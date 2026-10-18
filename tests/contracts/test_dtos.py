"""Semantic invariants trace to Plan 4, 6 and ADR-001; all data is synthetic."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import unittest

from original_words.contracts import from_json, to_json
from original_words.contracts.common import ErrorInfo, ServiceFailure, SnapshotRef, TaskEvent
from original_words.contracts.data import CharSpan, ImportReport
from original_words.contracts.search import (
    EvidenceBundle, InvestigationDecision, MessageEdge, SearchBudget, SearchFilters,
    SearchRequest, SearchResult, SearchSpec,
)
from original_words.contracts.answers import Answer, Claim, SearchOutcome, SearchUsage
from original_words.contracts.services import CleanupItem, CleanupReport, IndexRecord
from samples import SNAPSHOT, SOURCE, message, samples, send_plan


class WireTests(unittest.TestCase):
    def test_every_sample_roundtrips_and_is_immutable(self):
        for name, obj in samples().items():
            with self.subTest(name=name):
                self.assertEqual(from_json(type(obj), to_json(obj)), obj)
                with self.assertRaises((AttributeError, TypeError)):
                    obj.unexpected = "mutation"

    def test_persisted_wire_examples_match_current_contract(self):
        path = Path(__file__).parents[1] / "fixtures/contracts/v0_2.json"
        wire = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(wire["contract_version"], "0.2.0-draft")
        self.assertEqual(set(wire["examples"]), set(samples()))
        for name, obj in samples().items():
            entry = wire["examples"][name]
            self.assertEqual(entry["type"], type(obj).__name__)
            self.assertEqual(from_json(type(obj), json.dumps(entry["value"])), obj)

    def test_unknown_missing_and_duplicate_fields_rejected(self):
        for payload in ('{"request_id":"r","query":"q","extra":1}',
                        '{"request_id":"r"}',
                        '{"request_id":"r","query":"q","query":"other"}'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                from_json(SearchRequest, payload)

    def test_nested_fields_are_strict(self):
        for filters in ({"start": 42}, {"message_types": ["alien"]}, {"source_ids": "a"}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                from_json(SearchRequest, json.dumps(dict(request_id="r", query="q", filters=filters)))

    def test_bool_is_not_int_and_mutable_lists_rejected(self):
        for kwargs in ({"top_k": True}, {"top_k": 0}, {"top_k": 201}):
            with self.assertRaises(ValueError):
                SearchRequest("r", "q", **kwargs)
        with self.assertRaises(ValueError):
            SearchFilters(source_ids=["a"])

    def test_size_depth_and_nonfinite_limits(self):
        with self.assertRaises(ValueError):
            from_json(SearchRequest, " " * 1_048_577)
        for number in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                replace(samples()["hit"], score=number)

    def test_dto_repr_does_not_leak_query_or_preview(self):
        for name in ("request", "send_plan", "claim"):
            obj = samples()[name]
            self.assertNotIn("合成", repr(obj))

    def test_service_failure_does_not_echo_user_message(self):
        error = ErrorInfo("INVALID_INPUT", "SYNTHETIC_SENTINEL")
        self.assertEqual(str(ServiceFailure(error)), "INVALID_INPUT")


class DataTests(unittest.TestCase):
    def test_import_reconciliation_and_subset(self):
        report = samples()["report"]
        for changes in ({"read_count": 2}, {"unknown_count": 2},
                        {"duplicate_count": -1}, {"rejected_count": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(report, **changes)

    def test_unknown_source_count_cannot_be_verified_or_partial(self):
        manifest = replace(samples()["manifest"], source_count=None)
        report = ImportReport(manifest, None, None, None, None, None, None)
        self.assertIsNone(from_json(ImportReport, to_json(report)).read_count)
        for status in ("partial", "verified_for_scope"):
            with self.assertRaises(ValueError):
                replace(report, completeness=status)

    def test_verified_scope_needs_all_counts_and_no_rejections(self):
        report = samples()["report"]
        for changes in ({"attachment_missing_count": None}, {"read_count": 0, "imported_count": 0},
                        {"imported_count": 0, "rejected_count": 1}):
            with self.assertRaises(ValueError):
                replace(report, **changes)

    def test_batch_rejects_duplicate_and_wrong_source(self):
        batch = samples()["batch"]
        for messages in ((message(), message()), (replace(message(), source_id="other"),)):
            with self.assertRaises(ValueError):
                replace(batch, messages=messages)

    def test_chunk_spans_and_membership(self):
        with self.assertRaises(ValueError):
            CharSpan("m", 3, 3)
        with self.assertRaises(ValueError):
            replace(samples()["chunk"], char_spans=(CharSpan("absent", 0, 1),))
        with self.assertRaises(ValueError):
            replace(samples()["chunk"], message_ids=())

    def test_context_cannot_cross_chat_or_source(self):
        valid = samples()["context"]
        for msg in (message(2, "another-chat"), replace(message(2), source_id="other")):
            with self.assertRaises(ValueError):
                replace(valid, messages=(message(), msg))
        with self.assertRaises(ValueError):
            replace(valid, anchor_id="missing")

    def test_progress_is_truthful(self):
        for kwargs in (dict(state="running", completed=2, total=1),
                       dict(state="succeeded", completed=0, total=1),
                       dict(state="failed"),
                       dict(state="running", error=ErrorInfo("CANCELLED", "cancel"))):
            with self.assertRaises(ValueError):
                TaskEvent("task", "r", **kwargs)
        self.assertIsNone(TaskEvent("task", None, "running", 2).total)

    def test_cleanup_reports_every_resource_and_failure(self):
        cleanup = samples()["cleanup"]
        self.assertTrue(cleanup.succeeded)
        with self.assertRaises(ValueError):
            replace(cleanup, items=cleanup.items[:-1])
        failed = CleanupItem("database", "failed", ErrorInfo("PERMISSION_DENIED", "无法清理"))
        self.assertFalse(CleanupReport("task", (failed,) + cleanup.items[1:]).succeeded)

    def test_index_dimensions_and_delete_conflicts(self):
        update = samples()["index_update"]
        for changes in (
            {"records": (IndexRecord("a", "", (0.1,)), IndexRecord("b", "", (0.1, 0.2)))},
            {"deleted_chunk_ids": ("chunk-1",)},
        ):
            with self.assertRaises(ValueError):
                replace(update, **changes)


class SearchTests(unittest.TestCase):
    def test_empty_search_is_first_class(self):
        result = samples()["empty_result"]
        self.assertEqual(from_json(SearchResult, to_json(result)).hits, ())
        self.assertEqual(samples()["empty_answer"].status, "not_found")

    def test_scope_cannot_widen_and_hints_are_separate(self):
        request = SearchRequest("r", "q", SearchFilters(source_ids=("other",)))
        with self.assertRaises(ValueError):
            SearchSpec(request, SNAPSHOT, (SOURCE,))
        spec = replace(samples()["spec"], soft_hints=("可能三月",))
        self.assertIsNone(spec.hard_filters.start)

    def test_search_and_edge_revisions_match_snapshot(self):
        with self.assertRaises(ValueError):
            replace(samples()["result"], snapshot=SnapshotRef("data-1", "other-index"))
        edge = MessageEdge(message().message_id, None, "quote", "synthetic", "data-2", True)
        with self.assertRaises(ValueError):
            replace(samples()["bundle"], edge_provenance=(edge,))

    def test_evidence_references_are_closed(self):
        with self.assertRaises(ValueError):
            replace(samples()["bundle"], message_ids=())
        with self.assertRaises(ValueError):
            MessageEdge("m", "target", "quote", "synthetic", "data-1", True)

    def test_decision_cannot_invent_ids_or_tools(self):
        bundle = samples()["bundle"]
        decision = InvestigationDecision("search", queries=("合成补查",),
                                         expand_message_ids=(message().message_id,))
        decision.validate_against(bundle, SearchBudget())
        with self.assertRaises(ValueError):
            replace(decision, expand_message_ids=("invented",)).validate_against(bundle, SearchBudget())
        with self.assertRaises(ValueError):
            from_json(InvestigationDecision, '{"action":"shell","queries":["whoami"]}')
        with self.assertRaises(ValueError):
            InvestigationDecision("finalize", queries=("q",))

    def test_budget_caps_and_batch_limits(self):
        for changes in ({"max_rounds": 3}, {"remote_calls": 4}, {"queries_per_round": 4},
                        {"cumulative_input_tokens": 24001}, {"machine_seconds": 31},
                        {"machine_seconds": float("nan")}, {"seeds": 12, "fused_candidates": 10}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                SearchBudget(**changes)
        with self.assertRaises(ValueError):
            InvestigationDecision("search", queries=("a", "b", "c", "d"))
        with self.assertRaises(ValueError):
            InvestigationDecision("search", queries=("a", "b")).validate_against(
                samples()["bundle"], SearchBudget(queries_per_round=1))

    def test_claims_and_timeline_cannot_have_dangling_citations(self):
        answer = samples()["answer"]
        with self.assertRaises(ValueError):
            replace(answer, claims=(Claim("unsupported", ("absent",)),))
        with self.assertRaises(ValueError):
            replace(answer, timeline=(replace(answer.timeline[0], message_id="other"),))
        with self.assertRaises(ValueError):
            Claim("unsupported", ())
        with self.assertRaises(ValueError):
            replace(answer, status="not_found")

    def test_citations_cannot_cross_snapshots_or_evidence(self):
        outcome = samples()["outcome"]
        for citation in (replace(outcome.answer.citations[0], snapshot=SnapshotRef("x", "y")),
                         replace(outcome.answer.citations[0], message_id="other", char_span=None)):
            answer = replace(outcome.answer, citations=(citation,), timeline=())
            with self.assertRaises(ValueError):
                replace(outcome, answer=answer)

    def test_incomplete_cannot_claim_full_answer(self):
        outcome = samples()["outcome"]
        for changes in ({"evidence": replace(outcome.evidence, truncated=True)},
                        {"evidence": replace(outcome.evidence, missing_stages=("solution",))},
                        {"stop_reason": "deadline", "budget_exhausted": True},
                        {"stop_reason": "cancelled"}):
            with self.assertRaises(ValueError):
                replace(outcome, **changes)
        partial = replace(outcome, answer=replace(outcome.answer, status="partial"),
                          stop_reason="deadline", budget_exhausted=True)
        self.assertEqual(partial.status, "partial")

    def test_usage_is_checked_without_hiding_overrun(self):
        outcome = samples()["outcome"]
        overrun = replace(outcome, usage=SearchUsage(remote_calls=4))
        with self.assertRaises(ValueError):
            overrun.validate_budget(SearchBudget())
        with self.assertRaises(ValueError):
            SearchUsage(machine_seconds=2, elapsed_seconds=1)


class SendingTests(unittest.TestCase):
    def test_exact_preview_digest(self):
        plan = send_plan()
        with self.assertRaises(ValueError):
            replace(plan, preview_text=plan.preview_text + " ")
        changed = plan.preview_text + " "
        updated = replace(plan, preview_text=changed,
                          payload_hash=sha256(changed.encode()).hexdigest())
        self.assertNotEqual(plan.fingerprint, updated.fingerprint)

    def test_metadata_changes_invalidate_grant_fingerprint(self):
        plan = send_plan()
        for changes in ({"purpose": "investigation"}, {"request_id": "new"},
                        {"mode": "full"}, {"selected_message_ids": ()},
                        {"consent_scope": ("other",)},
                        {"endpoint": "https://api.deepseek.com/v1/chat/completions"}):
            self.assertNotEqual(plan.fingerprint, replace(plan, **changes).fingerprint)

    def test_reject_wrong_model_and_non_deepseek_endpoint(self):
        plan = send_plan()
        for endpoint in ("http://api.deepseek.com/chat/completions",
                         "https://api.deepseek.com.evil.example/chat/completions",
                         "https://user@api.deepseek.com/chat/completions",
                         "https://api.deepseek.com:444/chat/completions",
                         "https://api.deepseek.com/chat/completions?redirect=elsewhere"):
            with self.assertRaises(ValueError):
                replace(plan, endpoint=endpoint)
        with self.assertRaises(ValueError):
            replace(plan, model="different")
        with self.assertRaises(ValueError):
            replace(plan, consent_scope=())



class BoundaryRegressionTests(unittest.TestCase):
    def test_time_precision_does_not_silently_discard_fractions(self):
        for precision, timestamp in (("second", "2026-01-01T00:00:00.001Z"),
                                     ("millisecond", "2026-01-01T00:00:00.000001Z")):
            with self.assertRaises(ValueError):
                replace(message(), timestamp_precision=precision, timestamp=timestamp)
        self.assertEqual(replace(message(), timestamp_precision="millisecond",
                                 timestamp="2026-01-01T00:00:00.001Z").timestamp_precision,
                         "millisecond")

    def test_preview_rejects_duplicate_json_keys_and_nonfinite_values(self):
        plan = send_plan()
        for body in ('{"model":"other","model":"synthetic-model","messages":[{}]}',
                     '{"model":"synthetic-model","messages":[{}],"temperature":NaN}',
                     '{"model":"synthetic-model"}'):
            with self.assertRaises(ValueError):
                replace(plan, preview_text=body, payload_hash=sha256(body.encode()).hexdigest())

    def test_extreme_float_input_is_sanitized(self):
        with self.assertRaises(ValueError):
            replace(samples()["hit"], score=10 ** 400)

    def test_malformed_deep_and_surrogate_json_are_sanitized(self):
        for payload in ('[' * 2000 + ']' * 2000, '"' + chr(0xD800) + '"',
                        '{"request_id":"r","query":"q","top_k":NaN}'):
            with self.assertRaises(ValueError):
                from_json(SearchRequest, payload)

    def test_deadline_cannot_disguise_incomplete_search_as_not_found(self):
        with self.assertRaises(ValueError):
            SearchOutcome("r", Answer("not_found"), EvidenceBundle(SNAPSHOT),
                          "deadline", budget_exhausted=True)
        with self.assertRaises(ValueError):
            replace(samples()["outcome"], stop_reason="no_evidence")

    def test_citation_cannot_span_a_gap_in_selected_text(self):
        from original_words.contracts.validation import validate_answer
        fixture = samples()
        bundle = replace(fixture["bundle"], char_spans=(
            CharSpan(message().message_id, 0, 1), CharSpan(message().message_id, 2, 3)))
        with self.assertRaises(ValueError):
            validate_answer(fixture["answer"], bundle, (message(),), (SOURCE,))
        contiguous = replace(bundle, char_spans=(
            CharSpan(message().message_id, 0, 1), CharSpan(message().message_id, 1, 3)))
        validate_answer(fixture["answer"], contiguous, (message(),), (SOURCE,))


if __name__ == "__main__":
    unittest.main()
