# Форматы данных и CLI

Спецификация входных/выходных форматов, конфигурации и CLI-интерфейса.
Архитектура и пайплайн описаны в [projectdescription.md](../projectdescription.md),
алгоритмы — в [docs/processing.md](processing.md),
модели данных — в [docs/models.md](models.md).

## Входные данные

На вход подаётся путь к файлу с текстом на русском языке (с возможными латинскими
научными названиями). Загрузка выполняется через абстракцию `TextLoader`.

### TextLoader

```python
class TextLoader(Protocol):
    """Protocol for loading text from various file formats."""

    def supports(self, path: Path) -> bool:
        """Return True if this loader can handle the given file."""
        ...

    def load(self, path: Path) -> str:
        """Load and return plain text content from the file."""
        ...
```

Функция `load_text(path: Path) -> str` автоматически выбирает загрузчик по расширению.
Если формат не поддерживается — ошибка с понятным сообщением.

### Поддерживаемые форматы

| Формат | Расширение | Реализация | Статус |
|--------|-----------|------------|--------|
| Plain text | `.txt` | `PlainTextLoader` (UTF-8) | v0.1 (MVP) |
| EPUB | `.epub` | `EpubLoader` | планируется |
| PDF | `.pdf` | `PdfLoader` | планируется |

Требования к входному тексту: кодировка UTF-8 (предпочтительно), русский язык.

### Автоопределение кодировки

Если файл не является валидным UTF-8, `PlainTextLoader` использует
`charset-normalizer` для автоопределения кодировки (CP-1251, KOI8-R и др.
часты для русских текстов из старых источников). При неудачном
определении — фатальная ошибка с понятным сообщением,
рекомендующим конвертировать файл в UTF-8.

### Ограничения входных данных

Максимальный размер входного файла ограничен конфигурацией (`max_file_size_mb`).
По умолчанию: **2 МБ**. Проверка выполняется перед загрузкой: если файл
превышает лимит — фатальная ошибка с сообщением:

```
Error: Input file exceeds maximum size (2.0 MB). Current: 5.3 MB.
Adjust max_file_size_mb in configuration if needed.
```

Это критично для веб-бэкенда (защита от DoS).

## Выходные данные

Результат — JSON-файл. Формат зависит от режима вывода.

### Версионирование формата вывода

Выходной JSON обёрнут в envelope с полем `version`:

```json
{
  "version": "1.0",
  "results": [ ... ]
}
```

Поле `version` соответствует версии формата вывода (не версии приложения).
При изменении формата (breaking change) версия инкрементируется.
Потребители могут проверять `version` для обратной совместимости.

### Режимы вывода

| Режим | Флаг CLI | Описание |
|-------|---------|----------|
| **Дедуплицированный** (по умолчанию) | — | Одна запись на уникальный таксон с `count` и `occurrences` |
| **Полный** | `--all-occurrences` | Одна запись на каждое вхождение |

### Дедуплицированный формат (по умолчанию)

Массив объектов, каждый объект — уникальный таксон.

Обязательные поля:
- `source_text`: string — каноническая форма названия (из первого вхождения).
- `identified`: boolean (`true` | `false`).
- `extraction_confidence`: number (0.0–1.0).
- `extraction_method`: `"gazetteer"` | `"latin_regex"` | `"llm"`.
- `count`: integer — количество вхождений в тексте.
- `occurrences`: array — все вхождения:
  - `line_number`: integer (1-based).
  - `source_text`: string (как в оригинале).
  - `source_context`: string (предложение).
- `matches`: array (до 5) — результаты из iNaturalist.
- `candidate_names`: array[string] — опробованные варианты названий (пустой при identified=true).
- `reason`: string — диагностическое сообщение (пустая строка при identified=true).

Опциональные поля:
- `llm_response`: object | null — ответ LLM-обогатителя.

Поля `candidate_names` и `reason` всегда присутствуют (без conditional requirements) —
это упрощает схему и парсинг.

Поля каждого элемента `matches`:
- `taxon_id`: integer — id таксона в iNaturalist.
- `taxon_name`: string — научное (латинское) название.
- `taxon_rank`: string — таксономический ранг.
- `taxonomy`: object — таксономическая иерархия (kingdom, phylum, class, order, family, genus, species).
- `taxon_common_name_en`: string | null — английское народное название.
- `taxon_common_name_loc`: string | null — народное название для locale из конфига.
- `taxon_matched_name`: string — имя, по которому найден таксон.
- `taxon_url`: string — `https://www.inaturalist.org/taxa/{taxon_id}`.
- `score`: number — релевантность совпадения (score из iNaturalist API или синтетический для газеттера).

Пример:

```json
{
  "version": "1.0",
  "results": [
    {
      "source_text": "липа",
      "identified": true,
      "extraction_confidence": 1.0,
      "extraction_method": "gazetteer",
      "count": 3,
      "occurrences": [
        {
          "line_number": 10,
          "source_text": "липа",
          "source_context": "На перевале росла огромная липа."
        },
        {
          "line_number": 45,
          "source_text": "лип",
          "source_context": "Среди лип и дубов мы разбили лагерь."
        },
        {
          "line_number": 102,
          "source_text": "липы",
          "source_context": "Листья липы уже пожелтели."
        }
      ],
      "matches": [
        {
          "taxon_id": 54586,
          "taxon_name": "Tilia",
          "taxon_rank": "genus",
          "taxonomy": {
            "kingdom": "Plantae",
            "phylum": "Tracheophyta",
            "class": "Magnoliopsida",
            "order": "Malvales",
            "family": "Malvaceae",
            "genus": "Tilia",
            "species": null
          },
          "taxon_common_name_en": "Lindens",
          "taxon_common_name_loc": "Липа",
          "taxon_matched_name": "липа",
          "taxon_url": "https://www.inaturalist.org/taxa/54586",
          "score": 1.0
        }
      ],
      "candidate_names": [],
      "reason": "",
      "llm_response": null
    }
  ]
}
```

### Полный формат (`--all-occurrences`)

Массив объектов, каждый объект — одно вхождение.

Обязательные поля:
- `line_number`: integer (1-based).
- `source_text`: string.
- `source_context`: string.
- `identified`: boolean (`true` | `false`).
- `extraction_confidence`: number (0.0–1.0).
- `extraction_method`: `"gazetteer"` | `"latin_regex"` | `"llm"`.
- `matches`: array (до 5).
- `candidate_names`: array[string] — опробованные варианты названий (пустой при identified=true).
- `reason`: string — диагностическое сообщение (пустая строка при identified=true).

Опциональные поля:
- `llm_response`: object | null.

Пример:

```json
{
  "version": "1.0",
  "results": [
    {
      "line_number": 10,
      "source_text": "липа",
      "source_context": "На перевале росла огромная липа.",
      "identified": true,
      "extraction_confidence": 1.0,
      "extraction_method": "gazetteer",
      "matches": [
        {
          "taxon_id": 54586,
          "taxon_name": "Tilia",
          "taxon_rank": "genus",
          "taxonomy": {
            "kingdom": "Plantae",
            "phylum": "Tracheophyta",
            "class": "Magnoliopsida",
            "order": "Malvales",
            "family": "Malvaceae",
            "genus": "Tilia",
            "species": null
          },
          "taxon_common_name_en": "Lindens",
          "taxon_common_name_loc": "Липа",
          "taxon_matched_name": "липа",
          "taxon_url": "https://www.inaturalist.org/taxa/54586",
          "score": 1.0
        }
      ],
      "candidate_names": [],
      "reason": "",
      "llm_response": null
    }
  ]
}
```

JSON-схемы: `schemas/output-deduplicated.schema.json`,
`schemas/output-full.schema.json`.

## Конфигурация

Файл: `taxonfinder.config.json` (в текущей директории).
JSON-схема: `schemas/config.schema.json`.

### Основные поля

| Поле | Тип | Описание | По умолчанию |
|------|-----|----------|-------------|
| `confidence` | number | Минимальный порог `extraction_confidence` (0.0–1.0) | — (обязательное) |
| `locale` | string | Locale для iNaturalist API и шаблонизации промптов | — (обязательное) |
| `gazetteer_path` | string | Путь к SQLite-базе газеттера | `"data/gazetteer.db"` |
| `spacy_model` | string | Имя модели spaCy | `"ru_core_news_md"` |
| `max_file_size_mb` | number | Максимальный размер входного файла (МБ) | `2.0` |
| `degraded_mode` | boolean | Разрешить работу без газеттера (WARNING, но не фатальная ошибка) | `false` |
| `user_agent` | string | Значение заголовка User-Agent для HTTP-запросов | `"TaxonFinder/0.1.0"` |
| `llm_extractor` | object\|null | Настройки LLM-экстрактора (null = отключён) | null |
| `llm_enricher` | object\|null | Настройки LLM-обогатителя (null = отключён) | null |
| `inaturalist` | object | Настройки iNaturalist API | см. ниже |

### inaturalist

| Поле | Тип | Описание | По умолчанию |
|------|-----|----------|-------------|
| `base_url` | string | Базовый URL API (для proxy/mock в тестах) | `"https://api.inaturalist.org"` |
| `timeout` | number | Общий таймаут запроса (сек) | `30` |
| `rate_limit` | number | Устойчивый rate (запросов/сек) | `1.0` |
| `burst_limit` | integer | Максимальный burst | `5` |
| `max_retries` | integer | Максимум повторов при ошибках | `3` |
| `cache_enabled` | boolean | Включить disk-кэш | `true` |
| `cache_path` | string | Путь к SQLite-базе disk-кэша | `"cache/taxonfinder.db"` |
| `cache_ttl_days` | integer | TTL кэша (дни) | `7` |

### llm_extractor

| Поле | Тип | Описание | По умолчанию |
|------|-----|----------|-------------|
| `enabled` | boolean | Включён ли экстрактор | true |
| `provider` | string | `"ollama"`, `"openai"`, `"anthropic"` | — (обязательное) |
| `model` | string | Имя модели (напр. `"llama3.1"`, `"gpt-4o-mini"`) | — (обязательное) |
| `url` | string | URL подключения (для Ollama обязателен) | — |
| `timeout` | number | Таймаут в секундах | 60 |
| `prompt_file` | string | Путь к промпту | `"prompts/llm_extractor.txt"` |
| `chunk_strategy` | string | `"paragraph"` или `"page"` | `"paragraph"` |
| `min_chunk_words` | integer | Минимальный размер чанка (слов) | 50 |
| `max_chunk_words` | integer | Максимальный размер чанка (слов) | 500 |

### llm_enricher

| Поле | Тип | Описание | По умолчанию |
|------|-----|----------|-------------|
| `enabled` | boolean | Включён ли обогатитель | true |
| `provider` | string | `"ollama"`, `"openai"`, `"anthropic"` | — (обязательное) |
| `model` | string | Имя модели | — (обязательное) |
| `url` | string | URL подключения | — |
| `timeout` | number | Таймаут в секундах | 30 |
| `prompt_file` | string | Путь к промпту | `"prompts/llm_enricher.txt"` |

## Режим CLI

### Команды

```
taxonfinder process <input.txt> [output.json]
```

- `input.txt` — обязательный путь к входному файлу.
- `output.json` — опциональный; если не задан, вывод в stdout.
- `--config PATH` — путь к конфигурации (по умолчанию: `taxonfinder.config.json`).
- `--all-occurrences` — полный вывод (одна запись на вхождение, вместо
  дедуплицированного).

```
taxonfinder build-gazetteer --source csv --file <path.csv> --tag <tag> --locales <loc1,loc2>
```

Построение газеттера из CSV-контрольного списка iNaturalist.
См. [docs/processing.md§Построение газеттера](processing.md#построение-газеттера-builder) для подробностей.
- `--source csv` — стратегия построения (v0.1: только `csv`).
- `--file` — путь к CSV-файлу.
- `--tag` — тег для маркировки источника (например, `"russia"`).
- `--locales` — локали для загрузки common names (например, `ru,en`).
- `--config PATH` — путь к конфигурации.

```
taxonfinder dry-run <input.txt>
```

Предварительный анализ текста без обращения к API и LLM. Выводит:
- Общее число предложений в тексте.
- Число чанков для LLM-экстрактора (при текущей `chunk_strategy` и лимитах).
- Ожидаемое число LLM-вызовов (Фаза 1).
- Оценку числа уникальных кандидатов (на основе газеттера и regex — без LLM).
- Оценку числа запросов к iNaturalist API (Фаза 3).
- Оценку времени обработки.

`--config PATH` — используется для определения параметров чанкинга и включённых
экстракторов.

## Ограничения по iNaturalist API

- **Rate limit:** token bucket — 1 запрос/сек устойчивая нагрузка, burst до 5 запросов.
- **Retry:** при ошибках 429 (Too Many Requests) или 5xx — повтор до 3 раз
  с экспоненциальным backoff (3, 6, 12 секунд) и random jitter (50–100% от delay).
- **Таймауты:** подключение 5 сек, чтение 20 сек, общий лимит 30 сек.
- **Кэширование:** in-memory (обязательное) + disk (опциональное) снижают число
  реальных обращений.

## Обработка ошибок

- Фатальные ошибки (файл не найден, конфигурация невалидна, газеттер отсутствует
  при `degraded_mode: false`):
  ненулевой код выхода + сообщение в stderr.
- При `degraded_mode: true` отсутствие газеттера — WARNING в лог,
  пайплайн продолжает с доступными экстракторами (regex, LLM).
- Нефатальные (отдельный LLM-чанк вернул невалидный ответ, отдельный API-вызов
  завершился ошибкой после ретраев): WARNING в лог, элемент пропускается.

## Логи

Логирование — через `structlog`.

- **CLI-режим:** Human-readable formatter (цветной, ISO-8601 время, уровень, сообщение).
- **Production/Web:** JSON formatter (`LOG_FORMAT=json` или запуск через web-адаптер).
- Уровни: `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- Файл: `logs/taxonfinder.log` (создаётся автоматически).

## Управление секретами

API-ключи для LLM-провайдеров читаются из переменных окружения
или `.env` файла (через `python-dotenv`). **Никогда не хранятся
в конфигурационном файле.**

| Переменная | Назначение |
|------------|----------|
| `OPENAI_API_KEY` | Ключ для OpenAI API |
| `ANTHROPIC_API_KEY` | Ключ для Anthropic API |
| `LOG_FORMAT` | `json` для JSON-логов (production); по умолчанию human-readable |

## Примечания по обновлению файлов

Файлы, обновлённые в соответствии с этой документацией:
- `schemas/config.schema.json` — чанкинг, раздельные LLM-секции.
- `schemas/output-deduplicated.schema.json` — дедуплицированный формат (по умолчанию).
- `schemas/output-full.schema.json` — полный формат (--all-occurrences).
- `prompts/llm_extractor.txt`, `prompts/llm_enricher.txt` — промпты LLM.

Файлы, требующие обновления при дальнейшей разработке:
- `tests/data/*.json` — обновить фикстуры при изменении формата.
- `pyproject.toml` — добавить optional dependencies для epub, pdf загрузчиков.
