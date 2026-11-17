import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "audit_core.py"
_spec = importlib.util.spec_from_file_location("audit_core_under_test", _PATH)
ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ac)


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class ParserTests(unittest.TestCase):
    def test_parse_ruff(self):
        raw = json.dumps([
            {"code": "F821", "message": "Undefined name `x`", "filename": "/w/a.py", "location": {"row": 3, "column": 1}, "end_location": {"row": 3, "column": 2}},
            {"code": "F401", "message": "unused import", "filename": "/w/a.py", "location": {"row": 1, "column": 1}, "end_location": {"row": 1, "column": 9}},
        ])
        out = ac.parse_ruff(raw, "/w")
        self.assertEqual([(f["file"], f["kind"], f["severity"]) for f in out], [("a.py", "bug", "high"), ("a.py", "dead_code", "low")])

    def test_parse_vulture(self):
        out = ac.parse_vulture("backend/x.py:12: unused function 'foo' (60% confidence)\nlixo\nb.py:3: unused import 'os' (90% confidence)\n", "/w")
        self.assertEqual([(f["file"], f["line"], f["confidence"]) for f in out], [("backend/x.py", 12, "low"), ("b.py", 3, "high")])

    def test_parse_radon_skips_simple_blocks(self):
        raw = json.dumps({"a.py": [{"name": "f", "complexity": 25, "rank": "D", "lineno": 4, "endline": 90}, {"name": "g", "complexity": 5, "rank": "A", "lineno": 1, "endline": 2}], "b.py": {"error": "x"}})
        out = ac.parse_radon(raw, "/w")
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["severity"], out[0]["rule"]), ("medium", "CC25"))

    def test_parse_bandit_ignores_assert(self):
        raw = json.dumps({"results": [
            {"filename": "a.py", "line_number": 2, "issue_text": "shell", "issue_severity": "HIGH", "issue_confidence": "MEDIUM", "test_id": "B602"},
            {"filename": "a.py", "line_number": 5, "issue_text": "assert", "issue_severity": "LOW", "issue_confidence": "HIGH", "test_id": "B101"}]})
        out = ac.parse_bandit(raw, "/w")
        self.assertEqual([(f["rule"], f["severity"], f["confidence"]) for f in out], [("B602", "high", "medium")])


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.environ["AUDIT_DIR"] = os.path.join(self.root, "_state")
        Path(self.root, "a.py").write_text(
            "import os\n\n@app.get('/x')\ndef rota():\n    return 1\n\ndef morta():\n    return 2\n\ndef usada():\n    return 3\n", encoding="utf-8")
        Path(self.root, "b.py").write_text("from a import usada\nusada()\n", encoding="utf-8")

    def tearDown(self):
        os.environ.pop("AUDIT_DIR", None)
        self.tmp.cleanup()

    def _f(self, line, msg, tool="vulture", rule="unused", conf="medium", file="a.py"):
        return ac._finding(file, line, "dead_code", "low", conf, tool, rule, msg)

    def test_snippet_comes_from_real_file_and_invalid_lines_dropped(self):
        good, dropped = ac.validate_findings(self.root, [self._f(7, "unused function 'morta' (60%)"), self._f(99, "unused function 'x' (60%)"), self._f(1, "x", file="../fora.py")])
        self.assertEqual(len(good), 1)
        self.assertIn("def morta", good[0]["snippet"])
        self.assertEqual(len(good[0]["id"]), 12)
        self.assertEqual(len(dropped), 2)

    def test_decorated_and_mismatched_names_dropped(self):
        good, dropped = ac.validate_findings(self.root, [self._f(4, "unused function 'rota' (60%)"), self._f(7, "unused function 'outra' (60%)")])
        self.assertEqual(good, [])
        self.assertEqual(len(dropped), 2)

    def test_name_used_elsewhere_lowers_confidence(self):
        good, _ = ac.validate_findings(self.root, [self._f(10, "unused function 'usada' (80%)", conf="high")])
        self.assertEqual(good[0]["confidence"], "low")
        self.assertIn("aparece", good[0]["note"])

    def test_reexport_in_init_dropped(self):
        Path(self.root, "__init__.py").write_text("from a import usada\n", encoding="utf-8")
        f = ac._finding("__init__.py", 1, "dead_code", "low", "high", "ruff", "F401", "unused import")
        good, dropped = ac.validate_findings(self.root, [f])
        self.assertEqual((good, len(dropped)), ([], 1))

    def test_false_positive_registry_survives_line_shift(self):
        good, _ = ac.validate_findings(self.root, [self._f(7, "unused function 'morta' (60%)")])
        self.assertTrue(ac.mark_false_positive(self.root, good[0], "usada por reflexão"))
        src = Path(self.root, "a.py")
        src.write_text("# novo\n" + src.read_text(encoding="utf-8"), encoding="utf-8")
        again, _ = ac.validate_findings(self.root, [self._f(8, "unused function 'morta' (60%)")])
        self.assertEqual(again[0]["id"], good[0]["id"])
        self.assertIn(again[0]["id"], ac.load_false_positives(self.root))
        self.assertTrue(ac.unmark_false_positive(self.root, again[0]["id"]))
        self.assertEqual(ac.load_false_positives(self.root), {})


class DuplicationAndTasksTests(unittest.TestCase):
    def test_ast_duplicates_ignores_names_and_constants(self):
        body = "    total = 0\n    for item in {0}:\n        if item > {1}:\n            total += item * {1}\n        else:\n            total -= 1\n    result = [total, total + 1, total + 2]\n    return result\n"
        with tempfile.TemporaryDirectory() as root:
            Path(root, "m.py").write_text("def somar(xs):\n" + body.format("xs", 3) + "\n\ndef outra(ys):\n" + body.format("ys", 7), encoding="utf-8")
            out = ac.ast_duplicates(root, ["m.py"])
        self.assertEqual(len(out), 1)
        self.assertIn("somar", out[0]["message"])

    def test_findings_to_tasks_groups_by_file_and_is_dynamic(self):
        f = ac._finding("a.py", 3, "bug", "high", "high", "ruff", "F821", "Undefined name")
        f["snippet"], f["note"] = "x = y", ""
        g = dict(f, line=9)
        tasks = ac.findings_to_tasks([f, g, dict(f, file="b.js")], max_per_task=1)
        self.assertEqual(len(tasks), 3)
        self.assertTrue(all(t["steps"] == [] and (chr(96) * 3) not in t["description"] for t in tasks))
        self.assertEqual(tasks[0]["verify"], [{"type": "python_syntax", "path": "a.py"}])
        self.assertEqual(tasks[2]["verify"], [])


class RunAuditTests(unittest.TestCase):
    def test_missing_tools_do_not_break_and_incremental_uses_git(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
            os.environ["AUDIT_DIR"] = os.path.join(root, "_state")
            try:
                _git(root, "init", "-q")
                _git(root, "config", "user.email", "t@t")
                _git(root, "config", "user.name", "t")
                Path(root, "velho.py").write_text("x = 1\n", encoding="utf-8")
                _git(root, "add", "-A")
                _git(root, "commit", "-q", "-m", "i")
                Path(root, "novo.py").write_text("y = 2\n", encoding="utf-8")
                self.assertEqual(ac.changed_files(root), ["novo.py"])
                result = ac.run_audit(root, incremental=True, tools=("duplication", "ferramenta_que_nao_existe"))
                self.assertEqual(result["files"], 1)
                self.assertEqual(result["findings"], [])
                self.assertIn("ferramenta", result["tools"]["ferramenta_que_nao_existe"])
            finally:
                os.environ.pop("AUDIT_DIR", None)


if __name__ == "__main__":
    unittest.main()


class ChatCommandTests(unittest.TestCase):
    def test_rel_handles_windows_and_posix_absolute_paths(self):
        self.assertEqual(ac._rel("C:\\proj\\sub\\a.py", "C:\\proj"), "sub/a.py")
        self.assertEqual(ac._rel("c:/PROJ/a.py", "C:\\proj"), "a.py")
        self.assertEqual(ac._rel("/w/a.py", "/w"), "a.py")
        self.assertEqual(ac._rel("pasta\\b.py", "/w"), "pasta/b.py")

    def test_parse_command_variants(self):
        self.assertIsNone(ac.parse_command("faça uma auditoria"))
        self.assertIsNone(ac.parse_command("x" * 60 + " @audit"))
        run = ac.parse_command("@audit diff base=main min=medium tools=ruff,xx backend/api")
        self.assertEqual((run["cmd"], run["incremental"], run["base"], run["min"], run["tools"], run["paths"]),
                         ("run", True, "main", "medium", ("ruff",), ["backend/api"]))
        self.assertEqual(ac.parse_command("@auditoria")["cmd"], "run")
        self.assertEqual(ac.parse_command("@audit tasks 1 3"), {"cmd": "tasks", "args": ["1", "3"]})
        self.assertEqual(ac.parse_command("@audit falso 2 usada por reflexão"), {"cmd": "fp", "args": ["2"], "reason": "usada por reflexão"})
        self.assertEqual(ac.parse_command("@audit desfazer abc")["args"], ["abc"])
        self.assertEqual(ac.parse_command("@audit ajuda")["cmd"], "help")

    def test_expand_paths_and_select_findings(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "pkg").mkdir()
            Path(root, "pkg", "a.py").write_text("x = 1\n", encoding="utf-8")
            Path(root, "pkg", "b.txt").write_text("x", encoding="utf-8")
            Path(root, "c.py").write_text("y = 1\n", encoding="utf-8")
            files, errors = ac.expand_paths(root, ["pkg", "c.py", "../fora", "nada.py"])
        self.assertEqual(files, ["c.py", "pkg/a.py"])
        self.assertEqual(len(errors), 2)
        items = [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}]
        self.assertEqual(ac.select_findings(items, []), items)
        self.assertEqual([f["id"] for f in ac.select_findings(items, ["3", "i1", "9", "3"])], ["i3", "i1"])

    def test_last_report_roundtrip_and_format(self):
        with tempfile.TemporaryDirectory() as root:
            os.environ["AUDIT_DIR"] = os.path.join(root, "_s")
            try:
                f = ac._finding("a.py", 2, "bug", "high", "high", "ruff", "F821", "Undefined name")
                f["snippet"], f["id"] = "x = y", "abc123abc123"
                result = {"findings": [f], "tools": {"ruff": "ok", "bandit": "ausente (pip install bandit)"}, "files": 3, "dropped": ["z"], "ignored_false_positives": 1}
                ac.save_last(root, "thread/1", result)
                self.assertEqual(ac.load_last(root, "thread/1")["findings"][0]["id"], "abc123abc123")
                self.assertIsNone(ac.load_last(root, "outra"))
            finally:
                os.environ.pop("AUDIT_DIR", None)
        text = ac.format_report(result)
        self.assertIn("a.py:2", text)
        self.assertIn("1 alta", text)
        self.assertIn("@audit tasks", text)
        self.assertIn("Nenhum achado", ac.format_report({"findings": [], "tools": {}, "files": 0}))


class NaturalLanguageTests(unittest.TestCase):
    def test_single_and_multiple_files(self):
        one = ac.parse_command("Audite o arquivo backend/graph/executor.py")
        self.assertEqual((one["cmd"], one["paths"], one["incremental"]), ("run", ["backend/graph/executor.py"], False))
        many = ac.parse_command("audite os arquivos executor.py, task_guards.py e <task_journal.py>.")
        self.assertEqual(many["paths"], ["executor.py", "task_guards.py", "task_journal.py"])
        self.assertEqual(ac.parse_command("Por favor, poderia auditar x.js")["paths"], ["x.js"])
        self.assertEqual(ac.parse_command("faça uma auditoria do arquivo a.py")["paths"], ["a.py"])

    def test_folders_project_and_changes(self):
        self.assertEqual(ac.parse_command("Audite a pasta backend/api")["paths"], ["backend/api"])
        self.assertEqual(ac.parse_command("audite a pasta rag")["paths"], ["rag"])
        self.assertEqual(ac.parse_command("Audite o projeto")["paths"], [])
        diff = ac.parse_command("Audite o que mudou")
        self.assertEqual((diff["cmd"], diff["incremental"], diff["paths"]), ("run", True, []))

    def test_unrelated_messages_are_left_to_the_llm(self):
        self.assertIsNone(ac.parse_command("Audite esta função e me explique o resultado"))
        self.assertIsNone(ac.parse_command("faça uma auditoria"))
        self.assertIsNone(ac.parse_command("preciso que você audite x.py " + "y" * 450))
        self.assertIsNone(ac.parse_command("o que é uma auditoria de código?"))

    def test_expand_paths_resolves_bare_file_names(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "pkg").mkdir()
            Path(root, "pkg", "unico.py").write_text("x = 1\n", encoding="utf-8")
            Path(root, "pkg", "dup.py").write_text("x = 1\n", encoding="utf-8")
            Path(root, "dup.py").write_text("x = 1\n", encoding="utf-8")
            files, errors = ac.expand_paths(root, ["unico.py", "dup.py", "pkg/dup.py", "faltando.py"])
        self.assertEqual(files, ["dup.py", "pkg/dup.py", "pkg/unico.py"])
        self.assertEqual(len(errors), 1)
        self.assertIn("faltando.py", errors[0])
