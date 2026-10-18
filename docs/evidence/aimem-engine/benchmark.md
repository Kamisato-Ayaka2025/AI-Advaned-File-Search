# aimem engine 基准记录

> 单机、小样本评测，用于方向判断，不作为统计显著性证明。
> 数据为作者本机授权目录；仓库不包含数据、数据库或向量。

## 1. 环境

| 项 | 值 |
|---|---|
| OS | Windows 11 + WSL2 |
| GPU | RTX 5060 Laptop 8GB（sm_120） |
| Python | 3.13 |
| torch | 2.11.0+cu128 |
| Embedding | `BAAI/bge-small-zh-v1.5`（512 维） |
| Reranker | `BAAI/bge-reranker-v2-m3`（568M） |

## 2. 数据

| 来源 | 规模 |
|---|---:|
| 本地文件 | 68,822 文件 |
| 检索单元 | 111,381（42,559 正文分块） |
| 微信消息 | 19,159（53 会话） |
| QQ 消息 | 2,204 |

索引耗时 395s（PDF 解析占大头）；嵌入 111,381 条约 1–2 分钟（GPU）。

## 3. 分层评测

查询集：

- L1-exact：15 条，query = 文件名（去扩展名）。
- L1-partial：15 条，query = 文件名中截 4 个汉字。
- L2-semantic：10 条，query 为内容改写，不含文件名关键词。

指标：Recall@10、MRR。

### 3.1 无精排

| 层 | n | Recall@10 | MRR |
|---|---:|---:|---:|
| L1-exact | 15 | 1.000 | 0.967 |
| L1-partial | 15 | 1.000 | 1.000 |
| L2-semantic | 10 | 0.900 | 0.760 |

延迟（40 条）：avg 85ms / p50 50ms / p95 369ms。

### 3.2 精排

Top-50 cross-encoder，权重网格：

| 配置 | L1-partial MRR | L2 MRR | 40 条耗时 |
|---|---:|---:|---:|
| 无精排 | 1.000 | 0.760 | 5.3s |
| w=0.45 | 0.967 | 0.820 | 18.5s |
| w=0.75 | 0.967 | 0.900 | 19.1s |
| w=0.75 + 标题命中跳过 | **1.000** | **0.900** | **10.2s** |

规则：查询词（≥4 字符）已出现在 Top-1 标题时跳过精排。

### 3.3 模型 A/B

同 111,381 单元、256 字符截断：

| 模型 | 参数量 | 重嵌耗时 | L1-exact MRR | L2 MRR |
|---|---:|---:|---:|---:|
| bge-small-zh-v1.5 | 24M | 87s | 0.967 | 0.760 |
| Qwen3-Embedding-0.6B | 596M | 687s | 0.933 | 0.770 |

结论：无实质差异；embedding 不是瓶颈。

## 4. 失败案例（抽象）

1. **代码文件**：中文 query「删除二叉搜索树节点找后继」→ C++ 文件，精排后仍未进前 10。cross-encoder 不是代码模型。
2. **同主题文档**：目标排第 2，第 1 是同一目录下同主题论文；属于 gold 标注过严。
3. **表格 OCR**：课表类截图的 OCR 文本块按检测顺序输出，词被拆开，整词查询无法命中。

## 5. 复现

```bash
cd engine
pip install -e ".[dev,embed,docs]"
python examples/build_real_index.py   # 修改 AIMEM_HOME / roots
python examples/eval_real.py          # 修改 AIMEM_HOME / gold
pytest -q
```

脚本路径均为占位符；不会自动读取真实数据。
