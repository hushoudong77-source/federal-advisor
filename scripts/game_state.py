#!/usr/bin/env python3
"""
联邦投顾 — 博弈态判定模块 V1.0
职责：基于VIX/ADX/成交量/情绪四维判定当前市场博弈态，输出仓位硬上限。
数据源：
  VIX     → macro_gate.py 输出（或独立拉取）
  ADX14   → market_data.py 输出的全池ADX14中位数
  成交量  → market_data.py 输出的全池成交量比值中位数
  情绪    → AnySearch CNN Fear & Greed Index（辅助确认层）

判定流程（V2.0 层级投票，三步串行）：
  Step 1【否决层 — VIX前置分流】:
    VIX > 50 → 系统性崩溃态（-∞），终止判定
    28 < VIX ≤ 50 → 震荡爆发态（-3），终止判定
    VIX ≤ 28 → 进入 Step 2

  Step 2【判定层 — ADX + 成交量 联合判定】:
    ADX > 30 ∧ 成交量 ≥ 1.0 → 多空绞杀态（0）
    ADX < 22 ∧ 成交量 < 0.8 ∧ 持续≥3日 → 冷却静默态（+10）
    ADX 20-30 ∧ 成交量 < 1.0 → 噪音衰退态（+5）
    其他 → 取最接近的态 + 标注过渡区间

  Step 3【辅助确认层 — D4情绪分】:
    CNN F&G 仅用于确认 Step 2 判定方向（不独立投票）

仓位硬上限映射：
  震荡爆发态（-3）  → 0%
  多空绞杀态（0）   → 35%
  噪音衰退态（+5）  → 35%
  冷却静默态（+10） → 25%
  系统性崩溃态（-∞）→ 0%

用法：
  python3 scripts/game_state.py                     # JSON输出
  python3 scripts/game_state.py --vix 15.38         # 传入VIX值
  python3 scripts/game_state.py --bridged <json>    # 从 bridged JSON 读取
"""

import json
import sys
import os
import re
from datetime import datetime


# ============================================================
# 五大博弈态定义
# ============================================================
GAME_STATES = {
    -3:   {"name": "震荡爆发态",  "effect": -3,  "cap": 0.0,   "desc": "负和操控，HFT收割散户", "label": "🔴震荡爆发"},
    0:    {"name": "多空绞杀态",  "effect": 0,   "cap": 0.35,  "desc": "零和绞杀，方向不明",   "label": "🟠多空绞杀"},
    5:    {"name": "噪音衰退态",  "effect": 5,   "cap": 0.35,  "desc": "正和收敛，散户滞后",   "label": "🟡噪音衰退"},
    10:   {"name": "冷却静默态",  "effect": 10,  "cap": 0.25,  "desc": "正和均衡，机构收集筹码", "label": "🟢冷却静默"},
    -999: {"name": "系统性崩溃态", "effect": -999, "cap": 0.0,  "desc": "四方亏损，流动性枯竭", "label": "🔴🔴系统性崩溃"},
}


def classify_game_state(vix_value, adx_median, vol_median, vol_days_under_08=0, cnn_fear_greed=None):
    """
    三步串行判定博弈态
    
    Args:
        vix_value: VIX 当前值
        adx_median: 全池标的 ADX14 中位数
        vol_median: 全池标的成交量比值中位数（当日成交量/20日均量）
        vol_days_under_08: 成交量比值<0.8 持续天数（连续交易日）
        cnn_fear_greed: CNN Fear & Greed Index 0-100 分值（可选）
    
    Returns:
        dict: {state_key, name, effect, cap, label, desc, diagnostics}
    """
    diag = {
        "vix": vix_value,
        "adx_median": adx_median,
        "vol_median": vol_median,
        "vol_days_under_08": vol_days_under_08,
        "cnn_fear_greed": cnn_fear_greed,
        "step": "unknown"
    }
    
    # ============================================================
    # Step 1【否决层 — VIX前置分流】
    # ============================================================
    if vix_value is None:
        diag["step"] = "vix_missing"
        result = GAME_STATES[0]  # 默认多空绞杀
        result["diagnostics"] = diag
        result["warning"] = "VIX数据缺失，默认多空绞杀态"
        return result
    
    if vix_value > 50:
        diag["step"] = "step1_vix_meltdown"
        result = GAME_STATES[-999]
        result["diagnostics"] = diag
        return result
    
    if vix_value > 28:
        diag["step"] = "step1_vix_volatile"
        result = GAME_STATES[-3]
        result["diagnostics"] = diag
        return result
    
    # VIX ≤ 28 → Step 2
    diag["step"] = "step2"
    
    # ============================================================
    # Step 2【判定层 — ADX + 成交量 联合判定】
    # ============================================================
    if adx_median is None or vol_median is None:
        diag["step"] = "step2_missing_data"
        result = GAME_STATES[0]  # 默认多空绞杀
        result["diagnostics"] = diag
        result["warning"] = "ADX/成交量数据缺失，默认多空绞杀态"
        return result
    
    # 冷却静默优先判定（优先于噪音衰退）
    if adx_median < 22 and vol_median < 0.8 and vol_days_under_08 >= 3:
        diag["step"] = "step2_cooling"
        result = GAME_STATES[10]
        result["diagnostics"] = diag
        return result
    
    # 多空绞杀
    if adx_median > 30 and vol_median >= 1.0:
        diag["step"] = "step2_choppy"
        result = GAME_STATES[0]
        result["diagnostics"] = diag
        return result
    
    # 噪音衰退
    if 20 <= adx_median <= 30 and vol_median < 1.0:
        diag["step"] = "step2_noise"
        result = GAME_STATES[5]
        result["diagnostics"] = diag
        return result
    
    # 过渡区间——取最接近的态
    diag["step"] = "step2_transition"
    # 优先判定：ADX偏哪边就往哪靠
    if adx_median < 22:
        # ADX低 + 缩量不达标 → 接近冷却静默但缩量不够
        result = GAME_STATES[5]  # 退回到噪音衰退
        result["diagnostics"] = diag
        result["note"] = "过渡区间：ADX低但缩量不达标(vol={:.2f}, days<0.8={})".format(vol_median, vol_days_under_08)
        return result
    elif adx_median > 30:
        # ADX高 + 放量不达标 → 接近多空绞杀但量不够
        result = GAME_STATES[5]  # 退回到噪音衰退
        result["diagnostics"] = diag
        result["note"] = "过渡区间：ADX高但放量不达标(vol={:.2f})".format(vol_median)
        return result
    else:
        result = GAME_STATES[5]  # 默认噪音衰退
        result["diagnostics"] = diag
        result["note"] = "过渡区间：取噪音衰退默认"
        return result


def fetch_cnn_fear_greed():
    """拉取 CNN Fear & Greed Index（辅助确认层 D4，带30分钟TTL缓存）"""
    # 缓存复用（与 macro_gate 共用缓存目录）
    import json as _json
    import time as _time
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tmp", "macro_cache")
    try:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, "cnn_fear_greed.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = _json.load(f)
            if _time.time() - cached.get("_cached_ts", 0) < 1800:
                return cached
    except Exception:
        pass
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        anysearch_cli = os.path.join(script_dir, "..", "skills", "anysearch", "scripts", "anysearch_cli.py")
        import subprocess
        result = subprocess.run(
            ["python3", anysearch_cli, "search", "CNN Fear and Greed Index", "--max_results", "3", "--freshness", "day"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout:
            # 匹配 0-100 的数字
            matches = re.findall(r'(?:Fear.*?Greed|Greed).*?(\d{1,3})', result.stdout)
            if matches:
                val = int(matches[0])
                if 0 <= val <= 100:
                    emotion = "极度恐惧" if val <= 25 else "恐惧" if val <= 40 else "中性" if val <= 60 else "贪婪" if val <= 75 else "极度贪婪"
                    r = {"value": val, "emotion": emotion, "source": "anysearch_cnn"}
                    try:
                        import json as _json, time as _time
                        _r = dict(r); _r["_cached_ts"] = _time.time()
                        with open(cache_path, "w", encoding="utf-8") as _f:
                            _json.dump(_r, _f, ensure_ascii=False)
                    except Exception:
                        pass
                    return r
            
            # 备用匹配
            matches2 = re.findall(r'(?:指数|Index|Value)[:\s]*(\d{1,3})', result.stdout)
            if matches2:
                val = int(matches2[0])
                if 0 <= val <= 100:
                    emotion = "极度恐惧" if val <= 25 else "恐惧" if val <= 40 else "中性" if val <= 60 else "贪婪" if val <= 75 else "极度贪婪"
                    r = {"value": val, "emotion": emotion, "source": "anysearch_cnn"}
                    try:
                        import json as _json, time as _time
                        _r = dict(r); _r["_cached_ts"] = _time.time()
                        with open(cache_path, "w", encoding="utf-8") as _f:
                            _json.dump(_r, _f, ensure_ascii=False)
                    except Exception:
                        pass
                    return r
    except Exception:
        pass
    
    return {"value": None, "source": "unavailable"}


def compute_from_bridged(bridged):
    """
    从 bridged JSON 中提取 VIX/ADX/成交量数据并判定博弈态
    
    bridged 格式（fire_report.py 构建的桥接层）：
    {
        "macro": {"vix": {"value": 15.38, ...}, ...},
        "indicators": {
            "QQQ": {"adx14": 18.5, "vol_ratio": 0.72},
            ...
        }
    }
    """
    # 提取 VIX
    macro = bridged.get("macro", {})
    vix_data = macro.get("vix", {})
    vix_value = vix_data.get("value")
    
    # 从 indicators 计算 ADX 中位数和成交量比值中位数
    indicators = bridged.get("indicators", {})
    adx_values = []
    vol_values = []
    
    for ticker, ind in indicators.items():
        # bridged 嵌套格式: ind["indicators"]["ADX14"]["value"]
        inner = ind.get("indicators", {})
        adx_data = inner.get("ADX14", {})
        adx = adx_data.get("value") if isinstance(adx_data, dict) else adx_data
        if adx is not None and adx > 0:
            adx_values.append(adx)
        vr_data = inner.get("VOL_RATIO", {})
        vr = vr_data.get("value") if isinstance(vr_data, dict) else vr_data
        if vr is not None and vr > 0:
            vol_values.append(vr)
    
    adx_median = sorted(adx_values)[len(adx_values)//2] if adx_values else None
    vol_median = sorted(vol_values)[len(vol_values)//2] if vol_values else None
    
    # vol_days_under_08 无法从单日数据判定，默认 0
    vol_days_under_08 = 1 if (vol_median is not None and vol_median < 0.8) else 0
    
    # 尝试拉 CNN F&G（非阻塞）
    cnn = fetch_cnn_fear_greed()
    
    return classify_game_state(
        vix_value=vix_value,
        adx_median=adx_median,
        vol_median=vol_median,
        vol_days_under_08=vol_days_under_08,
        cnn_fear_greed=cnn.get("value")
    )


def format_game_state(state):
    """格式化博弈态输出（用于 Markdown 渲染）"""
    diag = state.get("diagnostics", {})
    cnn = diag.get("cnn_fear_greed")
    
    lines = [
        f"{state['label']}（效用{state['effect']:+d}）| 仓位硬上限: {state['cap']*100:.0f}%",
        f"├── VIX={diag.get('vix', '—')} | ADX中位数={diag.get('adx_median', '—')} | 量比中位数={diag.get('vol_median', '—')}",
    ]
    if cnn:
        lines.append(f"├── CNN F&G: {cnn}")
    if state.get("note"):
        lines.append(f"├── ⚠️ {state['note']}")
    if state.get("warning"):
        lines.append(f"├── ⚠️ {state['warning']}")
    lines.append(f"└── 判定路径: {diag.get('step', 'unknown')}")
    
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="博弈态判定")
    parser.add_argument("--vix", type=float, help="VIX值")
    parser.add_argument("--adx", type=float, help="ADX14中位数")
    parser.add_argument("--vol", type=float, help="成交量比值中位数")
    parser.add_argument("--vol-days", type=int, default=0, help="成交量<0.8持续天数")
    parser.add_argument("--bridged", type=str, help="bridged JSON 字符串")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    
    args = parser.parse_args()
    
    if args.bridged:
        bridged = json.loads(args.bridged)
        state = compute_from_bridged(bridged)
    elif args.vix is not None:
        state = classify_game_state(
            vix_value=args.vix,
            adx_median=args.adx,
            vol_median=args.vol,
            vol_days_under_08=args.vol_days
        )
    else:
        # 无输入 → 返回默认（多空绞杀 + 警告）
        state = classify_game_state(None, None, None)
    
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_game_state(state))


if __name__ == "__main__":
    main()
