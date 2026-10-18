# 02 · 微信 4.x → Markdown

> 实测版本：微信 **4.1.13.65**（Windows x64）。
> 相关脚本：[`wechat4_extract_keys.py`](./wechat4_extract_keys.py)、[`wechat4_decrypt.py`](./wechat4_decrypt.py)、
> [`wechat4_export_md.py`](./wechat4_export_md.py)、[`wechat_media_index.py`](./wechat_media_index.py)、
> [`wechat4_find_image_key.py`](./wechat4_find_image_key.py)、[`wechat4_decode_images.py`](./wechat4_decode_images.py)

---

## 1. 数据定位

```
xwechat_files\
├── all_users\                  ← 共享配置、登录态、头像
└── wxid_<id>_<4hex>\
    ├── db_storage\             ← 全部加密库（相对路径即库标识）
    │   ├── message\            message_0/1.db、message_fts.db、media_*.db、biz_message_0.db
    │   ├── contact\            contact.db、contact_fts.db
    │   ├── session\            session.db（会话表 + Name2Id）
    │   ├── sns\                sns.db
    │   ├── hardlink\           hardlink.db（消息↔媒体关联）
    │   └── emotion\ favorite\ general\ head_image\ ...
    ├── msg\
    │   ├── attach\<会话md5>\<yyyy-mm>\Img\<file>.dat   ← 图片（V2 DAT）
    │   ├── file\<yyyy-mm>\<原文件名>                    ← 文件（保留原名）
    │   └── video\<yyyy-mm>\                             ← 视频
    └── cache\<yyyy-mm>\          ← 气泡等资源
```

要点：

- 一个 `xwechat_files` 下可能有多份 `wxid_*`，**必须按账号分别处理**。
- 微信升级会重写所有 `.db`，**不能用修改时间判断当前账号**，要用密码学校验。
- 22 个库实测文件长度全部是 4096 整数倍。

---

## 2. 容器格式

| 参数 | 值 |
| --- | --- |
| 加密 | AES-256-CBC |
| 页面认证 | HMAC-SHA512 |
| 页大小 / reserve | 4096 / 80（IV 16 + HMAC 64） |
| 文件头 | 无自定义头，前 16 字节即 salt，每库独立 |

页 1：`salt(16) | 密文 | IV(16) | HMAC(64)`。

**验钥函数**（解密前必须先证明它是对的）：

```python
mac_salt = bytes(b ^ 0x3A for b in salt)
mac_key  = PBKDF2-HMAC-SHA512(enc_key, mac_salt, 2, 32)
ok       = HMAC-SHA512(mac_key, page1[16:4032] || uint32_le(1)) == page1[4032:4096]
```

阳性对照（用自建 SQLCipher 4 库验证，已通过）：

| 用例 | 期望 |
| --- | --- |
| passphrase → PBKDF2(256000) → `verify()` | True |
| 随机 32 字节 → `verify()` | False |
| raw key 库 → `verify()` | True |

没有这一步，后面任何“0 命中”都不能作结论。

---

## 3. 密钥

### 3.1 形态

密钥**不是** passphrase，也**不是**裸 32 字节堆缓冲：

```
"com.Tencent.WCDB.Config.Cipher" 字节串（唯一）
  → (addr,len) 节点 → +0x28 配置对象
  → 对象 +0x88 的 {ptr,len} 缓冲
  → 24 字节 XOR 掩码逐字节还原
  → 文本 x'<64 hex>…' → 前 64 位 hex = 该库 32 字节 raw key
```

掩码（24 字节，循环使用）：

```
d2c74424 58020000 00488944 2450488b 45004884 4c244848 89442540
```

**关键**：掩码解开前，内存里既没有裸 key，也没有可读 hex 串——所以“扫值”必然落空，“走结构”才能拿到。

### 3.2 提取

```bash
python wechat4_extract_keys.py --db-dir "<...>/db_storage" --out keys.json
```

典型诊断输出：

```
[SCAN] regions=2768  bytes=1167MB
[SCAN] config_cipher_needles: 1
[SCAN] nodes: 163  blobs: 162  literals: 162  candidates: 54
[VERIFY] verified: 22/22
```

计数分层用于定位失败层级：找不到对象 / 结构解析失败 / 候选解码失败 / 账号不对。

约束：

- 微信必须**正在运行且已登录**，密钥只在内存中。
- 只读（`ReadProcessMemory`），不注入、不写进程、无需管理员。
- 若 `verified = 0`，先怀疑账号目录选错（见 [`04-troubleshooting.md`](./04-troubleshooting.md)）。

---

## 4. 解密

```bash
# 复制 db + -wal + -shm 到快照目录
python wechat4_decrypt.py --db-dir <快照> --keys keys.json --out ./plain
```

- 用 raw key 语义：`PRAGMA key = "x'<hex>'"`，不再做 KDF。
- 普通库 `integrity_check = ok`；FTS 库因微信私有分词器缺失报 `n/a(fts)`，
  脚本会回退到“只复制真实表（含影子表）”，索引可重建。
- 实测：22 库 / 约 81 MB，12.4 s，失败 0。

---

## 5. 消息结构

- 消息表名 `Msg_<md5(username)>`，分布在 `message_0.db` / `message_1.db`。
- `session.SessionTable.username` 做 md5 反查可还原会话。
- 行字段：`local_id`、`server_id`、`local_type`、`sort_seq`、`real_sender_id`、
  `create_time`、`message_content`、`compress_content`。
- **`message_content` 几乎全是 zstd 帧**（`28 b5 2f fd`），必须先解压。
- **`local_type` 是打包值**：`base = local_type & 0xFFFFFFFF`，高位是子类型。

渲染映射：

| base type | 含义 | 渲染 |
| --- | --- | --- |
| 1 | 文本 | 原文 |
| 3 | 图片 | `![图片](<路径>)` 或 `🖼 图片` |
| 34 | 语音 | `🎤 语音 Ns` |
| 42 | 名片 | `👤 名片` |
| 43 | 视频 | `🎬 视频` |
| 47 | 表情 | `😀 表情` |
| 48 | 位置 | `📍 位置：POI` |
| 49 | 应用消息 | 按子类型给图标 + 标题（链接/文件/引用/转账…） |
| 50 | 通话 | `☎️ 通话` |
| 10000 | 系统/撤回 | `— 原文` |

发送者解析（三级）：`real_sender_id` → `Name2Id` 行号 → username → 显示名
（群里优先 `chat_room.ext_buffer` 里的群名片，字段 1=wxid、2=昵称）。

---

## 6. 媒体

### 6.1 关联（hardlink）

`hardlink.db`：

- `image_hardlink_info_v4(md5, file_name, dir1, dir2, type)`
- `video_hardlink_info_v4`、`file_hardlink_info_v4` 结构相同
- `dir2id(rowid → username)`：dir1 是会话 md5，dir2 是年月

关联依据：**消息 XML 的 `md5` ≡ `image_hardlink_info_v4.md5`**，
再由 `dir1/dir2/file_name` 还原路径：

```
msg/attach/<dir1>/<dir2>/Img/<file_name>
```

实测 879 条图片消息：521 条 `verified_path`、9 条 `path_missing`、349 条 `unlinked`。
不要用 md5 去猜磁盘文件名（0% 命中），必须走这张表。

```bash
python wechat_media_index.py ./plain "<...>/msg/attach" ./media-index.jsonl
```

输出字段见 [`03-markdown-contract.md`](./03-markdown-contract.md) 第 5 节。

### 6.2 V2 DAT 解密

```
[6B 签名 07 08 56 32 08 07][4B aes_size LE][4B xor_size LE][1B padding]
[aligned_aes_size 字节 AES-ECB 段][raw 明文段][xor_size 字节 单字节 XOR 段]
```

- `aligned_aes_size = aes_size + (16 - aes_size % 16)`，数据从 **offset 15** 开始；
- 末段单字节 XOR，本机实测 key = `0xAC`（用 JPEG EOI 反推，191/193 票一致）；
- AES key **不是**消息里的 `aeskey`，而是进程内存中一个 **16 字节 ASCII 串**。

取图片密钥：

```bash
python wechat4_find_image_key.py --dat "<任一个 .dat>" --out imgkey.txt
```

判据：用候选 key 解该文件的 AES 段，输出出现 `JPEG/PNG/GIF/WEBP/wxgf` 魔数即命中
（本机 7248 个候选内命中）。只读扫描，不注入。

### 6.3 WXGF 转码

`wxgf` 是 HEVC 裸流封装。处理：在解出的码流里找 HEVC 起始码 `00 00 00 01`，
用 `ffmpeg -f hevc -frames:v 1` 导出首帧 PNG。

```bash
python wechat4_decode_images.py --index ./media-index.jsonl --out ./wx/media \
       --map map.json --key "$(cat imgkey.txt)" --xor-key 0xAC
```

实测：521 条已验证路径 → **505 张解码成功**（156 PNG + 37 JPEG + 312 WXGF→PNG），
10 张缺起始码，耗时 55.6 s。

---

## 7. 导出

```bash
python wechat4_export_md.py --plain ./plain --out ./wx --me <own_wxid> \
       --media "<...>/msg" --image-map map.json
```

| 参数 | 作用 |
| --- | --- |
| `--plain` | `wechat4_decrypt.py` 的输出目录 |
| `--out` | Markdown 输出目录 |
| `--me` | 自己的 wxid，渲染为“我” |
| `--media` | `.../<wxid>/msg`，用于文件消息链接 |
| `--image-map` | `wechat4_decode_images.py` 产出的 md5→图片路径 |

输出遵循 [`03-markdown-contract.md`](./03-markdown-contract.md)。
实测 19 159 条消息导出耗时 0.68 s。

---

## 8. 实测

| 指标 | 数值 |
| --- | ---: |
| 会话 | 53（15 群 + 38 私） |
| 消息 | 19 159 |
| 图片消息 | 879（521 已内联） |
| 文件链接 | 195 |
| 取钥 / 解密 / 导出 / 图片 | 2.0 s / 12.4 s / 0.68 s / 55.6 s |

---

## 9. 限制

| 项 | 说明 |
| --- | --- |
| 合并转发 | 47 条，`<recorditem>` 含内层消息，未展开 |
| 引用原文 | 567 条，`<refermsg>` 含被引内容，未回填 |
| 视频 | 59 条，`video_hardlink_info_v4` 可部分定位 |
| 未关联图片 | 359 条（本地无缓存或未匹配） |
| 语音 | 未处理 |
| 版本敏感 | 节点偏移（`+0x28`、`+0x88`）与 24 字节掩码随大版本可能变化，需重采 |
