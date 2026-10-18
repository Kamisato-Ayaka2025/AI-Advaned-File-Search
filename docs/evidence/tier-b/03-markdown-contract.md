# 03 · Markdown 契约（aimem 消费格式）

> 本契约同时约束 QQ 与微信的导出结果。目标：一个会话一个 `.md`，逐条消息可被解析出
> **发言人 / 时间 / 正文 / 附件**。aimem 侧命令：`aimem import-markdown <dir> --platform qq|wechat`。

---

## 1. 目录布局

```
<export>/
├── index.md                      # 索引表，aimem 会跳过
├── private/<标题>_<id>.md        # 私聊
├── group/<标题>_<id>.md          # 群聊
└── media/<md5>.jpg               # 微信解码图片（可选）
<export>-ALL.md                   # 合并版，必须在导入目录之外
```

> **`ALL.md` 不能放在导入目录里**：契约只约定跳过 `index.md`，多会话合并文件会被当成
> 一个会话解析，出现“日期重复 / 非升序”而失败。

---

## 2. 单个会话文件

```markdown
---
platform: qq
kind: group
conversation: "2024级某某专业群"
conversation_id: "945067886"
---
# 2024级某某专业群

- 类型：群聊
- 会话 ID：`945067886`
- 消息数：196
- 时间范围：2025-09-01 10:00 ~ 2026-10-12 22:31

## 2025-10-12

**15:28:00 · 张经理**

> 新报价已经发给你了，之前那个版本别用了。
> 第二行正文也用 `> ` 开头。

**15:31:00 · 我**

> 收到，设备采购方案我按最终版更新。
```

YAML 字段：

| 字段 | 取值 |
| --- | --- |
| `platform` | `qq` / `wechat` |
| `kind` | `group` / `private` |
| `conversation` | 会话标题（JSON 字符串，允许引号/中文） |
| `conversation_id` | 群号 / wxid / uid |

---

## 3. 硬性规则

| # | 规则 |
| --- | --- |
| 1 | UTF-8，**不要 BOM** |
| 2 | YAML front matter 用 `---` 包裹，至少含 `platform`、`conversation` |
| 3 | 日期用 `## YYYY-MM-DD`，同一日期只出现一次，消息按时间升序 |
| 4 | 每条消息头：`**HH:MM:SS · 发言人**`（时间在前，`·` 分隔） |
| 5 | 正文每行以 `> ` 开头；换行保持为多个 `> ` 行 |
| 6 | 图片：`![图片](<相对路径>)`；文件：`📎 [文件名](<相对路径>)` |
| 7 | 本地时区（+08:00），不输出 UTC |
| 8 | 会话文件里不要放表格；表格只放 `index.md` |
| 9 | 系统/撤回消息保留一行占位，不丢，否则时间线会断 |

**相对路径的基准是“会话文件所在目录”**。文件位于 `group/` 或 `private/`，
所以指向同级 `media/` 要写成 `../media/x.jpg`，指向导出目录外要按实际层级递增 `../`。

---

## 4. 校验

```bash
python validate_format.py ./qq
python validate_format.py ./wx
# 输出: root=... files=N failed=0
```

校验项：BOM、front matter（`platform`/`conversation`）、日期唯一且升序、
消息头格式、正文 `> ` 前缀、会话文件内无表格。

实测：QQ 34/34、微信 53/53 通过。

---

## 5. 媒体索引 `media-index.jsonl`

每行一条消息 ↔ 媒体文件的**可追溯**记录：

```json
{"platform":"wechat","conversation_id":"...","message_id":"1","server_id":"...",
 "media_type":"image","variant":"cached","evidence":"hardlink_db",
 "md5":"6ea7...","source_path":"...","output_path":null,
 "match_status":"verified_path","decode_status":"pending"}
```

`match_status` 语义（**只有 verified 才算事实**）：

| 值 | 含义 |
| --- | --- |
| `verified_path` | hardlink 命中且文件存在 |
| `path_missing` | hardlink 命中但文件已删 |
| `unlinked` | 无 hardlink 记录 |

`decode_status`：`pending` / `decoded` / `failed`。

原则：**不得**用时间、大小相近来推断关联；推断出的关系只能标候选，不能写成来源。

---

## 6. aimem 导入行为（实测）

```bash
aimem import-markdown ~/Desktop/qq-chat-markdown --platform qq
aimem import-markdown ~/Desktop/wechat-markdown --platform wechat
aimem stats
```

| 项 | 结果 |
| --- | --- |
| 导入条数 | QQ 2 234、微信 19 159，与源一致 |
| 重复导入 | `embedded=0`，总数不变 |
| 局限 | 按消息身份去重，**正文变化不会刷新**；更新导出后需 `--force` 或清库 |

---

## 7. 生成方清单

| 平台 | 生成脚本 | 备注 |
| --- | --- | --- |
| QQ | `ntqq_export_md.py` | 图片用本地缓存相对路径 |
| 微信 | `wechat4_export_md.py` | 图片用 `media/`，文件用 `msg/file` 相对路径 |
| 校验 | `validate_format.py` | 两个平台通用 |
