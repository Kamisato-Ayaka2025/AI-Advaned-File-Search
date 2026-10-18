# 微信 4.x 本地库：容器格式与解密路径实测

> **类型**：Tier B 可行性 spike（`Plan.md` R-08 / `requirement.md` REQ-006）
> **日期**：2026-10-18
> **结论**：**容器格式已确认，密钥获取在当前版本上未打通**。4.1.13.65 已不再把库密钥以明文形式常驻进程内存，纯只读内存扫描无法恢复；可行路径只剩 hook / 注入或维护良好的原生组件，与 `AGENTS.md`「排除 hook 与注入」冲突 → 微信在 MVP 阶段应保持 Tier A。

---

## 1. 环境

| 项 | 值 |
| --- | --- |
| 客户端 | 微信 4.1.13.65（Windows x64） |
| 进程 | `Weixin.exe`（主，约 400 MB）+ `WeChatAppEx.exe` × 3 |
| 数据根 | `%USERPROFILE%\Documents\xwechat_files\` |
| 账号目录 | `wxid_<id>_<4hex>\db_storage\` |
| 数据库 | 22 个 `.db`，合计约 81 MB |
| 最大库 | `message\message_0.db` 15.7 MB、`message\message_fts.db` 13.2 MB |
| 权限 | 普通用户（未提权） |

> 与 `requirement.md` 的目标版本 4.1.15.13 不同，需在矩阵中单列。

## 2. 数据布局

```
xwechat_files\
├── all_users\            ← 各账号共享的配置、登录态、头像
└── wxid_<id>_<4hex>\
    ├── db_storage\       ← 全部加密数据库
    │   ├── message\      ← message_0.db / message_1.db / message_fts.db
    │   │                   media_0.db / media_1.db / biz_message_0.db
    │   ├── contact\      ← contact.db / contact_fts.db
    │   ├── session\      ← session.db
    │   ├── sns\          ← sns.db（朋友圈）
    │   └── emoticon\ favorite\ general\ hardlink\ head_image\ ...
    ├── cache\<yyyy-mm>\  ← 图片/视频缓存
    └── business\         ← 收藏、表情等
```

要点：

- **每个库一套独立 salt + 独立 enc_key**（不是一把主钥解全部）。
- 文件大小全部是 4096 的整数倍（实测 22/22），**没有自定义文件头**——这一点与 QQ NT 的 1024 字节头完全不同。
- 消息按会话分表，需解密后才能确认具体表名与分库策略（本次未能验证）。

## 3. 容器格式（SQLCipher 4）

| 参数 | 值 |
| --- | --- |
| 加密 | AES-256-CBC |
| HMAC | HMAC-SHA512 |
| KDF | PBKDF2-HMAC-SHA512，256,000 次 |
| page size | 4096 |
| reserve | 80 字节（IV 16 + HMAC 64） |

首页布局：

```
page1[0:16]        salt（明文，即文件头 16 字节）
page1[16:4016]     密文
page1[4016:4032]   IV
page1[4032:4096]   HMAC-SHA512（截断 64 字节）
```

**密钥验证算法**（无需 SQLCipher 即可快速验证候选密钥，本次扫描全部基于它）：

```python
mac_salt = bytes(b ^ 0x3a for b in salt)
mac_key  = pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=32)
mac      = HMAC-SHA512(mac_key, page1[16:4032] || uint32_le(1))
assert mac.digest() == page1[4032:4096]
```

注意 `mac_salt` 是 salt 每字节异或 `0x3a`，HMAC 迭代只有 **2 次**（不是 256,000）——这使得候选密钥验证非常快，是爆破可行的前提。

## 4. 实测尝试与结果

参考实现：[`328336690/wechat-decrypt`](https://github.com/328336690/wechat-decrypt)（MIT，纯 Python）。其原理是扫描内存中的 `x'<64hex enc_key><32hex salt>'` 字符串。**该形式在本机不存在**。

| # | 方法 | 覆盖范围 | 候选数 | 命中 |
| --- | --- | --- | ---: | --- |
| 1 | 原工具正则 `x'<hex>'` 扫描 | `Weixin.exe` 1.17 GB | 0 | 0/22 |
| 2 | 全部裸 hex 串（64/96 位）当密钥 | 同上 | 7 676 | 0/22 |
| 3 | 已知 salt 反查相邻 32 字节 | 同上（salt 出现 2 次） | — | 0/22 |
| 4 | 库路径字符串 ±1 KB 邻近扫描 | 99 处路径出现 | — | 0/22 |
| 5 | 私有堆 16 字节对齐爆破 | 283 MB | 2 032 947 | 0/22 |
| 6 | **全内存 8 字节对齐爆破** | **1 167 MB** | **40 459 119** | **0/22** |

第 6 项是最强证据：把整个主进程可读内存按 8 字节步长枚举所有 32 字节窗口，用上面的 HMAC 算法逐个验证 `message_0.db`，4045 万候选全部失败。

补充观察：

- `ReadProcessMemory` 完全正常（1 167 MB、0 个区域读取失败），排除权限干扰。
- `message_0.db` 的 salt 在主进程内存中只出现 2 次，附近没有 32 字节密钥。
- 另一个 `Weixin.exe`（18 MB）与 `WeChatAppEx.exe` 中都没有可用的密钥材料。

## 5. 结论

1. **格式层已打通**：SQLCipher 4 参数、页布局、快速验证算法都已确认，后续任何方案只要能拿到 `enc_key`，解密就是几十行代码。
2. **密钥层未打通**：4.1.13.65 不再把 `enc_key` 以 32 字节明文常驻内存。合理推断是 WCDB 做了加固（按需派生、用后清零，或存放于受保护结构），这与 4.0 时代工具的假设不符。
3. **只读路径不可行**：在不注入、不 hook 的前提下，无法在当前版本恢复密钥。
4. **与仓库约束冲突**：`AGENTS.md` 明确「Defer Tier B; exclude hooks, injection, and OCR」。因此微信在 MVP 阶段不应接入真实库。

## 6. 对产品的影响

- **微信保持 Tier A**：走客户端自带导出 / 用户提供文件，符合 `requirement.md` 的 MVP 范围。
- **QQ 与微信不对称**：QQ NT 可以在不注入的情况下完成（取密钥只需调试器附加一次，之后离线解密），微信 4.1.x 不行。版本矩阵里应分别标注，不能合并成一句“Tier B 已验证”。
- **若后续要推进微信**：需要（a）hook `sqlite3_key` 类函数，或（b）引入维护中的原生组件（如 `WeChatDataAnalysis` 的 WCDB 组件，注意其 45 天有效期与闭源风险），或（c）等待官方导出能力。三者都要单独做安全与合规评审。
- **不可承诺**：任何“零操作读取微信”“所有版本通用”的说法在当前证据下都不成立。

## 7. 复用建议

给后续接手者：

1. 先跑格式检查：`文件大小 % 4096 == 0`、首页 16 字节 salt 各不相同。
2. 用第 3 节的验证函数写一个 `verify(enc_key, page1)`，这是后续所有方案的公共判据。
3. 再决定取密钥路线：
   - 只读内存扫描：先在 4.0.x 上验证工具；4.1.13 及以上预期失败（本次已证）。
   - hook / 注入：违反仓库约束，仅可作研究，不进产品。
   - 原生组件：评估来源可信度、有效期、许可证。
4. 客户端升级后必须重跑第 4 节的尝试表，**不要假设上一次的结论仍然成立**。

## 8. 隐私

- 未落盘任何内存转储；扫描全程在进程内读取，未写入磁盘。
- 本文不含真实聊天内容、wxid、密钥或绝对路径。
- 运行时数据库与导出结果被 `.gitignore` 覆盖（`*.db`、`*.db-*`）。
