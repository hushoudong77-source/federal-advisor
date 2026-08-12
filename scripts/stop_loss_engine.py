#!/usr/bin/env python3
"""
止损/止盈计算引擎 V1.0
输入标的代码 → 输出完整止损止盈状态
覆盖：美股进攻/反击/A股进攻/固定层/金盾/独立动量/CANE
"""

import json
import sys
import os
from datetime import datetime, date, timedelta
from pathlib import Path
import pandas as pd
import numpy as np

# Tushare
import tushare as ts
pro = ts.pro_api()

# ─── 路径 ───
SCRIPTS_DIR = Path(__file__).parent
WORKSPACE = SCRIPTS_DIR.parent
POSITIONS_FILE = SCRIPTS_DIR / "positions.json"
PARAMS_FILE = SCRIPTS_DIR / "params.json"
DECISION_LOG_DIR = WORKSPACE / "knowledge" / "analysis" / "decision-log"

# ─── 参数矩阵 ───
# 反击止损：买入区间下沿 − stop_mult × ATR14
COUNTER_STOP_PARAMS = {
    "513910": {"k": 2.7, "stop_mult": 3.5, "anchor": "MA40"},
    "512100": {"k": 2.0, "stop_mult": 3.0, "anchor": "MA40"},
    "510500": {"k": 2.5, "stop_mult": 2.5, "anchor": "MA40", "bear_pause": True},
    "510880": {"k": 2.0, "stop_mult": 3.0, "anchor": "MA40", "tp_fixed": 0.10},
    "159530": {"k": 1.5, "stop_mult": 4.0, "anchor": "MA40"},
    "588000": {"k": 4.7, "stop_mult": 3.0, "anchor": "MA40"},
    "BBJP": {"k": 4.3, "stop_mult": 2.0, "anchor": "MA40"},
    "VNM": {"k": 5.0, "stop_mult": 1.5, "anchor": "MA40"},
    "510300": {"k": 2.0, "stop_mult": 4.0, "anchor": "MA40"},
    "159915": {"k": 2.0, "stop_mult": 4.0, "anchor": "MA40"},
}

# 美股进攻止损：入场价 − stop_mult × ATR14
SPEARHEAD_STOP_PARAMS = {
    "QQQ": {"stop_mult": 8.0, "stop_type": "dynamic_drawdown", "activation": 0.20, "drawdown_atr": 2.5},
    "IVV": {"stop_mult": 2.0, "stop_type": "none"},
    "MUFG": {"stop_mult": 7.0, "stop_type": "fixed_tp", "tp_pct": 0.50},
    "BOTZ": {"stop_mult": 2.0, "stop_type": "none"},
}

# A股进攻止损：min(入场价−fixed%, 入场价−atr×ATR)
A_OFFENSIVE_STOP_PARAMS = {
    "512100": {"fixed_pct": 0.05, "atr_mult": 2.0, "tp_type": "fixed", "tp_pct": 0.20},
    "513180": {"fixed_pct": 0.08, "atr_mult": 2.0, "tp_type": "MA20"},
    "588000": {"fixed_pct": 0.04, "atr_mult": 4.0, "tp_type": "batched",
               "tp_batches": [0.20, 0.35, 0.50], "tp_weights": [0.30, 0.30, 0.40]},
    "510500": {"fixed_pct": 0.13, "atr_mult": 2.0, "tp_type": "batched",
               "tp_batches": [0.15, 0.25], "tp_weights": [0.50, 0.50]},
}

# 独立动量止损
MOMENTUM_STOP_PARAMS = {
    "FLIN": {"stop_atr": 5.5, "activation_atr": 1.5, "drawdown_atr": 1.5},
    "SMIN": {"stop_atr": 9.0, "activation_atr": 1.5, "drawdown_atr": 1.5,
             "track2_threshold": -0.15, "track2_stop_pct": -0.15, "track2_drawdown_atr": 3.5},
    "EWY": {"stop_atr": 10.0, "activation_atr": 1.5, "drawdown_atr": 1.5,
            "track2_threshold": -0.20, "track2_stop_pct": -0.15, "track2_drawdown_atr": 3.5},
    "VNM": {"stop_atr": 1.5, "activation_atr": 1.5, "drawdown_atr": 1.5,
            "track2_threshold": -0.20, "track2_stop_pct": -0.15, "track2_drawdown_atr": 3.5},
}

# 金盾止损
GOLD_SHIELD_STOP_PARAMS = {
    "IAU": {"S6": -0.13, "S7": -0.19, "S4": "MA60"},
    "518880": {"S6": -0.13, "S7": -0.19, "S4": "MA60"},
}

# CANE止损
CANE_STOP_PARAMS = {"S6": -0.13, "S7": -0.19, "hard_stop": -0.25}

# 固定层：永不离场
FIXED_LAYER = {"VTI", "VEA"}


def load_positions():
    """加载持仓数据 — 展平 accounts 结构"""
    try:
        with open(POSITIONS_FILE, 'r') as f:
            data = json.load(f)
        
        # 展平嵌套结构: {"accounts": {"B": {"holdings": {"MUFG": {...}}}}}
        positions = {}
        accounts = data.get("accounts", {})
        for account_name, account_data in accounts.items():
            if not isinstance(account_data, dict):
                continue
            holdings = account_data.get("holdings", account_data)  # 兼容直接或嵌套
            if isinstance(holdings, dict):
                for ticker, pos_data in holdings.items():
                    if isinstance(pos_data, dict):
                        positions[ticker] = {
                            **pos_data,
                            "account": account_name,
                        }
        return positions
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_tushare_daily(ticker, is_a_share=False):
    """获取日线数据"""
    start_date = (datetime.now() - timedelta(days=400)).strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')
    
    try:
        if is_a_share:
            df = pro.fund_daily(ts_code=ticker, start_date=start_date, end_date=end_date)
        else:
            ts_code = ticker if '.' in ticker else ticker
            df = pro.us_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        
        if df is not None and len(df) > 0:
            df = df.sort_values('trade_date').reset_index(drop=True)
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['vol'] = df['vol'].astype(float)
            return df
        return None
    except Exception as e:
        print(f"  ⚠️ Tushare拉取失败: {e}", file=sys.stderr)
        return None


def calc_indicators(df):
    """计算技术指标"""
    if df is None or len(df) < 60:
        return {}
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    vol = df['vol'].values
    
    # ATR14
    tr = np.maximum(high[1:] - low[1:], 
                    np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:] - close[:-1]))
    atr14 = np.mean(tr[-14:]) if len(tr) >= 14 else np.mean(tr)
    
    # MA/EMA
    ma20 = np.mean(close[-20:]) if len(close) >= 20 else close[-1]
    ma40 = np.mean(close[-40:]) if len(close) >= 40 else close[-1]
    ma60 = np.mean(close[-60:]) if len(close) >= 60 else close[-1]
    
    # MA60方向（20日斜率）
    if len(close) >= 80:
        ma60_20d_ago = np.mean(close[-80:-60])
        ma60_dir = "↑" if ma60 > ma60_20d_ago else "↓"
    else:
        ma60_dir = "?"
    
    # H20
    h20 = np.max(high[-20:]) if len(high) >= 20 else high[-1]
    
    # VOL_MA20
    vol_ma20 = np.mean(vol[-20:]) if len(vol) >= 20 else vol[-1]
    
    # 20日回撤
    if len(close) >= 20:
        drawdown_20d = (close[-1] / close[-21] - 1) if close[-21] > 0 else 0
    else:
        drawdown_20d = 0
    
    return {
        "close": close[-1],
        "atr14": atr14,
        "ma20": ma20,
        "ma40": ma40,
        "ma60": ma60,
        "ma60_dir": ma60_dir,
        "h20": h20,
        "vol_ma20": vol_ma20,
        "drawdown_20d": drawdown_20d,
        "latest_date": df['trade_date'].iloc[-1],
        "n_rows": len(df),
    }


def get_ticker_type(ticker):
    """判定标的类型"""
    if ticker in FIXED_LAYER:
        return "fixed"
    if ticker in SPEARHEAD_STOP_PARAMS:
        return "spearhead"
    if ticker in COUNTER_STOP_PARAMS:
        return "counter"
    if ticker in A_OFFENSIVE_STOP_PARAMS:
        return "a_offensive"
    if ticker in MOMENTUM_STOP_PARAMS:
        return "momentum"
    if ticker in GOLD_SHIELD_STOP_PARAMS:
        return "gold"
    if ticker == "CANE":
        return "cane"
    return "unknown"


def normalize_ticker(ticker, ticker_type):
    """A股代码添加后缀"""
    is_a = ticker_type in ("counter", "a_offensive", "gold")
    if is_a and not ticker.endswith((".SH", ".SZ")):
        # 根据代码判断：5/6开头→SH，0/1/3开头→SZ
        if ticker.startswith(("5", "6")):
            return f"{ticker}.SH", True
        else:
            return f"{ticker}.SZ", True
    elif ticker.endswith((".SH", ".SZ")):
        return ticker, True
    return ticker, False


def get_market_data(ticker, ticker_type):
    """获取行情数据 + 技术指标"""
    ts_ticker, is_a = normalize_ticker(ticker, ticker_type)
    df = get_tushare_daily(ts_ticker, is_a)
    indicators = calc_indicators(df)
    return indicators


def check_add_heat(ticker, ticker_type):
    """检查加仓过热状态（30天内≥3次加仓）"""
    cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
    count = 0
    
    # 读决策日志
    current_month = datetime.now().strftime('%Y-%m')
    log_file = DECISION_LOG_DIR / f"{current_month}.md"
    
    if log_file.exists():
        with open(log_file, 'r') as f:
            content = f.read()
        # 简单关键词匹配（实际应更精确解析）
        lines = content.split('\n')
        for line in lines:
            if ticker in line and ('买入' in line or '加仓' in line):
                count += 1
    
    return count >= 3


def compute_stop_loss(ticker, indicators):
    """核心：计算止损止盈"""
    if not indicators:
        return {"error": "无法获取行情数据"}
    
    ticker_type = get_ticker_type(ticker)
    positions = load_positions()
    current_price = indicators["close"]
    atr14 = indicators["atr14"]
    
    result = {
        "ticker": ticker,
        "type": ticker_type,
        "price": round(current_price, 4),
        "atr14": round(atr14, 4),
        "latest_date": indicators["latest_date"],
        "has_position": ticker in positions,
    }
    
    # ─── 固定层 ───
    if ticker_type == "fixed":
        result["stop_loss"] = None
        result["stop_price"] = None
        result["tp"] = None
        result["tp_price"] = None
        result["status"] = "🟢 永不离场"
        result["note"] = "宪法级固定层，不设止损止盈"
        return result
    
    # ─── 获取持仓成本 ───
    cost = None
    shares = None
    if ticker in positions:
        pos = positions[ticker]
        if isinstance(pos, dict):
            cost = pos.get("cost")
            shares = pos.get("shares")
    
    # ─── 美股进攻 ───
    if ticker_type == "spearhead":
        params = SPEARHEAD_STOP_PARAMS[ticker]
        c4 = indicators["h20"] * 0.98
        
        # 止损位 = C4 − stop_mult × ATR14（理论入场止损）
        stop_price = c4 - params["stop_mult"] * atr14
        if stop_price < 0:
            stop_price = c4 * 0.85  # 兜底
        
        result["entry_zone"] = round(c4, 4)
        result["stop_loss"] = round(stop_price, 4)
        result["stop_pct"] = round((current_price - stop_price) / current_price * 100, 2) if current_price > 0 else 0
        
        # 止盈
        if params["stop_type"] == "dynamic_drawdown":
            result["tp_type"] = "动态回撤"
            result["tp_activation"] = f"浮盈≥+{params['activation']*100:.0f}%"
            result["tp_drawdown"] = f"{params['drawdown_atr']}×ATR"
            if cost:
                activation_price = cost * (1 + params["activation"])
                result["tp_activation_price"] = round(activation_price, 4)
                result["tp_activated"] = current_price >= activation_price
        elif params["stop_type"] == "fixed_tp":
            result["tp_type"] = f"固定止盈+{params['tp_pct']*100:.0f}%"
            if cost:
                result["tp_price"] = round(cost * (1 + params["tp_pct"]), 4)
                result["tp_distance"] = round((result["tp_price"] - current_price) / current_price * 100, 2)
        elif params["stop_type"] == "none":
            result["tp_type"] = "仅止损"
    
    # ─── 反击 ───
    elif ticker_type == "counter":
        params = COUNTER_STOP_PARAMS[ticker]
        ma40 = indicators["ma40"]
        entry_zone = ma40 - params["k"] * atr14
        
        # 🔴 守东直接指定止损（不经过ATR公式）
        MANUAL_STOP = {
            "510500": 7.479,
            "512100": {"reduce": 2.78, "clear": 2.67},
        }
        if ticker in MANUAL_STOP:
            manual = MANUAL_STOP[ticker]
            if isinstance(manual, dict):
                stop_price = manual["clear"]  # 引擎用清仓价
                result["stop_note"] = f"守东直接指定：减仓¥{manual['reduce']}/清仓¥{manual['clear']}，不经过ATR公式"
            else:
                stop_price = manual
                result["stop_note"] = f"守东直接指定：¥{manual}，不经过ATR公式"
        else:
            stop_price = entry_zone - params["stop_mult"] * atr14
            if stop_price < 0:
                stop_price = entry_zone * 0.85
        
        result["ma40"] = round(ma40, 4)
        result["entry_zone"] = round(entry_zone, 4)
        result["stop_loss"] = round(stop_price, 4)
        result["stop_pct"] = round((current_price - stop_price) / current_price * 100, 2) if current_price > 0 else 0
        result["distance_to_entry"] = round((current_price - entry_zone) / current_price * 100, 2)
        
        # 止盈
        if "tp_fixed" in params:
            result["tp_type"] = f"固定止盈+{params['tp_fixed']*100:.0f}%"
            if cost:
                result["tp_price"] = round(cost * (1 + params["tp_fixed"]), 4)
        else:
            result["tp_type"] = "无止盈（均值回归自然退出）"
        
        # 熊市暂停（510500）
        if params.get("bear_pause") and indicators["ma60_dir"] == "↓":
            result["bear_pause"] = True
            result["note"] = "⚠️ 熊市暂停反击新开仓"
    
    # ─── A股进攻 ───
    elif ticker_type == "a_offensive":
        params = A_OFFENSIVE_STOP_PARAMS[ticker]
        ma5 = np.mean([indicators["close"]])  # 简化，实际应取最近5日
        # 实际应用需完整MA5计算，这里用近似
        ma60_dir = indicators["ma60_dir"]
        
        # 牛市判定
        is_bull = ma60_dir == "↑" and current_price > indicators["ma60"]
        
        if cost:
            stop_fixed = cost * (1 - params["fixed_pct"])
            stop_atr = cost - params["atr_mult"] * atr14
            stop_price = min(stop_fixed, stop_atr)
        else:
            stop_price = current_price * 0.95  # 估测
        
        result["stop_loss"] = round(stop_price, 4)
        result["stop_pct"] = round((current_price - stop_price) / current_price * 100, 2) if current_price > 0 else 0
        result["bull_market"] = is_bull
        
        if not is_bull:
            result["note"] = "⛔ 熊市/过渡期，A股进攻策略冻结"
        
        if params["tp_type"] == "fixed":
            result["tp_type"] = f"固定止盈+{params['tp_pct']*100:.0f}%"
            if cost:
                result["tp_price"] = round(cost * (1 + params["tp_pct"]), 4)
        elif params["tp_type"] == "MA20":
            result["tp_type"] = "MA20止盈"
            result["tp_price"] = round(indicators["ma20"], 4)
        elif params["tp_type"] == "batched":
            result["tp_type"] = f"分批止盈: {params['tp_batches']}"
            tp_details = []
            if cost:
                for i, (pct, w) in enumerate(zip(params['tp_batches'], params['tp_weights'])):
                    tp_details.append(f"第{i+1}批({w*100:.0f}%): +{pct*100:.0f}% → ${cost*(1+pct):.4f}")
            result["tp_details"] = tp_details
    
    # ─── 独立动量 ───
    elif ticker_type == "momentum":
        params = MOMENTUM_STOP_PARAMS[ticker]
        
        if cost:
            stop_price = cost - params["stop_atr"] * atr14
        else:
            stop_price = current_price * 0.90
        
        result["stop_loss"] = round(stop_price, 4)
        result["stop_pct"] = round((current_price - stop_price) / current_price * 100, 2) if current_price > 0 else 0
        result["tp_type"] = "动态回撤止盈"
        result["tp_activation"] = f"浮盈≥{params['activation_atr']}×ATR"
        result["tp_drawdown"] = f"回撤≥{params['drawdown_atr']}×ATR"
        
        # 轨道二恐慌抄底
        if "track2_threshold" in params:
            dd = indicators["drawdown_20d"]
            result["track2_triggered"] = dd < params["track2_threshold"]
            result["drawdown_20d"] = round(dd * 100, 2)
            if result["track2_triggered"]:
                track2_stop = current_price * (1 + params["track2_stop_pct"])
                result["track2_stop"] = round(track2_stop, 4)
                result["note"] = f"🟢 轨道二触发！20日回撤{dd*100:.1f}%"
    
    # ─── 金盾 ───
    elif ticker_type == "gold":
        params = GOLD_SHIELD_STOP_PARAMS[ticker]
        ma60 = indicators["ma60"]
        
        if cost:
            s6_price = cost * (1 + params["S6"])
            s7_price = cost * (1 + params["S7"])
        else:
            s6_price = current_price * 0.87
            s7_price = current_price * 0.81
        
        result["stop_loss"] = {
            "S4": round(ma60, 4),
            "S6": round(s6_price, 4),
            "S7": round(s7_price, 4),
        }
        result["tp_type"] = "金盾七级卖点（S1-S7）"
        result["note"] = "金盾独立体系，按金盾总纲V1.4执行"
    
    # ─── CANE ───
    elif ticker_type == "cane":
        params = CANE_STOP_PARAMS
        if cost:
            s6_price = cost * (1 + params["S6"])
            s7_price = cost * (1 + params["S7"])
            hard_stop_price = cost * (1 + params["hard_stop"])
        else:
            s6_price = current_price * 0.87
            s7_price = current_price * 0.81
            hard_stop_price = current_price * 0.75
        
        result["stop_loss"] = {
            "S6": round(s6_price, 4),
            "S7": round(s7_price, 4),
            "hard_stop": round(hard_stop_price, 4),
        }
        result["tp_type"] = "事件驱动退出（厄尔尼诺结束/糖价>+100%）"
    
    # ─── 通用：距止损ATR数 ───
    if result.get("stop_loss") and isinstance(result["stop_loss"], (int, float)):
        result["atr_to_stop"] = round((current_price - result["stop_loss"]) / atr14, 2) if atr14 > 0 else 0
    
    # ─── 加仓过热 ───
    if ticker_type not in ("fixed", "gold"):
        result["add_heat"] = check_add_heat(ticker, ticker_type)
    
    # ─── 持仓浮盈亏 ───
    if cost and shares:
        pnl = (current_price - cost) * shares
        pnl_pct = (current_price - cost) / cost * 100 if cost > 0 else 0
        result["position"] = {
            "shares": shares,
            "cost": round(cost, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        }
    
    # ─── 状态判定 ───
    has_pos = result.get("position") is not None
    stop_val = result.get("stop_loss")
    
    if isinstance(stop_val, dict):
        # 多级止损（金盾/CANE）→ 取最近一级
        numeric_stops = {k: v for k, v in stop_val.items() if isinstance(v, (int, float))}
        if numeric_stops:
            closest_stop = max(numeric_stops.values())  # 取最高价（最先触发）
            stop_val = closest_stop
    
    if has_pos and isinstance(stop_val, (int, float)) and stop_val > 0:
        if current_price <= stop_val:
            result["status"] = "🔴 已触发止损！"
        elif result.get("atr_to_stop", 99) < 1:
            result["status"] = "🟡 距止损<1×ATR，危险"
        elif result.get("atr_to_stop", 0) < 2:
            result["status"] = "🟡 观察（距止损1-2×ATR）"
        else:
            result["status"] = "🟢 安全"
    elif has_pos:
        result["status"] = "🟢 持有（多级止损体系）"
    elif result.get("status") is None:
        result["status"] = "⚪ 无持仓"
    
    return result


def format_output(result):
    """格式化输出"""
    if "error" in result:
        return f"❌ {result['error']}"
    
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"  {result['ticker']} 止损/止盈分析")
    lines.append(f"{'='*60}")
    lines.append(f"  类型: {result['type']} | 现价: {result['price']} | ATR14: {result['atr14']}")
    lines.append(f"  数据日期: {result.get('latest_date', 'N/A')}")
    
    if result.get("position"):
        pos = result["position"]
        lines.append(f"  持仓: {pos['shares']}股 | 成本: {pos['cost']} | 浮盈: {pos['pnl']} ({pos['pnl_pct']}%)")
    
    lines.append(f"\n  📊 止损止盈:")
    
    if isinstance(result.get("stop_loss"), dict):
        for k, v in result["stop_loss"].items():
            lines.append(f"    {k}: {v}")
    elif result.get("stop_loss"):
        lines.append(f"    止损位: {result['stop_loss']}")
        if result.get("stop_pct"):
            lines.append(f"    距止损: {result['stop_pct']}%")
        if result.get("atr_to_stop"):
            lines.append(f"    ATR倍数: {result['atr_to_stop']}×ATR")
    
    if result.get("entry_zone"):
        lines.append(f"    买入区间: ≤{result['entry_zone']}")
    
    if result.get("tp_type"):
        lines.append(f"    止盈: {result['tp_type']}")
    if result.get("tp_price"):
        lines.append(f"    止盈价: {result['tp_price']}")
    if result.get("tp_activation_price"):
        lines.append(f"    激活价: {result['tp_activation_price']} (已激活: {result.get('tp_activated', False)})")
    if result.get("tp_details"):
        for d in result["tp_details"]:
            lines.append(f"      {d}")
    
    lines.append(f"\n  🚦 状态: {result.get('status', 'N/A')}")
    
    if result.get("add_heat"):
        lines.append(f"  🔴 加仓过热: 30天内≥3次加仓")
    
    if result.get("bear_pause"):
        lines.append(f"  ⛔ 熊市暂停反击新开仓")
    
    if result.get("track2_triggered"):
        lines.append(f"  🟢 轨道二触发: 20日回撤{result['drawdown_20d']}% | 硬止损: {result.get('track2_stop')}")
    
    if result.get("note"):
        lines.append(f"  📝 {result['note']}")
    
    lines.append(f"{'='*60}\n")
    
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 stop_loss_engine.py <标的代码> [--json]")
        print("示例: python3 stop_loss_engine.py MUFG")
        print("      python3 stop_loss_engine.py 513910.SH --json")
        sys.exit(1)
    
    ticker = sys.argv[1]
    output_json = "--json" in sys.argv
    
    ticker_type = get_ticker_type(ticker)
    if ticker_type == "unknown":
        print(f"❌ 未知标的: {ticker}，不在全池24标内")
        sys.exit(1)
    
    indicators = get_market_data(ticker, ticker_type)
    result = compute_stop_loss(ticker, indicators)
    
    if output_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_output(result))


if __name__ == "__main__":
    main()
