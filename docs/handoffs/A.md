# A 交接记录 — P0-01 消息契约子任务

日期：2026-10-18。负责人：A / @Kamisato-Ayaka2025。
状态：本子任务 REVIEW（本地待独立评审）；P0-01 整体未完成，G1 未通过。
分支：codex/p0-a-message-contract；基线：b486089。
工作区：F:/Code/AI_Advanced_File_Search/private/worktrees/p0-a-message-contract。

## 当前状态与任务边界

- 开工已 fetch origin；main 最新 b486089，包含已合并的规划 PR #1 和微信报告修正。
- 原检出仍在 docs/decoder-informed-plan，AGENTS.md 有用户未提交修改；未改动或暂存它。
- 仅认领 P0-01 的 A 侧 Message 契约子任务，REQ-004/011/022；未接管 B/C 路径、依赖、入口或 CI。
- 产品尚无入口、仓储、模型、界面或构建配置。此提交只有共享消息契约和合成测试。
- 最新微信报告自述 22/22 页首校验、19/22 完整导出，旧 Plan/README 中失败描述已过时；这是队友报告证据，未独立复现，不可外推目标版本或通过 G5。后续由 A 协调 C 更新公共文档。

## 交付及接口决策（草案，需 B/C 确认）

- src/original_words/contracts/messages.py：不可变 Message、稳定命名空间 ID、时间精度和 UTC 检查。
- tests/contracts/test_messages.py：合成构造器与九项可执行边界检查；无私人数据。
- 原始 ID 优先；缺失时调用者必须提供持久源序号，不能使用过滤后行号；路径和批次不参与身份。
- 日期级 timestamp 保留 ISO 日期及来源时区，禁止制造午夜秒级事件。当前有界时间查询保守排除日期级消息；日期区间相交策略需 B/C 评审后追加，不能宣称完整日期过滤已完成。
- 未知时间和空正文保留；有界过滤排除未知时间，无界查询保留。
- Message 的 repr 隐藏正文、附件、原始时间和 raw_payload，但仍包含身份元数据，因此禁止将整个 DTO 写入普通日志。
- 无数据库/网络/Qt/模型依赖；未实现完整 DTO/Protocol、JSON 输入边界验证或安全网关。版本 0.1.0-draft，不可标记为冻结 v1。

## 实测证据

执行者：本会话 A 代理。人工确认者：无。输入：测试内置合成字段。
环境：Windows，应用捆绑 Python 3.12.14；不是计划候选 Python 3.11，也不是三机锁定环境。

```powershell
$env:PYTHONPATH = 'src'
& 'C:\Users\z1534\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests/contracts -v
```

结果：9 tests，OK。覆盖序列化往返、ID 隔离/幂等、未知时间、日期精度、UTC、半开边界、错误消息不回显无效时间。
未执行：pytest/Ruff（C 尚未建立工具链）、模型离线、SQLCipher/WAL、GUI、Windows 打包和任何真实数据/API测试。

## 失败尝试与恢复

- 沙箱终端未进入项目路径，显式 Set-Location 返回拒绝访问；限定项目的提升命令已成功。
- Git 在 F 盘报告 dubious ownership；只使用命令级 safe.directory，未修改全局配置。
- 应用 create_worktree 因同一所有权错误失败；改用 git worktree add 创建独立目录，原分支不切换。

## 剩余工作和精确下一步

1. B/C 独立运行九项测试并评审 Message 的日期精度、来源命名空间、未知类型及错误映射；未获确认前不冻结/合并。
2. A 继续 P0-01：补 Chunk/ImportReport/Search/SendPlan/Answer/TaskEvent 和 Protocol；SR0 搜索 DTO/预算及八个合成事件仍未实现。
3. C 建立 Python 3.11 候选验证、pyproject/锁文件/pytest/Ruff/最小窗口与打包；B 验证本地模型。不要把本机 Python 3.12 的通过当作 P0 完成。
4. A/C 验证 SQLCipher、FTS5、WAL 与凭据机制；G5 前真实数据模式继续关闭。
5. 当前没有新建远端 Issue/PR、没有推送或向队友发送消息。独立评审前不自批、不合并。后续发布需关联 P0-01 任务与 contract-change。
