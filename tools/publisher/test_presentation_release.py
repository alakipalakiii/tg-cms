"""Manual presentation releases reuse public content, never its transaction identity."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publisher import artifact_contract as c, artifact_transport, workflow_stage_cli as cli
from publisher.transaction_journal import JournalInvalid, TransactionJournal, empty_journal, logical_transaction_id, validate_journal

SOURCE = 'a' * 40
MANUAL = {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'PUBLISHER_MODE': 'PUBLISH', 'MAHOON_PUBLISH_READY': 'YES'}

class PresentationReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'published.json'
        self.state.write_text(json.dumps({'published_content_revision': 341}))
        self.path = self.root / 'journal.json'
        self.path.write_text(json.dumps(empty_journal(cli.DEFAULT_WORKER)))
        self.journal = TransactionJournal.from_file(self.path, cli.DEFAULT_WORKER)

    def resolve(self, presentation=True, current=341):
        return cli.create_revision_resolution(self.state, source_sha=SOURCE, presentation_release=presentation,
            fetcher=lambda _url: ({'revision': current, 'changed_at': '2026-11-05 16:30:09'}, {}))

    def complete(self, tx):
        self.journal.record_build_ready(tx, 'b' * 64)
        for operation in ('upload_version', 'deploy_zero_percent', 'promote'):
            op, attempt = self.journal.record_intent(tx, operation)
            self.journal.record_result(tx, op, attempt, 'APPLIED', {'type':'synthetic', 'reference':'fixture', 'sha256':'c'*64})
        self.journal.record_proof_ready(tx, 'd' * 64)
        self.journal.mark_ready_to_persist(tx)
        self.journal.finalize_completed(tx, 'e' * 40)

    def test_scheduled_unchanged_still_skips_without_release_identity(self):
        value = self.resolve(False)
        self.assertEqual(value['payload']['decision'], 'UNCHANGED')
        self.assertNotIn('presentation_source_sha', value['transaction'])

    def test_release_requires_manual_publish_and_ready(self):
        for environment in ({}, {**MANUAL, 'GITHUB_EVENT_NAME':'schedule'}, {**MANUAL, 'MAHOON_PUBLISH_READY':'NO'}, {**MANUAL, 'PUBLISHER_MODE':'AUTO_TICK'}):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True), self.assertRaises(ValueError):
                self.resolve()

    @patch.dict(os.environ, MANUAL)
    def test_same_revision_has_distinct_source_bound_identity_and_full_completion(self):
        _, old = self.journal.admit(341, 'synthetic')
        self.complete(old)
        revision = self.resolve()
        self.assertEqual(revision['payload']['decision'], 'PRESENTATION_CHANGED')
        self.assertEqual(revision['payload']['revision'], revision['payload']['published_revision'])
        tx = revision['transaction']
        self.assertNotEqual(old, tx['logical_transaction_id'])
        self.assertEqual(tx['logical_transaction_id'], logical_transaction_id(cli.DEFAULT_WORKER, 341, SOURCE))
        path = self.root / 'revision.json'
        artifact_transport.write_artifact(path, revision)
        admission = cli.create_admission_receipt(path, self.path, 'workflow_dispatch', '2', '1')
        c.validate_artifact(admission, expected_transaction=tx)
        self.assertEqual(admission['payload']['decision'], 'ADMITTED')
        self.complete(tx['logical_transaction_id'])
        self.assertEqual(self.journal.admit(341, 'workflow_dispatch', presentation_source_sha=SOURCE)[0], 'COALESCED_COMPLETED')
        self.assertEqual(self.journal.admit(342, 'schedule')[0], 'ADMITTED')
        state = json.loads(self.path.read_text())
        self.assertEqual(len(state['history']), 2)
        validate_journal(state)

    @patch.dict(os.environ, MANUAL)
    def test_new_content_uses_existing_content_release_identity(self):
        value = self.resolve(current=342)
        self.assertEqual(value['payload']['decision'], 'CHANGED')
        self.assertNotIn('presentation_source_sha', value['transaction'])

    @patch.dict(os.environ, MANUAL)
    def test_wrong_source_and_missing_release_namespace_are_rejected(self):
        revision = self.resolve()
        for change in ('producer', 'namespace', 'decision', 'revision'):
            bad = copy.deepcopy(revision)
            if change == 'producer': bad['producer']['source_sha'] = 'b' * 40
            if change == 'namespace': bad['transaction'].pop('presentation_source_sha')
            if change == 'decision': bad['payload']['decision'] = 'CHANGED'
            if change == 'revision': bad['payload']['published_revision'] = 340
            with self.subTest(change=change), self.assertRaises(c.ArtifactContractError):
                c.validate_artifact(c.seal_artifact(bad))

    def test_release_cannot_replace_or_queue_behind_active_content(self):
        self.journal.admit(340, 'schedule')
        self.assertEqual(self.journal.admit(341, 'workflow_dispatch', presentation_source_sha=SOURCE)[0], 'STALE')
        self.assertIsNone(json.loads(self.path.read_text())['pending'])

    def test_build_authorization_accepts_only_matching_presentation_lineage(self):
        import test_build_runner_boundary as fixtures
        runner = fixtures._load_runner()
        revision, admission = fixtures._authorization_pair()
        source = revision["producer"]["source_sha"]
        tx = {**revision["transaction"], "presentation_source_sha": source}
        tx["logical_transaction_id"] = c.logical_transaction_id(tx["worker"], tx["content_revision"], source)
        revision["transaction"] = tx
        revision["payload"].update(decision="PRESENTATION_CHANGED", published_revision=tx["content_revision"])
        revision = c.seal_artifact(revision)
        admission["transaction"] = tx
        admission["payload"].update(revision_resolution_sha256=revision["artifact_sha256"], active_transaction_id=tx["logical_transaction_id"])
        admission = c.seal_artifact(admission)
        rp, ap = self.root / "build-revision.json", self.root / "admission.json"
        rp.write_text(json.dumps(revision)); ap.write_text(json.dumps(admission))
        with patch.dict(os.environ, {"MAHOON_REVISION_RESOLUTION_ARTIFACT": str(rp), "MAHOON_ADMISSION_RECEIPT_ARTIFACT": str(ap)}), patch.object(runner, "execution_source_identity", return_value=(source, source)):
            self.assertEqual(runner._build_authorization()[0]["transaction"], tx)
            admission["payload"]["decision"] = "DEFERRED"
            ap.write_text(json.dumps(c.seal_artifact(admission)))
            with self.assertRaises(runner.BuildBoundaryError): runner._build_authorization()

    def test_null_presentation_identity_cannot_be_smuggled_into_normal_journal(self):
        self.journal.admit(341, "schedule")
        state = json.loads(self.path.read_text())
        state["active"]["presentation_source_sha"] = None
        with self.assertRaises(JournalInvalid): validate_journal(state)

if __name__ == '__main__': unittest.main()

