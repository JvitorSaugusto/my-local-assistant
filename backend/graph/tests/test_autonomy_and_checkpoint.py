import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.controllers.tasks_controller import task_router
from backend.graph import autonomy_config
from backend.graph.batch_checkpoint import get_checkpoint, rollback_checkpoint, save_checkpoint


def test_autonomy_config_defaults_and_bounds(tmp_path, monkeypatch):
    monkeypatch.setattr(autonomy_config, "_STORE_PATH", tmp_path / "autonomy.json")
    cfg = autonomy_config.get_autonomy_config()
    assert cfg["max_verify_retries"] == 3
    assert cfg["auto_heal_failed_tasks"] is True
    assert cfg["chat_readonly_mode"] is False

    updated = autonomy_config.update_autonomy_config({"max_verify_retries": 99, "chat_readonly_mode": True})
    assert updated["max_verify_retries"] == 5
    assert updated["chat_readonly_mode"] is True


def test_batch_checkpoint_save_and_rollback(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@local"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    f = tmp_path / "a.txt"
    f.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    cp = save_checkpoint("thread-cp", str(tmp_path), [1, 2])
    assert cp is not None
    assert get_checkpoint("thread-cp")["commit_sha"] == cp["commit_sha"]

    f.write_text("quebrado\n", encoding="utf-8")
    res = rollback_checkpoint("thread-cp")
    assert res["reverted"] is True
    assert f.read_text(encoding="utf-8") == "original\n"
    assert get_checkpoint("thread-cp") is None


def test_autonomy_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(autonomy_config, "_STORE_PATH", tmp_path / "autonomy_api.json")
    app = FastAPI()
    app.include_router(task_router, prefix="/api/tasks")
    client = TestClient(app)

    r1 = client.get("/api/tasks/autonomy")
    assert r1.status_code == 200
    assert r1.json()["autonomy"]["max_verify_retries"] == 3

    r2 = client.put("/api/tasks/autonomy", json={"max_verify_retries": 4, "auto_plan_tasks": False})
    assert r2.status_code == 200
    assert r2.json()["autonomy"]["max_verify_retries"] == 4
    assert r2.json()["autonomy"]["auto_plan_tasks"] is False
