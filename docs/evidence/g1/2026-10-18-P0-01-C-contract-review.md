# P0-01 / C：共享契约 0.2.0-draft 评审记录

- 日期：2026-10-18。
- 评审人：C / @Zhong-Yufeng（低等级 Agent，桌面与构建执行线）。
- 被评审对象：PR #2 `feat(P0-01): complete A-side DTO and service contracts`，分支 `codex/p0-a-message-contract`，HEAD `a33399451836a52cbba1d49950963836e91ac1e5`。
- 抓取时 `main`：`bc62161a055038252580d472be84b1f3c9e965fc`；A 分支自称合入点 `5f6dbf6`。
- 输入：`src/original_words/contracts/*`（10 个 Python 模块 + README）、`tests/contracts/*`（5 个文件）、`tests/fixtures/contracts/v0_2.json`、`docs/handoffs/A.md`、`docs/evidence/g1/2026-10-18-P0-01-A-contracts.md`。
- 结论：**方向可接受，C 侧可消费；但按当前形态不能冻结 v1。5 项阻塞 + 10 项建议见下。**
- 本记录不构成 G1/G5 通过、真实数据许可、加密或网络拦截证据。

## 1. 实测环境与命令

| 项目 | 实测 |
|---|---|
| 主机 | 当前 Windows 开发机（非干净安装） |
| Python | 3.10.11（系统）、3.13.1（系统）、.venv-ais 为 3.10.11 + PySide6 6.12.0 + pytest 9.1.1 + ruff 0.17.1 |
| Python 3.11 | **本机不存在**；只做了 A 的语法检查复跑，没有 3.11 运行证据 |
| 网络/数据 | 仅合成样例；无 API 请求、无真实聊天库、无客户端进程 |

抓取与运行方式（评审沙箱 `ais-src/c-p0-review`，内容等于 A 分支快照）：

```powershell
python .tmp\ais_c\fetch_branch.py codex/p0-a-message-contract .tmp\ais_c\a-contract
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests/contracts -q          # A 的 52 项
python -m pytest tests/integration -q                       # C 的 31 项消费测试
```

实测结果：

| 检查 | 结果 |
|---|---|
| A 侧 52 项（Python 3.10.11） | `Ran 52 tests in 0.270s` OK |
| A 侧 52 项（Python 3.13.1） | `Ran 52 tests in 0.265s` OK |
| A 侧标准库隔离检查（`-I -S check_environment.py`） | 15 文件 3.11 语法通过；socket 拦截下导入通过 |
| C 侧消费测试 31 项（`tests/integration/test_contract_consumption.py`） | `31 passed` |
| Ruff（`E,F,I,UP,B`，line-length 100）与 `ruff format --check` | 全部通过（仅针对 C 新增测试，未对 A 的模块施加新规则） |
| C 工作副本全套（main + C-01 现状） | `49 passed, 1 skipped`（新增测试在 contracts 未合入前整文件跳过） |

Python 3.11 结论：**未实测**。A 的语法检查结论可以复现，但不能替代 3.11 运行；候选环境由 C 在 P0-01 建立，届时补 3.11 的实测记录。

## 2. 阻塞项（冻 v1 前必须处理）

### B1 契约里没有会话/来源列表接口，C-01 的会话列表与时间线无法只靠契约实现

`Repository` 只有 `import_batch/get_messages/get_context/get_chunks`；契约中也没有 `Chat`/会话摘要 DTO。C 的窗口骨架需要：会话名、会话类型、所属来源、参与人、消息条数、时间范围、覆盖范围、以及"按时间线看某会话"的区间读取。这些都无法从 `Message` 单独拼出（`Message` 只有 `chat_id`，没有会话显示名；逐条扫描全库枚举会话违反"UI 不直接查库"）。

建议 A 增：

```python
@dataclass(frozen=True, slots=True, repr=False)
class ChatSummary(Contract):
    source_id: str
    chat_id: str
    chat_type: Literal["group", "private", "unknown"]
    display_name: str | None
    participants: tuple[str, ...]
    message_count: int | None
    first_at: str | None
    last_at: str | None
    coverage: Coverage

class Repository(Protocol):
    def list_chats(self, *, snapshot: SnapshotRef,
                   source_ids: tuple[str, ...]) -> tuple[ChatSummary, ...]: ...
    def get_message_range(self, chat_id: str, *, snapshot: SnapshotRef,
                          source_ids: tuple[str, ...], start: str | None,
                          end: str | None, limit: int = 200) -> tuple[Message, ...]: ...
```

`message_count` 允许 `None`（未知不填 0），与导入计数口径一致。

### B2 `Answer` 没有 `request_id`，也没有追问文案，迟到结果与 REQ-023 都无法在 UI 侧闭合

- Plan §6 要求"新请求使旧请求失效，迟到 token/错误/结果按 ID 丢弃"。`AnswerService.generate` 只返回 `Answer`，其中没有 `request_id`；C 只能靠外部约定配对，无法在 DTO 层判定迟到结果。
- REQ-023 需要一次追问文案，`Answer.status="ambiguous"` 却没有承载追问文本的字段（`InvestigationDecision.clarification` 属于 A/B 内部调度，不回到 UI）。

建议：`Answer` 增 `request_id: str` 与 `clarification: str | None`（`status=="ambiguous"` 时必填），或让 `generate` 返回 `SearchOutcome`（已有 `request_id`）并保持 `Answer` 作内层结构。

### B3 `ImportReport` 只有计数，没有逐条错误明细

REQ-011/A-01 要求"字段错误报告"，Plan §8.2 要求覆盖缺字段、坏编码、未知类型。当前 C 只能显示"拒收 90 条"，无法告诉用户哪一行、为什么失败。

建议：增独立 DTO（限条数、不含原文全文、字段值脱敏）：

```python
@dataclass(frozen=True, slots=True, repr=False)
class ImportIssue(Contract):
    code: Literal["missing_field", "bad_encoding", "unknown_type", "bad_time", "bad_quote"]
    record_ref: str          # 来源内的行号/键，不是原文
    field: str | None
    detail: str              # 已脱敏，禁止原文/密钥

# ImportReport 增：
issues: tuple[ImportIssue, ...] = ()
issues_truncated: bool = False
```

不要求与 `rejected_count` 等长（只保留前 N 条 + 截断标志），维持计数守恒不变。

### B4 日期级/未知时间在有界过滤中被静默排除，UI 无法披露

`Message.matches_time_range` 对 `timestamp_precision in {"day","unknown"}` 在任一有界条件下返回 `False`，README 也声明"保守排除、策略待 B/C 评审"。C 认同"不伪造秒级时间"，但当前 `SearchResult`/`Coverage` 没有任何计数或标志，C 无法在结果页写"另有 N 条仅日期级数据未纳入时间过滤"。REQ-020/019 的覆盖披露要求会被违反。

建议（二选一或同时）：

- `SearchResult` 增 `excluded_unknown_time_count: int | None`、`excluded_date_only_count: int | None`；或
- `Coverage` 增 `date_only_count: int | None` 与 `date_only_policy: Literal["excluded","included_whole_day"]`。

同时请把日期区间策略定稿（A 出方案、B/C 各自给结论），避免 UI 文案与检索行为长期不一致。

### B5 `SendPlan` 不绑定证据版本，预览与发送之间存在数据版本漂移

`preview_text` 是实际发送字节，`payload_hash` 只覆盖这段字节；`fingerprint` 覆盖 plan 自身字段（含 `selected_message_ids`）。但 `prepare_send(spec, evidence, ...)` 与 `generate(plan, grant, ..., evidence=...)` 是**两次**传入 evidence，plan 里没有任何快照/证据摘要。于是"预览时看到的是 revision A 的原文，发送时用的是 revision B 的原文"在 DTO 层不可检测，`consume` 只校验 fingerprint 也拦不住。

这属于同意完整性问题（REQ-025/026），建议：`SendPlan` 增 `snapshot: SnapshotRef`（或 `evidence_digest: str`，对 evidence.message_ids + 字符区间 + 实际外发文本做摘要），`generate` 校验传入 evidence 与 plan 绑定值一致，不一致抛 `CONSENT_REQUIRED`/`REVISION_MISMATCH` 并要求重新预览。

## 3. 建议项（不阻塞 v1，请在 README 决策段记录）

| ID | 问题 | 建议 |
|---|---|---|
| S1 | `TaskEvent` 无序号/时间，C 无法排序乱序的跨线程信号；契约里也没有取消任务的接口（Plan §6 要求长任务可取消） | 增 `TaskCoordinator` Protocol（`submit/subscribe/cancel(task_id)`）或在 README 明确由 C 的组装层拥有；`TaskEvent` 建议加 `seq: int` |
| S2 | `ErrorCode` 现有 12 值比 C 的过渡 DTO 多 `UNSUPPORTED_OPERATION/REVISION_MISMATCH/INTERNAL_ERROR` | C 已把 12 值全部纳入 UI 文案表，并加了"新增错误码即失败"的守卫测试；A 今后加码请在同一 PR 通知 C |
| S3 | `CleanupItem` 资源枚举无 `temp`/WAL 单独项，REQ-027 的"WAL/临时文件"无法逐项证明 | 增 `temp`，或在 README 声明 `database`/`index` 覆盖 WAL 且在 G5 证据中单独验证 |
| S4 | `ExportReceipt` 只有 `bytes_written`，无法证明导出文件可读/未被截断 | 可选增 `sha256: str`（不要求强制） |
| S5 | `mode="partial"` 时 `selected_message_ids` 允许为空；`mode="full"` 也不要求覆盖 evidence | 增不变量：`partial/keywords → selected 非空`，`full → set(evidence.message_ids) ⊆ set(selected)` |
| S6 | `ConsentGrant` 只有 `grant_id/fingerprint/expires_at`，UI 想展示"这次授权了什么范围"必须自己保存 plan | 保持现状可接受（README 已声明），或增 `scope_summary: str` |
| S7 | `Repository.get_messages` 静默丢弃缺失 ID，UI 分不清"消息已删"与"数据不一致" | 返回体增 `missing_ids`，或规定抛 `REVISION_MISMATCH`；C 侧已加守卫函数 `require_all_messages` |
| S8 | `EvidenceBundle` 要求 resolved edge 的 `to_id in message_ids`，引用目标不在候选集时只能标 unresolved，会丢"这条在回复哪条"的信息 | 允许目标在 bundle 外的 resolved edge，另加 `external_target: bool` |
| S9 | `SearchBudget` 允许 0 值（例如 `max_rounds=0`），误配会静默关闭补查 | 关键项设下限 1，或 README 写明 0 的语义 |
| S10 | `SearchHit` 不含文本，首屏必须批量 `get_messages`；若 UI 逐条取会 N+1 拖慢 ≤1s 目标 | README 明确"首屏只允许一次批量取文本" |

## 4. 流程与基线问题

- **PR 基线过期**：本次抓取的 `main`（`bc62161a`）比 A 分支多 `docs/evidence/tier-b/validate_format.py`，并已更新 `docs/evidence/tier-b/2026-10-18-wechat4-decode-pipeline.md`、`ntqq_export_md.py`、`wechat4_export_md.py`（逐文件 SHA-256 比对）。按 Plan §5.1.4/§5.1.7，合入前必须更新 main 并重跑检查，不能沿用旧基线的绿色结果。
- **C 侧未做过的验证**：本评审没有运行 SQLCipher/FTS5/WAL、模型、UI、打包与真实网络拦截；这些仍属 P0-01 的 C 任务。
- **自批与冻结**：C 的结论是"可消费但不冻 v1"，不是批准合并。B 的检索/LLM 侧评审仍缺失，v1 冻结需 A 汇总三方结论。

## 5. C 侧本次实际交付

1. `tests/integration/test_contract_consumption.py`（31 项）：以 UI/组装视角消费契约，覆盖导入报告、任务/错误状态、引用渲染与字符区间、发送预览与授权失效、清理结果，另含 7 个 `test_gap_*` 缺口探针（B1–B5、S1、S3、S7 的可执行记录）。
2. 本记录与 `docs/handoffs/C.md`。
3. 未改动 A 的 `src/original_words/contracts/`、`tests/contracts/`、`tests/fixtures/`（评审而非代改）。
