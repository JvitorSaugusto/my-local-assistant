import importlib.util
import os
import pathlib
import subprocess
import tempfile
import unittest


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tc = _load("task_commit")


def git(root, *args):
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return done.stdout.strip()


def write(root, name, text):
    path = pathlib.Path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


class CommitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "proj"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "feat/teste")
        git(self.root, "config", "user.email", "t@t.t")
        git(self.root, "config", "user.name", "Teste")
        git(self.root, "config", "core.autocrlf", "false")
        write(self.root, "a.py", "x = 1\n")
        write(self.root, "outro.py", "o = 1\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")
        os.environ["TASK_AUTOCOMMIT"] = "1"

    def tearDown(self):
        os.environ.pop("TASK_AUTOCOMMIT", None)
        self._tmp.cleanup()

    def _run_task(self, edits):
        steps = [{"op": "replace_text" if p.exists() else "create_file", "path": n} for n, _t in edits for p in [self.root / n]]
        pre = tc.capture_originals(str(self.root), steps)
        for name, text in edits:
            write(self.root, name, text)
        return pre

    def test_commits_only_files_touched_by_task(self):
        write(self.root, "outro.py", "o = 99\n")  # alteração sua, em outro arquivo
        pre = self._run_task([("a.py", "x = 2\n"), ("novo.py", "n = 1\n")])
        note = tc.commit_task(str(self.root), 5, "Meu título", pre)
        self.assertIn("commit", note)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "task #5: Meu título")
        self.assertEqual(sorted(git(self.root, "show", "--name-only", "--format=", "HEAD").split()), ["a.py", "novo.py"])
        self.assertIn("outro.py", git(self.root, "status", "--porcelain"))  # ficou como estava, sem commit

    def test_skips_when_touched_file_already_had_your_changes(self):
        write(self.root, "a.py", "x = 50  # sua mudança\n")
        pre = self._run_task([("a.py", "x = 50  # sua mudança\ny = 2\n")])
        before = git(self.root, "rev-parse", "HEAD")
        note = tc.commit_task(str(self.root), 6, "T", pre)
        self.assertIn("alterações suas não commitadas", note)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), before)

    def test_protected_branch_is_skipped(self):
        git(self.root, "checkout", "-q", "-b", "main")
        pre = self._run_task([("a.py", "x = 2\n")])
        before = git(self.root, "rev-parse", "HEAD")
        self.assertIn("protegida", tc.commit_task(str(self.root), 7, "T", pre))
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), before)

    def test_disabled_by_default(self):
        os.environ.pop("TASK_AUTOCOMMIT", None)
        pre = self._run_task([("a.py", "x = 2\n")])
        self.assertIsNone(tc.commit_task(str(self.root), 8, "T", pre))

    def test_nothing_changed_returns_none(self):
        pre = tc.capture_originals(str(self.root), [{"op": "replace_text", "path": "a.py"}])
        self.assertIsNone(tc.commit_task(str(self.root), 9, "T", pre))

    def test_not_a_git_repo_returns_none(self):
        with tempfile.TemporaryDirectory() as plain:
            pre = {"files": {"a.py": None}, "multi": False}
            write(plain, "a.py", "x = 1\n")
            self.assertIsNone(tc.commit_task(plain, 10, "T", pre))

    def test_dryrun_copy_is_ignored(self):
        copy = pathlib.Path(self._tmp.name) / "dryrun_abc"
        copy.mkdir()
        git(copy, "init", "-q")
        write(copy, "a.py", "x = 1\n")
        pre = {"files": {"a.py": None}, "multi": False}
        self.assertIsNone(tc.commit_task(str(copy), 11, "T", pre))

    def test_multi_file_ops_are_skipped(self):
        pre = tc.capture_originals(str(self.root), [{"op": "extract_zip", "path": "p", "source": "x.zip"}])
        self.assertTrue(pre["multi"])
        self.assertIn("vários arquivos", tc.commit_task(str(self.root), 12, "T", pre))

    def test_crlf_working_copy_is_not_treated_as_dirty(self):
        path = self.root / "a.py"
        path.write_bytes(b"x = 1\r\n")  # CRLF no disco, LF no HEAD (sem mudança real sua)
        pre = tc.capture_originals(str(self.root), [{"op": "replace_text", "path": "a.py"}])
        path.write_bytes(b"x = 1\r\ny = 2\r\n")
        self.assertIn("commit", tc.commit_task(str(self.root), 13, "T", pre))

    def test_ignored_file_is_not_added(self):
        write(self.root, ".gitignore", "gerado.txt\n")
        git(self.root, "add", ".gitignore")
        git(self.root, "commit", "-qm", "ignore")
        pre = self._run_task([("gerado.txt", "x\n"), ("a.py", "x = 3\n")])
        tc.commit_task(str(self.root), 14, "T", pre)
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD").split(), ["a.py"])

    def test_commit_from_journal_disabled_returns_none(self):
        os.environ.pop("TASK_AUTOCOMMIT", None)
        self.assertIsNone(tc.commit_from_journal(1, "T"))


if __name__ == "__main__":
    unittest.main()
