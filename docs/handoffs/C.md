# C 交接记录 — P0-01 契约评审 / C-01 桌面骨架

日期：2026-10-18。负责人：C / @Zhong-Yufeng（低等级 Agent，UI、应用组装、依赖与集成）。
当前状态：契约 0.2.0-draft 的 C 侧评审**已完成**（结论：可消费、不冻 v1）；C-01 骨架**仅存在于本地工作副本、尚未推送到远端**。

## 1. 当前分支与位置

| 项 | 值 |
|---|---|
| C 工作副本 | `D:\deepseek\ais-src\AI-Advaned-File-Search-main`（内容基于 `main`，非 git clone，**没有 .git，不可直接提交**） |
| 评审沙箱 | `D:\deepseek\ais-src\c-p0-review`（= A 分支 `codex/p0-a-message-contract` 快照 `a3339945` + C 的消费测试） |
| 远端分支 | C 自己的功能分支**尚未创建**；`feat/C-01-desktop-shell` 在 GitHub 上不存在 |
| 抓取工具 | `D:\deepseek\.tmp\ais_c\fetch_branch.py`（走 Clash 代理拉 codeload tarball，绕开 API 限流） |
| 待推送文件 | `pyproject.toml`、`src/original_words/{__init__,__main__}.py`、`application/`、`ui/`、`tests/conftest.py`、`tests/ui/`、`tests/integration/test_contract_consumption.py`、`docs/evidence/g1/2026-10-18-P0-01-C-contract-review.md`、本文件 |

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
| K1 无法推送 | 本环境 `git` 走 schannel 失败（`SEC_E_NO_CREDENTIALS`），也没有 GitHub 凭据/gh CLI；只有 python + Clash 代理可读远端 | 用户在自己的终端创建 `feat/C-01-desktop-shell` 并推送，或在环境里配置 PAT/gh 登录 |
| K2 契约未冻结 | B1–B5 未处理前 UI 只能继续用过渡 DTO（`application/dtos.py`），改一次要改两遍 | A 补齐 B1–B5 并汇总 B/C 结论后冻 v1 |
| K3 PR #2 基线过期 | A 分支落后 `main`（缺 `docs/evidence/tier-b/validate_format.py`，微信报告与两个研究脚本在 main 上已更新） | A 更新 main 后重跑并与 C 的评审结论对齐 |
| K4 Python 3.11 缺失 | 契约/打包/CI 都写 3.11 候选基线 | 装了 3.11 后重跑 A 的 52 项与 C 的 31 项并记录 |

## 5. 下一步具体操作（按顺序）

1. 用户授权推送后：以 `main` 建 `feat/C-01-desktop-shell`，提交 C-01 现状 + 本记录 + 评审记录；PR 描述引用评审记录的 B1–B5，标注 `contract-change` 的关联（不修改 A 的文件）。
2. 等 A 回应 B1–B5；B1（会话列表/时间线接口）与 B2（`Answer.request_id`/追问文案）是 C-01 必须先有的接口，A 一旦给出，C 立刻把 `ui/chat_list.py`、`ui/timeline_view.py` 接到正式 DTO，删掉 `application/dtos.py` 里对应的镜像结构。
3. 契约冻结后：把 `application/dtos.py` 整体退役（文件头已写明"不得作为契约源"），`ui/`、`application/mocks.py` 改为只消费 `contracts/`；过渡 DTO 的 `ErrorCode` 与 `TaskState` 枚举由契约类型替换。
4. P0-01 的 C 部分继续推进：Python 3.11 环境、依赖锁文件（`uv`）、CI 四个目标 job（`lint`/`unit-contract`/`integration`/`package-smoke`）、最小窗口的 `pyside6-deploy` 打包冒烟。
5. 打包与 SQLCipher/FTS5/WAL 探针需要 A 配合；这两项没结果前不得对外宣称 G1 通过。

## 6. 占用的公共文件

- 已占用并修改：`pyproject.toml`（新建）、`__main__.py`、`tests/conftest.py`（新建）。
- 本次新增：`tests/integration/test_contract_consumption.py`、`docs/evidence/g1/2026-10-18-P0-01-C-contract-review.md`、`docs/handoffs/C.md`。
- 未触碰：`requirement.md`、`Plan.md`、`README.md`、`AGENTS.md`、A 的 `src/original_words/contracts/`、`tests/contracts/`、`tests/fixtures/`。

## 7. 失败尝试与注意事项

- `git clone/ls-remote` 在本沙箱一律失败（schannel 凭据错误），不要反复重试；改用 `fetch_branch.py`（codeload tarball）。
- GitHub API 未认证额度 60 次/小时，抓 blob 会 403（已发生）；批量取文件请用 tarball，不要逐个 blob。
- 不要用 heredoc 在 PowerShell 里改文件（`<<'EOF'` 不被支持），用编辑工具或写脚本文件。
- C 工作副本没有 `.git`：任何"忘记备份就清理"的动作都会丢 C-01 代码，先确认远端有对应分支再动本地目录。
- 微信实验状态需要 C 同步公共文档（A 交接第 63 条）：本轮**未做**，等 C-01 推送落地后再统一改 `Plan.md`/`README.md`，避免与 A 的 PR 抢同一批文件。
