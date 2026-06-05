#!/usr/bin/env python3
"""
calc_all_indicators.py V1.0 — Tushare日线→全量技术指标一体化计算
联邦投顾规则M.1 新鲜度强制自检 执行脚本

用法:
    python scripts/calc_all_indicators.py --all              # 全池17标
    python scripts/calc_all_indicators.py --all --json        # JSON输出
    python scripts/calc_all_indicators.py 513910 588000       # 指定标的
"""

import os, sys, json, argparse
import numpy as np
import pandas as pd
import tushare as ts

# ── 配置 ──────────────────────────────────────────────
pro = ts.pro_api(os.environ.get("TUSHARE_TOKEN", ""))
LOOKBACK = 400  # 往回拉400条日线（覆盖150EMA+安全余量）

# 全池17标
FULL_POOL = {
    # 美股 (11)
    "QQQ":     {"ts": "QQQ",      "market": "us"},
    "IVV":     {"ts": "IVV",      "market": "us"},
    "IAU":     {"ts": "IAU",      "market": "us"},
    "BBJP":    {"ts": "BBJP",     "market": "us"},
    "MUFG":    {"ts": "MUFG",     "market": "us"},
    "EWY":     {"ts": "EWY",      "market": "us"},
    "VNM":     {"ts": "VNM",      "market": "us"},
    "FLIN":    {"ts": "FLIN",     "market": "us"},
    "SMIN":    {"ts": "SMIN",     "market": "us"},
    "VEA":     {"ts": "VEA",      "market": "us"},
    "VTI":     {"ts": "VTI",      "market": "us"},
    # A股 (6)
    "588000":  {"ts": "588000.SH", "market": "cn"},
    "513180":  {"ts": "513180.SH", "market": "cn"},
    "513910":  {"ts": "513910.SH", "market": "cn"},
    "159302":  {"ts": "159302.SZ", "market": "cn"},
    "510500":  {"ts": "510500.SH", "market": "cn"},
    "518880":  {"ts": "518880.SH", "market": "cn"},
}


# ── 技术指标计算函数 ──────────────────────────────────

def calc_ma(series, window):
    if len(series) < window:
        return None, None, None
    val = series.iloc[-window:].mean()
    start_idx = max(0, len(series) - window)
    return round(float(val), 4), str(series.index[start_idx].date()), str(series.index[-1].date())


def calc_ema(series, window):
    if len(series) < window:
        return None, None, None
    ema = series.ewm(span=window, adjust=False).mean()
    return round(float(ema.iloc[-1]), 4), str(series.index[0].date()), str(series.index[-1].date())


def calc_atr(df, window=14):
    if len(df) < window + 1:
        return None, None, None
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.iloc[-window:].mean()
    return round(float(atr), 4), str(tr.index[-window].date()), str(tr.index[-1].date())


def calc_macd(series, fast=12, slow=26, signal=9):
    if len(series) < slow + signal:
        return None, None, None, None, None
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    bar = 2 * (dif - dea)
    return (
        round(float(dif.iloc[-1]), 4),
        round(float(dea.iloc[-1]), 4),
        round(float(bar.iloc[-1]), 4),
        str(series.index[-slow - signal + 1].date()),
        str(series.index[-1].date())
    )


def calc_rsi(series, window=14):
    if len(series) < window + 1:
        return None, None, None
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2), str(rsi.index[-window].date()), str(rsi.index[-1].date())


def calc_h20(high_series):
    if len(high_series) < 20:
        return None, None, None
    val = high_series.iloc[-20:].max()
    return round(float(val), 4), str(high_series.index[-20].date()), str(high_series.index[-1].date())


def calc_deviation(price, ma_val):
    if price is None or ma_val is None or ma_val == 0:
        return None
    return round((price - ma_val) / ma_val * 100, 2)


# ── 主计算函数 ────────────────────────────────────────

def compute_all(symbol, info):
    ts_code = info["ts"]
    market = info["market"]

    try:
        if market == "us":
            df = pro.us_daily(ts_code=ts_code, start_date="20240101", end_date="20991231")
        else:
            df = pro.fund_daily(ts_code=ts_code, start_date="20240101", end_date="20991231")
    except Exception as e:
        return {"symbol": symbol, "error": f"Tushare拉取失败: {e}"}

    if df is None or len(df) == 0:
        return {"symbol": symbol, "error": "Tushare返回空数据"}

    df = df.sort_values("trade_date").reset_index(drop=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df.set_index("trade_date", inplace=True)

    close = df["close"]
    latest_date = str(df.index[-1].date())
    latest_close = round(float(close.iloc[-1]), 4)

    result = {
        "symbol": symbol,
        "ts_code": ts_code,
        "market": market,
        "latest_date": latest_date,
        "close": latest_close,
        "rows": len(df),
        "indicators": {}
    }

    # MA系列
    for w in [20, 30, 40, 50, 60, 150]:
        val, w_start, w_end = calc_ma(close, w)
        if val is not None:
            dev = calc_deviation(latest_close, val)
            result["indicators"][f"MA{w}"] = {
                "value": val, "deviation_pct": dev,
                "window": [w_start, w_end], "freshness": w_end
            }

    # EMA系列
    for w in [30, 50, 150]:
        val, w_start, w_end = calc_ema(close, w)
        if val is not None:
            dev = calc_deviation(latest_close, val)
            result["indicators"][f"EMA{w}"] = {
                "value": val, "deviation_pct": dev,
                "window": [w_start, w_end], "freshness": w_end
            }

    # ATR14
    atr_val, atr_start, atr_end = calc_atr(df)
    if atr_val is not None:
        result["indicators"]["ATR14"] = {
            "value": atr_val, "window": [atr_start, atr_end], "freshness": atr_end
        }

    # MACD
    dif, dea, bar, macd_start, macd_end = calc_macd(close)
    if dif is not None:
        result["indicators"]["MACD"] = {
            "DIF": dif, "DEA": dea, "BAR": bar,
            "window": [macd_start, macd_end], "freshness": macd_end
        }

    # RSI14
    rsi_val, rsi_start, rsi_end = calc_rsi(close)
    if rsi_val is not None:
        result["indicators"]["RSI14"] = {
            "value": rsi_val, "window": [rsi_start, rsi_end], "freshness": rsi_end
        }

    # H20
    h20_val, h20_start, h20_end = calc_h20(df["high"])
    if h20_val is not None:
        result["indicators"]["H20"] = {
            "value": h20_val, "window": [h20_start, h20_end], "freshness": h20_end
        }

    return result


def compute_pool(symbols=None):
    targets = {}
    if symbols:
        for s in symbols:
            if s in FULL_POOL:
                targets[s] = FULL_POOL[s]
            else:
                print(f"WARNING: {s} not in pool, skipping", file=sys.stderr)
    else:
        targets = FULL_POOL

    results = []
    errors = 0
    for sym, info in targets.items():
        r = compute_all(sym, info)
        if "error" in r:
            errors += 1
        results.append(r)
    return results, errors


# ── 输出 ──────────────────────────────────────────────

def print_text_report(results):
    print(f"{'='*80}")
    print(f"  联邦投顾 — 全池技术指标新鲜度报告")
    print(f"  计算时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")

    for r in results:
        if "error" in r:
            print(f"  X {r['symbol']}: {r['error']}\n")
            continue

        ind = r["indicators"]
        print(f"{'─'*60}")
        print(f"  {r['symbol']} ({r['ts_code']}) | close={r['close']} | latest={r['latest_date']} | rows={r['rows']}")
        print(f"{'─'*60}")

        ma_keys = sorted([k for k in ind if k.startswith("MA") and k != "MACD"], key=lambda x: int(x[2:]))
        for k in ma_keys:
            v = ind[k]
            print(f"  {k:6s}: {v['value']:>10.4f}  dev={str(v.get('deviation_pct','-')):>7}%  [{v['window'][0]}..{v['window'][1]}]")

        ema_keys = sorted([k for k in ind if k.startswith("EMA")], key=lambda x: int(x[3:]))
        for k in ema_keys:
            v = ind[k]
            print(f"  {k:6s}: {v['value']:>10.4f}  dev={str(v.get('deviation_pct','-')):>7}%  [{v['window'][0]}..{v['window'][1]}]")

        for k in ["ATR14", "MACD", "RSI14", "H20"]:
            if k not in ind:
                continue
            v = ind[k]
            if k == "MACD":
                print(f"  {k:6s}: DIF={v['DIF']:>10.4f}  DEA={v['DEA']:>10.4f}  BAR={v['BAR']:>10.4f}  [{v['window'][0]}..{v['window'][1]}]")
            else:
                print(f"  {k:6s}: {v['value']:>10.4f}  [{v['window'][0]}..{v['window'][1]}]")

        freshness_dates = set()
        for v in ind.values():
            freshness_dates.add(v["freshness"])
        print(f"  fresh: {'OK' if len(freshness_dates)==1 else 'MULTI'}: {sorted(freshness_dates)}")
        print()

    ok = sum(1 for r in results if "error" not in r)
    err = sum(1 for r in results if "error" in r)
    print(f"{'='*80}")
    print(f"  Total: {ok}/{ok+err} OK, {err} errors")
    print(f"{'='*80}")


def main():
    parser = argparse.ArgumentParser(description="Full pool technical indicator calculator")
    parser.add_argument("symbols", nargs="*", help="Symbol codes (omit for --all)")
    parser.add_argument("--all", action="store_true", help="All 17 symbols")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.all or not args.symbols:
        symbols = None
    else:
        symbols = args.symbols

    results, errors = compute_pool(symbols)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    else:
        print_text_report(results)

    sys.exit(errors)


if __name__ == "__main__":
    main()
