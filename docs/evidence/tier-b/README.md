# Tier B 工具与产物总览

本目录是 QQ / 微信本地聊天记录解密的可行性证据与参考实现。本文件是**代码、产物、结构**的总入口；细节见两份 pipeline 文档。

---

## 1. 代码清单

| 脚本 | 行数 | 作用 | 输入 → 输出 |
| --- | ---: | --- | --- |
| `ntqq_export_md.py` | 362 | QQ NT 解密 + 解析 + 导出 | 加密 `nt_db/` + `NTQQ_DB_KEY` → `private/` `group/` `index.md` |
| `wechat4_extract_keys.py` | 170 | 微信 4.x 只读取钥 | `db_storage/` + 运行中的微信 → `keys.json` |
| `wechat4_decrypt.py` | 111 | 微信库解密 | 快照 + `keys.json` → 明文 SQLite |
| `wechat4_export_md.py` | 307 | 微信消息导出 | 明文库 → `private/` `group/` `index.md` |
| `wechat_media_index.py` | 102 | 图片消息 ↔ 本地缓存关联 | 明文库 + `msg/attach` → `wechat-media-index.jsonl` |
| `validate_format.py` | 76 | aimem Markdown 契约校验 | 导出目录 → 通过/失败报告 |

### 1.1 QQ 链

```text
nt_msg.db (1024B 头 + SQLCipher 页)
  └─ ntqq_export_md.py
       ├─ 剥头 → cipher 参数轮询（HMAC_SHA1/SHA512 × iter）
       ├─ [40800] Element 解析（1/2/3/5/6/7/8/10/11/16）
       ├─ 昵称：profile_info_v6 / group_list / group_member3
       ├─ 时间：40050 → 40058 → 相邻消息继承（禁用 msgid>>32）
       └─ 输出 Markdown（front matter + private/group）
```

### 1.2 微信链

```text
Weixin.exe 内存
  └─ wechat4_extract_keys.py   "Config.Cipher" → 节点 → 对象+0x88 → XOR(24B) → x'<hex>'
       └─ keys.json（每库 32B raw key）

db_storage/*.db（SQLCipher 4）
  └─ wechat4_decrypt.py  raw key → 明文 SQLite（FTS 库走影子表回退）

明文库
  ├─ wechat4_export_md.py  zstd 解压 + local_type 渲染 + 名称解析 → Markdown
  └─ wechat_media_index.py  hardlink.db 关联 → media jsonl
```

---

## 2. 结果

| 指标 | 数值 |
| --- | --- |
| QQ 会话 / 消息 | 34（19 群 + 15 私）/ 2 234 |
| 微信会话 / 消息 | 53（15 群 + 38 私）/ 19 159 |
| 微信数据库 | 22 个，密钥 22/22 验证通过，解密 22/22 |
| 微信图片消息 | 879 条，**521** 条本地路径已验证 |
| 微信文件链接 | 195 条，可访问 195/195 |
| aimem 导入 | 87 会话 / 21 393 条，计数与源一致 |
| 契约校验 | QQ 34/34、微信 53/53 通过 |

---

## 3. 产物结构

### 3.1 目录

```
<export>/
├── index.md            # 索引表（aimem 跳过）
├── private/<标题>_<id>.md
└── group/<标题>_<id>.md
<export>-ALL.md         # 合并版，故意放在导入目录之外
```

### 3.2 会话文件

```markdown
---
platform: qq | wechat
kind: group | private
conversation: "会话标题"
conversation_id: "群号 / wxid / uid"
---
# 会话标题

- 类型：群聊
- 会话 ID：`...`
- 消息数：N
- 时间范围：YYYY-MM-DD HH:MM ~ YYYY-MM-DD HH:MM

## YYYY-MM-DD

**HH:MM:SS · 发送者**

> 正文（多行各自 `> ` 开头）
```

媒体行：`![图片](<相对路径>)`、`📎 [文件名](<相对路径>)`。

### 3.3 媒体索引 `wechat-media-index.jsonl`

```json
{"platform":"wechat","conversation_id":"...","message_id":"1","server_id":"...",
 "media_type":"image","md5":"...","source_path":"...",
 "match_status":"verified_path|path_missing|unlinked","decode_status":"pending",
 "evidence":"hardlink_db","variant":"cached"}
```

关联依据：消息 XML 的 `md5` ≡ `image_hardlink_info_v4.md5`，再由 `dir2id` + `file_name` 还原路径。
`unlinked` / `path_missing` 明确标出，不当作事实。

---

## 4. 复现命令

```bash
# QQ
export NTQQ_DB_KEY='<16 字符密钥>'
python ntqq_export_md.py --nt-db "<...>/nt_qq/nt_db" --out ./qq --my-uin <UIN>

# 微信
python wechat4_extract_keys.py --db-dir "<...>/db_storage" --out keys.json
python wechat4_decrypt.py --db-dir <快照目录> --keys keys.json --out ./plain
python wechat4_export_md.py --plain ./plain --out ./wechat --me <own_wxid> --media "<...>/msg"
python wechat_media_index.py ./plain "<...>/msg/attach" ./wechat-media-index.jsonl

# 校验
python validate_format.py ./qq
python validate_format.py ./wechat
```

---

## 5. 已知限制

| 项 | 状态 |
| --- | --- |
| 微信图片内联 | ✅ V2 外层已打通：193 张解码（PNG/JPEG），322 张为 WXGF 待 HEVC 转码 |
| 微信语音 | ⬜ 未做（`media_*.db` 的 `VoiceInfo` 可关联） |
| 微信 FTS 库 | ⚠️ 私有分词器缺失，`integrity_check` 为 `n/a(fts)`，影子表已导出、索引可重建 |
| QQ 无正文消息 | 409 条系统/撤回，保留占位不丢 |
| aimem 增量 | ⚠️ 按消息身份去重，正文变化不会刷新（`embedded=0`） |

---

## 6. 踩过的坑

1. **`.gitignore` 的 `/exports/` 与 `private/`**：后者是全局规则，任何层级的 `private/` 都会被跳过，上传需 `git add -f`。
2. **`ALL.md` 不能留在导入目录**：契约只跳过 `index.md`，合并文件会被当成单个会话解析失败。
3. **相对链接深度**：文件在 `group/` 下一层，从导出根算相对路径会全部断链。
4. **`cp -r src dst`**：`dst` 已存在时会嵌套一层，上传前务必校验目录结构。
