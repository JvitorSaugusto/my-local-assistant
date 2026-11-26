from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.graph import code_extractor, nodes


def test_extract_snippets_accepts_multiple_comma_separated_subpaths(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_PACK_DIR", str(tmp_path / "_packs"))
    app_dir = tmp_path / "god-backend" / "app"
    routers = app_dir / "routers"
    routers.mkdir(parents=True)

    (routers / "auth.py").write_text(
        "@router.post('/api/auth/jwt/')\n"
        "async def jwt_login():\n"
        "    return {'access': 'ok'}\n",
        encoding="utf-8",
    )
    (app_dir / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "from app.routers import auth\n"
        "app = FastAPI()\n"
        "app.include_router(auth.router)\n",
        encoding="utf-8",
    )

    res = code_extractor.extract_snippets(
        workspace_path=str(tmp_path),
        queries=["auth/jwt/", "include_router"],
        subpath="god-backend/app/routers, god-backend/app/main.py",
        save_txt="always",
    )
    paths = [b["path"] for b in res["blocks"]]
    assert "god-backend/app/routers/auth.py" in paths
    assert "god-backend/app/main.py" in paths
    assert res["not_found"] == []
    assert res["txt_url"] and res["txt_url"].startswith("/api/handoff/packs/trechos_")


def test_extract_snippets_blocks_secret_file_in_multi_subpath(tmp_path):
    (tmp_path / ".env").write_text("SECRET_KEY=topsecret\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("def boot():\n    return 'topsecret'\n", encoding="utf-8")

    res = code_extractor.extract_snippets(
        workspace_path=str(tmp_path),
        queries=["topsecret"],
        subpath=".env, main.py",
        save_txt="never",
    )
    paths = [b["path"] for b in res["blocks"]]
    assert paths == ["main.py"]


def test_unread_mentioned_files_detects_only_existing_unread_files(tmp_path):
    app_dir = tmp_path / "god-backend" / "app"
    routers = app_dir / "routers"
    routers.mkdir(parents=True)
    (app_dir / "main.py").write_text("app = FastAPI()\n", encoding="utf-8")
    (routers / "auth.py").write_text("# auth\n", encoding="utf-8")

    prompt = (
        "Verifique god-backend/app/routers/internal_portal.py (provável), "
        "god-backend/app/routers/auth.py e god-backend/app/main.py."
    )
    msgs = [
        HumanMessage(content=prompt),
        AIMessage(
            content="",
            tool_calls=[{"name": "read_file_content", "args": {"file_path": "god-backend/app/routers/auth.py"}, "id": "1"}],
        ),
        ToolMessage(content="# auth", tool_call_id="1", name="read_file_content"),
    ]
    unread = nodes._unread_mentioned_files(prompt, str(tmp_path), msgs)
    assert unread == ["god-backend/app/main.py"]

    msgs.append(
        AIMessage(
            content="",
            tool_calls=[{"name": "read_file_content", "args": {"file_path": "god-backend/app/main.py"}, "id": "2"}],
        )
    )
    assert nodes._unread_mentioned_files(prompt, str(tmp_path), msgs) == []


def test_code_node_reminds_once_for_unread_mentioned_file(tmp_path, monkeypatch):
    app_dir = tmp_path / "god-backend" / "app"
    routers = app_dir / "routers"
    routers.mkdir(parents=True)
    (routers / "auth.py").write_text("@router.post('/api/auth/jwt/')\n", encoding="utf-8")
    (app_dir / "main.py").write_text("app = FastAPI()\napp.include_router(auth.router)\n", encoding="utf-8")

    calls = []

    class FakeCodeLLM:
        def invoke(self, context):
            calls.append(context)
            if len(calls) == 1:
                return AIMessage(content="Chutei o prefixo do main.py sem ler.", tool_calls=[])
            return AIMessage(
                content="",
                tool_calls=[{"name": "read_file_content", "args": {"file_path": "god-backend/app/main.py"}, "id": "c1"}],
            )

    monkeypatch.setattr(nodes, "code_llm_with_tools", FakeCodeLLM())
    monkeypatch.setattr(nodes, "code_llm", FakeCodeLLM())

    # Simula o cenário real: o modelo já leu auth.py, mas tentou responder sem ler main.py
    prior_msgs = [
        HumanMessage(content="Confirma a rota JWT em god-backend/app/routers/auth.py e god-backend/app/main.py"),
        AIMessage(
            content="",
            tool_calls=[{"name": "read_file_content", "args": {"file_path": "god-backend/app/routers/auth.py"}, "id": "a1"}],
        ),
        ToolMessage(content="@router.post('/api/auth/jwt/')", tool_call_id="a1", name="read_file_content"),
    ]

    state = {
        "messages": list(prior_msgs),
        "workspace_path": str(tmp_path),
        "summary": "",
        "preset": "default",
    }
    out = nodes.code_node(state)
    msg = out["messages"][-1]
    assert len(calls) == 2
    assert msg.additional_kwargs.get("missing_files_reminded") is True
    assert msg.tool_calls and msg.tool_calls[0]["args"]["file_path"] == "god-backend/app/main.py"

    # Se já houve lembrete nesta rodada, não repete (sem loop)
    calls.clear()
    state_after_remind = {
        "messages": prior_msgs + [AIMessage(content="Tentativa", additional_kwargs={"missing_files_reminded": True})],
        "workspace_path": str(tmp_path),
        "summary": "",
        "preset": "default",
    }
    out2 = nodes.code_node(state_after_remind)
    assert len(calls) == 1
    assert "Chutei" in out2["messages"][-1].content
