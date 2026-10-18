#!/usr/bin/env python3
"""Generate a small bilingual demo corpus for smoke tests and evaluation."""
from __future__ import annotations

import os
import time
from pathlib import Path

ROOT = Path(__file__).parent / "corpus"

FILES: dict[str, tuple[str, int]] = {
    # name: (content, days_ago)
    "2025Q3_设备采购方案_终版.csv": (
        "项目,供应商,报价,交期\n"
        "服务器采购,华信科技,128000,30天\n"
        "网络设备,中科网络,46000,15天\n"
        "备注,本方案为最终版,张经理确认,2025-10\n",
        3,
    ),
    "会议纪要_0321.md": (
        "# 新能源项目立项讨论\n\n"
        "参会人：张经理、李工、王总\n"
        "议题：光伏储能项目的可行性、预算与时间表。\n"
        "结论：先做 500kW 试点，Q4 前完成设备采购方案。\n",
        40,
    ),
    "GPU_thermal_throttling_analysis.md": (
        "# GPU thermal throttling analysis\n\n"
        "The GPU overheats under sustained load and drops clocks, which causes "
        "frame drops and stutter in games. Repasting the cooler and limiting "
        "the power target reduced the temperature by 12C.\n\n"
        "结论：显卡温度过高会触发降频，导致游戏掉帧。\n",
        8,
    ),
    "报价对比表.csv": (
        "供应商,单价,总价,备注\n"
        "华信科技,12800,128000,含三年质保\n"
        "中科网络,9800,98000,不含安装\n"
        "恒通电子,11500,115000,含安装\n",
        5,
    ),
    "新能源项目立项报告.md": (
        "# 立项报告\n\n"
        "本项目拟建设分布式光伏与储能系统，装机容量 500kW，"
        "预计年发电量 55 万度。总投资约 320 万元。\n",
        60,
    ),
    "季度预算_2024.csv": (
        "季度,预算,实际,差异\nQ1,1200000,1180000,-20000\n"
        "Q2,1300000,1350000,50000\nQ3,1250000,1210000,-40000\n",
        400,
    ),
    "合同_供应商A_违约金条款.md": (
        "# 采购合同（供应商 A）\n\n"
        "第 8 条 违约责任：任一方逾期交货，应按合同总金额的每日 0.5% 支付违约金；"
        "逾期超过 30 日，守约方有权解除合同并要求赔偿损失。\n",
        20,
    ),
    "notes_meeting_2025-10-12.md": (
        "张经理：新报价已经发给你了，之前那个版本别用了。\n"
        "我：收到，设备采购方案我按最终版更新。\n"
        "张经理：附件是报价对比表，周五前给客户。\n",
        2,
    ),
    "产品需求文档_PRD.md": (
        "# 产品需求文档\n\n目标用户：需要找回历史信息的个人用户。\n"
        "核心能力：跨文件系统与聊天记录的语义检索。\n",
        12,
    ),
    "架构设计_v2.md": (
        "# 架构设计 v2\n\n三路召回：Everything（文件名）、FTS5（正文）、"
        "向量（语义）。RRF 融合后精排，再做跨来源关联。\n",
        7,
    ),
    "data_analysis.py": (
        "import pandas as pd\n\n"
        "def load_sales(path):\n"
        "    return pd.read_csv(path)\n\n"
        "def monthly_growth(df):\n"
        "    return df.groupby('month')['amount'].sum().pct_change()\n",
        30,
    ),
    "客户名单.csv": (
        "客户,联系人,电话\n星河科技,刘总,138xxxx\n远航集团,陈经理,139xxxx\n",
        90,
    ),
    "invoice_2025_09.txt": (
        "Invoice 2025-09\nVendor: 华信科技\nAmount: 128000 CNY\n"
        "Description: server procurement, final quotation\n",
        35,
    ),
    "photo_2025.jpg": ("not-a-real-image", 15),  # binary placeholder, name-only
    "readme.md": ("# Demo corpus\n\nUsed by aimem smoke tests.\n", 360),
}


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for name, (content, days) in FILES.items():
        p = ROOT / name
        p.write_text(content, encoding="utf-8")
        ts = now - days * 86400
        os.utime(p, (ts, ts))
    # an excluded directory that must never be indexed
    nm = ROOT / "node_modules" / "junk.js"
    nm.parent.mkdir(exist_ok=True)
    nm.write_text("should not be indexed", encoding="utf-8")
    print(f"wrote {len(FILES)} files to {ROOT}")


if __name__ == "__main__":
    main()
