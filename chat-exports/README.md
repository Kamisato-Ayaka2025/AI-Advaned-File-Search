# 聊天记录导出（本机实测）

| 来源 | 会话 | 消息 | 目录 |
| --- | ---: | ---: | --- |
| QQ（NTQQ 9.9.33） | 34 | 2 234 | `qq/` |
| 微信（4.1.13.65） | 53 | 19 159 | `wechat/` |

- 格式遵循 `docs/evidence/tier-b/` 记录的 aimem Markdown 契约（YAML front matter + `private/` `group/`）。
- `*-ALL.md` 为多会话合并版，**故意放在导入目录之外**，避免按目录导入时被当成单个会话。
- `wechat-media-index.jsonl`：微信图片消息 → 本地缓存文件关联（`verified_path` / `path_missing` / `unlinked`）。

生成时间：2026-10-18。
