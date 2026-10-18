# A 交接记录 — P0-01 / C 评审修订

日期：2026-10-18；负责人 A / @Kamisato-Ayaka2025。
分支：codex/p0-a-message-contract。
工作区：F:/Code/AI_Advanced_File_Search/private/worktrees/p0-a-message-contract。
PR：https://github.com/Kamisato-Ayaka2025/AI-Advaned-File-Search/pull/2
状态：0.3.0-draft 已修订，待 C 二次评审；B 评审仍缺；不冻结、不合并，G1/G5 未通过。

## 当前基线和提交

- 已合入 origin/main bc62161a055038252580d472be84b1f3c9e965fc，包含 C 指出的研究文件基线更新；未运行研究脚本。
- 修复实现：15a1820b8f513f7e7756722f1afe4a5fdd64312b。
- 本交接/评审回应另作文档提交；当前最终 HEAD 以 git log -1 和 PR 为准。
- 原工作区 docs/decoder-informed-plan 的 AGENTS.md 用户修改保留，未切分支、未覆盖。
- 本轮只编辑 A 的 contracts、tests/contracts、tests/fixtures 和自己的交接/证据；未改 C 的 tests/integration 或 B/C 实现。

## C 评审及修复

C 对 a3339945 给出 COMMENTED：可消费但 B1–B5 处理前不能冻结 v1。
独立材料在 PR #3：https://github.com/Kamisato-Ayaka2025/AI-Advaned-File-Search/pull/3 ，本轮只读审阅。

1. B1：SourceSummary/ChatSummary 和分页 ChatPage/MessagePage；Repository 列来源/会话/读区间，明确权限/快照/游标边界。
2. B2：Answer 必填 request_id、ambiguous clarification；SearchOutcome 和生成返回校验请求归属。
3. B3：ImportIssue 安全模板、最多 100 条 issues、issues_truncated；保持总量计数不与样例等长。
4. B4：exclude_imprecise_v1；TimeFilterInfo 披露日期级/未知时间排除，计数未知为 None；有界结果缺披露会被 validate_search_result 拒绝。
5. B5：SendPlan.snapshot/evidence_digest 必填；generate/consume 在消耗授权前校验；版本/证据变化须重新预览。
6. S1–S10 逐项实现或明确职责，完整对照在新证据记录与 contracts/README.md。

## 实测

- Python 3.12.14，73 项 unittest 全通过（0.185s）；49 个 0.3 合成 wire 对象。
- 17 个 Python 文件通过 3.11 语法检查；-I -S 标准库隔离导入通过。
- git diff --cached --check 通过。
- 新增 tests/contracts/test_c_review.py 共 21 项；原 52 项全部保留并迁移。
- C 原 31 项测试未改、未在 0.3 重跑；C 应迁移新增字段与原缺口探针后独立执行。
- 未执行 Python 3.11 运行、pytest/Ruff、真实数据、API、加密、UI/打包；没有把测试替身当运行时安全实现。

```powershell
Set-Location -LiteralPath 'F:\Code\AI_Advanced_File_Search\private\worktrees\p0-a-message-contract'
$ContractPython = 'C:\Users\z1534\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = 'src'
& $ContractPython -m unittest discover -s tests/contracts -q
& $ContractPython -I -S tests/contracts/check_environment.py
git -c safe.directory=F:/Code/AI_Advanced_File_Search/private/worktrees/p0-a-message-contract status --short --branch
```

## 材料与下一步

- 最新证据：docs/evidence/g1/2026-10-18-P0-01-A-C-review-response.md。
- 当前调用/迁移约定：src/original_words/contracts/README.md。
- 原 0.2 证据保留在 docs/evidence/g1/2026-10-18-P0-01-A-contracts.md；v0_2.json 是历史，当前样例为 v0_3.json。
- 本轮重新交付沿用 PR #2（修复/文档推送、更新描述与逐项回复、重邀 Zhong-Yufeng）；完成情况以 GitHub 最新 HEAD/reviewRequests 为准，用户已明确授权。
- C 复核 B1–B5 与日期过滤方案，并独立更新自己分支的消费测试；B 仍需核对检索/LLM 及新 consume(evidence=...) 接口。
- A 不自批，不将自己的测试通过当作 C 接受。双方确认前不合入主线。
- 后续仍需 P0 Python 3.11/模型/打包、SQLCipher/FTS5/WAL 与安全探针；真实数据模式关闭。
- 每小时 PR 跟进 p0-01-pr 保持启用；无变化安静，只通知实质评审/失败/需要处理事项，不自动改代码或合并。

## 接手注意

Answer.request_id 和 SendPlan 的快照/证据摘要是必填关键字字段；旧构造器需显式迁移，不能绕过校验填随意默认值。consume 的 evidence 必须与预览绑定对象一致。日期级有界排除是明确且需披露的策略，并非消息丢弃。

研究文档与产品 Gate 分开；C 评审不是安全验收。本轮按评审修复没有访问聊天库、取密钥或执行客户端操作。
