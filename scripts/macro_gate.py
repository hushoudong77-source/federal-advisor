#!/usr/bin/env python3
"""
联邦投顾 — 宏观闸模块 V1.0
职责：在路由判定之前，判断全局宏观环境是否允许开火。
输出：结构化宏观状态（VIX档位/US10Y档位/事件静默/C3.1分层裁决）

数据源：
  US10Y → Tushare pro.us_tycr（P2 API真源）
  VIX   → web_search "VIX CBOE"（P4兜底，AnySearch不可用时）
  事件  → 硬编码近60天已知宏观事件（非农/CPI/FOMC）

用法：
  python3 scripts/macro_gate.py              # JSON输出
  python3 scripts/macro_gate.py --table       # 表格
"""

import json
import sys
import os
from datetime import datetime, date, timedelta
import re


# ============================================================
# 第一层：US10Y — Tushare us_tycr
# ============================================================
def fetch_us10y():
    """拉取最新US10Y收益率"""
    try:
        import tushare as ts
        pro = ts.pro_api()
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=10)).strftime("%Y%m%d")
        df = pro.us_tycr(start_date=start, end_date=end)
        if df is None or len(df) == 0:
            return {"value": None, "source": "tushare_empty", "error": "无数据"}

        # us_tycr返回收益率曲线面板：列=y10=US10Y
        df_sorted = df.sort_values("date", ascending=False)
        latest = df_sorted.iloc[0]
        value = float(latest["y10"])

        prev_value = None
        if len(df_sorted) >= 2:
            prev_value = float(df_sorted.iloc[1]["y10"])

        return {
            "value": round(value, 4),
            "date": str(latest["date"]),
            "prev_value": round(prev_value, 4) if prev_value else None,
            "change_bp": round((value - prev_value) * 100, 1) if prev_value else None,
            "source": "tushare_us_tycr"
        }

    except Exception as e:
        return {"value": None, "source": "tushare_error", "error": str(e)[:100]}


def classify_us10y(us10y_value):
    """US10Y三阈值分类（r33.30方向性翻转）"""
    if us10y_value is None:
        return {"level": "unknown", "label": "数据缺失", "action": "⚠️无法判定"}
    if us10y_value >= 5.00:
        return {"level": "meltdown", "label": "🔴熔断", "action": "全局暂停进攻开火"}
    if us10y_value >= 4.75:
        return {"level": "observe", "label": "🟡观察", "action": "仅提醒不调仓（n=17样本不足）"}
    if us10y_value >= 4.50:
        return {"level": "opportunity", "label": "🟢机会", "action": "进攻正常执行"}
    return {"level": "normal", "label": "⚪正常", "action": "无动作"}


# ============================================================
# 第二层：VIX — web_search（P4兜底）
# ============================================================
def fetch_vix():
    """拉取VIX实时值"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        anysearch_cli = os.path.join(script_dir, "..", "skills", "anysearch", "scripts", "anysearch_cli.py")
        import subprocess
        result = subprocess.run(
            ["python3", anysearch_cli, "search", "CBOE VIX index real-time", "--max_results", "3", "--freshness", "day"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout:
            matches = re.findall(r'VIX[:\s]*(\d{1,2}\.\d{1,2})', result.stdout, re.IGNORECASE)
            if matches:
                value = float(matches[0])
                if 5 < value < 100:
                    return {"value": value, "source": "anysearch"}
    except Exception:
        pass

    return {"value": None, "source": "unavailable", "error": "VIX不可用"}


def classify_vix(vix_value):
    """VIX四档危机状态机"""
    if vix_value is None:
        return {"level": "unknown", "label": "数据缺失", "action": "⚠️保守处理"}
    if vix_value > 50:
        return {"level": "meltdown", "label": "🔴🔴崩溃", "action": "全局熔断。黄金禁止买入。"}
    if vix_value > 35:
        return {"level": "crisis", "label": "🔴危机", "action": "暂停进攻/反击开火。黄金可买不追高。"}
    if vix_value > 20:
        return {"level": "alert", "label": "🟡警戒", "action": "进攻仓位减半。反击正常。"}
    return {"level": "normal", "label": "🟢正常", "action": "全策略正常"}


# ============================================================
# 第三层：C3.1 宏观事件静默
# ============================================================
# 一次性数据公布（触发静默）：非农/CPI/FOMC/央行决议
# 持续性地缘事件（不触发静默）：霍尔木兹/贸易战 — 豁免（r33.69）
KNOWN_EVENTS = [
    ("2026-08-01", "非农就业报告 7月", "one_time"),
    ("2026-08-12", "CPI 7月", "one_time"),
    ("2026-08-13", "PPI 7月", "one_time"),
    ("2026-08-27", "PCE 7月", "one_time"),
    ("2026-09-04", "非农就业报告 8月", "one_time"),
    ("2026-09-10", "CPI 8月", "one_time"),
    ("2026-09-16", "FOMC利率决议", "one_time"),
    ("2026-09-24", "PCE 8月", "one_time"),
    ("2026-10-02", "非农就业报告 9月", "one_time"),
]


def check_event_silence():
    """检查未来72小时内是否有🔴一次性宏观事件"""
    today = date.today()
    cutoff = today + timedelta(days=3)

    active_events = []
    silence_start = None
    silence_end = None

    for evt_date_str, evt_name, evt_type in KNOWN_EVENTS:
        if evt_type != "one_time":
            continue
        evt_date = datetime.strptime(evt_date_str, "%Y-%m-%d").date()
        win_start = evt_date - timedelta(days=2)
        win_end = evt_date + timedelta(days=1)

        if win_start <= cutoff and today <= win_end:
            active_events.append({
                "event": evt_name,
                "date": evt_date_str,
                "window": f"{win_start} ~ {win_end}"
            })

    if active_events:
        silence_start = min(
            datetime.strptime(e["date"], "%Y-%m-%d").date() - timedelta(days=2)
            for e in active_events
        )
        silence_end = max(
            datetime.strptime(e["date"], "%Y-%m-%d").date() + timedelta(days=1)
            for e in active_events
        )

    return {
        "in_silence": len(active_events) > 0,
        "events": active_events,
        "silence_start": str(silence_start) if silence_start else None,
        "silence_end": str(silence_end) if silence_end else None,
    }


def apply_c31_layered(events_in_silence):
    """C3.1分层裁决（r33.51 A股豁免）"""
    if not events_in_silence:
        return {
            "us_offensive": "✅正常",
            "hk_counterpunch": "✅正常",
            "a_offensive": "✅正常",
            "a_counterpunch": "✅正常",
            "momentum": "✅正常",
            "gold_shield": "✅正常",
            "fixed_layer": "✅正常",
        }

    return {
        "us_offensive": "⛔暂停（前2后1共4日）",
        "hk_counterpunch": "🟡降级（建仓推迟72h）",
        "a_offensive": "✅豁免（中国区三锚独立驱动）",
        "a_counterpunch": "✅豁免（CPI低开=加速触达）",
        "momentum": "⛔暂停",
        "gold_shield": "✅豁免",
        "fixed_layer": "✅豁免",
    }


# ============================================================
# 综合输出
# ============================================================
def assess_all():
    """一键获取所有宏观闸状态"""
    us10y = fetch_us10y()
    us10y_class = classify_us10y(us10y.get("value"))

    vix = fetch_vix()
    vix_class = classify_vix(vix.get("value"))

    events = check_event_silence()
    layered = apply_c31_layered(events.get("events", []))

    vix_level = vix_class["level"]
    us10y_level = us10y_class["level"]

    global_meltdown = (vix_level == "meltdown" or us10y_level == "meltdown")
    crisis_mode = (vix_level == "crisis") and not global_meltdown

    offensive_allowed = not global_meltdown and not crisis_mode
    if us10y_level == "meltdown":
        offensive_allowed = False

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "us10y": {
            "value": us10y.get("value"),
            "change_bp": us10y.get("change_bp"),
            "date": us10y.get("date"),
            "source": us10y.get("source"),
            **us10y_class,
        },
        "vix": {
            "value": vix.get("value"),
            "source": vix.get("source"),
            **vix_class,
        },
        "c31_events": events,
        "c31_layered": layered,
        "verdict": {
            "global_meltdown": global_meltdown,
            "crisis_mode": crisis_mode,
            "offensive_allowed": offensive_allowed,
            "summary": _summarize(global_meltdown, crisis_mode, offensive_allowed,
                                  us10y_class, vix_class, events),
        }
    }


def _summarize(global_meltdown, crisis_mode, offensive_allowed, us10y, vix, events):
    if global_meltdown:
        return "🔴全局熔断——暂停所有进攻/反击开火。"
    if crisis_mode:
        return "🔴危机模式——暂停进攻/反击新开仓。"
    if events.get("in_silence"):
        evt_names = [e["event"] for e in events["events"]]
        return f"🟡事件静默中（{', '.join(evt_names)}）——美股进攻⛔。A股✅豁免。"
    if us10y["level"] == "observe":
        return "🟡US10Y≥4.75%——仅提醒不调仓。"
    if us10y["level"] == "opportunity":
        return "🟢US10Y≥4.50%机会区间——进攻正常。"
    return "🟢宏观闸通过——全策略正常执行。"


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    result = assess_all()
    if "--table" in sys.argv:
        u = result["us10y"]
        v = result["vix"]
        e = result["c31_events"]
        print(f"US10Y: {u['value']}% ({u['label']})  |  VIX: {v['value']} ({v['label']})")
        print(f"事件静默: {'是' if e['in_silence'] else '否'}  |  {result['verdict']['summary']}")
        print()
        print("C3.1分层裁决:")
        for k, v in result["c31_layered"].items():
            print(f"  {k}: {v}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
