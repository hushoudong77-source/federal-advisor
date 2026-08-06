#!/usr/bin/env python3
"""
V3.0 — 从 TradingEconomics HTML 源码提取经济日历事件。
修复: HTML标签中的日期匹配，事件名从<th>间提取。

输出: memory/economic_calendar.md
"""

import re
import sys
import os
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

URL = "https://zh.tradingeconomics.com/united-states/calendar"
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "memory", "economic_calendar.md")

# C3.1 事件精确匹配（中文名）
C31_EVENTS = [
    ("非农就业数据", "🔴🔴🔴"),
    ("ADP就业人数变化", "🔴"),
    ("失业率", "🔴🔴"),
    ("首次申请失业救济人数", "🟡"),
    ("持续申请失业救济人数", "🟡"),
    ("核心通胀率（环比）", "🔴🔴🔴"),
    ("核心通胀率（同比）", "🔴🔴🔴"),
    ("月度通货膨胀率", "🔴🔴"),
    ("同比通货膨胀率", "🔴🔴"),
    ("核心个人消费支出价格指数（环比）", "🔴🔴🔴"),
    ("核心个人消费支出物价指数（同比）", "🔴🔴🔴"),
    ("个人消费支出价格指数（月度）", "🔴🔴"),
    ("生产者价格指数（月度）", "🔴"),
    ("核心生产者价格指数(环比)", "🔴"),
    ("生产者价格指数同比", "🔴"),
    ("国内生产总值增长率", "🔴🔴"),
    ("联邦公开市场委员会会议纪要", "🔴🔴🔴"),
    ("零售销售（月率环比)", "🔴🔴"),
    ("零售销售控制组环比", "🔴"),
    ("美国供应管理协会服务业采购经理人指数", "🔴"),
    ("美国供应管理协会制造业采购经理人指数", "🔴"),
    ("标准普尔全球综合采购经理人指数", "🔴"),
    ("标准普尔全球服务业采购经理人指数", "🔴"),
    ("标准普尔全球制造业采购经理人指数", "🔴"),
    ("世界大型企业联合会消费者信心指数", "🔴"),
    ("密歇根大学消费者信心", "🟡"),
    ("新屋开工", "🟡"),
    ("建筑许可证（初值）", "🟡"),
    ("成屋销售", "🟡"),
    ("新屋销售", "🟡"),
    ("杰克逊霍尔研讨会", "🔴🔴"),
    ("美国挑战者企业裁员", "🟡"),
    ("消费者价格指数", "🔴🔴"),
    ("非农就业私人", "🔴"),
    ("国内生产总值价格指数", "🔴"),
    ("（初值）非农生产率", "🟡"),
    ("（初值）密歇根大学消费者信心", "🟡"),
]


def fetch_page():
    req = Request(URL, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return raw
    except URLError as e:
        print(f"[ERROR] 拉取失败: {e}", file=sys.stderr)
        return None


def parse_events(html):
    """从HTML中提取事件。事件结构:
    <th>DD/MM/YYYY</th>
    ...
    <td>HH:MM AM/PM</td>
    ...
    <td>事件名</td>
    ...
    前值/预期在后续<td>中
    """
    today = datetime.now()
    events = []

    # 去掉HTML标签，保留文本和结构
    # 简化: 找到所有日期→事件对
    text = html

    # 找所有日期
    date_positions = [(m.start(), m.group(1)) for m in re.finditer(r'>\s*(\d{2}/\d{2}/\d{4})\s*<', text)]

    for i, (pos, date_str) in enumerate(date_positions):
        # 解析日期 (DD/MM/YYYY)
        try:
            event_date = datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            continue

        # 只保留今天-2天到未来14天
        if event_date < today - timedelta(days=2):
            continue
        if event_date > today + timedelta(days=14):
            continue

        # 取该日期到下一个日期之间的文本块
        next_pos = date_positions[i + 1][0] if i + 1 < len(date_positions) else len(text)
        block = text[pos:next_pos]

        # 在block中搜索C3.1事件
        for event_name, importance in C31_EVENTS:
            # 事件名通常在 <td>...</td> 中
            pattern = re.escape(event_name)
            if re.search(pattern, block):
                # 提取时间
                time_match = re.search(r'(\d{2}:\d{2})\s*(AM|PM)', block)
                event_time = f"{time_match.group(1)} {time_match.group(2)}" if time_match else ""

                # 提取前值和预期 - 在事件名后面找数字
                idx = block.find(event_name)
                after = block[idx + len(event_name):]
                nums = re.findall(r'>\s*([\d.,\-]+[KMB%]?)\s*<', after[:500])
                prev_val = nums[0] if len(nums) > 0 else ""
                cons_val = nums[2] if len(nums) > 2 else ""

                events.append({
                    "date_obj": event_date,
                    "date_str": date_str,
                    "time": event_time,
                    "event": event_name,
                    "importance": importance,
                    "previous": prev_val,
                    "consensus": cons_val,
                })
                break

    # 去重排序
    seen = set()
    unique = []
    for e in events:
        key = (e["date_str"], e["event"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda x: x["date_obj"])
    return unique


def format_markdown(events):
    today = datetime.now()
    lines = [
        f"# 📅 美国经济日历 — C3.1 宏观事件",
        f"",
        f"> 数据源: TradingEconomics | 更新: {today.strftime('%Y-%m-%d %H:%M')} UTC+8",
        f"> C3.1 规则: 一次性数据公布前2后1交易日静默 | 持续性地缘事件豁免",
        f"",
        f"## 近期关键事件",
        f"",
        f"| 日期 | 时间(ET) | 事件 | 前值 | 预期 | 重要度 |",
        f"|:---|:---|:---|:---:|:---:|:---:|",
    ]

    for e in events:
        lines.append(
            f"| {e['date_str']} | {e['time']} | {e['event']} | {e['previous']} | {e['consensus']} | {e['importance']} |"
        )

    if not events:
        lines.append("| — | — | 未来14天暂无C3.1关键事件 | — | — | — |")

    lines.append("")
    lines.append("## C3.1 静默期判定")
    lines.append("")

    # 找最早的高影响事件
    high = [e for e in events if "🔴🔴🔴" in e["importance"]]
    if not high:
        high = [e for e in events if "🔴🔴" in e["importance"]]
    if not high:
        high = [e for e in events if "🔴" in e["importance"]]

    if high:
        next_event = high[0]
        edate = next_event["date_obj"]
        quiet_start = edate - timedelta(days=2)
        quiet_end = edate + timedelta(days=1)

        if quiet_start <= today <= quiet_end:
            lines.append(f"⚠️ **静默期激活** — {next_event['event']} ({edate.strftime('%m/%d')})")
        else:
            lines.append(f"🟢 当前无C3.1静默期")

        lines.append(f"├── 最近关键事件: {next_event['event']} ({edate.strftime('%m/%d')})")
        lines.append(f"├── 静默窗口: {quiet_start.strftime('%m/%d')} ~ {quiet_end.strftime('%m/%d')}")
        if quiet_start <= today <= quiet_end:
            lines.append(f"├── 美股进攻: ⛔暂停 | A股: ✅豁免")
            lines.append(f"└── 动量: ⛔暂停 | 金盾+固定层: ✅豁免")
    else:
        lines.append("🟢 当前无C3.1静默期（未来14天无C3.1关键事件）")

    # 杰克逊霍尔
    jh = [e for e in events if "杰克逊霍尔" in e["event"]]
    if jh:
        lines.append("")
        lines.append(f"⚠️ **杰克逊霍尔研讨会**: {jh[0]['date_str']} ~ {jh[-1]['date_str']}")

    lines.append("")
    lines.append("---")
    lines.append(f"*自动生成 | fetch_economic_calendar.py V3.0*")

    return "\n".join(lines)


def main():
    print("[fetch_economic_calendar V3] 拉取中...")
    raw = fetch_page()
    if raw is None:
        sys.exit(1)

    events = parse_events(raw)
    print(f"[fetch_economic_calendar V3] 解析到 {len(events)} 个近期关键事件:")
    for e in events[:10]:
        print(f"  {e['date_str']} | {e['time']} | {e['event']} | {e['importance']}")

    md = format_markdown(events)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[fetch_economic_calendar V3] 已写入")


if __name__ == "__main__":
    main()
