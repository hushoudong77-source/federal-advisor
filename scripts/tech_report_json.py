"""
tech_report.py --json 补丁：输出JSON而非Markdown
内联到 tech_report.py main 中作为 --json 分支
"""
import sys, json, subprocess

def load_market_data():
    result = subprocess.run(["python3", "scripts/market_data.py"], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(json.dumps({"error": f"market_data.py failed: {result.stderr}"}))
        sys.exit(1)
    return json.loads(result.stdout)

def tech_json(ticker):
    ticker = ticker.strip().upper()
    data = load_market_data()
    d = data.get(ticker)
    if not d:
        print(json.dumps({"error": f"{ticker} not in pool"}))
        sys.exit(1)

    # 提取所有字段，保持与 market_data 输出结构一致，加衍生字段
    out = {
        "ticker": ticker,
        "name": d.get("name", ticker),
        "price": d.get("price"),
        "price_source": d.get("price_source"),
        "latest_date": d.get("latest_date"),
        "currency": "$" if ticker in {
            "CANE","VTI","VEA","QQQ","IVV","IAU","BBJP","MUFG","EWY","VNM","FLIN","SMIN","BOTZ"
        } else "¥",
        # 日线
        "open": d.get("open"), "high": d.get("high"), "low": d.get("low"), "close": d.get("close"),
        "change_pct": d.get("change_pct"),
        "vol_ratio": d.get("vol_ratio"),
        # 均线
        "ma5": d.get("ma5"), "ma20": d.get("ma20"), "ma60": d.get("ma60"),
        "ma120": d.get("ma120"), "ma250": d.get("ma250"),
        "ma60_dir": d.get("ma60_dir"),
        # 指标
        "atr14": d.get("atr14"), "atr_pct": d.get("atr_pct"),
        "rsi14": d.get("rsi14"),
        "macd": d.get("macd", {}),
        "kdj": d.get("kdj", {}),
        "obv": d.get("obv", {}),
        "adx14": d.get("adx14"),
        "dev_ma60": d.get("dev_ma60"),
        # 衍生
        "kline_shape": _kline_shape(d.get("open"), d.get("high"), d.get("low"), d.get("close"), d.get("atr14")),
        "trend_stage": _trend_stage(d.get("ma60_dir"), d.get("close"), d.get("ma60")),
        "entity_pct": _entity_pct(d.get("open"), d.get("close")),
        "above_ma": _above_below(d, True),
        "below_ma": _above_below(d, False),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


def _entity_pct(o, c):
    if not o or not c or o == 0: return None
    return round(abs(c - o) / o * 100, 2)

def _kline_shape(open_, high, low, close, atr):
    if any(v is None for v in [open_, high, low, close, atr]): return "—"
    body = abs(close - open_)
    upper = high - max(open_, close)
    lower = min(open_, close) - low
    if body < 0.1 * atr:
        if lower > 3 * body and upper < body: return "蜻蜓十字星"
        if upper > 3 * body and lower < body: return "墓碑十字星"
        return "十字星"
    if lower > 2.5 * body and upper < body: return "锤子线"
    if upper > 2.5 * body and lower < body: return "倒锤子线"
    if upper < 0.1 * body and lower < 0.1 * body:
        return "光头光脚阳线" if close > open_ else "光头光脚阴线"
    return "阳线" if close > open_ else "阴线"

def _trend_stage(ma60_dir, close, ma60):
    if ma60_dir == "up" and close and ma60 and close > ma60:
        return "趋势反转"
    if ma60_dir == "up": return "中级反弹"
    if ma60_dir == "down" and close and ma60 and close < ma60:
        return "下跌趋势"
    if ma60_dir == "down": return "MA60↓"
    return "震荡过渡"

def _above_below(d, above):
    price = d.get("price")
    result = []
    for label, key in [("MA5","ma5"),("MA20","ma20"),("MA60","ma60"),("MA120","ma120"),("MA250","ma250")]:
        ma_val = d.get(key)
        if price and ma_val:
            if (above and price > ma_val) or (not above and price < ma_val):
                result.append(label)
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 scripts/tech_report.py <ticker> [--json]")
        sys.exit(1)
    tech_json(sys.argv[1])
