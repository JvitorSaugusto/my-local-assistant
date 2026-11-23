import asyncio

from backend.api.quick_queue import QuickQueueManager, compose_queue_prompt, list_workspace_files


def test_compose_queue_prompt_and_workspace_file_listing(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "views.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("", encoding="utf-8")

    files = list_workspace_files(str(tmp_path), query="views")
    assert files == ["app/views.py"]

    prompt = compose_queue_prompt("Revise este arquivo", ["app/views.py"])
    assert "Revise este arquivo" in prompt
    assert "- app/views.py" in prompt
    assert "read_file_content" in prompt


def test_quick_queue_runs_sequentially_and_stops_on_error(monkeypatch):
    seen = []

    async def fake_run_graph_live(app_graph, inputs, config, thread_id):
        msg = inputs["messages"][0].content
        seen.append((msg, inputs.get("preset")))
        await asyncio.sleep(0.01)
        if "EXPLODE" in msg:
            raise RuntimeError("falha simulada")
        return {"messages": inputs["messages"]}

    monkeypatch.setattr("backend.api.quick_queue.run_graph_live", fake_run_graph_live)

    async def _run():
        mgr = QuickQueueManager()
        await mgr.start(
            app_graph=object(),
            thread_id="t-seq",
            items=[
                {"prompt": "Passo 1", "files": ["a.py"]},
                {"prompt": "Passo 2 EXPLODE", "files": []},
                {"prompt": "Passo 3 nunca roda", "files": []},
            ],
            workspace_path="",
            preset="direto",
            stop_on_error=True,
        )
        run = mgr._runs["t-seq"]
        await run.runner_task
        status = mgr.get_status("t-seq")
        assert status["running"] is False
        assert status["done"] == 1
        assert status["failed"] == 1
        assert status["cancelled"] == 1
        assert len(seen) == 2
        assert "- a.py" in seen[0][0]
        assert seen[0][1] == "direto"

    asyncio.run(_run())


def test_quick_queue_manual_stop_cancels_remaining(monkeypatch):
    started_event = asyncio.Event()

    async def slow_run_graph_live(app_graph, inputs, config, thread_id):
        started_event.set()
        await asyncio.sleep(5)
        return {"messages": inputs["messages"]}

    monkeypatch.setattr("backend.api.quick_queue.run_graph_live", slow_run_graph_live)

    async def _run():
        mgr = QuickQueueManager()
        await mgr.start(
            app_graph=object(),
            thread_id="t-stop",
            items=[{"prompt": "Longo 1"}, {"prompt": "Longo 2"}],
            workspace_path="",
        )
        await asyncio.wait_for(started_event.wait(), timeout=2)
        res = await mgr.stop("t-stop")
        assert res["stopped"] is True
        st = res["queue"]
        assert st["running"] is False
        assert st["cancelled"] == 2

    asyncio.run(_run())
