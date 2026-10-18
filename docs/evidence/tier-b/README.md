# Tier B：QQ / 微信聊天记录 → Markdown

本目录是「把本机 QQ、微信的本地聊天库转成 Markdown」这一能力的**完整实现与证据**。
目标是：换一台电脑、换一个 agent，照着本目录能独立复现全部结果。

> 状态：**数据链路已打通**，QQ 与微信均可导出并集成到 aimem。
> 最后实测：2026-10-18，QQ 9.9.33-52230 / 微信 4.1.13.65 / Windows 10。

---

## 1. 结果

| 指标 | QQ | 微信 |
| --- | ---: | ---: |
| 会话 | 34（19 群 + 15 私） | 53（15 群 + 38 私） |
| 消息 | 2 234 | 19 159 |
| 无正文（系统/撤回） | 409（占位保留） | 363（占位保留） |
| 图片 | 49 条内联（本地缓存） | 521 条内联（505 张解码） |
| 文件 | 58 条链接 | 195 条链接 |
| 契约校验 | 34/34 通过 | 53/53 通过 |

集成侧：aimem 导入 **87 会话 / 21 393 条**，计数与源一致；重复导入 0 新增。

---

## 2. 产物结构

```
<export>/
├── index.md                 # 索引表（aimem 跳过）
├── private/<标题>_<id>.md
├── group/<标题>_<id>.md
└── media/<md5>.jpg          # 微信解码后的图片（QQ 用本地缓存路径）
<export>-ALL.md              # 合并版，必须在导入目录之外
```

文件格式见 [`03-markdown-contract.md`](./03-markdown-contract.md)。

---

## 3. 代码清单

| 脚本 | 行数 | 作用 | 输入 → 输出 |
| --- | ---: | --- | --- |
| [`qqmd.py`](./qqmd.py) | 330 | **统一入口**：编排下列步骤 | 一条命令 → 完整导出 |
| [`ntqq_export_md.py`](./ntqq_export_md.py) | 362 | QQ 解密 + 解析 + 导出 | 加密 `nt_db/` + `NTQQ_DB_KEY` → Markdown |
| [`wechat4_extract_keys.py`](./wechat4_extract_keys.py) | 170 | 微信库密钥（只读内存） | `db_storage/` + 运行中的微信 → `keys.json` |
| [`wechat4_decrypt.py`](./wechat4_decrypt.py) | 111 | 微信库解密 | 快照 + `keys.json` → 明文 SQLite |
| [`wechat4_export_md.py`](./wechat4_export_md.py) | 313 | 微信消息 → Markdown | 明文库（+ 媒体、图片映射） → Markdown |
| [`wechat4_decode_images.py`](./wechat4_decode_images.py) | 102 | V2 `.dat` 解密 + WXGF 转码 | 图片密钥 + 媒体索引 → `media/*.jpg` |
| [`wechat4_find_image_key.py`](./wechat4_find_image_key.py) | 96 | 从进程内存找图片 AES key | 一个已知 `.dat` → 密钥文件 |
| [`wechat_media_index.py`](./wechat_media_index.py) | 102 | 消息 ↔ 本地媒体关联 | 明文库 + `msg/attach` → `media-index.jsonl` |
| [`validate_format.py`](./validate_format.py) | 76 | 契约校验 | 导出目录 → 通过/失败 |

---

## 4. 一条命令（推荐）

```bash
python qqmd.py doctor                       # 依赖 / 客户端 / 账号自检
python qqmd.py wechat all --out ./wechat-markdown
python qqmd.py qq export --nt-db "<...>/nt_db" --out ./qq --my-uin <UIN>
python qqmd.py validate ./wechat-markdown
```

Windows 上可直接双击 `run.cmd`，它只做一件事：检查 Python 后转调 `qqmd.py`。

`wechat all` 自动完成：账号发现 → 取密钥 → 快照 → 解密 22 库 → 媒体索引 →
取图片密钥 → 解码图片 → 导出 Markdown → 契约校验。密钥只在系统临时目录中短暂存在，
结束时删除。

**重复运行是增量的**（实测第二次 2.7 s）：

| 场景 | 行为 |
| --- | --- |
| 数据库签名未变 | 跳过解密与导出 |
| 图片已在 `media/` | 跳过解码，只补缺失 |
| 需要强制重跑 | `--force` |

### Windows 单文件 exe（已验证）

```powershell
powershell -File build_exe.ps1          # 产出 dist\qqmd.exe，约 14 MB
dist\qqmd.exe doctor
dist\qqmd.exe wechat all --out .\wechat-markdown
```

- 构建依赖：`pyinstaller`、`zstandard`、`cryptography`。**不需要 `sqlcipher3`**——
  exe 会自动改用纯 Python 按页解密（`wechat4_decrypt_pure.py`），实测与 sqlcipher3
  结果一致（22/22、integrity ok、16 015 条）。
- `ffmpeg.exe` 可选，放在 exe 同目录即可解 WXGF 图片。
- 实测：完整流程 62 s，53 会话 / 19 161 条，契约校验 53/53。

---

## 4.1 分步执行（调试用）

```bash
pip install sqlcipher3-binary zstandard cryptography   # ffmpeg 需另装

# ── QQ ──────────────────────────────────────────────
# 1) 取密钥（需先退出 QQ，脚本会重新拉起并等待登录）
#    见 01-qq.md 第 4 节
export NTQQ_DB_KEY='<16 字符>'
python ntqq_export_md.py --nt-db "<...>/nt_qq/nt_db" --out ./qq --my-uin <UIN>

# ── 微信 ────────────────────────────────────────────
python wechat4_extract_keys.py --db-dir "<...>/db_storage" --out keys.json
# 复制 db + -wal + -shm 到快照目录后：
python wechat4_decrypt.py --db-dir <快照> --keys keys.json --out ./plain
python wechat_media_index.py ./plain "<...>/msg/attach" ./media-index.jsonl
python wechat4_find_image_key.py --dat <任一个 .dat> --out imgkey.txt
python wechat4_decode_images.py --index ./media-index.jsonl --out ./wx/media \
        --map map.json --key "$(cat imgkey.txt)" --xor-key 0xAC
python wechat4_export_md.py --plain ./plain --out ./wx --me <own_wxid> \
        --media "<...>/msg" --image-map map.json

# ── 校验 ────────────────────────────────────────────
python validate_format.py ./qq
python validate_format.py ./wx
```

耗时（本机实测）：微信取钥 2.0 s、解密 12.4 s、导出 0.68 s、505 张图片解码 55.6 s；QQ 解密+导出 < 5 s（另需人工完成一次 QQ 登录）。

---

## 5. 复现清单（新机器）

```text
[ ] Windows 10/11 x64，管理员非必需
[ ] 客户端已安装并登录过至少一次（QQ NT 9.9.x / 微信 4.x）
[ ] Python 3.10+；pip install sqlcipher3-binary zstandard cryptography
[ ] ffmpeg 在 PATH（微信 WXGF 转码用）
[ ] QQ：按 01-qq.md 取 16 字符密钥，确认 nt_db 路径
[ ] 微信：确认 db_storage 属于当前登录账号（否则密钥全验不过）
[ ] 按第 4 节依次执行，注意腾讯系客户端运行时会占用库，先做快照
[ ] 用 validate_format.py 自查，再用客户端「消息管理器」核对量级
[ ] 密钥只放环境变量/临时文件，用完删除，不要提交
```

各步骤的失败表现与处置见 [`04-troubleshooting.md`](./04-troubleshooting.md)。

`--work` 指定中间目录（快照、明文库、状态文件 `.qqmd-state.json`），默认在输出同级的
`qqmd-work/`，可安全删除后重建。

---

## 6. 文档地图

| 文件 | 内容 |
| --- | --- |
| [`01-qq.md`](./01-qq.md) | QQ NT：数据定位、容器格式、取密钥、解密、字段表、媒体、导出 |
| [`02-wechat.md`](./02-wechat.md) | 微信 4.x：容器格式、密钥结构与 XOR 掩码、解密、消息/媒体、图片 V2 与 WXGF |
| [`03-markdown-contract.md`](./03-markdown-contract.md) | Markdown 契约、媒体索引 schema、校验规则、aimem 导入行为 |
| [`04-troubleshooting.md`](./04-troubleshooting.md) | 失效模式、版本敏感性、环境坑、隐私边界 |

---

## 7. 已知缺口

| 项 | 说明 |
| --- | --- |
| 合并转发未展开 | 微信 47 条，payload 里有 `<recorditem>`，可解析但未实现 |
| 引用原文未回填 | 微信 567 条，`<refermsg>` 有被引内容，只输出了新消息 |
| 视频未关联 | 微信 59 条（≥14 条可通过 `video_hardlink_info_v4` 定位）、QQ 1 条 |
| 图片未关联 | 微信 359 条（本地无缓存或未匹配）、QQ 130 张 |
| 语音 | 未处理（按需求忽略） |
| 增量导出 | 目前每次全量重写；DB 有单调 `sort_seq`，可做水位线增量 |
| 独立可执行程序 | 目前是脚本集合，需按本文件手工执行 |

> 产品化（语义检索、UI、跨来源）不在本目录范围，见仓库 `Plan.md`。
