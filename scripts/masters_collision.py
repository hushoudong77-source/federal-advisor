#!/usr/bin/env python3
"""
masters_collision.py V1.0 — /大师对撞 数据层脚本（2026-08-12 焊入）
联邦投顾四大师对撞流水线的数据层：拉取全量指标 + 输出结构化物理数据草稿

用法：
  python3 scripts/masters_collision.py QQQ          # 输出 Markdown 物理数据草稿
  python3 scripts/masters_collision.py QQQ --json   # 输出 JSON（供 LLM 进一步处理）

流水线：
  ① market_data.py 拉取 TickFlow 日线 + 腾讯实时现价 → 全量技术指标
  ② read_positions.py 读取持仓/成本（撒普 R 倍数需要）
  ③ 计算四框架判定所需的全部衍生指标
  ④ 按四章制模板输出 Markdown 草稿（物理层完成，对撞层留 LLM 填充）

四框架数据需求：
  Weinstein: MA30周线方向(≈MA150日线), 价格vs MA30周, MA21日线, 成交量特征
  CAN SLIM:  季度EPS增速(❌无数据源→标注数据真空), RS排名(❌无数据源), 机构持股(❌)
              → 仅提供可量化的替代指标：MA60方向(趋势强度), RSI14(超买超卖), MACD(动量)
  撒普R倍数: 现价/成本/浮盈亏 → 从 positions.json 读取
  达利奥:    宏观环境(DXY/US10Y/VIX/CRB) → 从 macro_gate 获取
"""

import json
import sys
import os
import subprocess
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(SCRIPT_DIR, "..")

# 标的名称映射
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


def get_ticker_info(ticker):
    """获取单标的全量物理数据"""
    
    # Step 1: market_data.py
    md = subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "market_data.py")],
        capture_output=True, text=True, timeout=120
    )
    market_data = _parse_json(md.stdout)
    
    if ticker not in market_data:
        return {"error": f"标的 {ticker} 不在 market_data 输出中", "available": list(market_data.keys())[:20]}
    
    ticker_data = market_data[ticker]
    
    # Step 2: 持仓数据
    positions = {}
    try:
        with open(os.path.join(SCRIPT_DIR, "positions.json")) as f:
            all_pos = json.load(f)
        for account in ["A", "B"]:
            for pos in all_pos.get(account, []):
                if pos.get("ticker") == ticker:
                    positions[account] = pos
    except:
        pass
    
    # Step 3: 宏观数据
    mg = subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "macro_gate.py")],
        capture_output=True, text=True, timeout=30
    )
    macro = _parse_json(mg.stdout)
    
    return {
        "ticker": ticker,
        "name": TICKER_NAMES.get(ticker, ticker),
        "market_data": ticker_data,
        "positions": positions,
        "macro": macro,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def render_markdown(data):
    """渲染 /大师对撞 Markdown 物理数据草稿（四章制）"""
    ticker = data["ticker"]
    name = data["name"]
    mkt = data["market_data"]
    pos = data["positions"]
    macro = data.get("macro", {})
    
    lines = []
    
    # ── 标题 + 数据新鲜度 ──
    lines.append(f"# 🥊 大师对撞 — {ticker} {name}")
    lines.append("")
    lines.append(f"数据窗口: {mkt.get('latest_date', '?')} | 现价: ${_fmt(mkt.get('price'))} ({mkt.get('price_source', '?')})")
    lines.append("")
    
    # ═══════════════════════════════════════
    # 第一章：Sentinel-01 物理层
    # ═══════════════════════════════════════
    lines.append("## 一、Sentinel-01 物理层：冻结事实")
    lines.append("")
    
    # 1.1 基本行情
    lines.append("### 基本行情")
    lines.append("")
    lines.append("| 项目 | 数值 |")
    lines.append("|:---|---:|")
    lines.append(f"| 现价 | {_fmt(mkt.get('price'))} |")
    lines.append(f"| 涨跌 | {_fmt_pct(mkt.get('change_pct'))} |")
    lines.append(f"| 开盘 | {_fmt(mkt.get('open'))} |")
    lines.append(f"| 最高 | {_fmt(mkt.get('high'))} |")
    lines.append(f"| 最低 | {_fmt(mkt.get('low'))} |")
    vol = mkt.get('volume')
    vol_str = f"{vol:,.0f}" if vol else "—"
    lines.append(f"| 成交量 | {vol_str} |")
    lines.append(f"| 量比(vs 20日均量) | {_fmt(mkt.get('vol_ratio'), 2)} |")
    lines.append(f"| 数据源 | {mkt.get('data_source', '?')} → 腾讯实时 |")
    lines.append("")
    
    # 1.2 均线系统（七线）
    lines.append("### 均线系统（七线全覆盖）")
    lines.append("")
    lines.append("| 均线 | 数值 | 方向 | 现价距 |")
    lines.append("|:---|---:|:---:|:---:|")
    for ma in [5, 20, 40, 60, 120, 150, 250]:
        val = mkt.get(f"ma{ma}")
        direction = mkt.get(f"ma{ma}_dir", "—")
        dev = mkt.get(f"dev_ma{ma}")
        lines.append(f"| MA{ma} | {_fmt(val)} | {_fmt_dir(direction)} | {_fmt_pct(dev)} |")
    lines.append("")
    
    # 1.3 核心指标
    lines.append("### 核心指标")
    lines.append("")
    lines.append("| 指标 | 数值 | 说明 |")
    lines.append("|:---|---:|:---|")
    lines.append(f"| ATR14 | {_fmt(mkt.get('atr14'))} ({_fmt_pct(mkt.get('atr_pct'))}) | 14日平均真实波幅 |")
    lines.append(f"| RSI14 | {_fmt(mkt.get('rsi14'), 1)} | {'超买⚠️' if mkt.get('rsi14', 50) > 70 else ('超卖' if mkt.get('rsi14', 50) < 30 else '正常')} |")
    
    macd = mkt.get('macd', {})
    if isinstance(macd, dict):
        lines.append(f"| MACD DIFF | {_fmt(macd.get('diff'), 4)} | |")
        lines.append(f"| MACD DEA | {_fmt(macd.get('dea'), 4)} | |")
        lines.append(f"| MACD BAR | {_fmt(macd.get('bar'), 4)} | {'🟢金叉' if macd.get('bar', 0) > 0 and macd.get('bar_prev', 0) <= 0 else ('🔴死叉' if macd.get('bar', 0) < 0 and macd.get('bar_prev', 0) >= 0 else ('动能增强🟢' if macd.get('bar', 0) > macd.get('bar_prev', 0) else '动能减弱🔴'))} |")
    
    kdj = mkt.get('kdj', {})
    if isinstance(kdj, dict):
        lines.append(f"| KDJ K/D/J | {_fmt(kdj.get('k'), 1)}/{_fmt(kdj.get('d'), 1)}/{_fmt(kdj.get('j'), 1)} | {'超买⚠️' if kdj.get('overbought') else ('超卖' if kdj.get('oversold') else '正常')} |")
    
    obv = mkt.get('obv', {})
    if isinstance(obv, dict):
        obv_status = []
        if obv.get('bullish_div'): obv_status.append('🟢底背离')
        if obv.get('bearish_div'): obv_status.append('🔴顶背离')
        if obv.get('obv_new_high'): obv_status.append('新高')
        if obv.get('obv_new_low'): obv_status.append('新低')
        lines.append(f"| OBV | {'>' if obv.get('obv_above_ma20') else '<'}MA20 | {', '.join(obv_status) if obv_status else '正常'} |")
    
    lines.append(f"| ADX14 | {_fmt(mkt.get('adx14'), 1)} | {'强趋势(>30)' if mkt.get('adx14', 0) > 30 else ('弱趋势(<20)' if mkt.get('adx14', 0) < 20 else '过渡区间')} |")
    lines.append(f"| H20(20日最高) | {_fmt(mkt.get('h20'))} | |")
    lines.append(f"| 20日回撤 | {_fmt_pct(mkt.get('drawdown_20d'))} | |")
    lines.append("")
    
    # 1.4 物理位阶判定
    lines.append("### 物理位阶判定")
    lines.append("")
    price = mkt.get('price', 0)
    ma60_val = mkt.get('ma60', 0)
    ma120_val = mkt.get('ma120', 0)
    ma250_val = mkt.get('ma250', 0)
    
    above = []
    below = []
    for ma, val in [(5, mkt.get('ma5')), (20, mkt.get('ma20')), (40, mkt.get('ma40')),
                     (60, mkt.get('ma60')), (120, mkt.get('ma120')), (150, mkt.get('ma150')),
                     (250, mkt.get('ma250'))]:
        if price and val:
            if price >= val:
                above.append(f"MA{ma}")
            else:
                below.append(f"MA{ma}")
    
    stage = "⚪ 待 LLM 判定"
    if price > ma60_val > ma120_val > ma250_val:
        stage_hint = "均线多头排列 → 倾向 Stage 2 主升"
    elif price < ma60_val < ma120_val < ma250_val:
        stage_hint = "均线空头排列 → 倾向 Stage 4 破位"
    elif price < ma250_val:
        stage_hint = "跌破年线 → 倾向 Stage 4"
    else:
        stage_hint = "均线交织 → 倾向 Stage 1/3 震荡"
    
    lines.append(f"├── 站上: {', '.join(above) if above else '无'}")
    lines.append(f"├── 跌破: {', '.join(below) if below else '无'}")
    lines.append(f"├── MA60: {_fmt(ma60_val)} ({_fmt_dir(mkt.get('ma60_dir', '—'))}) | MA120: {_fmt(ma120_val)} | MA250: {_fmt(ma250_val)}")
    lines.append(f"└── 均线结构: {stage_hint}")
    lines.append("")
    
    # 1.5 持仓与成本
    if pos:
        lines.append("### 持仓与成本")
        lines.append("")
        for account, p in pos.items():
            shares = p.get("shares", "?")
            cost = p.get("cost", "?")
            mkt_val = price * shares if price and isinstance(shares, (int, float)) else "?"
            pnl = (price - cost) * shares if price and cost and isinstance(shares, (int, float)) else "?"
            pnl_pct = ((price / cost - 1) * 100) if price and cost else "?"
            lines.append(f"├── {account}账户: {shares}股 | 成本: {_fmt(cost)} | 市值: {_fmt(mkt_val)} | 浮盈: {_fmt(pnl)} ({_fmt_pct(pnl_pct)})")
        lines.append("")
    else:
        lines.append("### 持仓与成本")
        lines.append("")
        lines.append("⚠️ 该标的未确权持仓")
        lines.append("")
    
    # 1.6 宏观环境
    lines.append("### 宏观重力场")
    lines.append("")
    lines.append("| 锚点 | 现值 | 方向 |")
    lines.append("|:---|---:|:---|")
    
    dxy = macro.get("dxy", {})
    us10y = macro.get("us10y", {})
    vix = macro.get("vix", {})
    
    lines.append(f"| DXY | {_fmt(dxy.get('value'))} | {dxy.get('label', '—')} |")
    lines.append(f"| US10Y | {_fmt(dxy.get('value'))}% | {us10y.get('label', '—')} |")
    lines.append(f"| VIX | {_fmt(vix.get('value'))} | {vix.get('label', '—')} |")
    lines.append("")
    
    # ═══════════════════════════════════════
    # 第二章：四大师框架对撞（LLM 填充区）
    # ═══════════════════════════════════════
    lines.append("## 二、大师战术知识库对撞")
    lines.append("")
    lines.append("> ⚠️ 以下四维度判定由 LLM 基于上述物理数据完成。脚本仅提供数据草稿。")
    lines.append("")
    
    # Weinstein 判定辅助数据
    lines.append("### 🥊 第一维度：Weinstein 阶段判定")
    lines.append("")
    lines.append("| 判定指标 | 当前状态 | 阶段判定 |")
    lines.append("|:---|:---|:---:|")
    ma150_val = mkt.get('ma150', 0)
    ma150_dir = mkt.get('ma150_dir', '—')
    ma20_val = mkt.get('ma20')
    lines.append(f"| MA30周线方向(≈MA150日线) | {_fmt(ma150_val)} {_fmt_dir(ma150_dir)} | [LLM判定] |")
    lines.append(f"| 价格 vs MA30周 | {_fmt(price)} vs {_fmt(ma150_val)} ({_fmt_pct(mkt.get('dev_ma150'))}) | [LLM判定] |")
    lines.append(f"| 短期MA21(≈MA20日线) | {_fmt(ma20_val)} {_fmt_dir(mkt.get('ma20_dir', '—'))} | [LLM判定] |")
    lines.append(f"| 成交量特征 | 量比 {_fmt(mkt.get('vol_ratio'), 2)} | [LLM判定] |")
    lines.append("")
    lines.append("**结论**: [LLM填写 — 阶段判定 + 一句话本质描述]")
    lines.append("")
    
    # CAN SLIM 辅助数据
    lines.append("### 🥊 第二维度：CAN SLIM 适配")
    lines.append("")
    lines.append("| CAN SLIM 要素 | 标的适配 | 评分 |")
    lines.append("|:---|:---|---:|")
    lines.append(f"| C 当季EPS增长 | ⚠️ ETF无EPS数据 | — |")
    lines.append(f"| A 年度EPS增长 | ⚠️ ETF无EPS数据 | — |")
    lines.append(f"| N 新产品/新趋势 | [LLM判定] | [LLM评分] |")
    lines.append(f"| S 供需(量比) | 量比 {_fmt(mkt.get('vol_ratio'), 2)} | [LLM评分] |")
    lines.append(f"| L 领涨股(RSI) | RSI14={_fmt(mkt.get('rsi14'), 1)} | [LLM评分] |")
    lines.append(f"| I 机构持股 | ⚠️ 无数据源 | — |")
    lines.append(f"| M 大盘方向(MA60) | MA60 {_fmt_dir(mkt.get('ma60_dir', '—'))} | [LLM评分] |")
    lines.append("")
    lines.append("**结论**: [LLM填写 — 总分/100，主要扣分项]")
    lines.append("")
    
    # 撒普 R 倍数 辅助数据
    lines.append("### 🥊 第三维度：撒普 R 倍数框架")
    lines.append("")
    if pos:
        lines.append("| R 维度 | 计算 | 审计 |")
        lines.append("|:---|---:|:---|")
        for account, p in pos.items():
            shares = p.get("shares", 0)
            cost = p.get("cost", 0)
            if price and cost and shares:
                pnl = (price - cost) * shares
                pnl_pct = (price / cost - 1) * 100
                lines.append(f"| 浮盈({account}) | {_fmt(pnl)} ({_fmt_pct(pnl_pct)}) | [LLM审计] |")
        lines.append(f"| ATR14 | {_fmt(mkt.get('atr14'))} ({_fmt_pct(mkt.get('atr_pct'))}) | [LLM审计] |")
        lines.append("")
        lines.append("**R_tier**: [LLM判定 — L1~L5]")
    else:
        lines.append("⚠️ 无持仓数据，R倍数无法计算")
    lines.append("")
    
    # 达利奥 辅助数据
    lines.append("### 🥊 第四维度：达利奥全天候适配")
    lines.append("")
    lines.append("| 经济环境 | 当前状态 | 适配度 |")
    lines.append("|:---|:---|:---:|")
    lines.append(f"| 增长 | DXY {_fmt(dxy.get('value'))}, VIX {_fmt(vix.get('value'))} | [LLM判定] |")
    lines.append(f"| 通胀 | US10Y {_fmt(us10y.get('value'))}% | [LLM判定] |")
    lines.append(f"| 紧缩 | [LLM判定] | [LLM判定] |")
    lines.append("")
    lines.append("**结论**: [LLM填写]")
    lines.append("")
    
    # ═══════════════════════════════════════
    # 第三、四章（完全 LLM 填充）
    # ═══════════════════════════════════════
    lines.append("## 三、大师对撞综合裁决")
    lines.append("")
    lines.append("| 大师框架 | 核心判定 | 信号灯 |")
    lines.append("|:---|:---|:---:|")
    lines.append("| Weinstein | [LLM填写] | [LLM判定] |")
    lines.append("| CAN SLIM | [LLM填写] | [LLM判定] |")
    lines.append("| 撒普R倍数 | [LLM填写] | [LLM判定] |")
    lines.append("| 达利奥 | [LLM填写] | [LLM判定] |")
    lines.append("")
    lines.append("**四大师共识**: [LLM填写]")
    lines.append("")
    lines.append("## 四、核心指令")
    lines.append("")
    lines.append("> **⚔️ 核心指令**")
    lines.append("> ")
    lines.append("> **持仓**: [LLM填写]")
    lines.append("> ")
    lines.append("> **止损**: [LLM填写]")
    lines.append("> ")
    lines.append("> **加仓条件**: [LLM填写]")
    lines.append("> ")
    lines.append("> **挂单**: [LLM填写]")
    lines.append("")
    
    # 签章
    lines.append("---")
    lines.append("")
    lines.append(f"*全球资产管理部 · 首席执行官 | {data['timestamp']}*")
    
    return "\n".join(lines)


def _fmt(val, decimals=2):
    """安全格式化数值"""
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:,.{decimals}f}"
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def _fmt_pct(val, decimals=1):
    """安全格式化百分比"""
    if val is None:
        return "—"
    if isinstance(val, (int, float)):
        sign = "+" if val > 0 else ""
        return f"{sign}{val:.{decimals}f}%"
    return str(val)


def _fmt_dir(d):
    """格式化方向"""
    if not d:
        return "—"
    d = str(d).lower()
    if d in ("up", "↑"):
        return "↑"
    elif d in ("down", "↓"):
        return "↓"
    elif d in ("flat", "→"):
        return "→"
    return d


def _parse_json(s):
    """安全解析JSON"""
    s = s.strip()
    for i, c in enumerate(s):
        if c in ('{', '['):
            try:
                return json.loads(s[i:])
            except:
                return {"error": "JSON解析失败", "raw": s[:500]}
    return {"error": "无有效JSON", "raw": s[:500]}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="/大师对撞 数据层脚本 V1.0")
    parser.add_argument("ticker", help="标的代码，如 QQQ, 513910")
    parser.add_argument("--json", action="store_true", help="输出JSON而非Markdown")
    args = parser.parse_args()
    
    ticker = args.ticker.upper()
    data = get_ticker_info(ticker)
    
    if "error" in data:
        print(f"❌ {data['error']}")
        if "available" in data:
            print(f"可用标的: {data['available']}")
        sys.exit(1)
    
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(render_markdown(data))


if __name__ == "__main__":
    main()
