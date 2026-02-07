from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from taxonfinder.cli import main
from taxonfinder.config import Config, InaturalistConfig
from taxonfinder.events import (
    PhaseProgress,
    PipelineEstimate,
    PipelineFinished,
    PipelineSummary,
    ResultReady,
)
from taxonfinder.models import Occurrence, TaxonResult


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _config() -> Config:
    return Config(
        confidence=0.1,
        locale="ru",
        gazetteer_path="data/empty.db",
        spacy_model="ru_core_news_sm",
        max_file_size_mb=2.0,
        degraded_mode=True,
        user_agent="TaxonFinder/0.1.0-test",
        inaturalist=InaturalistConfig(cache_enabled=False),
        llm_extractor=None,
        llm_enricher=None,
    )


def _sample_result() -> TaxonResult:
    return TaxonResult(
        source_text="липа",
        identified=True,
        extraction_confidence=1.0,
        extraction_method="gazetteer",
        occurrences=[
            Occurrence(
                line_number=1,
                source_text="липа",
                source_context="Росла липа.",
            ),
        ],
        matches=[],
        llm_response=None,
        candidate_names=[],
        reason="",
    )


def _summary() -> PipelineFinished:
    return PipelineFinished(
        summary=PipelineSummary(
            total_candidates=1,
            unique_candidates=1,
            identified_count=1,
            unidentified_count=0,
            skipped_resolution=0,
            api_calls=0,
            cache_hits=0,
            phase_times={"extraction": 0.01},
            total_time=0.01,
        )
    )


def test_process_outputs_json(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
) -> None:
    input_file = tmp_path / "input.txt"
    input_file.write_text("text", encoding="utf-8")

    monkeypatch.setattr("taxonfinder.cli.load_config", lambda path: _config())
    monkeypatch.setattr(
        "taxonfinder.cli.load_text", lambda path, max_file_size_mb=2.0: "text"
    )

    def fake_process(text: str, config: Config):
        yield PhaseProgress(
            phase="extraction",
            current=1,
            total=1,
            detail="chunk",
        )
        yield ResultReady(result=_sample_result())
        yield _summary()

    monkeypatch.setattr("taxonfinder.cli.process", fake_process)

    result = runner.invoke(
        main,
        ["--config", str(tmp_path / "cfg.json"), "process", str(input_file)],
    )

    assert result.exit_code == 0
    assert "\"version\": \"1.0\"" in result.stdout
    assert "липа" in result.stdout


def test_process_all_occurrences(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
) -> None:
    input_file = tmp_path / "input.txt"
    input_file.write_text("text", encoding="utf-8")

    monkeypatch.setattr("taxonfinder.cli.load_config", lambda path: _config())
    monkeypatch.setattr(
        "taxonfinder.cli.load_text", lambda path, max_file_size_mb=2.0: "text"
    )

    def fake_process(text: str, config: Config):
        yield ResultReady(result=_sample_result())
        yield _summary()

    monkeypatch.setattr("taxonfinder.cli.process", fake_process)

    result = runner.invoke(
        main,
        [
            "--config",
            str(tmp_path / "cfg.json"),
            "process",
            str(input_file),
            "--all-occurrences",
        ],
    )

    assert result.exit_code == 0
    assert "line_number" in result.stdout


def test_process_writes_file_and_summary(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
) -> None:
    input_file = tmp_path / "input.txt"
    output_file = tmp_path / "out.json"
    input_file.write_text("text", encoding="utf-8")

    monkeypatch.setattr("taxonfinder.cli.load_config", lambda path: _config())
    monkeypatch.setattr(
        "taxonfinder.cli.load_text", lambda path, max_file_size_mb=2.0: "text"
    )

    def fake_process(text: str, config: Config):
        yield PhaseProgress(
            phase="extraction",
            current=1,
            total=1,
            detail=None,
        )
        yield ResultReady(result=_sample_result())
        yield _summary()

    monkeypatch.setattr("taxonfinder.cli.process", fake_process)

    result = runner.invoke(
        main,
        [
            "--config",
            str(tmp_path / "cfg.json"),
            "process",
            str(input_file),
            str(output_file),
        ],
    )

    assert result.exit_code == 0
    assert "Written to" in result.output
    assert "Done in" in result.output
    assert "\"version\": \"1.0\"" in output_file.read_text(encoding="utf-8")


def test_dry_run(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
) -> None:
    input_file = tmp_path / "input.txt"
    input_file.write_text("text", encoding="utf-8")

    monkeypatch.setattr("taxonfinder.cli.load_config", lambda path: _config())
    monkeypatch.setattr(
        "taxonfinder.cli.load_text", lambda path, max_file_size_mb=2.0: "text"
    )

    estimate_obj = PipelineEstimate(
        sentences=3,
        chunks=2,
        llm_calls_phase1=2,
        gazetteer_candidates=1,
        regex_candidates=1,
        unique_candidates=2,
        api_calls_estimated=1,
        estimated_time_seconds=4.0,
    )

    monkeypatch.setattr("taxonfinder.cli.estimate", lambda text, config: estimate_obj)

    result = runner.invoke(
        main,
        ["--config", str(tmp_path / "cfg.json"), "dry-run", str(input_file)],
    )

    assert result.exit_code == 0
    assert "Sentences: 3" in result.stdout
    assert "API calls (est): 1" in result.stdout


def test_json_logs_flag(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
) -> None:
    called = {}

    def fake_setup_logging(*, json_mode: bool):
        called["json_mode"] = json_mode
        return object()

    monkeypatch.setattr("taxonfinder.cli.setup_logging", fake_setup_logging)
    monkeypatch.setattr("taxonfinder.cli.load_config", lambda path: _config())
    monkeypatch.setattr(
        "taxonfinder.cli.load_text", lambda path, max_file_size_mb=2.0: "text"
    )
    monkeypatch.setattr("taxonfinder.cli.process", lambda text, config: iter(()))

    input_file = tmp_path / "input.txt"
    input_file.write_text("text", encoding="utf-8")

    result = runner.invoke(
        main,
        ["--json-logs", "--config", str(tmp_path / "cfg.json"), "process", str(input_file)],
    )

    assert result.exit_code == 0
    assert called["json_mode"] is True


def test_process_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
) -> None:
    input_file = tmp_path / "input.txt"
    input_file.write_text("text", encoding="utf-8")

    class DummyLogger:
        def __init__(self) -> None:
            self.logged: list[str] = []

        def error(self, message: str, **kwargs: str) -> None:
            self.logged.append(message)

    dummy_logger = DummyLogger()

    monkeypatch.setattr("taxonfinder.cli.load_config", lambda path: _config())
    monkeypatch.setattr(
        "taxonfinder.cli.load_text", lambda path, max_file_size_mb=2.0: "text"
    )
    monkeypatch.setattr("taxonfinder.cli.setup_logging", lambda json_mode=False: dummy_logger)
    monkeypatch.setattr(
        "taxonfinder.cli.process", lambda text, config: (_ for _ in ()).throw(ValueError("boom"))
    )

    result = runner.invoke(
        main,
        ["--config", str(tmp_path / "cfg.json"), "process", str(input_file)],
    )

    assert result.exit_code != 0
    assert "boom" in result.output
    assert "cli_process_failed" in dummy_logger.logged[0]


def test_build_gazetteer_not_implemented(runner: CliRunner) -> None:
    result = runner.invoke(main, ["build-gazetteer"])
    assert result.exit_code != 0
    assert "not implemented" in result.output.lower()
