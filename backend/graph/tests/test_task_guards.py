import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest
from types import SimpleNamespace


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tg = _load("task_guards")
HAS_NODE = shutil.which("node") is not None
HAS_PYTEST = importlib.util.find_spec("pytest") is not None


def _write(root, name, text):
    path = pathlib.Path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


class SnapshotTests(unittest.TestCase):
    def test_restores_modified_and_removes_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = _write(tmp, "a.py", "x = 1\n")
            snap = tg.FileSnapshot(tmp)
            snap.touch_step(SimpleNamespace(op="replace_text", path="a.py"))
            snap.touch_step(SimpleNamespace(op="create_file", path="novo.py"))
            old.write_bytes(b"x = 2\n")
            _write(tmp, "novo.py", "y = 1\n")
            self.assertTrue(snap.restore())
            self.assertEqual(old.read_bytes(), b"x = 1\n")
            self.assertFalse(pathlib.Path(tmp, "novo.py").exists())

    def test_nothing_changed_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "a.py", "x = 1\n")
            snap = tg.FileSnapshot(tmp)
            snap.touch_step(SimpleNamespace(op="replace_text", path="a.py"))
            self.assertFalse(snap.restore())

    def test_extract_zip_disables_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _write(tmp, "a.py", "x = 1\n")
            snap = tg.FileSnapshot(tmp)
            snap.touch_step(SimpleNamespace(op="replace_text", path="a.py"))
            snap.touch_step(SimpleNamespace(op="extract_zip", path="pasta"))
            target.write_bytes(b"x = 2\n")
            self.assertFalse(snap.restore())
            self.assertEqual(target.read_bytes(), b"x = 2\n")

    def test_path_outside_workspace_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = tg.FileSnapshot(tmp)
            snap.touch_step(SimpleNamespace(op="create_file", path="../fora.py"))
            self.assertFalse(snap.restore())


class SyntaxTests(unittest.TestCase):
    def test_invalid_json_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "d.json", "{ invalido")
            problems = tg.extra_syntax_problems(tmp, [SimpleNamespace(op="create_file", path="d.json")])
            self.assertEqual(len(problems), 1)
            self.assertIn("JSON inválido", problems[0])

    def test_valid_json_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "d.json", json.dumps({"a": 1}))
            self.assertEqual(tg.extra_syntax_problems(tmp, [SimpleNamespace(op="create_file", path="d.json")]), [])

    @unittest.skipUnless(HAS_NODE, "node não instalado")
    def test_invalid_js_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "a.js", "function f( {\n")
            problems = tg.extra_syntax_problems(tmp, [SimpleNamespace(op="replace_text", path="a.js")])
            self.assertEqual(len(problems), 1)
            self.assertIn("JavaScript", problems[0])

    @unittest.skipUnless(HAS_NODE, "node não instalado")
    def test_esm_file_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "m.js", "import fs from 'fs';\nexport const x = 1;\n")
            self.assertEqual(tg.extra_syntax_problems(tmp, [SimpleNamespace(op="create_file", path="m.js")]), [])

    @unittest.skipUnless(HAS_NODE, "node não instalado")
    def test_js_edit_error_only_when_edit_breaks_file(self):
        good = "function f() { return 1; }\n"
        broken = "function f() { return 1; \n"
        self.assertIsNone(tg.js_edit_error(".js", good, good.replace("1", "2")))
        self.assertIn("REJEITADA", tg.js_edit_error(".js", good, broken))
        self.assertIsNone(tg.js_edit_error(".js", broken, broken + "// x\n"))
        self.assertIsNone(tg.js_edit_error(".py", good, broken))


class PytestTests(unittest.TestCase):
    def test_pytest_check_reports_pass_or_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "test_ok.py", "def test_ok():\n    assert True\n")
            _write(tmp, "test_bad.py", "def test_bad():\n    assert False\n")
            ok = tg.run_pytest(tmp, "test_ok.py")
            bad = tg.run_pytest(tmp, "test_bad.py")
            if HAS_PYTEST:
                self.assertEqual(ok, [])
                self.assertEqual(len(bad), 1)
                self.assertIn("falhou", bad[0])
            else:
                self.assertIn("não está instalado", ok[0])


if __name__ == "__main__":
    unittest.main()
