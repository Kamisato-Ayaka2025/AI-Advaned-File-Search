# P0-01 / A：回应 C 的契约评审

日期：2026-10-18。执行者：A / @Kamisato-Ayaka2025 的开发代理。
输入：C 在 PR #2 对 a3339945 的评审，以及 PR #3 中的独立评审记录和消费测试（只读）。
最新 main 基线：bc62161a055038252580d472be84b1f3c9e965fc，已合入当前分支。
修复提交：15a1820b8f513f7e7756722f1afe4a5fdd64312b。契约：0.3.0-draft。
状态：A 已修复并自测，重新交 C 评审；不是 C 已确认关闭阻塞，更不是 G1/G5 通过。

- 产品 PR：https://github.com/Kamisato-Ayaka2025/AI-Advaned-File-Search/pull/2
- C 评审 PR：https://github.com/Kamisato-Ayaka2025/AI-Advaned-File-Search/pull/3
- 调用与迁移规范：src/original_words/contracts/README.md
- 新增回归：tests/contracts/test_c_review.py（21 项）
- 当前合成样例：tests/fixtures/contracts/v0_3.json（49 对象）；v0_2 保留为历史。

## B1–B5 修复对照

| 编号 | 实现 | 证据 / C 复审重点 |
|---|---|---|
| B1 | 新增 SourceSummary/ChatSummary/ChatPage/MessagePage；Repository.list_sources/list_chats/get_message_range | 来源+会话复合身份、未知计数、200 条页上限、next_cursor、范围读取/披露。CatalogReviewTests；C 检查会话列表和时间线是否能消费。仓储实现仍在后续任务。 |
| B2 | Answer 必填关键字 request_id；ambiguous 必须有 clarification；SearchOutcome 内外请求 ID 一致；validate_generated_answer 拒绝旧请求 | AnswerReviewTests 验证 JSON 往返、追问文案和迟到结果。C 仍按当前活动 request_id 丢弃旧回复；一次追问限额由 A 协调器实施。 |
| B3 | ImportIssue + issues/ issues_truncated，最多 100 条 | ImportReviewTests 验证拒收数量与样例数量独立；record_ref 只用 record:序号，detail 固定模板，不嵌原文/路径/字段值。 |
| B4 | 确定 A 提案 exclude_imprecise_v1；新增 TimeFilterInfo 和参考过滤函数、validate_search_result | 有界排除 day/unknown，无界保留；披露两个排除计数，None 不能当 0。按授权和其余硬过滤后的完整集合统计，不是当前页/top-k 计数。TimeReviewTests 验证边界与强制披露。请 B/C 对此明确方案分别给结论。 |
| B5 | SendPlan 必填 snapshot + evidence_digest；fingerprint 覆盖二者；generate 和 consume(evidence=...) 前校验绑定 | ConsentReviewTests 验证数据/索引版本变化、同版本区间/成员变化均拒发且不消耗原授权；重绑证据也不能复用旧 grant。实际服务仍需实现原子授权和 revision 不变即原文不变。 |

## S1–S10 处置

| 编号 | 结果 |
|---|---|
| S1 | 新增 TaskEvent.seq 和 TaskControl.cancel；A 协调器负责事件序号/协作取消，C 调用并丢弃迟到序号。未实现运行时队列。 |
| S2 | ErrorCode 原 12 值保持不变，不破坏 C 文案表。 |
| S3 | 不增加清理枚举；明确 database 覆盖 WAL/SHM/journal/临时文件，index 与其他资源负责自身临时文件。任一子项失败聚合为 failed；G5 另逐路径验证。 |
| S4 | ExportReceipt.sha256 可选并校验格式；实际导出计算，不能替代可读性检查。 |
| S5 | 非 query_parse 的 partial/keywords/summary 不准空选择；full 覆盖完整绑定证据。纯查询解析不要求聊天证据，但仍须单独预览授权且证据包为空。 |
| S6 | UI 保留 grant 对应原 SendPlan；不复制可能漂移的授权摘要。 |
| S7 | get_messages 明确全量/按请求顺序返回，否则 REVISION_MISMATCH；越权 PERMISSION_DENIED；增加 require_all_messages 后置校验。 |
| S8 | 新增 external_target：已知引用目标可在 bundle 外，不误标 unresolved；不能直接引用外部目标，扩展前重核权限和版本。 |
| S9 | README 定义 0 是显式禁用对应阶段/额度，协调器不可偷偷恢复默认值；机器截止仍必须大于 0。 |
| S10 | README 要求首屏去重 ID 后一次批量取原文，禁止 UI N+1。性能未实测。 |

## 复验

环境：Windows / 应用捆绑 Python 3.12.14；没有安装项目依赖或修改 C 的锁文件。
代码与测试均为合成内容，没有 API、真实聊天库或研究脚本执行。

```powershell
$env:PYTHONPATH = 'src'
& $ContractPython -m unittest discover -s tests/contracts -q
& $ContractPython -I -S tests/contracts/check_environment.py
git -c safe.directory=F:/Code/AI_Advanced_File_Search/private/worktrees/p0-a-message-contract diff --cached --check
```

实际结果：

```text
Ran 73 tests in 0.185s
OK
Python 3.11 grammar: 17 files passed (not runtime proof)
Isolated stdlib-only imports passed with socket access blocked
```

diff 检查通过。原 A 侧 52 项迁移到新契约后全部保留；本次新增 21 项，未删测或降低既有断言。

C 在 0.2 上报告的 31 项独立消费测试没有被 A 修改，也没有在 0.3 上被宣称通过。0.3 的新增必填安全字段与新增接口会使部分旧构造器/缺口断言不再适用。C 应按迁移说明在自己的分支更新测试后独立重跑，不能用 A 新回归替代。

## 兼容性与剩余门槛

- 0.3 的 Answer.request_id、SendPlan.snapshot/evidence_digest 是显式草案破坏性变更，避免给安全字段填默认值后继续静默运行。C 评审建议要求这些信息；本轮用户授权按评审修订。其余新增字段维持兼容默认。
- 不在 B/C 确认前冻结或合并。B 的检索/LLM 评审仍待完成。
- Python 3.11 真实运行、pytest/Ruff、模型、SQLCipher/WAL、UI、打包与 G5 安全验证仍缺，不把本轮契约回归当作这些门槛通过。
- C 的 S3/S6/S9/S10 通过明确契约职责处理，运行时实现和性能证据在后续工作包完成。
