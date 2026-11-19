import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "diff_review.py"
_spec = importlib.util.spec_from_file_location("diff_review_under_test", _PATH)
dr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dr)

ORIGINAL = """from fastapi import APIRouter

router = APIRouter()


def register_checkout(item, qty):
    if item.status == "em_reparo":
        raise ValueError("item em reparo")
    before_qty = item.quantity
    item.quantity -= qty
    item.updated_by = "sistema"
    log_movement(item, qty, before_qty)
    return item


def other():
    return 1
"""


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        os.environ["TASK_REVIEW_LIB_SECONDS"] = "3"
        self.path = self.root / "app" / "movements_router.py"
        self.path.parent.mkdir(parents=True)
        self.path.write_text(ORIGINAL, encoding="utf-8")
        (self.root / "app" / "models.py").write_text("class Item:\n    quantity = 0\n    status = ''\n    updated_by = ''\n", encoding="utf-8")

    def tearDown(self):
        os.environ.pop("TASK_REVIEW_LIB_SECONDS", None)
        os.environ.pop("TASK_REVIEW", None)
        os.environ.pop("TASK_REVIEW_UNKNOWN", None)
        self.tmp.cleanup()

    def _review(self, new_text, original=ORIGINAL):
        self.path.write_text(new_text, encoding="utf-8")
        return dr.review_changes(str(self.root), {self.path: original.encode("utf-8")})

    def test_block_pasted_twice_is_blocked(self):
        block = '    before_qty = item.quantity\n    item.quantity -= qty\n    item.updated_by = "sistema"\n    log_movement(item, qty, before_qty)\n'
        doubled = ORIGINAL.replace(block, block + block, 1)
        out = self._review(doubled)
        self.assertEqual(len(out["blocking"]), 1)
        self.assertIn("duplicidade", out["blocking"][0])
        self.assertEqual(out["risk"], "alto")

    def test_normal_edit_is_clean(self):
        out = self._review(ORIGINAL.replace('    if item.status == "em_reparo":\n        raise ValueError("item em reparo")\n',
                                            '    if item.quantity < qty:\n        raise ValueError("estoque insuficiente")\n'))
        self.assertEqual((out["blocking"], out["warnings"], out["risk"]), ([], [], "baixo"))

    def test_new_file_with_repetition_is_not_checked(self):
        new = self.root / "app" / "novo.py"
        block = "a = 1\nb = 2\nc = 3\nd = 4 + a + b + c + 100000\n" * 3
        new.write_text(block, encoding="utf-8")
        self.assertEqual(dr.review_changes(str(self.root), {new: None})["blocking"], [])

    def test_invented_attribute_warns_and_existing_one_does_not(self):
        bad = self._review(ORIGINAL.replace('    if item.status == "em_reparo":', '    if item.is_defective:'))
        self.assertEqual(bad["blocking"], [])
        self.assertTrue(any("is_defective" in w for w in bad["warnings"]))
        (self.root / "app" / "models.py").write_text("class Item:\n    is_defective = False\n", encoding="utf-8")
        good = self._review(ORIGINAL.replace('    if item.status == "em_reparo":', '    if item.is_defective:'))
        self.assertEqual(good["warnings"], [])

    def test_library_attribute_is_not_flagged(self):
        out = self._review(ORIGINAL + "\n\nasync def run():\n    return await asyncio.to_thread(other)\n")
        self.assertEqual(out["warnings"], [])

    def test_unknown_names_can_block_or_be_disabled(self):
        text = ORIGINAL.replace('    if item.status == "em_reparo":', '    if item.is_defective:')
        os.environ["TASK_REVIEW_UNKNOWN"] = "block"
        self.assertEqual(len(self._review(text)["blocking"]), 1)
        os.environ["TASK_REVIEW_UNKNOWN"] = "off"
        self.assertEqual(self._review(text)["warnings"], [])

    def test_big_deletion_warns(self):
        big = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(20))
        out = self._review("x = 1\n", original=big)
        self.assertTrue(any("apagou" in w for w in out["warnings"]))

    def test_disabled_by_env(self):
        os.environ["TASK_REVIEW"] = "0"
        block = '    before_qty = item.quantity\n    item.quantity -= qty\n    item.updated_by = "sistema"\n    log_movement(item, qty, before_qty)\n'
        self.assertEqual(self._review(ORIGINAL.replace(block, block + block, 1))["blocking"], [])


if __name__ == "__main__":
    unittest.main()


def test_related_test_files_and_free_task_checks(tmp_path, monkeypatch):
    from backend.graph.nodes import _related_test_files, _run_free_task_logic_checks
    from backend.graph.task_journal import begin_journal, journal_end, record_write
    from types import SimpleNamespace

    monkeypatch.setenv("TASK_JOURNAL_DIR", str(tmp_path / "journal"))
    pkg = tmp_path / "tests"
    pkg.mkdir(parents=True)
    target = tmp_path / "sample_mod.py"
    body = (
        "    subtotal = qty * price\n"
        "    discount = subtotal * 0.10\n"
        "    final_value = subtotal - discount\n"
        "    return round(final_value, 2)\n"
    )
    original_code = "def calc_total(qty, price):\n" + body
    target.write_text(original_code, encoding="utf-8")
    test_file = pkg / "test_sample_mod.py"
    test_file.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "from sample_mod import calc_total\n\n"
        "def test_calc_total():\n"
        "    assert calc_total(2, 50) == 90.0\n",
        encoding="utf-8",
    )

    matches = _related_test_files(str(tmp_path), ["sample_mod.py"])
    assert "tests/test_sample_mod.py" in matches

    begin_journal(str(tmp_path), 999)
    record_write(target)
    target.write_text(original_code + body, encoding="utf-8")
    task = SimpleNamespace(id=999, title="teste", description="teste")
    blocking, _warnings = _run_free_task_logic_checks(str(tmp_path), task, [], ["sample_mod.py"])
    journal_end(str(tmp_path))
    assert any("duplicidade" in item for item in blocking)


def test_filter_existing_duplicates():
    from backend.api.task_split import filter_existing_duplicates

    existing = [{
        "title": "Corrigir cálculo de estoque",
        "description": "Ajusta o cálculo de disponibilidade ignorando itens em reparo no endpoint de saída.",
        "files": ["app/routers/movements_router.py"],
    }]
    candidates = [{
        "title": "Corrigir cálculo de estoque",
        "description": "Ajusta o cálculo de disponibilidade ignorando itens em reparo no endpoint de saída.",
        "files": ["app/routers/movements_router.py"],
    }]
    kept, skipped = filter_existing_duplicates(candidates, existing)
    assert kept == []
    assert len(skipped) == 1
