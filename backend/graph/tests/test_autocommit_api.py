from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.controllers.tasks_controller import task_router
from backend.graph import task_commit


def test_autocommit_route_and_file_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_AUTOCOMMIT", "1")
    monkeypatch.setenv("TASK_AUTOCOMMIT_FILE", str(tmp_path / "autocommit.state"))
    monkeypatch.setattr(task_commit, "_RUNTIME_ENABLED", None)

    app = FastAPI()
    app.include_router(task_router, prefix="/api/tasks")
    client = TestClient(app)

    res = client.get("/api/tasks/autocommit")
    assert res.status_code == 200
    assert res.json() == {"enabled": True}

    res = client.put("/api/tasks/autocommit", json={"enabled": False})
    assert res.status_code == 200
    assert res.json() == {"enabled": False}

    # Simula reinicio/reload do servidor ou processo Celery separado
    monkeypatch.setattr(task_commit, "_RUNTIME_ENABLED", None)
    assert task_commit.enabled() is False
    assert client.get("/api/tasks/autocommit").json() == {"enabled": False}

    res = client.put("/api/tasks/autocommit", json={"enabled": True})
    assert res.status_code == 200
    assert res.json() == {"enabled": True}
    monkeypatch.setattr(task_commit, "_RUNTIME_ENABLED", None)
    assert task_commit.enabled() is True
