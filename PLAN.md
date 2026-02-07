# TaxonFinder — План реализации

## Текущее состояние

Готова проектная документация, JSON-схемы, промпты, конфигурация, `pyproject.toml`
и заглушки тестов с фикстурами. Кода пакета `taxonfinder/` ещё нет.

---

## Шаг 1. Фундамент: модели, конфигурация, нормализация

**Цель:** создать скелет пакета и все структуры данных, через которые проходит информация.
Модули этого шага не зависят от внешних сервисов и тестируются изолированно.

### Файлы

| Файл | Что реализуем |
|------|--------------|
| `taxonfinder/__init__.py` | Пустой, делает директорию пакетом |
| `taxonfinder/models.py` | Dataclasses: `Candidate`, `Occurrence`, `CandidateGroup`, `TaxonomyInfo`, `TaxonMatch`, `LlmEnrichmentResponse`, `ResolvedCandidate`, `TaxonResult` + `ExtractionMethod` (Literal) |
| `taxonfinder/events.py` | Dataclasses: `PhaseStarted`, `PhaseProgress`, `ResultReady`, `PipelineFinished`, `PipelineSummary`, `PipelineEstimate` + type alias `PipelineEvent` |
| `taxonfinder/config.py` | `Config` dataclass, `load_config(path) -> Config` — загрузка JSON, валидация через `jsonschema` по `schemas/config.schema.json`, `dotenv.load_dotenv()`, чтение API-ключей из `os.environ` |
| `taxonfinder/normalizer.py` | `normalize(text) -> str` (lowercase + ё→е), `lemmatize(text, morph) -> str` (pymorphy3 по токенам), `search_variants(text, morph) -> list[str]` — набор вариантов для поиска |
| `taxonfinder/logging.py` | `setup_logging(json_mode: bool)` — конфигурация structlog (human-readable / JSON) |
| `taxonfinder/rate_limiter.py` | `TokenBucketRateLimiter(rate, burst)` — thread-safe token bucket |

### Тесты

- `tests/test_models.py` — round-trip сериализация (`to_dict()` / `from_dict()`), проверка маппинга `class_` → `class` в JSON.
- `tests/test_config.py` — загрузка валидного конфига, отклонение невалидного.
- `tests/test_normalizer.py` — нормализация, лемматизация, корректность вариантов поиска.

### Рекомендации

- Все dataclasses — `frozen=True` (или `slots=True`) где возможно: предотвращает случайное изменение.
- `TaxonResult` и `TaxonMatch` — реализовать `to_dict()` для сериализации в JSON. Не использовать `dataclasses.asdict()` напрямую — он рекурсивно конвертирует, а нужен контроль над `class_` → `class`.
- `Config` — **не** frozen (может мутироваться при merge с CLI-аргументами).
- `normalize` / `lemmatize` — чистые функции, легко тестируются.
- pymorphy3 MorphAnalyzer создаётся один раз при старте, передаётся в функции. Не создавать внутри `normalize` — это дорого.

---

## Шаг 2. Загрузка текста и экстракция кандидатов (Фаза 1)

**Цель:** загрузить текст, прогнать через spaCy, извлечь кандидатов тремя методами.

### Файлы

| Файл | Что реализуем |
|------|--------------|
| `taxonfinder/loaders/__init__.py` | `load_text(path: Path) -> str` — автовыбор загрузчика |
| `taxonfinder/loaders/base.py` | `TextLoader` Protocol |
| `taxonfinder/loaders/plain_text.py` | `PlainTextLoader` — UTF-8 с fallback на charset-normalizer, проверка `max_file_size_mb` |
| `taxonfinder/extractors/__init__.py` | Реэкспорт экстракторов |
| `taxonfinder/extractors/gazetteer.py` | `GazetteerExtractor` — загрузка PhraseMatcher из SQLite, метод `extract(doc) -> list[Candidate]` |
| `taxonfinder/extractors/latin.py` | `LatinRegexExtractor` — regex + эвристические фильтры, метод `extract(doc) -> list[Candidate]` |
| `taxonfinder/extractors/llm_extractor.py` | `LlmExtractorPhase` — чанкинг текста, отправка в LLM, парсинг JSON, метод `extract(text, doc) -> list[Candidate]` |
| `taxonfinder/extractors/llm_client.py` | Protocol `LlmClient` + реализации: `OllamaClient`, `OpenAIClient`, `AnthropicClient` |

### Газеттер (SQLite)

| Файл | Что реализуем |
|------|--------------|
| `taxonfinder/gazetteer/__init__.py` | Реэкспорт |
| `taxonfinder/gazetteer/storage.py` | `GazetteerStorage` — чтение SQLite: `get_taxon_ids(name_normalized)`, `get_full_record(taxon_id)`, проверка `PRAGMA user_version` |
| `taxonfinder/gazetteer/builder.py` | CLI-утилита для заполнения SQLite из CSV + iNaturalist API (ThreadPoolExecutor + rate limiter, resume, graceful shutdown) |

### Тесты

- `tests/test_loaders.py` — загрузка txt, проверка отклонения файлов > лимита.
- `tests/test_latin_extractor.py` — regex + фильтры: стоп-лист, контекстная эвристика, минимальная длина.
- `tests/test_llm_client.py` — mock-тесты с подставным HTTP-ответом.
- `tests/test_gazetteer_storage.py` — тесты на in-memory SQLite.

### Рекомендации

- `GazetteerExtractor` загружает PhraseMatcher **один раз** при инициализации. Метод `extract()` — быстрый проход по doc.
- `LlmClient` — реализации максимально тонкие: только HTTP-запрос + парсинг ответа. Вся логика retry, JSON cleanup — в `llm_extractor.py` / `llm_enricher.py`.
- Чанкинг (`paragraph` / `page`) — отдельная чистая функция `chunk_text(text, doc, strategy, min_words, max_words) -> list[str]`, тестируется отдельно.
- Builder — **можно отложить** до получения рабочего пайплайна. На первое время создать маленькую тестовую SQLite-базу из 5–10 таксонов скриптом.

---

## Шаг 3. Merge, дедупликация и разрешение (Фазы 2–3)

**Цель:** объединить кандидатов, сгруппировать, разрешить через iNaturalist API.

### Файлы

| Файл | Что реализуем |
|------|--------------|
| `taxonfinder/resolvers/__init__.py` | Реэкспорт |
| `taxonfinder/resolvers/base.py` | Protocols: `TaxonSearcher`, `IdentificationResolver` |
| `taxonfinder/resolvers/inaturalist.py` | `INaturalistSearcher` — httpx.Client, endpoint `/v1/taxa/autocomplete`, парсинг ответа в `list[TaxonMatch]`, `TaxonomyInfo` из ancestry |
| `taxonfinder/resolvers/identifier.py` | `DefaultIdentificationResolver` — сравнение normalized/lemmatized форм, определение `identified` и `reason` |
| `taxonfinder/resolvers/cache.py` | `DiskCache` — SQLite (`cache/taxonfinder.db`), `get(query, locale)`, `put(query, locale, response_json)`, TTL-проверка |
| `taxonfinder/pipeline.py` (частично) | Функции merge/dedup: `merge_candidates(candidates_lists) -> list[CandidateGroup]`, логика перекрытий spans, группировка по лемме, проверка пересечения `gazetteer_taxon_ids` |

### Тесты

- `tests/test_merge.py` — перекрытие spans, приоритеты, группировка по леммам, условие пересечения `gazetteer_taxon_ids`.
- `tests/test_identifier.py` — сценарии identified=true/false, все значения reason.
- `tests/test_inaturalist.py` — mock httpx, парсинг реального JSON-ответа iNaturalist (фикстура).
- `tests/test_cache.py` — put/get, TTL expiry, schema version check.

### Рекомендации

- `INaturalistSearcher` — принимает `httpx.Client` и `RateLimiter` через конструктор (DI). Это позволяет мокировать в тестах.
- Merge-логику оформить как чистые функции (не внутри `pipeline.py`), вынести в отдельный модуль если будет расти, либо в `pipeline.py` приватными функциями.
- Для тестов `test_inaturalist.py` — сохранить реальный JSON-ответ iNaturalist API (1 запрос) как фикстуру `tests/data/inat_autocomplete_sample.json`.

---

## Шаг 4. LLM-обогащение и Checkpoint (Фаза 4)

**Цель:** обогатить неразрешённых кандидатов через LLM, реализовать checkpoint.

### Файлы

| Файл | Что реализуем |
|------|--------------|
| `taxonfinder/extractors/llm_enricher.py` | `LlmEnricherPhase` — формирование расширенного контекста (±1 предложение), шаблонизация промпта, отправка в LLM, парсинг `LlmEnrichmentResponse`, повторный поиск через `TaxonSearcher` |
| `taxonfinder/checkpoint.py` | `FileCheckpoint` — save/load JSON, идентификация по `sha256(text + config)`, cleanup после завершения |

### Тесты

- `tests/test_llm_enricher.py` — mock LLM, проверка формирования контекста, fallback на невалидный JSON.
- `tests/test_checkpoint.py` — round-trip save/load, проверка hash-идентификации, cleanup.

### Рекомендации

- Расширенный контекст (±1 предложение) — вычислять через `doc.sents`, не хранить в модели.
- Шаблонизация промпта: простая `str.replace("{{locale}}", config.locale)`.
- Checkpoint сериализует dataclasses в JSON. Реализовать `to_dict()` / `from_dict()` на моделях заранее (шаг 1).

---

## Шаг 5. Пайплайн-оркестратор и сборка результата (Фазы 1–5)

**Цель:** собрать весь пайплайн в генератор `process()`, реализовать сборку `TaxonResult`, вывод JSON с envelope.

### Файлы

| Файл | Что реализуем |
|------|--------------|
| `taxonfinder/pipeline.py` (полностью) | `process(text, config, **deps) -> Iterator[PipelineEvent]`, `process_all(text, config) -> list[TaxonResult]`, `estimate(text, config) -> PipelineEstimate` |
| `taxonfinder/pipeline.py` (в нём же) | Фаза 5: сборка `TaxonResult` из `ResolvedCandidate`, фильтрация по `confidence`, формирование JSON-envelope `{"version": "1.0", "results": [...]}` |

### Тесты

- `tests/test_pipeline.py` — интеграционный тест: маленький текст + mock searcher/llm → проверка потока событий и итогового JSON.
- `tests/test_first_case.py` — существующие тесты на фикстурах (уже готовы).

### Рекомендации

- Пайплайн — тонкий оркестратор. Вся логика — в экстракторах, merge, resolvers. `pipeline.py` только вызывает их в нужном порядке и yield'ит события.
- `GeneratorExit` — обработать корректно: закрыть httpx.Client, сохранить checkpoint.
- Timing: замерять `time.monotonic()` для каждой фазы, складывать в `PipelineSummary.phase_times`.
- JSON-вывод: две функции — `format_deduplicated(results) -> dict` и `format_full(results) -> dict`.

---

## Шаг 6. CLI и интеграция

**Цель:** CLI-интерфейс, прогресс-бар, команды `process`, `build-gazetteer`, `dry-run`.

### Файлы

| Файл | Что реализуем |
|------|--------------|
| `taxonfinder/cli.py` | Click-группа с командами: `process`, `build-gazetteer`, `dry-run`. Подписка на `PhaseProgress` для прогресс-бара. Обработка SIGINT → `generator.close()`. |

### Тесты

- `tests/test_cli.py` — CLI через `click.testing.CliRunner`, проверка exit codes, формата вывода.

### Рекомендации

- `CliRunner` позволяет тестировать CLI без реального запуска процесса.
- Прогресс-бар: `click.progressbar` или простой вывод `Phase [extraction] 15/42`.
- При `--all-occurrences` — переключить формат вывода.
- Stderr для прогресса и логов, stdout для JSON (если `output.json` не задан).

---

## Шаг 7. Builder газеттера и end-to-end тесты

**Цель:** полноценный builder газеттера, E2E тесты на реальных данных.

### Файлы

| Файл | Что реализуем |
|------|--------------|
| `taxonfinder/gazetteer/builder.py` (полностью) | Парсинг CSV, запросы к iNaturalist API (ThreadPoolExecutor, 5 workers), rate limiter, resume, graceful shutdown (SIGINT), прогресс |
| `tests/test_builder.py` | Тесты с мини-CSV (3–5 строк) + mock iNaturalist |

### E2E тесты

- `tests/test_e2e.py` — загрузка маленького txt → process → проверка JSON-схемой (`jsonschema.validate` по `schemas/output-deduplicated.schema.json`).

---

## Рекомендуемый порядок работы

```
Шаг 1 (фундамент)
    ↓
Шаг 2 (экстракторы) ← можно начать параллельно latin.py + loaders
    ↓
Шаг 3 (merge + resolvers)
    ↓
Шаг 5 (pipeline) ← минимальный рабочий пайплайн без LLM и checkpoint
    ↓
Шаг 6 (CLI) ← первый запуск на реальном тексте
    ↓
Шаг 4 (LLM-обогащение + checkpoint)
    ↓
Шаг 7 (builder + E2E)
```

> **Note:** Шаги 4 и 7 можно отложить. Минимально рабочий пайплайн (regex +
> газеттер из тестовой БД → iNaturalist → JSON) достигается на шагах 1–3 + 5–6.

---

## Best Practices для работы с AI-агентом

### 1. Инкрементальная реализация с тестами

Каждый шаг заканчивается запуском тестов. Не переходить к следующему шагу, пока
тесты текущего не проходят. AI-агент должен:
- Создавать модуль → писать тесты → запускать → фиксить → двигаться дальше.

### 2. Контракт-first разработка

Документация (models.md, processing.md) — это контракт. При реализации сверяться
с документацией. Если реализация расходится с документацией — обновить документацию,
а не молча отступить.

### 3. Тестовые фикстуры как золотой стандарт

Файлы `tests/data/` — ожидаемые результаты. При изменении моделей — обновлять фикстуры
синхронно. Не оставлять расхождений между кодом и фикстурами.

### 4. Маленькая тестовая БД газеттера

До реализации полного builder'а создать скриптом миниатюрную SQLite-базу с 5–10
таксонами (липа, дуб, берёза, Tilia cordata, Quercus robur) для тестирования
газеттера. Файл: `tests/data/test_gazetteer.db`.

### 5. Mock внешних сервисов

- iNaturalist — mock через `httpx.MockTransport` или фикстуры с реальными ответами.
- LLM — mock `LlmClient`, возвращающий фиксированный JSON.
- Не делать реальных HTTP-запросов в unit-тестах.

### 6. Один модуль = одна ответственность

Не складывать логику в `pipeline.py`. Pipeline — оркестратор. Вся бизнес-логика —
в extractors, resolvers, normalizer. Это упрощает тестирование и замену компонентов.

### 7. Type hints и ruff

Весь код — с type hints. Запускать `ruff check` после каждого модуля.
`pyproject.toml` уже настроен (Python 3.11+, line-length 100).

---

## Итого: структура пакета после реализации

```
taxonfinder/
  __init__.py
  cli.py
  config.py
  pipeline.py
  events.py
  logging.py
  rate_limiter.py
  checkpoint.py
  normalizer.py
  models.py
  loaders/
    __init__.py
    base.py
    plain_text.py
  extractors/
    __init__.py
    gazetteer.py
    latin.py
    llm_extractor.py
    llm_enricher.py
    llm_client.py
  resolvers/
    __init__.py
    base.py
    inaturalist.py
    identifier.py
    cache.py
  gazetteer/
    __init__.py
    builder.py
    storage.py
```
