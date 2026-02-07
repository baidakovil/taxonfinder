# TaxonFinder

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)](#)
[![Lint](https://img.shields.io/badge/ruff-passing-brightgreen)](#)

Извлечение названий таксонов (растений, животных, грибов и т.д.) из русскоязычных текстов. На вход подаётся файл с текстом, на выходе — JSON со списком обнаруженных организмов, их латинскими названиями и ссылками на iNaturalist.

## Ключевые идеи
- Гибридный подход: газеттер (spaCy PhraseMatcher), regex-детектор латинских биномиалов и LLM (экстракция и обогащение — отдельные роли).
- Верификация и обогащение через iNaturalist API (httpx); iNaturalist — источник истины для финальных данных.
- Газеттер хранится в локальной SQLite-базе и позволяет пропускать запросы к iNaturalist для полноценных записей.

## Быстрый старт
```bash
pip install -e .
python -m taxonfinder.cli process path/to/text.txt --config taxonfinder.config.json
```

Дополнительно: требуется модель spaCy `ru_core_news_md` и, при использовании LLM через Ollama, локально запущенный сервер с выбранной моделью.
