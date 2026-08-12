#!/usr/bin/env python3
"""
联邦投顾 — 盘前预判报告 V1.0
============================
纯宏观锚点，不拉全池日线。时段：06:00-09:00，其他时段可调用但不推荐。

数据源:
  VIX       → AnySearch CLI search "CBOE VIX index"  → web_search兜底
  DXY       → AnySearch CLI search "DXY US Dollar Index" → web_search兜底
  US10Y     → AnySearch CLI search "US 10-year Treasury yield" → web_search兜底
  ES/NQ     → AnySearch CLI search "S&P 500 E-mini futures ES" → web_search兜底
  CRB       → AnySearch CLI search "CRB Commodity Index" → web_search兜底
  DR007     → AnySearch CLI search "DR007 加权均价 2026年X月X日" → web_search兜底
  USDCNY    → AnySearch CLI search "美元兑人民币 USDCNY" → web_search兜底
  Gamma     → AnySearch CLI search "SPX gamma exposure flip level" (周一/周五)
  杠杆率    → AnySearch CLI search "银行间质押式回购日均余额" (每周一)

用法:
  python3 scripts/premarket_report.py              # Markdown输出
  python3 scripts/premarket_report.py --json        # JSON输出(供LLM消费)
  python3 scripts/premarket_report.py --table       # 仅数据表
"""

import json
import sys
import os
import subprocess
import re
from pathlib import Path
from datetime import datetime

WORKSPACE = Path(__file__).parent.parent
ANYSEARCH_CLI = WORKSPACE / "skills" / "anysearch" / "scripts" / "anysearch_cli.py"


def anysearch(query, freshness="day", max_results=3):
    """调用 AnySearch CLI 搜索"""
    try:
        cmd = [
            "python3", str(ANYSEARCH_CLI), "search", query,
            "--max_results", str(max_results),
            "--freshness", freshness
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception as e:
        return None


def web_search_fallback(query):
    """web_search 兜底 — 由 LLM 侧调用，脚本侧留接口"""
    return {"source": "web_search", "query": query, "status": "pending_llm_fetch"}


def extract_number_priority(text, patterns):
    """按优先级尝试多个正则，返回第一个有效数值。
    加入合理性过滤：VIX在10-80、DXY在80-120、US10Y在2-8、ES在3000-8000、
    CRB在100-600、DR007在1-3、USDCNY在6-8、Gamma在3000-7000。
    """
    if not text:
        return None
    for pattern, vmin, vmax in patterns:
        for m in re.finditer(pattern, text):
            try:
                val = float(m.group(1))
                if vmin <= val <= vmax:
                    return val
            except (ValueError, IndexError):
                continue
    return None


def fetch_vix():
    """拉取 VIX"""
    text = anysearch("CBOE VIX index real-time value")
    val = extract_number_priority(text, [
        (r"VIX[:\s]*(\d+\.?\d*)", 10, 80),
        (r"(\d+\.?\d*)", 10, 80),
    ])
    return {
        "value": val,
        "source": "AnySearch" if val else "web_search_pending",
        "raw": text[:500] if text else None
    }


def fetch_dxy():
    """拉取 DXY"""
    text = anysearch("DXY US Dollar Index value today")
    val = extract_number_priority(text, [
        (r"DXY[:\s]*(\d+\.?\d*)", 80, 120),
        (r"(\d{2,3}\.\d{2,3})", 80, 120),
    ])
    return {
        "value": val,
        "source": "AnySearch" if val else "web_search_pending",
        "raw": text[:500] if text else None
    }


def fetch_us10y():
    """拉取 US10Y"""
    text = anysearch("US 10-year Treasury bond yield percent today")
    val = extract_number_priority(text, [
        (r"[Yy]ield[:\s]*(\d+\.?\d*)", 2, 8),
        (r"(\d\.\d{1,2})%", 2, 8),
        (r"(\d\.\d{1,2})", 2, 8),
    ])
    return {
        "value": val,
        "source": "AnySearch" if val else "web_search_pending",
        "raw": text[:500] if text else None
    }


def fetch_es():
    """拉取 S&P 500 E-mini futures"""
    text = anysearch("S&P 500 E-mini futures ES price today")
    val = extract_number_priority(text, [
        (r"[Pp]rice[:\s]*(\d{4,}\.?\d*)", 3000, 8000),
        (r"(\d{4,}\.?\d{2})", 3000, 8000),
    ])
    return {
        "value": val,
        "source": "AnySearch" if val else "web_search_pending",
        "raw": text[:500] if text else None
    }


def fetch_crb():
    """拉取 CRB 商品指数"""
    text = anysearch("CRB Commodity Index Thomson Reuters value today")
    val = extract_number_priority(text, [
        (r"(\d{3}\.?\d*)", 100, 600),
    ])
    return {
        "value": val,
        "source": "AnySearch" if val else "web_search_pending",
        "raw": text[:500] if text else None
    }


def fetch_dr007():
    """拉取 DR007"""
    today = datetime.now().strftime("%Y年%m月%d日")
    text = anysearch(f"DR007 加权均价 {today}")
    val = extract_number_priority(text, [
        (r"DR007[:\s]*(\d\.\d+)", 1, 3),
        (r"(\d\.\d{2,4})", 1, 3),
    ])
    return {
        "value": val,
        "source": "AnySearch" if val else "web_search_pending",
        "raw": text[:500] if text else None
    }


def fetch_usdcny():
    """拉取 USDCNY"""
    today = datetime.now().strftime("%Y年%m月%d日")
    text = anysearch(f"美元兑人民币 USDCNY 汇率 {today}")
    val = extract_number_priority(text, [
        (r"(\d\.\d{4})", 6, 8),
        (r"(\d\.\d{3,4})", 6, 8),
    ])
    return {
        "value": val,
        "source": "AnySearch" if val else "web_search_pending",
        "raw": text[:500] if text else None
    }


def fetch_gamma():
    """拉取 SPX Gamma 翻转位（周一/周五）"""
    today = datetime.now().strftime("%Y-%m-%d")
    text = anysearch(f"SPX gamma exposure flip level {today}", freshness="week")
    val = extract_number_priority(text, [
        (r"[Ff]lip[:\s]*(\d{4,}\.?\d*)", 3000, 7000),
        (r"(\d{4,}\.?\d{2})", 3000, 7000),
    ])
    return {
        "value": val,
        "source": "AnySearch" if val else "web_search_pending",
        "raw": text[:500] if text else None
    }


def classify_vix(val):
    """VIX 三档分类"""
    if val is None:
        return "⚠️"
    if val > 35:
        return "🟢"
    elif val <= 20:
        return "🟡"
    else:
        return "🔴"


def classify_dxy(text_raw):
    """DXY MA20 方向判定 — 脚本侧尽力，LLM 可覆写"""
    if text_raw and "down" in text_raw.lower():
        return "🟢"
    elif text_raw and "up" in text_raw.lower():
        return "🔴"
    return "🟡"


def classify_us10y(val):
    """US10Y 三阈值分类"""
    if val is None:
        return "⚠️"
    if val >= 5.0:
        return "🔴"
    elif val >= 4.50:
        return "🟢"
    else:
        return "🟢"


def format_markdown(data):
    """输出 Markdown 盘前报告"""
    ts = data.get("timestamp", datetime.now().isoformat())
    date_str = ts[:10]

    lines = []
    lines.append(f"# 🌅 盘前预判 — {date_str}")
    lines.append("")

    # 数据源摘要
    sources = []
    for k, v in data.get("sources", {}).items():
        sources.append(f"{k}: {v}")
    lines.append(f"🔴 P0覆写摘要：{' / '.join(sources)}")
    lines.append("")

    # 一、全球重力场
    lines.append("## 一、全球重力场")
    lines.append("")
    lines.append("| 锚点 | 现价 | 方向 | 信号灯 | 传导预判 |")
    lines.append("|:---|---:|:---:|:---:|:---|")
    gf = data.get("global_gravity", {})

    es = gf.get("ES_NQ", {})
    es_val = es.get("value", "—")
    lines.append(f"| ES/NQ | {es_val} | — | — | IVV/VTI/QQQ: 待LLM判定 |")

    dxy = gf.get("DXY", {})
    dxy_val = dxy.get("value", "—")
    lines.append(f"| DXY | {dxy_val} | — | — | 待LLM判定 |")

    us10y = gf.get("US10Y", {})
    us10y_val = us10y.get("value", "—")
    lines.append(f"| US10Y | {us10y_val}% | — | — | 待LLM判定 |")

    vix = gf.get("VIX", {})
    vix_val = vix.get("value", "—")
    lines.append(f"| VIX | {vix_val} | — | — | 待LLM判定 |")

    crb = gf.get("CRB", {})
    crb_val = crb.get("value", "—")
    lines.append(f"| CRB | {crb_val} | — | — | 待LLM判定 |")
    lines.append("")

    # 二、中国区压强
    cn = data.get("china_pressure", {})
    lines.append("## 二、中国区压强")
    lines.append("")
    dr007 = cn.get("DR007", {})
    lines.append(f"├── DR007: {dr007.get('value', '—')}% [—]")
    lines.append(f"├── 杠杆率分位: — (待获取)")
    usdcny = cn.get("USDCNY", {})
    lines.append(f"├── USDCNY: {usdcny.get('value', '—')}")
    lines.append(f"└── 综合: 待LLM判定")
    lines.append("")

    # 三、Gamma翻转位
    gamma = data.get("gamma", {})
    lines.append("## 三、Gamma翻转位")
    lines.append("")
    lines.append(f"├── SPX: — | Gamma翻: {gamma.get('value', '—')} | 距: — | 信号灯: —")
    lines.append("")

    # 四、今日作战基调（LLM填空）
    lines.append("## 四、今日作战基调")
    lines.append("")
    lines.append("├── 风险偏好: 待LLM判定")
    lines.append("├── 操作基调: 待LLM判定")
    lines.append("├── 开盘盯防: 待LLM判定")
    lines.append("└── 核心变量: 待LLM判定")
    lines.append("")
    lines.append("---")
    lines.append("⚠️ 以上为物理数据层，叙事解读由LLM完成。")
    return "\n".join(lines)


def format_table(data):
    """仅数据表模式"""
    gf = data.get("global_gravity", {})
    es = gf.get("ES_NQ", {}).get("value", "—")
    dxy = gf.get("DXY", {}).get("value", "—")
    us10y = gf.get("US10Y", {}).get("value", "—")
    vix = gf.get("VIX", {}).get("value", "—")
    crb = gf.get("CRB", {}).get("value", "—")
    dr007 = data.get("china_pressure", {}).get("DR007", {}).get("value", "—")
    usdcny = data.get("china_pressure", {}).get("USDCNY", {}).get("value", "—")
    gamma = data.get("gamma", {}).get("value", "—")

    return f"ES={es} DXY={dxy} US10Y={us10y}% VIX={vix} CRB={crb} DR007={dr007}% USDCNY={usdcny} Gamma={gamma}"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="联邦投顾盘前预判报告")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--table", action="store_true", help="仅数据表")
    args = parser.parse_args()

    now = datetime.now()
    ts = now.isoformat()

    # 并行拉取所有锚点
    data = {
        "timestamp": ts,
        "global_gravity": {
            "ES_NQ": fetch_es(),
            "DXY": fetch_dxy(),
            "US10Y": fetch_us10y(),
            "VIX": fetch_vix(),
            "CRB": fetch_crb(),
        },
        "china_pressure": {
            "DR007": fetch_dr007(),
            "USDCNY": fetch_usdcny(),
            "leverage_percentile": {"value": None, "source": "weekly_only"},
        },
        "gamma": fetch_gamma(),
        "sources": {
            "ES_NQ": "AnySearch",
            "DXY": "AnySearch",
            "US10Y": "AnySearch",
            "VIX": "AnySearch",
            "CRB": "AnySearch",
            "DR007": "AnySearch",
            "USDCNY": "AnySearch",
            "Gamma": "AnySearch (周一/周五)",
        }
    }

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    elif args.table:
        print(format_table(data))
    else:
        print(format_markdown(data))


if __name__ == "__main__":
    main()
