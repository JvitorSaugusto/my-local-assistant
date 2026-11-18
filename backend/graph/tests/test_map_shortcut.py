import importlib.util
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "map_shortcut.py"
_spec = importlib.util.spec_from_file_location("map_shortcut_under_test", _PATH)
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)


def _render(path):
    return f"ARVORE:{path.name}"


class WantsMapTests(unittest.TestCase):
    def test_real_requests(self):
        for text in ("me retorna o mapa do repositorio", "Mostre o mapa da pasta backend", "qual a estrutura de pastas do projeto?",
                     "gere a árvore de arquivos do código"):
            self.assertTrue(ms.wants_repo_map(text), text)

    def test_unrelated_or_risky_requests(self):
        for text in ("crie um mapa de calor em python", "gere tasks para o mapa do projeto", "explique decision tree",
                     "mapa " + "x" * 400 + " projeto", ""):
            self.assertFalse(ms.wants_repo_map(text), text)


class BuildMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "backend" / "api").mkdir(parents=True)
        (self.root / "node_modules" / "backend").mkdir(parents=True)
        (self.root / ".git").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_a_map_request_returns_none(self):
        self.assertIsNone(ms.build_map_text(str(self.root), "explique o fluxo de login", _render))

    def test_without_workspace_is_honest(self):
        for ws in (None, "", "Diretório não informado", str(self.root / "nao_existe")):
            self.assertEqual(ms.build_map_text(ws, "me retorna o mapa do repositorio", _render), ms.NO_PROJECT)

    def test_root_map_comes_from_renderer(self):
        reply = ms.build_map_text(str(self.root), "me retorna o mapa do repositorio", _render)
        self.assertIn("ARVORE:" + self.root.name, reply)
        self.assertIn("sem IA", reply)
        self.assertEqual(reply.count(chr(96) * 3), 2)

    def test_named_folder_is_chosen_and_ignored_dirs_are_skipped(self):
        reply = ms.build_map_text(str(self.root), "mostre o mapa da pasta api", _render)
        self.assertIn("ARVORE:api", reply)
        self.assertEqual(ms.pick_target(self.root, "mapa da pasta backend"), self.root / "backend")
        self.assertEqual(ms.pick_target(self.root, "mapa de node_modules do projeto"), self.root)

    def test_empty_render_is_reported(self):
        self.assertIn("vazia", ms.build_map_text(str(self.root), "mapa do projeto", lambda p: ""))


if __name__ == "__main__":
    unittest.main()
