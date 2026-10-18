# 里程碑：aimem engine 端到端检索原型（2026-10-18）

- 状态：**研究原型完成**，独立于 `src/original_words/` 主线
- 代码：`engine/`
- 测试：29 passed
- 关联：B-01（`src/original_words/retrieval/`）、Tier B 聊天导出

## 1. 目标

验证「文件系统 + 微信 + QQ」能否共用一套检索核心，并回答三个工程问题：

1. 关键词与纯语义检索在真实 6.8 万文件规模下是否可用？
2. 换更大的 embedding 模型、加 cross-encoder 精排，各自的收益是多少？
3. 聊天记录（含图片 OCR）接入后，跨源检索是否成立？

## 2. 交付物

| 模块 | 路径 | 说明 |
|---|---|---|
| 检索核心 | `engine/src/aimem/` | Unit、SQLite FTS5、向量、RRF、精排 |
| 数据接入 | `ingest/fs.py`、`ingest/jsonl.py`、`ingest/markdown.py` | 文件、JSONL、Markdown 聊天 |
| Everything | `everything.py` | Windows HTTP/JSON 客户端 + 本地扫描回退 |
| 服务 | `server.py` + `cli.py serve` | 本地 Web UI |
| 基准 | `engine/examples/` | 建索引、分层评测、重嵌、精排、OCR |
| 文档 | `docs/evidence/aimem-engine/` | 本文件、基准、微信图片 |

## 3. 架构

```
查询
 ├─ 规则 planner：时间/类型/大小/来源
 ├─ Everything：文件名/路径（5–20ms）
 ├─ FTS5：正文 BM25（20–80ms）
 ├─ 向量：bge-small-zh（30–120ms）
 └─ RRF 融合 → 折叠到展示单元 → 精排 Top-50 → 结果卡片
```

关键设计：

- **检索单元 ≠ 展示单元**：chunk 命中聚合回 file；message 独立展示。
- **先出结果不等规划**：LLM/规划不阻塞首屏。
- **精排条件触发**：查询词已出现在 Top-1 标题时跳过，避免推翻强词法信号。
- **增量**：`(id, content_hash)`；文本变化才重嵌。

## 4. 数据规模

| 来源 | 数量 |
|---|---:|
| 本地文件（C/D 盘） | 68,822 文件 |
| 检索单元 | 111,381（42,559 正文分块） |
| 微信消息 | 19,159（53 会话，15 个月） |
| QQ 消息 | 2,204 |
| 微信图片 | 505 解码 / 377 有文字 |
| 演示库合计 | 132,744 单元 |

## 5. 评测结果

### 5.1 分层（无精排）

| 层 | 查询构造 | n | Recall@10 | MRR |
|---|---|---:|---:|---:|
| L1 精确 | 文件名 | 15 | 1.000 | 0.967 |
| L1 片段 | 文件名中截 4 个汉字 | 15 | 1.000 | 1.000 |
| L2 纯语义 | 内容改写，无文件名关键词 | 10 | 0.900 | 0.760 |

### 5.2 精排 A/B（bge-reranker-v2-m3，Top-50）

| 配置 | L1-partial MRR | L2 MRR | 40 条耗时 |
|---|---:|---:|---:|
| 无精排 | 1.000 | 0.760 | 5.3s |
| w=0.45 | 0.967 | 0.820 | 18.5s |
| w=0.75 | 0.967 | 0.900 | 19.1s |
| **w=0.75 + 标题命中跳过** | **1.000** | **0.900** | **10.2s** |

### 5.3 模型 A/B（同 111,381 单元，256 字符截断）

| 模型 | 参数量 | 重嵌耗时 | L2 MRR |
|---|---:|---:|---:|
| bge-small-zh-v1.5 | 24M | 87s | 0.760 |
| Qwen3-Embedding-0.6B | 596M | 687s | 0.770 |

结论：**embedding 不是瓶颈**，换 0.6B 无实质收益。

### 5.4 微信图片

- 879 条图片消息，521 链接，0 断链，505 解码，377 有文字（75%）。
- 隔离测试（图片独有词）：OCR 后 12/12，OCR 前 0/12。
- 图片消息覆盖率：377/879 = 43%。

## 6. 工程发现

1. **FTS5 执行计划陷阱**：`MATCH` 与 `u.source IN (...)` 写在同一层 JOIN 时，SQLite 选择逐行重算的计划，单条查询 212s；改为「子查询取 FTS top-N 再 JOIN」后 0.28s。
2. **打分归一化**：RRF 分数约 1/60，直接叠加时间/路径先验会让「最近修改」压过相关性；必须先归一化再融合。
3. **chunk 聚合**：同一文件的多个 chunk 不能各自累加 RRF 分，否则长文档虚高；先折叠到 file 再融合。
4. **增量正确性**：同 id 文本变化（如补 OCR caption）必须按内容哈希重嵌，否则语义检索保留旧向量。
5. **OCR 内存**：1.3 亿像素图片会打爆内存；缩放至 1600px、跳过 >40MP、caption 缓存断点续跑。
6. **Everything HTTP 默认关闭**：`allow_http_server=1` 不等于服务启用，需在 UI 中开启。

## 7. 演示

本地 Web UI：来源筛选、精排开关、匹配理由、时间/路径。演示库 132,744 单元，单条查询约 250–500ms。

## 8. 与主线的边界

- 当前产品 `Plan.md` 明确排除 Everything、文件正文解析、OCR、Tier C；本原型包含这些内容，**仅作为研究证据**，不改变产品范围。
- 未修改 `src/original_words/`、契约、`Plan.md`、`requirement.md`。
- 未提交真实聊天记录、数据库、向量、模型权重、含个人内容的截图。

## 9. 未完成 / 风险

- 中文 query → C++ 代码检索仍弱（cross-encoder 也救不回）。
- 表格类截图 OCR 文本碎片化，需要版面重建或 VLM。
- 128 张无文字图片需要 VLM 描述。
- 349 张微信图片无本地缓存。
- 评测样本小（15/15/10），结论不代表统计显著性。
- 无 PySide6、无加密存储、无 `src/original_words/` 契约。

## 10. 下一步

1. VLM 描述覆盖无文字图片与表格。
2. 将精排、内容哈希、图片 caption 契约评审后并入 B-01。
3. 跨源 `links`（微信附件 ↔ 本地文件，basename 匹配率 88%）。
4. 代码文件专用索引（注释/标识符）。
5. 增量导入自动化（监听导出目录）。

## 11. 复现

```bash
cd engine
pip install -e ".[dev]"
python examples/make_demo.py
aimem --db demo.db index examples/corpus --embed hash
aimem --db demo.db search "设备采购方案" --embed hash
pytest -q
```

真实数据基准见 `engine/examples/README.md`（路径需按本机修改）。
