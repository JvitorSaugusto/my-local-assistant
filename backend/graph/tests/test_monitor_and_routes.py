import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.controllers.monitor_controller import monitor_router
from backend.api.docker_monitor import extract_code_snippet_from_traceback, is_error_line
from backend.graph import dev_tools


def test_docker_logs_allowed_in_run_safe_command(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dev_tools.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="api-1 | INFO ready", stderr=""),
    )
    out = dev_tools.run_safe_command.func(command="docker compose logs --tail=50", workspace_path=str(tmp_path))
    assert "exit_code=0" in out
    assert "INFO ready" in out

    # Flag -f (follow) bloqueada no comando síncrono para não travar a tool
    blocked = dev_tools.run_safe_command.func(command="docker compose logs -f", workspace_path=str(tmp_path))
    assert "ERRO DE SEGURANÇA" in blocked


def test_local_route_suite_discovers_openapi_and_separates_pass_fail(monkeypatch):
    openapi_doc = {
        "paths": {
            "/api/health": {"get": {}},
            "/api/items": {"get": {}},
            "/api/items/{item_id}": {"get": {}},
            "/api/broken": {"get": {}},
        }
    }

    class FakeResp:
        def __init__(self, status, body, ctype="application/json"):
            self.status = status
            self._body = body.encode("utf-8")
            self.headers = {"Content-Type": ctype}

        def read(self, n=-1):
            return self._body[:n] if n > 0 else self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=8):
        url = req.full_url
        if url.endswith("/openapi.json"):
            return FakeResp(200, json.dumps(openapi_doc))
        if url.endswith("/api/health") or url.endswith("/api/items"):
            return FakeResp(200, '{"ok": true}')
        if url.endswith("/api/broken"):
            raise dev_tools.urllib.error.HTTPError(
                url, 500, "Internal Server Error", {}, dev_tools.io.BytesIO(b"ImportError: no module named x")
            )
        return FakeResp(404, "not found")

    monkeypatch.setattr(dev_tools.urllib.request, "urlopen", fake_urlopen)

    app = FastAPI()
    app.include_router(monitor_router, prefix="/api/monitor")
    client = TestClient(app)

    res = client.post("/api/monitor/test-routes", json={"base_url": "http://127.0.0.1:8000", "routes": ""})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3  # ignora /api/items/{item_id}
    assert len(body["passed"]) == 2
    assert len(body["failed"]) == 1
    assert body["failed"][0]["path"] == "/api/broken"
    assert body["failed"][0]["status"] == 500
    assert "ImportError" in body["failed"][0]["detail"]

    # Bloqueia host externo
    ext = client.post("/api/monitor/test-routes", json={"base_url": "https://example.com"})
    assert ext.status_code == 400


def test_docker_monitor_error_detection_and_traceback_snippet(tmp_path):
    assert is_error_line("api-1 | Traceback (most recent call last):")
    assert is_error_line("api-1 | ModuleNotFoundError: No module named 'foo'")
    assert is_error_line("web-1 | error TS2322: Type 'string' is not assignable")
    assert not is_error_line("api-1 | INFO: Uvicorn running on http://0.0.0.0:8000")

    src = tmp_path / "core" / "views.py"
    src.parent.mkdir(parents=True)
    src.write_text("import os\nimport foo_missing\n\ndef index():\n    return 1\n", encoding="utf-8")

    tb = f'Traceback (most recent call last):\n  File "{src}", line 2, in <module>\nModuleNotFoundError: No module named \'foo_missing\''
    snippet = extract_code_snippet_from_traceback(str(tmp_path), tb)
    assert "core/views.py" in snippet
    assert "foo_missing" in snippet
