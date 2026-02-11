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
      "extraction_method": "dictionary",
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
      "extraction_method": "dictionary",
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
| `locale` | string | Locale для выбора языка обработки и локализованных промптов | — (обязательное) |
| `data_source` | string | `"inaturalist"` (online) или `"noo_garden"` (offline) | — (обязательное) |
| `spacy_model` | string | Имя модели spaCy для выбранного языка | — (обязательное) |
| `max_file_size_mb` | number | Максимальный размер входного файла (МБ) | `2.0` |
| `user_agent` | string | Значение заголовка User-Agent для HTTP-запросов | `"TaxonFinder/0.1.0"` |
| `llm_extractor` | object\|null | Настройки LLM-экстрактора (null = отключён) | null |
| `llm_enricher` | object\|null | Настройки LLM-обогатителя (null = отключён) | null |
| `inaturalist` | object | Настройки iNaturalist API (только для online режима) | см. ниже |
| `noo_garden` | object | Настройки PostgreSQL noo-garden (только для offline режима) | см. ниже |

### inaturalist (только data_source: "inaturalist")

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

### noo_garden (только data_source: "noo_garden")

| Поле | Тип | Описание | По умолчанию |
|------|-----|----------|-------------|
| `host` | string | Хост PostgreSQL | `"localhost"` |
| `port` | integer | Порт PostgreSQL | `5432` |
| `database` | string | Имя базы данных | `"noo_garden"` |
| `user` | string | Пользователь PostgreSQL | `"postgres"` |
| `password` | string | Пароль (поддерживает `${ENV_VAR}`) | — (обязательное) |
| `schema` | string | Схема PostgreSQL | `"public"` |

**Примечание:** Пароль должен быть задан через переменную окружения. Пример:
```json
"noo_garden": {
  "host": "localhost",
  "port": 5432,
  "database": "noo_garden",
  "user": "postgres",
  "password": "${POSTGRES_PASSWORD}",
  "schema": "public"
}
```

### llm_extractor

| Поле | Тип | Описание | По умолчанию |
|------|-----|----------|-------------|
| `enabled` | boolean | Включён ли экстрактор | true |
| `provider` | string | `"ollama"`, `"openai"`, `"anthropic"` | — (обязательно при `enabled: true`) |
| `model` | string | Имя модели (напр. `"llama3.1"`, `"gpt-4o-mini"`) | — (обязательно при `enabled: true`) |
| `url` | string | URL подключения (для Ollama обязателен) | — |
| `timeout` | number | Таймаут в секундах | 60 |
| `prompt_file` | string | Путь к промпту (базовый файл, локализованные версии ищутся автоматически) | `"prompts/llm_extractor.txt"` |
| `chunk_strategy` | string | `"paragraph"` или `"page"` | `"paragraph"` |
| `min_chunk_words` | integer | Минимальный размер чанка (слов) | 50 |
| `max_chunk_words` | integer | Максимальный размер чанка (слов) | 500 |

**Отключение LLM-экстрактора:** Чтобы использовать только газеттер и regex-детектор латинских названий, 
установите `"enabled": false`. В этом случае поля `provider` и `model` необязательны:

```json
"llm_extractor": {
  "enabled": false
}
```

### llm_enricher

| Поле | Тип | Описание | По умолчанию |
|------|-----|----------|-------------|
| `enabled` | boolean | Включён ли обогатитель | true |
| `provider` | string | `"ollama"`, `"openai"`, `"anthropic"` | — (обязательно при `enabled: true`) |
| `model` | string | Имя модели | — (обязательно при `enabled: true`) |
| `url` | string | URL подключения | — |
| `timeout` | number | Таймаут в секундах | 30 |
| `prompt_file` | string | Путь к промпту (базовый файл, локализованные версии ищутся автоматически) | `"prompts/llm_enricher.txt"` |

**Отключение LLM-обогатителя:** Если не нужна Фаза 4 (обогащение неразрешённых кандидатов через LLM), 
установите `"enabled": false`. В этом случае поля `provider` и `model` необязательны:

```json
"llm_enricher": {
  "enabled": false
}
```

**Полное отключение LLM:** Для работы только с газеттером и regex (без использования LLM вообще), 
отключите оба компонента. См. пример конфигурации: `taxonfinder.no-llm.config.json`.

#### Локализация промптов

Система автоматически ищет локализованные версии промптов на основе значения `locale` в конфигурации. 
Если указан `prompt_file = "prompts/llm_extractor.txt"` и `locale = "ru"`, система сначала попытается 
загрузить `prompts/llm_extractor.ru.txt`. Если локализованный файл не найден, используется базовый 
файл без суффикса локали.

Формат имени локализованного промпта: `<basename>.<locale><extension>`

Примеры:
- `locale: "ru"` → `llm_extractor.ru.txt` (если существует), иначе `llm_extractor.txt`
- `locale: "en"` → `llm_extractor.en.txt` (если существует), иначе `llm_extractor.txt`

Это позволяет создавать специфичные для языка промпты, которые лучше работают с LLM для 
соответствующего языка текста.

### logging

| Поле | Тип | Описание | По умолчанию |
|------|-----|----------|-------------|
| `console_level` | string | Уровень логирования для консоли (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `"INFO"` |
| `file_level` | string | Уровень логирования для файла (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `"DEBUG"` |
| `log_file` | string | Путь к файлу логов | `"logs/taxonfinder.log"` |

**Примечание:** CLI-параметры логирования (`--console-log-level`, `--file-log-level`, `--log-file`) 
переопределяют значения из конфигурации. Это общее правило для всего приложения: CLI имеет приоритет 
над конфигурационным файлом.

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
taxonfinder dry-run <input.txt>
```

Предварительный анализ текста без обращения к источникам данных и LLM. Выводит:
- Общее число предложений в тексте.
- Число чанков для LLM-экстрактора (при текущей `chunk_strategy` и лимитах).
- Ожидаемое число LLM-вызовов (Фаза 1).
- Оценку числа уникальных кандидатов (на основе dictionary matching и regex — без LLM).
- Оценку числа запросов к источнику данных (Фаза 3).
- Оценку времени обработки.

`--config PATH` — используется для определения параметров чанкинга и включённых
экстракторов.

## Ограничения источников данных

### Online режим (iNaturalist API)

- **Rate limit:** token bucket — 1 запрос/сек устойчивая нагрузка, burst до 5 запросов.
- **Retry:** при ошибках 429 (Too Many Requests) или 5xx — повтор до 3 раз
  с экспоненциальным backoff (3, 6, 12 секунд) и random jitter (50–100% от delay).
- **Таймауты:** подключение 5 сек, чтение 20 сек, общий лимит 30 сек.
- **Кэширование:** in-memory (обязательное) + disk (опциональное) снижают число
  реальных обращений.

### Offline режим (noo-garden PostgreSQL)

- **Производительность:** зависит от индексов в базе noo-garden. См. рекомендации
  по оптимизации в [projectdescription.md](../projectdescription.md).
- **Подключение:** используется connection pool для эффективного использования
  соединений с PostgreSQL.
- **Timeout:** по умолчанию 30 секунд на запрос.

## Обработка ошибок

- Фатальные ошибки (файл не найден, конфигурация невалидна, недоступен источник данных):
  ненулевой код выхода + сообщение в stderr.
- При недоступности offline источника (noo-garden) — фатальная ошибка.
- При недоступности online источника (iNaturalist API) — попытка retry, затем ошибка.
- Нефатальные (отдельный LLM-чанк вернул невалидный ответ, отдельный API-вызов
  завершился ошибкой после ретраев): WARNING в лог, элемент пропускается.

## Логи

Логирование — через `structlog` с поддержкой вывода в консоль и файл.

### Конфигурация логирования

Логирование настраивается тремя способами (в порядке приоритета):
1. **CLI-параметры** (наивысший приоритет) — переопределяют все остальные настройки
2. **Конфигурационный файл** (секция `logging`) — используется если CLI-параметры не заданы
3. **Переменная окружения `LOG_FORMAT`** — включает JSON-формат для консоли

**Общее правило:** CLI-параметры всегда имеют приоритет над конфигурационным файлом.

#### CLI-параметры

| Параметр | Значение по умолчанию | Описание |
|----------|----------------------|----------|
| `--console-log-level` | Из конфига (`INFO`) | Уровень логирования для консоли. Переопределяет `logging.console_level` из конфига. |
| `--file-log-level` | Из конфига (`DEBUG`) | Уровень логирования для файла. Переопределяет `logging.file_level` из конфига. |
| `--log-file` | Из конфига (`logs/taxonfinder.log`) | Путь к файлу логов. Переопределяет `logging.log_file` из конфига. |
| `--json-logs` | `false` | Использовать JSON-формат для консольного вывода (флаг) |

#### Переменная окружения

| Переменная | Значение | Эффект |
|------------|----------|--------|
| `LOG_FORMAT` | `json` | Включает JSON-формат для консоли (эквивалентно `--json-logs`) |

### Форматы вывода

- **Консоль (CLI-режим):** Human-readable formatter (цветной, ISO-8601 время, уровень, сообщение). 
  При `--json-logs` или `LOG_FORMAT=json` — JSON-формат.
- **Файл:** Всегда JSON-формат для удобства парсинга и анализа.

### Файл логов

- **Расположение:** `logs/taxonfinder.log` (по умолчанию, настраивается через `--log-file`)
- **Ротация:** Автоматическая ротация при достижении 10 МБ, сохраняется до 5 backup-файлов
- **Кодировка:** UTF-8
- **Создание:** Директория создаётся автоматически при первом запуске

### Уровни логирования

| Уровень | Назначение |
|---------|-----------|
| `DEBUG` | Детальная диагностическая информация (HTTP-запросы, кэш hits/misses, парсинг промптов) |
| `INFO` | Основные события (начало/завершение фаз, статистика обработки) |
| `WARNING` | Нефатальные проблемы (невалидный LLM-ответ, fallback на другой метод, degraded mode) |
| `ERROR` | Фатальные ошибки (файл не найден, невалидная конфигурация) |

### Примеры использования

**Настройка через конфигурационный файл:**
```json
{
  "confidence": 0.6,
  "locale": "ru",
  "logging": {
    "console_level": "WARNING",
    "file_level": "DEBUG",
    "log_file": "logs/my_app.log"
  }
}
```

**Разработка (детальные логи в файле, минимум в консоли):**
```bash
taxonfinder --console-log-level WARNING --file-log-level DEBUG process input.txt
```

**Production (JSON-формат, минимум шума):**
```bash
export LOG_FORMAT=json
taxonfinder --console-log-level ERROR --file-log-level INFO process input.txt
```

**Отладка (всё в консоли):**
```bash
taxonfinder --console-log-level DEBUG process input.txt
```

**Использование настроек из конфига (без CLI-параметров):**
```bash
# Логирование настроено в taxonfinder.config.json
taxonfinder process input.txt
```

**Переопределение одного параметра из конфига:**
```bash
# Использовать console_level и log_file из конфига, но изменить file_level
taxonfinder --file-log-level INFO process input.txt
```

**Пользовательский путь к логам:**
```bash
taxonfinder --log-file /var/log/taxonfinder/app.log process input.txt
```

## Управление секретами

API-ключи и пароли баз данных читаются из переменных окружения
или `.env` файла (через `python-dotenv`). **Никогда не хранятся
в конфигурационном файле.**

| Переменная | Назначение |
|------------|----------|
| `OPENAI_API_KEY` | Ключ для OpenAI API |
| `ANTHROPIC_API_KEY` | Ключ для Anthropic API |
| `POSTGRES_PASSWORD` | Пароль для PostgreSQL noo-garden (offline режим) |
| `LOG_FORMAT` | `json` для JSON-логов (production); по умолчанию human-readable |

## Примечания по обновлению файлов

Файлы, обновлённые в соответствии с этой документацией:
- `schemas/config.schema.json` — чанкинг, раздельные LLM-секции.
- `schemas/output-deduplicated.schema.json` — дедуплицированный формат (по умолчанию).
- `schemas/output-full.schema.json` — полный формат (--all-occurrences).
- `prompts/llm_extractor.txt`, `prompts/llm_enricher.txt` — базовые промпты LLM (fallback).
- `prompts/llm_extractor.ru.txt`, `prompts/llm_enricher.ru.txt` — русские локализованные промпты.

Файлы, требующие обновления при дальнейшей разработке:
- `tests/data/*.json` — обновить фикстуры при изменении формата.
- `pyproject.toml` — добавить optional dependencies для epub, pdf загрузчиков.
