from __future__ import annotations

import json
import os
from pathlib import Path

import click

from .config import Config, load_config
from .events import PhaseProgress, PipelineFinished, ResultReady
from .loaders import load_text
from .logging import setup_logging
from .pipeline import estimate, format_deduplicated, format_full, process


def _echo_progress(event: PhaseProgress) -> None:
    detail = f" {event.detail}" if event.detail else ""
    click.echo(
        f"[{event.phase}] {event.current}/{event.total}{detail}",
        err=True,
    )


def _echo_summary(summary: PipelineFinished | None) -> None:
    if summary is None:
        return
    s = summary.summary
    click.echo(
        (
            f"Done in {s.total_time:.2f}s — "
            f"identified {s.identified_count}, "
            f"unidentified {s.unidentified_count}, "
            f"candidates {s.unique_candidates}, api_calls {s.api_calls}"
        ),
        err=True,
    )


def _load_text(input_path: Path, config: Config) -> str:
    return load_text(input_path, max_file_size_mb=config.max_file_size_mb)


@click.group()
@click.option(
    "--config",
    "config_path",
    default="taxonfinder.config.json",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to configuration JSON file.",
)
@click.option(
    "--json-logs",
    is_flag=True,
    default=False,
    help="Emit logs in JSON (overrides LOG_FORMAT env).",
)
@click.pass_context
def main(ctx: click.Context, config_path: Path, json_logs: bool) -> None:
    """TaxonFinder CLI."""
    json_mode = json_logs or os.getenv("LOG_FORMAT") == "json"
    logger = setup_logging(json_mode=json_mode)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["logger"] = logger


@main.command(name="process")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_path", required=False, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--all-occurrences", is_flag=True, help="Output one entry per occurrence.")
@click.pass_context
def process_cmd(
    ctx: click.Context,
    input_path: Path,
    output_path: Path | None,
    all_occurrences: bool,
) -> None:
    """Process input text and produce JSON results."""
    config_path: Path = ctx.obj["config_path"]
    logger = ctx.obj["logger"]
    try:
        config = load_config(config_path)
        text = _load_text(input_path, config)

        results = []
        finished: PipelineFinished | None = None
        for event in process(text, config):
            if isinstance(event, PhaseProgress):
                _echo_progress(event)
            elif isinstance(event, ResultReady):
                results.append(event.result)
            elif isinstance(event, PipelineFinished):
                finished = event

        output_obj = format_full(results) if all_occurrences else format_deduplicated(results)
        payload = json.dumps(output_obj, ensure_ascii=False, indent=2)

        if output_path:
            output_path.write_text(payload, encoding="utf-8")
            click.echo(f"Written to {output_path}", err=True)
        else:
            click.echo(payload)

        _echo_summary(finished)
    except Exception as exc:  # noqa: BLE001
        logger.error("cli_process_failed", error=str(exc))
        raise click.ClickException(str(exc)) from exc


@main.command(name="dry-run")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.pass_context
def dry_run_cmd(ctx: click.Context, input_path: Path) -> None:
    """Estimate workload without calling APIs/LLMs."""
    config_path: Path = ctx.obj["config_path"]
    try:
        config = load_config(config_path)
        text = _load_text(input_path, config)
        est = estimate(text, config)

        lines = [
            f"Sentences: {est.sentences}",
            f"LLM chunks: {est.chunks}",
            f"LLM calls (phase1): {est.llm_calls_phase1}",
            f"Gazetteer candidates: {est.gazetteer_candidates}",
            f"Regex candidates: {est.regex_candidates}",
            f"Unique candidates (est): {est.unique_candidates}",
            f"API calls (est): {est.api_calls_estimated}",
            f"Estimated time (s): {est.estimated_time_seconds:.1f}",
        ]
        click.echo("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(str(exc)) from exc


@main.command(name="build-gazetteer")
@click.option("--source", default="csv", show_default=True, help="Source type (planned: csv)")
@click.option("--file", "file_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--tag", help="Tag for gazetteer build")
@click.option("--locales", help="Locales comma-separated")
@click.pass_context
def build_gazetteer_cmd(
    ctx: click.Context,
    source: str,
    file_path: Path | None,
    tag: str | None,
    locales: str | None,
) -> None:
    """Placeholder for gazetteer builder (to be implemented in Step 7)."""
    _ = ctx, source, file_path, tag, locales
    raise click.ClickException("build-gazetteer is not implemented yet (planned in Step 7).")


if __name__ == "__main__":
    main()
