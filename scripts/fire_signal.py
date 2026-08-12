#!/usr/bin/env python3
"""
fire_signal.py V1.0 — /开火 信号计算引擎（2026-07-07 焊入）
联邦投顾六类策略开火信号的确定性计算层

功能：
  反击策略：MA40−k×ATR买入区间，R0/R0.5/R1/R2四条件判定
  美股进攻：C4=H20×0.98买入区间，C1-C4四条件判定
  A股进攻(MA5)：牛市MA5回踩，逐标独立参数
  A股进攻(MA60)：牛市MA60回踩，MACD+缩量+容忍度
  固定层：MA60−k×ATR区间判定
  独立动量：MACD金叉+价<MA20
  金盾：四条件+战术前置

输入：scan_engine.py 输出的标准化JSON
输出：信号JSON — 每标的买入区间/触发状态/止损位/止盈位/冷却期

用法：
  python scripts/fire_signal.py indicators.json           # 从扫描JSON生成信号
  python scripts/scan_engine.py | python scripts/fire_signal.py --stdin  # 管道模式
  python scripts/fire_signal.py --test                   # 自测
"""

import json, sys, os, argparse
from datetime import datetime, date

# ── 加载配置文件 ──────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "fire_params.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def get_ind(ind_dict, key, field="value"):
    """安全获取指标值"""
    v = ind_dict.get(key, {})
    return v.get(field) if isinstance(v, dict) else None

def get_ind_dir(ind_dict, key):
    """安全获取MA方向"""
    return get_ind(ind_dict, key, "direction")

def pct_diff(a, b):
    """百分比差 (a相对于b)"""
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / b * 100, 2)


# ══════════════════════════════════════════════════════════════
# 六大策略计算函数
# ══════════════════════════════════════════════════════════════

def compute_counterpunch(sym, info, ind, params):
    """
    反击策略信号计算
    返回: {triggered, buy_zone_upper, buy_zone_lower, stop_loss, conditions, ...}
    """
    anchor_key = params["anchor"]  # MA40
    anchor_val = get_ind(ind, anchor_key)
    anchor_dir = get_ind_dir(ind, anchor_key)
    atr = get_ind(ind, "ATR14")
    price = info.get("price_realtime") or info.get("close_tushare")
    k = params["k"]
    
    if anchor_val is None or atr is None or price is None:
        return {"error": "指标缺失，无法计算", "anchor_val": anchor_val, "atr": atr, "price": price}
    
    buy_zone_upper = round(anchor_val - k * atr, 4)
    buy_zone_lower = round(buy_zone_upper - params["stop_atr"] * atr, 4)
    stop_loss = round(buy_zone_lower - params["stop_atr"] * atr, 4)
    gap_pct = pct_diff(price, buy_zone_upper)
    
    conditions = {}
    
    # R0: 现价 ≤ 买入区间上沿
    conditions["R0_price_in_zone"] = {
        "met": price <= buy_zone_upper,
        "value": f"现价{price} vs 区间上沿{buy_zone_upper}",
        "detail": {"price": price, "upper": buy_zone_upper, "gap_pct": gap_pct}
    }
    
    # R0.5: MA40方向过滤（部分标的豁免）
    if params.get("r05_exempt"):
        conditions["R0.5_anchor_direction"] = {
            "met": True, "value": "✅豁免", "detail": {"direction": anchor_dir, "exempt": True}
        }
    else:
        conditions["R0.5_anchor_direction"] = {
            "met": anchor_dir == "↑",
            "value": f"MA40方向={anchor_dir}",
            "detail": {"direction": anchor_dir, "exempt": False}
        }
    
    # R1: 缩量确认
    vol_ratio = get_ind(ind, "VOL_RATIO")
    vol_shrink_days = get_ind(ind, "VOL_SHRINK_DAYS")
    r1_met = vol_ratio is not None and vol_ratio < 1.0
    conditions["R1_volume_shrink"] = {
        "met": r1_met,
        "value": f"量比={vol_ratio}, 缩量天数={vol_shrink_days}",
        "detail": {"vol_ratio": vol_ratio, "shrink_days": vol_shrink_days}
    }
    
    # R2: 两层建仓触发
    conditions["R2_tiered_entry"] = {
        "met": price <= buy_zone_lower,
        "value": f"现价{price} vs 下沿{buy_zone_lower}",
        "detail": {"price": price, "lower": buy_zone_lower, "upper": buy_zone_upper}
    }
    
    all_met = conditions["R0_price_in_zone"]["met"] and conditions["R0.5_anchor_direction"]["met"]
    
    return {
        "strategy": "counterpunch",
        "anchor": {"key": anchor_key, "value": anchor_val, "direction": anchor_dir},
        "params": {"k": k, "stop_atr": params["stop_atr"]},
        "buy_zone": {"upper": buy_zone_upper, "lower": buy_zone_lower},
        "stop_loss": stop_loss,
        "hard_stop": params["hard_stop"],
        "gap_pct": gap_pct,
        "conditions": conditions,
        "triggered": all_met,
        "r2_triggered": conditions["R2_tiered_entry"]["met"],
        "entry_type": "正金字塔两层(30%+70%)" if conditions["R2_tiered_entry"]["met"] else "单层建仓(30%)",
        "cooldown_days": 0,  # 冷却期已废除 r33.68
        "force_exit_days": params["force_exit"]
    }


def compute_offense_us(sym, info, ind, params):
    """
    美股进攻策略信号计算 (QQQ/IVV/MUFG)
    C1: 现价 < MA60 / C2: VOL > MA20×1.2 / C3: 无宏观事件(LLM层判定) / C4: 现价 ≤ H20×0.98
    """
    ma60 = get_ind(ind, "MA60")
    h20 = get_ind(ind, "H20")
    vol_ratio = get_ind(ind, "VOL_RATIO")
    price = info.get("price_realtime") or info.get("close_tushare")
    c4_factor = params["c4_factor"]
    
    if ma60 is None or h20 is None or price is None:
        return {"error": "指标缺失"}
    
    c4 = round(h20 * c4_factor, 4)
    stop_loss = round(c4 - params["stop_atr"] * get_ind(ind, "ATR14"), 4) if get_ind(ind, "ATR14") else None
    gap_pct = pct_diff(price, c4)
    
    conditions = {}
    conditions["C1_below_MA60"] = {
        "met": price < ma60,
        "value": f"现价{price} vs MA60={ma60}",
        "detail": {"price": price, "ma60": ma60}
    }
    conditions["C2_volume_above_120"] = {
        "met": vol_ratio is not None and vol_ratio > 1.2,
        "value": f"量比={vol_ratio}",
        "detail": {"vol_ratio": vol_ratio}
    }
    conditions["C3_macro_clear"] = {
        "met": True,  # LLM层判定
        "value": "C3.1宏观事件检查→LLM层"
    }
    conditions["C4_price_at_H20x98"] = {
        "met": price <= c4,
        "value": f"现价{price} vs C4={c4}",
        "detail": {"price": price, "h20": h20, "c4": c4}
    }
    
    all_met = all(c["met"] for c in conditions.values())
    
    return {
        "strategy": "offense_us",
        "c4": c4,
        "h20": h20,
        "stop_loss": stop_loss,
        "gap_pct": gap_pct,
        "conditions": conditions,
        "triggered": all_met,
        "cooldown_disabled": True,
        "position_pct": params["position"]
    }


def compute_offense_cn_ma5(sym, info, ind, params):
    """
    A股进攻MA5回踩策略
    牛市判定: MA60↑ + 价>MA60
    入场: 前日收盘>MA5 + 当日最低触及MA5(±0.5%)
    """
    ma5 = get_ind(ind, "MA5")
    ma60 = get_ind(ind, "MA60")
    ma60_dir = get_ind_dir(ind, "MA60")
    atr = get_ind(ind, "ATR14")
    price = info.get("price_realtime") or info.get("close_tushare")
    
    if ma5 is None or ma60 is None or price is None:
        return {"error": "指标缺失"}
    
    # 牛市判定
    is_bull = (ma60_dir == "↑" and price > ma60)
    
    stop_loss = round(price - params["stop_atr"] * atr, 4) if atr else None
    
    # MA5回踩条件（简化：判断现价距MA5的偏离）
    gap_to_ma5 = pct_diff(price, ma5)
    near_ma5 = gap_to_ma5 is not None and abs(gap_to_ma5) <= 2.0  # ±2%视为接近回踩
    
    conditions = {}
    conditions["bull_market"] = {
        "met": is_bull,
        "value": f"MA60方向={ma60_dir}, 价vsMA60: {price}vs{ma60}",
        "detail": {"ma60_dir": ma60_dir, "price_above_ma60": price > ma60}
    }
    conditions["ma5_pullback"] = {
        "met": near_ma5,
        "value": f"距MA5={gap_to_ma5}%",
        "detail": {"ma5": ma5, "price": price, "gap_pct": gap_to_ma5}
    }
    
    triggered = is_bull and near_ma5
    
    return {
        "strategy": "offense_cn_ma5",
        "is_bull": is_bull,
        "ma5": ma5,
        "ma60": ma60,
        "ma60_dir": ma60_dir,
        "stop_loss": stop_loss,
        "take_profit": params["take_profit"],
        "gap_to_ma5": gap_to_ma5,
        "conditions": conditions,
        "triggered": triggered,
        "cooldown_disabled": True,
        "position_pct": params["position"]
    }


def compute_offense_cn_ma60(sym, info, ind, params):
    """
    A股进攻MA60回踩策略 (512100/510500)
    入场: MA向上 + 价回踩MA60±容忍度 + 近N日MACD金叉 + 缩量
    """
    ma = get_ind(ind, f"MA{params['ma']}")
    ma_dir = get_ind_dir(ind, f"MA{params['ma']}")
    atr = get_ind(ind, "ATR14")
    macd_bar = get_ind(ind, "MACD", "BAR")
    vol_ratio = get_ind(ind, "VOL_RATIO")
    price = info.get("price_realtime") or info.get("close_tushare")
    
    if ma is None or price is None:
        return {"error": "指标缺失"}
    
    gap_pct = pct_diff(price, ma)
    tolerance = params["tolerance"]
    within_tolerance = gap_pct is not None and abs(gap_pct) <= tolerance * 100
    
    # MACD金叉窗口（简化：BAR>0即可）
    macd_golden = macd_bar is not None and macd_bar > 0
    
    # 缩量
    vol_ok = vol_ratio is not None and vol_ratio < params["vol_threshold"]
    
    # 牛市判定
    is_bull = ma_dir == "↑"
    
    # 止损 = min(入场价+硬止损%, 入场价−ATR倍数×ATR)
    hard_stop_price = round(price * (1 + params["stop_pct"]), 4)
    atr_stop_price = round(price - params["stop_atr"] * atr, 4) if atr else None
    stop_loss = min(hard_stop_price, atr_stop_price) if atr_stop_price else hard_stop_price
    
    # 止盈 = 入场价+固定%
    take_profit_price = round(price * (1 + params["take_profit"]), 4)
    
    conditions = {}
    conditions["ma_direction"] = {
        "met": is_bull,
        "value": f"MA{params['ma']}方向={ma_dir}",
        "detail": {"ma_dir": ma_dir}
    }
    conditions["price_in_tolerance"] = {
        "met": within_tolerance,
        "value": f"距MA{params['ma']}={gap_pct}%, 容忍度±{tolerance*100}%",
        "detail": {"gap_pct": gap_pct, "tolerance": tolerance, "ma_val": ma}
    }
    conditions["macd_golden"] = {
        "met": macd_golden,
        "value": f"MACD BAR={macd_bar}",
        "detail": {"macd_bar": macd_bar}
    }
    conditions["volume_shrink"] = {
        "met": vol_ok,
        "value": f"量比={vol_ratio}, 阈值<{params['vol_threshold']}",
        "detail": {"vol_ratio": vol_ratio}
    }
    
    triggered = is_bull and within_tolerance and macd_golden and vol_ok
    
    return {
        "strategy": "offense_cn_ma60",
        "is_bull": is_bull,
        f"ma{params['ma']}": ma,
        "ma_dir": ma_dir,
        "stop_loss": stop_loss,
        "take_profit": take_profit_price,
        "max_hold": params["max_hold"],
        "gap_pct": gap_pct,
        "conditions": conditions,
        "triggered": triggered,
        "cooldown_disabled": True,
        "position_pct": params["position"]
    }


def compute_fixed_layer(sym, info, ind, params):
    """
    固定层信号计算 (VTI/VEA)
    买入区间: [MA60−k×ATR, MA60+2×ATR)
    """
    anchor_key = params["anchor"]
    anchor_val = get_ind(ind, anchor_key)
    atr = get_ind(ind, "ATR14")
    price = info.get("price_realtime") or info.get("close_tushare")
    
    if anchor_val is None or atr is None or price is None:
        return {"error": "指标缺失"}
    
    zone_lower = round(anchor_val - params["k_buy"] * atr, 4)
    zone_upper = round(anchor_val + params["k_upper"] * atr, 4)
    in_zone = zone_lower <= price < zone_upper
    gap_pct = pct_diff(price, zone_upper)
    
    stop_loss = round(zone_lower - 2.0 * atr, 4)
    
    return {
        "strategy": "fixed_layer",
        "anchor": {"key": anchor_key, "value": anchor_val},
        "buy_zone": {"lower": zone_lower, "upper": zone_upper},
        "in_zone": in_zone,
        "stop_loss": stop_loss,
        "gap_pct": gap_pct,
        "triggered": in_zone,
        "cooldown_disabled": True,
        "position_pct": params["position"]
    }


def _get_macd_bar(ind):
    """兼容大小写字段：MACD 结构可能是 {bar, bar_prev} 或 {BAR, cross}"""
    macd = ind.get("MACD", {})
    if not isinstance(macd, dict):
        return None, None
    bar = macd.get("bar", macd.get("BAR"))
    bar_prev = macd.get("bar_prev", macd.get("BAR_PREV", 0))
    return bar, bar_prev


def compute_momentum(sym, info, ind, params):
    """
    独立动量跟随策略 (FLIN/SMIN/EWY/VNM)
    入场: MACD金叉(BAR>0且前日BAR≤0) + 现价<MA20
    """
    ma20 = get_ind(ind, "MA20")
    macd_bar, macd_bar_prev = _get_macd_bar(ind)
    atr = get_ind(ind, "ATR14")
    price = info.get("price_realtime") or info.get("close_tushare")
    
    if ma20 is None or macd_bar is None or price is None:
        return {"error": "指标缺失"}
    
    # 金叉判定：BAR>0 且 前日BAR≤0（确定性计算，不依赖 cross 字段）
    macd_golden = macd_bar > 0 and (macd_bar_prev or 0) <= 0
    below_ma20 = price < ma20
    
    stop_loss = round(price - params["stop_atr"] * atr, 4) if atr else None
    gap_to_ma20 = pct_diff(price, ma20)
    
    conditions = {}
    conditions["MACD_golden_cross"] = {
        "met": macd_golden,
        "value": f"MACD BAR={macd_bar}, BAR_prev={macd_bar_prev}",
        "detail": {"macd_bar": macd_bar, "bar_prev": macd_bar_prev}
    }
    conditions["price_below_MA20"] = {
        "met": below_ma20,
        "value": f"现价{price} vs MA20={ma20}",
        "detail": {"price": price, "ma20": ma20, "gap_pct": gap_to_ma20}
    }
    
    triggered = macd_golden and below_ma20
    
    return {
        "strategy": "momentum",
        "stop_loss": stop_loss,
        "conditions": conditions,
        "triggered": triggered,
        "entry_phase": "待入场" if triggered else "等待MACD金叉+价<MA20",
        "cooldown_disabled": True,
        "position_pct": params["position"]
    }


def compute_golden_shield(sym, info, ind, params):
    """
    金盾策略信号计算 (IAU/518880)
    四条件: MA60↑ + MACD金叉 + RSI<70 + 波动率正常
    战术前置: DXY↓ + MACD金叉 + FOMC落地 → ⅓仓位
    """
    ma60_dir = get_ind_dir(ind, "MA60")
    macd_bar = get_ind(ind, "MACD", "BAR")
    macd_cross = get_ind(ind, "MACD", "cross")
    rsi = get_ind(ind, "RSI14")
    atr = get_ind(ind, "ATR14")
    price = info.get("price_realtime") or info.get("close_tushare")
    ema150 = get_ind(ind, "EMA150")
    
    if ma60_dir is None or rsi is None:
        return {"error": "指标缺失"}
    
    # 正统四条件
    conditions = {}
    conditions["C1_MA60_up"] = {
        "met": ma60_dir == "↑",
        "value": f"MA60方向={ma60_dir}"
    }
    conditions["C2_MACD_golden"] = {
        "met": macd_cross == "金叉🟢",
        "value": f"MACD={macd_cross}, BAR={macd_bar}"
    }
    conditions["C3_RSI_below_70"] = {
        "met": rsi < 70,
        "value": f"RSI14={rsi}"
    }
    # C4: 波动率正常 — 简化：ATR14/现价 < 3%
    vol_normal = (atr / price) < 0.03 if atr and price else True
    conditions["C4_vol_normal"] = {
        "met": vol_normal,
        "value": f"ATR/价格={round(atr/price*100,2)}%" if atr and price else "N/A"
    }
    
    orthodox_all = all(c["met"] for c in conditions.values())
    
    # 战术前置：DXY↓+MACD金叉+FOMC落地 → LLM层判定DXY和FOMC
    tactical_possible = conditions["C2_MACD_golden"]["met"]  # 仅判定C2，其余LLM层
    
    # EMA150约束
    ema150_deviation = pct_diff(price, ema150) if ema150 and price else None
    ema150_ok = ema150_deviation is not None and abs(ema150_deviation) <= 2.0
    
    return {
        "strategy": "golden_shield",
        "conditions": conditions,
        "orthodox_triggered": orthodox_all,
        "tactical_possible": tactical_possible,
        "ema150_deviation": ema150_deviation,
        "ema150_ok": ema150_ok,
        "triggered": orthodox_all or tactical_possible,
        "entry_type": "满仓" if orthodox_all else ("战术前置⅓仓" if tactical_possible else "等待")
    }


# ══════════════════════════════════════════════════════════════
# 主引擎
# ══════════════════════════════════════════════════════════════

STRATEGY_DISPATCH = {
    "counter":    ("counterpunch",      compute_counterpunch,      "反击"),
    "offense":    ("offense_us",         compute_offense_us,        "美股进攻"),
    "momentum":   ("momentum",           compute_momentum,          "独立动量"),
    "fixed":      ("fixed_layer",        compute_fixed_layer,       "固定层"),
    "goldshield": ("golden_shield",      compute_golden_shield,     "金盾"),
}


# ── 多路由标的映射（同一标的在多个策略中）──
DUAL_ROUTE_TICKERS = {
    "512100": ["counter", "offense_cn"],  # 反击 + A股进攻MA5/MA60
    "588000": ["counter", "offense_cn"],  # 反击 + A股进攻MA5
    "510500": ["counter", "offense_cn"],  # 反击 + A股进攻MA5/MA60
}


def compute_all_signals(indicators_json):
    """
    主函数：从scan_engine输出JSON计算全池信号
    """
    raw = json.loads(indicators_json) if isinstance(indicators_json, str) else indicators_json
    pool = raw.get("indicators", {})
    meta = raw.get("meta", {})
    game_state = raw.get("game_state", {})
    
    signals = {}
    
    for sym, info in pool.items():
        if "error" in info:
            signals[sym] = {"error": info["error"]}
            continue
        
        route = info.get("route", "")
        ind = info.get("indicators", {})
        
        # 多路由标的：生成多个策略信号
        if sym in DUAL_ROUTE_TICKERS:
            multi = {"strategies": {}}
            for r in DUAL_ROUTE_TICKERS[sym]:
                multi["strategies"][r] = _dispatch_route(sym, info, ind, r)
            multi["triggered"] = any(s.get("triggered") for s in multi["strategies"].values())
            signals[sym] = multi
            continue
        
        signals[sym] = _dispatch_route(sym, info, ind, route)
    
    return {
        "meta": {
            "version": "V1.0",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "engine": "fire_signal.py",
            "source_meta": meta
        },
        "game_state": game_state,
        "signals": signals,
        "summary": generate_summary(signals)
    }


def _dispatch_route(sym, info, ind, route):
    """根据路由分发到对应策略计算函数"""
    # ── 路由别名标准化（route_engine 输出 → fire_signal 内部名）──
    ROUTE_ALIAS = {
        "us_offensive":         "offense",
        "offensive_candidate":  "offense",
        "counterpunch":         "counter",
        "fixed_layer":          "fixed",
        "gold_shield":          "goldshield",
        "momentum":             "momentum",
        "offense_cn":           "offense_cn",
    }
    route = ROUTE_ALIAS.get(route, route)
    
    if route == "counter":
        params = CONFIG["counterpunch"].get(sym)
        if params:
            return compute_counterpunch(sym, info, ind, params)
        return {"error": f"反击参数未配置: {sym}"}
    
    elif route == "offense":
        market = info.get("market", "")
        if market == "us":
            params = CONFIG["offense_us"].get(sym)
            if params:
                return compute_offense_us(sym, info, ind, params)
            return {"error": f"美股进攻参数未配置: {sym}"}
        elif market == "cn":
            result_cn = {"strategy": "offense_cn_dual_track", "tracks": {}}
            params_ma5 = CONFIG["offense_cn_ma5"].get(sym)
            if params_ma5:
                result_cn["tracks"]["ma5"] = compute_offense_cn_ma5(sym, info, ind, params_ma5)
            params_ma50 = CONFIG.get("offense_cn_ma50", {}).get(sym)
            if params_ma50:
                result_cn["tracks"]["ma50"] = compute_offense_cn_ma60(sym, info, ind, params_ma50)
            result_cn["triggered"] = any(
                t.get("triggered") for t in result_cn["tracks"].values()
            )
            return result_cn
        return {"error": f"未知市场: {market}"}
    
    elif route == "momentum":
        params = CONFIG["momentum"].get(sym)
        if params:
            return compute_momentum(sym, info, ind, params)
        return {"error": f"动量参数未配置: {sym}"}
    
    elif route == "fixed":
        params = CONFIG["fixed_layer"].get(sym)
        if params:
            return compute_fixed_layer(sym, info, ind, params)
        return {"error": f"固定层参数未配置: {sym}"}
    
    elif route == "goldshield":
        return compute_golden_shield(sym, info, ind, CONFIG["golden_shield"])
    
    elif route == "offense_cn":
        # 多路由标的的A股进攻通道
        result_cn = {"strategy": "offense_cn_dual_track", "tracks": {}}
        params_ma5 = CONFIG["offense_cn_ma5"].get(sym)
        if params_ma5:
            result_cn["tracks"]["ma5"] = compute_offense_cn_ma5(sym, info, ind, params_ma5)
        params_ma50 = CONFIG.get("offense_cn_ma50", {}).get(sym)
        if params_ma50:
            result_cn["tracks"]["ma50"] = compute_offense_cn_ma60(sym, info, ind, params_ma50)
        result_cn["triggered"] = any(
            t.get("triggered") for t in result_cn["tracks"].values()
        )
        return result_cn
    
    elif route in ("independent", "idle", "unclassified"):
        # 不参与开火的标的（CANE独立标的/闲置/待分类）→ 返回占位结果，非错误
        return {
            "strategy": route,
            "triggered": False,
            "note": "不参与六类开火信号判定",
            "cooldown_disabled": True,
        }
    
    return {"error": f"未知路由: {route}"}


def generate_summary(signals):
    """生成信号摘要"""
    summary = {
        "counterpunch": [],
        "offense_us": [],
        "offense_cn_ma5": [],
        "offense_cn_ma60": [],
        "fixed_layer": [],
        "momentum": [],
        "golden_shield": [],
        "errors": []
    }
    
    for sym, sig in signals.items():
        if "error" in sig and "strategy" not in sig:
            summary["errors"].append({"symbol": sym, "error": sig["error"]})
            continue
        
        # 多路由标的（有 strategies 字段）
        if "strategies" in sig:
            for route, sub_sig in sig["strategies"].items():
                _summarize_one(summary, sym, sub_sig, route)
            continue
        
        _summarize_one(summary, sym, sig, sig.get("strategy", "unknown"))
    
    return summary


def _summarize_one(summary, sym, sig, strategy):
    """汇总单个策略信号到摘要"""
    triggered = sig.get("triggered", False)
    
    if strategy == "counterpunch":
        summary["counterpunch"].append({
            "symbol": sym, "triggered": triggered,
            "gap_pct": sig.get("gap_pct"),
            "buy_zone": sig.get("buy_zone", {}),
            "conditions": {k: v["met"] for k, v in sig.get("conditions", {}).items()}
        })
    elif strategy == "offense_us":
        summary["offense_us"].append({
            "symbol": sym, "triggered": triggered,
            "gap_pct": sig.get("gap_pct"),
            "c4": sig.get("c4"),
            "conditions": {k: v["met"] for k, v in sig.get("conditions", {}).items()}
        })
    elif strategy == "offense_cn_dual_track":
        for track_name, track in sig.get("tracks", {}).items():
            key = f"offense_cn_{track_name}"
            if key in summary:
                summary[key].append({
                    "symbol": sym, "triggered": track.get("triggered", False),
                    "gap_pct": track.get("gap_pct"),
                    "conditions": {k: v["met"] for k, v in track.get("conditions", {}).items()}
                })
    elif strategy == "fixed_layer":
        summary["fixed_layer"].append({
            "symbol": sym, "triggered": triggered,
            "in_zone": sig.get("in_zone"),
            "buy_zone": sig.get("buy_zone", {})
        })
    elif strategy == "momentum":
        summary["momentum"].append({
            "symbol": sym, "triggered": triggered,
            "conditions": {k: v["met"] for k, v in sig.get("conditions", {}).items()}
        })
    elif strategy == "golden_shield":
        summary["golden_shield"].append({
            "symbol": sym,
            "orthodox_triggered": sig.get("orthodox_triggered"),
            "tactical_possible": sig.get("tactical_possible"),
            "ema150_ok": sig.get("ema150_ok"),
            "conditions": {k: v["met"] for k, v in sig.get("conditions", {}).items()}
        })
    
    return summary


def main():
    parser = argparse.ArgumentParser(description="/开火 信号计算引擎 V1.0")
    parser.add_argument("input_file", nargs="?", help="scan_engine输出的JSON文件路径")
    parser.add_argument("--stdin", action="store_true", help="从stdin读取JSON")
    parser.add_argument("--test", action="store_true", help="自测模式")
    parser.add_argument("--summary", action="store_true", help="仅输出摘要")
    args = parser.parse_args()
    
    if args.test:
        run_self_test()
        return
    
    if args.stdin:
        raw = sys.stdin.read()
    elif args.input_file:
        with open(args.input_file) as f:
            raw = f.read()
    else:
        print("错误: 请提供输入文件或使用 --stdin", file=sys.stderr)
        sys.exit(1)
    
    result = compute_all_signals(raw)
    
    if args.summary:
        print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def run_self_test():
    """自测：用模拟数据验证各策略计算逻辑"""
    print("=" * 60)
    print("  fire_signal.py V1.0 自测")
    print("=" * 60)
    
    # 模拟一个反击标的
    mock_indicators = {
        "meta": {"version": "V1.0", "scope": "all"},
        "game_state": {"adx_median": 22.5, "vol_ratio_median": 0.85},
        "indicators": {
            "513910": {
                "symbol": "513910",
                "market": "cn",
                "route": "counter",
                "price_realtime": 1.555,
                "indicators": {
                    "MA40": {"value": 1.611, "direction": "↑", "freshness": "2026-07-07"},
                    "ATR14": {"value": 0.0191, "freshness": "2026-07-07"},
                    "VOL_RATIO": {"value": 0.72},
                    "VOL_SHRINK_DAYS": {"value": 3},
                }
            },
            "QQQ": {
                "symbol": "QQQ",
                "market": "us",
                "route": "offense",
                "price_realtime": 580.50,
                "indicators": {
                    "MA60": {"value": 590.00, "freshness": "2026-07-07"},
                    "H20": {"value": 610.00, "freshness": "2026-07-07"},
                    "ATR14": {"value": 8.50, "freshness": "2026-07-07"},
                    "VOL_RATIO": {"value": 1.35},
                }
            },
            "FLIN": {
                "symbol": "FLIN",
                "market": "us",
                "route": "momentum",
                "price_realtime": 28.50,
                "indicators": {
                    "MA20": {"value": 29.00, "freshness": "2026-07-07"},
                    "MACD": {"BAR": 0.05, "cross": "金叉🟢", "freshness": "2026-07-07"},
                    "ATR14": {"value": 0.45, "freshness": "2026-07-07"},
                }
            }
        }
    }
    
    result = compute_all_signals(mock_indicators)
    
    # 验证反击
    sig_513910 = result["signals"]["513910"]
    print(f"\n📊 513910 反击策略:")
    print(f"  买入区间: {sig_513910.get('buy_zone')}")
    print(f"  触发: {sig_513910.get('triggered')}")
    print(f"  条件: {json.dumps({k: v['met'] for k, v in sig_513910.get('conditions', {}).items()}, indent=2)}")
    assert sig_513910["triggered"] == True, f"513910应该触发! 实际: {sig_513910['triggered']}"
    print("  ✅ 通过")
    
    # 验证美股进攻
    sig_qqq = result["signals"]["QQQ"]
    print(f"\n📊 QQQ 美股进攻:")
    print(f"  C4: {sig_qqq.get('c4')}")
    print(f"  触发: {sig_qqq.get('triggered')}")
    print(f"  条件: {json.dumps({k: v['met'] for k, v in sig_qqq.get('conditions', {}).items()}, indent=2)}")
    assert sig_qqq["triggered"] == True, f"QQQ应该触发! 实际: {sig_qqq['triggered']}"
    print("  ✅ 通过")
    
    # 验证动量
    sig_flin = result["signals"]["FLIN"]
    print(f"\n📊 FLIN 动量:")
    print(f"  触发: {sig_flin.get('triggered')}")
    print(f"  条件: {json.dumps({k: v['met'] for k, v in sig_flin.get('conditions', {}).items()}, indent=2)}")
    assert sig_flin["triggered"] == True, f"FLIN应该触发! 实际: {sig_flin['triggered']}"
    print("  ✅ 通过")
    
    print(f"\n📋 摘要:")
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    
    print(f"\n{'='*60}")
    print("  自测全部通过 ✅")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
