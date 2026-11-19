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
