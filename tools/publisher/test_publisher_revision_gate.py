from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "m9"))
import m9.publisher_runner as runner  # noqa: E402


def test_real_runner_no_change_does_not_export() -> None:
    with tempfile.TemporaryDirectory() as directory:
        old_cwd = Path.cwd()
        old_env = os.environ.copy()
        try:
            os.chdir(directory)
            state = Path(directory) / "state.json"
            state.write_text(json.dumps({"published_content_revision": 10}), encoding="utf-8")
            static_state = Path(directory) / "static-state.json"
            static_state.write_text(json.dumps({
                "current_version": "static-v1", "current_version_type": "STATIC",
            }), encoding="utf-8")
            old_state, old_static_state = runner.STATE, runner.STATIC_STATE
            runner.STATE = state
            runner.STATIC_STATE = static_state
            os.environ.update({
                "PUBLISHER_MODE": "PUBLISH",
                "MAHOON_PUBLISHER_STATE": str(state),
            })
            with patch("publisher.cloudflare_wrangler.active_deployment", return_value={
                "id": "deployment-v1",
                "versions": [{"version_id": "static-v1", "percentage": 100}],
            }), patch("publisher.state_machine.live_static_baseline", return_value=(True, {})), \
                    patch.object(runner, "fetch_public_content_revision", return_value=(10, "2026-09-14T13:00:00Z", {})):
                with patch.object(runner, "export_content", side_effect=AssertionError("export must not run")):
                    assert runner.main() == 0
            evidence = json.loads(
                (Path(directory) / "runner-evidence" / "public-content-revision-lookup.json").read_text()
            )
            assert evidence["request_count"] == 1
            assert evidence["NO_CHANGE_DETECTED"] is True
        finally:
            os.chdir(old_cwd)
            runner.STATE, runner.STATIC_STATE = old_state, old_static_state
            os.environ.clear()
            os.environ.update(old_env)


def test_real_runner_revision_failure_is_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        old_cwd = Path.cwd()
        old_env = os.environ.copy()
        try:
            os.chdir(directory)
            state = Path(directory) / "state.json"
            state.write_text(json.dumps({"published_content_revision": 10}), encoding="utf-8")
            static_state = Path(directory) / "static-state.json"
            static_state.write_text(json.dumps({
                "current_version": "static-v1", "current_version_type": "STATIC",
            }), encoding="utf-8")
            old_state, old_static_state = runner.STATE, runner.STATIC_STATE
            runner.STATE = state
            runner.STATIC_STATE = static_state
            os.environ.update({
                "PUBLISHER_MODE": "PUBLISH",
                "MAHOON_PUBLISHER_STATE": str(state),
            })
            with patch("publisher.cloudflare_wrangler.active_deployment", return_value={
                "id": "deployment-v1",
                "versions": [{"version_id": "static-v1", "percentage": 100}],
            }), patch("publisher.state_machine.live_static_baseline", return_value=(True, {})), \
                    patch.object(runner, "fetch_public_content_revision", side_effect=RuntimeError("HTTP_500")):
                with patch.object(runner, "export_content", side_effect=AssertionError("export must not run")):
                    assert runner.main() == 5
        finally:
            os.chdir(old_cwd)
            runner.STATE, runner.STATIC_STATE = old_state, old_static_state
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    test_real_runner_no_change_does_not_export()
    test_real_runner_revision_failure_is_fail_closed()
    print("CI_NOCHANGE_PROOF=PASS")
    print("FAIL_CLOSED_REVISION_TESTS=PASS")
