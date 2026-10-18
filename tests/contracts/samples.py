"""Deterministic synthetic wire examples; not retrieval-quality evidence."""
from hashlib import sha256

from original_words.contracts.common import ErrorInfo, SnapshotRef, TaskEvent
from original_words.contracts.data import (
    CharSpan, Chunk, Coverage, ImportBatch, ImportManifest, ImportReport, ImportResult,
)
from original_words.contracts.messages import Message, stable_message_id
from original_words.contracts.search import (
    Candidate, EvidenceBundle, InvestigationDecision, MessageEdge, SearchBudget,
    SearchFilters, SearchHit, SearchRequest, SearchResult, SearchSpec, StageCandidate,
)
from original_words.contracts.answers import (
    Answer, Citation, Claim, SearchOutcome, SearchUsage, TimelineEntry,
)
from original_words.contracts.sending import ConsentGrant, SendPlan
from original_words.contracts.services import (
    CleanupItem, CleanupReport, ContextResult, ExportReceipt, IndexRecord, IndexUpdate,
    ProbeResult, SourceAuthorization, SourceDescriptor,
)

SOURCE = "synthetic:account-a"
SNAPSHOT = SnapshotRef("data-1", "index-1")


def message(seq=1, chat="synthetic-chat"):
    return Message(
        message_id=stable_message_id(SOURCE, chat, original_id=str(seq)),
        source_id=SOURCE, chat_id=chat, chat_type="group", sender_id="synthetic-person",
        sender_name="合成角色", timestamp="2026-01-01T00:00:00Z",
        message_type="text", content="这是合成证据", seq=seq, timestamp_status="known",
        timestamp_precision="second", timestamp_source="fixture", source_timezone="UTC",
    )


def send_plan():
    body = '{"model":"synthetic-model","messages":[{"role":"user","content":"合成问题"}]}'
    return SendPlan("request-1", "answer", "partial", sha256(body.encode()).hexdigest(),
                    (message().message_id,), body, "synthetic-model",
                    "https://api.deepseek.com/chat/completions", (SOURCE,))


def samples():
    msg = message()
    span = CharSpan(msg.message_id, 0, 3)
    coverage = Coverage((SOURCE,), completeness="partial")
    manifest = ImportManifest("synthetic-json", "1", "synthetic-v1", (SOURCE,),
                              "synthetic-snapshot-digest", source_count=1)
    report = ImportReport(manifest, 1, 1, 0, 0, 0, 0, "verified_for_scope")
    chunk = Chunk("chunk-1", SOURCE, msg.chat_id, (msg.message_id,), msg.timestamp,
                  msg.timestamp, (msg.sender_id,), msg.content, "data-1",
                  char_spans=(span,))
    request = SearchRequest("request-1", "合成问题", SearchFilters(source_ids=(SOURCE,)))
    hit = SearchHit(chunk.chunk_id, chunk.message_ids, 0.5, ("synthetic",), "index-1")
    bundle = EvidenceBundle(SNAPSHOT, chunk.message_ids, (span,),
                            (StageCandidate("problem", chunk.message_ids),),
                            coverage=coverage)
    citation = Citation("citation-1", msg.message_id, SNAPSHOT, span)
    answer = Answer("answered", (Claim("合成结论", ("citation-1",)),), (citation,),
                    (TimelineEntry(msg.message_id, ("citation-1",)),), "demo")
    plan = send_plan()
    error = ErrorInfo("INDEX_NOT_READY", "索引尚未就绪", True, "task-1")
    cleanup = CleanupReport("delete-1", tuple(CleanupItem(resource, "absent") for resource in
                            ("database", "index", "attachments", "cache", "logs",
                             "keys", "pending_sends")))
    return {
        "message": msg, "snapshot": SNAPSHOT, "span": span, "coverage": coverage,
        "chunk": chunk, "manifest": manifest, "report": report,
        "batch": ImportBatch("batch-1", manifest, (msg,)),
        "import_result": ImportResult(report, "data-1"),
        "request": request, "filters": request.filters, "budget": SearchBudget(),
        "spec": SearchSpec(request, SNAPSHOT, (SOURCE,)),
        "hit": hit, "candidate": Candidate(hit, SOURCE, msg.chat_id, (span,)),
        "result": SearchResult(request.request_id, SNAPSHOT, (hit,), coverage),
        "empty_result": SearchResult(request.request_id, SNAPSHOT, (), coverage),
        "bundle": bundle, "stage": bundle.stage_candidates[0],
        "edge": MessageEdge(msg.message_id, None, "quote", "synthetic-export",
                            "data-1", True),
        "decision": InvestigationDecision("finalize", (msg.message_id,)),
        "citation": citation, "claim": answer.claims[0], "timeline": answer.timeline[0],
        "answer": answer, "empty_answer": Answer("not_found"),
        "outcome": SearchOutcome(request.request_id, answer, bundle, "complete"),
        "usage": SearchUsage(), "send_plan": plan,
        "grant": ConsentGrant("opaque-synthetic-grant", plan.fingerprint,
                              "2026-12-01T00:00:00Z"),
        "error": error, "task": TaskEvent("task-1", request.request_id, "failed", error=error),
        "source": SourceDescriptor(SOURCE, "合成来源", "A", True),
        "authorization": SourceAuthorization(SOURCE, "synthetic-source-grant"),
        "probe": ProbeResult(True, manifest),
        "failed_probe": ProbeResult(False, error=ErrorInfo("UNSUPPORTED_FORMAT", "未知格式")),
        "context": ContextResult(SNAPSHOT, msg.message_id, SOURCE, msg.chat_id, (msg,)),
        "index_record": IndexRecord(chunk.chunk_id, "合成 证据", (0.1, 0.2)),
        "index_update": IndexUpdate(SNAPSHOT, None, "synthetic-model-1", "tokenizer-1",
                                    "chunker-1", (IndexRecord(chunk.chunk_id, "", (0.1,)),)),
        "cleanup_item": cleanup.items[0], "cleanup": cleanup,
        "export": ExportReceipt("synthetic-output.json", "json", 12),
    }
