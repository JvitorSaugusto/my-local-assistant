"""Testes do executor com rollback, cura de espaços e checagem de sintaxe extra.

Rode na raiz do projeto:  python -m unittest backend.graph.tests.test_executor_guards -v
"""
import pathlib
import shutil
import tempfile
import unittest

from backend.graph.executor import execute_task_sync

HAS_NODE = shutil.which("node") is not None


def _write(root, name, text):
    path = pathlib.Path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _replace(path, old, new):
    return {"op": "replace_text", "path": path, "old": old, "new": new, "occurrences": "one"}


class ExecutorGuardTests(unittest.TestCase):
    def test_verify_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _write(tmp, "a.py", "x = 1\n")
            task = {
                "steps": [_replace("a.py", "x = 1\n", "x = 2\n")],
                "verify": [{"type": "contains", "path": "a.py", "text": "NAO_EXISTE"}],
            }
            result = execute_task_sync(task, tmp)
            self.assertFalse(result.ok)
            self.assertIn("DESFEITOS", result.error)
            self.assertEqual(target.read_bytes(), b"x = 1\n")

    def test_step_failure_rolls_back_previous_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _write(tmp, "a.py", "x = 1\ny = 2\n")
            task = {"steps": [_replace("a.py", "x = 1\n", "x = 5\n"), _replace("a.py", "zzz\n", "w = 1\n")]}
            result = execute_task_sync(task, tmp)
            self.assertFalse(result.ok)
            self.assertIn("Rollback", result.error)
            self.assertEqual(target.read_bytes(), b"x = 1\ny = 2\n")

    def test_whitespace_only_difference_is_healed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _write(tmp, "a.py", "a = 1   \nb = 2\n")
            task = {"steps": [_replace("a.py", "a = 1\nb = 2\n", "a = 1\nb = 3\n")]}
            result = execute_task_sync(task, tmp)
            self.assertTrue(result.ok, result.error)
            self.assertIn("b = 3", target.read_text(encoding="utf-8"))

    def test_invalid_json_created_by_task_is_rolled_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = {"steps": [{"op": "create_file", "path": "d.json", "content": "{ invalido"}]}
            result = execute_task_sync(task, tmp)
            self.assertFalse(result.ok)
            self.assertFalse(pathlib.Path(tmp, "d.json").exists())

    @unittest.skipUnless(HAS_NODE, "node não instalado")
    def test_js_edit_that_breaks_syntax_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _write(tmp, "app.js", "function f() { return 1; }\n")
            task = {"steps": [_replace("app.js", "return 1; }\n", "return 1; \n")]}
            result = execute_task_sync(task, tmp)
            self.assertFalse(result.ok)
            self.assertEqual(target.read_bytes(), b"function f() { return 1; }\n")


if __name__ == "__main__":
    unittest.main()
