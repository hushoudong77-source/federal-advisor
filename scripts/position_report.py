#!/usr/bin/env python3
"""
position_report.py V1.0 — /持仓 报告渲染器（2026-08-12 焊入）
联邦投顾持仓健康度诊断的最后一环：positions.json + stop_loss_engine.py → 四段式 Markdown

用法：
  python3 scripts/position_report.py                # 输出 /持仓 Markdown
  python3 scripts/position_report.py --json          # 输出JSON（供LLM进一步处理）

流水线：
  positions.json → stop_loss_engine.py（逐标） → position_report.py (渲染)
  注：position_health.py 的 Tushare 日线拉取 + 指标计算逻辑已集成到本脚本
"""

import json
import sys
import os
import subprocess
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(SCRIPT_DIR, "..")

# ══════════════════════════════════════════════════════════════
# 第零层：配置
# ══════════════════════════════════════════════════════════════

TICKER_NAMES = {
    "QQQ": "纳指100ETF", "IVV": "标普500ETF", "IAU": "黄金ETF",
    "BBJP": "日本大盘ETF", "MUFG": "三菱日联金融", "EWY": "韩国ETF",
    "VNM": "越南ETF", "FLIN": "印度大盘ETF", "SMIN": "印度小盘ETF",
    "VEA": "发达市场ETF", "VTI": "全美市场ETF", "BOTZ": "机器人AI ETF",
    "588000": "科创50ETF", "513180": "恒生科技ETF", "513910": "港股央企红利",
    "510500": "中证500ETF", "518880": "黄金ETF", "512100": "中证1000ETF",
    "510880": "红利ETF", "159530": "机器人ETF", "510300": "沪深300ETF",
    "159915": "创业板ETF", "513770": "恒生医疗ETF", "159545": "中证红利ETF",
    "CANE": "白糖ETN",
}

CN_TICKERS = {"588000", "513180", "513910", "510500", "518880", "512100",
              "510880", "159530", "510300", "159915", "513770", "159545"}

def ticker_market(ticker):
    return "cn" if ticker in CN_TICKERS else "us"


# ══════════════════════════════════════════════════════════════
# 第一层：数据拉取
# ══════════════════════════════════════════════════════════════

def load_positions():
    """从 positions.json 读取持仓"""
    try:
        with open(os.path.join(WORKSPACE, "scripts", "positions.json")) as f:
            pos_data = json.load(f)
        
        holdings = []
        cash = {}
        accounts = pos_data.get("accounts", {})
        
        for acct in ["A", "B"]:
            acct_data = accounts.get(acct, {})
            cash[acct] = acct_data.get("cash_approx", 0)
            
            # 加上 extra_cash
            extra = acct_data.get("extra_cash", {})
            if extra:
                cash[acct] += extra.get("cmb", 0)
            
            # 遍历持仓
            for ticker, item in acct_data.get("holdings", {}).items():
                shares = item.get("shares", 0)
                cost = item.get("cost", 0)
                if shares > 0 and ticker not in ("511880", "SGOV"):  # 跳过现金等价物
                    holdings.append({
                        "ticker": ticker,
                        "account": acct,
                        "shares": shares,
                        "cost": cost,
                    })
                elif ticker in ("511880", "SGOV"):
                    # 现金等价物计入现金
                    cash[acct] += shares * cost
        
        return {"holdings": holdings, "cash": cash}
    except Exception as e:
        return {"holdings": [], "cash": {"A": 0, "B": 0}, "error": str(e)}


def run_stop_loss(ticker):
    """调用 stop_loss_engine.py 获取止损止盈数据"""
    try:
        result = subprocess.run(
            ["python3", os.path.join(SCRIPT_DIR, "stop_loss_engine.py"), ticker, "--json"],
            capture_output=True, text=True, timeout=30
        )
        return json.loads(result.stdout)
    except:
        return {"ticker": ticker, "error": "stop_loss_engine 调用失败"}


def run_market_data():
    """调用 market_data.py 获取现价"""
    try:
        result = subprocess.run(
            ["python3", os.path.join(SCRIPT_DIR, "market_data.py")],
            capture_output=True, text=True, timeout=120
        )
        s = result.stdout.strip()
        for i, c in enumerate(s):
            if c in ('{', '['):
                return json.loads(s[i:])
        return {}
    except:
        return {}


def run_pipeline():
    """跑完整流水线"""
    pos_data = load_positions()
    holdings = pos_data["holdings"]
    
    if not holdings:
        return {"holdings": [], "cash": pos_data["cash"], "error": "无持仓"}
    
    # 拉取现价（market_data.py 一次拿到所有标的的现价）
    market_data = run_market_data()
    
    # 逐标跑 stop_loss_engine
    results = []
    for h in holdings:
        ticker = h["ticker"]
        sl = run_stop_loss(ticker)
        
        # 现价优先用腾讯实时（market_data），其次用 stop_loss_engine 的 Tushare 收盘价
        md = market_data.get(ticker, {}) or {}
        price = md.get("price") or sl.get("price")
        
        # MACD/RSI/MA60方向 从 market_data 取
        macd = md.get("macd", {}) or {}
        macd_bar = macd.get("bar") if isinstance(macd, dict) else None
        rsi14 = md.get("rsi14")
        ma60_dir = md.get("ma60_dir", "")
        ma20 = md.get("ma20")
        ma60 = md.get("ma60")
        atr14 = md.get("atr14") or sl.get("atr14")
        drawdown_20d = md.get("drawdown_20d")
        
        # 均线排列
        ma5 = md.get("ma5")
        ma120 = md.get("ma120")
        bull_alignment = False
        bear_alignment = False
        if all(v is not None for v in [ma5, ma20, ma60, ma120]):
            bull_alignment = ma5 > ma20 > ma60 > ma120
            bear_alignment = ma5 < ma20 < ma60 < ma120
        
        # 持仓成本/股数
        cost = h["cost"]
        shares = h["shares"]
        market_value = price * shares if price and shares else 0
        pnl = (price - cost) * shares if price and cost and shares else 0
        pnl_pct = (price - cost) / cost * 100 if cost and cost > 0 else 0
        
        # 止损信息
        stop_loss_price = sl.get("stop_loss")
        # 金盾可能返回 dict（多级止损），取 S6 作为主止损
        if isinstance(stop_loss_price, dict):
            stop_loss_price = stop_loss_price.get("S6") or stop_loss_price.get("S3")
        atr_to_stop = sl.get("atr_to_stop")
        stop_pct = sl.get("stop_pct")
        
        # 止盈信息
        tp_type = sl.get("tp_type", "")
        tp_price = sl.get("tp_price")
        tp_distance = sl.get("tp_distance")
        
        # 健康度判定（四维）
        health, health_details = _calc_health(
            price, cost, stop_loss_price, atr14, atr_to_stop,
            ma60_dir, bull_alignment, bear_alignment, price, ma60, ma20,
            macd_bar, rsi14
        )
        
        results.append({
            "ticker": ticker,
            "name": TICKER_NAMES.get(ticker, ""),
            "account": h["account"],
            "shares": shares,
            "cost": cost,
            "price": price,
            "market_value": market_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "atr14": atr14,
            "stop_loss": stop_loss_price,
            "atr_to_stop": atr_to_stop,
            "stop_pct": stop_pct,
            "tp_type": tp_type,
            "tp_price": tp_price,
            "tp_distance": tp_distance,
            "macd_bar": macd_bar,
            "rsi14": rsi14,
            "ma60_dir": ma60_dir,
            "ma20": ma20,
            "ma60": ma60,
            "bull_alignment": bull_alignment,
            "bear_alignment": bear_alignment,
            "drawdown_20d": drawdown_20d,
            "health": health,
            "health_details": health_details,
        })
    
    return {
        "holdings": results,
        "cash": pos_data["cash"],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _calc_health(price, cost, stop_loss, atr14, atr_to_stop,
                 ma60_dir, bull, bear, px, ma60, ma20,
                 macd_bar, rsi):
    """四维健康度判定"""
    details = {}
    
    # 维度1: 止损距离
    if atr_to_stop is not None and isinstance(atr_to_stop, (int, float)):
        if atr_to_stop < 1:
            details["止损距离"] = {"level": "🔴", "detail": f"距止损{atr_to_stop:.1f}×ATR，危险"}
        elif atr_to_stop < 2:
            details["止损距离"] = {"level": "🟡", "detail": f"距止损{atr_to_stop:.1f}×ATR，接近"}
        else:
            details["止损距离"] = {"level": "🟢", "detail": f"距止损{atr_to_stop:.1f}×ATR，安全"}
    else:
        details["止损距离"] = {"level": "?", "detail": "无止损位"}
    
    # 维度2: 均线结构
    if ma60_dir and ma60_dir.lower() == "up":
        if bull:
            details["均线结构"] = {"level": "🟢", "detail": "多头排列✅"}
        else:
            details["均线结构"] = {"level": "🟢", "detail": "MA60↑"}
    elif ma60_dir and ma60_dir.lower() == "down":
        # MACD金叉+MA60↓ = 🟡（均值回归中），纯死叉+MA60↓ = 🔴
        if macd_bar is not None and macd_bar > 0:
            details["均线结构"] = {"level": "🟡", "detail": f"MA60↓但MACD金叉(BAR={macd_bar:+.4f})，均值回归中"}
        else:
            details["均线结构"] = {"level": "🔴", "detail": f"MA60↓{' 空头排列' if bear else ''}"}
    else:
        details["均线结构"] = {"level": "🟡", "detail": "MA60走平/不明"}
    
    # 维度3: 动量指标
    if macd_bar is not None:
        if macd_bar > 0:
            details["动量指标"] = {"level": "🟢", "detail": f"MACD BAR>0 ({macd_bar:+.4f})"}
        else:
            details["动量指标"] = {"level": "🔴" if macd_bar < -0.1 else "🟡",
                                   "detail": f"MACD BAR<0 ({macd_bar:+.4f})"}
    else:
        details["动量指标"] = {"level": "?", "detail": "数据缺失"}
    
    # 维度4: 仓位集中度（简化，实际需总资产，此处留后注入）
    details["仓位集中度"] = {"level": "?", "detail": "待计算"}
    
    # 综合
    levels = [d["level"] for d in details.values()]
    if "🔴" in levels:
        health = "🔴 危险"
    elif levels.count("🟡") >= 2:
        health = "🟡 观察"
    elif "🟡" in levels:
        health = "🟡 观察"
    else:
        health = "🟢 健康"
    
    return health, details


# ══════════════════════════════════════════════════════════════
# 第二层：Markdown 渲染
# ══════════════════════════════════════════════════════════════

def render_markdown(data):
    """渲染 /持仓 四段式 Markdown"""
    holdings = data["holdings"]
    cash = data["cash"]
    
    if not holdings:
        return "# 🏥 联邦持仓健康诊断\n\n⚠️ 无持仓数据"
    
    lines = []
    
    # ── 段一：A账户持仓表 ──
    a_holdings = [h for h in holdings if h["account"] == "A"]
    if a_holdings:
        lines.append(f"# 🏥 联邦持仓健康诊断 — {datetime.now().strftime('%Y-%m-%d')}")
        lines.append("")
        lines.append("## 一、A账户")
        lines.append("")
        lines.append("| 标的 | 持仓 | 成本 | 现价 | 市值 | 浮盈亏 | 盈亏% | 健康度 |")
        lines.append("|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
        
        a_total_mv = 0
        a_total_pnl = 0
        for h in a_holdings:
            price_s = _fmt_price(h["price"], h["ticker"])
            cost_s = _fmt_price(h["cost"], h["ticker"])
            mv_s = f"¥{h['market_value']:,.0f}" if h["market_value"] else "—"
            pnl_s = f"{h['pnl']:+,.0f}" if h["pnl"] else "—"
            pnl_pct_s = f"{h['pnl_pct']:+.1f}%" if h["pnl_pct"] else "—"
            lines.append(
                f"| {h['ticker']} | {h['shares']:,}股 | {cost_s} | {price_s} | {mv_s} | {pnl_s} | {pnl_pct_s} | {h['health']} |"
            )
            a_total_mv += h["market_value"] or 0
            a_total_pnl += h["pnl"] or 0
        
        a_total = a_total_mv + cash.get("A", 0)
        a_equity = (a_total_mv / a_total * 100) if a_total > 0 else 0
        lines.append("")
        lines.append(f"├── 现金: ¥{cash.get('A', 0):,.0f}（{100-a_equity:.0f}%） | 总资产: ¥{a_total:,.0f}")
        lines.append("")
    
    # ── 段二：B账户持仓表 ──
    b_holdings = [h for h in holdings if h["account"] == "B"]
    if b_holdings:
        if not a_holdings:
            lines.append(f"# 🏥 联邦持仓健康诊断 — {datetime.now().strftime('%Y-%m-%d')}")
            lines.append("")
        lines.append("## 二、B账户")
        lines.append("")
        lines.append("| 标的 | 持仓 | 成本 | 现价 | 市值 | 浮盈亏 | 盈亏% | 健康度 |")
        lines.append("|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
        
        b_total_mv = 0
        b_total_pnl = 0
        for h in b_holdings:
            price_s = _fmt_price(h["price"], h["ticker"])
            cost_s = _fmt_price(h["cost"], h["ticker"])
            mv_s = f"${h['market_value']:,.0f}" if h["market_value"] else "—"
            pnl_s = f"{h['pnl']:+,.0f}" if h["pnl"] else "—"
            pnl_pct_s = f"{h['pnl_pct']:+.1f}%" if h["pnl_pct"] else "—"
            lines.append(
                f"| {h['ticker']} | {h['shares']:,}股 | {cost_s} | {price_s} | {mv_s} | {pnl_s} | {pnl_pct_s} | {h['health']} |"
            )
            b_total_mv += h["market_value"] or 0
            b_total_pnl += h["pnl"] or 0
        
        b_total = b_total_mv + cash.get("B", 0)
        b_equity = (b_total_mv / b_total * 100) if b_total > 0 else 0
        lines.append("")
        lines.append(f"├── 现金: ${cash.get('B', 0):,.0f}（{100-b_equity:.0f}%） | 总资产: ${b_total:,.0f}")
        lines.append("")
    
    # ── 段三：逐标健康度诊断 ──
    lines.extend(_render_health_detail(holdings))
    
    # ── 段四：操作建议汇总 ──
    lines.extend(_render_action_summary(holdings))
    
    return "\n".join(lines)


def _render_health_detail(holdings):
    """段三：逐标健康度诊断"""
    lines = ["## 三、逐标健康度诊断", ""]
    
    # 分组
    healthy = [h for h in holdings if "🟢" in h["health"]]
    watch = [h for h in holdings if "🟡" in h["health"]]
    danger = [h for h in holdings if "🔴" in h["health"]]
    
    if danger:
        lines.append("### 🔴 危险（需立即关注）")
        lines.append("")
        for h in danger:
            lines.append(f"**{h['ticker']}** {h.get('name','')} | {h['shares']:,}股 | 成本{_fmt_price(h['cost'], h['ticker'])}")
            for dim, diag in h.get("health_details", {}).items():
                lines.append(f"├── {dim}: {diag.get('level','?')} {diag.get('detail','')}")
            # 止损信息
            if h.get("stop_loss"):
                lines.append(f"├── 止损位: {_fmt_price(h['stop_loss'], h['ticker'])} | 距止损: {h.get('atr_to_stop','?')}×ATR")
            if h.get("tp_type"):
                lines.append(f"├── 止盈: {h['tp_type']} @ {_fmt_price(h.get('tp_price'), h['ticker'])}")
            lines.append("")
    
    if watch:
        lines.append("### 🟡 观察（接近边界）")
        lines.append("")
        for h in watch:
            lines.append(f"**{h['ticker']}** {h.get('name','')} | {h['shares']:,}股 | 成本{_fmt_price(h['cost'], h['ticker'])}")
            for dim, diag in h.get("health_details", {}).items():
                if diag.get("level") in ("🟡", "🔴"):
                    lines.append(f"├── {dim}: {diag.get('level','?')} {diag.get('detail','')}")
            if h.get("stop_loss"):
                lines.append(f"├── 止损位: {_fmt_price(h['stop_loss'], h['ticker'])} | 距止损: {h.get('atr_to_stop','?')}×ATR")
            lines.append("")
    
    if healthy:
        lines.append("### 🟢 健康（无需操作）")
        lines.append("")
        for h in healthy:
            lines.append(f"├── {h['ticker']} {h.get('name','')}: {h['shares']:,}股 | 浮盈{h['pnl_pct']:+.1f}% | 距止损{h.get('atr_to_stop','?')}×ATR")
        lines.append("")
    
    return lines


def _render_action_summary(holdings):
    """段四：操作建议汇总"""
    lines = ["## 四、操作建议汇总", ""]
    
    actions = []
    for h in holdings:
        health = h["health"]
        if "🔴" in health:
            actions.append({
                "priority": "🔴", "ticker": h["ticker"],
                "action": "审查止损",
                "detail": f"距止损仅{h.get('atr_to_stop','?')}×ATR"
            })
        elif "🟡" in health:
            details = h.get("health_details", {})
            issues = [f"{dim}: {d['detail']}" for dim, d in details.items() if d.get("level") == "🟡"]
            actions.append({
                "priority": "🟡", "ticker": h["ticker"],
                "action": "观察",
                "detail": "; ".join(issues) if issues else "接近边界"
            })
    
    if not actions:
        lines.append("全部持仓健康，无待执行操作。")
        return lines
    
    lines.append("| # | 优先级 | 标的 | 操作 | 详情 |")
    lines.append("|:---:|:---:|:---|:---|:---|")
    
    priority_order = {"🔴": 0, "🟡": 1}
    actions.sort(key=lambda a: priority_order.get(a["priority"], 99))
    
    for i, a in enumerate(actions, 1):
        lines.append(f"| {i} | {a['priority']} | {a['ticker']} | {a['action']} | {a['detail']} |")
    
    lines.append("")
    lines.append("**优先级**：🟢可执行 | 🟡观察 | 🔴紧急")
    
    return lines


def _fmt_price(val, ticker):
    """格式化价格"""
    if val is None:
        return "—"
    if isinstance(val, (int, float)):
        if ticker_market(ticker) == "cn":
            return f"¥{val:.4f}" if val < 100 else f"¥{val:.3f}"
        return f"${val:.2f}"
    return str(val)


# ══════════════════════════════════════════════════════════════
# CLI入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="联邦投顾持仓健康度报告渲染器")
    parser.add_argument("--json", action="store_true", help="输出JSON（供LLM进一步处理）")
    args = parser.parse_args()
    
    data = run_pipeline()
    
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_markdown(data))
