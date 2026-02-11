# План интеграции noo-garden в TaxonFinder

План реализации offline режима с использованием PostgreSQL базы noo-garden как источника данных
вместо iNaturalist API. Предполагается что noo-garden уже содержит:
- Таблицу `vernacular_name_words` с POS tagging и `is_head_word`
- Functional indexes для нормализации (`LOWER(REPLACE(...))`)
- Fuzzy matching indexes (pg_trgm) для латинских названий
- Поле `is_preferred` **отсутствует** (используем fallback стратегию)

## 1. Создание NooGarden Resolver

**Файл:** `taxonfinder/resolvers/noo_garden.py`

Создать класс `NooGardenSearcher` реализующий протокол `TaxonSearcher`:

1. **Подключение к PostgreSQL**: использовать `psycopg` (sync client), connection string из config
2. **Метод `search_vernacular(name, locale)`**:
   - Лемматизировать входное название через pymorphy3 (разбить на слова, получить леммы)
   - Искать по head_word: `WHERE LOWER(word) = ? AND is_head_word = TRUE AND language = ?`
   - Для каждого кандидата получить все слова из `vernacular_name_words`
   - Проверить сколько слов кандидата присутствует в исходном предложении (scoring)
   - Ранжировать: 100% совпадение → score 0.9, частичное → 0.7, только head → 0.5
   - Fallback без is_preferred: все названия равны, берем первое
3. **Метод `search_scientific(name)`**:
   - Exact match: `WHERE LOWER(name) = ?` (functional index)
   - Fuzzy match (если включен): `WHERE name % ? ORDER BY similarity(name, ?) DESC LIMIT 5`
4. **Формирование TaxonMatch**: извлечь taxon_id, rank, taxonomy из денормализованных полей таблицы `taxa`
5. **Обработка ошибок**: try/except на уровне SQL запросов, логирование через structlog
6. **Connection pooling**: использовать `psycopg.ConnectionPool` для эффективного переиспользования соединений

## 2. Обновление Pipeline для выбора источника данных

**Файлы:** `taxonfinder/pipeline.py`, `taxonfinder/config.py`

1. **Config.data_source**: добавить enum `DataSource` с значениями `inaturalist | noo_garden`
2. **Config.noo_garden**: новая секция с полями `host, port, database, user, password` (password через env)
3. **Фабрика resolver в pipeline.py**:
   ```python
   def create_searcher(config: Config) -> TaxonSearcher:
       if config.data_source == "inaturalist":
           return InaturalistSearcher(...)
       elif config.data_source == "noo_garden":
           return NooGardenSearcher(config.noo_garden)
   ```
4. **Передача searcher в dictionary extractor**: обновить `extractors/dictionary.py` чтобы принимать `TaxonSearcher`
5. **Обновить Фазу 3 (Resolution)**: убедиться что resolver корректно работает с обоими источниками
6. **Rate limiting**: применяется только для InaturalistSearcher, пропускаем для NooGarden
7. **Disk cache**: используется только в online режиме, отключаем для offline
8. **LLM enricher (Фаза 4)**: в offline режиме LLM-обогатитель **опционален** — можно отключить, т.к. база уже полная

## 3. Нормализация и лемматизация

**Файл:** `taxonfinder/normalizer.py`

1. **Функция `normalize_for_db(text: str) -> str`**:
   - Должна **точно совпадать** с functional index: `text.lower().replace('ё', 'е')`
   - Критично: если порядок операций другой, индекс не будет использоваться!
2. **Функция `lemmatize_words(text: str, locale: str) -> list[str]`**:
   - Для русского: использовать pymorphy3 для каждого слова
   - Для других языков: spaCy lemmatizer
   - Возвращать список лемм в lowercase
3. **Sentence context extraction**: функция для получения предложения по позиции в тексте (для проверки многословных названий)
4. **Интеграция в dictionary extractor**: вызывать lemmatize перед поиском в БД
5. **Unit тесты**: проверить что нормализация работает для всех случаев с ё/е

## 4. Конфигурация, тестирование и документация

**Конфигурация:**
1. Обновить `taxonfinder.config.json` с примером noo_garden секции
2. Обновить `schemas/config.schema.json` с новыми полями
3. Добавить в `.env.example`: `POSTGRES_PASSWORD=your_password_here`
4. Документировать переменные окружения в `docs/data-and-cli.md`

**Unit тесты:**
1. `tests/test_noo_garden.py`: моки PostgreSQL через pytest fixtures
2. `tests/test_normalizer.py`: все комбинации ё/е, многословные названия
3. `tests/test_pipeline_offline.py`: full pipeline с NooGardenSearcher (мок БД)

**Интеграционные тесты:**
1. `tests/test_noo_garden_live.py`: реальное подключение к тестовой БД (skip if DB unavailable)
2. Проверить: поиск по head_word, многословные названия, fuzzy match, functional indexes
3. Замерить производительность: сколько запросов в секунду, latency, index usage (EXPLAIN ANALYZE)

**Документация:**
1. Обновить README.md: добавить инструкции по настройке PostgreSQL для offline режима
2. Создать `docs/noo-garden-setup.md`: как развернуть noo-garden локально, примеры SQL для проверки
3. Обновить CLI help: добавить описание `data_source` параметра

**Миграция с gazetteer:**
1. Удалить старый код: `build-gazetteer` команда, SQLite gazetteer логика
2. Переименовать `gazetteer_taxon_ids` → `dictionary_taxon_ids` в models
3. Обновить tests: заменить старые моки gazetteer на новые

---

## Порядок реализации (приоритет)

1. **Сначала:** Normalizer + Config (фундамент)
2. **Затем:** NooGarden Resolver (core логика)
3. **Затем:** Pipeline integration (склейка)
4. **Последнее:** Tests + Documentation (валидация)

Ожидаемое время: **2-3 дня** разработки для MVP (базовая функциональность без оптимизаций).
