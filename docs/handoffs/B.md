# B 交接记录

日期：2026-10-18
负责人：B / @YuanKunlin
范围：检索与答案（`retrieval/`、`llm/`、`tests/retrieval/`、`tests/llm/`、`tests/evaluation/`）

## 当前实现（本分支）

### B-01 混合检索

- `retrieval/chunking.py`：parent 30/重叠 5，child 4–8/重叠 1；长消息按字符区间切分，保留 `message_id + char_span`。
- `retrieval/text.py`：CJK 预分词（一字一 token）、FTS5 查询构造（AND + 长查询 bigram OR 回退）、精确实体提取。
- `retrieval/index.py`：SQLite FTS5 + `unit_senders`/`unit_types` 过滤表 + 精确 LIKE 通道；索引版本；上下文读取。
- `retrieval/vectors.py`：精确 cosine 内存向量，支持过滤集合。
- `retrieval/hybrid.py`：BM25 top-80 + 向量 top-80 + 精确实体命中，RRF `k=60`，按 message 重叠去重，返回命中理由与降级标记。
- `retrieval/context.py`：前后各 N 条上下文、显式 `quote_of` 双向扩展（最多 2 跳、120 条）。
- `retrieval/evaluate.py`：Recall@K、MRR、nDCG@10、零结果率。

### B-02 查询理解与答案

- `llm/query.py`：规则解析时间（今天/昨天/上周/上周三/最近 N 天/月份/ISO 日期）、人物、会话、来源、消息类型；硬过滤 vs 软线索；意图；`apply_llm_query` 合并 LLM 槽位（显式规则优先，hedged 时间仍为软线索）。
- `llm/deepseek.py`：`prepare_send` 只生成 payload 与 hash；`generate` 必须收到 A 的授权且 hash 匹配；无 Key/429/401 的错误映射；JSON 输出校验。
- `llm/answer.py`：引用校验（message_id、字符区间、原文、revision、发送者/时间可选）、抽取式无网络回答、`answer_from_json`。
- 无证据时返回 `not_found`，不生成补足。

### 测试

```bash
# 当前环境（Python 3.13 + numpy + pytest）：
/home/ykl/AI-Advaned-File-Search/.venv/bin/python -m pytest -q tests/retrieval tests/llm
```

78 passed（B-01 35 + B-02 43），覆盖 CJK 两字查询、向量改写、过滤、去重、上下文、引用扩展、时间解析、无授权零网络、引用伪造拒收、搜索→回答端到端。

## 临时边界（待 A 的 contracts v1 替换）

- `retrieval/types.py` 中的 `MessageRecord/ChunkRecord/SearchRequest/SearchHit/SearchResponse` 是 B 内部 DTO，字段对齐 `Plan.md` §4.1；A 发布 `contracts/search.py` 后应改为适配层，不复制公共契约。
- `RetrievalIndex` 是开发/评测用的本地 SQLite；生产写入必须走 A 的 `IndexStore.publish`，B 不自行迁移或并发写表。
- 向量默认精确 cosine；ANN 需 SR3 独立验收。
- `HybridSearcher.min_vector_score=0.2` 是可配置阈值，用于避免“无词法证据时被低相似向量硬答”；需在真实模型/开发集上校准。
- `HashingEmbedder` 只用于测试/链路验证，不是语义模型；基线仍是 FastEmbed/ONNX 的 `bge-small-zh-v1.5`。

## 待 A/C 确认

1. contracts v1 + fixtures 的可执行样例；`Repository/IndexStore/SearchService` 签名。
2. `SearchHit` 是否需要 `char_span/index_revision/quote_of/timestamp_precision` 等字段，由谁落 schema。
3. 中文分词最终方案（jieba 预分词 / simple / trigram）；当前 B-01 是可插拔的 CJK 字符方案。
4. C 的依赖锁是否批准 `numpy`（B-01 需要）、`fastembed`/`onnxruntime`（P0 模型 spike）、`pytest`。
5. 6 小时 D1 中 B 的最小集：B-01 fixture + B-02 规则/一次 DeepSeek + 引用；SR2/G7 放演示后。

## 下一步

1. P0：FastEmbed/ONNX 加载 bge-small，记录离线、CPU 时延、RSS、中文效果、模型缺失降级。
2. B-01：接 A 的 fixture 与 `IndexStore`，跑 recall@10；补精确引用/时间过滤回归。
3. B-02：把 `DeepSeekClient.build_query_request` 的输出接回 `QuerySpec`；补 20 条槽位评测；补 API 失败回退。
4. B-03：追问状态、冲突证据、超时/限流、缓存按 revision/授权绑定。
5. 评测：把 `tests/evaluation/gold_smoke.jsonl` 扩到 80 题，按事件拆 dev/test。

## 不做

- 不继续微信探测；QQ 解码经验只做交接，不产品化。
- 不把本地生成模型作为 B-02 依赖；DeepSeek 是唯一 LLM。
- 不提交真实聊天、密钥、运行数据库、模型权重。

## 契约 0.2.0-draft B 侧评审（PR #2）

基于 `pr-2`（A 的 `codex/p0-a-message-contract`）合并 B-01/B-02 后，新增：

- `src/original_words/retrieval/contracts_bridge.py`：内部 Message/Chunk/Hit → 契约 DTO；`ContractSearchService` 实现 A 的 `SearchService.parse_local/search`。
- `src/original_words/llm/contracts_bridge.py`：内部 Citation/Answer/SendPlan → 契约 DTO；Citation 只保留 `message_id + snapshot + char_span`，不带模型生成的原文/发送者/时间。
- `tests/retrieval/test_contracts_consumption.py`、`tests/llm/test_contracts_consumption.py`：11 个 B 侧消费测试。
- 结果：B 93 tests + A 52 tests 全过（Python 3.13；A 的 3.11 语法检查仍通过）。
- 已修正 B-02 的发送预览：`preview_text` 现在是实际 UTF-8 JSON 请求体，`payload_hash = SHA-256(preview_text)`，`_http_post` 发送同一串字节；满足 `SendPlan` 的“完整预览指纹”。

### B 侧确认

- `SearchSpec` 硬过滤不得超出 `authorized_source_ids`；`ContractSearchService.parse_local` 依赖契约校验。
- `SearchResult` 的 hit 必须共享同一 `index_revision`；B 适配器用 `SnapshotRef.index_revision` 校验。
- 证据包/引用必须绑定同一 `SnapshotRef`；`validate_answer` 可对 B 的抽取式回答通过。
- `SendPlan.fingerprint` 会把 purpose/mode/selected/model/endpoint/scope 与完整 preview 一起绑定；编辑后旧 grant 失效。

### 待 A 确认的契约缺口（B 不建议在确认前冻结 v1）

> 与 C 的评审对齐：B4（日期级时间）和 B5（SendPlan 证据版本）同时阻塞；B 追加 B2（Answer request_id/clarification）与 `SearchFilters`/`Message` 的 B 侧缺口。

1. **`SearchFilters` 缺 `chat_types`（group/private）**：REQ-022 要求群聊/私聊过滤，目前只能用 `chat_ids` 逐个列，无法表达“只看群聊”。B 内部有 `chat_types`，契约层丢失。
2. **`SearchFilters.message_types` 缺 `link/voice/emoji`**：B 的规则解析会产出这三类；契约只有 `text/image/file/system/recalled/unknown`。若映射到 `unknown`，用户按“语音/链接”过滤会失效；建议扩枚举或明确降级规则。
3. **`SearchResult.hits` 不含 `source_id/chat_id/char_spans`**：C 需再用 `Repository.get_chunks(chunk_ids, snapshot, source_ids)` 二次取片段才能展示来源/会话/引用区间。B 测试已验证该路径可行，但请确认这是契约意图，而不是让 C 从 `SearchHit` 猜。
4. **`Message` 的 `timestamp_source/precision` 来源**：B 内部 `MessageRecord` 只有 epoch，适配器只能推断 `timestamp_source="retrieval-index"`。真实导入必须保留 A 的原始 provenance/精度；B 建议生产路径直接消费 A 的 `Message`，不要用 B 的推断值。
5. **日期级过滤策略**：A 当前对有界时间过滤保守排除 `precision=day` 的消息；B 可以接受该保守策略用于 v1，但“3 月份”这类查询会漏掉日期级记录。请产品/A 明确是否接受，或增加独立的日期区间策略。
6. **`AnswerService.generate` 尚未接 A 的 `ConsentService.consume`**：B 已有 `to_contract_send_plan` 和精确 preview；完整 `AnswerService` 适配（consume → 发送原样字节 → hydrate citations）仍待 B-02 下一步实现。当前 `DeepSeekClient` 仍保留内部 `Authorization` 测试替身，不冒充 A 的授权服务。
7. **`Answer` 缺 `request_id` / `clarification`**（与 C 的 B2 一致）：`AnswerService.generate` 返回 `Answer`，迟到结果无法按 request_id 丢弃；REQ-023 的追问文案只能放在 `ambiguous` 状态但无处承载。建议 `Answer` 增 `request_id` 和 `clarification`，或让 `generate` 返回 `SearchOutcome`。
8. **`SendPlan` 未绑定证据快照/摘要**（与 C 的 B5 一致）：`prepare_send` 与 `generate` 两次传 `evidence`，但 plan 里没有 `snapshot`/`evidence_digest`，无法在 DTO 层发现“预览是 revision A、发送是 revision B”。建议 plan 增 `snapshot` 或 `evidence_digest` 并在 `consume`/`generate` 校验。

### 对 C 评审（B1–B5）的回应

- **同意 C 的 B2/B4/B5**：`Answer.request_id/clarification`、日期级过滤策略、`SendPlan` 证据版本绑定都列入 B 侧阻塞；B 的 `test_gap_*` 已覆盖 B2/B5。
- **C 的 B1（ChatSummary/list_chats）与 B3（ImportIssue）属 A 的存储/导入契约**：B 不阻塞其设计；B 会消费 `ChatSummary` 显示会话名，并接受 `ImportIssue` 作为覆盖/质量提示的来源，不自行扫描全库枚举会话。
- **C 的 S10（SearchHit 不含文本）与 B 的 hydration 缺口一致**：B 接受 `Repository.get_chunks` 二次取文本/字符区间的路径，但请 A 在契约说明中写明这是 C 的正式消费方式。
- **C 的基线过期提醒**：B 评审分支基于 `pr-2` 的 `a333994`；A 更新 main 后 B 会重新合并并重跑，不沿用旧基线绿色结果。
