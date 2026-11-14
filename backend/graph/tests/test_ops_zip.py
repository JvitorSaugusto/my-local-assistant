import importlib.util
import os
import pathlib
import subprocess
import tempfile
import unittest
import zipfile


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


oc = _load("ops_core")


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True).stdout.strip()


def write(root, name, text):
    path = pathlib.Path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def names_in(path):
    with zipfile.ZipFile(path) as archive:
        return sorted(archive.namelist())


class ZipIntentTests(unittest.TestCase):
    def test_detects_delivery_requests(self):
        self.assertIsNotNone(oc.detect_ops_intent("me entregue os arquivos script.js, style.css e tasks.py", []))
        self.assertIsNotNone(oc.detect_ops_intent("monta um zip da pasta backend/rag", []))
        self.assertIsNotNone(oc.detect_ops_intent("me mande a pasta static e o main.py", []))
        self.assertEqual(oc.detect_ops_intent("@zip a.py b.py", []), "a.py b.py")

    def test_does_not_hijack_other_messages(self):
        self.assertIsNone(oc.detect_ops_intent("como faço um zip em python?", []))
        self.assertIsNone(oc.detect_ops_intent("explique o arquivo script.js", []))
        self.assertIsNone(oc.detect_ops_intent("@heavy me entregue os arquivos", []))
        self.assertIsNone(oc.detect_ops_intent("Criar task para zipar os arquivos #12", []))


class ZipBuildTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "proj"
        self.root.mkdir()
        os.environ["TASK_PACK_DIR"] = str(pathlib.Path(self._tmp.name) / "packs")
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@t.t")
        git(self.root, "config", "user.name", "T")
        write(self.root, ".gitignore", "ignored.txt")
        write(self.root, "a.py", "x = 1")
        write(self.root, "pkg/b.py", "b = 1")
        write(self.root, "web/b.py", "b = 2")
        write(self.root, "static/script.js", "var a = 1;")
        write(self.root, "backend/rag/x.py", "x = 1")
        write(self.root, "backend/rag/y.py", "y = 1")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")
        write(self.root, ".env", "TOKEN=abc")
        write(self.root, "ignored.txt", "nope")
        write(self.root, "backend/rag/secret.key", "k")
        write(self.root, "novo.txt", "novo")

    def tearDown(self):
        os.environ.pop("TASK_PACK_DIR", None)
        self._tmp.cleanup()

    def test_simple_names_from_different_folders(self):
        result = oc.build_zip(self.root, ["a.py", "script.js", "novo.txt"])
        self.assertIsInstance(result, dict)
        self.assertEqual(names_in(result["path"]), ["a.py", "novo.txt", "static/script.js"])
        self.assertTrue(result["path"].name.startswith("arquivos_") and result["path"].name.endswith(".zip"))
        self.assertEqual(oc.zip_file_path(result["path"].name), result["path"])

    def test_whole_folder_skips_secrets(self):
        result = oc.build_zip(self.root, ["rag"])
        self.assertEqual(names_in(result["path"]), ["backend/rag/x.py", "backend/rag/y.py"])
        self.assertTrue(any("secret.key" in s for s in result["skipped"]))

    def test_folder_with_trailing_slash_and_file_together(self):
        result = oc.build_zip(self.root, ["backend/rag/", "web/b.py"])
        self.assertEqual(names_in(result["path"]), ["backend/rag/x.py", "backend/rag/y.py", "web/b.py"])

    def test_ambiguous_and_missing_names_ask_for_full_path(self):
        self.assertIn("bate com", oc.build_zip(self.root, ["b.py"]))
        self.assertIn("não encontrei", oc.build_zip(self.root, ["zzz.py", "ignored.txt"]))

    def test_secret_only_request_is_refused(self):
        result = oc.build_zip(self.root, [".env"])
        self.assertIsInstance(result, str)
        self.assertIn("segredo", result)
        self.assertNotIn("TOKEN=abc", result)

    def test_limits(self):
        old = oc.ZIP_MAX_FILES
        oc.ZIP_MAX_FILES = 2
        try:
            self.assertIn("limite", oc.build_zip(self.root, ["rag", "a.py"]))
        finally:
            oc.ZIP_MAX_FILES = old
        old = oc.ZIP_MAX_BYTES
        oc.ZIP_MAX_BYTES = 3
        try:
            self.assertIn("limite", oc.build_zip(self.root, ["a.py"]))
        finally:
            oc.ZIP_MAX_BYTES = old

    def test_brackets_from_tips_placeholder_are_ignored(self):
        result = oc.build_zip(self.root, ["<a.py>", "<rag>"])
        self.assertEqual(names_in(result["path"]), ["a.py", "backend/rag/x.py", "backend/rag/y.py"])

    def test_empty_request(self):
        self.assertIn("nenhum arquivo", oc.build_zip(self.root, []))

    def test_zip_file_path_rejects_paths(self):
        self.assertIsNone(oc.zip_file_path("../x.zip"))
        self.assertIsNone(oc.zip_file_path("nao_existe.zip"))
        self.assertIsNone(oc.zip_file_path("pacote.md"))

    def test_without_git_ignores_node_modules(self):
        plain = pathlib.Path(self._tmp.name) / "plain"
        write(plain, "src/app.js", "a")
        write(plain, "node_modules/lib/x.js", "x")
        result = oc.build_zip(plain, ["app.js"])
        self.assertEqual(names_in(result["path"]), ["src/app.js"])
        self.assertIn("não encontrei", oc.build_zip(plain, ["x.js"]))


if __name__ == "__main__":
    unittest.main()
