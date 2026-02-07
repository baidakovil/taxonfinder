---
description: Core coding standards for the project (migrated from .cursor)
alwaysApply: true
---

# Core Coding Standards

- Write clean, readable code with consistent naming and structure.
- Prefer small, focused functions and clear module boundaries.
- Use modern Python syntax (3.11+), f-strings, dataclasses where appropriate.
- Include type hints for public functions and complex data structures.
- Add docstrings for public modules, classes, and functions.
- Keep dependencies minimal and standard-library first.

## Architecture Constraints

- Pipeline core (`taxonfinder/`) is fully synchronous — no `asyncio` imports in core.
- Use `httpx.Client` (sync) for HTTP in core modules.
- Use `Protocol` for abstractions (TextLoader, LLM client).
- Use dataclasses for models and pipeline events.
- External APIs (iNaturalist, LLM) must be behind abstractions for testability.
- Refer to `projectdescription.md` and `docs/` for architecture decisions.

## Testing Requirements

- Write unit tests for new behavior and bug fixes.
- Favor deterministic tests; avoid network and time dependencies.
- Mock external services (iNaturalist API, LLM providers) in tests.
- Use pytest and arrange/act/assert structure.
- Name tests descriptively and cover edge cases.
- Validate output fixtures against JSON schemas in `schemas/`.

## Formatting & Style

- Format and lint with `ruff` (replaces Black + isort).
- Follow PEP 8; keep lines <= 100 chars.
- CI enforces lint and format checks (`ruff check`, `ruff format --check`)
  via `.github/workflows/lint.yml`.
- Tests run in CI via `.github/workflows/test.yml` (pytest + fixture schema validation).

## HTTP Client Requirements

- All outgoing HTTP clients must set the `User-Agent` header from config
  (`user_agent` field, default: `TaxonFinder/0.1.0`).
- Retry logic must use exponential backoff with random jitter
  (`delay * (0.5 + random() * 0.5)`) to prevent thundering herd.

## AI Coding Workflow

- When editing, read the file first and preserve existing style.
- Prefer small, incremental edits with minimal changes.
- Avoid security tooling or checks unless explicitly requested.
