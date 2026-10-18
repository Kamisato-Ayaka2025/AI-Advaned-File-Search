"""Regression requirements from C review B1-B5 and S1-S10; no real services."""
from dataclasses import replace
from hashlib import sha256
import unittest

from original_words.contracts import from_json, to_json
from original_words.contracts.answers import Answer, SearchOutcome
from original_words.contracts.catalog import ChatPage, MessagePage
from original_words.contracts.common import ServiceFailure, SnapshotRef, TaskEvent
from original_words.contracts.data import ImportIssue
from original_words.contracts.messages import TimeFilterInfo, filter_message_times
from original_words.contracts.search import MessageEdge
from original_words.contracts.services import TaskControl
from original_words.contracts.sending import evidence_digest
from original_words.contracts.validation import require_all_messages, validate_generated_answer
from samples import SOURCE, SNAPSHOT, message, samples, send_plan
from test_consumers import SyntheticAnswer, SyntheticConsent, SyntheticRepository


class CatalogReviewTests(unittest.TestCase):
    def test_b1_ui_lists_sources_chats_and_timeline_without_sql(self):
        repo = SyntheticRepository()
        sources = repo.list_sources(snapshot=SNAPSHOT, source_ids=(SOURCE,))
        chats = repo.list_chats(snapshot=SNAPSHOT, source_ids=(sources[0].source_id,))
        self.assertEqual(chats.chats[0].display_name, "合成群聊")
        page = repo.get_message_range(SOURCE, chats.chats[0].chat_id,
                                     snapshot=SNAPSHOT, source_ids=(SOURCE,))
        self.assertEqual(page.messages, (message(),))
        self.assertEqual(from_json(MessagePage, to_json(page)), page)

    def test_b1_pagination_scope_unknown_counts_and_colliding_chat_ids(self):
        chat = samples()["chat_summary"]
        self.assertIsNone(replace(chat, message_count=None).message_count)
        # A chat key is (source_id, chat_id), not chat_id alone.
        other = replace(chat, source_id="other",
                        coverage=replace(chat.coverage, source_ids=("other",)))
        self.assertEqual(len(ChatPage(SNAPSHOT, (chat, other)).chats), 2)
        with self.assertRaises(ValueError):
            ChatPage(SNAPSHOT, (chat, chat))
        with self.assertRaises(ValueError):
            ChatPage(SNAPSHOT, (), next_cursor="cursor")
        with self.assertRaises(ValueError):
            replace(samples()["message_page"], messages=(message(2, "other-chat"),))
        with self.assertRaises(ServiceFailure):
            SyntheticRepository().list_chats(snapshot=SNAPSHOT, source_ids=("other",))

    def test_b1_page_cap_and_bounded_contents(self):
        page = samples()["message_page"]
        with self.assertRaises(ValueError):
            replace(page, messages=tuple(message(i) for i in range(201)))
        with self.assertRaises(ValueError):
            replace(page, start="2026-02-01T00:00:00Z", time_filter=TimeFilterInfo(True, 0, 0))

    def test_s7_missing_messages_fail_loudly_without_ids(self):
        with self.assertRaises(ServiceFailure) as error:
            SyntheticRepository().get_messages(("private-id-sentinel",), snapshot=SNAPSHOT,
                                               source_ids=(SOURCE,))
        self.assertEqual(error.exception.error.code, "REVISION_MISMATCH")
        self.assertNotIn("private-id-sentinel", str(error.exception))
        with self.assertRaises(ServiceFailure):
            require_all_messages((message(2).message_id, message().message_id),
                                 (message(), message(2)))


class AnswerReviewTests(unittest.TestCase):
    def test_b2_request_id_is_required_and_survives_wire(self):
        with self.assertRaises(TypeError):
            Answer("not_found")
        with self.assertRaises(ValueError):
            Answer("not_found", request_id="")
        self.assertEqual(from_json(Answer, to_json(samples()["answer"])).request_id, "request-1")
        with self.assertRaises(ValueError):
            replace(samples()["outcome"], request_id="new-request")

    def test_b2_clarification_is_visible_and_only_for_ambiguous(self):
        answer = Answer("ambiguous", request_id="r", clarification="请指明会话")
        self.assertEqual(from_json(Answer, to_json(answer)).clarification, "请指明会话")
        for status, clarification in (("ambiguous", None), ("ambiguous", ""),
                                      ("not_found", "不应追问")):
            with self.assertRaises(ValueError):
                Answer(status, request_id="r", clarification=clarification)

    def test_b2_stale_generate_result_rejected_at_consumer_boundary(self):
        fixture = samples()
        with self.assertRaises(ServiceFailure):
            validate_generated_answer(fixture["answer"], "new-request", fixture["bundle"],
                                      (message(),), (SOURCE,))
        sender, consent, plan = SyntheticAnswer(), SyntheticConsent(), send_plan()
        grant = consent.grant(plan, user_confirmed=True)
        answer = sender.generate(plan, grant, consent=consent, evidence=fixture["bundle"])
        self.assertEqual(answer.request_id, plan.request_id)


class ImportReviewTests(unittest.TestCase):
    def test_b3_issue_sample_not_equal_to_rejection_count(self):
        report = replace(samples()["report"], read_count=101, rejected_count=100,
                         manifest=replace(samples()["manifest"], source_count=101),
                         completeness="partial", issues=(samples()["import_issue"],),
                         issues_truncated=True)
        self.assertEqual(report.rejected_count, 100)
        self.assertEqual(len(report.issues), 1)
        self.assertTrue(report.issues_truncated)

    def test_b3_issue_cap_and_redaction(self):
        issue = samples()["import_issue"]
        with self.assertRaises(ValueError):
            replace(samples()["report"], issues=(issue,) * 101)
        for changes in ({"detail": "RAW_MESSAGE_SENTINEL"}, {"record_ref": "C:/private/chat.json"},
                        {"field": "raw\nvalue"}):
            with self.assertRaises(ValueError) as error:
                replace(issue, **changes)
            self.assertNotIn("RAW_MESSAGE_SENTINEL", str(error.exception))
        self.assertEqual(ImportIssue("bad_time", "record:2", "timestamp",
                                     "时间无效或精度不明确").field, "timestamp")


class TimeReviewTests(unittest.TestCase):
    def test_b4_bounded_result_cannot_omit_filter_disclosure(self):
        from original_words.contracts.validation import validate_search_result
        fixture = samples()
        request = replace(fixture["request"], filters=replace(fixture["filters"],
                          start="2026-01-01T00:00:00Z"))
        spec = replace(fixture["spec"], request=request)
        with self.assertRaises(ValueError):
            validate_search_result(spec, fixture["result"])
        validate_search_result(spec, replace(fixture["result"], time_filter=TimeFilterInfo(True)))


    def test_b4_date_and_unknown_exclusions_are_counted(self):
        rows = (message(),
                replace(message(2), timestamp="2026-01-01", timestamp_precision="day"),
                replace(message(3), timestamp=None, timestamp_status="unknown",
                        timestamp_precision="unknown"))
        selected, info = filter_message_times(rows, "2026-01-01T00:00:00Z",
                                             "2026-01-02T00:00:00Z")
        self.assertEqual(selected, (message(),))
        self.assertTrue(info.applied)
        self.assertEqual(info.date_only_policy, "exclude_imprecise_v1")
        self.assertEqual((info.excluded_date_only_count, info.excluded_unknown_time_count), (1, 1))
        result = replace(samples()["result"], time_filter=info)
        self.assertEqual(from_json(type(result), to_json(result)).time_filter, info)
        selected, info = filter_message_times(rows, None, None)
        self.assertEqual(selected, rows)
        self.assertEqual((info.applied, info.excluded_date_only_count), (False, 0))

    def test_b4_unknown_count_never_becomes_zero(self):
        info = TimeFilterInfo(applied=True)
        self.assertIsNone(from_json(TimeFilterInfo, to_json(info)).excluded_date_only_count)
        with self.assertRaises(ValueError):
            TimeFilterInfo(False, 0, 1)
        with self.assertRaises(ValueError):
            TimeFilterInfo(True, -1, 0)

    def test_b4_half_open_exact_times_and_empty_range(self):
        rows = (message(), replace(message(2), timestamp="2026-01-02T00:00:00Z"))
        selected, _ = filter_message_times(rows, rows[0].timestamp, rows[1].timestamp)
        self.assertEqual(selected, (rows[0],))
        selected, _ = filter_message_times(rows, rows[0].timestamp, rows[0].timestamp)
        self.assertEqual(selected, ())


class ConsentReviewTests(unittest.TestCase):
    def test_b5_snapshot_change_rejected_before_send_and_grant_consumption(self):
        plan = send_plan()
        for snapshot in (SnapshotRef("data-2", "index-1"), SnapshotRef("data-1", "index-2")):
            sender, consent = SyntheticAnswer(), SyntheticConsent()
            grant = consent.grant(plan, user_confirmed=True)
            changed = replace(samples()["bundle"], snapshot=snapshot)
            with self.assertRaises(ServiceFailure) as error:
                sender.generate(plan, grant, consent=consent, evidence=changed)
            self.assertEqual(error.exception.error.code, "REVISION_MISMATCH")
            self.assertEqual(sender.sent_payloads, [])
            self.assertTrue(consent.validate(grant, plan))

    def test_b5_same_snapshot_changed_spans_or_membership_needs_new_preview(self):
        bundle, plan = samples()["bundle"], send_plan()
        changes = (replace(bundle, char_spans=(replace(bundle.char_spans[0], end=2),)),
                   replace(bundle, message_ids=bundle.message_ids + (message(2).message_id,)))
        for changed in changes:
            sender, consent = SyntheticAnswer(), SyntheticConsent()
            grant = consent.grant(plan, user_confirmed=True)
            with self.assertRaises(ServiceFailure) as error:
                sender.generate(plan, grant, consent=consent, evidence=changed)
            self.assertEqual(error.exception.error.code, "CONSENT_REQUIRED")
            self.assertEqual(sender.sent_payloads, [])
            self.assertTrue(consent.validate(grant, plan))

    def test_b5_new_evidence_binding_invalidates_old_grant(self):
        plan, bundle = send_plan(), samples()["bundle"]
        changed = replace(bundle, char_spans=(replace(bundle.char_spans[0], end=2),))
        rebound = replace(plan, evidence_digest=evidence_digest(changed))
        self.assertNotEqual(plan.fingerprint, rebound.fingerprint)
        consent = SyntheticConsent()
        grant = consent.grant(plan, user_confirmed=True)
        with self.assertRaises(ServiceFailure):
            consent.consume(grant, rebound, evidence=changed)
        self.assertTrue(consent.validate(grant, plan))

    def test_s5_modes_cannot_silently_widen_or_have_empty_evidence(self):
        plan, bundle = send_plan(), samples()["bundle"]
        with self.assertRaises(ValueError):
            replace(plan, selected_message_ids=())
        for selected in ((), ("not-in-bundle",)):
            with self.assertRaises(ServiceFailure):
                replace(plan, mode="full", selected_message_ids=selected).validate_evidence(bundle)
        replace(plan, mode="full").validate_evidence(bundle)

    def test_query_parse_can_authorize_query_without_chat_evidence(self):
        from original_words.contracts.search import EvidenceBundle
        bundle = EvidenceBundle(SNAPSHOT)
        plan = replace(send_plan(), purpose="query_parse", selected_message_ids=(),
                       evidence_digest=evidence_digest(bundle))
        plan.validate_evidence(bundle)
        with self.assertRaises(ServiceFailure):
            replace(send_plan(), purpose="query_parse").validate_evidence(samples()["bundle"])


class AdvisoryReviewTests(unittest.TestCase):
    def test_s1_task_sequence_and_cancel_protocol(self):
        event = TaskEvent("t", "r", "running", seq=2)
        with self.assertRaises(ValueError):
            replace(event, seq=-1)
        latest = max((event, replace(event, seq=1)), key=lambda e: e.seq)
        self.assertEqual(latest.seq, 2)
        class Control:
            def cancel(self, task_id):
                self.cancelled = task_id
        control = Control()
        self.assertIsInstance(control, TaskControl)
        control.cancel("t")
        self.assertEqual(control.cancelled, "t")

    def test_s4_export_digest_is_optional_but_validated(self):
        receipt = samples()["export"]
        digest = sha256(b"synthetic").hexdigest()
        self.assertEqual(replace(receipt, sha256=digest).sha256, digest)
        with self.assertRaises(ValueError):
            replace(receipt, sha256="bad")

    def test_s8_external_resolved_target_does_not_become_unresolved(self):
        bundle = samples()["bundle"]
        edge = MessageEdge(message().message_id, message(2).message_id, "quote",
                           "synthetic", "data-1", external_target=True)
        updated = replace(bundle, edge_provenance=(edge,))
        self.assertFalse(updated.edge_provenance[0].unresolved)
        self.assertNotIn(edge.to_id, updated.message_ids)
        with self.assertRaises(ValueError):
            replace(bundle, edge_provenance=(replace(edge, external_target=False),))


if __name__ == "__main__":
    unittest.main()
