# ADR-002：aimem engine 作为研究参考，不进入产品主线

- 状态：Proposed
- 日期：2026-10-18
- 提出者：B（@YuanKunlin）
- 关联：`Plan.md` v1.5、`feat/B-01-hybrid-search`、Tier B 导出

## 背景

B-01 已在 `src/original_words/retrieval/` 实现 FTS5 + 向量 + RRF、分块、评测与测试，是产品检索模块的正式落点。

本轮另做了一个端到端参考实现 `engine/`，额外验证了：

- Everything 文件名/路径通路（Windows）
- cross-encoder 精排（bge-reranker-v2-m3）
- 文件 / 微信 / QQ 统一 `Unit` 与跨源检索
- 图片 OCR caption
- 内容哈希增量重嵌
- 本地 Web UI

`Plan.md` 明确排除 Everything、文件正文解析与 OCR；`AGENTS.md` 要求不把研究脚本当作产品入口，且真实数据模式未通过 G5。因此不能把 `engine/` 直接并入 `src/original_words/`。

## 决策

1. `engine/` 作为**独立研究参考实现**保留在仓库，不被 `src/original_words/` import，不作为产品入口。
2. 文档放入 `docs/evidence/aimem-engine/` 与 `docs/progress/`，明确标注研究属性。
3. 不修改 `requirement.md`、`Plan.md`、共享契约与 `src/original_words/`；`README.md` 只增加链接。
4. 可采纳项（精排、内容哈希、图片 caption 契约）由 A 评审后进入 B-01，而不是整体合并。
5. Everything 与 OCR 仅作为研究结论，不改变产品范围；真实数据仍受 G5 约束。

## 后果

**正面**

- 保留完整端到端证据与可复现基准，不阻塞 B-01 主线。
- 精排、增量哈希、图片 caption 契约可直接评审复用。
- 真实数据评测暴露了 FTS 执行计划、打分归一化、chunk 聚合等工程问题。

**负面**

- 检索逻辑与 B-01 有重复，存在两套实现。
- `engine/` 需要单独维护，可能与 B-01 契约漂移。
- OCR/Everything 与当前产品范围不一致，需持续标注边界。

**缓解**

- `engine/` 不承诺产品兼容；合并时以 B-01 为准。
- 文档中所有“可采纳项”均标注“需评审”。
- 不提交数据、模型、数据库与含个人内容的截图。

## 备选方案

| 方案 | 结论 |
|---|---|
| 直接并入 `src/original_words/retrieval/` | 与 B-01 冲突大，且超出产品范围 |
| 仅本地保留、不提交 | 丢失证据，违背本轮目标 |
| 只提交文档、不提交代码 | 无法复现基准 |

## 后续

- A 评审精排与内容哈希的接入方式。
- 若产品范围调整（允许 Everything/OCR），再单独提案。
- `engine/` 在 B-01 覆盖对应能力后，可降级为纯文档或归档。
