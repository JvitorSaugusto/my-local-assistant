from backend.graph.executor import execute_task_sync


def test_move_file_creates_parent_and_is_idempotent(tmp_path):
    src = tmp_path / "dashboard" / "app" / "ops" / "page.tsx"
    src.parent.mkdir(parents=True)
    src.write_text("export default function Page() { return null; }\n", encoding="utf-8")

    task = {
        "steps": [
            {
                "op": "move_file",
                "source": "dashboard/app/ops/page.tsx",
                "destination": "dashboard/app/monitor/page.tsx",
            }
        ],
        "verify": [
            {"type": "file_exists", "path": "dashboard/app/monitor/page.tsx"},
        ],
    }

    first = execute_task_sync(task, str(tmp_path))
    assert first.ok, first.error
    assert first.log[0]["status"] == "ok"
    assert not src.exists()
    dst = tmp_path / "dashboard" / "app" / "monitor" / "page.tsx"
    assert dst.is_file()
    assert "export default function Page()" in dst.read_text(encoding="utf-8")

    # Reexecutar deve ser idempotente (skipped)
    second = execute_task_sync(task, str(tmp_path))
    assert second.ok, second.error
    assert second.log[0]["status"] == "skipped"


def test_move_file_respects_overwrite_flag(tmp_path):
    (tmp_path / "a.txt").write_text("novo", encoding="utf-8")
    (tmp_path / "b.txt").write_text("antigo", encoding="utf-8")

    blocked = execute_task_sync(
        {"steps": [{"op": "move_file", "source": "a.txt", "destination": "b.txt"}]},
        str(tmp_path),
    )
    assert not blocked.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "novo"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "antigo"

    allowed = execute_task_sync(
        {"steps": [{"op": "move_file", "source": "a.txt", "destination": "b.txt", "overwrite": True}]},
        str(tmp_path),
    )
    assert allowed.ok, allowed.error
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "novo"


def test_move_file_rolls_back_on_verify_failure(tmp_path):
    src = tmp_path / "old.py"
    src.write_text("VALUE = 1\n", encoding="utf-8")

    task = {
        "steps": [
            {"op": "move_file", "source": "old.py", "destination": "pkg/new.py"},
        ],
        "verify": [
            {"type": "contains", "path": "pkg/new.py", "text": "NAO_EXISTE"},
        ],
    }

    res = execute_task_sync(task, str(tmp_path))
    assert not res.ok
    assert src.is_file()
    assert src.read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (tmp_path / "pkg" / "new.py").exists()


def test_move_file_rejects_outside_workspace(tmp_path):
    (tmp_path / "inside.txt").write_text("ok", encoding="utf-8")
    res = execute_task_sync(
        {"steps": [{"op": "move_file", "source": "inside.txt", "destination": "../outside.txt"}]},
        str(tmp_path),
    )
    assert not res.ok
    assert (tmp_path / "inside.txt").is_file()
