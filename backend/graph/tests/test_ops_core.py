import importlib.util
import os
import pathlib
import subprocess
import tempfile
import types
import unittest


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


def msg(kind, content, name=None, tool_calls=None):
    return types.SimpleNamespace(type=kind, content=content, name=name, tool_calls=tool_calls or [])


class IntentTests(unittest.TestCase):
    def test_tags_and_natural_language(self):
        self.assertEqual(oc.detect_ops_intent("@commit meus arquivos", []), "meus arquivos")
        self.assertIsNotNone(oc.detect_ops_intent("commita meus arquivos atuais", [msg("human", "x")]))
        self.assertIsNotNone(oc.detect_ops_intent("quero fazer um commit do que mexi", []))
        self.assertIsNotNone(oc.detect_ops_intent("gere um md do problema do login pro claude", []))
        self.assertIsNotNone(oc.detect_ops_intent("me dá o primer do projeto", []))

    def test_does_not_hijack_other_messages(self):
        self.assertIsNone(oc.detect_ops_intent("como funciona o commit automático?", []))
        self.assertIsNone(oc.detect_ops_intent("o commit ficou ruim", []))
        self.assertIsNone(oc.detect_ops_intent("@heavy commita isso", []))
        self.assertIsNone(oc.detect_ops_intent("@generate 12 13", []))
        self.assertIsNone(oc.detect_ops_intent("Criar task para commitar o que a IA fez #12", []))
        self.assertIsNone(oc.detect_ops_intent("explique o fluxo do grafo", []))

    def test_sticky_answer_to_ops_question(self):
        history = [msg("human", "commita"), msg("ai", "Quais arquivos?", name=oc.OPS_NAME), msg("human", "a.py e b.py")]
        self.assertEqual(oc.detect_ops_intent("a.py e b.py", history), "a.py e b.py")
        done = [msg("human", "commita"), msg("ai", "Commit feito.", name=oc.OPS_NAME), msg("human", "valeu")]
        self.assertIsNone(oc.detect_ops_intent("valeu", done))
        other = [msg("human", "oi"), msg("ai", "Quer ver?", name="Qwen 3 Coder 30B"), msg("human", "sim")]
        self.assertIsNone(oc.detect_ops_intent("sim", other))


class GitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "proj"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "feat/x")
        git(self.root, "config", "user.email", "t@t.t")
        git(self.root, "config", "user.name", "T")
        git(self.root, "config", "core.autocrlf", "false")
        write(self.root, "a.py", "x = 1\n")
        write(self.root, "pkg/b.py", "def login():\n    return 1\n")
        write(self.root, "web/b.py", "y = 1\n")
        write(self.root, "gone.py", "g = 1\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")

    def tearDown(self):
        self._tmp.cleanup()

    def _edit(self):
        write(self.root, "a.py", "x = 2\nz = 3\n")
        write(self.root, "novo.py", "n = 1\nm = 2\n")
        (self.root / "gone.py").unlink()

    def test_changes_statuses_and_counts(self):
        self._edit()
        items = {i["path"]: i for i in oc.git_changes(self.root)}
        self.assertEqual(items["a.py"]["status"], "modificado")
        self.assertEqual((items["a.py"]["added"], items["a.py"]["removed"]), (2, 1))
        self.assertEqual(items["novo.py"]["status"], "novo")
        self.assertEqual(items["novo.py"]["added"], 2)
        self.assertEqual(items["gone.py"]["status"], "removido")
        text = oc.format_changes(list(items.values()), "feat/x")
        self.assertIn("3 arquivo(s)", text)
        self.assertIn("- a.py (modificado", text)

    def test_resolve_names(self):
        pool = ["pkg/b.py", "web/b.py", "a.py"]
        self.assertEqual(oc.resolve_names(pool, ["a.py"]), (["a.py"], {}, []))
        found, amb, miss = oc.resolve_names(pool, ["b.py", "zzz.py", "web/b.py"])
        self.assertEqual(found, ["web/b.py"])
        self.assertEqual(sorted(amb["b.py"]), ["pkg/b.py", "web/b.py"])
        self.assertEqual(miss, ["zzz.py"])

    def test_diff_text(self):
        self._edit()
        write(self.root, ".env", "TOKEN=abc\n")
        text = oc.diff_text(self.root, ["a.py", "novo.py", ".env"])
        self.assertIn("-x = 1", text)
        self.assertIn("(arquivo novo)", text)
        self.assertIn("omitido: parece arquivo de segredo", text)
        self.assertNotIn("TOKEN=abc", text)

    def test_commit_only_selected(self):
        self._edit()
        result = oc.commit_paths(self.root, ["a.py"], "feat: troca x")
        self.assertIn("Commit", result)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "feat: troca x")
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD").split(), ["a.py"])
        self.assertIn("novo.py", git(self.root, "status", "--porcelain"))

    def test_commit_deleted_and_new(self):
        self._edit()
        oc.commit_paths(self.root, ["gone.py", "novo.py"], "chore: limpa e cria")
        self.assertEqual(sorted(git(self.root, "show", "--name-only", "--format=", "HEAD").split()), ["gone.py", "novo.py"])

    def test_commit_refusals(self):
        self._edit()
        write(self.root, ".env", "T=1\n")
        self.assertIn("segredos", oc.commit_paths(self.root, [".env"], "x"))
        self.assertIn("mensagem", oc.commit_paths(self.root, ["a.py"], "  "))
        self.assertIn("não encontrei", oc.commit_paths(self.root, ["nao_existe.py"], "x"))
        git(self.root, "checkout", "-q", "-b", "main")
        self.assertIn("protegida", oc.commit_paths(self.root, ["a.py"], "x"))

    def test_commit_ambiguous_name_asks_for_full_path(self):
        write(self.root, "pkg/b.py", "def login():\n    return 2\n")
        write(self.root, "web/b.py", "y = 2\n")
        self.assertIn("bate com", oc.commit_paths(self.root, ["b.py"], "fix: b"))

    def test_suggest_files(self):
        ranked = oc.suggest_files(self.root, "o login está falhando depois do deploy")
        self.assertEqual(ranked[0][0], "pkg/b.py")  # único que cita 'login'
        self.assertIn("login", ranked[0][1])
        write(self.root, "web/b.py", "y = 2  # login falha aqui\n")
        ranked = oc.suggest_files(self.root, "o login está falhando depois do deploy")
        self.assertEqual(ranked[0][0], "web/b.py")  # cita 'login' e está alterado sem commit
        self.assertIn("alterado e ainda não commitado", ranked[0][1])
        self.assertIn("pkg/b.py", [p for p, _r in ranked])

    def test_pack_files(self):
        os.environ["TASK_PACK_DIR"] = str(pathlib.Path(self._tmp.name) / "packs")
        try:
            path = oc.save_pack("# oi", "Problema do Login!")
            self.assertTrue(path.name.startswith("pacote_") and path.name.endswith("_problema-do-login.md"))
            self.assertEqual(oc.pack_file_path(path.name), path)
            self.assertIsNone(oc.pack_file_path("../x.md"))
            self.assertIsNone(oc.pack_file_path("nao_existe.md"))
        finally:
            os.environ.pop("TASK_PACK_DIR", None)


if __name__ == "__main__":
    unittest.main()
