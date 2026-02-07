# TaxonFinder CLI

Command-line interface for running the pipeline, estimating workload, and (soon) building gazetteers.

## Installation

```bash
pip install -e .
```

## Usage

```bash
python -m taxonfinder.cli [OPTIONS] COMMAND [ARGS...]
```

Global options:
- `--config PATH` — path to JSON config (default: `taxonfinder.config.json`).
- `--json-logs` — emit logs in JSON format (otherwise human-readable). Applies to all commands.
- `--help` — show command help.

## Commands

### process
Run the full pipeline on an input text file.

```bash
python -m taxonfinder.cli process INPUT_PATH [OUTPUT_PATH] [--all-occurrences]
```

- `INPUT_PATH` — UTF-8 text file to process.
- `OUTPUT_PATH` (optional) — where to write JSON. If omitted, JSON is printed to stdout.
- `--all-occurrences` — output one item per occurrence instead of deduplicated results.

Progress is printed to stderr (phase, counters). Summary line shows elapsed time and counts. JSON envelope is versioned (`{"version": "1.0", ...}`).

### dry-run
Estimate work without calling external APIs/LLMs.

```bash
python -m taxonfinder.cli dry-run INPUT_PATH
```

Prints counts of sentences, chunks, candidates, estimated API calls, and time. Useful for sizing workloads.

### build-gazetteer (planned)
Placeholder for Step 7. Will populate SQLite gazetteers from CSV + iNaturalist. Currently raises `ClickException` to signal unimplemented status.

## Logging

- Stdout: JSON payloads (for `process`) or estimate lines (for `dry-run`).
- Stderr: progress, summaries, and operational messages.
- `--json-logs` forces JSON log format regardless of `LOG_FORMAT` env.

## Exit codes

- `0` on success.
- Non-zero on validation errors, processing errors, or unimplemented commands (`build-gazetteer`).

## Testing

CLI is covered by `tests/test_cli.py` using `click.testing.CliRunner` (no subprocess needed).

### Ollama lifecycle helpers

For provider `ollama`, optional config flags (both extractor and enricher blocks):

- `auto_start`: start `ollama serve` if not reachable.
- `auto_pull_model`: run `ollama pull <model>` if the model is missing.
- `stop_after_run`: if we auto-started ollama, stop it after the pipeline finishes.

Run full suite:

```bash
python -m pytest
python -m ruff check
```
