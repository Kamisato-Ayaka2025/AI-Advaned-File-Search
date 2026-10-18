# C 交接记录 — P0-01 契约评审 / C-01 桌面骨架

日期：2026-10-18。负责人：C / @Zhong-Yufeng（低等级 Agent，UI、应用组装、依赖与集成）。
当前状态：契约 0.2.0-draft 的 C 侧评审**已交付**（结论：可消费、不冻 v1），评审分支已开 PR #3；C-01 骨架已推送远端分支（暂未开 PR）。

## 1. 当前分支与位置

| 项 | 值 |
|---|---|
| C 推送用 clone | `D:\deepseek\ais-src\AI-Advaned-File-Search-c`（`git clone` 自 origin，已配 `http.proxy=127.0.0.1:7897` 与 `http.sslBackend=openssl`） |
| C 本地编辑区 | `D:\deepseek\ais-src\AI-Advaned-File-Search-main`（无 `.git`，只作草稿/验证，改动需同步到 clone 再提交） |
| 评审沙箱 | `D:\deepseek\ais-src\c-p0-review`（= A 分支 `codex/p0-a-message-contract` 快照 `a3339945` + C 的消费测试） |
| 远端分支 | `docs/C-p0-01-contract-review` @ `5024757` → PR #3（评审交付）；`feat/C-01-desktop-shell` @ `b111a05`（仅推送，PR 待开） |
| 已提交给 A | PR #2 上的正式评审（event=COMMENT，结论"不批准在 B1–B5 处理前冻结 v1"） |
| 抓取工具 | `D:\deepseek\.tmp\ais_c\fetch_branch.py`（Clash 代理拉 codeload tarball）、`.tmp\ais_c\deliver_review.py`（建 PR + 发评审） |

## 2. 本轮完成

1. **契约评审**：逐文件读完 A 的 10 个契约模块 + 5 个测试文件 + 42 个 wire 样例，输出 `docs/evidence/g1/2026-10-18-P0-01-C-contract-review.md`，含 5 项阻塞（B1–B5）与 10 项建议（S1–S10）。
2. **C 侧消费测试**：`tests/integration/test_contract_consumption.py`，31 项，覆盖 A 指定 C 检查的五块（导入报告、任务/错误状态、UI 引用、发送预览与授权、清理结果），并含 7 个 `test_gap_*` 探针把缺口变成可执行断言。
3. **跨版本复跑**：A 的 52 项在 Python 3.10.11 与 3.13.1 均 OK；C 的 31 项在 3.10.11 + pytest 9.1.1 全绿；Ruff（`E,F,I,UP,B`）与 `ruff format --check` 干净。
4. 确认 C 本地全套仍绿：`49 passed, 1 skipped`（新测试在 contracts 未合入前整文件跳过，不是"空测试通过"）。

## 3. 实测与恢复命令

```powershell
# 评审沙箱（A 分支快照 + C 消费测试）
cd D:\deepseek\ais-src\c-p0-review
$env:PYTHONPATH = 'src'
D:\deepseek\ais-src\AI-Advaned-File-Search-main\.venv-ais\Scripts\python.exe -m pytest tests/integration -q   # 31 passed
python -m unittest discover -s tests/contracts -q                                                          # A 的 52 项 OK

# C 工作副本（main 基线 + C-01 现状）
cd D:\deepseek\ais-src\AI-Advaned-File-Search-main
.\.venv-ais\Scripts\python.exe -m pytest -q            # 49 passed, 1 skipped
.\.venv-ais\Scripts\python.exe -m ruff check .
```

环境：Windows，`.venv-ais` = Python 3.10.11 + PySide6 6.12.0 + pytest 9.1.1 + pytest-qt 4.5.0 + Ruff 0.17.1。系统另有 Python 3.13.1。**没有 Python 3.11**，因此 A 要求的"候选 3.11 验证"仍未做到，只有 3.11 语法解析结论（A 的）与我这边 3.10/3.13 的运行证据。

## 4. 阻塞

| 阻塞 | 说明 | 恢复条件 |
|---|---|---|
| K1 推送受限（已解除） | 本沙箱 `git` 默认 schannel 失败（`SEC_E_NO_CREDENTIALS`），且凭据管理器要建命名管道被沙箱拒绝（Win32 error 5）。已用 `-c http.sslBackend=openssl -c http.proxy=...` + 单次放开沙箱解决，两个分支已推送 | 后续每次 push/API 调用仍需放开沙箱一次；token 只在进程内使用，不落盘 |
| K2 契约未冻结 | B1–B5 未处理前 UI 只能继续用过渡 DTO（`application/dtos.py`），改一次要改两遍 | A 补齐 B1–B5 并汇总 B/C 结论后冻 v1 |
| K3 PR #2 基线过期 | A 分支落后 `main`（缺 `docs/evidence/tier-b/validate_format.py`，微信报告与两个研究脚本在 main 上已更新） | A 更新 main 后重跑并与 C 的评审结论对齐 |
| K4 Python 3.11 缺失 | 契约/打包/CI 都写 3.11 候选基线 | 装了 3.11 后重跑 A 的 52 项与 C 的 31 项并记录 |
| K5 C-01 尚无 PR | `feat/C-01-desktop-shell` 只推送未开 PR（Plan §3 要求每人最多一个 REVIEW，当前 REVIEW 让给评审 PR #3） | PR #3 处理完后再开 C-01 的 PR |

## 5. 下一步具体操作（按顺序）

1. 跟 PR #3 与 PR #2 的评审结论：A 若接受 B1–B5，C 立刻按新接口改 `ui/chat_list.py`、`ui/timeline_view.py`、`ui/answer_view.py`，并删掉 `application/dtos.py` 里对应的镜像结构。
2. C-01 继续本地推进（用户已确认优先项）：会话列表、时间线、引用跳转、上下文窗，全部基于 mock；每完成一块跑 `pytest -q` 与 `ruff check .`，再同步到 clone 提交。
3. PR #3 合入后 C-01 的 PR 再开，PR 描述引用评审记录并附 offscreen 截图/测试输出。
4. 契约冻结后：把 `application/dtos.py` 整体退役（文件头已写明"不得作为契约源"），`ui/`、`application/mocks.py` 改为只消费 `contracts/`；过渡 DTO 的 `ErrorCode` 与 `TaskState` 枚举由契约类型替换。
5. P0-01 的 C 部分继续推进：Python 3.11 环境、依赖锁文件（`uv`）、CI 四个目标 job（`lint`/`unit-contract`/`integration`/`package-smoke`）、最小窗口的 `pyside6-deploy` 打包冒烟。
6. 打包与 SQLCipher/FTS5/WAL 探针需要 A 配合；这两项没结果前不得对外宣称 G1 通过。

## 6. 占用的公共文件

- 已占用并修改：`pyproject.toml`（新建）、`__main__.py`、`tests/conftest.py`（新建）。
- 本次新增：`tests/integration/test_contract_consumption.py`、`docs/evidence/g1/2026-10-18-P0-01-C-contract-review.md`、`docs/handoffs/C.md`。
- 未触碰：`requirement.md`、`Plan.md`、`README.md`、`AGENTS.md`、A 的 `src/original_words/contracts/`、`tests/contracts/`、`tests/fixtures/`。

## 7. 失败尝试与注意事项

- `git clone/ls-remote` 默认 schannel 失败（`SEC_E_NO_CREDENTIALS`）；加 `-c http.sslBackend=openssl` 即可读远端，写操作还需凭据管理器（要放开沙箱）。已把 `http.proxy` 与 `http.sslBackend=openssl` 写进 clone 的本地配置。
- GitHub API 未认证额度 60 次/小时，抓 blob 会 403（已发生）；批量取文件请用 tarball，不要逐个 blob。
- 不要用 heredoc 在 PowerShell 里改文件（`<<'EOF'` 不被支持），用编辑工具或写脚本文件。
- `Copy-Item` 复制目录到以 `\` 结尾的目标时，可能把目录内容摊到上一级（本轮曾把 `application/*.py` 复制成 `src/original_words/*.py` 的重复文件）；复制后必须 `git status` 核对，重复文件已删除。
- C 本地编辑区（`AI-Advaned-File-Search-main`）没有 `.git`：任何清理动作都可能丢掉未同步的改动，先确认 clone 里已提交再删。
- 微信实验状态需要 C 同步公共文档（A 交接第 63 条）：本轮**未做**，等 C-01 的 PR 落地后再统一改 `Plan.md`/`README.md`，避免与 A 的 PR 抢同一批文件。
