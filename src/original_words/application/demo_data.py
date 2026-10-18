"""合成演示数据（C 线所有，仅演示/测试用，不得包含真实聊天记录）。

- 3 个会话、约 1000 条消息：深蓝项目组（群聊）、张伟（私聊）、羽毛球群（群聊）。
- 覆盖文本/图片/文件/系统/撤回/引用/未知时间消息。
- 内置演示查询：3 条有证据（含“换供应商”3 处引用）+ 1 条无证据（冰岛团建，数据中不存在）。
- 数据完全确定性生成（固定随机种子），message_id 稳定。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from random import Random

from original_words.application.dtos import Chat, Message

SOURCE_ID = "demo"


def _msg_id(chat_id: str, seq: int) -> str:
    return f"{SOURCE_ID}:{chat_id}:{seq:06d}"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class DatasetBundle:
    def __init__(
        self,
        chats: list[Chat],
        messages: list[Message],
        events: dict[str, Message],
        now: datetime,
    ) -> None:
        self.chats = chats
        self.messages = messages
        self.events = events
        self.now = now

    def by_chat(self, chat_id: str) -> list[Message]:
        return [m for m in self.messages if m.chat_id == chat_id]


def build_dataset(now: datetime | None = None) -> DatasetBundle:
    now = now or datetime.now().replace(microsecond=0)
    rng = Random(20261018)
    chats: list[Chat] = []
    messages: list[Message] = []
    events: dict[str, Message] = {}

    project_members = ("张伟", "李娜", "王强", "赵敏", "刘洋", "陈晨", "孙磊", "周婷")
    chats.append(
        Chat(
            chat_id="chat_project",
            chat_name="深蓝项目组",
            chat_type="group",
            source_id=SOURCE_ID,
            participants=project_members,
        )
    )
    chats.append(
        Chat(
            chat_id="chat_zhangwei",
            chat_name="张伟",
            chat_type="private",
            source_id=SOURCE_ID,
            participants=("我", "张伟"),
        )
    )
    chats.append(
        Chat(
            chat_id="chat_badminton",
            chat_name="羽毛球群",
            chat_type="group",
            source_id=SOURCE_ID,
            participants=("王强", "赵敏", "陈晨", "周婷", "刘洋"),
        )
    )

    filler = [
        "收到，我这边没问题",
        "这个方案我再想想，晚点回复",
        "文档已更新到共享目录，大家查收",
        "今天进度正常，没有阻塞",
        "+1",
        "下午三点开会，别忘了",
        "接口联调今天能做完吗",
        "数据库迁移脚本我跑过了，一切正常",
        "这周周报谁还没交",
        "测试环境又挂了，谁看看",
        "需求又变了，产品刚发的新版",
        "排期太紧了，感觉要延期",
        "风险清单记得更新",
        "代码 review 通过了，可以合",
        "周末聚餐有人报名吗",
        "我刚把 bug 修完，等发布",
        "性能测试数据出来了，比上版本好",
        "这个依赖版本别乱升级",
        "会议纪要我整理好了",
        "今晚加班，宵夜走起",
    ]

    # ---------- 会话 1：深蓝项目组（群聊，约 700 条，跨度 300 天） ----------
    chat_id = "chat_project"
    total = 700
    span_days = 300
    step = int(span_days * 24 * 60 / total)  # 分钟/条
    start = now - timedelta(days=span_days)
    scripted: dict[int, dict] = {
        # seq: (sender, type, content, quote_of)；seq→日期 ≈ 0.43 天/条
        # 供应商弧 190-197 ≈ 3 月中旬；夜宵弧 350-353 ≈ 5 月下旬
        190: ("张伟", "text", "A 供应商报价涨了 30%，我建议换掉", None),
        191: ("李娜", "text", "我反对现在换供应商，A 的质量一直稳定，换人风险太大", None),
        192: ("王强", "text", "我同意张伟，B 供应商价格便宜还包安装", None),
        193: ("赵敏", "text", "C 供应商也可以看看，货期短", None),
        194: ("张伟", "text", "综合下来选 B 吧，便宜 20%，交付期还短一周", None),
        195: ("李娜", "text", "B 的售后怎么样？有实际案例吗", None),
        196: ("王强", "text", "B 供应商给了 3 家客户案例，反馈都 OK", None),
        197: ("张伟", "text", "那就定 B 供应商，下周签合同", None),
        198: ("张伟", "text", "A 供应商报价涨了 30%，影响下季度预算", None),
        200: ("王强", "text", "同意张伟的判断", "198"),
        201: ("张伟", "image", "", None),
        350: ("刘洋", "text", "夜宵预算建议上调到每人 50", None),
        351: ("李娜", "text", "我反对，上个月夜宵已经超支了 200 块", None),
        352: ("陈晨", "text", "同意李娜，先把超支的部分补上再说", None),
        353: ("刘洋", "text", "那改成 40 吧，大家投票", None),
        400: ("王强", "file", "预算表_2026H1.xlsx", None),
        500: ("赵敏", "recalled", "", None),
        600: ("李娜", "system", "李娜 邀请 陈晨 加入群聊", None),
    }
    for i in range(total):
        seq = i + 1
        ts = start + timedelta(minutes=i * step + (i * 7 % 47) - 23)
        if seq in scripted:
            sender, mtype, content, quote = scripted[seq]
        else:
            sender = project_members[i % len(project_members)]
            mtype = "text"
            content = filler[rng.randrange(len(filler))]
            quote = None
        attachment = None
        if mtype == "image":
            attachment = {
                "kind": "image",
                "name": "供应商报价截图.png",
                "size": 231456,
                "sha256": _sha("image-200"),
                "path": None,
                "available": False,
            }
        elif mtype == "file":
            attachment = {
                "kind": "file",
                "name": "预算表_2026H1.xlsx",
                "size": 18432,
                "sha256": _sha("file-400"),
                "path": None,
                "available": False,
            }
        # 尾部 10 条未知时间消息（按来源顺序单列展示）
        unknown = seq > total - 10
        msg = Message(
            message_id=_msg_id(chat_id, seq),
            chat_id=chat_id,
            chat_type="group",
            sender_id=f"u_{sender}",
            sender_name=sender,
            timestamp=None if unknown else ts,
            message_type=mtype,
            content=content,
            quote_of=_msg_id(chat_id, int(quote)) if quote else None,
            attachment_ref=attachment,
            source_id=SOURCE_ID,
            seq=seq,
            timestamp_status="unknown" if unknown else "known",
            timestamp_precision=None if unknown else "minute",
        )
        messages.append(msg)

    events["supplier_propose"] = messages[189]  # seq 190
    events["supplier_oppose_first"] = messages[190]  # seq 191
    events["supplier_support_b"] = messages[191]  # seq 192
    events["supplier_choice_b"] = messages[193]  # seq 194
    events["supplier_case_b"] = messages[195]  # seq 196
    events["supplier_decide"] = messages[196]  # seq 197
    events["quote_message"] = messages[199]  # seq 200
    events["night_propose"] = messages[349]  # seq 350
    events["night_oppose_first"] = messages[350]  # seq 351

    # ---------- 会话 2：张伟（私聊，约 220 条，跨度 300 天） ----------
    chat_id = "chat_zhangwei"
    total2 = 220
    step2 = int(span_days * 24 * 60 / total2)
    start2 = now - timedelta(days=span_days)
    scripted2 = {
        58: ("张伟", "text", "三月初那个登录 bug 又出现了", None),
        59: ("我", "text", "是那个 token 过期的问题吗", None),
        60: ("张伟", "text", "对，改成刷新失败时自动重试了，已经修好，下个版本带上", None),
        80: ("我", "text", "周末吃火锅吗，听说新开了一家", None),
        81: ("张伟", "text", "可以，叫上王强一起", None),
    }
    for i in range(total2):
        seq = i + 1
        ts = start2 + timedelta(minutes=i * step2 + (i * 11 % 41) - 20)
        if seq in scripted2:
            sender, mtype, content, quote = scripted2[seq]
        else:
            sender = ("我", "张伟")[i % 2]
            mtype = "text"
            content = filler[rng.randrange(len(filler))]
            quote = None
        unknown = seq > total2 - 8
        messages.append(
            Message(
                message_id=_msg_id(chat_id, seq),
                chat_id=chat_id,
                chat_type="private",
                sender_id=f"u_{sender}",
                sender_name=sender,
                timestamp=None if unknown else ts,
                message_type=mtype,
                content=content,
                quote_of=None,
                source_id=SOURCE_ID,
                seq=seq,
                timestamp_status="unknown" if unknown else "known",
                timestamp_precision=None if unknown else "minute",
            )
        )
    events["bug_recurred"] = messages[total + 57]  # 会话 2 seq 58
    events["bug_fixed"] = messages[total + 59]  # 会话 2 seq 60

    # ---------- 会话 3：羽毛球群（群聊，约 100 条，跨度 200 天） ----------
    chat_id = "chat_badminton"
    total3 = 100
    span3 = 200
    step3 = int(span3 * 24 * 60 / total3)
    start3 = now - timedelta(days=span3)
    badminton = ("王强", "赵敏", "陈晨", "周婷", "刘洋")
    court = [
        "今晚七点打球，有人吗",
        "场地订好了，3 号场",
        "我今晚加班，去不了",
        "改明天？",
        "带球了吗",
        "上次那个杀球教学视频谁有",
    ]
    for i in range(total3):
        seq = i + 1
        ts = start3 + timedelta(minutes=i * step3 + (i * 13 % 37) - 18)
        sender = badminton[i % len(badminton)]
        unknown = seq > total3 - 5
        messages.append(
            Message(
                message_id=_msg_id(chat_id, seq),
                chat_id=chat_id,
                chat_type="group",
                sender_id=f"u_{sender}",
                sender_name=sender,
                timestamp=None if unknown else ts,
                message_type="text",
                content=court[rng.randrange(len(court))],
                source_id=SOURCE_ID,
                seq=seq,
                timestamp_status="unknown" if unknown else "known",
                timestamp_precision=None if unknown else "minute",
            )
        )

    return DatasetBundle(chats, messages, events, now)


# 演示查询：query / 说明 / 证据键（供 mock 答案构造）
DEMO_QUERIES: list[dict] = [
    {"query": "谁最先反对换供应商", "kind": "evidence", "note": "李娜最先反对，引用她的原话"},
    {"query": "供应商最后换了哪家", "kind": "evidence", "note": "B 供应商，至少 3 处引用"},
    {
        "query": "张伟三月提到的登录 bug 后来怎么处理了",
        "kind": "evidence",
        "note": "软线索：人物=张伟、时间=三月",
    },
    {"query": "冰岛团建是哪天定的", "kind": "no_evidence", "note": "数据中不存在，不得编造引用"},
]
