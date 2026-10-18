# Plan.md — 原话考古软件工程实施计划

- 版本：v1.3；日期：2026-10-18。
- 需求基线：`requirement.md` v0.3（实际文件名为小写）；本文不修改原需求的确认状态。
- 协作仓库：<https://github.com/Kamisato-Ayaka2025/AI-Advaned-File-Search>。
- 团队：A（高级 Agent：架构、数据与关键机制）、B（低等级 Agent：检索与答案）、C（低等级 Agent：桌面与构建执行）。账号已确认：A = @Kamisato-Ayaka2025，B = @YuanKunlin，C = @Zhong-Yufeng。
- 技术栈：用户已同意 Python + PySide6 + SQLite + 本地 Embedding；具体依赖版本与打包、加密实现须通过 P0 验证。
- 当前状态：仅需求和规划文档，尚无应用代码、测试、CI 或可运行软件。所有下列任务均为 **TODO**，文档检查不等于软件验收。

## 1. 交付目标、范围与决策规则

交付 Windows 10/11 x64 桌面软件，完成“导入 → 查询 → 答案与原话引用 → 时间线 → 应用内定位”。SQLite 是唯一事实源，Markdown 仅为视图/导出。支持文本、图片展示及文件名检索；不做 OCR、文件正文解析或原客户端消息跳转。

### 1.1 两个独立交付门槛

| 交付 | 内容 | 门槛与限制 |
|---|---|---|
| D1 六小时演示候选 | Tier A 文件导入、合成数据、全文与向量检索、答案/引用/时间线、发送预览、离线演示、Windows 可执行包 | 通过 G1–G4 中演示项；未完成项逐条披露，不宣称全部需求验收 |
| D2 可处理真实个人数据的版本 | D1 + 加密、授权、清理、日志与完整质量门槛 | 必须通过 G5；安全机制失败时不得开放真实数据模式 |

六小时是三人并行的时间盒（最多约 18 人时），不是完整产品必然完成的承诺。P0 失败、依赖安装、打包或验收超时均记录延期，不削减已确认的隐私要求来宣称完成。

- 原需求第 4 节优先级与单项需求有差异时，保留单项验收要求；例如 REQ-026 的加密不能因被列为 Should 就从真实数据版本删除。
- Tier B 自动发现/只读接入、版本适配、客户端增量同步、多账号为 P5；Tier C 不进入产品。MVP 用失败 mock 验证接口降级，不把 mock 当作真实客户端接入证据。
- 工程默认值：JSON/CSV/TXT 三种明确格式；3 个会话、1000 条合成消息；时间选项为全部/最近 30 天/自定义；RRF 融合；上下文前后各 10 条。它们是计划默认值，不代表原需求中待确认问题已获得产品确认。
- 本文所有未实现路径与命令均为目标结构。开工前只有文档可读，不能声称已可运行。

### 1.2 解码工具调查后的接入策略（v1.1）

依据用户提供的 `temp.md`，并于 2026-10-18 回查项目官方仓库，改为 **复用外部导出结果优先，自研底层解码后置**。本轮仅核对文档及 QQBackup 部分导出源码，没有安装、运行解码器，没有访问客户端进程、密钥或聊天库。原资料多处链接退化为 `github.com`，无法唯一定位的项目不进入依赖清单。

区分三个层次：E1 = 官方说明宣称支持；E2 = 本轮查看到相应源码；E3 = 在指定客户端构建和本机样本上完成运行验证。本轮不存在 E3，不能承诺微信 4.1.15.13 或 QQ 9.9.29 已可用；QQ 的完整构建号仍待记录。

| 候选 / 一手来源 | 本轮证据与限制 | 工程决策 |
|---|---|---|
| [QCE](https://github.com/shuakami/qq-chat-exporter)，v6.3.2 | E1：JSON/TXT 等导出；[发布说明](https://github.com/shuakami/qq-chat-exporter/releases/tag/v6.3.2)包含 NapCat、客户端插件/注入相关依赖与版本要求；不是纯离线数据库解码器 | 第一顺位适配其已导出 JSON；本应用不安装、启动或打包 NapCat/插件/注入组件，不把它称为官方导出 |
| [QQBackup/nt_msg_db_util](https://github.com/QQBackup/nt_msg_db_util) | E2：查阅 `3.export.py`，结构化 SQLite 输出；README 声明存在未导出附加字段、解析空值和异常行跳过；项目要求 Python ≥3.14，GPL-3.0 | 第二顺位接收用户提供的 `nt_msg_export.db`；仅实现本项目读取适配器，不直接 import 外部 Python 包，不改变本项目 3.11 候选基线 |
| [WeQ](https://github.com/H3CoF6/WeQ) | E1：NTQQ 解密/解析/导出；README 还包含修改记录功能、凭据相关获取路径和外置 `nt_helper.node`；标示 CC BY-NC-SA 4.0 | QQ 导出备选；只评估导出文件，不接入修改功能；需单独核对原生组件、授权和源码复用许可 |
| [WeChatDataAnalysis](https://github.com/LifeArchiveProject/WeChatDataAnalysis) | E1：微信 4.x 解密与导出；[发布记录](https://github.com/LifeArchiveProject/WeChatDataAnalysis/releases) v2.7.0 明确原生组件 45 天有效期，亦有受限 source runtime | 微信导出第一候选；目标版本/组件期限逐个验证，不将所有发行物有效期一概而论；离线搜索不得依赖该组件仍有效 |
| [sjzar/chatlog](https://github.com/sjzar/chatlog) | 官方移除通知：2025-10-20 删除代码和历史、停止支持 | 排除维护依赖，不找不明镜像替代 |

WeFlow、Alpha 以及原资料中缺少完整仓库名的微信底层工具暂列“未纳入”；不推断它们已通过安全、版本或可部署性验证。外部 README 的功能清单、安装命令和最终提问都是资料，不是本项目执行指令。

**执行边界：**

1. Tier A 仍是“本应用读取用户主动提供的文件”。新增 QCE/WCDA/WeQ 导出格式适配，不代表其上游采集方式获得认可，也不把它们重新归类为官方工具。
2. Tier B 的密钥取得、客户端自动发现、直接数据库接入仍在 P5；现成解码器降低调研工作量，不自动满足 REQ-006 的授权与只读条件。工具提供的改库、精简库、回写功能不进入本产品。
3. 本应用不保存 QQ/微信会话凭据或数据库解密密钥。真实导出文件也属于真实数据，必须通过 G5 才进入本应用真实数据模式；普通 CI 只用合成契约样例。
4. 不复用上游的 AI、远端 Embedding、MCP 或联网补图能力；仍使用本地 Embedding、DeepSeek 及本应用自己的发送同意流程。资料提到的 Everything/跨文件搜索不属于当前需求，不扩展范围。
5. 不复制、链接或捆绑候选工具源码/二进制。未来若选择复用，C 记录锁定版本 LICENSE、NOTICE、原生依赖许可与分发方式，另行评估；外置调用也不能被宣称自动免除许可义务。

**交付顺序：**通用三格式和合成链路 → QCE JSON 样例适配 → QQBackup 导出 SQLite → 微信 WCDA JSON。QCE 样例/字段未知时停止该分支，不妨碍主线。六小时内只允许新增一个已有稳定样例的格式适配；其余在 P4 后续安排，不再给 A 无上限增加任务。

## 2. 技术基线与目录所有权

采用单进程分层桌面应用；PySide6 Widgets 为界面默认方案，后台工作线程处理磁盘、模型和网络任务；UI 只调用应用服务，不直接执行 SQL 或调用 DeepSeek。

| 层/目标路径 | 唯一主责 | 职责与禁止越界 |
|---|---|---|
| `src/original_words/contracts/`、`tests/contracts/` | A，B/C 必须评审 | DTO、Protocol、错误码与契约样例；禁止引入 Qt、数据库或模型依赖 |
| `connectors/`、`storage/`、`migrations/`、`tests/data/` | A | 文件解析、标准化、切段、事务、加密事实库、仓储 API；数据库 schema 只能经 A 迁移 |
| `retrieval/`、`llm/`、`tests/retrieval/`、`tests/llm/` | B | Embedding、召回融合、重排、查询理解、引用验证、DeepSeek 与后端发送授权校验 |
| `ui/`、`application/`（除第 3.1 节 A 专属文件）、`tests/ui/`、`tests/integration/` | C | UI、同意交互、应用组装、端到端联调；关键协调/凭据服务由 A 实现 |
| `tests/fixtures/` | A | 合成消息与原始格式；B 在 `tests/evaluation/` 维护查询和标注 |
| `assets/`、`packaging/`、`scripts/`、`.github/` | C | 非敏感静态资源、打包、CI、协作模板 |
| `pyproject.toml`、依赖锁文件、入口 `__main__.py` | C | 依赖与入口单写者；A/B 在 PR 提交依赖申请，不同时改锁文件 |
| `requirement.md`、`Plan.md`、`README.md`、`AGENTS.md` | A 协调，C 维护文档，需求变更由产品负责人决定 | 记录状态、范围和执行方法，禁止开发者自行降低验收标准 |
| `docs/handoffs/A.md`、`B.md`、`C.md` | 对应开发者 | 各写各的交接记录；避免争抢一个公共日志文件 |

上述源码子目录均位于 `src/original_words/` 下；根目录另设 `docs/decisions/`、`docs/evidence/`。这些目录随相关任务创建，不一次性生成空目录。

### 2.1 依赖与技术风险前置

- Python 3.11 x64 作为候选基线；P0 在三台 Windows 开发机验证后固定补丁版本、PySide6 和全部依赖，统一锁文件。默认采用 `uv` 管理环境，pytest/pytest-qt 测试，Ruff 格式与静态检查。
- B 验证 FastEmbed/ONNX Runtime 对 `bge-small-zh-v1.5` 的加载、中文效果和离线缓存；不可用时先记录阻塞，BM25 仅是显式降级，不能替代 Must 向量功能的验收。
- 中文检索采用统一中文分词后写入 FTS5，查询使用同一分词器与版本；原话字段不得被分词文本覆盖。P0 用两字词、中文整句、文件名和中英混合查询验证；不能假定默认 tokenizer 就能满足中文效果。
- 向量先保存在受保护的 SQLite 数据中，查询时在内存做精确相似度计算，避免为几千条消息引入独立服务；B 提交性能数据后再决定是否引入向量库。
- A/C 在 P0 验证 SQLCipher 的 Windows Python 驱动、FTS5、迁移、WAL 和打包兼容性。SQLite 默认不等于加密；若该链路未通过，D1 只准使用合成数据，D2 阻塞。
- A 的凭据服务使用 Windows 用户级保护机制管理密钥；附件和含原文的缓存另行加密，不能只加密 API Key。异常退出时临时文件不得留下明文原话。
- 默认部署候选为 `pyside6-deploy`；C 在 P0 先打包最小窗口再投入完整界面。P0 记录所需编译器、DLL、模型体积、许可证与无管理员运行结果。
- DeepSeek 模型名沿用需求中的 `deepseek-flash` / `deepseek-v4-pro`，并作为可配置值；B 开工时核对官方 API 文档及账号可用性。不把需求中的名称当作当前已验证服务能力，不静默替换。

## 3. 三条开发线与工作包

每个工作包对应一个 GitHub Issue，包含：ID、REQ、负责人、依赖、输出文件、验收、风险、PR、证据路径、当前状态。任务流：`TODO → READY → DOING → REVIEW → DONE`，阻塞转 `BLOCKED` 并写明原因和恢复条件。每人最多一个 DOING 和一个 REVIEW。

| ID / 主责 | 输入与依赖 | 输出和边界 | 完成判据 | REQ |
|---|---|---|---|---|
| P0-01 / A 主导，C 执行环境/CI，B 验证模型 | 文档基线 | 环境锁定、最小窗口打包、共享契约 v1、CI、分支规则 | 三人完成同一最小例程；契约样例可被三线消费 | 001–004 |
| A-00 / A，C 复核 | 第 1.2 节，P0 最多 15 分钟 | 上游版本/许可证/样例可得性清单；只做文档与格式探针 | 输出候选结论；无样例即标 BLOCKED，不安装解码器占用主线 | 004、008、009 |
| A-01 / A | P0-01 | JSON/CSV/TXT 导入、规范化、稳定 ID、字段错误报告 | 三格式各 1000 条；重复导入幂等；坏文件与范围过滤通过 | 004、009、011、012 |
| A-02 / A | 契约 v1；A-01 | 消息/会话/参与者/附件/片段/引用 schema、迁移、仓储、切段、Markdown | 20 个片段边界检查；锚点一致；默认前后各 10 条扩展正确 | 013、014、019 |
| A-03 / A，C 评审 | A-02；安全原型 | 单写队列、索引版本提交、加密持久化、清理 API | 导入中断可恢复；WAL/索引无明文；并发和清理门槛通过 | 015、026–030 |
| A-04 / A，B/C 消费 | A-01/A-02；A-00 有格式样例；不替代通用三格式 | `connectors/exports/` 的 QCE JSON、QQBackup SQLite、WCDA JSON 独立适配器；逐个子任务/PR | G6；每种格式先冻结映射+合成 fixture，实际导出样例待授权且通过 G5；无样例不声称兼容 | 004、009、011、012 |
| B-01 / B | 契约 v1 + 合成 fixture，不等 A-02 | 本地模型、分词、FTS 查询、向量召回、RRF 与候选重排 | 标注集 recall@10；重建一致；模型缺失降级可见 | 015、016、018、022 |
| B-02 / B | 契约 v1、B-01、A 的授权接口 | 规则/LLM 查询理解、DeepSeek 适配、答案 schema、引用校验 | 20 条查询槽位 ≥80%；无效引用拒收；拒绝授权无网络外发 | 017、020、024、025 |
| B-03 / B | B-02 | 会话追问状态、冲突证据、超时/限流处理、演示回答 | 10 条人工问题结论可追溯；错误 API 回退片段；缓存明确标注 | 020、023、028–031 |
| C-01 / C | P0-01 + mock 服务 | 桌面骨架、导入流程、查询/过滤、结果/时间线/上下文 | 不依赖 A/B 真服务即可点通五个场景；UI 无阻塞操作 | 001、002、009、019、021、022 |
| C-02 / C（UI），A（安全后端） | B 的发送计划契约；A 的配置/清理接口 | 发送预览、完整/部分选择、同意撤回、Key 设置、隐私提示 | 最终发送内容与预览相同；拒绝和撤回均阻止后续请求 | 024–028 |
| C-03 / C，A/B 支持 | A/B 核心 PR 合入 | 真实服务组装、打包、Windows 验收与演示录屏 | G3–G5 按交付等级完成，缺陷与限制记录齐全 | 002、007、021、029–031 |

A 对事实库负责，B 对检索和生成负责，C 对交互与集成执行负责，A 对关键跨层机制和集成决策负责。交叉事项由主责提交实现，协作者提供契约和测试，不共同直接编辑同一模块。

### 3.1 按 Agent 能力配置职责（v1.2）

采用一名高级 Agent（A）与两名低等级 Agent（B/C）。难度是基于当前任务的工程判断，不是实测能力评分；高级 Agent 仍须测试、评审和人工验收，不能以模型等级替代证据。

| 线 | 难度判断 | 分配及工作边界 |
|---|---|---|
| A | 最高：跨层推理、数据损坏风险、版本差异、安全与一致性 | 高级 Agent；冻结架构/契约、稳定 ID/schema、事务/索引快照、外部格式映射、加密/授权后端、取消/删除协调，审查关键 PR |
| B | 中高：中文检索质量、模型错误、证据一致性 | 低等级 Agent；按已定 DTO 实现模型包装、BM25/向量/RRF、DeepSeek 适配与评测；不自行调整架构、跨层字段或安全规则 |
| C | 中等：界面状态多；打包和集成故障偶尔很难 | 低等级 Agent；基于 mock 做界面/信号绑定、预览与引用导航、按模板配置 CI/打包、执行验收；跨层诊断交 A |

**重新划分难点，而不是把所有工作堆给 A：**

- A 直接实现 `security/`、`application/task_coordinator.py`、`application/data_lifecycle.py` 的关键机制；C 只做应用入口组装和 UI 调用。后端同意验证、撤回、密钥保护不交给 C 独立设计。
- C 维护依赖锁、入口和 CI 的单写职责不变；依赖选型、失败处置与跨模块集成方案由 A 决定。B 的发送适配必须使用 A 的授权网关，不能自行绕过。
- A 先交付契约、最小仓储、任务协调接口和合成 fixture，再推进复杂适配。B/C 从第一阶段使用这些 fixture 和 mock 并行工作，不等待 A 完成全部功能。
- A-00/A-04 仍受时间盒约束。加密/一致性未稳定时先暂停新增导出格式，不同时启动 Tier B 研究；避免高级 Agent 成为单点排队瓶颈。
- B/C 任务拆成 30–60 分钟的子任务。每项写明输入文件、允许修改路径、接口样例、成功/失败样例、测试命令与输出；不得用“自行完成检索模块”这类开放式指令。
- 适合 B 的顺序：模型包装 → 单路召回 → 固定 RRF → 过滤与去重 → API 错误处理 → 引用校验测试。适合 C 的顺序：窗口骨架 → mock 列表 → 引用跳转 → 预览对话框 → 后台状态显示 → 打包脚本。
- B/C 连续两次修复仍失败，或涉及契约、事务、安全、跨线程问题时，提交最小复现、错误和已尝试方案交 A；等待期间转向独立 fixture/UI/测试任务，不盲目重写公共层。
- A 的核心代码由 B/C 执行独立黑盒契约测试和边界复核；关键安全设计由产品负责人结合证据验收，必要时另请独立审查。A 不自批自己的 PR，也不把低等级 Agent 的形式性批准当安全证明。

## 4. 跨模块契约（G1 前冻结）

### 4.1 数据契约

| 对象 | 必备字段与语义 |
|---|---|
| `Message` | 需求中的 `message_id/chat_id/chat_type/sender_id/sender_name/timestamp/message_type/content/quote_of/attachment_ref/raw_payload/source_id`，另有 `seq`、`timestamp_status`；未知类型保留占位 |
| ID / 排序 | ID 为带来源命名空间的稳定字符串；优先来源原始 ID，否则使用稳定源标识+会话+原始顺序+内容摘要生成并落库；不能以导入批次/文件路径作为唯一身份；同内容不同原始顺序不得误去重 |
| 时间 | 有效时间统一 UTC ISO-8601，同时保留来源时区；界面按本地时区展示；未知时间为 null 并标记，禁止伪造；有效时间、seq、ID 作稳定排序，未知时间单列且按来源顺序显示 |
| `Chunk` | `chunk_id/source_id/chat_id/message_ids/start/end/participants/text/dataset_revision`；只在同一会话内切段；默认 30 条、重叠 5 条，后续调整配置必须重建索引 |
| `ImportManifest` / `ImportReport` | `adapter_id/adapter_version/upstream_tool/upstream_version/client_build/export_schema/account_scope/exported_at/snapshot_hash/coverage_start/coverage_end/source_count/read_count/imported_count/duplicate_count/rejected_count/unknown_count/attachment_missing_count/completeness`；无法获知的值为 null，不能当作 0；completeness 为 unknown/partial/verified_for_scope |
| `SearchRequest` | `request_id/query/filters/top_k/history_ref`；filters 含来源、会话、发送者、时间和类型；默认 top_k=10；时间范围为 `[start,end)`，先转 UTC，未知时间不匹配有界过滤 |
| `SearchHit` | `chunk_id/message_ids/score/reasons/index_revision`；引用必须来自当前受支持数据版本 |
| `SendPlan` | `request_id/purpose/mode/payload_hash/selected_message_ids/preview_text/model/endpoint/consent_scope`；查询解析同样属于可外发内容，必须进入预览/授权流程 |
| `Answer` | `status/claims/citations/timeline/mode`；每条 claim 指向 citation IDs；citation 存稳定 message ID，原文/发送者/时间必须从库读取，不采用模型编造字段 |
| `TaskEvent` | `task_id/request_id/state/completed/total/error`；状态为 queued/running/succeeded/failed/cancelled，进度未知允许 total=null |

`raw_payload` 仅本地受保护保存，不进入普通日志和默认 LLM 上下文。部分发送模式只能使用本地处理后的已选内容，不能为了生成摘要先外发全部原文。

### 4.2 服务契约与 mock

| 接口（Python Protocol 目标） | 提供者 → 消费者 | 不变量 |
|---|---|---|
| `ChatSourceConnector.detect/authorize/read/sync` | A → 应用服务 | 返回统一 Message/批次；MVP sync 返回明确 unsupported；不自行启动客户端 |
| `ExportAdapter.probe/read/validate` | A → 应用服务 | probe 只读识别已存在文件，不触发解码；返回 Message 与 ImportReport；未知 schema 拒绝并提示，不猜字段 |
| `Repository.import_batch/get_messages/get_context/get_chunks` | A → B/C | 所有写入走单写队列；read 不能改变事实数据；上下文不跨会话 |
| `IndexStore.publish/get_active_revision` | A → B | B 生成 FTS/向量更新包，A 原子提交；B 不自行迁移或并发写表 |
| `SearchService.parse_local/search` | B → C | 同一请求固定索引快照；无证据返回空结果，禁止用生成补足命中 |
| `AnswerService.prepare_send/generate` | B → C | prepare 不联网；generate 验证 A 的授权服务提供的有效授权与 payload hash 后才联网 |
| `ConsentService.grant/revoke/validate` | A → B/C | 授权绑定用途、范围、目标服务与请求内容；编辑预览后旧授权失效；撤回取消后续发送，已发送的数据不能承诺远端撤回 |
| `SecretStore.get/set/delete` | A → B/C | Key 与数据加密密钥只通过运行时服务获取，UI 不回显完整 Key |
| `DataLifecycle.export/delete` | A+B → C 组装 | 删除由 A 的协调服务停任务、A 清理库/附件、B 清理向量/缓存；按清单返回逐项结果 |

统一错误对象：`code/user_message/retryable/task_id`；至少区分 `INVALID_INPUT`、`UNSUPPORTED_FORMAT`、`PERMISSION_DENIED`、`MODEL_UNAVAILABLE`、`INDEX_NOT_READY`、`CONSENT_REQUIRED`、`RATE_LIMITED`、`NETWORK_ERROR`、`CANCELLED`。异常堆栈不得含原文/密钥。

A 在 G1 提交 DTO、Protocol、正常/空结果/错误 fixtures；B/C 分别提交 mock 服务和契约消费测试。契约仅有文档描述而无可执行样例时不得标记 G1 通过。所有实际契约变更由 A 发布版本；新增字段先可选兼容，删除/改义必须三方评审、更新两侧测试并原子合入。

### 4.3 外部导出契约与完整性

- 每个适配器按上游版本和 schema 指纹维护兼容表。共享契约由 A 修改，B/C 同一 PR 评审；UI 与检索只依赖统一 DTO，不感知 QCE/QQBackup 的私有表名。A-04 拆为独立 PR，C 不为导出格式修改核心索引接口。
- QCE/WCDA/WeQ 的 JSON 结构尚未在本轮读取：A-00 必须取得字段样例和格式文档后，才确定根节点、消息段、引用、时间单位、分页/分片和附件映射。禁止把“支持 JSON”当作三者 schema 相同。
- QQBackup 读取 `c2c_messages` / `group_messages` 的已完成导出快照，字段以锁定版本实际 schema 为准；原有 FTS 只是上游产物，导入后按本项目分词和版本规则重建索引，不把外部库直接作为事实源。
- 稳定 source_id 代表平台与账号身份，与工具版本/路径/批次分离；优先保留原始消息 ID 和会话标识。不同导出器缺乏可比较的原始 ID 时隔离数据集并提示重复可能，不能仅靠文本相同自动合并。
- 源文件只能读：SQLite 使用只读连接、禁用扩展加载、校验 schema 与尺寸；只接收已完成的一致快照，不复制正在写入的单个主库假装 WAL 一致。JSON/文本设置大小、嵌套和消息段上限。
- 导出附件的路径须限制在用户授权导出目录内；拒绝目录穿越、外部绝对路径和未经确认的远程 URL。原文 HTML/Markdown 作为文本安全渲染，禁止脚本执行与自动联网补图。
- 记录实际时间覆盖、消息类型覆盖、缺附件、解析异常及未知字段。统计必须满足 `read_count = imported_count + duplicate_count + rejected_count`；unknown_count 是已接受消息的子集，不重复相加。源总数不可得时完整性为 unknown。
- “当前数据中没找到”不等于“历史上没讨论过”。B 在答案中携带覆盖范围与不完整提示，C 在导入报告、数据源页及无结果页展示；解密成功不能恢复电脑未保存的历史或过期附件。

## 5. GitHub 并行开发与合并管理

### 5.1 分支、评审与公共文件

1. `main` 只保存可集成基线；本次初始化文档同步之后，功能修改通过 PR，不共享可写功能分支，不使用长期 develop 分支。
2. 命名：`feat/A-01-file-import`、`feat/B-01-hybrid-search`、`feat/C-01-desktop-shell`；修复使用 `fix/<任务ID>-<说明>`。一个分支对应一个工作包或明确的子任务。
3. 各自在独立 clone 中开发；每日开工和提 PR 前 fetch 最新 main。共享分支不 rebase/force-push；已发布分支优先 merge 最新 main。禁止对 main 强推。
4. B/C 普通界面和测试 PR 可互审；B 的检索/LLM 与 C 的跨层集成 PR 必须由 A 技术评审；A 的 PR 由 B/C 独立测试与评审；跨模块还必须获得受影响模块负责人的明确确认。接口/schema/锁文件变更必须标注 `contract-change`。
5. A 是技术合并协调人，只串行安排已通过评审的 PR；A 自己的 PR 由 B/C 独立测试与评审，关键安全项另需产品负责人验收，不允许自批。先合契约及迁移，再数据层、检索层、组装层。每次合并后，下一 PR 更新 main 并重新检查，不沿用旧基线的绿色结果。
6. A 独占 schema 和迁移编号；B 提出索引表需求，由 A 落库。C 独占依赖锁、入口、CI；任何共享文件修改先在 Issue 留言认领，PR 合入/关闭后释放。
7. 两人需要同一文件时，先拆出前置 PR，后续使用 mock 或已冻结接口；不要复制另一人的未合并实现。冲突由文件负责人处理，调用方复核，不采用机械“保留 ours/theirs”。
8. 出现 main 回归立即停止新合并，由引入变更的负责人提交修复或 `git revert` PR；不 reset 公共历史。失败测试不得删除或降低断言以放行。

### 5.2 GitHub 配置清单（P0-01，成员已确认，其余按项执行）

- 账号已确认：A/@Kamisato-Ayaka2025（admin），B/@YuanKunlin（write），C/@Zhong-Yufeng（write）；权限已通过 GitHub 查询确认，无待接受邀请。`.github/CODEOWNERS` 已随本次 PR 添加，合入目标分支后用于后续 PR 的目录负责人匹配。CODEOWNERS 不授予访问权限，也不单独强制评审；分支保护与 required checks 仍待 P0 配置。
- 创建 PR 模板：任务/REQ、变更行为、契约/迁移、测试命令与结果、UI 截图、风险/回滚、证据路径。
- 配置 main 保护/规则集：PR 必须评审至少 1 人、对话已解决、最新基线检查通过、禁止强推/删除；契约 PR 额外执行三方确认流程。若仓库权限不支持自动强制，C 记录限制并人工执行同等门槛。
- CI 目标检查：`lint`、`unit-contract`、`integration`（Windows）、`package-smoke`；只有实际创建且成功运行的 job 名称才能加入 required checks，避免配置不存在的检查阻塞全部 PR。
- Issue 标签建议：`lane:A/B/C`、`phase:P0…P5`、`blocked`、`contract-change`、`security`；项目看板对应任务状态。当前计划未自动创建 Issue、分支保护或邀请协作者。
- CI 只使用合成数据；默认拦截外部网络调用，不向 fork PR 注入密钥。需要真实 API 的检查独立手动执行，授权后使用最少合成内容并记录脱敏结果。

### 5.3 开发者操作示例

```powershell
git clone https://github.com/Kamisato-Ayaka2025/AI-Advaned-File-Search.git
cd AI-Advaned-File-Search
git switch main
git pull --ff-only
git switch -c feat/A-01-file-import
# 完成实现与本地检查后，仅暂存本任务文件
git add <本任务文件>
git commit -m "feat(A-01): add deterministic file import"
git push -u origin feat/A-01-file-import
gh pr create --base main
```

本机 F 盘不记录所有权，Git 可能报告 dubious ownership。已知可信工作目录可临时使用 `git -c safe.directory=F:/Code/AI_Advanced_File_Search ...`；不要设置 `safe.directory=*`。

## 6. 软件运行时并发与一致性

这部分是实现要求，不是仅靠 Git 分支解决的问题。

| 操作冲突 | 规则 | 验证负责人 |
|---|---|---|
| 外部导出与导入 | 仅处理已完成导出；导出工具结束后锁定文件清单、哈希与 manifest，读取结束复核；发生变化则整批不发布；相同快照幂等，外部工具崩溃/过期不影响已发布索引 | A/C |
| 多次导入/数据库写入 | A 提供单写线程与有界队列；每线程独立连接；同源导入串行；批次事务、幂等键、游标同事务提交；取消保留已完成批次并显式报告 | A |
| 导入与索引 | 先提交事实数据 revision，B 读取已提交快照生成新索引；A 原子切换 active index revision；失败保留旧索引并标记待更新 | A/B |
| 查询与重建 | 查询固定 index_revision；FTS、向量和引用对应同一数据快照；A 保留旧版本数据到读者释放再回收；初次未建索引提示等待，不能混用半成品索引 | B |
| UI 与后台 | Qt 主线程只更新 UI；工作线程通过信号返回结果；不跨线程操作 QWidget；取消信号协作处理，禁止强杀线程中断事务 | C |
| 连续查询/流式回答 | 每次递增 request_id，新请求使旧请求失效；迟到 token、错误和结果按 ID 丢弃；取消时停止重试并关闭网络流 | B/C |
| 同意与发送 | 发送前原子验证授权和最终 payload hash；正文/模型/目标/范围变更重新预览；一次性授权消耗后不可复用；不自动重复不确定已发送请求 | B/C |
| 删除与任意后台任务 | A 的协调服务获取全局维护锁、停止新任务并取消/等待运行任务，清除 pending SendPlan，A/B 再清理；失败清单可重试，禁止 UI 提前显示成功 | A/B/C |
| 多个应用实例 | 数据目录使用单实例锁；第二实例提示已有实例，不允许第二个写入者绕过队列 | C |

设定有界任务队列与可配置超时；长任务提供进度和取消。数据库 busy 重试必须有限且对 UI 可见。WAL 是否启用由加密驱动兼容测试决定，不假定所有驱动都已支持。

## 7. 阶段、时间盒与关键路径

| 阶段 / 相对时间 | A | B | C | 出口门槛 |
|---|---|---|---|---|
| P0 / 0:00–0:40 | schema/加密/导入样例 spike + A-00 文档探针（含在 40 分钟内） | 本地模型/中文检索/服务契约 spike | 环境、最小包、GitHub 流程 | G1：技术可行结果和契约 v1；失败立即记风险并调整 D1/D2 |
| P1 / 0:40–2:00 | A-01、A-02 基础 | B-01 基于 fixture | C-01 基于 mock，C-02 原型 | G2：三线独立可测试，不等真接口才动工 |
| P2 / 2:00–3:30 | 稳定仓储、上下文、索引写接口 | B-01 接真数据、B-02 | C-02、第一轮真实组装 | G3：真实导入→检索→引用定位纵向链路 |
| P3 / 3:30–4:45 | 异常、幂等、并发、加密 | B-03、检索质量、降级 | UI/撤回/删除联调、初版包 | 功能冻结；只修核心缺陷，Could 延后 |
| P4 / 4:45–6:00 | 数据完整性验收 | 质量/性能评测 | 打包、干净 Windows、录屏 | G4：D1 演示候选；G5 未通过则 D2 不发布 |
| P4 后续 / 按缺陷排期 | A-03 剩余与删除证据、A-04 分格式适配 | 新来源质量与覆盖提示回归 | 真数据模式/完整环境验证、导入覆盖 UI | G5：D2；各导出适配另过 G6；未满足不以时间盒结束代替验收 |
| P5 / 另立计划 | Tier B 技术调查与兼容矩阵 | 新数据源回归 | 授权/多账号交互 | 独立可行性、安全评审和产品确认后才立项实现 |

关键路径：P0 技术验证与契约 → A 事实库/片段 → B 索引/引用 → C 真实链路与打包。B/C 前期用同一 fixture 与 mock 并行，不能用各自私造的字段规避契约。

同步节奏：开工 10 分钟明确认领；每 45 分钟在 Issue 更新完成/阻塞/下一步；2:00、3:30、4:45 由 A 主持合并窗口，C 汇报构建与集成结果。阻塞超过 15 分钟先报 Issue，30 分钟内仍无可行路线则切换独立任务；需要改范围的事项交产品负责人决定。

## 8. 验收、测试与证据

### 8.1 Gate 定义

| Gate | 必需证据 | 不通过时处理 |
|---|---|---|
| G1 技术/契约 | 三机环境版本、最小 Windows 包、模型离线运行、FTS5/加密探针、DTO 双向消费测试、负责人确认 | 接口不可用不得进入联调；安全原型失败仅允许合成数据演示 |
| G2 模块 | lint、单元/契约测试、模块负责人自查、跨线评审 | 保持 REVIEW/BLOCKED，不合入破坏基线的代码 |
| G3 集成 | 三种格式各 ≥1000 条；重复导入不增量；8 类标准化边界；抽样 20 段和 10 处上下文；引用端到端定位 | 修复事实数据、契约或 UI 问题后重测相关链路 |
| G4 演示 | 五个演示场景；断网/无 Key 的 3–5 分钟演示；合成数据标签；Windows 包与录屏；所有未完需求清单 | 不标记 D1 完成；已有包只能标为预览 |
| G6 外部格式兼容（逐适配器） | 锁定版本/schema、只读前后哈希、字段映射、计数对账、重复与跨工具 ID 测试、缺附件/异常数据、上游失效后历史仍可搜索；实际授权样例与合成测试分列 | 该格式不标 supported，保留通用导入；不阻塞 G4，真实导出使用仍须 G5 |
| G5 真实数据/完整质量 | 发送授权与网络拦截证据、库/WAL/索引/附件加密、日志审计、删除重启、性能及人工评测、干净 Win11 安装和 Win10 启动验证 | 真实数据模式关闭；缺陷归责并补证据，不降低原需求 |

### 8.2 可量化用例

- 导入：JSON/CSV/TXT 各 1000 条，记录预期/实际数量；全量、最近时间、空范围、坏编码、缺字段、未知类型、重复、撤回、系统消息、跨时区均覆盖。格式说明须列必填字段；不承诺能解析所有 QQ/微信导出文件。
- 检索：20 条有证据问题组成固定评测集；**计划门槛** macro recall@10 ≥0.80，按每题命中的相关片段数/全部标注相关片段数计算再平均；这是补足 REQ-018 未指定的目标值，需在 G1 由产品负责人确认。负例单独统计，不混入 recall 分母。
- 查询理解：20 条已标注问题，槽位准确率 ≥80%；保留题目、期望槽位与比较规则；相对日期固定测试时钟。冲突条件不能默默忽略。
- 回答：10 条人工评测，每个结论可追溯；不存在的冰岛团建不得编造；“换供应商”至少 3 条引用；“谁最先反对”验证后续追问的会话上下文；冲突证据同时展示。
- 原需求对“4 个演示查询均命中/可跳转”的表述与第 4 个无证据场景冲突：按前三个有证据查询命中并定位、第四个明确没找到且无虚构引用执行，另独立验证第五个定位动作；在验收报告注明该解释并由产品负责人确认。
- 授权：默认拒绝、部分片段、编辑预览、模型/目标变化、撤回、旧授权复用、网络重试；断言最终 payload 与预览一致。查询解析请求也受控，不能把完整查询绕过授权发送。
- 故障/并发：两个导入同时启动、索引中查询、导入中取消、连续查询迟到回复、删除中网络返回、重复删除、损坏索引、只读目录/磁盘满、缺模型、断网、无效 Key、429、超时、非 JSON；应用不崩溃，状态与残留可核对。
- 性能：1 万条消息、SSD、缓存模型、记录 CPU/RAM/版本；首次加载独立测量。热态至少重复查询 30 次，记录 p50/p95；召回目标 ≤1 秒、索引 ≤2 分钟、常驻内存 ≤1 GB。网络正常时首 token ≤5 秒、完整答案 ≤30 秒；API 失败单列，不删除慢样本或以 mock 代替实测。
- 隐私清理：检查事实库、FTS、向量、WAL/临时文件、附件、缓存和日志；删除后重启和重试不恢复旧数据。删除本地文件不等于证明 SSD 物理不可恢复；REQ-027 的“不可恢复”需按威胁模型确认并设计密钥销毁，不能无证据承诺物理擦除。

### 8.3 目标命令（P0 建立后才可执行）

```powershell
uv sync --frozen
uv run python -m original_words
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/contracts tests/data tests/retrieval tests/llm
uv run pytest tests/integration tests/ui
uv run python scripts/evaluate.py --dataset tests/evaluation/queries.json
uv run python scripts/package_windows.py
```

C 在 P0 创建项目配置、脚本与真实命令，并回写 README。不要提交空测试、伪造通过输出或把未实现脚本当已存在。模型权重、私人数据、密钥不进 Git；离线包通过有校验值的构建/下载流程提供模型，打包检查必须包括断网首启。

每个 Gate 的脱敏记录存 `docs/evidence/<gate>/<日期>-<任务ID>.md`，写明提交 SHA、环境、输入 fixture 版本、命令/步骤、预期/实测、失败项、执行者、人工确认者。私密抓包/原文/Key 不上传公共仓库，只留脱敏结论和证据索引。DONE 必须关联合并 PR 和证据，自动化通过不等于人工验收。

## 9. 全量需求追踪矩阵

每行列出主要责任与验收入口；完整字段和边界以 `requirement.md` 为准。

| REQ | 主责 | 工作包/阶段 | 验收入口 |
|---|---|---|---|
| REQ-001 | C | C-01/C-03 | 五场景、G4 |
| REQ-002 | C | P0-01/C-03 | Windows 包、G5 |
| REQ-003 | C（全员遵守） | 全阶段 | 范围审查、无越界入口 |
| REQ-004 | A | P0-01/A-01/A-04 | 文件、外部导出适配+mock 契约 |
| REQ-005 | A | P5 | 真实客户端发现，未实现 |
| REQ-006 | A | P5 | 独立授权/只读/安全评审，待确认 |
| REQ-007 | C/A | C-03；P5 | mock 降级；真实降级另验收 |
| REQ-008 | A | P5 | 版本矩阵，待确认 |
| REQ-009 | A | A-01/A-04 | 三格式及版本锁定外部导出；G3/G6 |
| REQ-010 | A | P5 | 客户端增量/中断恢复，待确认；不混同文件幂等 |
| REQ-011 | A | A-01 | schema、八类边界、幂等 |
| REQ-012 | A/C | A-01/C-01 | 文本/图片/文件名 |
| REQ-013 | A | A-02 | 20 段抽样、重叠 |
| REQ-014 | A | A-02 | SQLite 与 Markdown/锚点一致 |
| REQ-015 | B/A | B-01/A-03 | FTS/向量、重建/增量一致 |
| REQ-016 | B | B-01 | 本地模型、离线、缺模型 |
| REQ-017 | B | B-02 | 20 题 ≥80% |
| REQ-018 | B | B-01 | recall@10、负例、融合重排 |
| REQ-019 | A/C | A-02/C-01 | 前后各 10 条、引用定位 |
| REQ-020 | B | B-02/B-03 | 10 题人工可追溯/冲突 |
| REQ-021 | C | C-01/C-03 | 时间线/应用内跳转 |
| REQ-022 | B/C | B-01/C-01 | 10 组组合；高级 UI 可延后，基本范围不可丢 |
| REQ-023 | B/C | B-03；P4 后续 | 5 条歧义最多追问一次；待确认；不阻塞普通后续提问 |
| REQ-024 | B/C | B-02/C-02 | 配置/可用性核验/错误/Key 保护 |
| REQ-025 | C/B | C-02/B-02 | 预览、同意、拒绝、撤回 |
| REQ-026 | A/C/B | A-03/C-02/G5 | 加密、访问控制、无未授权外发 |
| REQ-027 | A/C | A-03/C-02；P4 后续 | 导出可读；真实数据模式前完成删除 |
| REQ-028 | C（A/B 配合） | A-03/B-03/C-02 | 脱敏日志/诊断审查 |
| REQ-029 | B/C | C-03/G5 | 1 万条基准及内存/网络指标 |
| REQ-030 | B/C/A | A-03/B-03/C-03 | 故障注入/降级 |
| REQ-031 | C（A/B 配合） | 三线→C-03 | 合成数据、离线、3–5 分钟演示 |
| REQ-032 | A/C | P5 | 多源隔离/跨源标注，待确认 |

## 10. 风险、待决策与交接

| ID | 风险/待确认项 | 负责人/截止 | 处理 |
|---|---|---|---|
| R-01（已解决） | A/B/C 账号及访问权限已确认 | 用户确认；2026-10-18 | A=@Kamisato-Ayaka2025；B=@YuanKunlin；C=@Zhong-Yufeng；无需公开真实姓名 |
| R-02 | Windows 加密驱动、模型或打包可能超出六小时 | A/B/C，P0 | 优先 spike；失败保持 D1 合成模式并明确 D2 阻塞 |
| R-03 | 原需求模型名称/当前账号能力未经实测 | B，P0 | 查官方文档、授权的最小请求验证；配置不等于 API 成功 |
| R-04 | 分词、长文本截断影响中文召回 | B，P1 | 固定分词版本，长文本分窗；短词/中英测试与质量报告 |
| R-05 | 原需求第 6.2 节的时间选项、数据规模、导出优先级仍为建议 | C，G1 | 使用第 1 节工程默认；产品负责人确认后再更新需求状态 |
| R-06 | recall 门槛与无证据场景解释需确认 | B/C，G1 | 提交第 8 节可执行口径；未确认不声称完整产品验收 |
| R-07 | “删除后不可恢复”缺少威胁模型，SSD 擦除不能靠普通删除保证 | A/C，G5 前 | 明确逻辑删除、密钥销毁、备份/存储残留边界，留产品确认记录 |
| R-09 | 外部导出 schema 漂移、组件过期、上游缺数据/许可未明 | A/C，A-00/A-04 | 未锁定版本及 G6 未过不声明兼容；格式失败不影响已有索引；不将解码器纳入运行依赖 |
| R-08 | Tier B 可行性、授权边界与客户端未启动行为 | A/C，P5 | 独立 spike，不默认启动或接入客户端，不阻塞 MVP |

所有人每次停工前更新自己的 handoff：当前分支/HEAD、已完成任务、已跑检查与证据、失败尝试、未提交文件、占用的公共文件、阻塞、下一条具体操作。C 汇总执行证据，A 核对 Gate 状态；任务重新指派先释放旧认领，不能出现两个实际负责人。

本次交付仅为计划与仓库文档同步。A/B/C 已分配，开工第一步是执行 P0-01，不应直接跳到各自独立实现接口。

## 11. 技术参考（P0 仍须本机验证）

- [Qt for Python 部署指南](https://doc.qt.io/qtforpython-6/deployment/index.html)：Windows 部署工具选择依据。
- [SQLite FTS5 官方文档](https://www.sqlite.org/fts5.html)：全文索引、BM25 与 tokenizer 行为；不代替本项目中文质量测试。
- [SQLCipher 设计说明](https://www.zetetic.net/sqlcipher/design/)：加密数据库/WAL 的设计依据；不代表 Python 驱动或安装包已通过验证。
