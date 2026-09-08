import tempfile
import unittest
from pathlib import Path

from core import PromotionGuard, delta, fingerprint, route_gate, save_state_after_promotion


class PublisherCoreTests(unittest.TestCase):
    def test_fingerprint_is_stable(self):
        self.assertEqual(fingerprint({"b": 2, "a": 1}), fingerprint({"a": 1, "b": 2}))

    def test_delta_no_change_add_edit_delete(self):
        self.assertEqual(delta({"1": "a"}, {"1": "a"})["SAME_CONTRACT_DELTA"], "PASS")
        self.assertEqual(delta({}, {"1": "a"})["added"], ["1"])
        self.assertEqual(delta({"1": "a"}, {"1": "b"})["changed"], ["1"])
        self.assertEqual(delta({"1": "a"}, {})["removed"], ["1"])

    def test_route_gate_and_promotion_guard(self):
        self.assertTrue(route_gate(["/", "/post/1"], {"/": "x", "/post/1": "y"}, {"/": "https://x/", "/post/1": "https://x/1"})["PASS"])
        guard = PromotionGuard("v1", "v1", True, True, True, True, True)
        self.assertTrue(guard.allowed())
        self.assertFalse(PromotionGuard("v1", "v2", True, True, True, True, True).allowed())

    def test_state_commit_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with self.assertRaises(RuntimeError):
                save_state_after_promotion(path, {"x": 1}, True, False)
            save_state_after_promotion(path, {"x": 1}, True, True)
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
