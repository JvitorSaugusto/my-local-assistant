import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "api" / "task_split.py"
_spec = importlib.util.spec_from_file_location("task_split_under_test", _PATH)
ts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ts)


def _rep(path, size=10, tag="x"):
    return {"op": "replace_text", "path": path, "old": tag + "a" * size, "new": tag + "b" * size, "occurrences": "one"}


def _task(steps, verify=None, files=None):
    return {"title": "T", "description": "D", "reason": "R", "files": files or [], "priority": "high",
            "status": "pending", "code_snippet": "snip", "steps": steps, "verify": verify or []}


def test_small_task_is_untouched():
    task = _task([_rep("a.py"), _rep("b.py")])
    assert ts.split_task(task, 10000, 8) == [task]


def test_dynamic_task_without_steps_is_untouched():
    task = _task([])
    assert ts.split_task(task, 10, 1) == [task]


def test_split_by_step_count_keeps_order():
    steps = [_rep(f"f{i}.py", tag=str(i)) for i in range(5)]
    parts = ts.split_task(_task(steps), 100000, 2)
    assert [len(p["steps"]) for p in parts] == [2, 2, 1]
    assert [p["title"] for p in parts] == ["T (1/3)", "T (2/3)", "T (3/3)"]
    flat = [s["path"] for p in parts for s in p["steps"]]
    assert flat == [f"f{i}.py" for i in range(5)]
    assert parts[0]["code_snippet"] == "snip" and parts[1]["code_snippet"] is None


def test_split_by_chars_and_oversized_step_alone():
    steps = [_rep("a.py", 50), _rep("b.py", 5000), _rep("c.py", 50)]
    parts = ts.split_task(_task(steps), 300, 99)
    assert [[s["path"] for s in p["steps"]] for p in parts] == [["a.py"], ["b.py"], ["c.py"]]


def test_verify_goes_to_last_touch_and_pytest_to_last():
    steps = [_rep("a.py", tag="1"), _rep("b.py", tag="2"), _rep("a.py", tag="3")]
    verify = [
        {"type": "python_syntax", "path": "b.py"},
        {"type": "contains", "path": "a.py", "text": "x"},
        {"type": "pytest", "path": "tests/test_a.py"},
        {"type": "file_exists", "path": "outro.py"},
    ]
    parts = ts.split_task(_task(steps, verify), 100000, 1)
    assert len(parts) == 3
    assert [c["type"] for c in parts[1]["verify"]] == ["python_syntax"]
    assert sorted(c["type"] for c in parts[2]["verify"]) == ["contains", "file_exists", "pytest"]
    assert parts[0]["verify"] == []


def test_files_follow_each_part_and_keep_original_order():
    steps = [_rep("b.py"), _rep("a.py"), _rep("novo.py")]
    parts = ts.split_task(_task(steps, files=["a.py", "b.py"]), 100000, 2)
    assert parts[0]["files"] == ["a.py", "b.py"]
    assert parts[1]["files"] == ["novo.py"]


def test_autosplit_can_be_disabled(monkeypatch):
    monkeypatch.setenv("TASK_AUTOSPLIT", "0")
    task = _task([_rep("a.py"), _rep("b.py")])
    assert ts.split_task(task, 10, 1) == [task]


def test_expand_tasks_accepts_dicts_and_models():
    class Fake:
        def model_dump(self):
            return _task([_rep("a.py"), _rep("b.py")])
    out = ts.expand_tasks([Fake(), _task([_rep("c.py")])])
    assert len(out) == 2


def _dtask(title, desc, files, **extra):
    return dict(_task([], files=files), title=title, description=desc, **extra)


def test_near_duplicate_tasks_in_same_batch_are_dropped():
    desc = "Modificar a função register_checkout em app/routers/movements_router.py para filtrar itens defeituosos ao calcular a quantidade disponível."
    a = _dtask("Corrigir saída de itens defeituosos", desc, ["app/routers/movements_router.py"])
    b = _dtask("Corrigir lógica de saída para itens defeituosos", desc + " Apenas itens não defeituosos contam.", ["app/routers/movements_router.py"])
    c = _dtask("Corrigir tela de relatório", "Ajustar o relatório mensal.", ["app/routers/reports_router.py"])
    kept, dropped = ts.drop_near_duplicates([a, b, c])
    assert [t["title"] for t in kept] == [a["title"], c["title"]]
    assert dropped == [b["title"]]


def test_audit_parts_and_different_files_are_never_dropped():
    desc = "Corrija somente os achados abaixo " * 10
    audit1 = _dtask("Auditoria: a.py (1 achado(s))", desc, ["a.py"])
    audit2 = _dtask("Auditoria: a.py (1 achado(s))", desc, ["a.py"])
    part1 = _dtask("Mudar x (1/2)", desc, ["a.py"])
    part2 = _dtask("Mudar x (2/2)", desc, ["a.py"])
    other = _dtask("Mudar x", desc, ["b.py"])
    kept, dropped = ts.drop_near_duplicates([audit1, audit2, part1, part2, other])
    assert len(kept) == 5 and dropped == []


def test_expand_tasks_drops_duplicates_and_can_be_disabled(monkeypatch):
    desc = "Ajustar a validação do CPF no cadastro de clientes para aceitar pontuação."
    batch = [_dtask("Ajustar validação do CPF", desc, ["app/cpf.py"]), _dtask("Ajustar validação de CPF", desc, ["app/cpf.py"])]
    assert len(ts.expand_tasks(batch)) == 1
    monkeypatch.setenv("TASK_DEDUPE", "0")
    assert len(ts.expand_tasks(batch)) == 2
