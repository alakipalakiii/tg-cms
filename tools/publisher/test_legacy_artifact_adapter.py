from __future__ import annotations

import unittest

from tools.publisher.legacy_artifact_adapter import (
    LegacyArtifactError,
    adapt_legacy_read_only,
    assert_no_new_path_authority,
)


class LegacyAdapterTests(unittest.TestCase):
    def test_all_frozen_legacy_inputs_are_read_only(self):
        for name in ("transaction.json", "bundle-index.json", "remote-proof-result.json", "production-result.json"):
            adapted = adapt_legacy_read_only(name, {"synthetic": True})
            self.assertEqual("READ_ONLY", adapted["authority"])
            self.assertFalse(adapted["may_authorize_mutation"])
            self.assertFalse(adapted["may_authorize_replay"])
            self.assertFalse(adapted["may_authorize_ready_to_persist"])
            self.assertFalse(adapted["may_authorize_completed"])
            assert_no_new_path_authority(adapted)

    def test_adapter_rejects_new_authority(self):
        adapted = adapt_legacy_read_only("production-result.json", {})
        adapted["may_authorize_completed"] = True
        with self.assertRaises(LegacyArtifactError):
            assert_no_new_path_authority(adapted)

    def test_unknown_legacy_artifact_rejected(self):
        with self.assertRaises(LegacyArtifactError):
            adapt_legacy_read_only("other.json", {})


if __name__ == "__main__":
    unittest.main()
