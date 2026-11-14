"""Testes do ops_node com LLM falso e repositório git temporário.

Rode na raiz do projeto:  python -m unittest backend.graph.tests.test_ops_node -v
"""
import asyncio
import os
import pathlib
import subprocess
import tempfile
import unittest

from langchain_core.messages import AIMessage, HumanMessage

from backend.graph.ops_node import build_history, run_ops


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True).stdout.strip()


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        return self.replies.pop(0)


def call(name, args, ident):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": ident}])


class OpsNodeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        git(self.root, "init", "-q", "-b", "feat/x")
        git(self.root, "config", "user.email", "t@t.t")
        git(self.root, "config", "user.name", "T")
        (self.root / "a.py").write_text("x = 1\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")
        (self.root / "a.py").write_text("x = 2\n")
        (self.root / "b.py").write_text("b = 1\n")

    def tearDown(self):
        self._tmp.cleanup()

    def run_ops(self, llm, history=None):
        history = history or [HumanMessage(content="commita meus arquivos")]
        return asyncio.run(run_ops(history, str(self.root), "t1", llm=llm))

    def test_lists_changes_then_answers(self):
        llm = FakeLLM([call("git_changes_overview", {}, "1"), AIMessage(content="Achei a.py e b.py. Quais commito?")])
        answer = self.run_ops(llm)
        self.assertIn("Quais", answer)
        tool_message = llm.seen[1][-1]
        self.assertIn("a.py", tool_message.content)
        self.assertIn("b.py", tool_message.content)

    def test_diff_then_commit_only_chosen_file(self):
        llm = FakeLLM([
            call("git_diff_files", {"paths": ["a.py"]}, "1"),
            call("git_commit_files", {"paths": ["a.py"], "message": "fix: ajusta x"}, "2"),
            AIMessage(content="Commit feito."),
        ])
        answer = self.run_ops(llm)
        self.assertIn("Commit", answer)
        self.assertIn("a.py", answer)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "fix: ajusta x")
        self.assertIn("b.py", git(self.root, "status", "--porcelain"))

    def test_unknown_tool_and_tool_errors_do_not_crash(self):
        llm = FakeLLM([call("apaga_tudo", {}, "1"), call("git_commit_files", {"paths": ["zzz.py"], "message": "x"}, "2"), AIMessage(content="ok")])
        self.assertIn("não encontrei", self.run_ops(llm))
        self.assertIn("desconhecida", llm.seen[1][-1].content)
        self.assertEqual(len(llm.seen), 2)

    def test_round_limit(self):
        llm = FakeLLM([call("git_changes_overview", {}, str(i)) for i in range(20)])
        self.assertIn("Não consegui concluir", self.run_ops(llm))

    def test_without_workspace(self):
        answer = asyncio.run(run_ops([HumanMessage(content="commita")], "", None, llm=FakeLLM([])))
        self.assertIn("diretório de trabalho", answer)

    def test_zip_tool_result_goes_straight_to_the_user(self):
        with tempfile.TemporaryDirectory() as packs:
            os.environ["TASK_PACK_DIR"] = packs
            try:
                llm = FakeLLM([call("build_zip_files", {"names": ["a.py", "b.py"]}, "1"), AIMessage(content="nunca usado")])
                answer = self.run_ops(llm, [HumanMessage(content="me entregue os arquivos a.py e b.py")])
            finally:
                os.environ.pop("TASK_PACK_DIR", None)
        self.assertTrue(answer.startswith("Zip pronto"))
        self.assertIn("/api/handoff/zips/arquivos_", answer)
        self.assertIn("- a.py", answer)
        self.assertIn("- b.py", answer)
        self.assertEqual(len(llm.seen), 1)

    def test_invented_zip_link_is_rejected(self):
        fake = "Pronto! [x.zip](/api/handoff/zips/arquivos_inventado.zip)"
        llm = FakeLLM([AIMessage(content=fake), AIMessage(content=fake)])
        answer = self.run_ops(llm, [HumanMessage(content="me entregue o a.py")])
        self.assertIn("Não consegui gerar o zip", answer)
        self.assertIn("SISTEMA", llm.seen[1][-1].content)

    def test_history_keeps_only_human_and_plain_ai(self):
        class M:
            def __init__(self, type_, content, tool_calls=None, name=None):
                self.type, self.content, self.tool_calls, self.name = type_, content, tool_calls or [], name

        history = build_history([M("human", "oi"), M("ai", "", [{"name": "x"}]), M("tool", "r"), M("ai", "resposta")])
        self.assertEqual([m.content for m in history], ["oi", "resposta"])


if __name__ == "__main__":
    unittest.main()
