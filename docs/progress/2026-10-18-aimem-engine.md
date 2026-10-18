# 进度日志：aimem engine（2026-10-18）

> 本文件记录从路线分析到可演示原型的完整过程，便于复盘与交接。

## 阶段 0：环境与路线

| 时间 | 动作 | 结果 |
|---|---|---|
| 上午 | 检查仓库、硬件、网络 | 仓库为空；Windows RTX 5060 8GB；WSL 无 GPU 直通；HF/GitHub 直连受限 |
| 上午 | 路线分析：专用模型后训练 vs Agent+API | 结论：两者都不做，选「本地检索栈 + 薄查询层」 |
| 上午 | 明确复用边界 | `Unit` 抽象；引擎可复用，schema/排序不能照搬 |

## 阶段 1：检索核心

| 时间 | 动作 | 结果 |
|---|---|---|
| 中午 | 脚手架 | `src/aimem`、pyproject、venv |
| 中午 | SQLite schema | `units` + FTS5（CJK 单字分词）+ 向量 |
| 中午 | Everything 客户端 + 本地扫描 | HTTP JSON 解析、mock 单测 |
| 中午 | 文本抽取/分块 | txt/md/csv/pdf/docx/xlsx（可选依赖） |
| 下午 | RRF + 规则 planner + 启发式精排 | 端到端可跑 |
| 下午 | JSONL / Markdown 导入 | 微信/QQ 格式兼容 |
| 下午 | 测试 | 29 条通过 |

## 阶段 2：真实数据

| 时间 | 动作 | 结果 |
|---|---|---|
| 下午 | Windows 原生 + CUDA 验证 | torch 2.11 cu128，嵌入 5080 docs/s |
| 下午 | C/D 盘索引 | 68,822 文件 / 111,381 单元 / 395s |
| 下午 | 分层评测 | L1 1.000；L2 0.900 / MRR 0.760 |
| 下午 | 发现 FTS 执行计划 bug | 单条 212s → 0.28s |
| 下午 | 模型 A/B | Qwen3-0.6B 无实质提升 |
| 下午 | 精排 A/B | L2 MRR 0.760 → 0.900，L1 无损 |
| 下午 | 微信记录 | 19,159 条；附件 ↔ 本地文件匹配 88% |
| 下午 | 图片 OCR | 505 张解码，377 有文字；隔离测试 12/12 vs 0/12 |
| 下午 | Web UI | 132,744 单元；查询约 250–500ms |
| 下午 | 内容哈希增量 | 文本变化自动重嵌 |

## 关键决策

1. **不做「带 AI 的 Everything」**，做个人信息记忆检索。
2. **embedding 不是瓶颈**：24M 中文模型够用。
3. **精排是当前最高 ROI**：+0.14 L2 MRR。
4. **图片 OCR 可行**，但表格与无文字图片需要 VLM。
5. **增量更新不训练**：只嵌入新增/变化单元。

## 未完成

- VLM 描述（128 张无文字图 + 表格）。
- 跨源 `links` 表与结果卡片。
- 代码文件专用索引。
- 产品主线 `src/original_words/` 集成（精排、内容哈希、caption 契约）。

## 产物索引

- 代码：`engine/`
- 里程碑：`docs/evidence/aimem-engine/2026-10-18-milestone.md`
- 基准：`docs/evidence/aimem-engine/benchmark.md`
- 图片：`docs/evidence/aimem-engine/wechat-images.md`
- 决策：`docs/decisions/ADR-002-aimem-engine.md`
