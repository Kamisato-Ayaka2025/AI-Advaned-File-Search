"""Mock 服务（C 线所有，C-01 阶段并行开发用）。

实现 Plan §4.2 服务契约的本地假实现：不联网、不写数据库，纯内存 + 确定性行为。
A/B 真实服务交付后由 application/services.py 逐一切换，UI 不感知替换。
契约字段语义见 Plan §4.1；本模块与 application/dtos.py 同为过渡件，A 的
contracts v1 发布后整体替换。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from original_words.application import demo_data
from original_words.application.dtos import (
    Answer,
    Chat,
    ChatFilters,
    Chunk,
    Citation,
    Claim,
    ConsentGrant,
    ContextWindow,
    ErrorCode,
    ImportManifest,
    ImportReport,
    Message,
    ParsedQuery,
    SearchHit,
    SearchRequest,
    SendPlan,
    ServiceError,
    TaskEvent,
    TaskState,
)

# ---------------------------------------------------------------------------
# 仓储与索引（mock）


class MockRepository:
    """内存仓储：read 不改数据；写入只经 import_batch 单入口。"""

    def __init__(self) -> None:
        self._chats: dict[str, Chat] = {}
        self._messages: dict[str, Message] = {}
        self._chat_order: list[str] = []

    # ---- 写入 ----
    def add_chat(self, chat: Chat) -> None:
        if chat.chat_id not in self._chats:
            self._chats[chat.chat_id] = chat
            self._chat_order.append(chat.chat_id)

    def import_batch(self, messages: list[Message]) -> tuple[int, int]:
        """返回 (imported, duplicate)；调用方负责统计 rejected。"""
        imported = duplicate = 0
        for msg in messages:
            if msg.message_id in self._messages:
                duplicate += 1
                continue
            self._messages[msg.message_id] = msg
            imported += 1
        return imported, duplicate

    def clear(self) -> None:
        self._messages.clear()

    # ---- 读取 ----
    def list_chats(self) -> list[Chat]:
        return [self._chats[cid] for cid in self._chat_order if cid in self._chats]

    def get_chat(self, chat_id: str) -> Chat | None:
        return self._chats.get(chat_id)

    def find_message(self, message_id: str) -> Message | None:
        return self._messages.get(message_id)

    def get_messages(self, chat_id: str) -> list[Message]:
        return sorted(
            (m for m in self._messages.values() if m.chat_id == chat_id),
            key=lambda m: m.seq,
        )

    def sender_names(self) -> list[str]:
        return sorted({m.sender_name for m in self._messages.values()})

    def stats(self) -> dict:
        known = [m for m in self._messages.values() if m.timestamp is not None]
        unknown = [m for m in self._messages.values() if m.timestamp is None]
        return {
            "chat_count": len(self.list_chats()),
            "message_count": len(self._messages),
            "unknown_time_count": len(unknown),
            "coverage_start": min((m.timestamp for m in known), default=None),
            "coverage_end": max((m.timestamp for m in known), default=None),
        }

    def get_context(
        self, chat_id: str, anchor_id: str, before: int = 10, after: int = 10
    ) -> ContextWindow:
        chat = self._chats.get(chat_id)
        if chat is None:
            raise ServiceError(ErrorCode.INVALID_INPUT, f"会话不存在：{chat_id}")
        msgs = self.get_messages(chat_id)
        index = next((i for i, m in enumerate(msgs) if m.message_id == anchor_id), None)
        if index is None:
            raise ServiceError(ErrorCode.INVALID_INPUT, "锚点消息不存在或已被删除")
        lo = max(0, index - before)
        hi = min(len(msgs), index + after + 1)
        return ContextWindow(
            chat=chat,
            anchor_id=anchor_id,
            messages=tuple(msgs[lo:hi]),
            anchor_index=index - lo,
            clipped_start=lo > 0,
            clipped_end=hi < len(msgs),
        )


class MockIndexStore:
    """A 的 IndexStore 的假实现：chunk 构建 + 修订号。"""

    CHUNK_SIZE = 30
    CHUNK_OVERLAP = 5

    def __init__(self, repo: MockRepository) -> None:
        self._repo = repo
        self._revision = 0
        self._chunks: dict[str, Chunk] = {}
        self._message_chunk: dict[str, str] = {}

    def get_active_revision(self) -> int:
        return self._revision

    def rebuild(self) -> list[Chunk]:
        """按会话切段（30 条一段、重叠 5 条），消息→chunk 映射一并重建。"""
        chunks: dict[str, Chunk] = {}
        message_chunk: dict[str, str] = {}
        for chat in self._repo.list_chats():
            msgs = self._repo.get_messages(chat.chat_id)
            if not msgs:
                continue
            idx = 0
            while idx < len(msgs):
                window = msgs[idx : idx + self.CHUNK_SIZE]
                chunk = Chunk(
                    chunk_id=f"{chat.chat_id}:c{idx // (self.CHUNK_SIZE - self.CHUNK_OVERLAP)}",
                    source_id="mock",
                    chat_id=chat.chat_id,
                    message_ids=tuple(m.message_id for m in window),
                    start=window[0].seq,
                    end=window[-1].seq,
                    participants=chat.participants,
                    text="\n".join(_display_text(m) for m in window),
                    dataset_revision=self._revision + 1,
                )
                chunks[chunk.chunk_id] = chunk
                for m in window:
                    message_chunk[m.message_id] = chunk.chunk_id
                idx += self.CHUNK_SIZE - self.CHUNK_OVERLAP
        self._chunks = chunks
        self._message_chunk = message_chunk
        self._revision += 1
        return list(chunks.values())

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        return self._chunks.get(chunk_id)

    def chunk_of(self, message_id: str) -> str | None:
        return self._message_chunk.get(message_id)


def _display_text(msg: Message) -> str:
    if msg.message_type == "file" and msg.attachment_ref:
        return msg.attachment_ref.get("name", "")
    return msg.content


# ---------------------------------------------------------------------------
# 查询理解与检索（mock）


class MockSearchService:
    def __init__(self, repo: MockRepository, index: MockIndexStore, now: datetime) -> None:
        self._repo = repo
        self._index = index
        self.now = now
        self.bm25_only = True  # 向量模型缺失时的显式降级标记（UI 可见）

    def parse_local(self, query: str) -> ParsedQuery:
        if not query.strip():
            raise ServiceError(ErrorCode.INVALID_INPUT, "查询内容不能为空")
        names = [n for n in self._repo.sender_names() if n in query]
        hints: list[str] = []
        time_hint = None
        for pattern in ("最近30天", "最近一个月", "近30天"):
            if pattern in query:
                time_hint = "最近 30 天"
        if time_hint is None and re.search(r"[三一二四五六七八九十]月|3月", query):
            time_hint = "约在三月前后"
        if time_hint:
            hints.append(f"时间线索：{time_hint}")
        for name in names:
            hints.append(f"人物线索：{name}")
        intent = "事实查找" if re.search(r"谁|哪天|哪家|是不是|有没有", query) else "查找原话"
        return ParsedQuery(
            query=query,
            intent=intent,
            hard_filters=ChatFilters(),
            soft_hints=tuple(hints),
            confidence=1.0,
        )

    @staticmethod
    def _keywords(query: str, names: list[str]) -> list[str]:
        cleaned = query
        for noise in (
            "最近30天",
            "最近一个月",
            "近30天",
            "吗",
            "？",
            "?",
            "是",
            "的",
            "了",
            "什么",
            "怎么",
            "处理",
            "哪家",
            "哪天",
        ):
            cleaned = cleaned.replace(noise, "")
        for name in names:
            cleaned = cleaned.replace(name, "")
        parts = [p for p in re.split(r"[，。,.、；;：:\s]+", cleaned) if p]
        if not parts:
            parts = [query]
        return parts[:6]

    @staticmethod
    def _bigrams(query: str) -> list[str]:
        cleaned = re.sub(r"[\s，。,.、；;：:？！？!]+", "", query)
        return sorted({cleaned[i : i + 2] for i in range(len(cleaned) - 1)})[:12]

    def search(
        self,
        request: SearchRequest,
        on_progress=None,
        cancel=None,
    ) -> tuple[list[SearchHit], float]:
        if self._index.get_active_revision() == 0:
            raise ServiceError(
                ErrorCode.INDEX_NOT_READY, "尚未导入任何数据，请先导入或载入演示数据"
            )
        started = time.perf_counter()
        names = self._repo.sender_names()
        keywords = self._keywords(request.query, names)
        phrases = [k for k in keywords if len(k) >= 2]
        bigrams = self._bigrams(request.query)
        filters = request.filters
        time_bounded = filters.start_time is not None or filters.end_time is not None

        matched: dict[str, Message] = {}
        reasons_by_id: dict[str, list[str]] = {}
        processed = 0
        for msg in self._repo._messages.values():  # noqa: SLF001 见模块说明
            processed += 1
            if cancel is not None and cancel():
                raise ServiceError(ErrorCode.CANCELLED, "搜索已取消")
            if processed % 150 == 0 and on_progress is not None:
                on_progress(processed, None)
            if time_bounded and msg.timestamp is None:
                continue  # 未知时间不匹配有界过滤
            if filters.chat_ids and msg.chat_id not in filters.chat_ids:
                continue
            if filters.chat_types and msg.chat_type not in filters.chat_types:
                continue
            if filters.sender_names and msg.sender_name not in filters.sender_names:
                continue
            if filters.message_types and msg.message_type not in filters.message_types:
                continue
            if filters.start_time is not None and (
                msg.timestamp is None or msg.timestamp < filters.start_time
            ):
                continue
            if filters.end_time is not None and (
                msg.timestamp is None or msg.timestamp >= filters.end_time
            ):
                continue
            text = _display_text(msg)
            score = 0.0
            reasons: list[str] = []
            for phrase in phrases:
                count = text.count(phrase) + msg.content.count(phrase)
                if count:
                    score += count * 10
                    reasons.append(f"命中关键词「{phrase}」")
            if score == 0:
                # 中文短语切分粗粒度兜底：按字符二元组近似命中
                matched_bigrams = [bg for bg in bigrams if bg in text or bg in msg.content]
                if matched_bigrams:
                    score += len(matched_bigrams) * 4
                    reasons.append("关键词片段命中：" + "、".join(matched_bigrams[:3]))
            if score == 0 and not phrases and msg.content:
                score = 0.5  # 无关键词时弱相关兜底
            if score > 0:
                if msg.sender_name in request.query:
                    score += 5
                    reasons.append(f"发送者：{msg.sender_name}")
                if msg.timestamp is not None and self.now - msg.timestamp <= timedelta(days=30):
                    score += 1
                matched[msg.message_id] = msg
                reasons_by_id[msg.message_id] = reasons
        if on_progress is not None:
            on_progress(processed, processed)

        # 汇总到 chunk
        chunk_scores: dict[str, float] = {}
        chunk_messages: dict[str, list[Message]] = {}
        for msg in matched.values():
            chunk_id = self._index.chunk_of(msg.message_id)
            if chunk_id is None:
                continue
            chunk_scores[chunk_id] = chunk_scores.get(chunk_id, 0.0) + 10
            chunk_messages.setdefault(chunk_id, []).append(msg)

        hits = []
        for chunk_id, score in sorted(chunk_scores.items(), key=lambda kv: kv[1], reverse=True):
            msgs = sorted(chunk_messages[chunk_id], key=lambda m: m.seq)
            hit_reasons = sorted({r for m in msgs for r in reasons_by_id.get(m.message_id, [])})
            if not hit_reasons:
                hit_reasons = ("相关原话",)
            hits.append(
                SearchHit(
                    chunk_id=chunk_id,
                    message_ids=tuple(m.message_id for m in msgs),
                    score=round(score, 2),
                    reasons=tuple(hit_reasons),
                    index_revision=self._index.get_active_revision(),
                )
            )
            if len(hits) >= request.top_k:
                break
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return hits, elapsed_ms


# ---------------------------------------------------------------------------
# 答案与发送（mock）


class MockConsentService:
    """默认拒绝；同意绑定 payload_hash；一次性同意用后即失效。"""

    def __init__(self) -> None:
        self._grants: dict[str, ConsentGrant] = {}

    def grant(self, request_id: str, payload_hash: str, scope: str) -> ConsentGrant:
        grant = ConsentGrant(
            request_id=request_id,
            scope=scope,
            payload_hash=payload_hash,
            granted_at=datetime.now(),
        )
        self._grants[request_id] = grant
        return grant

    def validate(self, plan: SendPlan) -> bool:
        grant = self._grants.get(plan.request_id)
        if grant is None or grant.revoked or grant.payload_hash != plan.payload_hash:
            return False
        if grant.scope == "one_time":
            self.revoke(plan.request_id)
            return True
        return True

    def revoke(self, request_id: str | None = None) -> None:
        if request_id is None:
            for grant in self._grants.values():
                object.__setattr__(grant, "revoked", True)
            return
        grant = self._grants.get(request_id)
        if grant is not None:
            object.__setattr__(grant, "revoked", True)

    def list_active(self) -> list[ConsentGrant]:
        return [g for g in self._grants.values() if not g.revoked]


class MockSecretStore:
    """内存凭据（仅 mock）：UI 只拿到掩码值，不回显完整 Key。"""

    def __init__(self) -> None:
        self._values: dict[str, str] = {
            "base_url": "https://api.deepseek.com",
            "api_key": "",
            "model": "deepseek-flash",
            "timeout": "30",
            "retry": "2",
        }

    def get(self, key: str) -> str:
        return self._values.get(key, "")

    def set(self, key: str, value: str) -> None:
        self._values[key] = value

    def delete(self, key: str) -> None:
        self._values.pop(key, None)

    def is_key_configured(self) -> bool:
        return bool(self._values.get("api_key"))

    def is_key_valid(self) -> bool:
        key = self._values.get("api_key", "")
        return key.startswith("sk-") and len(key) >= 12

    def masked_key(self) -> str:
        key = self._values.get("api_key", "")
        if not key:
            return ""
        return f"{key[:3]}…{key[-4:]}"


class MockAnswerService:
    def __init__(
        self,
        repo: MockRepository,
        index: MockIndexStore,
        consent: MockConsentService,
        secrets: MockSecretStore,
    ) -> None:
        self._repo = repo
        self._index = index
        self._consent = consent
        self._secrets = secrets

    def has_llm(self) -> bool:
        return self._secrets.is_key_configured()

    def model(self) -> str:
        return self._secrets.get("model") or "deepseek-flash"

    def endpoint(self) -> str:
        return self._secrets.get("base_url") or "https://api.deepseek.com"

    def preview_messages(
        self, hits: list[SearchHit], limit: int = 3, per_hit: int = 6
    ) -> list[Message]:
        """取前若干命中的代表消息，供预览对话框勾选。"""
        unique: dict[str, Message] = {}
        for hit in hits[:limit]:
            for mid in hit.message_ids[:per_hit]:
                msg = self._repo.find_message(mid)
                if msg is not None:
                    unique[msg.message_id] = msg
        return list(unique.values())

    def prepare_send(
        self,
        request_id: str,
        query: str,
        hits: list[SearchHit],
        selected_message_ids: tuple[str, ...] | None = None,
        mode: str = "full",
    ) -> SendPlan:
        messages = []
        for hit in hits[:3]:
            for mid in hit.message_ids[:6]:
                msg = self._repo.find_message(mid)
                if msg is not None:
                    messages.append(msg)
        unique = {m.message_id: m for m in messages}
        if selected_message_ids is not None:
            messages = [unique[mid] for mid in selected_message_ids if mid in unique]
        preview_lines = ["# 发送预览（查询解析与回答）", f"查询：{query}", ""]
        for msg in messages:
            ts = msg.timestamp.strftime("%Y-%m-%d %H:%M") if msg.timestamp else "时间未知"
            preview_lines.append(f"- {ts} {msg.sender_name}：{_display_text(msg)}")
        preview_text = "\n".join(preview_lines)
        plan = SendPlan(
            request_id=request_id,
            purpose="查询解析与回答",
            mode=mode,
            payload_hash=SendPlan.compute_hash(preview_text, self.model(), self.endpoint()),
            selected_message_ids=tuple(m.message_id for m in messages),
            preview_text=preview_text,
            model=self.model(),
            endpoint=self.endpoint(),
            consent_scope="one_time",
        )
        return plan

    def update_selection(
        self,
        plan: SendPlan,
        selected_message_ids: tuple[str, ...],
        mode: str,
        edited_preview: str | None = None,
    ) -> SendPlan:
        """用户在预览对话框调整选择/编辑文本后重建计划；预览变化使旧授权失效。"""
        if edited_preview is not None:
            preview_text = edited_preview
        else:
            messages = [
                m for mid in selected_message_ids if (m := self._repo.find_message(mid)) is not None
            ]
            lines = [f"# {plan.purpose}", ""]
            for msg in messages:
                ts = msg.timestamp.strftime("%Y-%m-%d %H:%M") if msg.timestamp else "时间未知"
                lines.append(f"- {ts} {msg.sender_name}：{_display_text(msg)}")
            preview_text = "\n".join(lines)
        return SendPlan(
            request_id=plan.request_id,
            purpose=plan.purpose,
            mode=mode,
            payload_hash=SendPlan.compute_hash(preview_text, plan.model, plan.endpoint),
            selected_message_ids=selected_message_ids,
            preview_text=preview_text,
            model=plan.model,
            endpoint=plan.endpoint,
            consent_scope=plan.consent_scope,
        )

    def _canned(self, query: str, hits: list[SearchHit]) -> Answer | None:
        events = getattr(self._repo, "_events", None)
        if events is None:
            return None
        fmt = lambda m: (  # noqa: E731
            m.timestamp.strftime("%Y-%m-%d %H:%M") if m.timestamp else "时间未知"
        )
        if query.startswith("谁最先反对换供应商"):
            oppose = events["supplier_oppose_first"]
            support = events["supplier_support_b"]
            return Answer(
                status="answered",
                claims=(
                    Claim(
                        f"{oppose.sender_name} 最先提出反对（{fmt(oppose)}）：「{oppose.content}」",
                        (oppose.message_id,),
                    ),
                    Claim(
                        "其后王强、赵敏支持更换，讨论最终收敛到 B 供应商",
                        (support.message_id, events["supplier_choice_b"].message_id),
                    ),
                ),
                citations=tuple(self._cite(m, hits) for m in (oppose, support)),
                timeline_message_ids=(oppose.message_id, support.message_id),
                mode="llm_sim",
                stop_reason="demo",
            )
        if query.startswith("供应商最后换了哪家"):
            decide = events["supplier_decide"]
            choice = events["supplier_choice_b"]
            case = events["supplier_case_b"]
            return Answer(
                status="answered",
                claims=(
                    Claim("最终选定 B 供应商并计划签约", (choice.message_id, decide.message_id)),
                ),
                citations=tuple(self._cite(m, hits) for m in (choice, case, decide)),
                timeline_message_ids=(choice.message_id, case.message_id, decide.message_id),
                mode="llm_sim",
                stop_reason="demo",
            )
        if query.startswith("张伟三月提到的登录 bug"):
            recurred = events["bug_recurred"]
            fixed = events["bug_fixed"]
            return Answer(
                status="answered",
                claims=(
                    Claim(
                        "登录 bug（token 过期）已修复：改为刷新失败时自动重试，下个版本带上",
                        (fixed.message_id,),
                    ),
                ),
                citations=tuple(self._cite(m, hits) for m in (recurred, fixed)),
                timeline_message_ids=(recurred.message_id, fixed.message_id),
                mode="llm_sim",
                stop_reason="demo",
            )
        return None

    def _cite(self, msg: Message, hits: list[SearchHit]) -> Citation:
        chunk_id = self._index.chunk_of(msg.message_id)
        if chunk_id is None and hits:
            chunk_id = hits[0].chunk_id
        return Citation(
            message_id=msg.message_id,
            sender_name=msg.sender_name,
            timestamp=msg.timestamp,
            chat_id=msg.chat_id,
            chat_name=self._repo.get_chat(msg.chat_id).chat_name
            if self._repo.get_chat(msg.chat_id)
            else msg.chat_id,
            text=_display_text(msg),
            chunk_id=chunk_id or "",
        )

    def _coverage_note(self) -> str:
        stats = self._repo.stats()
        start = stats["coverage_start"]
        end = stats["coverage_end"]
        span = (
            f"{start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}"
            if start and end
            else "无有效时间"
        )
        return (
            f"覆盖范围：{stats['chat_count']} 个会话、{stats['message_count']} 条消息"
            f"（{span}）；其中 {stats['unknown_time_count']} 条时间未知、按来源顺序另列。"
            "“没找到”仅表示当前数据中不存在，不代表历史上没讨论过。"
        )

    def _local_answer(self, query: str, hits: list[SearchHit], elapsed_ms: int) -> Answer:
        if not hits:
            return Answer(
                status="no_evidence",
                claims=(Claim(f"没找到与「{query}」相关的聊天记录", ()),),
                citations=(),
                timeline_message_ids=(),
                mode="local",
                elapsed_ms=elapsed_ms,
                stop_reason="no_hits",
                coverage_note=self._coverage_note(),
            )
        messages = []
        for hit in hits[:3]:
            for mid in hit.message_ids[:3]:
                msg = self._repo.find_message(mid)
                if msg is not None:
                    messages.append(msg)
        messages = messages[:5]
        total_hits = sum(len(h.message_ids) for h in hits)
        return Answer(
            status="answered",
            claims=(Claim(f"共找到 {total_hits} 处相关原话，摘录如下", ()),),
            citations=tuple(self._cite(m, hits) for m in messages),
            timeline_message_ids=tuple(m.message_id for m in messages),
            mode="local",
            elapsed_ms=elapsed_ms,
            stop_reason="no_key_local",
            coverage_note=self._coverage_note(),
        )

    def generate(
        self,
        plan: SendPlan,
        query: str,
        hits: list[SearchHit],
        elapsed_ms: int = 0,
        on_token=None,
        cancel=None,
    ) -> Answer:
        started = time.perf_counter()
        canned = self._canned(query, hits)
        if not hits:
            return self._local_answer(query, hits, elapsed_ms)
        if not self._secrets.is_key_configured():
            # 无 Key：不联网、不需要同意；演示查询给本地罐头答案（mode=demo）
            if canned is not None:
                answer = Answer(**{**canned.__dict__, "mode": "demo"})
            else:
                answer = self._local_answer(query, hits, elapsed_ms)
            return Answer(
                **{**answer.__dict__, "elapsed_ms": int((time.perf_counter() - started) * 1000)}
            )
        if not self._consent.validate(plan):
            raise ServiceError(
                ErrorCode.CONSENT_REQUIRED,
                "需要先同意本次发送内容（默认拒绝外发）",
                retryable=True,
            )
        if canned is None:
            answer = self._local_answer(query, hits, elapsed_ms)
            answer = Answer(
                **{**answer.__dict__, "mode": "llm_sim", "stop_reason": "llm_sim_complete"}
            )
        else:
            answer = canned
        if on_token is not None:
            text = "\n".join(c.text for c in answer.claims)
            for i in range(0, len(text), 24):
                if cancel is not None and cancel():
                    raise ServiceError(ErrorCode.CANCELLED, "回答已取消")
                on_token(text[i : i + 24])
                time.sleep(0.005)
        tokens = sum(len(c.text) for c in answer.claims) // 2
        return Answer(
            **{
                **answer.__dict__,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "calls": 1,
                "tokens": tokens,
            }
        )


class MockDataLifecycle:
    """导出/删除的假实现：导出为真实文件写入，删除清内存仓储。"""

    def __init__(self, repo: MockRepository) -> None:
        self._repo = repo

    def export(self, path: Path, query: str, answer: Answer) -> Path:
        if path.suffix.lower() == ".json":
            payload = {
                "query": query,
                "status": answer.status,
                "mode": answer.mode,
                "claims": [
                    {"text": c.text, "citation_ids": list(c.citation_ids)} for c in answer.claims
                ],
                "citations": [
                    {
                        "message_id": c.message_id,
                        "sender_name": c.sender_name,
                        "timestamp": c.timestamp.isoformat() if c.timestamp else None,
                        "chat_name": c.chat_name,
                        "text": c.text,
                    }
                    for c in answer.citations
                ],
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            lines = ["# 原话考古 · 答案导出", "", f"查询：{query}", "", "## 结论"]
            for claim in answer.claims:
                lines.append(f"- {claim.text}")
            lines += ["", "## 引用原话"]
            for i, citation in enumerate(answer.citations, start=1):
                ts = (
                    citation.timestamp.strftime("%Y-%m-%d %H:%M")
                    if citation.timestamp
                    else "时间未知"
                )
                lines.append(
                    f"{i}. [{ts}] {citation.sender_name}（{citation.chat_name}）：{citation.text}"
                )
            if answer.coverage_note:
                lines += ["", "## 覆盖范围", answer.coverage_note]
            path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def delete(self) -> list[tuple[str, bool, str]]:
        count = len(self._repo._messages)  # noqa: SLF001
        self._repo.clear()
        return [("事实数据", True, f"已清除 {count} 条消息（mock 仅内存，无磁盘残留）")]


# ---------------------------------------------------------------------------
# 文件导入（mock，JSON/CSV/TXT 三种格式真实解析）


class MockExportAdapter:
    REQUIRED = ("message_id", "chat_id", "sender_name", "content")
    ADAPTER_VERSION = "0.1.0"

    @staticmethod
    def probe(path: Path) -> str:
        ext = path.suffix.lower().lstrip(".")
        if ext not in ("json", "csv", "txt"):
            raise ServiceError(
                ErrorCode.UNSUPPORTED_FORMAT,
                f"不支持的格式：{ext or '无扩展名'}（仅支持 JSON/CSV/TXT）",
            )
        return f"tier-a-{ext}"

    def read(
        self,
        path: Path,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        on_progress=None,
        cancel=None,
    ) -> tuple[list[Message], ImportReport]:
        adapter_id = self.probe(path)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ServiceError(ErrorCode.INVALID_INPUT, f"无法读取文件：{exc}") from exc
        if not raw.strip():
            raise ServiceError(ErrorCode.INVALID_INPUT, "文件为空")
        text = None
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ServiceError(ErrorCode.INVALID_INPUT, "文件编码无法识别（需 UTF-8 或 GB18030）")

        rows: list[dict] = []
        if adapter_id == "tier-a-json":
            rows = self._parse_json(text)
        elif adapter_id == "tier-a-csv":
            rows = self._parse_csv(text)
        else:
            rows = self._parse_txt(text)

        messages: list[Message] = []
        rejected = 0
        unknown = 0
        attachment_missing = 0
        seq_counter: dict[str, int] = {}
        known_times: list[datetime] = []
        for index, row in enumerate(rows):
            if cancel is not None and cancel():
                raise ServiceError(ErrorCode.CANCELLED, "导入已取消")
            if on_progress is not None and index % 100 == 0:
                on_progress(index, len(rows))
            missing = [key for key in self.REQUIRED if not str(row.get(key, "")).strip()]
            if missing:
                rejected += 1
                continue
            ts = row.get("timestamp")
            timestamp: datetime | None = None
            if ts:
                try:
                    timestamp = datetime.fromisoformat(str(ts))
                    known_times.append(timestamp)
                except ValueError:
                    timestamp = None
                    unknown += 1
            else:
                unknown += 1
            if start_time is not None and (timestamp is None or timestamp < start_time):
                rejected += 1
                continue
            if end_time is not None and (timestamp is None or timestamp >= end_time):
                rejected += 1
                continue
            attachment = row.get("attachment_ref")
            if isinstance(attachment, str):
                attachment = {"name": attachment, "kind": "file", "available": False}
            if attachment and not attachment.get("available", False):
                attachment_missing += 1
            chat_id = str(row["chat_id"])
            seq_counter[chat_id] = seq_counter.get(chat_id, 0) + 1
            message_id = str(row["message_id"])
            if not message_id.startswith("import:"):
                message_id = f"import:{message_id}"
            messages.append(
                Message(
                    message_id=message_id,
                    chat_id=chat_id,
                    chat_type=str(row.get("chat_type", "private")),
                    sender_id=str(row.get("sender_id", row["sender_name"])),
                    sender_name=str(row["sender_name"]),
                    timestamp=timestamp,
                    message_type=str(row.get("message_type", "text")),
                    content=str(row.get("content", "")),
                    quote_of=str(row["quote_of"]) if row.get("quote_of") else None,
                    attachment_ref=attachment,
                    source_id="import",
                    seq=seq_counter[chat_id],
                    timestamp_status="known" if timestamp else "unknown",
                    timestamp_precision="minute" if timestamp else None,
                )
            )
        if on_progress is not None:
            on_progress(len(rows), len(rows))
        manifest = ImportManifest(
            adapter_id=adapter_id,
            adapter_version=self.ADAPTER_VERSION,
            upstream_tool=None,
            upstream_version=None,
            client_build=None,
            export_schema=adapter_id,
            account_scope=None,
            exported_at=None,
            snapshot_hash=hashlib.sha256(raw).hexdigest()[:16],
        )
        completeness = (
            "verified_for_scope" if rejected == 0 else ("partial" if messages else "unknown")
        )
        report = ImportReport(
            manifest=manifest,
            source_count=len(rows),
            read_count=len(rows),
            imported_count=len(messages),
            duplicate_count=0,  # 去重由仓储 import_batch 统计
            rejected_count=rejected,
            unknown_count=unknown,
            attachment_missing_count=attachment_missing,
            completeness=completeness,
            coverage_start=min(known_times) if known_times else None,
            coverage_end=max(known_times) if known_times else None,
        )
        return messages, report

    def _parse_json(self, text: str) -> list[dict]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ServiceError(ErrorCode.INVALID_INPUT, f"JSON 解析失败：{exc}") from exc
        if not isinstance(data, list):
            raise ServiceError(
                ErrorCode.UNSUPPORTED_FORMAT,
                "未知 JSON 结构：期望顶层为消息数组（schema 不支持时拒绝，不猜字段）",
            )
        rows = [item for item in data if isinstance(item, dict)]
        if not rows:
            raise ServiceError(ErrorCode.INVALID_INPUT, "JSON 中没有可导入的消息")
        return rows

    def _parse_csv(self, text: str) -> list[dict]:
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        except csv.Error as exc:
            raise ServiceError(ErrorCode.INVALID_INPUT, f"CSV 解析失败：{exc}") from exc
        if not rows:
            raise ServiceError(ErrorCode.INVALID_INPUT, "CSV 没有数据行")
        if reader.fieldnames is None or not set(self.REQUIRED).issubset(set(reader.fieldnames)):
            raise ServiceError(
                ErrorCode.INVALID_INPUT,
                f"CSV 缺少必填列（需要：{'、'.join(self.REQUIRED)}）",
            )
        return rows

    def _parse_txt(self, text: str) -> list[dict]:
        rows = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 4:
                rows.append({})  # 计为 rejected，保证 read=imported+dup+rejected
                continue
            ts_raw, sender, chat_name, content = parts[0], parts[1], parts[2], "|".join(parts[3:])
            try:
                timestamp = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M")
            except ValueError:
                rows.append({})
                continue
            rows.append(
                {
                    "message_id": f"txt-{line_no}",
                    "chat_id": chat_name,
                    "sender_name": sender,
                    "content": content,
                    "timestamp": timestamp.isoformat(),
                }
            )
        return rows


# 由容器注入演示事件键到仓储（供 MockAnswerService._canned 使用）
class DemoRepository(MockRepository):
    def __init__(self) -> None:
        super().__init__()
        self._events: dict[str, Message] = {}

    def load_demo(self, bundle: demo_data.DatasetBundle) -> None:
        self._events = dict(bundle.events)
        for chat in bundle.chats:
            self.add_chat(chat)
        self.import_batch(bundle.messages)


def make_task_event(
    task_id: str,
    state: TaskState,
    completed: int | None = None,
    total: int | None = None,
    error: ServiceError | None = None,
    detail: str = "",
    request_id: str | None = None,
) -> TaskEvent:
    return TaskEvent(
        task_id=task_id,
        request_id=request_id,
        state=state,
        completed=completed,
        total=total,
        error=error,
        detail=detail,
    )
