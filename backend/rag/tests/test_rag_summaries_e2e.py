"""Teste ponta a ponta do resumo por IA contra um Ollama FALSO (servidor HTTP local, sem rede externa):
    python -m unittest backend.rag.tests.test_rag_summaries_e2e -v
Reproduz o erro real: trocar o modelo e clicar em 'Reindexar' não fazia nada.
"""

import asyncio
import dataclasses
import json
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from backend.rag.config import load_config
from backend.rag.providers import OllamaSummarizer
from backend.rag.service import RagService
from backend.rag.store_memory import MemoryStore


class FakeOllama:
    """/api/embed e /api/generate. O comportamento do /api/generate depende do NOME do modelo."""

    def __init__(self):
        self.generate_calls = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/embed":
                    return self._send(200, {"embeddings": [[0.1] * 16 for _ in body["input"]]})
                outer.generate_calls += 1
                model = body["model"]
                if model == "inexistente":
                    return self._send(404, {"error": "model not found"})
                if model == "pensador" and "think" not in body:  # raciocínio sem 'think': gasta tudo pensando
                    return self._send(200, {"response": "", "thinking": "hmm", "done_reason": "length"})
                self._send(200, {"response": "Resumo escrito pela IA.", "done_reason": "stop"})

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class SummariesEndToEnd(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from backend.rag import providers

        patcher = mock.patch.object(providers.time, "sleep", lambda seconds: None)  # sem espera entre tentativas
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ollama = FakeOllama()
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name, "repo")
        self.repo.mkdir()
        (self.repo / "a.py").write_text("def f(x):\n    return x + 1\n\ndef g(y):\n    return y * 2\n", encoding="utf-8")
        self.store = MemoryStore()  # o "banco" sobrevive aos reinícios simulados

    async def asyncTearDown(self):
        self.ollama.close()
        self.tmp.cleanup()

    def service(self, model=""):
        """Simula (re)iniciar o servidor com RAG_SUMMARY_MODEL=model."""
        cfg = dataclasses.replace(load_config(), ollama_url=self.ollama.url, embed_dim=16, summary_model=model,
                                  work_dir=str(Path(self.tmp.name, "work")))
        return RagService(cfg, store=self.store)

    async def run_job(self, service, **kw):
        started = await service.ingest_workspace(str(self.repo), **kw)
        for _ in range(400):
            job = (await service.status(started["source_id"]))["job"]
            if job and job["status"] in {"done", "failed", "cancelled"}:
                return job
            await asyncio.sleep(0.02)
        raise AssertionError("job não terminou")

    def kinds(self):
        return sorted({c.get("summary_kind") for c in self.store.chunks})

    async def test_changing_model_and_plain_reindex_now_uses_the_ai(self):
        await self.run_job(self.service(""))
        self.assertEqual(self.kinds(), ["heuristic"])

        self.ollama.generate_calls = 0
        job = await self.run_job(self.service("bom"))  # só trocou o modelo e clicou em 'Reindexar'
        self.assertEqual(self.kinds(), ["llm:bom"])
        self.assertGreater(self.ollama.generate_calls, 0)
        self.assertIn("refeitos", job["note"])
        self.assertIn("escritos pela IA", job["note"])

        calls = self.ollama.generate_calls
        again = await self.run_job(self.service("bom"))  # nada a refazer agora
        self.assertLessEqual(self.ollama.generate_calls, calls + 1)  # no máximo o teste prévio da IA
        self.assertEqual(again["note"].count("refeitos"), 0)
        self.assertIn("0 novos", again["note"])

    async def test_agent_refresh_never_resummarizes_unchanged_files(self):
        await self.run_job(self.service(""))
        service = self.service("bom")
        self.ollama.generate_calls = 0
        await service.refresh_workspace(str(self.repo), min_interval=0)
        self.assertEqual(self.ollama.generate_calls, 0)
        self.assertEqual(self.kinds(), ["heuristic"])

    async def test_missing_model_is_reported_and_does_not_hammer_ollama(self):
        job = await self.run_job(self.service("inexistente"))
        self.assertEqual(self.kinds(), ["heuristic"])
        self.assertIn("IA de resumos indisponível", job["note"])
        self.assertIn("404", job["note"])
        self.assertLessEqual(self.ollama.generate_calls, 2)  # só o teste prévio; nenhuma chamada por trecho

    async def test_reasoning_model_without_think_is_rescued(self):
        job = await self.run_job(self.service("pensador"))
        self.assertEqual(self.kinds(), ["llm:pensador"])
        self.assertNotIn("indisponível", job["note"])

    async def test_circuit_breaker_stops_after_repeated_failures(self):
        summarizer = OllamaSummarizer(self.ollama.url, "inexistente")
        from backend.rag.chunker import chunk_file

        chunk = chunk_file("a.py", "def f():\n    return 1\n", "python")[0]
        for _ in range(OllamaSummarizer.MAX_CONSECUTIVE_FAILURES):
            summarizer.summarize(chunk)
        calls = self.ollama.generate_calls
        self.assertTrue(summarizer.disabled)
        summarizer.summarize(chunk)  # desativado: não chama mais o Ollama
        self.assertEqual(self.ollama.generate_calls, calls)
        summarizer.reset()
        self.assertFalse(summarizer.disabled)

    async def test_summary_counts_and_summarizer_test(self):
        await self.run_job(self.service("bom"))
        service = self.service("bom")
        sources = await service.list_sources(True)
        self.assertTrue(sources[0]["summaries"])
        self.assertTrue(all(k.startswith("llm:") for k in sources[0]["summaries"]))
        ok = await service.test_summarizer()
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["mode"], "ia")
        off = await self.service("").test_summarizer()
        self.assertFalse(off["ok"])
        self.assertEqual(off["mode"], "heuristico")
        bad = await self.service("inexistente").test_summarizer()
        self.assertFalse(bad["ok"])
        self.assertIn("404", bad["message"])


if __name__ == "__main__":
    unittest.main()
