# Форматы данных и CLI

Спецификация входных/выходных форматов, конфигурации и CLI-интерфейса.
Архитектура и пайплайн описаны в [projectdescription.md](../projectdescription.md),
алгоритмы — в [docs/processing.md](processing.md).

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

Требования к входному тексту: кодировка UTF-8, русский язык.

## Выходные данные

Результат — JSON-файл. Формат зависит от режима вывода.

### Режимы вывода

| Режим | Флаг CLI | Описание |
|-------|---------|----------|
| **Дедуплицированный** (по умолчанию) | — | Одна запись на уникальный таксон с `count` и `occurrences` |
| **Полный** | `--all-occurrences` | Одна запись на каждое вхождение |

### Дедуплицированный формат (по умолчанию)

Массив объектов, каждый объект — уникальный таксон.

Обязательные поля:
- `source_text`: string — каноническая форма названия (из первого вхождения).
- `identified`: `"yes"` | `"no"`.
- `extraction_confidence`: number (0.0–1.0).
- `extraction_method`: `"gazetteer"` | `"latin_regex"` | `"llm"`.
- `count`: integer — количество вхождений в тексте.
- `occurrences`: array — все вхождения:
  - `line_number`: integer (1-based).
  - `source_text`: string (как в оригинале).
  - `source_context`: string (предложение).
- `matches`: array (до 5) — результаты из iNaturalist.

Опциональные поля:
- `llm_response`: object | null — ответ LLM-обогатителя.

Обязательные при `identified: "no"`:
- `candidate_names`: array[string].
- `reason`: string.

Поля каждого элемента `matches`:
- `taxon_id`: integer — id таксона в iNaturalist.
- `taxon_name`: string — научное (латинское) название.
- `taxon_rank`: string — таксономический ранг.
- `taxon_common_name`: string | null — предпочитаемое общее имя.
- `taxon_matched_name`: string — имя, по которому найден таксон.
- `taxon_url`: string — `https://www.inaturalist.org/taxa/{taxon_id}`.

Пример:

```json
[
  {
    "source_text": "липа",
    "identified": "yes",
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
        "taxon_common_name": "Linden",
        "taxon_matched_name": "липа",
        "taxon_url": "https://www.inaturalist.org/taxa/54586"
      }
    ],
    "llm_response": null
  }
]
```

### Полный формат (`--all-occurrences`)

Массив объектов, каждый объект — одно вхождение.

Обязательные поля:
- `line_number`: integer (1-based).
- `source_text`: string.
- `source_context`: string.
- `identified`: `"yes"` | `"no"`.
- `extraction_confidence`: number (0.0–1.0).
- `extraction_method`: `"gazetteer"` | `"latin_regex"` | `"llm"`.
- `matches`: array (до 5).

Опциональные поля:
- `llm_response`: object | null.

Обязательные при `identified: "no"`:
- `candidate_names`: array[string].
- `reason`: string.

Пример:

```json
[
  {
    "line_number": 10,
    "source_text": "липа",
    "source_context": "На перевале росла огромная липа.",
    "identified": "yes",
    "extraction_confidence": 1.0,
    "extraction_method": "gazetteer",
    "matches": [
      {
        "taxon_id": 54586,
        "taxon_name": "Tilia",
        "taxon_rank": "genus",
        "taxon_common_name": "Linden",
        "taxon_matched_name": "липа",
        "taxon_url": "https://www.inaturalist.org/taxa/54586"
      }
    ],
    "llm_response": null
  }
]
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
| `locale` | string | Locale для iNaturalist API | — (обязательное) |
| `gazetteer_path` | string | Путь к SQLite-базе газеттера | `"data/gazetteer.db"` |
| `llm_extractor` | object\|null | Настройки LLM-экстрактора (null = отключён) | null |
| `llm_enricher` | object\|null | Настройки LLM-обогатителя (null = отключён) | null |

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
taxonfinder build-gazetteer
```

Построение газеттера из iNaturalist API.

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
  с экспоненциальным backoff (3, 6, 12 секунд).
- **Таймауты:** подключение 5 сек, чтение 20 сек, общий лимит 30 сек.
- **Кэширование:** in-memory (обязательное) + disk (опциональное) снижают число
  реальных обращений.

## Обработка ошибок

- Фатальные ошибки (файл не найден, конфигурация невалидна, газеттер отсутствует):
  ненулевой код выхода + сообщение в stderr.
- Нефатальные (отдельный LLM-чанк вернул невалидный ответ, отдельный API-вызов
  завершился ошибкой после ретраев): WARNING в лог, элемент пропускается.

## Логи CLI

- Формат: текстовые строки с ISO-8601 временем, уровнем и сообщением.
- Уровни: `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- Файл: `logs/taxonfinder.log` (создаётся автоматически).

## Примечания по обновлению файлов

Файлы, обновлённые в соответствии с этой документацией:
- `schemas/config.schema.json` — чанкинг, раздельные LLM-секции.
- `schemas/output-deduplicated.schema.json` — дедуплицированный формат (по умолчанию).
- `schemas/output-full.schema.json` — полный формат (--all-occurrences).
- `prompts/llm_extractor.txt`, `prompts/llm_enricher.txt` — промпты LLM.

Файлы, требующие обновления при дальнейшей разработке:
- `tests/data/*.json` — обновить фикстуры при изменении формата.
- `pyproject.toml` — добавить optional dependencies для epub, pdf загрузчиков.
