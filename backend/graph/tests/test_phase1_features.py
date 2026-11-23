import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.controllers import settings_controller
from backend.api.controllers.upload_controller import upload_router
from backend.graph import assistant_tools, memory, task_commit, webkit
from backend.handoff import artifacts
from backend.handoff.api import handoff_router


class _FakeResult:
    def __init__(self, rows, rowcount):
        self._rows = rows
        self.rowcount = rowcount

    def all(self):
        return list(self._rows)


class _FakeAsyncSession:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt, params=None):
        sql = getattr(stmt, "text", str(stmt))
        cur = self._conn.execute(sql, params or {})
        rows = cur.fetchall() if cur.description else []
        return _FakeResult(rows, cur.rowcount)

    async def commit(self):
        self._conn.commit()


def test_global_uploads_and_read_attachment_without_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSISTANT_GLOBAL_UPLOADS_DIR", str(tmp_path / "global_uploads"))

    app = FastAPI()
    app.include_router(upload_router, prefix="/api/uploads")
    client = TestClient(app)

    res = client.post(
        "/api/uploads/thread-personal",
        data={"workspace_path": ""},
        files={"file": ("resumo.txt", b"Linha 1: Estudo de Docker\nLinha 2: Compose\n", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "resumo.txt"
    assert body["scope"] == "global"
    assert body["path"].startswith("@global/thread-personal/")

    listed = client.get("/api/uploads/thread-personal", params={"workspace_path": ""})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["name"] == "resumo.txt"

    content = assistant_tools.read_attachment.func(
        source=body["path"],
        config={"configurable": {"thread_id": "thread-personal"}},
    )
    assert "Estudo de Docker" in content
    assert "Compose" in content


def test_settings_store_toggles_and_ollama_vram_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSISTANT_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("TASK_AUTOCOMMIT_FILE", str(tmp_path / "autocommit.state"))
    monkeypatch.setattr(task_commit, "_RUNTIME_ENABLED", None)

    ps_models = [
        {
            "name": "qwen3-coder:30b",
            "size": 18_000_000_000,
            "size_vram": 15_000_000_000,
            "details": {"parameter_size": "30B", "quantization_level": "Q4_K_M"},
        }
    ]
    unloaded_calls = []

    def fake_ollama(path, payload=None, timeout=10):
        if path == "/api/ps":
            return {"models": list(ps_models)}
        if path == "/api/generate" and payload and payload.get("keep_alive") == 0:
            unloaded_calls.append(payload["model"])
            ps_models[:] = [m for m in ps_models if m["name"] != payload["model"]]
            return {"done": True}
        return {}

    monkeypatch.setattr(settings_controller, "_ollama_request", fake_ollama)

    app = FastAPI()
    app.include_router(settings_controller.settings_router, prefix="/api/settings")
    client = TestClient(app)

    res = client.put(
        "/api/settings",
        json={
            "web_search_enabled": False,
            "assistant_memory_enabled": False,
            "autocommit_enabled": False,
            "audit_tool_timeout": 0,
            "audit_chunk_size": 60,
        },
    )
    assert res.status_code == 200
    cfg = res.json()["settings"]
    assert cfg["web_search_enabled"] is False
    assert cfg["assistant_memory_enabled"] is False
    assert cfg["autocommit_enabled"] is False
    assert cfg["audit_tool_timeout"] == 0
    assert cfg["audit_chunk_size"] == 60
    assert webkit.web_enabled() is False
    assert memory.enabled() is False
    assert "desligada" in assistant_tools.web_search.func(query="teste").lower()

    ps = client.get("/api/settings/ollama/ps")
    assert ps.status_code == 200
    assert ps.json()["online"] is True
    assert len(ps.json()["models"]) == 1

    unload = client.post("/api/settings/ollama/unload", json={})
    assert unload.status_code == 200
    assert unload.json()["unloaded"] == ["qwen3-coder:30b"]
    assert unloaded_calls == ["qwen3-coder:30b"]
    assert unload.json()["ollama"]["models"] == []


def test_save_message_as_md_and_pdf_artifact(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "artifacts_phase1.db", check_same_thread=False)

    monkeypatch.setattr(artifacts, "async_session_env", lambda: _FakeAsyncSession(conn))
    monkeypatch.setattr(artifacts, "_ready", False)
    monkeypatch.setenv("TASK_PACK_DIR", str(tmp_path))

    app = FastAPI()
    app.include_router(handoff_router, prefix="/api/handoff")
    client = TestClient(app)

    try:
        res_md = client.post(
            "/api/handoff/artifacts/thread-notes",
            json={"title": "Resumo de Redes", "content": "# Redes\n\n- TCP\n- UDP\n", "format": "md"},
        )
        assert res_md.status_code == 200
        md_data = res_md.json()
        assert md_data["kind"] == "md"
        assert md_data["filename"].endswith(".md")

        res_pdf = client.post(
            "/api/handoff/artifacts/thread-notes",
            json={"title": "Resumo de Redes", "content": "# Redes\n\n- TCP\n- UDP\n", "format": "pdf"},
        )
        assert res_pdf.status_code == 200
        pdf_data = res_pdf.json()
        assert pdf_data["kind"] == "pdf"
        assert pdf_data["filename"].endswith(".pdf")

        pdf_dl = client.get(f"/api/handoff/packs/{pdf_data['filename']}")
        assert pdf_dl.status_code == 200
        assert pdf_dl.content.startswith(b"%PDF-")

        listed = client.get("/api/handoff/artifacts/thread-notes")
        assert listed.status_code == 200
        names = {item["filename"] for item in listed.json()["artifacts"]}
        assert md_data["filename"] in names
        assert pdf_data["filename"] in names
    finally:
        conn.close()
