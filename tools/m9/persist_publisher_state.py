"""Install publisher state only from a matching successful production result."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from publisher.resumable_transaction import verify_production_result, verify_proof_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    args = parser.parse_args()
    transaction, bundle_sha = verify_proof_bundle(args.bundle_dir)
    result = json.loads((args.result_dir / "production-result.json").read_text(encoding="utf-8"))
    verify_production_result(result, transaction, bundle_sha)
    state = ROOT / "publisher-state" / "published-static-state.json"
    current = json.loads(state.read_text(encoding="utf-8"))
    if current.get("current_version_type") != "STATIC" or current.get("current_version") != transaction.get("baseline_static_version"):
        raise RuntimeError("published static state drifted before persistence")

    source = args.result_dir / "published-state"
    mapping = (
        ("production-content-fingerprint.json", "production-content-fingerprint.json"),
        ("production-media-manifest.json", "production-media-manifest.json"),
        ("immutable-media-index.json", "immutable-media-index.json"),
        ("published-route-manifest.json", "published-route-manifest.json"),
        ("published-route-manifest.json", "current-accepted-route-manifest.json"),
        ("published-static-state.json", "published-static-state.json"),
    )
    for from_name, to_name in mapping:
        src = source / from_name
        if not src.is_file():
            raise RuntimeError(f"production result is missing {from_name}")
        shutil.copyfile(src, ROOT / "publisher-state" / to_name)
    print(json.dumps({
        "STATE_PERSIST_WITHOUT_PRODUCTION_PASS": "IMPOSSIBLE",
        "production_result_pass": result.get("PASS") is True,
        "transaction_id": transaction["transaction_id"],
        "published_content_revision": transaction["source_revision"],
        "state_files_installed": len(mapping),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
