import importlib.util
import os
import pathlib
import tempfile
import unittest


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tj = _load("task_journal")


def _write(root, name, text):
    path = pathlib.Path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


class JournalTests(unittest.TestCase):
    def setUp(self):
        self._journal_dir = tempfile.TemporaryDirectory()
        self._ws = tempfile.TemporaryDirectory()
        os.environ["TASK_JOURNAL_DIR"] = self._journal_dir.name
        os.environ.pop("TASK_ROLLBACK_ON_FAIL", None)
        tj._ACTIVE.clear()
        self.ws = self._ws.name

    def tearDown(self):
        tj._ACTIVE.clear()
        self._journal_dir.cleanup()
        self._ws.cleanup()

    def _edit(self, name, text):
        path = pathlib.Path(self.ws, name)
        tj.record_write(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def test_diff_shows_modified_and_new_files(self):
        _write(self.ws, "a.py", "x = 1\n")
        tj.begin_journal(self.ws, 7)
        self._edit("a.py", "x = 2\n")
        self._edit("novo.py", "y = 1\n")
        tj.journal_end(self.ws)
        data = tj.journal_diff(self.ws, 7)
        self.assertIn("-x = 1", data["diff"])
        self.assertIn("+x = 2", data["diff"])
        self.assertEqual(data["new_files"][0]["path"], "novo.py")

    def test_revert_restores_and_deletes_created(self):
        _write(self.ws, "a.py", "x = 1\n")
        tj.begin_journal(self.ws, 7)
        self._edit("a.py", "x = 2\n")
        self._edit("novo.py", "y = 1\n")
        tj.journal_end(self.ws)
        outcome = tj.journal_revert(self.ws, 7)
        self.assertEqual(sorted(outcome["restored"]), ["a.py", "novo.py"])
        self.assertEqual(outcome["conflicts"], [])
        self.assertEqual(pathlib.Path(self.ws, "a.py").read_text(), "x = 1\n")
        self.assertFalse(pathlib.Path(self.ws, "novo.py").exists())
        self.assertIsNone(tj.journal_diff(self.ws, 7))

    def test_revert_does_not_touch_file_changed_afterwards(self):
        _write(self.ws, "a.py", "x = 1\n")
        tj.begin_journal(self.ws, 7)
        self._edit("a.py", "x = 2\n")
        tj.journal_end(self.ws)
        pathlib.Path(self.ws, "a.py").write_text("x = 3\n")  # outra task mexeu depois
        outcome = tj.journal_revert(self.ws, 7)
        self.assertEqual(outcome["conflicts"], ["a.py"])
        self.assertEqual(pathlib.Path(self.ws, "a.py").read_text(), "x = 3\n")

    def test_rollback_run_on_failure_keeps_failed_diff(self):
        _write(self.ws, "a.py", "x = 1\n")
        tj.begin_journal(self.ws, 9)
        self._edit("a.py", "x = 99\n")
        self._edit("novo.py", "z = 1\n")
        restored = tj.journal_rollback(self.ws, 9)
        tj.journal_end(self.ws)
        self.assertEqual(sorted(restored), ["a.py", "novo.py"])
        self.assertEqual(pathlib.Path(self.ws, "a.py").read_text(), "x = 1\n")
        self.assertFalse(pathlib.Path(self.ws, "novo.py").exists())
        data = tj.journal_diff(self.ws, 9)
        self.assertIn("FALHOU", data["base"])
        self.assertIn("+x = 99", data["diff"])

    def test_rollback_disabled_by_env(self):
        _write(self.ws, "a.py", "x = 1\n")
        tj.begin_journal(self.ws, 9)
        self._edit("a.py", "x = 99\n")
        os.environ["TASK_ROLLBACK_ON_FAIL"] = "0"
        self.assertEqual(tj.journal_rollback(self.ws, 9), [])
        self.assertEqual(pathlib.Path(self.ws, "a.py").read_text(), "x = 99\n")

    def test_failed_second_run_goes_back_to_first_run_not_original(self):
        _write(self.ws, "a.py", "x = 1\n")
        tj.begin_journal(self.ws, 5)
        self._edit("a.py", "x = 2\n")           # 1a execução (ficou em revisão)
        tj.journal_end(self.ws)
        tj.begin_journal(self.ws, 5)             # reprovada e rodada de novo
        self._edit("a.py", "x = 3\n")
        self._edit("extra.py", "e = 1\n")
        tj.journal_rollback(self.ws, 5)          # a 2a execução falhou
        tj.journal_end(self.ws)
        self.assertEqual(pathlib.Path(self.ws, "a.py").read_text(), "x = 2\n")
        self.assertFalse(pathlib.Path(self.ws, "extra.py").exists())
        outcome = tj.journal_revert(self.ws, 5)   # desfazer tudo: volta ao original
        self.assertEqual(outcome["conflicts"], [])
        self.assertEqual(pathlib.Path(self.ws, "a.py").read_text(), "x = 1\n")

    def test_record_ignores_paths_outside_workspace_and_without_journal(self):
        with tempfile.TemporaryDirectory() as other:
            tj.begin_journal(self.ws, 1)
            tj.record_write(pathlib.Path(other, "fora.py"))
            self.assertEqual(tj._ACTIVE[str(pathlib.Path(self.ws).resolve())].data["files"], {})
        tj._ACTIVE.clear()
        tj.record_write(pathlib.Path(self.ws, "a.py"))

    def test_discard_removes_journal(self):
        _write(self.ws, "a.py", "x = 1\n")
        tj.begin_journal(self.ws, 3)
        self._edit("a.py", "x = 2\n")
        tj.journal_end(self.ws)
        tj.discard_journal(3)
        self.assertIsNone(tj.journal_diff(self.ws, 3))

    def test_other_workspace_gets_no_diff(self):
        _write(self.ws, "a.py", "x = 1\n")
        tj.begin_journal(self.ws, 3)
        self._edit("a.py", "x = 2\n")
        tj.journal_end(self.ws)
        with tempfile.TemporaryDirectory() as other:
            self.assertIsNone(tj.journal_diff(other, 3))

    def test_syntax_problems_reports_bad_json(self):
        _write(self.ws, "d.json", "{ invalido")
        _write(self.ws, "ok.json", "{}")
        problems = tj.syntax_problems_for_paths(self.ws, ["d.json", "ok.json"])
        self.assertEqual(len(problems), 1)
        self.assertIn("JSON inválido", problems[0])


if __name__ == "__main__":
    unittest.main()
