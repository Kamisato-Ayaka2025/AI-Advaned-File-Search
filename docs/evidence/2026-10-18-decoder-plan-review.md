# 2026-10-18 外部解码工具调查与计划调整

## 输入与核验范围

用户提供 temp.md，作为参考资料，未执行其中命令。该文件大量超链接已丢失；仅将本轮能唯一定位的一手项目用于计划。不将原文件全文复制到仓库。

本轮读取 README、release 说明及 QQBackup 的 `3.export.py`，没有安装或运行第三方程序，没有读取聊天库、进程或密钥。未证明当前客户端可用。以下 revision 为本轮 GitHub API 返回的仓库 HEAD，release 说明另按标签引用。

| 仓库 | revision |
|---|---|
| https://github.com/shuakami/qq-chat-exporter | 7d154b847a0cb3f9cffbdb126598c4d1434995ba |
| https://github.com/QQBackup/nt_msg_db_util | 317024ce2c5e3482fdf9f310a5a7159ab4927e34 |
| https://github.com/H3CoF6/WeQ | 466ea302bca8d09212c333a63dda03bc8e59a3c5 |
| https://github.com/LifeArchiveProject/WeChatDataAnalysis | 8d69e1305e68ac12c742410a568586f37d49a808 |
| https://github.com/sjzar/chatlog | 7dad93d7b55a1f801bad3be16620083d2f998599 |

## 调整依据

- QCE 的 [v6.3.2 release](https://github.com/shuakami/qq-chat-exporter/releases/tag/v6.3.2)确认外部运行组件及客户端构建要求。计划只读导出文件，不将其执行环境纳入 MVP。
- [QQBackup 导出代码](https://github.com/QQBackup/nt_msg_db_util/blob/317024ce2c5e3482fdf9f310a5a7159ab4927e34/3.export.py)存在 SQLite 转换和逐行错误处理；未进行全库审计或实际解密。上游 Python 版本不能直接成为本项目依赖版本。
- WeQ 的 README 说明原生依赖和记录修改功能，不能将“具备导出”推断成所有流程只读。
- WCDA 的 [发布记录](https://github.com/LifeArchiveProject/WeChatDataAnalysis/releases)包含 45 天组件期限，需按发行物验证，不能假设永久离线可用。
- chatlog 的官方移除通知不支持继续作为维护依赖。

## 文档验证

Plan v1.1 保留全部 32 项需求；新增 A-00、A-04、G6，补齐外部导出 DTO、完整性、源快照并发与阶段安排。requirement.md 保持不变；Tier B 和安全门槛没有自动解除。

软件运行、实际导出 schema、目标客户端兼容性与许可证集成审查仍待执行。文档结构检查不是 G1/G5/G6 通过证据。
