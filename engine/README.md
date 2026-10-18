# aimem engine（研究参考实现）

> 独立参考实现，**不属于** `src/original_words/` 产品主线。
> 用于验证 B 线检索路线、跨源可行性，并沉淀可复用的评测与工程结论。

## 它是什么

一个端到端的本地检索原型：

- **三路召回**：Everything（文件名/路径）+ SQLite FTS5（正文）+ 向量（语义）
- **统一抽象**：`file` / `chunk` / `message` 共用一张表、一套索引、一套融合
- **RRF 融合 + cross-encoder 精排**（`bge-reranker-v2-m3`）
- **增量更新**：按内容哈希只重嵌变化的单元
- **CLI + 本地 Web UI**（`aimem serve`）
- **基准脚本**：分层评测、模型 A/B、精排 A/B、图片 OCR

## 与 B-01 的关系

| | B-01 `src/original_words/retrieval/` | 本原型 `engine/` |
|---|---|---|
| 定位 | 产品检索模块 | 端到端参考实现 |
| FTS + 向量 + RRF | ✅ | ✅ |
| 分块 / 评测 / 契约 | ✅ | 简化版 |
| Everything 词法通路 | — | ✅ |
| cross-encoder 精排 | — | ✅ |
| 文件 / 微信 / QQ 统一 Unit | — | ✅ |
| 图片 OCR caption | — | ✅（研究） |
| Web UI | — | ✅ |

**建议**：精排、内容哈希、图片 caption 契约经评审后并入 B-01；Everything 与 OCR 属于研究结论，不自动进入当前产品范围（见 `Plan.md` 的排除项）。

## 安装

```bash
cd engine
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
# 真实向量（可选）
.venv/bin/pip install -e ".[embed]"
```

## 快速开始（合成数据）

```bash
python examples/make_demo.py
aimem --db demo.db index examples/corpus --embed hash
aimem --db demo.db search "设备采购方案" --embed hash
```

## 真实数据基准（路径需按本机修改）

```bash
# 1) 建索引（Windows + CUDA 示例）
python examples/build_real_index.py

# 2) 分层评测
python examples/eval_real.py

# 3) 重嵌（换模型，不重新解析）
python examples/reembed.py

# 4) 精排探针
python examples/reranker_probe.py
```

## Web 演示

```bash
aimem --db demo.db serve --device cuda \
  --rerank ce:/path/to/bge-reranker-v2-m3
# http://127.0.0.1:8765
```

## 关键结果（详见 `docs/evidence/aimem-engine/`）

| 项 | 结果 |
|---|---|
| 真实文件索引 | 68,822 文件 → 111,381 单元 |
| L1 文件名/片段 | Recall@10 1.000 |
| L2 纯语义 | Recall@10 0.900，MRR 0.760 → **0.900**（精排后） |
| 模型 A/B | bge-small-zh 与 Qwen3-0.6B 无实质差异 |
| 微信图片 | 505 张解码，377 张 OCR 出文字（75%） |
| 图片隔离测试 | OCR 后 12/12，OCR 前 0/12 |
| 测试 | 29 条 |

## 隐私

本目录**不包含**真实聊天记录、运行数据库、向量文件、模型权重或含个人内容的截图。基准脚本中的路径均为占位符，运行时需指向本机数据。

## 限制

- 单机评测，样本量小（15/15/10 条查询），结论用于方向判断，不是统计显著性证明。
- 中文 query → C++ 代码、表格类图片 OCR 仍是短板。
- Everything 后端仅 Windows；Linux/WSL 使用本地扫描。
- 没有实现 `src/original_words/` 的契约、加密存储、PySide6 UI。
