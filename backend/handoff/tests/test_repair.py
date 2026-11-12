import importlib.util
import pathlib
import tempfile


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rp = _load("repair")


def _write(tmp, name, text):
    pathlib.Path(tmp, name).write_bytes(text.encode("utf-8"))


def test_repairs_trailing_spaces_and_crlf():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "a.py", "def f():\r\n    x = 1   \r\n    \r\n    return x\r\n")
        steps = [{"op": "replace_text", "path": "a.py", "old": "    x = 1\n\n    return x\n", "new": "    x = 2\n\n    return x\n", "occurrences": "one"}]
        fixed, notes = rp.repair_steps(tmp, steps)
        assert len(notes) == 1
        assert fixed[0]["old"] == "    x = 1   \n    \n    return x\n"
        assert fixed[0]["new"] == "    x = 2\n\n    return x\n"


def test_exact_match_is_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "a.py", "a = 1\nb = 2\n")
        steps = [{"op": "replace_text", "path": "a.py", "old": "b = 2\n", "new": "b = 3\n", "occurrences": "one"}]
        fixed, notes = rp.repair_steps(tmp, steps)
        assert notes == []
        assert fixed[0]["old"] == "b = 2\n"


def test_reindents_new_when_indent_differs():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "a.py", "def f():\n  y = 1\n")
        steps = [{"op": "replace_text", "path": "a.py", "old": "    y = 1\n", "new": "    y = 2\n", "occurrences": "one"}]
        fixed, notes = rp.repair_steps(tmp, steps)
        assert len(notes) == 1
        assert fixed[0]["old"] == "  y = 1\n"
        assert fixed[0]["new"] == "  y = 2\n"


def test_ambiguous_block_is_not_repaired():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "a.py", "x = 1 \nx = 1  \n")
        steps = [{"op": "replace_text", "path": "a.py", "old": "x = 1\n", "new": "x = 2\n", "occurrences": "one"}]
        fixed, notes = rp.repair_steps(tmp, steps)
        assert notes == []
        assert fixed[0]["old"] == "x = 1\n"


def test_single_line_without_newline_is_not_repaired():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "a.py", "    z = 1 \n")
        steps = [{"op": "replace_text", "path": "a.py", "old": "z = 1", "new": "z = 2", "occurrences": "one"}]
        fixed, notes = rp.repair_steps(tmp, steps)
        assert notes == []


def test_later_step_sees_earlier_edit():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "a.py", "a = 1 \nb = 2\n")
        steps = [
            {"op": "replace_text", "path": "a.py", "old": "a = 1\n", "new": "a = 1\nc = 3\n", "occurrences": "one"},
            {"op": "replace_text", "path": "a.py", "old": "c = 3\nb = 2\n", "new": "c = 4\nb = 2\n", "occurrences": "one"},
        ]
        fixed, notes = rp.repair_steps(tmp, steps)
        assert len(notes) == 1
        assert fixed[1]["old"] == "c = 3\nb = 2\n"


def test_non_replace_steps_pass_through():
    with tempfile.TemporaryDirectory() as tmp:
        steps = [{"op": "create_file", "path": "n.py", "content": "x = 1\n"}]
        fixed, notes = rp.repair_steps(tmp, steps)
        assert fixed == steps and notes == []
