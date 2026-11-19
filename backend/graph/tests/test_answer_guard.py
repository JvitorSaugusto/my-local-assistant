import importlib.util
import pathlib


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ag = _load("answer_guard")


def test_scrub_removes_dossie():
    out = ag.scrub_meta_references("O dossiê não contém nenhum arquivo .bat")
    assert "dossi" not in out.lower()
    assert out.startswith("Não encontrei")


def test_scrub_keeps_code_blocks():
    text = "Veja:\n```python\nprint('tool calls')\n```\nSegundo o dossiê, ok."
    out = ag.scrub_meta_references(text)
    assert "print('tool calls')" in out
    assert "dossi" not in out.lower()


def test_detect_repetition_extension_loop():
    letters = "abcdefghijklmnopqrstuvwxyz"
    text = " ".join(".x%s%s," % (a, b) for a in letters for b in letters)
    assert ag.detect_repetition(text) is True


def test_detect_repetition_normal_text():
    assert ag.detect_repetition("A função chat_with_ai inicia o grafo e devolve a resposta ao frontend.") is False


def test_ground_answer_flags_invented_name():
    corpus = "function toggleSourceLink() openSourcesMenu /api/rag/links backend/static/script.js"
    answer = "Veja `toggleSourceLink()` e `_pasteToQueue` em `backend/static/script.js` e `/api/rag/links`."
    text, invalid = ag.ground_answer(answer, corpus)
    assert invalid == ["_pasteToQueue"]
    assert "`_pasteToQueue` (não confirmado no código)" in text
    assert "`toggleSourceLink()`" in text


def test_route_with_router_prefix_is_not_flagged():
    corpus = '@rag_router.put("/links")'
    text, invalid = ag.ground_answer("Use `/api/rag/links`.", corpus)
    assert invalid == []


def test_missing_route_and_file_flagged():
    text, invalid = ag.ground_answer("Use `/api/nao/existe` e `foo/bar.py`.", "nada aqui")
    assert "/api/nao/existe" in invalid
    assert "foo/bar.py" in invalid


def test_names_not_checked_without_dossier():
    text, invalid = ag.ground_answer("Use `minha_funcao_x`.", "", check_names=False)
    assert invalid == []


def test_finalize_answer():
    result = ag.finalize_answer("Segundo o dossiê, use `minhaFuncao_x`.", "texto sem a funcao")
    assert "dossi" not in result["text"].lower()
    assert result["invalid"] == ["minhaFuncao_x"]
    assert result["degenerate"] is False


def test_wants_raw_output():
    assert ag.wants_raw_output("me dá o retorno bruto do generate_repo_map") is True
    assert ag.wants_raw_output("explique o fluxo") is False


def test_needs_code_reading_flags_ungrounded_bug_diagnosis():
    from backend.graph.answer_guard import needs_code_reading

    assert needs_code_reading(
        "estou com problema ao dar saída em item quebrado",
        "No arquivo app/routers/movements_router.py, a função `register_checkout` não filtra `is_defective`.",
    )
    assert not needs_code_reading(
        "qual a diferença entre lista e tupla em python?",
        "Listas são mutáveis e tuplas são imutáveis.",
    )


def test_planner_rejects_diff_review_warning(tmp_path):
    import asyncio
    from backend.handoff.planner import Edit, Plan, plan_and_check

    target = tmp_path / "mod.py"
    target.write_text("def checkout(item):\n    return item.quantity\n", encoding="utf-8")

    class FakePlannerLLM:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return Plan(edits=[Edit(kind="replace_lines", path="mod.py", start_line=2, end_line=2, new_text="    if item.is_defective:\n        return 0\n    return item.quantity")])
            return Plan(edits=[], missing="Campo is_defective não existe no projeto.")

    def fake_runner(task, workspace, thread_id):
        from backend.graph.executor import TaskRunResult
        return TaskRunResult(
            ok=True,
            log=[{"index": 0, "total": 1, "label": "revisão do diff", "status": "warn", "detail": "risco alto: revisão do diff: mod.py: usa is_defective"}],
        )

    outcome = asyncio.run(
        plan_and_check(
            str(tmp_path),
            {"title": "Filtrar quebrados", "description": "Checar is_defective", "files": ["mod.py"]},
            llm=FakePlannerLLM(),
            runner=fake_runner,
            max_retries=1,
        )
    )
    assert outcome["ok"] is False
    assert "is_defective" in outcome["error"]
