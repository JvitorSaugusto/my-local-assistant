import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.controllers.monitor_controller import monitor_router
from backend.graph import dev_tools


def test_parse_auth_headers_formats_and_injection_guard():
    assert dev_tools._parse_auth_headers("") == {}
    assert dev_tools._parse_auth_headers("meu-token-123") == {"Authorization": "Bearer meu-token-123"}
    assert dev_tools._parse_auth_headers("Bearer abc") == {"Authorization": "Bearer abc"}
    assert dev_tools._parse_auth_headers("Cookie: sessionid=xyz") == {"Cookie": "sessionid=xyz"}
    assert dev_tools._parse_auth_headers("X-API-Key: k1\r\nEvil: 1") == {}


def test_route_suite_sends_auth_header(monkeypatch):
    seen_headers = []

    class FakeResp:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self, n=-1):
            return b'{"user": "ok"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=8):
        seen_headers.append(dict(req.header_items()))
        return FakeResp()

    monkeypatch.setattr(dev_tools.urllib.request, "urlopen", fake_urlopen)

    app = FastAPI()
    app.include_router(monitor_router, prefix="/api/monitor")
    client = TestClient(app)

    res = client.post(
        "/api/monitor/test-routes",
        json={"base_url": "http://127.0.0.1:8000", "routes": "/api/me", "auth_header": "tok_999"},
    )
    assert res.status_code == 200
    assert res.json()["passed"][0]["path"] == "/api/me"
    assert any(h.get("Authorization") == "Bearer tok_999" for h in seen_headers)


def test_git_quick_status_diff_and_commit(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@local"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)

    f = tmp_path / "hello.txt"
    f.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    f.write_text("v2\n", encoding="utf-8")

    app = FastAPI()
    app.include_router(monitor_router, prefix="/api/monitor")
    client = TestClient(app)

    st = client.get("/api/monitor/git/status", params={"workspace_path": str(tmp_path)})
    assert st.status_code == 200
    assert st.json()["clean"] is False
    assert st.json()["files"][0]["path"] == "hello.txt"

    df = client.get("/api/monitor/git/diff", params={"workspace_path": str(tmp_path), "file": "hello.txt"})
    assert df.status_code == 200
    assert "+v2" in df.json()["diff"]

    cm = client.post("/api/monitor/git/commit", json={"workspace_path": str(tmp_path), "message": "update hello"})
    assert cm.status_code == 200
    assert cm.json()["committed"] is True

    st2 = client.get("/api/monitor/git/status", params={"workspace_path": str(tmp_path)})
    assert st2.json()["clean"] is True
