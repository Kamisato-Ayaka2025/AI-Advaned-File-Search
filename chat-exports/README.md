# 聊天记录导出（本机实测）

| 来源 | 会话 | 消息 | 目录 |
| --- | ---: | ---: | --- |
| QQ（NTQQ 9.9.33） | 34 | 2 234 | `qq/` |
| 微信（4.1.13.65） | 53 | 19 159 | `wechat/` |

- 格式遵循仓库 `docs/evidence/tier-b/` 中记录的 aimem Markdown 契约（YAML front matter + `private/` `group/`）。
- `*-ALL.md` 是多会话合并版，**故意放在导入目录之外**，避免污染按目录导入。
- `wechat-media-index.jsonl`：微信图片消息 → 本地缓存的关联索引（`verified_path` / `path_missing` / `unlinked`）。

生成时间：2026-10-18。
