# AI-Advaned-File-Search

原话考古（Original Words）：面向 Windows 的本地优先 QQ/微信聊天记录检索工具。

## 当前状态

项目处于需求与工程规划阶段，尚无可运行应用、构建脚本、自动化测试或 CI。技术方向为 Python + PySide6 + SQLite + 本地 Embedding；具体依赖和 Windows 打包方案在 P0 验证。

## 项目文档

- [requirement.md](requirement.md)：产品范围、REQ-001～REQ-032 与验收标准。
- [Plan.md](Plan.md)：三人分工、接口契约、并发管理、GitHub 流程、阶段与验收门槛。
- [AGENTS.md](AGENTS.md)：贡献者与开发代理指南。

## 三人开发入口

| 开发线 | 责任 |
|---|---|
| A（高级 Agent） | 架构/契约、数据存储、并发与安全、关键技术评审 |
| B（低等级 Agent） | 本地 Embedding、混合检索、DeepSeek、引用校验 |
| C（低等级 Agent） | PySide6 桌面端、授权交互、应用协调、CI 与 Windows 打包 |

先分配 A/B/C 与 GitHub 账号，再完成 Plan.md 的 P0-01：环境验证、契约冻结、mock/fixture、仓库协作设置。后续各工作包使用独立分支和 PR；A 协调技术评审和串行合并，C 执行构建与联调，公共文件遵守单一负责人规则。

## 范围与数据

MVP 使用文件导入和明确标注的合成演示数据。Tier B 本地客户端接入属于后续独立验证；不将演示视为真实客户端已接入。加密、授权和隐私门槛未通过前，不开放真实数据模式。

本仓库公开。不要提交真实聊天记录、API Key、运行数据库、模型权重或本地工具配置。构建、运行和测试命令将在工具链实际建立后补充；Plan.md 中的目标命令目前不可直接执行。
