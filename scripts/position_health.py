#!/usr/bin/env python3
"""
持仓健康度诊断引擎 V1.0
四维逐标诊断：止损距离 / 均线结构 / 动量指标 / 仓位集中度
输出：健康度🟢🟡🔴 + 操作建议
"""

import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
import tushare as ts

pro = ts.pro_api()

SCRIPTS_DIR = Path(__file__).parent
POSITIONS_FILE = SCRIPTS_DIR / "positions.json"
PARAMS_FILE = SCRIPTS_DIR / "params.json"

# ─── 策略参数（与 stop_loss_engine.py 共用） ───
from stop_loss_engine import (
    load_positions, normalize_ticker, get_ticker_type,
    SPEARHEAD_STOP_PARAMS, COUNTER_STOP_PARAMS, A_OFFENSIVE_STOP_PARAMS,
    MOMENTUM_STOP_PARAMS, GOLD_SHIELD_STOP_PARAMS, CANE_STOP_PARAMS,
    FIXED_LAYER, get_tushare_daily
)


def calc_full_indicators(df):
    """完整技术指标计算"""
    if df is None or len(df) < 60:
        return None
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    vol = df['vol'].values
    n = len(close)
    
    # ATR14
    tr = np.maximum(high[1:] - low[1:],
                    np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:] - close[:-1]))
    atr14 = np.mean(tr[-14:])
    
    # MA
    mas = {}
    for period in [5, 20, 40, 60, 120]:
        if n >= period:
            mas[f"MA{period}"] = np.mean(close[-period:])
    
    # EMA
    emas = {}
    for period in [12, 26, 50, 150]:
        if n >= period:
            emas[f"EMA{period}"] = pd.Series(close).ewm(span=period, adjust=False).mean().iloc[-1]
    
    # MACD
    if n >= 26:
        ema12 = pd.Series(close).ewm(span=12, adjust=False).mean()
        ema26 = pd.Series(close).ewm(span=26, adjust=False).mean()
        diff = ema12 - ema26
        dea = diff.ewm(span=9, adjust=False).mean()
        macd_bar = 2 * (diff - dea)
        macd_bar_now = macd_bar.iloc[-1]
        macd_bar_prev = macd_bar.iloc[-2]
        diff_now = diff.iloc[-1]
        dea_now = dea.iloc[-1]
        
        is_golden = macd_bar_now > 0 and macd_bar_prev <= 0
        is_dead = macd_bar_now < 0 and macd_bar_prev >= 0
    else:
        macd_bar_now = 0
        is_golden = False
        is_dead = False
        diff_now = 0
        dea_now = 0
    
    # RSI14
    if n >= 15:
        delta = np.diff(close)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = np.mean(gain[-14:])
        avg_loss = np.mean(loss[-14:])
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi14 = 100 - 100 / (1 + rs)
        else:
            rsi14 = 100
    else:
        rsi14 = 50
    
    # MA60方向
    if n >= 80:
        ma60_20d_ago = np.mean(close[-80:-60])
        ma60_now = np.mean(close[-60:])
        ma60_dir = "↑" if ma60_now > ma60_20d_ago else "↓"
    else:
        ma60_dir = "?"
    
    # 均线排列
    ma_values = [mas.get(f"MA{p}") for p in [5, 20, 60, 120] if f"MA{p}" in mas]
    if len(ma_values) >= 3:
        is_bull_alignment = all(ma_values[i] > ma_values[i+1] for i in range(len(ma_values)-1))
        is_bear_alignment = all(ma_values[i] < ma_values[i+1] for i in range(len(ma_values)-1))
    else:
        is_bull_alignment = False
        is_bear_alignment = False
    
    # VOL_MA20
    vol_ma20 = np.mean(vol[-20:]) if n >= 20 else vol[-1]
    vol_ratio = vol[-1] / vol_ma20 if vol_ma20 > 0 else 1.0
    
    # 20日回撤
    if n >= 21:
        drawdown_20d = (close[-1] / close[-21] - 1)
    else:
        drawdown_20d = 0
    
    return {
        "close": close[-1],
        "atr14": atr14,
        "mas": mas,
        "emas": emas,
        "ma60_dir": ma60_dir,
        "is_bull_alignment": is_bull_alignment,
        "is_bear_alignment": is_bear_alignment,
        "macd_bar": macd_bar_now,
        "macd_diff": diff_now,
        "macd_dea": dea_now,
        "is_golden": is_golden,
        "is_dead": is_dead,
        "rsi14": rsi14,
        "vol_ratio": vol_ratio,
        "drawdown_20d": drawdown_20d,
        "latest_date": df['trade_date'].iloc[-1],
    }


def diagnose_stop_distance(cost, price, stop_price_raw, atr14):
    """维度一：止损距离"""
    if stop_price_raw is None or not isinstance(stop_price_raw, (int, float)):
        return {"level": "?", "detail": "无止损位"}
    
    atr_to_stop = (price - stop_price_raw) / atr14 if atr14 > 0 else 0
    pct_to_stop = (price - stop_price_raw) / price * 100
    
    if atr_to_stop < 1:
        return {"level": "🔴", "detail": f"距止损{atr_to_stop:.1f}×ATR，危险"}
    elif atr_to_stop < 2:
        return {"level": "🟡", "detail": f"距止损{atr_to_stop:.1f}×ATR，接近"}
    else:
        return {"level": "🟢", "detail": f"距止损{atr_to_stop:.1f}×ATR，安全"}


def diagnose_ma_structure(price, ind):
    """维度二：均线结构"""
    ma60 = ind["mas"].get("MA60", 0)
    ma20 = ind["mas"].get("MA20", 0)
    ma60_dir = ind["ma60_dir"]
    
    issues = []
    score = "🟢"
    
    if ma60_dir == "↓":
        issues.append("MA60方向↓")
        score = "🔴"
    elif ma60_dir == "?":
        score = "🟡"
        issues.append("MA60方向不明")
    
    if ma60 > 0 and price < ma60:
        issues.append(f"价<MA60({ma60:.2f})")
        if score != "🔴":
            score = "🟡"
    
    if ma20 > 0 and price < ma20:
        issues.append(f"价<MA20({ma20:.2f})")
    
    if ind["is_bull_alignment"]:
        if score == "🟢":
            detail = "多头排列✅"
        else:
            detail = f"多头排列但{'; '.join(issues)}"
    elif ind["is_bear_alignment"]:
        score = "🔴"
        detail = f"空头排列{' + ' + '; '.join(issues) if issues else ''}"
    else:
        detail = f"均线交织{' + ' + '; '.join(issues) if issues else '✅'}"
    
    return {"level": score, "detail": detail}


def diagnose_momentum(ind):
    """维度三：动量指标"""
    macd_bar = ind["macd_bar"]
    is_golden = ind["is_golden"]
    is_dead = ind["is_dead"]
    rsi = ind["rsi14"]
    
    if is_golden:
        return {"level": "🟢", "detail": f"MACD金叉(BAR={macd_bar:.4f})，动量恢复"}
    elif is_dead:
        return {"level": "🔴", "detail": f"MACD死叉(BAR={macd_bar:.4f})，动量恶化"}
    elif macd_bar > 0:
        return {"level": "🟢", "detail": f"MACD BAR>0({macd_bar:.4f})，动能偏多"}
    elif macd_bar < 0:
        return {"level": "🟡", "detail": f"MACD BAR<0({macd_bar:.4f})，动能偏空"}
    else:
        return {"level": "🟡", "detail": "MACD零轴附近，方向不明"}


def diagnose_concentration(ticker, market_value, total_asset):
    """维度四：仓位集中度"""
    if total_asset <= 0:
        return {"level": "?", "detail": "总资产未知"}
    
    pct = market_value / total_asset * 100
    if pct > 20:
        return {"level": "🔴", "detail": f"占比{pct:.1f}%>20%，过高"}
    elif pct > 15:
        return {"level": "🟡", "detail": f"占比{pct:.1f}%，偏高"}
    else:
        return {"level": "🟢", "detail": f"占比{pct:.1f}%，正常"}


def compute_total_assets(positions, data):
    """计算各账户总资产"""
    totals = {}
    
    # 先读取账户级别的现金
    accounts = data.get("accounts", {})
    for acct, acct_data in accounts.items():
        if isinstance(acct_data, dict):
            totals[acct] = {
                "market_value": 0,
                "cash": acct_data.get("cash_approx", acct_data.get("cash", 0)),
            }
    
    for ticker, pos in positions.items():
        acct = pos.get("account", "B")
        if acct not in totals:
            totals[acct] = {"market_value": 0, "cash": 0}
        
        price = pos.get("_price", 0)  # 由外部注入
        shares = pos.get("shares", 0)
        if price and shares:
            totals[acct]["market_value"] += price * shares
    
    for acct in totals:
        totals[acct]["total"] = totals[acct]["market_value"] + totals[acct].get("cash", 0)
    
    return totals


def diagnose_position(ticker, pos, price, ind, total_asset):
    """单标全面诊断"""
    cost = pos.get("cost")
    shares = pos.get("shares", 0)
    market_value = price * shares if price and shares else 0
    pnl = (price - cost) * shares if cost and price and shares else 0
    pnl_pct = (price - cost) / cost * 100 if cost and cost > 0 else 0
    
    ticker_type = get_ticker_type(ticker)
    
    atr14 = ind["atr14"] if ind else 0
    
    # 维度1: 止损距离
    if ticker_type in FIXED_LAYER:
        stop_diag = {"level": "🟢", "detail": "固定层永不离场"}
        stop_price_raw = None
    elif ticker_type == "spearhead" and cost and ind:
        params = SPEARHEAD_STOP_PARAMS[ticker]
        stop_price_raw = cost - params["stop_mult"] * atr14
    elif ticker_type == "counter" and cost and ind:
        params = COUNTER_STOP_PARAMS[ticker]
        ma40 = ind["mas"].get("MA40", price)
        entry_zone = ma40 - params["k"] * atr14
        stop_price_raw = entry_zone - params["stop_mult"] * atr14
    elif ticker_type == "momentum" and cost and ind:
        params = MOMENTUM_STOP_PARAMS[ticker]
        stop_price_raw = cost - params["stop_atr"] * atr14
    elif ticker_type == "gold":
        if cost:
            stop_price_raw = cost * (1 + GOLD_SHIELD_STOP_PARAMS[ticker]["S6"])
        else:
            stop_price_raw = price * 0.87
    elif ticker_type == "cane" and cost:
        stop_price_raw = cost * (1 + CANE_STOP_PARAMS["S6"])
    else:
        stop_price_raw = None
    
    stop_diag = diagnose_stop_distance(cost, price, stop_price_raw, atr14) if stop_price_raw and atr14 > 0 else {"level": "?", "detail": "无法计算"}
    
    # 维度2-3（仅当有指标数据时）
    if ind:
        ma_diag = diagnose_ma_structure(price, ind)
        mom_diag = diagnose_momentum(ind)
    else:
        ma_diag = {"level": "?", "detail": "数据缺失"}
        mom_diag = {"level": "?", "detail": "数据缺失"}
    
    # 维度4
    conc_diag = diagnose_concentration(ticker, market_value, total_asset)
    
    # 综合健康度
    levels = [stop_diag["level"], ma_diag["level"], mom_diag["level"], conc_diag["level"]]
    if "🔴" in levels:
        health = "🔴 危险"
    elif levels.count("🟡") >= 2 or "🔴" in levels:
        health = "🟡 观察"
    elif "🟡" in levels:
        health = "🟡 观察"
    else:
        health = "🟢 健康"
    
    # 操作建议
    suggestions = []
    if stop_diag["level"] == "🔴":
        suggestions.append("⚠️ 距止损<1×ATR，准备执行止损")
    if ma_diag["level"] == "🔴":
        suggestions.append("均线空头排列，不加仓")
    if mom_diag["level"] == "🔴":
        suggestions.append("MACD死叉，警惕进一步下跌")
    if conc_diag["level"] == "🔴":
        suggestions.append("仓位集中度过高，考虑减仓")
    if pnl_pct > 20:
        suggestions.append(f"浮盈{pnl_pct:.0f}%，关注止盈条件")
    
    return {
        "ticker": ticker,
        "type": ticker_type,
        "account": pos.get("account", "?"),
        "shares": shares,
        "cost": cost,
        "price": price,
        "market_value": market_value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "health": health,
        "diagnoses": {
            "止损距离": stop_diag,
            "均线结构": ma_diag,
            "动量指标": mom_diag,
            "仓位集中度": conc_diag,
        },
        "suggestions": suggestions,
    }


def format_output(all_diagnoses, totals):
    """格式化输出"""
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  🏥 联邦持仓健康度诊断")
    lines.append(f"{'='*70}")
    
    # 逐标的
    for acct in ["A", "B"]:
        acct_diags = [d for d in all_diagnoses if d["account"] == acct]
        if not acct_diags:
            continue
        
        lines.append(f"\n{'─'*70}")
        lines.append(f"  {acct}账户")
        lines.append(f"{'─'*70}")
        
        # 表头
        lines.append(f"  {'标的':<10} {'持仓':>8} {'成本':>10} {'现价':>10} {'市值':>12} {'浮盈':>12} {'健康度':<10}")
        lines.append(f"  {'─'*70}")
        
        total_mv = 0
        total_pnl = 0
        for d in acct_diags:
            lines.append(f"  {d['ticker']:<10} {d['shares']:>8} {d['cost']:>10.3f} {d['price']:>10.3f} {d['market_value']:>12,.0f} {d['pnl']:>12,.0f} {d['health']:<10}")
            total_mv += d["market_value"]
            total_pnl += d["pnl"]
        
        if acct in totals:
            t = totals[acct]
            lines.append(f"  {'─'*70}")
            lines.append(f"  合计: 市值{t['market_value']:,.0f} | 现金{t.get('cash',0):,.0f} | 总资产{t['total']:,.0f} | 浮盈{total_pnl:,.0f}")
    
    # 诊断详情
    lines.append(f"\n{'='*70}")
    lines.append(f"  逐标诊断详情")
    lines.append(f"{'='*70}")
    
    for d in all_diagnoses:
        lines.append(f"\n  📌 {d['ticker']} ({d['type']}) — {d['health']}")
        for dim, diag in d["diagnoses"].items():
            lines.append(f"    {dim}: {diag['level']} {diag['detail']}")
        if d["suggestions"]:
            for s in d["suggestions"]:
                lines.append(f"    → {s}")
    
    # 操作汇总
    lines.append(f"\n{'='*70}")
    lines.append(f"  操作建议汇总")
    lines.append(f"{'='*70}")
    
    danger = [d for d in all_diagnoses if "🔴" in d["health"]]
    watch = [d for d in all_diagnoses if "🟡" in d["health"]]
    healthy = [d for d in all_diagnoses if "🟢" in d["health"]]
    
    if danger:
        lines.append(f"\n  🔴 危险（需立即关注）:")
        for d in danger:
            lines.append(f"    {d['ticker']}: {'; '.join(d['suggestions'])}")
    
    if watch:
        lines.append(f"\n  🟡 观察（接近边界）:")
        for d in watch:
            lines.append(f"    {d['ticker']}: {'; '.join(d['suggestions']) if d['suggestions'] else '暂无明确建议'}")
    
    if healthy:
        lines.append(f"\n  🟢 健康（无需操作）:")
        lines.append(f"    {', '.join(d['ticker'] for d in healthy)}")
    
    lines.append(f"\n{'='*70}\n")
    
    return "\n".join(lines)


def main():
    with open(POSITIONS_FILE, 'r') as f:
        raw_data = json.load(f)
    
    positions = load_positions()
    if not positions:
        print("❌ 无法加载持仓数据")
        sys.exit(1)
    
    # 获取所有持仓标的的行情
    all_diagnoses = []
    
    for ticker, pos in positions.items():
        ticker_type = get_ticker_type(ticker)
        if ticker_type == "unknown":
            continue
        
        ts_ticker, is_a = normalize_ticker(ticker, ticker_type)
        df = get_tushare_daily(ts_ticker, is_a)
        ind = calc_full_indicators(df)
        
        # 注入行情数据到pos
        if ind:
            pos["_price"] = ind["close"]
        else:
            pos["_price"] = pos.get("cost", 0)
    
    totals = compute_total_assets(positions, raw_data)
    
    for ticker, pos in positions.items():
        ticker_type = get_ticker_type(ticker)
        if ticker_type == "unknown":
            continue
        
        price = pos.get("_price", pos.get("cost", 0))
        
        ts_ticker, is_a = normalize_ticker(ticker, ticker_type)
        df = get_tushare_daily(ts_ticker, is_a)
        ind = calc_full_indicators(df)
        
        acct = pos.get("account", "B")
        total_asset = totals.get(acct, {}).get("total", 100000)
        
        diag = diagnose_position(ticker, pos, price, ind, total_asset)
        all_diagnoses.append(diag)
    
    # 按健康度排序
    all_diagnoses.sort(key=lambda d: (0 if "🔴" in d["health"] else 1 if "🟡" in d["health"] else 2))
    
    print(format_output(all_diagnoses, totals))


if __name__ == "__main__":
    main()
