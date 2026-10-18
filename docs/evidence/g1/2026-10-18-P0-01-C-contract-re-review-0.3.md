# P0-01 / C：共享契约 0.3.0-draft 二次评审（针对 A 的评审修订）

- 日期：2026-10-18。
- 评审人：C / @Zhong-Yufeng（桌面、应用组装、依赖与集成）。
- 被评审对象：PR #2 分支 `codex/p0-a-message-contract`，**HEAD 由 `a3339945` 更新为 `06b9d516`**；契约 0.2.0-draft → 0.3.0-draft。
- A 的修复说明：`docs/evidence/g1/2026-10-18-P0-01-A-C-review-response.md`（修复提交 `15a1820`）。
- 基线核对：本分支的 `Plan.md` / `README.md` / `requirement.md` / `AGENTS.md` / `docs/evidence/tier-b/*` 与抓取时的 `main`（`bc62161a`）逐文件 SHA-256 一致 → **上一轮指出的基线过期已解决**。
- 结论：**B1–B5 已实质修复，C 侧可消费**（C 的 0.3 消费测试 37 项全绿）；仍有 3 项小缺口（F1–F3，1 项与安全相邻、2 项影响 UI 表达）。C 对 B4 时间策略给出正式结论并附条件。**建议 A 处理 F1–F3 后冻结 v1；不因本轮通过而视为 G1/G5 或人工验收。**

## 1. 复核方式与环境

独立复核，不采信 A 的自测结论：

1. 逐文件读 0.3 的 `contracts/`（新增 `catalog.py`）、`tests/contracts/test_c_review.py`、`v0_3.json`、README 的迁移段与 S1–S10 处置表。
2. 在本地沙箱跑 A 的 73 项（Python 3.10.11 与 3.13.1），并跑 A 的标准库隔离检查。
3. 把自己的 31 项消费测试按迁移说明改写成 0.3 版：原 7 个 `test_gap_*` 缺口探针全部改为**正向验收**，另加正向用例与 3 个新探针，共 37 项。
4. 对可疑不变量写最小复现脚本（`stop_reason` 与状态绑定、`TaskEvent.seq` 默认值）。

| 检查 | 实测 |
|---|---|
| A 的 73 项（Python 3.10.11） | `Ran 73 tests in 0.448s` OK |
| A 的 73 项（Python 3.13.1） | `Ran 73 tests in 0.493s` OK |
| A 的 `-I -S check_environment.py` | 17 文件 3.11 语法通过；socket 拦截下导入通过 |
| C 的 0.3 消费测试（37 项） | `37 passed` |
| C 的测试 ruff（`E,F,I,UP,B`，line-length 100）+ `format --check` | 通过 |
| Python 3.11 实际运行 | **仍无环境，未实测**（只有 A 的语法解析结论） |

命令（沙箱 `ais-src/c-p0-review2`，内容 = `06b9d516` 快照）：

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests/contracts -q      # A 的 73 项
python -m pytest tests/integration -q                   # C 的 37 项
```

## 2. B1–B5 逐条复核

| 编号 | A 声称 | C 独立复核 | C 侧证据（测试名） |
|---|---|---|---|
| B1 会话/来源列表 | 新增 `SourceSummary/ChatSummary/ChatPage/MessagePage` + `Repository.list_sources/list_chats/get_message_range` | **成立**。复合身份 `(source_id, chat_id)`、`message_count=None`、200 条上限、`next_cursor=None` 为末页、空页不得带 cursor、时间线跨源/跨会话被拒、有界范围与 `time_filter.applied` 强制一致，均已验证 | `test_b1_source_and_chat_list_render_unknown_counts`、`test_b1_chat_page_rejects_duplicates_and_dangling_cursor`、`test_b1_message_page_bounded_and_unbounded`、`test_b1_timeline_cross_chat_and_unknown_page`、`test_b1_repository_protocol_surface` |
| B2 请求 ID / 追问 | `Answer.request_id` 必填关键字；`ambiguous` 必须带 `clarification`；`SearchOutcome` 内外一致；`validate_generated_answer` 拒旧请求 | **成立**。实测 `Answer("not_found")` 抛 `TypeError`（不能用默认值静默通过）；非 `ambiguous` 带追问被拒；迟到请求抛 `REVISION_MISMATCH` | `test_b2_request_id_survives_and_stale_answer_rejected`、`test_b2_ambiguous_answer_carries_single_clarification` |
| B3 导入问题明细 | `ImportIssue` + `issues`/`issues_truncated`，≤100 条 | **成立**。`record_ref` 只接受 `record:数字`、`field` 只接受 ASCII 标识符、`detail` 必须是固定模板（写"原始内容泄露"即被拒），样例数与 `rejected_count` 独立 | `test_b3_issue_rows_are_redacted_and_truncation_is_visible`、`test_b3_issue_rejects_raw_values_and_oversized_samples` |
| B4 时间披露 | 策略 `exclude_imprecise_v1`、`TimeFilterInfo`、参考过滤函数、`validate_search_result` | **成立（附 C 的正式结论，见第 4 节）**。有界排除日期级/未知时间、无界保留；计数 None ≠ 0；`validate_search_result` 会拒绝缺披露的结果 | `test_b4_time_policy_reference_helper_and_disclosure`、`test_b4_search_result_must_disclose_time_filter` |
| B5 证据绑定 | `SendPlan.snapshot`/`evidence_digest` 必填，`fingerprint` 覆盖，`validate_evidence` 校验 | **成立**。版本变化抛 `REVISION_MISMATCH`、同版本成员/区间变化抛 `CONSENT_REQUIRED`、空证据或 `mode=full` 不覆盖全集均拒发；重绑摘要后旧 grant 不再匹配 | `test_b5_send_preview_is_exact_body_and_binds_evidence`、`test_b5_changed_evidence_forces_new_preview`、`test_b5_selection_and_scope_rules`、`test_b5_query_parse_send_carries_no_chat_evidence`、`test_editing_preview_invalidates_grant_and_ui_must_reconfirm` |

S1–S10 处置复核：S1（`seq` + `TaskControl.cancel`）、S4（`ExportReceipt.sha256`）、S6（UI 保留 plan）、S7（`require_all_messages` 只报 code、不含 ID）、S8（`external_target` 与包内成员一致性）、S3（七类资源 + 文档化 WAL/临时文件归并）、S9（0 表示显式禁用）、S10（首屏一次批量取文本）**均按 C 的建议落地或明确记录职责**；S2 未破坏 C 的错误码文案表（12 值不变）；S5 的 `query_parse` 例外已给出可执行约束。

## 3. 仍未闭合的缺口（新发现，按严重度）

### F1（建议修，安全相邻）`stop_reason="ambiguous"` 与 `answer.status` 未绑定

实测可构造 `SearchOutcome(stop_reason="ambiguous", answer.status="answered")`，两者同时成立。UI 按 `status` 渲染"已回答"、按 `stop_reason` 渲染"需要追问"，会出现互斥提示；A 已要求 `ambiguous` 状态必须带 `clarification`，但该约束没有和停止原因对齐。建议增不变量：`(stop_reason == "ambiguous") == (answer.status == "ambiguous")`。探针：`test_gap_stop_reason_ambiguous_not_tied_to_answer_status`。

### F2（建议修，进度显示）`TaskEvent.seq` 兼容默认 0 会让"忘记赋值"变成"丢事件"

README 约定"每个 `task_id` 内从 0 单调递增，UI 丢弃旧序号"。但 `seq` 有兼容默认 0：生产者一旦漏赋值，同一任务的所有事件 `seq` 都是 0，C 按 `seq <= last` 丢弃，进度会停在第一个事件（我用 `ProgressTracker` 复现）。契约层无法校验单调性，因此建议把 `seq` 改为必填关键字字段（仍在草案期，成本低于上线后排查），或在 README 明确"C 必须先做 `seq` 严格递增校验，全 0 视为生产者缺陷并在导入报告/日志中标注"。探针：`test_gap_task_event_seq_default_zero_hides_forgotten_seq`。

### F3（建议修，REQ-022 表达力）`SearchFilters` 仍无 `chat_types`

C 的过滤面板需要"只看群聊/私聊"，B 的 0.2 评审也提出同一条；当前只能用 `chat_ids` 逐个列举，无法表达会话类型过滤，且 UI 无法把"群聊"翻译成 `chat_ids`（那等于 C 自行扫描会话列表拼过滤器，违反"UI 不查库"）。建议 `SearchFilters` 增 `chat_types: tuple[Literal["group","private","unknown"], ...] = ()`。探针：`test_gap_search_filters_have_no_chat_types`。

（同一处 B 还提出 `message_types` 缺 `link/voice/emoji`。C 的结果视图目前只按文本/图片/文件分类，因此该项对 C 不阻塞；请 A 在处理 F3 时一并给 B 一个降级规则或扩枚举的决定。）

## 4. C 对 B4 时间策略的正式结论

**接受 `exclude_imprecise_v1` 作为 v1 策略**，条件如下（均已可执行）

1. 有界查询必须返回 `SearchResult.time_filter` / `MessagePage.time_filter`；C 在结果页与时间线页显示"排除了 N 条未知时间、M 条仅日期级消息"，并在无界查询时不显示该提示（`Test_b4_*`）。
2. 计数为 `None` 时 UI 显示"排除数量尚未统计"，**不得显示 0**。
3. UI 必须提供"清除时间条件"入口，避免用户以为数据缺失。
4. 计数口径必须是"授权来源 + 其余硬过滤后的完整集合"，不是当前页/top-k；这一条 DTO 无法证明，列入 G3 的仓储验收项（真实仓储要按此口径实现，C 在联调时抽查）。
5. 不把日期级记录当"范围内命中"，也不在时间线里为其伪造时刻。

若 A 后续改用"整日区间包含"策略，需要新的 `date_only_policy` 值并同步 C 的文案与测试；本轮不需要。

## 5. 冻结 v1 的剩余条件

1. A 处理 F1–F3（或明确书面接受并记录风险）。
2. B 的 0.3 复审结论（B 的 `review/B-contracts-v0.2` 针对的是 0.2，需在 0.3 上重跑）。
3. Python 3.11 实机运行（C 在 P0-01 建立候选环境后补测）。
4. 契约之外的实现与证据仍缺：仓储、协调器、授权服务、SQLCipher/FTS5/WAL、UI、打包——本轮不因契约通过而视为 G1/G5。

## 6. C 侧本轮交付

- `tests/integration/test_contract_consumption.py` 更新为 0.3 版：37 项，含 34 项正向验收 + 3 项缺口探针（F1/F2/F3）；未改动 A 的 `contracts/`、`tests/contracts/`、`tests/fixtures/`。
- 本记录；`docs/handoffs/C.md` 同步更新。

C 的身份是评审与消费方，不是契约实现方；上述修复建议均由 A 决定是否采纳及其具体形态。
