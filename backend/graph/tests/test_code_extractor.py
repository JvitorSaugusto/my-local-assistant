from pathlib import Path

from backend.graph import code_extractor


def test_extract_snippets_python_method_and_full_class(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_PACK_DIR", str(tmp_path / "_packs"))
    app_dir = tmp_path / "god-backend" / "app" / "services"
    app_dir.mkdir(parents=True)

    sample = (
        "class PortalSyncService:\n"
        "    DEFAULT_ROLE = 'Operador'\n\n"
        "    def _sync_user_to_god(self, cargo: str):\n"
        "        mapping = {\n"
        "            'cliente': 'Gestor',\n"
        "            'tecnico': 'Administrador',\n"
        "        }\n"
        "        return mapping.get(cargo, self.DEFAULT_ROLE)\n\n"
        "    def other_method(self):\n"
        "        return 123\n"
    )
    (app_dir / "user_sync.py").write_text(sample, encoding="utf-8")

    res_method = code_extractor.extract_snippets(
        workspace_path=str(tmp_path),
        queries=["Gestor", "nao_existe_xyz"],
        subpath="god-backend/app",
        include_full_class=False,
        save_txt="never",
    )
    assert len(res_method["blocks"]) == 1
    blk = res_method["blocks"][0]
    assert blk["path"] == "god-backend/app/services/user_sync.py"
    assert "class PortalSyncService > def _sync_user_to_god" in blk["scope"]
    assert "other_method" not in res_method["formatted"]
    assert res_method["not_found"] == ["nao_existe_xyz"]

    res_class = code_extractor.extract_snippets(
        workspace_path=str(tmp_path),
        queries=["Gestor"],
        subpath="god-backend/app",
        include_full_class=True,
        save_txt="always",
    )
    assert len(res_class["blocks"]) == 1
    assert "class PortalSyncService (linhas" in res_class["blocks"][0]["scope"]
    assert "other_method" in res_class["formatted"]
    assert res_class["txt_url"].startswith("/api/handoff/packs/trechos_")
    assert Path(res_class["txt_path"]).is_file()


def test_extract_snippets_blocks_secret_files_and_traversal(tmp_path):
    (tmp_path / ".env").write_text("SECRET_TOKEN=Gestor123\n", encoding="utf-8")
    res = code_extractor.extract_snippets(str(tmp_path), ["Gestor123"], save_txt="never")
    assert res["blocks"] == []

    trav = code_extractor.extract_snippets(str(tmp_path), ["x"], subpath="../fora", save_txt="never")
    assert "ERRO DE SEGURANÇA" in trav["error"]
