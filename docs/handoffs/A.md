# A 交接记录 — P0-01 DTO / Protocol

日期：2026-10-18。负责人：A / @Kamisato-Ayaka2025。
当前状态：本轮 A 侧契约实现与测试已完成，REVIEW（待 B/C 独立评审）；P0-01 整体未完成，G1/G5 均未通过。
分支：codex/p0-a-message-contract。
工作区：F:/Code/AI_Advanced_File_Search/private/worktrees/p0-a-message-contract。
基线：b486089；本轮实现提交：1325fa68dab3358859073068ddf25037e623006a。
本文与最终证据在后续文档提交中保存；当前 HEAD 以 git log -1 为准。

## 认领与文件边界

- 本轮用户明确要求持续补齐其余 DTO/Protocol、完成测试并维护 Git/交接。
- A 所有：src/original_words/contracts/、tests/contracts/、tests/fixtures/contracts/、本交接与本任务证据。
- B/C 的检索、LLM、UI、应用组装、依赖、入口和 CI 均未修改。
- 原工作区仍在 docs/decoder-informed-plan，AGENTS.md 有用户未提交修改；未覆盖、未暂存、未切换该分支。
- 本分支开工 fetch 后 origin/main 仍为 b486089；没有推送、创建远端 Issue/PR、向队友发消息或合并。

## 已完成

1. 契约版本升级为 0.2.0-draft。Message 保留现有字段并加强类型/时间精度验证。
2. 补齐 Plan 4.1 其余 DTO，以及 ADR-001 搜索规格、预算、候选、证据包、决策和结果；导入元数据嵌入 ImportReport.manifest，避免重复字段冲突。
3. 补齐 Plan 4.2 九类 Protocol。仓储读取显式固定 SnapshotRef 与授权来源；索引发布有 expected_active_revision；授权发送增加原子 consume 接口。
4. 严格 JSON 序列化和解码；全元数据发送指纹；原消息来源/字符边界检查；清理清单与任务状态检查。
5. 42 个版本化合成 DTO 样例（正常/空结果/错误），52 项 unittest，九类服务的 A 侧消费示例。
6. 调用说明：src/original_words/contracts/README.md。证据：docs/evidence/g1/2026-10-18-P0-01-A-contracts.md。

## 实测与恢复命令

执行者：本会话 A 代理；人工确认者和 B/C 独立评审者：尚无。
环境：Windows，应用捆绑 Python 3.12.14。系统只有 Python 3.12.6；没有候选 3.11，pytest/Ruff 也不可用。

```powershell
Set-Location -LiteralPath 'F:\Code\AI_Advanced_File_Search\private\worktrees\p0-a-message-contract'
$ContractPython = 'C:\Users\z1534\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = 'src'
& $ContractPython -m unittest discover -s tests/contracts -q
& $ContractPython -I -S tests/contracts/check_environment.py
git -c safe.directory=F:/Code/AI_Advanced_File_Search/private/worktrees/p0-a-message-contract status --short --branch
```

结果：52 tests，OK；15 个 Python 文件通过 3.11 语法解析；-I -S 标准库隔离导入通过，导入期间禁止 socket 调用。
git diff --cached --check 最初发现 EOF 空行，修正后通过。
未运行：Python 3.11 实际测试、pytest/Ruff、静态类型检查、模型、SQLCipher/WAL、UI、打包、真实数据或 API。

## 接口决策及限制

- Message 日期级 timestamp 仍用 ISO 日期与来源时区；当前有界过滤保守排除日期级，待 B/C 评审区间策略。未知时间为 null。
- CharSpan 使用 Python Unicode 字符索引 [start,end)，不是 UTF-8 字节或 UTF-16 索引。引用只含 ID/区间，原文/作者/时间从固定版本仓储取。
- SendPlan.preview_text 是完整 UTF-8 JSON 请求体；hash 匹配原字节，fingerprint 绑定全部范围和用途。仅允许指定 DeepSeek HTTPS 端点；服务必须禁止未授权重定向。
- ConsentGrant 不代表有效授权；后台服务必须查存储状态并原子 consume。当前测试替身是单线程内存示例，不证明生产授权、加密或竞态安全。
- Source/Message ID 和授权范围都由可信服务核对，构造 DTO 不等于获得读取/发送权限。
- SearchBudget 默认上限已按 ADR 编码；计时、取消、每阶段 token 预留和真实索引版本生命周期属于后续实现。
- DTO 转 JSON 可能含私人内容，不能写普通日志；Message repr 还有身份元数据，同样禁止直接记日志。
- 共享契约尚未冻结；不将 52 项本地通过宣称 G1/G5 或人工验收。

## 剩余任务与下一步

1. B/C 分别运行上述测试并提交自己的消费测试/评审，重点确认日期级过滤、ImportReport 嵌套、授权 consume 与快照生命周期。评审后再冻结 v1。
2. A 继续 P0 技术探针：与 C 验证 SQLCipher/FTS5/WAL、凭据保护；共享契约通过后再进入 A-01/A-02 实现。真实数据模式维持关闭。
3. C 建立 Python 3.11 候选环境、锁文件、pytest/Ruff/CI、最小窗口及打包；B 完成本地模型与中文检索探针。
4. SR0 搜索 DTO 已具备；八个跨时间事件及 B 的评测题仍待补齐，42 个 DTO 样例不等同于事件覆盖或检索质量证据。
5. 发布时关联 P0-01 与 contract-change。保持 A 不自批自己的变更、串行集成、B/C 确认后才合入。
6. A 协调 C 同步公共文档的微信实验状态：最新报告自述 22/22 页首校验、19/22 完整导出，Plan/README 的旧失败描述已过时；本会话没有独立复现，不能外推目标构建或产品 Gate。

## 已处理故障

- 沙箱无法进入项目，限定项目的提升命令成功；后续仍使用明确绝对路径。
- 应用托管 worktree 因 F 盘所有权检查失败，前轮已用 git worktree add 建立当前独立区；保留现状，不重建。
- 组合写入超过 Windows 命令长度限制，改用分文件/分块写入，已通过读取/样例匹配和测试确认。
- EOF 空行导致 diff 检查失败，规范化后通过，未削弱测试断言。

## Git 收尾

实现提交 1325fa6 已保存全部本轮源码/测试/样例；本记录与证据另作文档提交。
本轮结束前要求独立工作区 git status 干净；原工作区 AGENTS.md 修改继续保留。没有远端 PR，因此当前 REVIEW 是本地待评审状态，不是已获批准。
