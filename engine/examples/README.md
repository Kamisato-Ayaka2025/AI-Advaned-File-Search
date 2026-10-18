# 基准脚本

这些脚本用于本机真实数据评测，**不包含数据**。路径均为占位符（`C:\Users\user\...`），运行前请改成你的环境。

## 环境变量

| 变量 | 用途 |
|---|---|
| `AIMEM_HOME` | 数据/数据库目录，默认 `C:\Users\user\aimem-test` |
| `AIMEM_DB` | 数据库路径 |
| `AIMEM_STORE` | 向量目录 |
| `AIMEM_EMBED` | embedder spec，如 `st:BAAI/bge-small-zh-v1.5` |
| `AIMEM_RERANK` | reranker spec，如 `ce:C:\...\bge-reranker-v2-m3` |
| `AIMEM_RERANK_WEIGHT` | 精排融合权重，默认 0.75 |
| `AIMEM_CHARS` | 重嵌截断字符数，默认 256 |
| `AIMEM_DTYPE` | `float16` / `bfloat16` / `float32` |

## 脚本

| 脚本 | 用途 |
|---|---|
| `make_demo.py` | 生成合成演示语料 |
| `build_real_index.py` | 索引真实目录（Windows + CUDA） |
| `eval_real.py` | 分层评测（L1/L2） |
| `reembed.py` | 换模型重嵌（可断点续跑） |
| `reranker_probe.py` | 精排模型冒烟测试 |
| `wx_ocr_caption.py` | 图片 OCR + Markdown caption 注入 |
| `wx_image_eval.py` | 图片独有词隔离评测 |
| `gpu_check.py` | CUDA 可用性检查 |
| `gpu_embed_bench.py` | 嵌入吞吐基准 |

## 数据流

```
原始目录 ──index──> SQLite(FTS5) + vectors
聊天 Markdown ──import-markdown──> 同一 SQLite/向量
图片 ──OCR──> Markdown caption ──import-markdown──> 同一 Unit
```

## 注意

- 所有脚本只读原始数据；数据库/向量写入 `AIMEM_HOME`。
- 不要把这些脚本当作产品入口（见仓库 `AGENTS.md`）。
- 真实聊天记录、图片、数据库不得提交。
