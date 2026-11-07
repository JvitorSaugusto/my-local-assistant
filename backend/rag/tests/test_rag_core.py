"""Testes do núcleo do RAG (sem rede, sem Postgres). Rode na raiz do projeto:
    python -m unittest backend.rag.tests.test_rag_core -v
"""

import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.rag.chunker import chunk_file
from backend.rag.pipeline import IngestCancelled, ingest
from backend.rag.providers import HashEmbedder, HeuristicSummarizer
from backend.rag.repo_map import build_repo_map
from backend.rag.scanner import scan
from backend.rag.search import fuse, hybrid_search, symbol_tokens, text_tokens
from backend.rag.store_memory import MemoryStore
from backend.rag.zip_utils import ZipRejected, safe_extract_zip

VIEWS = '''import json
from django.http import JsonResponse

ALLOWED_SIGNUP_TIPOS = {"cliente", "parceiro"}


''' + "".join(f"def helper_{i}(x):\n    return x + {i}\n\n" for i in range(30)) + '''
class OSMobileSignupSyncView:
    """Recebe o cadastro vindo do app mobile."""

    def post(self, request):
        if request.tipo not in ALLOWED_SIGNUP_TIPOS:
            return JsonResponse({"detail": "tipo inválido"}, status=400)
        return JsonResponse({"ok": True}, status=201)
'''


def make_repo(root: str) -> None:
    Path(root, "app").mkdir()
    Path(root, "app", "views.py").write_text(VIEWS, encoding="utf-8")
    Path(root, "app", "urls.py").write_text("from .views import OSMobileSignupSyncView\nurlpatterns = []\n", encoding="utf-8")
    Path(root, "README.md").write_text("# Projeto\ntexto\n## Uso\nmais\n", encoding="utf-8")
    Path(root, "node_modules").mkdir()
    Path(root, "node_modules", "x.js").write_text("function a(){}\n", encoding="utf-8")
    Path(root, "logo.png").write_bytes(b"\x89PNG\x00\x00")
    Path(root, ".env").write_text("SECRET=1\n", encoding="utf-8")


class ChunkerTests(unittest.TestCase):
    def test_header_keeps_constants(self):
        chunks = chunk_file("app/views.py", VIEWS, "python")
        header = next(c for c in chunks if c.kind == "header")
        self.assertIn("ALLOWED_SIGNUP_TIPOS", header.code)

    def test_method_has_parent_and_tag(self):
        chunks = chunk_file("app/views.py", VIEWS, "python")
        cls = next(c for c in chunks if c.qualname == "OSMobileSignupSyncView")
        self.assertIn("[arquivo] app/views.py", cls.tag())

    def test_big_class_split_into_skeleton_and_methods(self):
        body = "".join(f"    def m{i}(self):\n        return {i}\n\n" for i in range(60))
        chunks = chunk_file("a.py", "class Big:\n" + body, "python")
        kinds = {c.kind for c in chunks}
        self.assertEqual(kinds, {"class_skeleton", "method"})
        self.assertTrue(all(c.parent == "Big" for c in chunks if c.kind == "method"))

    def test_long_function_is_windowed(self):
        code = "def f():\n" + "".join(f"    x{i} = {i}\n" for i in range(450))
        chunks = chunk_file("a.py", code, "python", max_lines=200)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.parts == len(chunks) for c in chunks))

    def test_syntax_error_falls_back(self):
        self.assertTrue(chunk_file("bad.py", "def (:\n  x\n", "python"))

    def test_js_and_markdown(self):
        js = chunk_file("a.js", "const A = 1;\n\nfunction go() {\n  return 1;\n}\n", "javascript")
        self.assertIn("go", [c.qualname for c in js])
        md = chunk_file("r.md", "# A\nx\n## B\ny\n", "markdown")
        self.assertEqual([c.qualname for c in md], ["A", "B"])


class ScannerTests(unittest.TestCase):
    def test_ignores_noise(self):
        with tempfile.TemporaryDirectory() as root:
            make_repo(root)
            files, skipped = scan(root)
            paths = {f.path for f in files}
            self.assertEqual(paths, {"app/views.py", "app/urls.py", "README.md"})
            self.assertNotIn(".env", paths)


class ZipTests(unittest.TestCase):
    def test_zip_slip_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.zip")
            with zipfile.ZipFile(bad, "w") as z:
                z.writestr("../../evil.txt", "x")
            with self.assertRaises(ZipRejected):
                safe_extract_zip(bad, os.path.join(tmp, "out"), 10_000, 10)

    def test_limits_and_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "good.zip")
            with zipfile.ZipFile(good, "w") as z:
                z.writestr("p/a.py", "x = 1\n")
            self.assertEqual(safe_extract_zip(good, os.path.join(tmp, "o1"), 10_000, 10), 1)
            with self.assertRaises(ZipRejected):
                safe_extract_zip(good, os.path.join(tmp, "o2"), 10_000, 0)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        make_repo(self.root)
        self.store = MemoryStore()
        self.embedder = HashEmbedder(128)
        self.summ = HeuristicSummarizer()
        self.sid = await self.store.upsert_source("demo", "workspace", self.root)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def run_ingest(self, **kw):
        return await ingest(self.store, self.embedder, self.summ, self.sid, self.root, **kw)

    async def test_search_finds_constant_in_big_file(self):
        await self.run_ingest()
        hits = await hybrid_search(self.store, self.embedder, "quais tipos de cadastro ALLOWED_SIGNUP_TIPOS aceita", [self.sid], limit=3)
        self.assertTrue(any("ALLOWED_SIGNUP_TIPOS" in h.content for h in hits), [h.qualname for h in hits])

    async def test_incremental_only_reprocesses_changed_files(self):
        first = await self.run_ingest()
        self.assertEqual(first["files_indexed"], 3)
        calls = self.embedder.calls
        again = await self.run_ingest()
        self.assertEqual(again["files_indexed"], 0)
        self.assertEqual(self.embedder.calls, calls)

        Path(self.root, "app", "urls.py").write_text("urlpatterns = [1]\n", encoding="utf-8")
        third = await self.run_ingest()
        self.assertEqual(third["files_indexed"], 1)

    async def test_removed_file_is_dropped(self):
        await self.run_ingest()
        os.remove(os.path.join(self.root, "README.md"))
        res = await self.run_ingest()
        self.assertEqual(res["files_removed"], 1)
        self.assertNotIn("README.md", await self.store.file_hashes(self.sid))

    async def test_summary_cache_by_hash(self):
        calls = {"n": 0}

        class Counting(HeuristicSummarizer):
            def summarize(self, chunk):
                calls["n"] += 1
                return super().summarize(chunk)

        self.summ = Counting()
        await self.run_ingest()
        first = calls["n"]
        await self.run_ingest(force=True)  # reprocessa tudo, mas o resumo vem do cache
        self.assertEqual(calls["n"], first)

    async def test_cancel(self):
        with self.assertRaises(IngestCancelled):
            await self.run_ingest(is_cancelled=lambda: True)

    async def test_repo_map(self):
        await self.run_ingest()
        text = build_repo_map(await self.store.outline(self.sid))
        self.assertIn("app/", text)
        self.assertIn("views.py", text)
        self.assertIn("class OSMobileSignupSyncView", text)


class SearchHelpersTests(unittest.TestCase):
    def test_tokens(self):
        self.assertIn("allowed_signup_tipos", [t.lower() for t in symbol_tokens("o que ALLOWED_SIGNUP_TIPOS faz")])
        self.assertIn("signup", text_tokens("ALLOWED_SIGNUP_TIPOS e signup"))

    def test_fuse_prefers_items_in_several_lists(self):
        from backend.rag.entities import SearchHit

        def h(i, by):
            return SearchHit(i, "p", "function", f"f{i}", 1, 2, "", "c", 0.0, [by])

        merged = fuse([[h(1, "vetor"), h(2, "vetor")], [h(2, "texto"), h(3, "texto")]])
        self.assertEqual(merged[0].chunk_id, 2)
        self.assertEqual(sorted(merged[0].matched_by), ["texto", "vetor"])


if __name__ == "__main__":
    unittest.main()
