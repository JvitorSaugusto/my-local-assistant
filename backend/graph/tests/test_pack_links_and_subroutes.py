from langchain_core.messages import ToolMessage

from backend.graph import code_extractor, nodes


def test_code_extractor_subroute_fallback_finds_fastapi_split_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_PACK_DIR", str(tmp_path / "_packs"))
    routers = tmp_path / "god-backend" / "app" / "routers"
    routers.mkdir(parents=True)
    (routers / "portal_internal.py").write_text(
        "router = APIRouter(prefix='/api/internal/portal')\n\n"
        "@router.post('/users/sync')\n"
        "async def sync_portal_user(payload: dict):\n"
        "    return {'role': 'Gestor'}\n",
        encoding="utf-8",
    )

    res = code_extractor.extract_snippets(
        workspace_path=str(tmp_path),
        queries=["/api/internal/portal/users/sync"],
        subpath="god-backend/app",
        save_txt="always",
    )
    assert len(res["blocks"]) == 1
    assert "sync_portal_user" in res["blocks"][0]["scope"]
    assert res["not_found"] == []
    assert res["txt_url"].startswith("/api/handoff/packs/trechos_")


def test_ensure_pack_links_repairs_broken_domain_and_appends_missing():
    msgs = [
        ToolMessage(
            content="Arquivo `.txt` completo gerado: [trechos_20261124_153618_app.txt](/api/handoff/packs/trechos_20261124_153618_app.txt)",
            tool_call_id="1",
            name="extract_code_snippets",
        )
    ]
    broken = "Veja aqui: [trechos_20261124_153618_app.txt](http://api.handoff/packs/trechos_20261124_153618_app.txt)"
    fixed = nodes._ensure_pack_links(broken, msgs)
    assert "(/api/handoff/packs/trechos_20261124_153618_app.txt)" in fixed
    assert "api.handoff" not in fixed

    no_link = "Resumo pronto sem link."
    appended = nodes._ensure_pack_links(no_link, msgs)
    assert "[trechos_20261124_153618_app.txt](/api/handoff/packs/trechos_20261124_153618_app.txt)" in appended
