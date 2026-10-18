# 微信 4.x 本地库解密：22/22 打通的完整路径

> **类型**：Tier B 可行性 spike（`Plan.md` R-08 / `requirement.md` REQ-006）
> **日期**：2026-10-18（复核更新）
> **状态**：**已打通**。22 个库全部通过页 1 HMAC 校验，19 个完整导出且 `integrity_check = ok`，消息内容可读。
> **脱敏**：本文与随附脚本不含真实消息、昵称、wxid、密钥、绝对路径。

---

## 0. 更正声明（前一版结论作废）

本文件早前版本给出的结论是「4.1.13.65 只能通过 hook 获取密钥」。**该结论错误**，现予撤回。错误来自三处方法问题：

| 问题 | 事实 |
| --- | --- |
| 验钥函数从未做阳性对照 | 现已用 SQLCipher 4 自制库验证：passphrase→PBKDF2(256000)→raw key→`verify()` 通过，错误密钥被拒 |
| 把 `cipher_memory_security` 当作“密钥混淆存储” | SQLCipher 官方语义是内存锁定/清理，不能推出密钥被加密；此解释作废 |
| 只在内存里找“值” | 密钥材料真实形态是**结构 + XOR 掩码**，值扫描从设计上就不可能命中 |

真正的机制见第 4 节。此前 4000 万级候选全灭，不是参数错，而是**假设错**。

---

## 1. 结论

| 项 | 结果 |
| --- | --- |
| 密钥形态 | 每库 32 字节 **raw key**（不是 passphrase，也不是主密钥派生） |
| 缓存位置 | WCDB 运行时对象 `com.Tencent.WCDB.Config.Cipher` 引用的数据块 |
| 混淆方式 | 数据块用 **24 字节 XOR 掩码**混淆，解开后是 `x'<64hex>…'` 文本 |
| 获取方式 | **纯只读**：`ReadProcessMemory` + 结构遍历，无注入、无 hook、无写入 |
| 验证 | 22/22 库页 1 HMAC 通过 |
| 解密 | 19/22 完整导出，`integrity_check = ok`；3 个 FTS 库受虚表限制 |
| 消息规模 | `message_0.db`：48 个会话表 / 16 015 条消息，正文可读 |

---

## 2. 环境

| 项 | 值 |
| --- | --- |
| 客户端 | 微信 4.1.13.65（Windows x64） |
| 进程 | `Weixin.exe`，约 1.17 GB 可读内存 |
| 数据根 | `%USERPROFILE%\Documents\xwechat_files\` |
| 数据库 | 22 个 `.db`，合计约 81 MB |
| 账号一致性 | 从 cfg 读出的 wxid 与数据库目录名**一致**（已核对，避免“选错账号”伪失败） |
| 权限 | 普通用户，未提权 |

---

## 3. 容器格式（已验证）

- SQLCipher 4：AES-256-CBC、HMAC-SHA512、页 4096、reserve 80（IV 16 + HMAC 64）。
- 无自定义文件头，前 16 字节即 salt，每个库独立。
- 页 1 布局：`salt(16) | 密文 | IV(16) | HMAC(64)`。

验钥函数（与随附脚本一致）：

```python
mac_salt = bytes(b ^ 0x3A for b in salt)
mac_key  = PBKDF2-HMAC-SHA512(enc_key, mac_salt, 2, 32)
ok       = HMAC-SHA512(mac_key, page1[16:4032] || uint32_le(1)) == page1[4032:4096]
```

### P0 阳性对照（必须先做）

| 用例 | 结果 |
| --- | --- |
| passphrase → PBKDF2(256000) → `verify()` | ✅ True |
| 同一库，随机 32 字节 → `verify()` | ✅ False（正确拒绝） |
| raw key 库 → `verify()` | ✅ True |
| SQLCipher C 库用派生 key 打开 | ✅ 成功 |

阳性对照通过后，后续所有「0 命中」才具备判据意义。

---

## 4. 密钥的真实形态

WCDB 不会把密钥裸放在堆上，而是：

1. 进程里存在唯一一处 `com.Tencent.WCDB.Config.Cipher` 字节串；
2. 由它出发可定位一个运行时节点（`addr,len` 对 出现 163 次）；
3. 节点 `+0x28` 指向配置对象，对象 `+0x88` 是一个 `{ptr,len}` 缓冲；
4. 该缓冲被 **24 字节掩码** XOR 混淆；
5. 解开后是一段 `x'<64 hex>…'` 文本，前 64 位 hex 即该库的 32 字节 raw key。

掩码（来自参考实现的常量）：

```
d2 c7 44 24 58 02 00 00 00 48 89 44 24 50 48 8b 45 00 48 84 4c 24 48 48 89 44 25 40
```

**关键点**：掩码解开前，密钥既不是裸 32 字节，也不是可读 hex 串。这就是值扫描失败的根因。

---

## 5. 提取链路与诊断计数

```
[CHECK] verifier_positive_test: PASS
[SCAN] main_process_found: YES
[SCAN] config_cipher_needles: 1
[SCAN] pair_hits: 163
[SCAN] nodes_ok: 163
[SCAN] blobs: 162
[SCAN] hex_literals: 162
[SCAN] unique_candidates: 54 ~ 81   （多次运行有波动，属正常）
[VERIFY] verified_dbs: 22/22
```

计数分层的价值：失败时能立刻判断卡在“找对象 / 解析结构 / 解掩码 / 校验”哪一层。本次一次通过。

---

## 6. 为什么此前 4045 万候选必然失败（方法论复盘）

| 此前的尝试 | 覆盖 | 为什么不可能命中 |
| --- | --- | --- |
| `x'<hex>'` 正则扫描 | 1.17 GB | 该字符串只在 XOR 解密**之后**存在，内存里从来没有 |
| 所有裸 hex 串当密钥 | 7 676 个 | 同上，hex 被掩码打乱 |
| salt 邻近 ±8 KB 穷举 | 55 处 salt / 88.9 万窗口 | key 与 salt 不在同一结构里 |
| 全内存 8 字节对齐爆破 | 4 045 万窗口 | 裸 32 字节 key 根本不存在 |

结论：在 4.x 上要**找结构**，不要**找值**。这条经验对后续版本适配同样成立。

---

## 7. 解密与验收

- 快照：`db` + `db-wal` + `db-shm` 三件套一起复制，避免丢最新消息。
- 打开：`PRAGMA key = "x'<hex>'"`（raw key 语义，不再做 KDF）。
- 验收：`integrity_check = ok`，表结构可读，正文为可读文本。

| 结果 | 数量 | 说明 |
| --- | --- | --- |
| 解密成功且完整性 ok | 19 | 含 `message_0/1`、`contact`、`session`、`sns` 等 |
| 失败 | 3 | `message_fts` / `contact_fts` / `favorite_fts` |

3 个 FTS 库失败**不是密钥问题**：`sqlcipher_export()` 无法复制虚表（FTS5）。如需它们，应改为“按页解密后直写”，或本次先跳过（FTS 只是索引，可重建）。

消息表命名：`Msg_<md5(username)>`；`session.db::SessionTable.username` 与 `contact.db::contact` 可还原会话名。实测 `message_0.db` 解出 48 个会话、16 015 条消息。

---

## 8. 限制与版本敏感性

| 限制 | 说明 |
| --- | --- |
| 必须客户端在运行且账号已登录 | 密钥缓存在运行时对象里，退出即消失 |
| 版本敏感 | 节点偏移（`+0x28`、`+0x88`）与掩码常量随版本可能变化，需按版本重采 |
| 只读但有前提 | 仅 `ReadProcessMemory`，不写进程；但需要同用户权限 |
| FTS 库 | 需另走页级解密 |
| 账号对应 | 必须用密码学校验决定账号，不能靠 `.db` 修改时间（微信更新会重写全部库） |

参考实现（`wechatauto-replica`）的 Issue #3/#4 在 4.1.12.55 上报告失败，常见原因是账号目录错配；本次先核对 wxid 再取钥，规避了该问题。

---

## 9. 复用步骤

```powershell
# 1) 取密钥（只读，客户端需运行并已登录）
python wechat4_extract_keys.py --db-dir "C:\Users\<user>\Documents\xwechat_files\<wxid>\db_storage" --out keys.json

# 2) 复制三件套后解密
python wechat4_decrypt.py --db-dir "<snapshot dir>" --keys keys.json --out .\plain

# 3) 用完删除 keys.json
```

随附脚本：

- [`wechat4_extract_keys.py`](./wechat4_extract_keys.py)
- [`wechat4_decrypt.py`](./wechat4_decrypt.py)

---

## 10. 与 QQ 的对比

| 维度 | QQ NT 9.9.33 | 微信 4.1.13.65 |
| --- | --- | --- |
| 容器 | 1024 字节自定义头 + 4096 页 | 无头，标准 SQLCipher 页 |
| 密钥 | 16 字符 passphrase | 每库 32 字节 raw key |
| 获取 | 调试器断点读 `R8` | 只读内存结构 + XOR 解掩码 |
| 是否需重启客户端 | 是 | 否 |
| 是否需注入 | 否 | 否 |
| 解密产物 | 可直接导出 Markdown | 可直接导出结构化数据 |

两者都不违反「不 hook、不注入」约束。

---

## 11. 隐私

- 未落盘任何内存转储；读取仅在进程内完成。
- 密钥只写入本地临时 JSON，用完即删，不入库、不入 Git。
- 运行时数据库与导出结果被 `.gitignore` 覆盖（`*.db`、`*.db-*`）。
- 本文不含真实聊天内容、昵称、wxid 或密钥。
