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


if __name__ == "__main__":
    unittest.main()
