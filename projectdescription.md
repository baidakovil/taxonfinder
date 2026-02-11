## Описание проекта

Приложение для извлечения названий таксонов (растений, животных, грибов и т.д.) из текстов
на естественных языках. На вход подаётся текст книги, на выходе — JSON-файл со списком 
обнаруженных таксонов, их латинскими названиями и ссылками на iNaturalist.

Целевой сценарий: натуралист читает книгу о природе и хочет получить полный список
упомянутых организмов с возможностью перехода на iNaturalist.org.

**Поддержка языков:** Приложение разработано с расчётом на работу с текстами на любом
естественном языке. Язык текста указывается в конфигурации (параметр `locale`), что
определяет модель spaCy для токенизации, лемматизатор и язык народных названий для поиска.

## Технический стек

### Режимы работы

Приложение поддерживает два режима работы, определяемых параметром `data_source` в конфигурации:

1. **Online режим** (`data_source: "inaturalist"`): все запросы выполняются через iNaturalist API.
   Подходит для обработки небольших текстов, не требует локальной базы данных.

2. **Offline режим** (`data_source: "noo_garden"`): использует локальную PostgreSQL базу noo-garden, 
   содержащую ~1.4M таксонов и все народные названия из iNaturalist. Поддерживает полностью офлайн
   работу без обращений к API. Подходит для обработки больших текстов и сценариев без доступа к сети.

### Извлечение названий таксонов

Гибридный подход из трёх методов:

1. **Dictionary matching** — основной метод для народных названий. В зависимости от режима:
   - **Online:** названия загружаются через iNaturalist API и кэшируются локально
   - **Offline:** прямые запросы к PostgreSQL базе noo-garden с полнотекстовым поиском
   
   Даёт предсказуемый recall для известных названий. Использует spaCy для токенизации и сегментации.

2. **Regex-детектор латинских биномиалов** (опциональный) — отдельный проход для научных латинских
   названий вида *Tilia cordata*, *Quercus robur*. Не зависит от словаря, работает как fallback для
   видов, отсутствующих в базе, или при опечатках. В offline режиме может быть отключен (если база
   noo-garden всегда актуальна). Включается параметром `enable_regex_extractor` в конфигурации.
   
   Альтернатива regex в offline режиме: **fuzzy matching через PostgreSQL pg_trgm** — находит латинские
   названия с опечатками (например, "Tila cordata" → "Tilia cordata") через индекс сходства.

3. **LLM** — используется в двух независимых ролях (каждая включается/отключается отдельно):
   - **LLM-экстрактор** (Фаза 1): получает чанки текста и извлекает названия организмов,
     не пойманные dictionary matching и regex.
   - **LLM-обогатитель** (Фаза 4): подбирает альтернативные названия для кандидатов,
     не разрешённых через основной источник данных.

### Верификация данных

В **online режиме** iNaturalist API является финальным источником истины: все кандидаты 
проверяются через API.

В **offline режиме** noo-garden база данных содержит все необходимые данные (таксономия, 
народные названия, идентификаторы таксонов), обращение к API не требуется.

### Основные зависимости

| Зависимость | Назначение |
|-------------|-----------|
| **spaCy** | Токенизация, сегментация на предложения (`doc.sents`). Модель определяется параметром `spacy_model` в конфигурации (например, `ru_core_news_md` для русского языка, `en_core_web_md` для английского) |
| **pymorphy3** | Лемматизация слов (для языков с богатой морфологией, прежде всего русского). Дополняет spaCy для корректной морфологии |
| **httpx** | HTTP-клиент для iNaturalist API (online режим) и LLM-провайдеров (единый клиент для sync I/O) |
| **psycopg** | PostgreSQL драйвер для работы с noo-garden базой данных (offline режим) |
| **jsonschema** | Валидация конфигурации |
| **click** | CLI-интерфейс |
| **structlog** | Structured logging (JSON в production, human-readable в CLI) |
| **python-dotenv** | Загрузка секретов (API-ключей, пароля БД) из `.env` файла |
| **charset-normalizer** | Автоопределение кодировки входного файла (fallback при не-UTF-8) |

LLM работает через Ollama (local) или через API облачных провайдеров (OpenAI, Anthropic). 
Для каждой роли LLM можно задать свою модель и провайдера.

В **online режиме** взаимодействие с iNaturalist API выполняется напрямую через httpx 
(эндпоинты `/v1/taxa/autocomplete`, `/v1/taxa/{id}` и др.). Библиотека-обёртка 
pyinaturalist не используется.

В **offline режиме** используется прямое подключение к PostgreSQL через psycopg.
noo-garden база данных должна быть развёрнута и доступна локально или по сети.

## Архитектура

### Модули

Код организован как Python-пакет с чётким разделением ответственности. Ядро пайплайна
не зависит от CLI или веб-фреймворка, что позволяет использовать его как backend
для Flask/FastAPI.

```
taxonfinder/
  __init__.py
  cli.py                # CLI entry point (Click)
  config.py             # Загрузка и валидация конфигурации
  pipeline.py           # Оркестрация: sync-генератор PipelineEvent
  events.py             # Dataclasses для PipelineEvent, PipelineSummary
  logging.py            # Настройка structlog (JSON / human-readable)
  rate_limiter.py       # Token-bucket rate limiter для HTTP-запросов
  checkpoint.py         # Сохранение/загрузка промежуточного состояния
  loaders/
    __init__.py         # load_text() — автовыбор загрузчика по расширению
    base.py             # TextLoader Protocol
    plain_text.py       # PlainTextLoader (.txt, UTF-8)
  extractors/
    __init__.py
    dictionary.py       # Dictionary-based matching (online/offline)
    latin.py            # Regex-детектор латинских биномиалов + валидация
    llm_extractor.py    # LLM-экстракция названий из текста (Фаза 1)
    llm_enricher.py     # LLM-обогащение неразрешённых кандидатов (Фаза 4)
    llm_client.py       # Абстракция LLM-клиента (Ollama, OpenAI, Anthropic)
  resolvers/
    __init__.py
    base.py             # TaxonSearcher и IdentificationResolver Protocols
    inaturalist.py      # Поиск таксонов через iNaturalist API (online режим)
    noo_garden.py       # Поиск таксонов через PostgreSQL noo-garden (offline режим)
    identifier.py       # Логика определения identified (сравнение имён)
    cache.py            # Кэш результатов (in-memory + опциональный disk)
  models.py             # Dataclasses для внутренних структур данных
  normalizer.py         # Нормализация текста, лемматизация

data/
  control_list/         # CSV-файлы с контрольными списками таксонов (для справки)

cache/                  # Disk-кэш для iNaturalist API (SQLite, только online режим)

prompts/
  llm_extractor.txt     # Базовый промпт для LLM-экстрактора (Фаза 1)
  llm_extractor.{locale}.txt  # Локализованные версии (например, .ru.txt)
  llm_enricher.txt      # Базовый промпт для LLM-обогатителя (Фаза 4)
  llm_enricher.{locale}.txt   # Локализованные версии
```

### Контракт пайплайна

Пайплайн реализован как **синхронный генератор**, который yield'ит события по мере
обработки. Это обеспечивает стриминг результатов, отчёт о прогрессе и возможность отмены.

```python
def process(
    text: str,
    config: Config,
    *,
    searcher: TaxonSearcher | None = None,
    identifier: IdentificationResolver | None = None,
    llm_client: LlmClient | None = None,
    rate_limiter: RateLimiter | None = None,
) -> Iterator[PipelineEvent]:
    """Основной sync-генератор. Ядро пайплайна.

    Зависимости принимаются через keyword-аргументы для тестируемости.
    Если не переданы — создаются из config (production defaults).
    """
    ...

def process_all(text: str, config: Config, **kwargs) -> list[TaxonResult]:
    """Convenience-обёртка: возвращает только итоговые результаты."""
    return [e.result for e in process(text, config, **kwargs)
            if isinstance(e, ResultReady)]

def estimate(text: str, config: Config) -> PipelineEstimate:
    """Dry-run: оценка объёма работы без выполнения."""
    ...
```

Типы событий (`PipelineEvent` — union/dataclass):
- `PhaseStarted(phase: str, total: int)` — начало фазы, `total` — количество элементов.
- `PhaseProgress(phase: str, current: int, total: int, detail: str)` — прогресс фазы.
- `ResultReady(result: TaxonResult)` — готовый элемент результата.
- `PipelineFinished(summary: PipelineSummary)` — завершение: статистика по методам,
  количество найденных/неидентифицированных, время каждой фазы.

> **Примечание:** Поле `identified` в Python-моделях и в JSON-выводе имеет тип
> `bool` (`true`/`false`). См. [docs/models.md](docs/models.md) для подробностей.

CLI подписывается на `PhaseProgress` для отображения прогресс-бара.

### Синхронное ядро и граница async

Ядро пайплайна — **полностью синхронное** (осознанный выбор для MVP: простота
отладки, предсказуемый поток данных, минимум абстракций). Все HTTP-запросы
(iNaturalist API, LLM-провайдеры) выполняются через `httpx.Client`
(синхронный клиент).

Для использования в веб-бэкенде синхронный генератор оборачивается на уровне
веб-слоя. Подробности — в разделе [Web API контракт](#web-api-контракт).

Ядро (`taxonfinder/`) не импортирует `asyncio` и не содержит `async/await`.
Весь async-код принадлежит веб-адаптеру, который не является частью v0.1.

#### Подготовка к веб-бэкенду

Чтобы синхронное ядро можно было корректно использовать в async-контексте:
1. **Все зависимости передаются через DI** (keyword-аргументы `process()`)
   — нет глобального состояния, каждый вызов изолирован.
2. **`httpx.Client` — thread-safe** и может обслуживать несколько потоков
   через `ThreadPoolExecutor`.
3. **Генератор PipelineEvent** совместим с SSE: каждое событие сериализуется
   в JSON и отправляется клиенту.
4. **Checkpoint** позволяет сохранять промежуточное состояние на диск,
   что критично при долгих обработках в веб-контексте.

### Web API контракт

Веб-адаптер (Flask/FastAPI) не является частью MVP, но архитектура ядра
проектируется для его поддержки.

**Транспорт: Server-Sent Events (SSE).** Генератор `PipelineEvent` естественно
ложится на SSE — каждое событие отправляется клиенту по мере готовности.
SSE проще WebSocket (однонаправленный), не требует библиотек на клиенте
(стандартный `EventSource`), работает через HTTP/1.1.

**Эндпоинты:**

```
POST /api/v1/tasks
  Body: {"text": "...", "config_overrides": {...}}
  Response: {"task_id": "uuid", "status": "queued"}

GET  /api/v1/tasks/{task_id}/events
  Response: SSE stream of PipelineEvent (Content-Type: text/event-stream)
  Events:
    event: phase_started\ndata: {"phase": "extraction", "total": 42}\n\n
    event: phase_progress\ndata: {"phase": "extraction", "current": 1, ...}\n\n
    event: result_ready\ndata: {"result": {...}}\n\n
    event: pipeline_finished\ndata: {"summary": {...}}\n\n

GET  /api/v1/tasks/{task_id}
  Response: {"task_id": "...", "status": "running|completed|failed", ...}

DELETE /api/v1/tasks/{task_id}
  Response: 204 (отмена обработки через generator.close())
```

**Реализация:**

```python
# web/adapter.py — не часть ядра пайплайна
import asyncio
import queue
import threading
from taxonfinder.pipeline import process

def run_pipeline_in_thread(
    text: str, config: Config, event_queue: queue.Queue
) -> None:
    """Запускает синхронный пайплайн в отдельном потоке,
    отправляя события в thread-safe очередь."""
    try:
        for event in process(text, config):
            event_queue.put(event)
    except Exception as exc:
        event_queue.put(exc)
    finally:
        event_queue.put(None)  # sentinel
```

Веб-адаптер запускает `run_pipeline_in_thread` в `ThreadPoolExecutor`
и читает из `event_queue` для формирования SSE-ответа.

**Ограничения конкурентности:** текущая архитектура (синхронное ядро +
thread pool) поддерживает **1–3 задачи одновременно**. Каждая задача
занимает поток и выполняет блокирующие HTTP-запросы. Для масштабируемости
(десятки одновременных задач) задача обработки должна уходить в task queue
(Celery, RQ, Dramatiq) — воркер-процесс исполняет синхронный генератор
без изменений, а веб-адаптер только принимает задачу и отдаёт статус.
Это не требует переписывания ядра — синхронный генератор отлично работает
в воркер-процессе task queue.

**httpx.Client и `User-Agent`:** Все HTTP-клиенты (iNaturalist API,
LLM-провайдеры) должны устанавливать заголовок `User-Agent` с именем
и версией приложения (например, `TaxonFinder/0.1.0`). Это требование
iNaturalist API guidelines — без корректного User-Agent запросы могут
быть ограничены.

### Механизм отмены

Отмена обработки поддерживается через стандартный механизм Python-генераторов:

- **CLI:** при получении SIGINT (Ctrl+C) вызывается `generator.close()`. Генератор
  получает `GeneratorExit`, выполняет cleanup и завершается.
- **Веб-бэкенд:** отмена `asyncio.Task` приводит к завершению потока, в котором
  работает генератор.

Пайплайн обрабатывает `GeneratorExit` корректно: закрывает HTTP-соединения через
`httpx.Client` context manager, сохраняет промежуточные данные disk-кэша.

## Пайплайн обработки

Обработка текста выполняется в пять фаз. Подробности алгоритмов описаны
в [docs/processing.md](docs/processing.md).

### Фаза 1: Загрузка, предобработка и извлечение кандидатов

1. Текст загружается из входного файла через `TextLoader` (автовыбор по расширению).
2. Текст обрабатывается через spaCy: токенизация, сегментация на предложения, лемматизация.
3. Запускаются экстракторы:
   - **Dictionary matching**: поиск совпадений с известными народными и научными названиями.
     - В **online режиме**: использует локальный кэш и iNaturalist API
     - В **offline режиме**: прямые запросы к PostgreSQL базе noo-garden
   - **Regex-детектор** (всегда): ищет латинские биномиалы с эвристической валидацией.
   - **LLM-экстрактор** (если включён): текст разбивается на чанки и отправляется в LLM.
4. Результаты объединяются в общий список кандидатов.

### Фаза 2: Merge и дедупликация кандидатов

1. Кандидаты из всех экстракторов объединяются.
2. При перекрытии spans сохраняется кандидат с наивысшим `extraction_confidence`.
   Приоритет при равенстве: газеттер > regex > LLM.
3. Кандидаты группируются по нормализованной лемме.
4. Для каждой уникальной леммы выбирается один представитель для разрешения.
5. Все вхождения (включая дубли) сохраняются для Фазы 5.

### Фаза 3: Разрешение таксонов

Разрешение выполняется в зависимости от режима (`data_source`):

**Online режим** (`inaturalist`):
1. Кандидаты отправляются в iNaturalist API (endpoint `/v1/taxa/autocomplete`).
2. Результаты кэшируются (in-memory, опционально disk).
3. Для каждого кандидата формируется список matches (до 5 результатов).
4. Определяется значение `identified` (см. [критерии](docs/processing.md#критерии-identified)).

**Offline режим** (`noo_garden`):
1. Выполняются SQL-запросы к PostgreSQL базе noo-garden.
2. Поиск ведётся по таблицам `taxa` (научные названия) и `vernacular_names` (народные названия).
3. Используется полнотекстовый поиск и индексы для быстрого поиска.
4. Таксономическая иерархия берётся из денормализованных полей таблицы `taxa`.
5. Определяется значение `identified` по тем же критериям, что и в online режиме.

### Фаза 4: LLM-обогащение неразрешённых кандидатов

Выполняется только если LLM-обогатитель включён в конфигурации.

1. Кандидаты с пустым `matches` или `identified: false` передаются в LLM-обогатитель.
2. LLM получает кандидатное название + контекстное предложение, возвращает альтернативные
   русские и английские названия.
3. Альтернативные названия отправляются в iNaturalist для повторного поиска.
4. Результаты повторного поиска объединяются с существующими matches.

### Фаза 5: Сборка результата

1. Разрешённые данные раскладываются по всем вхождениям: если «липа» встречается 30 раз,
   разрешение выполняется 1 раз, а результат применяется ко всем 30 вхождениям.
2. Результат фильтруется по порогу `confidence` из конфигурации.
3. Формируется итоговый JSON:
   - **По умолчанию (дедуплицированный режим):** одна запись на уникальный таксон
     с полем `count` и массивом `occurrences` (каждое вхождение с `line_number`,
     `source_text`, `source_context`).
   - **С флагом `--all-occurrences`:** одна запись на каждое вхождение (без группировки).

## Прогресс

Обработка книги — длительная операция (минуты–десятки минут). Генератор yield'ит
`PhaseProgress` на каждом значимом шаге:
- Фаза 1: после обработки каждого LLM-чанка.
- Фаза 3: после каждого запроса к iNaturalist API.
- Фаза 4: после каждого запроса к LLM-обогатителю.

CLI использует события для прогресс-бара (`click.progressbar` или аналог).

## Управление секретами

API-ключи и пароли баз данных **никогда не хранятся в конфигурационном файле**.
Они загружаются из переменных окружения или `.env` файла (через `python-dotenv`):

```
# .env (добавлен в .gitignore)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
POSTGRES_PASSWORD=...         # Для подключения к noo-garden (offline режим)
```

`config.py` при загрузке конфигурации вызывает `dotenv.load_dotenv()`, что загружает
переменные окружения из `.env` файла в `os.environ`. 

- LLM-клиенты (OpenAI, Anthropic) читают API-ключи из `os.environ` при инициализации. 
  Провайдер `ollama` не требует ключа.
- PostgreSQL драйвер psycopg читает пароль из `${POSTGRES_PASSWORD}` при формировании
  connection string (только в offline режиме).

## Подробная документация

- [Модели данных](docs/models.md) — внутренние структуры, поток данных между фазами,
  события пайплайна, протоколы.
- [Обработка и алгоритмы](docs/processing.md) — экстракторы, нормализация, confidence,
  identified, LLM, чанкинг, дедупликация, кэширование.
- [Форматы данных и CLI](docs/data-and-cli.md) — входные/выходные форматы, конфигурация,
  CLI, ограничения API, обработка ошибок.

## Рекомендации по оптимизации noo-garden для TaxonFinder

TaxonFinder в offline режиме выполняет интенсивные запросы к PostgreSQL базе noo-garden.
Для оптимальной производительности рекомендуются следующие улучшения схемы noo-garden:

### 1. Functional indexes вместо дублирования данных

TaxonFinder выполняет поиск по нормализованным формам названий (lowercase, ё→е).
Вместо создания отдельных колонок используются **functional indexes** — индексы на результат
функции, что экономит место и упрощает поддержку:

```sql
-- Для vernacular_names: нормализация ё→е + lowercase
CREATE INDEX idx_vn_name_normalized ON vernacular_names 
  USING btree (LOWER(REPLACE(vernacular_name, 'ё', 'е')));

-- Для taxa: латинские названия (только lowercase)
CREATE INDEX idx_taxa_name_lower ON taxa 
  USING btree (LOWER(name));
```

**Важно:** В SQL-запросах TaxonFinder использует **точно такую же функцию**, что и в индексе:

```sql
-- PostgreSQL автоматически использует functional index
SELECT * FROM vernacular_names 
WHERE LOWER(REPLACE(vernacular_name, 'ё', 'е')) = 'елка'
  AND language = 'ru';
```

**Почему это работает для всех случаев с ё/е:**

Функция `LOWER(REPLACE(vernacular_name, 'ё', 'е'))` применяется **и к данным в БД, и к поисковому запросу**.
`REPLACE` заменяет **все** вхождения 'ё' на 'е', поэтому:

| В БД        | В тексте    | БД: после normalize | Код: после normalize | Совпадение |
|-------------|-------------|---------------------|----------------------|------------|
| "ёлка"      | "елка"      | "елка"              | "елка"               | ✅ ДА      |
| "елка"      | "ёлка"      | "елка"              | "елка"               | ✅ ДА      |
| "ёлка"      | "ёлка"      | "елка"              | "елка"               | ✅ ДА      |
| "счёт-счёт" | "счет-счет" | "счет-счет"         | "счет-счет"          | ✅ ДА      |
| "берёзовый" | "березовый" | "березовый"         | "березовый"          | ✅ ДА      |

**Ключевой момент:** Независимо от того, где 'ё' (в БД или тексте), после нормализации
получаем одинаковую строку для сравнения.

### 2. Таблица vernacular_name_words для поддержки многословных названий

**Проблема:** "Американский лебедь" в тексте может быть в любой форме: "американского лебедя",
"американским лебедем". Кроме того, слова могут идти не подряд: "Прилетел хрущ" должен находить
"Хрущ майский", если в том же предложении встречается "майский".

**Решение:** Разбиваем каждое многословное название на отдельные слова и определяем главное слово
(существительное) через POS tagging.

```sql
CREATE TABLE vernacular_name_words (
  id SERIAL PRIMARY KEY,
  vernacular_name_id INTEGER REFERENCES vernacular_names(id),
  word TEXT NOT NULL,              -- "Американский", "лебедь" - как в исходном названии
  word_position INTEGER,           -- 0, 1, 2... (позиция слова в названии)
  is_head_word BOOLEAN NOT NULL    -- TRUE для существительного (главного слова)
);

-- Индекс для первичного поиска (ТОЛЬКО по существительным)
CREATE INDEX idx_vnw_head_lower ON vernacular_name_words (LOWER(word)) 
  WHERE is_head_word = TRUE;

-- Индекс для проверки остальных слов при уточнении
CREATE INDEX idx_vnw_all_lower ON vernacular_name_words (LOWER(word));

-- Индекс для быстрого получения всех слов названия
CREATE INDEX idx_vnw_name_id ON vernacular_name_words (vernacular_name_id);
```

**Заполнение таблицы (Python-скрипт с pymorphy3):**

```python
import pymorphy3

morph = pymorphy3.MorphAnalyzer()

for vn in vernacular_names:
    words = vn.vernacular_name.split()
    for position, word in enumerate(words):
        parsed = morph.parse(word)[0]
        is_head = (parsed.tag.POS == 'NOUN')  # Существительное = главное слово
        
        insert_word(vn.id, word, position, is_head)
```

**Пример:**
- "Американский лебедь" → ["Американский" (ADJ, pos=0), "лебедь" (NOUN, pos=1, **head**)]  
- "Серохохлый очковый сорокопут" → ["Серохохлый" (ADJ), "очковый" (ADJ), "сорокопут" (NOUN, **head**)]
- "Роза домашняя" → ["Роза" (NOUN, **head**), "домашняя" (ADJ)]

**Алгоритм поиска TaxonFinder:**

1. Лемматизировать текст: "американского лебедя" → ["американский", "лебедь"]
2. Искать по head_word: `WHERE LOWER(word) = 'лебедь' AND is_head_word = TRUE`
3. Получить кандидатов: "Американский лебедь", "Лебедь-шипун", "Лебедь-кликун"
4. Для каждого кандидата проверить остальные слова в предложении:
   - "Американский лебедь": ["американский" ✓, "лебедь" ✓] → 2/2 = HIGH confidence
   - "Лебедь-шипун": ["лебедь" ✓, "шипун" ✗] → 1/2 = LOW confidence
5. Выбрать кандидата с максимальным совпадением

**Преимущества подхода:**
- ✅ Находит названия независимо от склонения ("американского лебедя", "американским лебедем")
- ✅ Слова могут быть не рядом: "Прилетел хрущ. Майского окраса." → "Хрущ майский"
- ✅ Исключает ложные срабатывания: "американский посол" не даст кандидатов ("посол" не head_word)
- ✅ Работает с прилагательными в начале: "Американский лебедь", "Серохохлый сорокопут"

### 3. Добавить поле is_preferred в vernacular_names (опционально)

**Статус:** Опциональное улучшение. TaxonFinder работает без этого поля, но качество
ранжирования снижается.

**Проблема:** В исходных данных iNaturalist (VernacularNames-russian.csv) может отсутствовать
информация о предпочитаемых названиях. Это затрудняет выбор основного названия из синонимов:
- "Липа сердцевидная" (основное) vs "Липа сердцелистная" (синоним)
- "Ёлка" vs "Ель обыкновенная" vs "Picea abies" (народные варианты)

**Если is_preferred доступно:**

```sql
ALTER TABLE vernacular_names 
  ADD COLUMN is_preferred BOOLEAN DEFAULT FALSE;

-- Заполнение из iNaturalist API (в скрипте импорта)
-- Preferred имя можно получить из поля preferred_common_name таксона через запрос:
-- GET /v1/taxa/{id} → response.preferred_common_name
-- Сравнить с vernacular_name, установить is_preferred=TRUE для совпавшего

CREATE INDEX idx_vn_preferred ON vernacular_names(is_preferred) 
  WHERE is_preferred = TRUE;
```

**Влияние на confidence:**
- С is_preferred: exact match + preferred = confidence **0.95**
- Без is_preferred: exact match = confidence **0.9** (все названия равны)

**Fallback стратегии без is_preferred:**

1. **Эвристика по длине названия** (самое короткое часто основное):
   ```sql
   SELECT *, 
     (LENGTH(vernacular_name) = MIN(LENGTH(vernacular_name)) 
       OVER (PARTITION BY taxon_id)) AS is_preferred_heuristic
   FROM vernacular_names;
   ```

2. **Без приоритизации**: все названия равны, выбирается первое по порядку (алфавит, ID)

3. **Дополнительный импорт**: сделать запрос к `/v1/taxa/{id}` для каждого таксона
   при миграции (~50K API запросов с rate limiting, занимает ~14 часов)

### 4. Fuzzy matching для латинских названий (опционально)

Для поиска латинских названий с опечатками используется расширение **pg_trgm** (trigram similarity):

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- GIN индекс для быстрого fuzzy поиска
CREATE INDEX idx_taxa_name_trgm ON taxa 
  USING gin (name gin_trgm_ops);
```

**Запрос с fuzzy matching:**

```sql
-- Найти таксоны похожие на "Tila cordata" (опечатка)
SELECT name, similarity(name, 'Tila cordata') AS score
FROM taxa
WHERE name % 'Tila cordata'  -- оператор % использует trigram similarity
ORDER BY score DESC
LIMIT 5;

-- Результат: "Tilia cordata" (score ~0.8)
```

**Настройка порога схожести:**

```sql
-- Установить минимальный порог (по умолчанию 0.3)
SET pg_trgm.similarity_threshold = 0.75;
```

### 5. Составной индекс для фильтрации по языку

TaxonFinder всегда фильтрует по языку (`WHERE language = 'ru'`), поэтому рекомендуется
составной индекс:

```sql
CREATE INDEX idx_vn_language ON vernacular_names(language);
```

**Примечание:** Functional index `idx_vn_name_normalized` уже включает нормализованное название,
поэтому отдельный составной индекс `(language, normalized_name)` может быть избыточным.
PostgreSQL может использовать bitmap index scan (комбинация двух индексов).

### 6. Денормализация: preferred common name в taxa (опционально)

Для быстрого доступа к основному народному названию без JOIN:

```sql
ALTER TABLE taxa 
  ADD COLUMN preferred_common_name_ru TEXT,
  ADD COLUMN preferred_common_name_en TEXT;

-- Заполнение через UPDATE с подзапросом к vernacular_names
UPDATE taxa t SET 
  preferred_common_name_ru = (
    SELECT vernacular_name FROM vernacular_names 
    WHERE taxon_id = t.taxon_id 
      AND language = 'ru' 
      AND is_preferred = TRUE 
    LIMIT 1
  );
```

**Альтернатива:** Использовать материализованное представление (materialized view) для таксонов
с preferred названиями — обновляется по расписанию, не требует изменения схемы.

### Приоритет реализации

**Критично (блокирует production):**
- **Functional indexes** (п. 1) — без них поиск будет медленным
- **vernacular_name_words с is_head_word** (п. 2) — без этого многословные названия не будут
  корректно находиться, будет много ложных срабатываний

**Важно (улучшает качество):**
- **is_preferred** (п. 3) — влияет на ранжирование результатов. **Опционально:** TaxonFinder
  работает без него, но качество ниже (все синонимы равны)
- **Fuzzy matching через pg_trgm** (п. 4) — находит опечатки в латинских названиях
- Язык-специфичные индексы (п. 5) — ускоряет фильтрацию

**Желательно (удобство):**
- Денормализация preferred_common_name (п. 6) — избавляет от JOIN при выводе

**Заполнение vernacular_name_words:**
Требуется отдельный Python-скрипт с pymorphy3 для POS tagging (определение существительных).
Скрипт должен быть запущен один раз при миграции, далее таблица заполняется автоматически
при добавлении новых народных названий через trigger или application logic.

Все изменения должны быть оформлены как миграции Alembic в noo-garden проекте.

