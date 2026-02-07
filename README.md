# TaxonFinder

[![Tests](https://img.shields.io/github/actions/workflow/status/baidakov/taxonfinder/test.yml?branch=main&label=tests)](https://github.com/baidakov/taxonfinder/actions/workflows/test.yml)
[![Lint](https://img.shields.io/github/actions/workflow/status/baidakov/taxonfinder/lint.yml?branch=main&label=lint)](https://github.com/baidakov/taxonfinder/actions/workflows/lint.yml)

TaxonFinder extracts organism names (plants, animals, fungi, etc.) from Russian texts and returns JSON with Latin names, confidence, and iNaturalist links.

## Highlights
- Hybrid extraction: gazetteer (spaCy PhraseMatcher), regex for Latin binomials, and LLM (independent extractor/enricher roles).
- iNaturalist-powered verification and enrichment via httpx; gazetteer-backed records can bypass API calls when data is complete.
- Configurable LLM providers (Ollama or hosted APIs) and resilient mode that tolerates missing gazetteer.

## Requirements
- Python 3.11+
- spaCy model `ru_core_news_md` (download with `python -m spacy download ru_core_news_md`)
- Optional: running Ollama instance with the configured model when using the LLM extractor or enricher
- Optional: API keys in `.env` for hosted LLM providers (OpenAI, Anthropic)

## Quick start
```bash
pip install -e .
python -m spacy download ru_core_news_md
python -m taxonfinder.cli process path/to/text.txt --config taxonfinder.config.json
```

To list all occurrences instead of deduplicated results, add `--all-occurrences`. For JSON logs, pass `--json-logs`.
