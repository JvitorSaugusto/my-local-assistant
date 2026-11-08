"""Testes da fachada RagService com store em memória. Rode na raiz do projeto:
    python -m unittest backend.rag.tests.test_rag_service -v
"""

import asyncio
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.rag.config import load_config
from backend.rag.providers import HashEmbedder, HeuristicSummarizer
from backend.rag.service import RagService
from backend.rag.store_memory import MemoryStore
from backend.rag.zip_utils import ZipRejected


def make_service(work_dir: str) -> RagService:
    cfg = load_config()
    cfg = type(cfg)(**{**cfg.__dict__, "work_dir": work_dir})
    return RagService(cfg, MemoryStore(), HashEmbedder(128), HeuristicSummarizer())


async def wait_done(service: RagService, source_id: int, timeout: float = 10.0) -> dict:
    for _ in range(int(timeout / 0.05)):
        info = await service.status(source_id)
        job = info["job"] if info else None
        if job and job["status"] in {"done", "failed", "cancelled", "interrupted"}:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError("ingestão não terminou a tempo")


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name, "meu_repo")
        self.repo.mkdir()
        (self.repo / "a.py").write_text('LIMITE_MAXIMO = 10\n\ndef calcula():\n    """Calcula o total."""\n    return LIMITE_MAXIMO\n', encoding="utf-8")
        self.service = make_service(os.path.join(self.tmp.name, "work"))

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_workspace_ingest_and_search(self):
        started = await self.service.ingest_workspace(str(self.repo))
        job = await wait_done(self.service, started["source_id"])
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["files_done"], 1)
        hits = await self.service.search("LIMITE_MAXIMO", workspace=str(self.repo))
        self.assertTrue(hits)
        ctx = await self.service.context_for_workspace(str(self.repo), "qual o LIMITE_MAXIMO")
        self.assertIn("a.py", ctx)
        self.assertEqual(await self.service.context_for_workspace(self.tmp.name, "x"), "")

    async def test_invalid_path(self):
        with self.assertRaises(ValueError):
            await self.service.ingest_workspace(os.path.join(self.tmp.name, "nao_existe"))

    async def test_zip_ingest_cleans_up(self):
        zpath = os.path.join(self.tmp.name, "up.zip")
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("projeto-main/b.py", "def zip_func():\n    return 1\n")
        started = await self.service.ingest_zip(zpath, "meu-zip")
        job = await wait_done(self.service, started["source_id"])
        self.assertEqual(job["status"], "done")
        self.assertFalse(os.path.exists(zpath))
        work = Path(self.service.cfg.work_dir)
        self.assertEqual([p for p in work.iterdir()] if work.exists() else [], [])
        hits = await self.service.search("zip_func", source_id=started["source_id"])
        self.assertEqual(hits[0].path, "b.py")

    async def test_bad_zip_rejected(self):
        bad = os.path.join(self.tmp.name, "bad.zip")
        Path(bad).write_bytes(b"isto nao e um zip")
        with self.assertRaises(ZipRejected):
            await self.service.ingest_zip(bad, "x")

    async def test_failed_job_reports_error(self):
        class Boom(HashEmbedder):
            def embed(self, texts):
                raise RuntimeError("ollama fora do ar")

        self.service._embedder = Boom(128)
        started = await self.service.ingest_workspace(str(self.repo))
        job = await wait_done(self.service, started["source_id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("ollama fora do ar", job["error"])

    async def test_delete_source(self):
        started = await self.service.ingest_workspace(str(self.repo))
        await wait_done(self.service, started["source_id"])
        await self.service.delete_source(started["source_id"])
        self.assertEqual(await self.service.list_sources(), [])


class ScopeAndRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.proj = base / "projeto_x"
        self.other = base / "projeto_y"
        for folder, code in ((self.proj, "def so_no_x():\n    return 1\n"), (self.other, "def so_no_y():\n    return 2\n")):
            folder.mkdir()
            (folder / "m.py").write_text(code, encoding="utf-8")
        self.service = make_service(os.path.join(self.tmp.name, "work"))
        for folder in (self.proj, self.other):
            started = await self.service.ingest_workspace(str(folder))
            await wait_done(self.service, started["source_id"])
        zpath = os.path.join(self.tmp.name, "z.zip")
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("pasta/z.py", "def so_no_zip():\n    return 3\n")
        started = await self.service.ingest_zip(zpath, "meu-zip")
        await wait_done(self.service, started["source_id"])
        self.ws = str(self.proj)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def names(self, source=None):
        _hits, _label, sources = await self.service.search_scoped("def", self.ws, source)
        return sorted(s["name"] for s in sources)

    async def test_default_scope_is_active_workspace_only(self):
        self.assertEqual(await self.names(), ["projeto_x"])

    async def test_named_source_reaches_zip_and_other_workspace(self):
        self.assertEqual(await self.names("meu-zip"), ["meu-zip"])
        self.assertEqual(await self.names("PROJETO_Y"), ["projeto_y"])
        hits, _l, _s = await self.service.search_scoped("so_no_zip", self.ws, "meu-zip")
        self.assertEqual(hits[0].path, "z.py")

    async def test_all_and_unknown(self):
        self.assertEqual(await self.names("all"), ["meu-zip", "projeto_x", "projeto_y"])
        with self.assertRaises(ValueError) as ctx:
            await self.service.resolve_scope(self.ws, "nao-existe")
        self.assertIn("meu-zip", str(ctx.exception))

    async def test_links_extend_default_scope(self):
        zip_id = (await self.service._source_by_name("meu-zip"))["id"]
        own_id = (await self.service.find_source_for_workspace(self.ws))["id"]
        saved = await self.service.set_links(self.ws, [zip_id, own_id, 999])
        self.assertEqual(saved, [zip_id])  # ignora a própria fonte e ids inexistentes
        self.assertEqual(await self.names(), ["meu-zip", "projeto_x"])
        await self.service.delete_source(zip_id)
        self.assertEqual(await self.names(), ["projeto_x"])

    async def test_overview_tells_what_is_default(self):
        text = await self.service.overview(self.ws)
        self.assertIn("projeto_x", text)
        self.assertIn("consultada por padrão", text)
        self.assertIn('source="meu-zip"', text)

    async def test_refresh_picks_up_edits_and_is_throttled(self):
        (self.proj / "m.py").write_text("def so_no_x():\n    return 1\n\ndef recem_criada():\n    return 9\n", encoding="utf-8")
        result = await self.service.refresh_workspace(self.ws, min_interval=0)
        self.assertEqual(result["files_indexed"], 1)
        hits, _l, _s = await self.service.search_scoped("recem_criada", self.ws)
        self.assertTrue(any("recem_criada" in h.content for h in hits))
        self.assertIsNone(await self.service.refresh_workspace(self.ws, min_interval=60))  # trava de intervalo
        self.assertIsNone(await self.service.refresh_workspace(str(self.other.parent), min_interval=0))  # não indexado

    async def test_refresh_detects_removed_file(self):
        os.remove(self.proj / "m.py")
        (self.proj / "n.py").write_text("def nova():\n    pass\n", encoding="utf-8")
        result = await self.service.refresh_workspace(self.ws, min_interval=0)
        self.assertEqual((result["files_indexed"], result["files_removed"]), (1, 1))


class ScopeInfoTests(ScopeAndRefreshTests):
    async def test_scope_info_for_active_project(self):
        zip_id = (await self.service._source_by_name("meu-zip"))["id"]
        await self.service.set_links(self.ws, [zip_id])
        info = await self.service.scope_info(self.ws)
        self.assertEqual(info["own"]["name"], "projeto_x")
        self.assertEqual(info["linked_ids"], [zip_id])
        self.assertEqual([s["name"] for s in info["sources"]], ["meu-zip", "projeto_x", "projeto_y"])
        self.assertTrue(all({"id", "name", "kind", "files", "chunks"} <= set(s) for s in info["sources"]))

    async def test_scope_info_without_project(self):
        for empty in ("", "   ", None):
            info = await self.service.scope_info(empty)
            self.assertIsNone(info["own"])
            self.assertEqual(info["linked_ids"], [])
            self.assertEqual(len(info["sources"]), 3)


if __name__ == "__main__":
    unittest.main()
