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
# 宏观锚点 TTL 缓存（V1.0 — 2026-08-13 焊入，解决 /开火 反应慢）
# 根因：US10Y/VIX/DXY/CNN情绪这些宏观锚点一天内变化极小，
#       但每次 /开火 都串行拉 AnySearch（每次2-5秒），导致25秒延迟。
# 方案：文件缓存 + TTL，命中缓存时跳过网络请求。
# ============================================================
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tmp", "macro_cache")
CACHE_TTL_SECONDS = 1800  # 30分钟TTL，宏观锚点30分钟内复用

def _cache_path(key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{key}.json")

def _cache_read(key):
    """读缓存，命中且未过期返回 (True, data)，否则 (False, None)"""
    try:
        p = _cache_path(key)
        if not os.path.exists(p):
            return False, None
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        # TTL 检查
        ts = data.get("_cached_ts", 0)
        if time.time() - ts > CACHE_TTL_SECONDS:
            return False, None
        return True, data
    except Exception:
        return False, None

def _cache_write(key, data):
    """写缓存（附带时间戳）"""
    try:
        data = dict(data)
        data["_cached_ts"] = time.time()
        data["_cached"] = True
        with open(_cache_path(key), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

import time

# ============================================================
# AnySearch CLI 调用辅助（统一入口，避免重复代码）
# ============================================================
def _anysearch_extract(url):
    """用 AnySearch extract 抓取页面文本。失败返回空串。"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        anysearch_cli = os.path.join(script_dir, "..", "skills", "anysearch", "scripts", "anysearch_cli.py")
        import subprocess
        result = subprocess.run(
            ["python3", anysearch_cli, "extract", url],
            capture_output=True, text=True, timeout=20
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


# ============================================================
# 第一层：US10Y — CNBC extract（Tushare 已退役，2026-08-13 切换）
# ============================================================
def fetch_us10y():
    """拉取最新US10Y收益率（带30分钟TTL缓存）。
    数据源：CNBC US10Y 页面 extract，抓 "Yield | ... 4.678%" 行。
    """
    hit, cached = _cache_read("us10y")
    if hit:
        return cached

    text = _anysearch_extract("https://www.cnbc.com/quotes/US10Y")
    value = None
    prev_value = None
    if text:
        # 抓 "Yield | HH:MM" 后的收益率值（CNBC 页面格式：Yield | 12:56 PM EDT\n\n4.678%-0.006）
        yield_match = re.search(r'Yield\s*\|\s*[^\n]*\n+\s*(\d\.\d{3})\s*%', text)
        if yield_match:
            value = float(yield_match.group(1))
        # Prev Close
        prev_match = re.search(r'Yield\s*Prev\s*Close\s*(\d\.\d{3})\s*%', text)
        if prev_match:
            prev_value = float(prev_match.group(1))

    if value is not None:
        r = {
            "value": round(value, 4),
            "date": date.today().strftime("%Y-%m-%d"),
            "prev_value": round(prev_value, 4) if prev_value else None,
            "change_bp": round((value - prev_value) * 100, 1) if prev_value else None,
            "source": "cnbc_extract"
        }
        _cache_write("us10y", r)
        return r

    return {"value": None, "source": "unavailable", "error": "US10Y不可用"}


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
# 第二层：VIX — CNBC extract（2026-08-13 切换）
# ============================================================
def fetch_vix():
    """拉取VIX实时值（带30分钟TTL缓存）。
    数据源：CNBC .VIX 页面 extract，抓 "Last | ... 14.67" 行。
    """
    hit, cached = _cache_read("vix")
    if hit:
        return cached

    text = _anysearch_extract("https://www.cnbc.com/quotes/.VIX")
    value = None
    prev_value = None
    if text:
        # CNBC 格式：Last | 12:56 PM EDT\n\n14.67-0.61(-3.99%)
        last_match = re.search(r'Last\s*\|\s*[^\n]*\n+\s*(\d{1,2}\.\d{1,2})', text)
        if last_match:
            value = float(last_match.group(1))
        prev_match = re.search(r'Prev\s*Close\s*(\d{1,2}\.\d{2})', text)
        if prev_match:
            prev_value = float(prev_match.group(1))

    if value is not None and 5 < value < 100:
        r = {
            "value": round(value, 2),
            "prev_value": round(prev_value, 2) if prev_value else None,
            "source": "cnbc_extract"
        }
        _cache_write("vix", r)
        return r

    return {"value": None, "source": "unavailable", "error": "VIX不可用"}


# ============================================================
# 第二层.五：DXY — CNBC extract（2026-08-13 切换）
# ============================================================
def fetch_dxy():
    """拉取DXY美元指数（带30分钟TTL缓存）。
    数据源：CNBC .DXY 页面 extract，抓 "Last | ... 99.949" 行。
    """
    hit, cached = _cache_read("dxy")
    if hit:
        return cached

    text = _anysearch_extract("https://www.cnbc.com/quotes/.DXY")
    value = None
    prev_value = None
    if text:
        # CNBC 格式：Last | 12:57 PM EDT\n\n99.949+0.121(+0.12%)
        last_match = re.search(r'Last\s*\|\s*[^\n]*\n+\s*(\d{2,3}\.\d{2,3})', text)
        if last_match:
            value = float(last_match.group(1))
        prev_match = re.search(r'Prev\s*Close\s*(\d{2,3}\.\d{2,3})', text)
        if prev_match:
            prev_value = float(prev_match.group(1))

    if value is not None and 80 < value < 120:
        # 方向判定：当前值 vs Prev Close
        direction = "→"
        if prev_value is not None:
            if value > prev_value + 0.05:
                direction = "↑"
            elif value < prev_value - 0.05:
                direction = "↓"
        r = {"value": round(value, 3), "source": "cnbc_extract", "direction": direction}
        _cache_write("dxy", r)
        return r

    return {"value": None, "source": "unavailable", "error": "DXY不可用"}


def classify_dxy(dxy):
    """DXY MA20方向分类
    r33.29：DXY MA20↓=🟢弱美元利好 / 走平=🟡 / DXY MA20↑=🔴强美元利空
    """
    dxy_value = dxy.get("value") if isinstance(dxy, dict) else dxy
    direction = dxy.get("direction", "—") if isinstance(dxy, dict) else "—"
    
    if dxy_value is None:
        return {"level": "unknown", "label": "数据缺失", "direction": "—"}
    
    if direction == "↓":
        return {"level": "bullish", "label": "🟢弱美元利好", "direction": "↓"}
    elif direction == "↑":
        return {"level": "bearish", "label": "🔴强美元利空", "direction": "↑"}
    else:
        return {"level": "neutral", "label": "🟡走平", "direction": "→"}


def classify_vix(vix_value):
    """VIX分类 — r33.29 方向翻转：恐慌=机会，低VIX=自满风险
    
    回测铁证（2018-2026 Tushare全量）：
      VIX>35 → 20D IVV +2.09% 胜率72% → 🟢最佳买入窗口
      VIX≤20 → 20D IVV +0.99% 胜率75% → 🟡自满风险，尾部最大
      VIX 20-35 → 20D IVV +0.31% 胜率60% → 🔴方向不明，最差收益
    """
    if vix_value is None:
        return {"level": "unknown", "label": "数据缺失", "action": "⚠️保守处理"}
    if vix_value > 50:
        return {"level": "meltdown", "label": "🔴🔴崩溃", "action": "全局熔断。黄金禁止买入。"}
    if vix_value > 35:
        return {"level": "crisis", "label": "🟢机会", "action": "恐慌=机会。危机状态机接管路由，二维评估🟢"}
    if vix_value > 20:
        return {"level": "alert", "label": "🔴方向不明", "action": "VIX中位，方向不明。暂停进攻，仅反击/固定层"}
    return {"level": "normal", "label": "🟡自满风险", "action": "VIX极低=自满+黑天鹅未定价。进攻正常但警惕尾部"}


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
    """一键获取所有宏观闸状态。
    2026-08-13 优化：US10Y/VIX/DXY 三个独立网络请求并行执行（ThreadPoolExecutor），
    冷启动时从 ~8秒串行 降到 ~4秒并行。
    """
    # 并行拉取三个宏观锚点（各自有 30 分钟 TTL 缓存，命中缓存时瞬时返回）
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_us10y = pool.submit(fetch_us10y)
        fut_vix = pool.submit(fetch_vix)
        fut_dxy = pool.submit(fetch_dxy)
        us10y = fut_us10y.result()
        vix = fut_vix.result()
        dxy = fut_dxy.result()

    us10y_class = classify_us10y(us10y.get("value"))
    vix_class = classify_vix(vix.get("value"))
    dxy_class = classify_dxy(dxy)

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
        "dxy": {
            "value": dxy.get("value"),
            "source": dxy.get("source"),
            **dxy_class,
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
