---
description: Documentation style for Markdown files (migrated from .cursor)
globs: "**/*.md, **/*.mdc"
alwaysApply: false
---

# Documentation Guidelines

- Keep docs concise and task-focused.
- Use clear headings and short sections.
- Provide runnable examples when helpful.
- Prefer Markdown lists and code fences for readability.

## Project Documentation Structure

- `projectdescription.md` — overview, architecture, pipeline.
- `docs/models.md` — internal data models, pipeline events, protocols.
- `docs/processing.md` — extractors, algorithms, confidence model.
- `docs/data-and-cli.md` — formats, config, CLI interface.
- `schemas/*.json` — source of truth for data format contracts.

## Conventions

- Descriptions and docs in Russian; code, comments, schemas, and identifiers in English.
- When updating behavior, update the relevant doc and schema together.
- Do not duplicate information across documents; cross-reference instead.