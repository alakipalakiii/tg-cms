"""Credential-free CLI for local journal admission and evidence transitions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .transaction_journal import JournalError, TransactionJournal
except ImportError:  # Supports direct invocation from the repository root.
    from transaction_journal import JournalError, TransactionJournal


def _evidence(raw: str | None) -> dict | None:
    if raw is None:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("evidence must be a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--worker", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    admit = commands.add_parser("admit")
    admit.add_argument("--revision", required=True, type=int)
    admit.add_argument("--source", required=True)
    admit.add_argument("--run-id", default="")
    admit.add_argument("--attempt-id", default="")

    intent = commands.add_parser("record-intent")
    intent.add_argument("--transaction-id", required=True)
    intent.add_argument("--operation", required=True)

    for name in ("record-result", "reconcile"):
        command = commands.add_parser(name)
        command.add_argument("--transaction-id", required=True)
        command.add_argument("--operation-id", required=True)
        command.add_argument("--outcome", required=True,
                             choices=("APPLIED", "NOT_APPLIED", "UNKNOWN"))
        command.add_argument("--evidence-json")
        if name == "record-result":
            command.add_argument("--attempt-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        journal = TransactionJournal.from_file(args.journal, args.worker)
        if args.command == "admit":
            status, tx_id = journal.admit(args.revision, args.source, args.run_id, args.attempt_id)
            output = {"status": status, "transaction_id": tx_id}
            code = 2 if status == "RECOVERY_REQUIRED" else 0
        elif args.command == "record-intent":
            operation_id, attempt_id = journal.record_intent(args.transaction_id, args.operation)
            output = {"status": "RECORDED", "operation_id": operation_id,
                      "attempt_id": attempt_id}
            code = 0
        elif args.command == "record-result":
            journal.record_result(args.transaction_id, args.operation_id, args.attempt_id,
                                  args.outcome, _evidence(args.evidence_json))
            output, code = {"status": args.outcome}, 0
        else:
            journal.reconcile(args.transaction_id, args.operation_id, args.outcome,
                              _evidence(args.evidence_json))
            output = {"status": args.outcome,
                      "blocked": args.outcome == "UNKNOWN"}
            code = 2 if args.outcome == "UNKNOWN" else 0
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return code
    except (JournalError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
