from __future__ import annotations

import httpx

from taxonfinder.pipeline import _prepare_ollama


class FakeHttp:
    def __init__(self, models: list[str] | None = None, reachable: bool = True) -> None:
        self.models = models or []
        self.reachable = reachable
        self.calls: list[str] = []

    def get(self, url: str, timeout: float):
        self.calls.append(url)
        if not self.reachable:
            raise httpx.ConnectError("unreachable", request=httpx.Request("GET", url))
        return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})


def test_prepare_ollama_reachable_noop() -> None:
    http = FakeHttp(models=["llama3.1"], reachable=True)

    cleanup = _prepare_ollama(
        http=http,
        base_url="http://localhost:11434",
        model="llama3.1",
        auto_start=False,
        auto_pull=False,
        stop_after=False,
        timeout=5,
    )

    assert cleanup is None
    assert http.calls  # checked reachability


def test_prepare_ollama_autostart_and_cleanup(monkeypatch) -> None:
    http = FakeHttp(models=[], reachable=False)

    class DummyProc:
        def __init__(self) -> None:
            self.terminated = False

        def terminate(self) -> None:
            self.terminated = True

    started: list[DummyProc] = []

    def fake_popen(cmd, stdout=None, stderr=None):  # noqa: ANN001
        http.reachable = True
        proc = DummyProc()
        started.append(proc)
        return proc

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    cleanup = _prepare_ollama(
        http=http,
        base_url="http://localhost:11434",
        model="llama3.1",
        auto_start=True,
        auto_pull=False,
        stop_after=True,
        timeout=2,
    )

    assert cleanup is not None
    assert http.calls  # reachability checked after start

    cleanup()
    assert started[0].terminated is True


def test_prepare_ollama_autopull(monkeypatch) -> None:
    http = FakeHttp(models=[], reachable=True)

    calls: list[list[str]] = []

    def fake_run(cmd, check, stdout=None, stderr=None):  # noqa: ANN001
        calls.append(cmd)
        http.models.append("llama3.1")
        return None

    monkeypatch.setattr("subprocess.run", fake_run)

    cleanup = _prepare_ollama(
        http=http,
        base_url="http://localhost:11434",
        model="llama3.1",
        auto_start=False,
        auto_pull=True,
        stop_after=False,
        timeout=2,
    )

    assert cleanup is None
    assert calls == [["ollama", "pull", "llama3.1"]]
    assert "llama3.1" in http.models
