from types import SimpleNamespace

from backend.api import live_thoughts


def test_humanize_tool_calls_and_cross_process_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(live_thoughts, "_LIVE_DIR", tmp_path)

    assert "📖 Lendo" in live_thoughts.humanize_tool_call("read_file_content", '{"file_path": "backend/graph/nodes.py"}')
    assert "📝 Criando" in live_thoughts.humanize_tool_call("create_new_file", '{"file_path": "tests/test_a.py"}')
    assert "🧪 Rodando testes" in live_thoughts.humanize_tool_call("run_tests", '{"path": "tests/test_a.py"}')
    assert "✏️ Editando" in live_thoughts.humanize_tool_call("edit_existing_file", '{"file_path": "a.py", "start_line": 10, "end_line": 20}')

    buf = live_thoughts.live_start("thread-celery-1", persist=True)
    buf.add_state([SimpleNamespace(type="human", content="start")])
    buf.add_state([
        SimpleNamespace(type="human", content="start"),
        SimpleNamespace(
            type="ai",
            name="Qwen3-Coder",
            content="",
            tool_calls=[{"name": "read_file_content", "args": {"file_path": "app/views.py"}}],
        ),
    ])
    buf.add_state([
        SimpleNamespace(type="human", content="start"),
        SimpleNamespace(
            type="ai",
            name="Qwen3-Coder",
            content="",
            tool_calls=[{"name": "read_file_content", "args": {"file_path": "app/views.py"}}],
        ),
        SimpleNamespace(type="tool", name="read_file_content", content="line1\nline2"),
    ])
    # Simula outro processo (FastAPI sem o buffer em memória) lendo o snapshot gravado pelo Celery
    live_thoughts.LIVE.clear()
    snap = live_thoughts.live_snapshot("thread-celery-1", after=-1)
    assert snap["running"] is True
    assert snap["changed"] is True
    assert "app/views.py" in snap["headline"]
    assert len(snap["actions"]) >= 1
    assert "Concluído" in snap["actions"][0].get("detail", "")
