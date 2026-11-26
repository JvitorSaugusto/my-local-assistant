from pathlib import Path

from backend.graph import code_extractor


def test_sync_does_not_match_async_or_async_session_and_reaches_routers(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_PACK_DIR", str(tmp_path / "_packs"))
    core = tmp_path / "god-backend" / "app" / "core"
    routers = tmp_path / "god-backend" / "app" / "routers"
    migrations = tmp_path / "god-backend" / "app" / "migrations"
    core.mkdir(parents=True)
    routers.mkdir(parents=True)
    migrations.mkdir(parents=True)

    # 30 arquivos em core/ usando async/AsyncSession (não devem poluir a busca por 'sync')
    for idx in range(30):
        (core / f"helper_{idx:02d}.py").write_text(
            "from sqlalchemy.ext.asyncio import AsyncSession\n\n"
            f"async def util_{idx}(db: AsyncSession):\n"
            "    return await db.execute('select 1')\n",
            encoding="utf-8",
        )

    # Migrations devem ser ignoradas por padrão
    (migrations / "0001_init.py").write_text(
        "def upgrade():\n    cargo = 'Gestor'\n",
        encoding="utf-8",
    )

    # Alvos reais em routers/ (alfabeticamente depois de core/)
    (routers / "portal_internal.py").write_text(
        "@router.post('/api/internal/portal/users/sync')\n"
        "async def portal_sync_user(payload, db: AsyncSession):\n"
        "    return {'cargo': payload.cargo, 'origin': payload.origin}\n",
        encoding="utf-8",
    )
    (routers / "auth.py").write_text(
        "@router.post('/api/auth/jwt/')\n"
        "async def jwt_login(request, db: AsyncSession):\n"
        "    return {'access': 'tok'}\n",
        encoding="utf-8",
    )

    res = code_extractor.extract_snippets(
        workspace_path=str(tmp_path),
        queries=[
            "api/internal/portal/users/sync",
            "sync",
            "auth/jwt/",
            "Gestor",
            "GOD_JWT_LOGIN_PATH",
        ],
        subpath="god-backend/app",
        save_txt="always",
        max_blocks=10,
    )

    paths = [b["path"] for b in res["blocks"]]
    assert not any("helper_" in p for p in paths)
    assert not any("migrations" in p for p in paths)
    assert "god-backend/app/routers/portal_internal.py" in paths[:2]
    assert "god-backend/app/routers/auth.py" in paths[:2]
    assert res["not_found"] == ["Gestor", "GOD_JWT_LOGIN_PATH"]
    assert res["txt_url"] and Path(res["txt_path"]).is_file()


def test_overlapping_module_windows_are_merged_without_duplicates(tmp_path):
    app_dir = tmp_path / "app" / "core"
    app_dir.mkdir(parents=True)
    (app_dir / "permissions_catalog.py").write_text(
        "MODULES = ['a', 'b']\n"
        "# cargo 1\n"
        "DEFAULT_PRESETS = {\n"
        "    'Administrador': ['all'],\n"
        "    'Gestor': ['all'],\n"
        "    'Supervisor': ['read'],\n"
        "    # cargo 2\n"
        "    'Operador': ['read'],\n"
        "}\n",
        encoding="utf-8",
    )

    res = code_extractor.extract_snippets(
        workspace_path=str(tmp_path),
        queries=["cargo", "Supervisor", "Gestor"],
        subpath="app",
        save_txt="never",
    )
    assert len(res["blocks"]) == 1
    blk = res["blocks"][0]
    assert blk["path"] == "app/core/permissions_catalog.py"
    assert set(blk["matches"]) == {"cargo", "Supervisor", "Gestor"}


def test_fair_per_query_coverage_when_one_term_is_noisy(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)
    for idx in range(15):
        (app_dir / f"a_noisy_{idx:02d}.py").write_text(
            f"def fn_{idx}():\n    return 'Gestor'\n",
            encoding="utf-8",
        )
    (app_dir / "z_target.py").write_text(
        "def ensure_internal_root():\n    return 'root@esolvere.internal'\n",
        encoding="utf-8",
    )

    res = code_extractor.extract_snippets(
        workspace_path=str(tmp_path),
        queries=["Gestor", "esolvere"],
        subpath="app",
        save_txt="never",
        max_blocks=5,
    )
    paths = [b["path"] for b in res["blocks"]]
    assert "app/z_target.py" in paths
    assert len(res["blocks"]) == 5
