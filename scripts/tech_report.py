#!/usr/bin/env python3
"""
联邦投顾 — /技术 六段式报告生成器 V1.0
用法: python3 scripts/tech_report.py <ticker>
依赖: market_data.py（自动拉取全量数据）
"""

import sys
import json
import subprocess
from datetime import datetime


def load_market_data():
    result = subprocess.run(
        ["python3", "scripts/market_data.py"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        print(f"❌ market_data.py 失败: {result.stderr}")
        sys.exit(1)
    return json.loads(result.stdout)


def _fmt(v, precision=2, prefix="", suffix=""):
    if v is None: return "—"
    if isinstance(v, float): return f"{prefix}{v:.{precision}f}{suffix}"
    if isinstance(v, int): return f"{prefix}{v:,}{suffix}"
    return str(v)

def _fmt_chg(v):
    if v is None: return "—"
    return f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"

def _entity_pct(open_, close):
    if not open_ or not close or open_ == 0: return None
    return abs(close - open_) / open_ * 100

def _ma_dir_emoji(d):
    if d == "up": return "↑"
    if d == "down": return "↓"
    return "→"

def _trend_stage(ma60_dir, close, ma60):
    """大周期趋势判断 — 修正版：close>ma60 且 ma60↑ = 趋势反转"""
    if ma60_dir == "up" and close and ma60 and close > ma60:
        return "🟢 趋势反转（MA60↑+价>MA60）"
    if ma60_dir == "up":
        return "🟡 中级反弹（MA60↑但价<MA60）"
    if ma60_dir == "down" and close and ma60 and close < ma60:
        return "🔴 下跌趋势（MA60↓+价<MA60）"
    if ma60_dir == "down":
        return "🔴 MA60↓"
    return "⚪ 震荡过渡"

def _macd_bar_signal(bar, bar_prev):
    if bar is None or bar_prev is None: return "⚪"
    if bar > 0 and bar > bar_prev: return "🟢 BAR扩大"
    if bar > 0 and bar < bar_prev: return "🟡 BAR缩小"
    if bar < 0 and bar < bar_prev: return "🔴 BAR扩大(负)"
    if bar < 0 and bar > bar_prev: return "🟡 BAR缩小(负)"
    return "⚪"

def _kline_shape(open_, high, low, close, atr):
    if any(v is None for v in [open_, high, low, close, atr]): return "—"
    body = abs(close - open_)
    upper = high - max(open_, close)
    lower = min(open_, close) - low
    if body < 0.1 * atr:
        if lower > 3 * body and upper < body: return "🟢 蜻蜓十字星"
        if upper > 3 * body and lower < body: return "🔴 墓碑十字星"
        return "⚪ 十字星"
    if lower > 2.5 * body and upper < body: return "🟢 锤子线"
    if upper > 2.5 * body and lower < body: return "🔴 倒锤子线"
    if upper < 0.1 * body and lower < 0.1 * body:
        return "🟢 光头光脚阳线" if close > open_ else "🔴 光头光脚阴线"
    return "🟢 阳线" if close > open_ else "🔴 阴线"

def _bull_bear_verdict(d):
    bullish, bearish = [], []
    close = d.get("close")
    ma20, ma60 = d.get("ma20"), d.get("ma60")
    ma60_dir = d.get("ma60_dir")
    macd = d.get("macd", {})
    rsi = d.get("rsi14")
    kdj = d.get("kdj", {})
    obv = d.get("obv", {})
    vol_ratio = d.get("vol_ratio")
    dev_ma60 = d.get("dev_ma60")

    if ma60_dir == "up" and close and ma60 and close > ma60:
        bullish.append("MA60↑且价站上MA60 — 牛市结构")
    elif ma60_dir == "up":
        bullish.append("MA60方向↑ — 中期趋势向上")

    bar = macd.get("bar", 0)
    bar_prev = macd.get("bar_prev", 0)
    if bar and bar > 0:
        if bar_prev and bar > bar_prev:
            bullish.append(f"MACD BAR=+{bar:.4f} 扩大 — 动能加速")
        else:
            bullish.append(f"MACD BAR=+{bar:.4f} — 零轴上")

    if close and ma20 and close > ma20:
        bullish.append("价站上MA20 — 短期强势")

    if dev_ma60 is not None and dev_ma60 < -5:
        bullish.append(f"乖离MA60 {dev_ma60:.1f}% — 超卖修复预期")

    if ma60_dir == "down" and close and ma60 and close < ma60:
        bearish.append("MA60↓且价在MA60下 — 熊市结构")
    elif ma60_dir == "down":
        bearish.append("MA60方向↓ — 中期趋势向下")

    if bar and bar < 0:
        bearish.append(f"MACD BAR={bar:.4f} — 零轴下")

    if rsi and rsi > 70:
        bearish.append(f"RSI={rsi} — 超买")
    elif rsi and rsi < 30:
        bullish.append(f"RSI={rsi} — 超卖")

    if kdj.get("overbought"): bearish.append(f"KDJ J={kdj.get('j')} — 超买")
    if kdj.get("oversold"): bullish.append(f"KDJ J={kdj.get('j')} — 超卖")
    if obv.get("bearish_div"): bearish.append("OBV顶背离 — 量价背离")
    if obv.get("bullish_div"): bullish.append("OBV底背离 — 量价背离")
    if vol_ratio is not None and vol_ratio < 0.5:
        bearish.append(f"量比={vol_ratio:.2f} — 极度缩量")

    return bullish, bearish

def _score(bullish, bearish, d):
    b, r = len(bullish), len(bearish)
    ma60_dir = d.get("ma60_dir")
    if b > r + 1 and ma60_dir == "up": return "🟢 偏多"
    if r > b + 1 and ma60_dir == "down": return "🔴 偏空"
    return "🟡 中性偏多" if b >= r else "🟡 中性偏空"

def _triple_signal(macd, kdj, obv):
    macd_ok = macd and macd.get("bar", 0) > 0
    kdj_ok = kdj and kdj.get("k", 0) > kdj.get("d", 0)
    obv_ok = obv and obv.get("obv_above_ma20", False)
    parts = [("🟢" if macd_ok else "🔴"), ("🟢" if kdj_ok else "🔴"), ("🟢" if obv_ok else "🔴")]
    if macd_ok and kdj_ok and obv_ok:
        return "✅ 三指标共振", parts
    missing = []
    if not macd_ok: missing.append("MACD")
    if not kdj_ok: missing.append("KDJ")
    if not obv_ok: missing.append("OBV")
    return f"❌ 不满足 ({', '.join(missing)})", parts

def _currency_prefix(ticker):
    """判断标的是 $ 还是 ¥"""
    us_stocks = {"CANE","VTI","VEA","QQQ","IVV","IAU","BBJP","MUFG","EWY","VNM","FLIN","SMIN","BOTZ"}
    return "$" if ticker in us_stocks else "¥"


def generate(ticker):
    ticker = ticker.strip().upper()
    data = load_market_data()
    d = data.get(ticker)
    if not d:
        print(f"❌ 标的 {ticker} 不在全池中")
        sys.exit(1)

    name = d.get("name", ticker)
    price = d.get("price")
    price_source = d.get("price_source", "?")
    latest_date = d.get("latest_date", "—")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    prefix = _currency_prefix(ticker)

    # 字段
    open_ = d.get("open")
    high = d.get("high")
    low = d.get("low")
    close = d.get("close")
    change_pct = d.get("change_pct")
    vol_ratio = d.get("vol_ratio")
    ma5 = d.get("ma5")
    ma20 = d.get("ma20")
    ma60 = d.get("ma60")
    ma120 = d.get("ma120")
    ma250 = d.get("ma250")
    ma60_dir = d.get("ma60_dir")
    atr14 = d.get("atr14")
    atr_pct = d.get("atr_pct")
    rsi14 = d.get("rsi14")
    macd = d.get("macd", {})
    kdj = d.get("kdj", {})
    obv = d.get("obv", {})
    adx14 = d.get("adx14")

    # ====== 输出 ======
    lines = []
    lines.append(f"# 🔍 {ticker} {name} — K线+七均线+VOL+ATR14 四维组合分析")
    lines.append("")
    lines.append(f"数据窗口: {latest_date} | 现价: {_fmt(price, prefix=prefix)} ({price_source} {now}) | TickFlow latest: {latest_date}")
    lines.append("")

    # ── 段一 ──
    lines.append("## 一、最新日线")
    lines.append("")
    lines.append("| O | H | L | C | 涨跌 | 实体% | 量比 |")
    lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
    lines.append(f"| {_fmt(open_, prefix=prefix)} | {_fmt(high, prefix=prefix)} | {_fmt(low, prefix=prefix)} | {_fmt(close, prefix=prefix)} | {_fmt_chg(change_pct)} | {_fmt(_entity_pct(open_, close), suffix='%')} | {_fmt(vol_ratio, 2)} |")
    lines.append("")
    shape = _kline_shape(open_, high, low, close, atr14)
    lines.append(f"一句话定性：{shape}")
    lines.append("")

    # ── 段二 ──
    lines.append("## 二、均线+指标（精简合并）")
    lines.append("")
    lines.append("### 均线位置")
    lines.append("")
    lines.append("| MA5 | MA20 | MA60 | MA120 | MA250 |")
    lines.append("|:---:|:---:|:---:|:---:|:---:|")
    lines.append(f"| {_fmt(ma5, prefix=prefix)} | {_fmt(ma20, prefix=prefix)} | {_fmt(ma60, prefix=prefix)} | {_fmt(ma120, prefix=prefix)} | {_fmt(ma250, prefix=prefix)} |")
    lines.append("")

    above, below = [], []
    for label, ma_val in [("MA5", ma5), ("MA20", ma20), ("MA60", ma60), ("MA120", ma120), ("MA250", ma250)]:
        if price and ma_val:
            (above if price > ma_val else below).append(f"{label}({_fmt(ma_val, prefix=prefix)})")
    lines.append(f"├── 站上: {', '.join(above) if above else '无'}")
    lines.append(f"├── 跌破: {', '.join(below) if below else '无'}")
    lines.append(f"├── MA60方向: {_ma_dir_emoji(ma60_dir)} | 大周期: {_trend_stage(ma60_dir, close, ma60)}")
    lines.append("")

    lines.append("### 核心指标")
    lines.append("")
    lines.append("| ATR14 | RSI14 | MACD BAR | KDJ | ADX |")
    lines.append("|:---:|:---:|:---:|:---:|:---:|")
    bar_val = macd.get("bar", 0) or 0
    macd_bar_str = _fmt(bar_val, 4, "+" if bar_val >= 0 else "")
    kdj_str = f"K{_fmt(kdj.get('k'),1)}/D{_fmt(kdj.get('d'),1)}/J{_fmt(kdj.get('j'),1)}" if kdj else "—"
    lines.append(f"| {_fmt(atr14, prefix=prefix)} ({_fmt(atr_pct, suffix='%')}) | {_fmt(rsi14)} | {macd_bar_str} | {kdj_str} | {_fmt(adx14)} |")
    lines.append("")

    lines.append("### 近5日量价节奏")
    lines.append("")
    lines.append("⚠️ 近5日逐根K线数据需从 TickFlow SDK 获取（market_data 仅提供最新日线汇总）。")
    lines.append(f"   最新日线形态: {shape}")
    if vol_ratio is not None:
        vol_desc = "放量" if vol_ratio > 1.5 else ("缩量" if vol_ratio < 0.5 else "正常量")
        lines.append(f"   量价配合: {vol_desc}（量比={vol_ratio:.2f}）")
    lines.append("")

    # ── 段三 ──
    lines.append("## 三、MACD动能审计")
    lines.append("")
    lines.append("| DIFF | DEA | BAR | 动能 |")
    lines.append("|:---:|:---:|:---:|:---:|")
    diff = macd.get("diff")
    dea = macd.get("dea")
    bar = macd.get("bar")
    bar_prev = macd.get("bar_prev")
    signal = _macd_bar_signal(bar, bar_prev)
    lines.append(f"| {_fmt(diff, 4)} | {_fmt(dea, 4)} | {_fmt(bar, 4, '+' if (bar or 0) >= 0 else '')} | {signal} |")
    lines.append("")

    # ── 段四 ──
    lines.append("## 四、综合联判")
    lines.append("")
    bullish, bearish = _bull_bear_verdict(d)
    lines.append("├── 🟢 看多（中期）:")
    for b in bullish[:3]:
        lines.append(f"│   ├── {b}")
    if not bullish: lines.append("│   └── 无明显看多信号")
    lines.append("├── 🔴 看空（短期）:")
    for r in bearish[:3]:
        lines.append(f"│   ├── {r}")
    if not bearish: lines.append("│   └── 无明显看空信号")
    s = _score(bullish, bearish, d)
    short = "🟢" if len(bullish) > len(bearish) else "🔴" if len(bearish) > len(bullish) else "🟡"
    lines.append(f"└── 裁决: 中期[{s}] / 短期[{short}]")
    lines.append("")

    # ── 段五 ──
    lines.append("## 五、MACD+KDJ+OBV 三指标合体（辅助确认层）")
    lines.append("")
    triple_result, triple_parts = _triple_signal(macd, kdj, obv)
    lines.append(f"├── MACD: {triple_parts[0]} | KDJ: {triple_parts[1]} | OBV: {triple_parts[2]}")
    lines.append(f"├── 合体: {triple_result}")
    if "✅" in triple_result:
        lines.append("└── 辅助确认信号触发，综合评分自动上调一档（最多一档）")
    else:
        lines.append(f"└── 注意：三指标共振不满足，仅依赖法典路由判定")
    lines.append("")

    # ── 段六 ──
    lines.append("## 六、操作建议")
    lines.append("")
    trend = _trend_stage(ma60_dir, close, ma60)
    short_key = f"MA20={_fmt(ma20, prefix=prefix)}" if ma20 else "—"
    mid_key = f"MA60={_fmt(ma60, prefix=prefix)}" if ma60 else "—"
    risks = []
    if rsi14 and rsi14 > 70: risks.append("RSI超买")
    if kdj.get("overbought"): risks.append("KDJ超买")
    if obv.get("bearish_div"): risks.append("OBV顶背离")
    if vol_ratio is not None and vol_ratio < 0.5: risks.append("极度缩量")
    if atr_pct and atr_pct > 3: risks.append(f"高波动(ATR={atr_pct}%)")
    risk_str = ", ".join(risks) if risks else "无明显风险信号"

    lines.append(f"├── 综合评分: {s} | 大周期: {trend}")
    lines.append(f"├── 短期: 关键支撑/阻力 {short_key}")
    lines.append(f"├── 中期: 关键支撑/阻力 {mid_key}")
    lines.append(f"└── ⚠️ 风险: {risk_str}")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 scripts/tech_report.py <ticker> [--json]")
        print("示例: python3 scripts/tech_report.py 512100")
        print("      python3 scripts/tech_report.py 512100 --json")
        sys.exit(1)

    ticker = sys.argv[1]
    if len(sys.argv) >= 3 and sys.argv[2] == "--json":
        # 复用 JSON 补丁模块
        from tech_report_json import tech_json
        tech_json(ticker)
    else:
        print(generate(ticker))
