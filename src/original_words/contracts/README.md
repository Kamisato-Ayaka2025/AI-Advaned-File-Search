# P0-01 共享契约 0.2.0-draft

负责人 A；B/C 独立消费和评审前不冻结 v1。这里只定义纯 Python 数据边界、校验及服务接口，没有数据库、模型、Qt、网络或安全服务实现。

## 文件与调用入口

| 文件 | DTO / 接口 | 消费者与主要不变量 |
|---|---|---|
| messages.py | Message、stable_message_id | A 导入，B/C 消费；来源/会话命名空间、原始 ID 优先、未知时间保留 |
| common.py | ErrorInfo、ServiceFailure、SnapshotRef、TaskEvent | 全线；统一错误、固定数据/索引版本、进度与失败状态一致 |
| data.py | Chunk、CharSpan、Coverage、ImportManifest、ImportReport、ImportBatch、ImportResult | A → B/C；计数守恒、未知计数为 null、片段成员/字符区间 |
| search.py | SearchFilters、SearchRequest、SearchHit、SearchResult | B → C；明确范围与 UTC 半开时间过滤、首屏数量独立于调查预算 |
| search.py | SearchSpec、SearchBudget、Candidate、MessageEdge、StageCandidate、EvidenceBundle、InvestigationDecision | A/B/C；权限与软线索分离、同一快照、受限补查、显式关系与缺口 |
| answers.py | Citation、Claim、TimelineEntry、Answer、SearchUsage、SearchOutcome | B → C；结论必须引用、无证据结果不编造、部分结果不宣称完整 |
| sending.py | SendPlan、ConsentGrant | A/B/C；完整请求字节预览、全元数据指纹、一次性授权接口 |
| services.py | 九类 Protocol 及 ProbeResult/ContextResult/IndexUpdate/CleanupReport 等辅助 DTO | 方法签名、不变量及结构化失败 |
| validation.py | validate_chunk / validate_evidence / validate_answer | 对照固定快照的原消息检查来源、字符范围和引用；不能证明语义支持 |
| base.py | from_json / to_json | 严格类型、枚举、未知字段/重复键拒绝；不可变 tuple ↔ JSON array |

## Wire 约定与具体决策

- 使用 frozen dataclass + tuple；不接收可变 list 作为 Python 构造参数。JSON 走 from_json，不用未经检查的 dict 当 DTO。
- 版本化合成 wire 样例在 tests/fixtures/contracts/v0_2.json，含 42 个正常/空结果/错误对象。它是公共合成数据，不是上游 QQ/微信格式样例。
- from_json 限制 UTF-8 输入为 1 MiB、契约嵌套为 32 层；拒绝重复键、NaN/Infinity、未知字段、bool 冒充 int、缺必填字段。仅接受已定义 DTO，不提供任意对象反序列化。
- ImportReport 通过 manifest 嵌入来源/版本/覆盖字段；source_count 不可知时 completeness 必须 unknown。unknown_count 是 imported_count 的子集；attachment_missing_count 统计附件，可大于消息数。
- Chunk.start/end 是可知的 UTC 时间边界，未知为 null；message_ids/char_spans 保留实际成员及 Python Unicode 字符索引，区间为 [start,end)。JS/Qt 需要转换 UTF-16 索引，不能直接当字节偏移。
- 秒级和毫秒级时间必须匹配声明精度；日期级保留 YYYY-MM-DD 和来源时区，不生成午夜时间。当前日期级数据在有界时间过滤中保守排除，此策略需 B/C 评审；不是完整日期区间检索实现。
- SearchSpec.request.filters 就是 hard_filters；soft_hints 单独保存，不能转换为授权或强制条件。authorized_source_ids 必须明确且非空；filters.source_ids 为空表示授权范围内全部，不是无限权限。
- SearchOutcome 的 citations 在 answer 中，coverage/missing_stages 在 evidence 中，调用/token/耗时在 usage 中；避免重复字段出现冲突。status 属性代理 answer.status。
- EvidenceBundle.snapshot 同时绑定 dataset_revision/index_revision；MessageEdge.revision 对应数据版本；SearchHit.index_revision 对应索引版本。
- 补查默认最多 2 轮、每轮 3 查询、远端 3 次、累计输入 24000 tokens、机器时间 30 秒；可向下配置，不能向上越过 ADR 标准模式。DTO 只校验配置和计数，时钟/取消/每阶段 token 预留由 A 的调度器实施。超时实际耗时如实记录，不能截短测量值以达标。
- 阶段候选是检索线索，不是已经证实的事件事实。关系只能 reply/quote，失去目标时 to_id=null + unresolved=true；相似文本不冒充关系。

## 发送及引用边界

SendPlan.preview_text 必须是实际发送的完整 UTF-8 JSON 请求体，包含模型、查询和系统消息；不是另写一段概述。payload_hash 是这些字节的 SHA-256，fingerprint 再绑定 request_id/purpose/mode/selected_message_ids/model/endpoint/consent_scope。任何修改都必须重新预览并授权。

当前只接受 HTTPS api.deepseek.com 的 /chat/completions 或 /v1/chat/completions；不支持代理、任意端点或重定向。后端也必须禁止跳转至未授权目标。模型名是配置值，样例 synthetic-model 不代表可用服务。

ConsentGrant 仅是记录，不能靠构造 DTO 获得权限。ConsentService 必须查运行时授权状态、过期、撤回和范围；validate 是只读预检，发送前还必须调用原子的 consume。所有 HTTP 重试占预算，不自动重试发送状态不确定的请求。查询解析/Planner 同样需要授权。

Citation 不允许携带模型生成的原文、发送者或时间；UI 从固定版本仓储取消息并按 char_span 展示。先调用 validate_answer 验证权限和字符边界；若 evidence 只包含局部字符区间，引用不得扩大为整条消息，也不能跨越未选文本。语义上是否支持结论仍需人工评测。

任何 DTO / to_json 输出都可能包含敏感信息，禁止写入普通日志。ErrorInfo.user_message 必须由服务生成脱敏文字；ServiceFailure 的异常字符串只显示 code，不附带原始异常或数据。Message 的 repr 仍有身份元数据，同样不可直接记日志。

## 九类 Protocol 的调用语义

全部是同步的后台工作线程接口，服务失败抛 ServiceFailure。Protocol 的 runtime_checkable 只检查方法存在，不能替代静态类型检查、行为测试或安全验收。

1. ChatSourceConnector：detect/authorize/read/sync；Tier A sync 抛 UNSUPPORTED_OPERATION；不得启动或探测真实客户端。
2. ExportAdapter：probe/read/validate；只读已有文件；未知 schema 拒绝；处理前后核对快照。
3. Repository：import_batch/get_messages/get_context/get_chunks；单写队列；每次读显式传 snapshot 和非空授权 source_ids；上下文默认前后各 10 条且不跨会话。
4. IndexStore：publish/get_active_revision；IndexUpdate 指定 expected_active_revision 做比较后提交；FTS/向量同次发布，旧读者仍须保留版本。
5. SearchService：parse_local/search；parse_local 不联网；固定 snapshot，硬范围不得放宽。
6. AnswerService：prepare_send/generate；prepare_send 不联网；局部发送由调用方先缩小 evidence，后端仍检查 scope；generate 消耗授权后发送原样字节。
7. ConsentService：grant/revoke/validate/consume；只有明确 user_confirmed 才能授予；一次性、可撤回，不能只检查 DTO 字段。
8. SecretStore：get/set/delete；bytes 仅运行时使用，存储保护机制由安全实现提供。
9. DataLifecycle：export/delete；删除先确认、停任务、清 pending sends，再清所有资源；CleanupReport 必须包含 database/index/attachments/cache/logs/keys/pending_sends，任一失败不能显示成功。

## 验证和评审

在工作区根目录，使用已存在的 Python：

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests/contracts -v
python -I -S tests/contracts/check_environment.py
```

test_consumers.py 是 A 编写的合成接口调用示例，无真实网络或存储，不能替代 B/C 独立 mock/消费测试。C 尚未建立锁文件、pytest/Ruff 或 CI；上述命令是本契约独立检查入口，不是应用运行命令。

评审重点：日期级过滤、来源/账号命名空间、ImportReport 嵌套、SnapshotRef 生命周期、完整请求预览、consume 原子边界及 ADR 搜索预算。通过评审后才发布 v1；G1 仍需要三机工具链、模型、加密与最小窗口打包证据。
