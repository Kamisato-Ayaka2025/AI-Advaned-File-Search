# AI-Advaned-File-Search

原话考古（Original Words）：面向 Windows 的本地优先 QQ/微信聊天记录检索工具。

## 当前状态

项目处于需求与工程规划阶段，已有 QQ/微信研究报告和实验脚本，尚无可运行产品、产品构建脚本、自动化测试或 CI。技术方向为 Python + PySide6 + SQLite + 本地 Embedding；具体依赖和 Windows 打包方案在 P0 验证。

## 项目文档

- [requirement.md](requirement.md)：产品范围、REQ-001～REQ-032 与验收标准。
- [Plan.md](Plan.md)：三人分工、接口契约、并发管理、GitHub 流程、阶段与验收门槛。
- [AGENTS.md](AGENTS.md)：贡献者与开发代理指南。
- [QQ 查找实现路线](docs/decisions/ADR-001-qq-search-route.md)：多粒度召回、两轮 Agent 补查、上下文/时间预算及跨时间验收。

## 三人开发入口

| 开发线 | 责任 |
|---|---|
| A：@Kamisato-Ayaka2025（高级 Agent） | 架构/契约、数据存储、并发与安全、关键技术评审 |
| B：@YuanKunlin（低等级 Agent） | 本地 Embedding、混合检索、DeepSeek、引用校验 |
| C：@Zhong-Yufeng（低等级 Agent） | PySide6 桌面端、授权交互、应用协调、CI 与 Windows 打包 |

A/B/C 及 GitHub 账号已确认。接下来完成 Plan.md 的 P0-01：环境验证、契约冻结、mock/fixture、仓库协作设置。后续各工作包使用独立分支和 PR；A 协调技术评审和串行合并，C 执行构建与联调，公共文件遵守单一负责人规则。

## 范围与数据

MVP 使用文件导入和明确标注的合成演示数据。QQ 9.9.33-52230 已有队友解码实验报告，现优先将其解析经验转为结构化导入，不能直接将 Markdown 当事实源；原目标 QQ 9.9.29 未验证。微信保持文件导入。Tier B 密钥取得/客户端操作仍属后续独立评审，不把实验脚本当生产接入。加密、授权和隐私门槛未通过前，不开放真实数据模式。

本仓库公开。不要提交真实聊天记录、API Key、运行数据库、模型权重或本地工具配置。构建、运行和测试命令将在工具链实际建立后补充；Plan.md 中的目标命令目前不可直接执行。
