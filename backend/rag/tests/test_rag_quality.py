"""Testes de qualidade do índice (chunker sem perda, resumos, cache por tipo, mapa). Na raiz do projeto:
    python -m unittest backend.rag.tests.test_rag_quality -v
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.rag.chunker import chunk_file
from backend.rag.pipeline import format_summary_note, ingest
from backend.rag.providers import HashEmbedder, HeuristicSummarizer, OllamaSummarizer, Summary
from backend.rag.repo_map import build_repo_map
from backend.rag.store_memory import MemoryStore


def summary_of(code, kind="function", name="f", language="python"):
    from backend.rag.entities import Chunk

    chunk = Chunk(path="a.py", language=language, kind=kind, qualname=name, parent="", start_line=1,
                  end_line=code.count("\n") + 1, code=code)
    return HeuristicSummarizer().summarize(chunk)


class ChunkerQualityTests(unittest.TestCase):
    def test_huge_constants_become_named_chunks_and_nothing_is_lost(self):
        text = "import os\n\n" + "".join(f'PROMPT_{i} = f"""\n' + "linha de prompt\n" * 40 + '"""\n\n' for i in range(5))
        total = len(text.split("\n"))
        chunks = chunk_file("prompts.py", text, "python")
        consts = [c for c in chunks if c.kind == "constant"]
        self.assertEqual([c.qualname for c in consts], [f"PROMPT_{i}" for i in range(5)])
        self.assertGreaterEqual(max(c.end_line for c in chunks), total - 2)  # o fim do arquivo está coberto

    def test_header_is_not_truncated_at_200_lines(self):
        text = "".join(f"CAMPO_{i} = {i}\n" for i in range(450))
        chunks = chunk_file("cfg.py", text, "python")
        self.assertTrue(all(c.kind == "header" for c in chunks))
        self.assertGreaterEqual(max(c.end_line for c in chunks), 450)
        self.assertIn("CAMPO_449", "\n".join(c.code for c in chunks))

    def test_split_function_shares_hash_and_symbol_code(self):
        code = "def f(a):\n" + "".join(f"    x{i} = a + {i}\n" for i in range(450))
        parts = chunk_file("a.py", code, "python")
        self.assertGreater(len(parts), 1)
        self.assertEqual(len({p.content_hash for p in parts}), 1)
        self.assertTrue(all(p.symbol_code.startswith("def f(a):") for p in parts))
        summaries = {HeuristicSummarizer().summarize(p) for p in parts}
        self.assertEqual(len(summaries), 1)
        self.assertTrue(next(iter(summaries)).startswith("Função f(a)."))


class HeuristicSummaryTests(unittest.TestCase):
    def test_endpoint_and_noise_filter(self):
        code = (
            '@router.post("/chat")\nasync def chat_with_ai(payload, graph):\n'
            "    data = payload.get('a')\n    items.append(1)\n    return await graph.ainvoke(data)\n"
        )
        text = summary_of(code, name="chat_with_ai")
        self.assertIn("Endpoint POST /chat", text)
        self.assertIn("ainvoke", text)
        self.assertNotIn("append", text)
        self.assertNotIn("Usa: get", text)
        self.assertNotIn("Usa: post", text)

    def test_tool_decorator(self):
        self.assertTrue(summary_of("@tool\nasync def search(query, runtime):\n    return query\n", name="search").startswith("Tool do agente"))

    def test_class_with_fields_and_bases(self):
        code = "class ChatPayload(BaseModel):\n    message: str\n    workspace_path: str\n"
        self.assertEqual(summary_of(code, kind="class", name="ChatPayload"),
                         "Classe ChatPayload(BaseModel) com campos message, workspace_path.")

    def test_constant_summary(self):
        code = 'GENERATE_NODE_PROMPT = f"""\nVocê é um agente de implementação.\nSiga as regras.\n"""\n'
        text = summary_of(code, kind="constant", name="GENERATE_NODE_PROMPT")
        self.assertIn("Constante GENERATE_NODE_PROMPT", text)
        self.assertIn("Você é um agente", text)


class OllamaSummarizerTests(unittest.TestCase):
    def chunk(self):
        return chunk_file("a.py", "def f(a):\n    return a\n", "python")[0]

    def test_gpt_oss_gets_think_low_and_enough_tokens(self):
        seen = {}

        def fake(url, payload, timeout, retries=2):
            seen.update(payload)
            return {"response": "Retorna o argumento recebido."}

        with mock.patch("backend.rag.providers._post_json", fake):
            result = OllamaSummarizer("http://x", "gpt-oss:20b").summarize(self.chunk())
        self.assertEqual(seen["think"], "low")
        self.assertGreaterEqual(seen["options"]["num_predict"], 512)
        self.assertEqual(result.kind, "llm:gpt-oss:20b")

    def test_empty_response_falls_back_and_records_why(self):
        with mock.patch("backend.rag.providers._post_json", lambda *a, **k: {"response": "", "done_reason": "length"}):
            summarizer = OllamaSummarizer("http://x", "gpt-oss:20b")
            result = summarizer.summarize(self.chunk())
        self.assertEqual(result.kind, "heuristic")
        self.assertIn("vazia", summarizer.last_error)
        self.assertIn("length", summarizer.last_error)

    def test_retries_without_think_when_model_rejects_it(self):
        calls = []

        def fake(url, payload, timeout, retries=2):
            calls.append("think" in payload)
            if "think" in payload:
                raise RuntimeError("Falha ao chamar: HTTP Error 400: Bad Request")
            return {"response": "<think>hmm</think> Retorna a."}

        with mock.patch("backend.rag.providers._post_json", fake):
            summarizer = OllamaSummarizer("http://x", "outro-modelo", think="low")
            result = summarizer.summarize(self.chunk())
        self.assertEqual(calls, [True, False])
        self.assertIsNone(summarizer.think)
        self.assertEqual((result.kind, str(result)), ("llm:outro-modelo", "Retorna a."))

    def test_connection_error_falls_back(self):
        def boom(*a, **k):
            raise RuntimeError("ollama fora do ar")

        with mock.patch("backend.rag.providers._post_json", boom):
            summarizer = OllamaSummarizer("http://x", "m")
            result = summarizer.summarize(self.chunk())
        self.assertEqual(result.kind, "heuristic")
        self.assertIn("fora do ar", summarizer.last_error)


class FakeLLM:
    kind = "llm:fake"
    last_error = ""

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail
        if fail:
            self.last_error = "resposta vazia (done_reason=length)"

    def summarize(self, chunk):
        self.calls += 1
        if self.fail:
            return Summary(HeuristicSummarizer()._text(chunk), "heuristic")
        return Summary("Frase escrita pela IA.", "llm:fake")


class SummaryKindPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        Path(self.tmp.name, "a.py").write_text("X = 1\n\ndef f():\n    return X\n\ndef g():\n    return 2\n", encoding="utf-8")
        self.store = MemoryStore()
        self.embedder = HashEmbedder(64)
        self.sid = await self.store.upsert_source("s", "workspace", self.tmp.name)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def run_ingest(self, summarizer, **kw):
        return await ingest(self.store, self.embedder, summarizer, self.sid, self.tmp.name, **kw)

    async def kinds(self):
        return {c.get("summary_kind") for c in self.store.chunks}

    async def test_heuristic_summaries_are_replaced_by_llm_on_forced_reindex(self):
        await self.run_ingest(HeuristicSummarizer())
        self.assertEqual(await self.kinds(), {"heuristic"})
        llm = FakeLLM()
        result = await self.run_ingest(llm, force=True)
        self.assertGreater(llm.calls, 0)
        self.assertEqual(await self.kinds(), {"llm:fake"})
        self.assertEqual(result["summaries"]["llm"], result["summaries"]["new"])
        self.assertTrue(all(c["summary"] == "Frase escrita pela IA." for c in self.store.chunks))
        calls = llm.calls
        again = await self.run_ingest(llm, force=True)  # já é da IA: nada a refazer
        self.assertEqual((llm.calls, again["summaries"]["new"]), (calls, 0))

    async def test_without_force_unchanged_files_are_not_touched(self):
        await self.run_ingest(HeuristicSummarizer())
        llm = FakeLLM()
        await self.run_ingest(llm)
        self.assertEqual(llm.calls, 0)  # arquivo não mudou: por isso existe 'Regerar resumos' (force)

    async def test_llm_failure_is_reported_and_retried_later(self):
        failing = FakeLLM(fail=True)
        result = await self.run_ingest(failing)
        info = result["summaries"]
        self.assertEqual((info["llm"], info["fallback"] > 0), (0, True))
        self.assertIn("vazia", info["last_error"])
        note = format_summary_note(info)
        self.assertIn("ATENÇÃO", note)
        self.assertEqual(await self.kinds(), {"heuristic"})  # marcados como heurísticos, então a IA os refaz depois
        working = FakeLLM()
        await self.run_ingest(working, force=True)
        self.assertGreater(working.calls, 0)
        self.assertEqual(await self.kinds(), {"llm:fake"})


class RepoMapQualityTests(unittest.TestCase):
    def test_markdown_titles_with_dots_are_kept(self):
        rows = [dict(path="a.md", kind="section", qualname="1. Como a ingestão ocorre", parent="", start_line=1, end_line=9, summary="x", part=1)]
        self.assertIn("section 1. Como a ingestão ocorre (L1-9)", build_repo_map(rows))

    def test_split_function_is_one_line_with_full_range(self):
        rows = [dict(path="n.py", kind="function", qualname="gen", parent="", start_line=s, end_line=e, summary="Gera tudo.", part=p)
                for p, (s, e) in enumerate([(431, 630), (621, 808)], start=1)]
        text = build_repo_map(rows)
        self.assertEqual(text.count("def gen"), 1)
        self.assertIn("def gen (L431-808)", text)

    def test_header_only_files_and_constants(self):
        rows = [dict(path="p.py", kind="header", qualname="<cabeçalho do módulo>", parent="", start_line=1, end_line=3, summary="Cabeçalho de p.py: importa os.", part=1),
                dict(path="q.py", kind="constant", qualname="BIG_PROMPT", parent="", start_line=5, end_line=60, summary="Constante BIG_PROMPT (56 linhas).", part=1)]
        text = build_repo_map(rows)
        self.assertIn("(só cabeçalho/constantes)", text)
        self.assertIn("const BIG_PROMPT (L5-60)", text)


if __name__ == "__main__":
    unittest.main()
