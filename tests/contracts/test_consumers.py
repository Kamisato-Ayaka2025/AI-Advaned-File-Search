"""A-side executable consumers only; not B/C independent sign-off or G5 proof."""
from dataclasses import replace
import unittest

from original_words.contracts import from_json, to_json
from original_words.contracts.answers import Answer
from original_words.contracts.common import ErrorInfo, ServiceFailure
from original_words.contracts.search import SearchSpec, SearchResult
from original_words.contracts.services import (
    AnswerService, ChatSourceConnector, ConsentService, DataLifecycle, ExportAdapter,
    IndexStore, Repository, SearchService, SecretStore,
)
from original_words.contracts.sending import ConsentGrant
from original_words.contracts.validation import validate_answer, validate_chunk, validate_evidence
from samples import SOURCE, SNAPSHOT, message, samples, send_plan


class SyntheticRepository:
    def import_batch(self, batch):
        return samples()["import_result"]

    def get_messages(self, message_ids, *, snapshot, source_ids):
        if snapshot != SNAPSHOT or source_ids != (SOURCE,):
            raise ServiceFailure(ErrorInfo("PERMISSION_DENIED", "合成范围不匹配"))
        return tuple(m for m in (message(),) if m.message_id in message_ids)

    def get_context(self, message_id, *, snapshot, source_ids, before=10, after=10):
        self.get_messages((message_id,), snapshot=snapshot, source_ids=source_ids)
        return samples()["context"]

    def get_chunks(self, chunk_ids, *, snapshot, source_ids):
        self.get_messages((), snapshot=snapshot, source_ids=source_ids)
        return (samples()["chunk"],) if "chunk-1" in chunk_ids else ()


class SyntheticSearch:
    def parse_local(self, request, *, snapshot, authorized_source_ids):
        return SearchSpec(request, snapshot, authorized_source_ids)

    def search(self, spec):
        # Exercise wire transfer between hypothetical B and C consumers.
        result = samples()["result"] if spec.request.query == "合成问题" else samples()["empty_result"]
        return from_json(SearchResult, to_json(result))


class SyntheticConsent:
    """Deliberately single-thread test double. Does not demonstrate atomic security."""

    def __init__(self):
        self.active = None

    def grant(self, plan, *, user_confirmed):
        if not user_confirmed:
            raise ServiceFailure(ErrorInfo("CONSENT_REQUIRED", "需明确同意"))
        self.active = ConsentGrant("synthetic-token", plan.fingerprint, "2026-12-01T00:00:00Z")
        return self.active

    def revoke(self, grant_id):
        self.active = None

    def validate(self, grant, plan):
        return self.active == grant and grant.plan_fingerprint == plan.fingerprint

    def consume(self, grant, plan):
        if not self.validate(grant, plan):
            raise ServiceFailure(ErrorInfo("CONSENT_REQUIRED", "授权失效"))
        self.active = None


class SyntheticAnswer:
    def __init__(self):
        self.sent_payloads = []

    def prepare_send(self, spec, evidence, *, purpose, mode, model, endpoint):
        return send_plan()

    def generate(self, plan, grant, *, consent, evidence):
        consent.consume(grant, plan)
        self.sent_payloads.append(plan.preview_text.encode("utf-8"))
        return from_json(Answer, to_json(samples()["answer"]))


class SyntheticConnector:
    def detect(self):
        return (samples()["source"],)

    def authorize(self, source_id, *, user_confirmed):
        if not user_confirmed:
            raise ServiceFailure(ErrorInfo("PERMISSION_DENIED", "未授权"))
        return samples()["authorization"]

    def read(self, authorization):
        return iter((samples()["batch"],))

    def sync(self, authorization, cursor):
        raise ServiceFailure(ErrorInfo("UNSUPPORTED_OPERATION", "Tier A 不支持同步"))


class SyntheticAdapter:
    def probe(self, path):
        return samples()["probe"]

    def read(self, path, manifest):
        return iter((samples()["batch"],))

    def validate(self, path, manifest):
        return samples()["report"]


class SyntheticIndex:
    def publish(self, update):
        return update.snapshot

    def get_active_revision(self):
        return SNAPSHOT


class SyntheticSecrets:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


class SyntheticLifecycle:
    def export(self, answer, *, snapshot, destination, format):
        return samples()["export"]

    def delete(self, *, task_id, user_confirmed):
        if not user_confirmed:
            raise ServiceFailure(ErrorInfo("PERMISSION_DENIED", "未确认删除"))
        return samples()["cleanup"]


class ConsumerTests(unittest.TestCase):
    def test_all_nine_protocols_have_consumable_examples(self):
        pairs = ((SyntheticRepository(), Repository), (SyntheticSearch(), SearchService),
                 (SyntheticAnswer(), AnswerService), (SyntheticConsent(), ConsentService),
                 (SyntheticConnector(), ChatSourceConnector), (SyntheticAdapter(), ExportAdapter),
                 (SyntheticIndex(), IndexStore), (SyntheticSecrets(), SecretStore),
                 (SyntheticLifecycle(), DataLifecycle))
        for implementation, protocol in pairs:
            with self.subTest(protocol=protocol.__name__):
                self.assertIsInstance(implementation, protocol)
                self.assertNotIsInstance(object(), protocol)

    def test_repository_search_to_citation_consumer(self):
        repository: Repository = SyntheticRepository()
        search: SearchService = SyntheticSearch()
        fixture = samples()
        spec = search.parse_local(fixture["request"], snapshot=SNAPSHOT,
                                  authorized_source_ids=(SOURCE,))
        result = search.search(spec)
        messages = repository.get_messages(result.hits[0].message_ids,
                                           snapshot=result.snapshot, source_ids=(SOURCE,))
        validate_evidence(fixture["bundle"], messages, (SOURCE,))
        validate_answer(fixture["answer"], fixture["bundle"], messages, (SOURCE,))
        validate_chunk(fixture["chunk"], messages)
        citation = fixture["answer"].citations[0]
        self.assertEqual(messages[0].content[citation.char_span.start:citation.char_span.end], "这是合")

    def test_empty_and_error_consumption(self):
        search: SearchService = SyntheticSearch()
        spec = search.parse_local(replace(samples()["request"], query="没有证据"),
                                  snapshot=SNAPSHOT, authorized_source_ids=(SOURCE,))
        self.assertEqual(search.search(spec).hits, ())
        connector: ChatSourceConnector = SyntheticConnector()
        with self.assertRaises(ServiceFailure) as failure:
            connector.sync(samples()["authorization"], None)
        self.assertEqual(failure.exception.error.code, "UNSUPPORTED_OPERATION")
        self.assertFalse(failure.exception.error.retryable)

    def test_prepare_never_sends_then_one_shot_grant(self):
        answer: AnswerService = SyntheticAnswer()
        consent: ConsentService = SyntheticConsent()
        fixture = samples()
        plan = answer.prepare_send(fixture["spec"], fixture["bundle"], purpose="answer",
                                   mode="partial", model="synthetic-model",
                                   endpoint="https://api.deepseek.com/chat/completions")
        self.assertEqual(answer.sent_payloads, [])
        with self.assertRaises(ServiceFailure):
            consent.grant(plan, user_confirmed=False)
        grant = consent.grant(plan, user_confirmed=True)
        answer.generate(plan, grant, consent=consent, evidence=fixture["bundle"])
        with self.assertRaises(ServiceFailure):
            answer.generate(plan, grant, consent=consent, evidence=fixture["bundle"])
        self.assertEqual(answer.sent_payloads, [plan.preview_text.encode("utf-8")])

    def test_revoked_and_edited_plans_do_not_reach_send_sink(self):
        for revoke in (False, True):
            answer = SyntheticAnswer()
            consent = SyntheticConsent()
            plan = send_plan()
            grant = consent.grant(plan, user_confirmed=True)
            if revoke:
                consent.revoke(grant.grant_id)
            else:
                plan = replace(plan, purpose="investigation")
            with self.assertRaises(ServiceFailure):
                answer.generate(plan, grant, consent=consent, evidence=samples()["bundle"])
            self.assertEqual(answer.sent_payloads, [])

    def test_import_index_secret_and_cleanup_consumption(self):
        fixture = samples()
        connector: ChatSourceConnector = SyntheticConnector()
        adapter: ExportAdapter = SyntheticAdapter()
        repository: Repository = SyntheticRepository()
        authorization = connector.authorize(connector.detect()[0].source_id, user_confirmed=True)
        probe = adapter.probe("synthetic.json")
        self.assertTrue(probe.supported)
        for batch in adapter.read("synthetic.json", probe.manifest):
            self.assertEqual(repository.import_batch(batch).report.imported_count, 1)
        self.assertEqual(len(tuple(connector.read(authorization))), 1)
        self.assertEqual(adapter.validate("synthetic.json", probe.manifest), fixture["report"])
        index: IndexStore = SyntheticIndex()
        self.assertEqual(index.publish(fixture["index_update"]), index.get_active_revision())
        secrets: SecretStore = SyntheticSecrets()
        secrets.set("synthetic", b"fake")
        self.assertEqual(secrets.get("synthetic"), b"fake")
        secrets.delete("synthetic")
        self.assertIsNone(secrets.get("synthetic"))
        lifecycle: DataLifecycle = SyntheticLifecycle()
        self.assertTrue(lifecycle.delete(task_id="delete-1", user_confirmed=True).succeeded)
        self.assertEqual(lifecycle.export(fixture["answer"], snapshot=SNAPSHOT,
                                         destination="synthetic.json", format="json").bytes_written, 12)

    def test_original_text_bounds_and_scope_are_checked(self):
        fixture = samples()
        bad_span = replace(fixture["span"], end=1000)
        for operation in (
            lambda: validate_chunk(replace(fixture["chunk"], char_spans=(bad_span,)), (message(),)),
            lambda: validate_evidence(replace(fixture["bundle"], char_spans=(bad_span,)),
                                      (message(),), (SOURCE,)),
            lambda: validate_answer(fixture["answer"], fixture["bundle"], (message(),), ("other",)),
            lambda: validate_answer(replace(fixture["answer"], citations=(
                replace(fixture["citation"], char_span=None),)),
                fixture["bundle"], (message(),), (SOURCE,)),
        ):
            with self.assertRaises(ValueError):
                operation()


if __name__ == "__main__":
    unittest.main()
