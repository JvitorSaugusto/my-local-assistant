from types import SimpleNamespace

from backend.graph import code_extractor
from backend.graph.tools import _edit_phase_block, search_in_file


def test_search_in_file_handles_directory_recursively_without_permission_error(tmp_path):
    routers = tmp_path / "god-backend" / "app" / "routers"
    routers.mkdir(parents=True)
    (routers / "portal_internal.py").write_text(
        "@router.post('/api/internal/portal/users/sync')\n"
        "def sync_portal_user():\n"
        "    return {'role': 'Gestor'}\n",
        encoding="utf-8",
    )
    (tmp_path / "god-backend" / ".env").write_text("SECRET=users/sync\n", encoding="utf-8")

    runtime = SimpleNamespace(state={"workspace_path": str(tmp_path), "messages": []})
    out = search_in_file.func(file_path="god-backend/app", pattern="users/sync", runtime=runtime)

    assert "Permission denied" not in out
    assert "god-backend/app/routers/portal_internal.py:1:" in out
    assert ".env" not in out


def test_edit_phase_block_only_applies_to_active_generate_task():
    ai_msg = SimpleNamespace(
        type="ai",
        tool_calls=[{"name": "read_file_content", "args": {"file_path": "a.py"}}],
    )
    # Em modo chat/code (sem active_generate_task), nunca deve bloquear leitura nem pedir SEM_ALTERACOES
    chat_runtime = SimpleNamespace(
        state={
            "messages": [SimpleNamespace(type="human", content="oi")] + [ai_msg] * 20,
            "active_generate_task": None,
        }
    )
    assert _edit_phase_block(chat_runtime, "read_file_content") is None

    # Em uma task ativa do Generate, a trava continua funcionando normalmente
    gen_runtime = SimpleNamespace(
        state={
            "messages": [SimpleNamespace(type="human", content="task")] + [ai_msg] * 20,
            "active_generate_task": SimpleNamespace(id=1),
        }
    )
    blocked = _edit_phase_block(gen_runtime, "read_file_content")
    assert blocked is not None and "FERRAMENTA DESATIVADA" in blocked


def test_code_extractor_strips_redundant_workspace_root_prefix(tmp_path):
    ws = tmp_path / "god-backend"
    app_dir = ws / "app" / "routers"
    app_dir.mkdir(parents=True)
    (app_dir / "auth.py").write_text(
        "def login_jwt():\n    return '/api/auth/jwt/'\n",
        encoding="utf-8",
    )

    # Workspace já é .../god-backend, mas o usuário informou subpath='god-backend/app'
    res = code_extractor.extract_snippets(
        workspace_path=str(ws),
        queries=["auth/jwt"],
        subpath="god-backend/app",
        save_txt="never",
    )
    assert not res.get("error")
    assert len(res["blocks"]) == 1
    assert res["blocks"][0]["path"] == "app/routers/auth.py"
