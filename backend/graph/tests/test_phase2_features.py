import asyncio
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from backend.api import chat_meta, chat_search
from backend.api.controllers.chat_controller import chat_router, get_chat_service
from backend.graph import presets


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


def test_chat_meta_crud_and_partial_updates(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "chat_meta.db", check_same_thread=False)
    monkeypatch.setattr(chat_meta, "async_session_env", lambda: _FakeAsyncSession(conn))
    monkeypatch.setattr(chat_meta, "_ready", False)

    async def _run():
        assert await chat_meta.get_meta("t1") == {"pinned": False, "folder": "", "tags": []}

        saved = await chat_meta.upsert_meta("t1", pinned=True, folder="  Estudos ", tags=["#Docker", "FastAPI", "docker"])
        assert saved == {"pinned": True, "folder": "Estudos", "tags": ["Docker", "FastAPI"]}

        # Atualização parcial: mexer só em pinned preserva folder e tags
        toggled = await chat_meta.upsert_meta("t1", pinned=False)
        assert toggled == {"pinned": False, "folder": "Estudos", "tags": ["Docker", "FastAPI"]}

        all_meta = await chat_meta.list_all_meta()
        assert "t1" in all_meta
        assert all_meta["t1"]["folder"] == "Estudos"

        await chat_meta.delete_meta("t1")
        assert await chat_meta.get_meta("t1") == {"pinned": False, "folder": "", "tags": []}

    try:
        asyncio.run(_run())
    finally:
        conn.close()


def test_global_message_search_and_presets_endpoints():
    class FakeGraph:
        def __init__(self, by_thread):
            self.by_thread = by_thread

        async def aget_state(self, config):
            tid = config["configurable"]["thread_id"]
            return SimpleNamespace(values={"messages": self.by_thread.get(tid, [])})

    class FakeChatService:
        async def list_chats(self):
            return [
                {
                    "id": 1,
                    "thread_id": "t-recipes",
                    "title": "Receitas da semana",
                    "created_at": "2026-11-20T10:00:00",
                    "pinned": True,
                    "folder": "Pessoal",
                    "tags": ["cozinha"],
                },
                {
                    "id": 2,
                    "thread_id": "t-study",
                    "title": "Estudo de Redes",
                    "created_at": "2026-11-21T08:00:00",
                    "pinned": False,
                    "folder": "Estudos",
                    "tags": ["tcp"],
                },
            ]

    fake_graph = FakeGraph(
        {
            "t-recipes": [
                HumanMessage(id="m1", content="Como fazer pão algodão com tangzhong sem leite?"),
                AIMessage(id="m2", content="Use leite de coco e óleo vegetal para manter a massa macia."),
            ],
            "t-study": [
                HumanMessage(id="m3", content="Qual a diferença entre TCP e UDP?"),
                AIMessage(id="m4", content="TCP garante entrega ordenada via handshake; UDP é mais rápido."),
            ],
        }
    )

    app = FastAPI()
    app.state.compiled_graph = fake_graph
    app.dependency_overrides[get_chat_service] = lambda: FakeChatService()
    app.include_router(chat_router, prefix="/api/chats")
    client = TestClient(app)

    # Busca sem acento encontra texto com acento dentro das mensagens
    res = client.get("/api/chats/search", params={"q": "pao algodao"})
    assert res.status_code == 200
    items = res.json()["results"]
    assert len(items) == 1
    assert items[0]["chat_id"] == 1
    assert items[0]["match_in"] == "message"
    assert items[0]["message_id"] == "m1"
    assert "algodão" in items[0]["snippet"].lower()

    # Busca encontra resposta do assistente
    res2 = client.get("/api/chats/search", params={"q": "handshake"})
    assert res2.status_code == 200
    assert res2.json()["results"][0]["chat_id"] == 2
    assert res2.json()["results"][0]["role"] == "assistant"

    # Presets disponíveis via API e blocos de prompt
    res_p = client.get("/api/chats/presets")
    assert res_p.status_code == 200
    ids = {p["id"] for p in res_p.json()["presets"]}
    assert {"default", "tutor", "revisor", "planejador", "direto"}.issubset(ids)
    assert presets.preset_prompt_block("default") is None
    assert "TUTOR SOCRÁTICO" in (presets.preset_prompt_block("tutor") or "")
    assert presets.normalize_preset("desconhecido") == "default"
