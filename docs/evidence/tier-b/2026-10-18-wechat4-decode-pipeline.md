# 微信 4.x 本地库解密：步骤、跨机复用与鲁棒性

> **类型**：Tier B 可行性 spike（`Plan.md` R-08 / `requirement.md` REQ-006）
> **日期**：2026-10-18（合并并取代同目录早前的 `wechat4-decrypt-probe` 记录）
> **状态**：已打通。22/22 库密钥验证通过，22/22 可解密导出，消息可读。
> **脱敏**：不含真实消息、昵称、wxid、密钥、绝对路径。

---

## 1. 结论摘要

| 项 | 结果 |
| --- | --- |
| 客户端 | 微信 4.1.13.65（Windows x64），普通用户权限 |
| 容器 | SQLCipher 4：AES-256-CBC / HMAC-SHA512 / 页 4096 / reserve 80 |
| 密钥 | **每库 32 字节 raw key**，缓存在 WCDB 运行时对象里，24 字节 XOR 掩码混淆 |
| 获取 | **纯只读**：`ReadProcessMemory` + 结构遍历；无注入、无 hook、无写入 |
| 验证 | 22/22 库页 1 HMAC 通过（验钥器有阳性对照） |
| 解密 | 22/22 导出成功；普通库 `integrity_check = ok`，FTS 库 `n/a(fts)` |
| 规模 | `message_0.db`：48 会话 / 16 015 条；全库导出约 12.9 万行（含 FTS 影子表） |
| 耗时 | 取钥 2.0 s；解密 22 个库 12.4 s（含 80 MB 数据） |
| 稳定性 | 同会话内两次取钥结果**逐字节一致**；重复解密结果一致 |

一句话：**能拿到全部聊天库，方式是读结构，不是扫内存。**

---

## 2. 环境与版本矩阵

| 项 | 本次验证 | `requirement.md` 目标 |
| --- | --- | --- |
| 微信 | 4.1.13.65 | 4.1.15.13（未验证） |
| 系统 | Windows 10/11 x64 | Win10/Win11 |
| 权限 | 普通用户（**不需要管理员**） | — |
| Python | 3.10+，`sqlcipher3-binary` | — |

> 版本矩阵必须单列：QQ 与微信的适配方式完全不同，不能合并成一句“Tier B 已验证”。

---

## 3. 数据定位

```
xwechat_files\
├── all_users\                  ← 共享配置、登录态、头像
└── wxid_<id>_<4hex>\
    ├── db_storage\             ← 全部加密库（相对路径即库标识）
    │   ├── message\            message_0.db / message_1.db / message_fts.db
    │   │                       media_0.db / media_1.db / biz_message_0.db
    │   ├── contact\            contact.db / contact_fts.db
    │   ├── session\            session.db（会话表 + Name2Id）
    │   ├── sns\                sns.db
    │   └── emoticon\ favorite\ general\ hardlink\ head_image\ ...
    ├── cache\<yyyy-mm>\        ← 图片/视频缓存
    └── business\               ← 收藏、表情等
```

要点：

- 一个 `xwechat_files` 下可能有多个 `wxid_*` 目录，**必须按账号分别处理**。
- 微信升级会重写所有 `.db`，**不能用修改时间判断当前账号**；要用密码学校验（见第 9 节）。
- 22 个库实测文件长度全部是 4096 的整数倍，可作为“无自定义头、页大小 4096”的自检。

---

## 4. 容器格式

| 参数 | 值 |
| --- | --- |
| 加密 | AES-256-CBC |
| 页面认证 | HMAC-SHA512 |
| 页大小 / reserve | 4096 / 80（IV 16 + HMAC 64） |
| 文件头 | 无自定义头，前 16 字节即 salt，每库独立 |

页 1 布局：`salt(16) | 密文 | IV(16) | HMAC(64)`。

验钥算法（**解密前先证明它是对的**）：

```python
mac_salt = bytes(b ^ 0x3A for b in salt)
mac_key  = PBKDF2-HMAC-SHA512(enc_key, mac_salt, 2, 32)
ok       = HMAC-SHA512(mac_key, page1[16:4032] || uint32_le(1)) == page1[4032:4096]
```

### 阳性对照（必做，不可省）

| 用例 | 期望 | 实测 |
| --- | --- | --- |
| passphrase → PBKDF2(256000) → `verify()` | True | ✅ |
| 随机 32 字节 → `verify()` | False | ✅ |
| raw key 库 → `verify()` | True | ✅ |
| SQLCipher C 库用派生 key 打开 | 成功 | ✅ |

没有这一步，后面任何“0 命中”都不能作为结论——本项目的第一次误判正是栽在这里。

---

## 5. 密钥形态与获取

### 5.1 形态

密钥**不是** passphrase，也**不是**裸 32 字节堆缓冲，而是：

```
"com.Tencent.WCDB.Config.Cipher" 字节串（唯一）
   → (addr,len) 节点 → +0x28 配置对象
   → 对象 +0x88 的 {ptr,len} 缓冲
   → 24 字节 XOR 掩码逐字节还原
   → 文本 x'<64 hex>…'  → 前 64 位 hex = 32 字节 raw key
```

掩码常量（24 字节，循环使用）：

```
d2c74424 58020000 00488944 2450488b 45004884 4c244848 89442540
```

**关键**：掩码解开前，内存里既没有裸 key，也没有可读 hex 串。所以“扫值”必然落空，“走结构”才能拿到。

### 5.2 诊断计数（一次成功运行的典型值）

```
[CHECK] verifier_positive_test: PASS
[SCAN]  main_process_found: YES
[SCAN]  regions=2768  bytes=1167MB
[SCAN]  config_cipher_needles: 1
[SCAN]  nodes: 163
[SCAN]  blobs: 162
[SCAN]  literals: 162
[SCAN]  candidates: 54
[VERIFY] verified: 22/22
```

计数分层的作用：失败时能定位是“找不到对象”“结构解析失败”“候选解码失败”还是“账号不对”，而不是笼统地报“没拿到密钥”。

---

## 6. 解密

```text
1. 快照：db + db-wal + db-shm 三件套一起复制
2. 打开：PRAGMA cipher_page_size=4096; PRAGMA key="x'<hex>'"
3. 导出：sqlcipher_export() → 明文库
4. 失败回退：只复制真实表（FTS 影子表），跳过虚表
```

注意事项：

- **raw key 语义**：拿到的是已经派生好的 AES key，不要再走 256000 次 KDF。
- **三件套**：实测本机快照去掉 WAL 后行数不变（微信已 checkpoint），但仍应一并复制——一旦遇到未 checkpoint 的库，缺 WAL 会直接丢最新消息。
- **FTS 库**：声明了微信私有分词器 `MMFtsTokenizer`，vanilla SQLCipher 没有该模块，`PRAGMA integrity_check` 会报 `SQL logic error`；`sqlcipher_export` 会跳过虚表、保留影子表，索引可重建。

---

## 7. 消息结构（初步）

- `message_0.db` / `message_1.db` 是**消息分片**，表名形如 `Msg_<md5(username)>`。
- `session.db::SessionTable.username` + `md5()` 可反查分片表；`contact.db::contact` 提供显示名。
- 消息行关键列：`local_id`、`server_id`、`local_type`、`sort_seq`、`real_sender_id`、`create_time`、`message_content`、`compress_content`。
- `message_content` 为可读文本（群消息带 `wxid_…:` 前缀）；`compress_content` 需按 `local_type` 解压。
- 实测：48 个会话、16 015 条。

> 尚未做完整的类型矩阵（图片/语音/引用/合并转发）与 Markdown 导出，属于下一步工作。

---


### 7.1 导出为 Markdown（已打通）

```text
message_0/1.db 的 Msg_<md5(username)>
  → session.SessionTable 还原 username（md5 反查）
  → contact.contact 取备注/昵称；chat_room.ext_buffer 解析群名片
  → message_content 先 zstd 解压，再按 local_type 渲染
  → index.md + ALL.md + chat/*.md
```

要点：

- `local_type` 是**打包值**：`base = local_type & 0xFFFFFFFF`，高位是子类型。
- `message_content` 几乎全是 **zstd** 帧（`28 b5 2f fd`），必须先解压。
- 群消息正文带 `wxid_xxx:` 前缀，需剥离后作为发送者兜底。
- 发送者：`real_sender_id` → `Name2Id` 行号 → username → 显示名（群里优先群名片）。

渲染覆盖的类型：

| base type | 含义 | 渲染 |
| --- | --- | --- |
| 1 | 文本 | 原文 |
| 3 | 图片 | `🖼 图片` |
| 34 | 语音 | `🎤 语音 Ns` |
| 42 | 名片 | `👤 名片` |
| 43 | 视频 | `🎬 视频` |
| 47 | 表情 | `😀 表情` |
| 48 | 位置 | `📍 位置：POI` |
| 49 | 应用消息 | 按子类型给图标 + 标题/描述（链接、文件、引用、转账…） |
| 50 | 通话 | `☎️ 通话` |
| 10000 | 系统/撤回 | `— 原文` |

实测：**53 个会话 / 19 159 条消息 / 3.4 MB**，`index.md` + `ALL.md` + 每会话一个文件；自己发的消息渲染为“我”。

随附脚本：[`wechat4_export_md.py`](./wechat4_export_md.py)

```bash
python wechat4_export_md.py --plain ./plain --out ./md --me <own_wxid>
```

尚未覆盖：图片/语音文件本地化（只标类型）、语音转写、合并转发的内层消息展开、引用消息的原文还原。

## 8. 在另一台电脑上复用

```text
[ ] Windows x64，微信 4.x 已安装并登录过
[ ] Python 3.10+；pip install sqlcipher3-binary
[ ] 确认 db_storage 目录属于**当前登录账号**（可用目录名与 cfg wxid 比对）
[ ] python wechat4_extract_keys.py --db-dir "...\db_storage" --out keys.json
      → 期望 verified = 库总数
[ ] 复制 db + -wal + -shm 到快照目录
[ ] python wechat4_decrypt.py --db-dir <快照> --keys keys.json --out .\plain
      → 期望 failed = 0
[ ] 抽样核对：会话数、消息总数与客户端量级一致
[ ] 删除 keys.json
```

耗时参考：取钥 2 s，解密 12 s（22 库 / 80 MB）。

**密钥不能跨机复用**：每库独立随机，且只在客户端运行时缓存在内存里。

---

## 9. 鲁棒性

### 9.1 实测项

| 项 | 方法 | 结果 |
| --- | --- | --- |
| 取钥确定性 | 连续两次运行，比较输出 | 两次 JSON **逐字节一致** |
| 候选稳定性 | 多次运行 | `candidates` 稳定为 54 |
| 重复解密 | 同一输出目录跑两次 | 行数一致（16015） |
| 页对齐不变量 | 22 个库取模 | 22/22 通过 |
| WAL 影响 | 有/无 `-wal` 对比 4 个活跃库 | 当前快照 delta = 0（已 checkpoint），仍建议保留 |
| FTS 兼容 | 加 `integrity_check` 容错 + 影子表导出 | 失败数从 3 → **0** |
| 权限 | 普通用户 `ReadProcessMemory` | 正常，无需提权 |

### 9.2 失效模式

| 环节 | 触发条件 | 表现 | 处置 |
| --- | --- | --- | --- |
| 进程 | 微信未运行 | `Weixin.exe not running` | 启动并登录后重试 |
| 账号 | 目录与当前登录账号不符 | `verified = 0/22` | 换正确目录；**勿按 mtime 选账号** |
| 版本 | 大版本升级 | `needles = 0` 或 `nodes = 0` | 重采结构偏移与掩码常量 |
| 结构 | 节点偏移漂移 | 候选为 0 或全部验不过 | 用字符串锚点重新定位，勿硬编码 |
| FTS | 私有分词器缺失 | `integrity_check` 报错 | 已内置容错与影子表导出 |
| 快照 | 只拷主库 | 可能丢最新消息 | 三件套一起复制 |
| 并发 | 边写边读 | 快照不一致 | 先复制再解密，不要在活库上直接解密 |

### 9.3 版本敏感性

结构偏移（节点 `+0x28`、对象 `+0x88`）与 24 字节掩码都是**版本相关常量**：

- 小版本通常不变；
- 大版本可能整体重排；
- 升级后必须回归一次“取钥成功率”，并保留 `nodes/blobs/verified` 三级计数用于快速定位。

---

## 10. 与 QQ 的对比

| 维度 | QQ NT 9.9.33 | 微信 4.1.13.65 |
| --- | --- | --- |
| 容器 | 1024 字节自定义头 + 4096 页 | 无头，标准 SQLCipher 页 |
| 密钥 | 16 字符 passphrase（按账号/机器生成） | 每库 32 字节 raw key |
| 获取 | 调试器断点读寄存器 | 只读内存结构 + XOR 解掩码 |
| 需重启客户端 | 是 | 否 |
| 需注入/hook | 否 | 否 |
| 解密参数 | HMAC-SHA1 + PBKDF2-SHA512/4000 | raw key，HMAC-SHA512 |
| 复用方式 | 每机重取 passphrase | 每机重取 raw key |

两者都满足仓库「不 hook、不注入」的边界。

---

## 11. 对产品的结论

1. **微信 Tier B 可行性成立**：本地库可只读解密，`REQ-006` 的微信侧不再被“必须 hook”阻断。
2. **架构仍是「快照 → 离线解密 → 解析」**：客户端只被读一次文件，解密与解析都不在查询路径上。
3. **版本适配器**：以 `(客户端版本, 结构偏移, 掩码常量)` 为键；健康检查用“页对齐 + 取钥成功率 + 抽样行数”，失败即降级 Tier A。
4. **账号识别必须用密码学校验**：能用该库的 key 解开，才算账号匹配。
5. **仍需隐私评审**：取钥是读进程内存，必须在产品里做成显式、可解释、可拒绝的动作。

---

## 12. 隐私

- 未落盘任何内存转储；读取只在进程内完成。
- 密钥仅写入本地临时 JSON，用完即删，不入库、不入 Git。
- 运行时数据库与导出结果被 `.gitignore` 覆盖（`*.db`、`*.db-*`）。
- 本文与脚本不含真实消息、昵称、wxid 或密钥。

---

## 附录：实测证据

| 指标 | 数值 |
| --- | --- |
| 数据库 | 22 个 / 约 81 MB |
| 密钥验证 | 22/22 |
| 解密导出 | 22/22（失败 0） |
| 完整性 | 19 个 `ok`，3 个 FTS `n/a(fts)` |
| 取钥耗时 | 2.0 s |
| 解密耗时 | 12.4 s |
| `message_0.db` | 48 会话 / 16 015 条 |
| `message_1.db` | 3 331 行 |
| Markdown 导出 | 53 会话 / 19 159 条 / 3.4 MB |
| 快照 | db + wal + shm，80 MB |

随附脚本：

- [`wechat4_extract_keys.py`](./wechat4_extract_keys.py)
- [`wechat4_decrypt.py`](./wechat4_decrypt.py)
- [`wechat4_export_md.py`](./wechat4_export_md.py)
