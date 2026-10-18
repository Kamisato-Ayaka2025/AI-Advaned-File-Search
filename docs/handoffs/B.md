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

- `llm/query.py`：规则解析时间（今天/昨天/上周/上周三/最近 N 天/月份/ISO 日期）、人物、会话、来源、消息类型；硬过滤 vs 软线索；意图。
- `llm/deepseek.py`：`prepare_send` 只生成 payload 与 hash；`generate` 必须收到 A 的授权且 hash 匹配；无 Key/429/401 的错误映射；JSON 输出校验。
- `llm/answer.py`：引用校验（message_id、字符区间、原文、revision、发送者/时间可选）、抽取式无网络回答、`answer_from_json`。
- 无证据时返回 `not_found`，不生成补足。

### 测试

```bash
# 当前环境（Python 3.13 + numpy + pytest）：
/home/ykl/AI-Advaned-File-Search/.venv/bin/python -m pytest -q tests/retrieval tests/llm
```

75 passed（B-01 35 + B-02 40），覆盖 CJK 两字查询、向量改写、过滤、去重、上下文、引用扩展、时间解析、无授权零网络、引用伪造拒收、搜索→回答端到端。

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
