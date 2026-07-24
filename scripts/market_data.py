#!/usr/bin/env python3
"""
联邦投顾 — 全量行情取数工具 V2.0
数据源：腾讯API（A股+美股实时现价）+ Tushare（历史日线+技术指标）
输出：JSON 结构化，key=标的代码，value={price, change_pct, ma20, atr14, macd, ...}

用法：
  python3 scripts/market_data.py              # 全量输出JSON
  python3 scripts/market_data.py --table       # 表格格式输出
  python3 scripts/market_data.py --ticker QQQ  # 单标查询
"""

import urllib.request
import json
import sys
import os
import re
from datetime import datetime, timedelta

# ============================================================
# 全池24标硬编码（真源：AGENT.md 白名单）
# ============================================================
FULL_POOL = {
    # 美股12标
    "VTI":   {"qt": "usVTI",   "type": "us", "tushare": "VTI"},
    "VEA":   {"qt": "usVEA",   "type": "us", "tushare": "VEA"},
    "QQQ":   {"qt": "usQQQ",   "type": "us", "tushare": "QQQ"},
    "IVV":   {"qt": "usIVV",   "type": "us", "tushare": "IVV"},
    "IAU":   {"qt": "usIAU",   "type": "us", "tushare": "IAU"},
    "BBJP":  {"qt": "usBBJP",  "type": "us", "tushare": "BBJP"},
    "MUFG":  {"qt": "usMUFG",  "type": "us", "tushare": "MUFG"},
    "EWY":   {"qt": "usEWY",   "type": "us", "tushare": "EWY"},
    "VNM":   {"qt": "usVNM",   "type": "us", "tushare": "VNM"},
    "FLIN":  {"qt": "usFLIN",  "type": "us", "tushare": "FLIN"},
    "SMIN":  {"qt": "usSMIN",  "type": "us", "tushare": "SMIN"},
    "BOTZ":  {"qt": "usBOTZ",  "type": "us", "tushare": "BOTZ"},
    # CANE（不入池，持仓展示）
    "CANE":  {"qt": "usCANE",  "type": "us", "tushare": "CANE"},
    # A股12标
    "588000": {"qt": "sh588000", "type": "a", "tushare": "588000.SH"},
    "513180": {"qt": "sh513180", "type": "a", "tushare": "513180.SH"},
    "513910": {"qt": "sh513910", "type": "a", "tushare": "513910.SH"},
    "510500": {"qt": "sh510500", "type": "a", "tushare": "510500.SH"},
    "518880": {"qt": "sh518880", "type": "a", "tushare": "518880.SH"},
    "512100": {"qt": "sh512100", "type": "a", "tushare": "512100.SH"},
    "510880": {"qt": "sh510880", "type": "a", "tushare": "510880.SH"},
    "159530": {"qt": "sz159530", "type": "a", "tushare": "159530.SZ"},
    "510300": {"qt": "sh510300", "type": "a", "tushare": "510300.SH"},
    "159915": {"qt": "sz159915", "type": "a", "tushare": "159915.SZ"},
    "513770": {"qt": "sh513770", "type": "a", "tushare": "513770.SH"},
    "159545": {"qt": "sz159545", "type": "a", "tushare": "159545.SZ"},
}

# ============================================================
# 第一层：腾讯API — 全池实时现价（A股+美股统一，一次请求）
# ============================================================
def fetch_tencent_realtime():
    """腾讯API拉取全池实时行情"""
    codes = [v["qt"] for v in FULL_POOL.values()]
    url = "http://qt.gtimg.cn/q=" + ",".join(codes)

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    raw = resp.read().decode("gbk")

    results = {}
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("~")
        if len(parts) < 5:
            continue

        qt_code = parts[0].split("=")[0].replace("v_", "")
        name = parts[1]

        # 美股71字段: [3]=现价 [4]=昨收 [31]=涨跌额 [32]=涨跌幅 [33]=最高 [34]=最低 [6]=成交量
        # A股88字段: [3]=现价 [4]=昨收 [31]=涨跌额 [32]=涨跌幅 [33]=最高 [34]=最低 [6]=成交量
        price = parts[3]
        prev_close = parts[4] if len(parts) > 4 else "N/A"

        if qt_code.startswith("us"):
            change_pct = parts[32] if len(parts) > 32 else "N/A"
            change_amt = parts[31] if len(parts) > 31 else "N/A"
        else:
            change_pct = parts[32] if len(parts) > 32 else "N/A"
            change_amt = parts[31] if len(parts) > 31 else "N/A"

        high = parts[33] if len(parts) > 33 else "N/A"
        low = parts[34] if len(parts) > 34 else "N/A"
        volume = parts[6] if len(parts) > 6 else "0"

        # 映射回联邦代码
        for fed, info in FULL_POOL.items():
            if info["qt"] == qt_code:
                results[fed] = {
                    "name": name,
                    "price": safe_float(price),
                    "prev_close": safe_float(prev_close),
                    "change_pct": safe_float(change_pct),
                    "change_amt": safe_float(change_amt),
                    "high": safe_float(high),
                    "low": safe_float(low),
                    "volume": safe_int(volume),
                }
                break
    return results


# ============================================================
# 第二层：Tushare — 历史日线 + 技术指标自算
# ============================================================
def safe_float(v):
    try:
        return round(float(v), 4)
    except (ValueError, TypeError):
        return None


def safe_int(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


def calc_ma(close_series, period):
    """简单移动平均"""
    if len(close_series) < period:
        return None
    return round(float(close_series[-period:].mean()), 4)


def calc_ema(close_series, period):
    """指数移动平均"""
    if len(close_series) < period:
        return None
    return round(float(close_series.ewm(span=period, adjust=False).mean().iloc[-1]), 4)


def calc_atr(high, low, close, period=14):
    """14日平均真实波幅"""
    if len(close) < period + 1:
        return None
    tr_list = []
    for i in range(1, len(close)):
        tr = max(
            high.iloc[i] - low.iloc[i],
            abs(high.iloc[i] - close.iloc[i - 1]),
            abs(low.iloc[i] - close.iloc[i - 1]),
        )
        tr_list.append(tr)
    import pandas as pd
    tr_series = pd.Series(tr_list, index=close.index[1:])
    return round(float(tr_series.rolling(period).mean().iloc[-1]), 4)


def calc_macd(close_series):
    """MACD: DIFF(EMA12-EMA26), DEA(EMA9_DIFF), BAR=2*(DIFF-DEA)"""
    if len(close_series) < 35:
        return {"diff": None, "dea": None, "bar": None}
    ema12 = close_series.ewm(span=12, adjust=False).mean()
    ema26 = close_series.ewm(span=26, adjust=False).mean()
    diff = ema12 - ema26
    dea = diff.ewm(span=9, adjust=False).mean()
    bar = 2 * (diff - dea)
    return {
        "diff": round(float(diff.iloc[-1]), 4),
        "dea": round(float(dea.iloc[-1]), 4),
        "bar": round(float(bar.iloc[-1]), 4),
        "bar_prev": round(float(bar.iloc[-2]), 4) if len(bar) >= 2 else None,
    }


def calc_rsi(close_series, period=14):
    """14日RSI"""
    if len(close_series) < period + 1:
        return None
    delta = close_series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def calc_h20(close_series):
    """20日内最高收盘价"""
    if len(close_series) < 20:
        return None
    return round(float(close_series.iloc[-20:].max()), 4)


def calc_vol_ma20(volume_series):
    """20日均量"""
    if len(volume_series) < 20:
        return None
    return round(float(volume_series.rolling(20).mean().iloc[-1]), 0)


def fetch_tushare_indicators(ticker_list=None):
    """Tushare拉取日线 + 自算全部技术指标"""
    import tushare as ts
    import pandas as pd
    pro = ts.pro_api()

    if ticker_list is None:
        ticker_list = [(fed, info["tushare"], info["type"]) for fed, info in FULL_POOL.items()
                       if info["tushare"]]

    results = {}
    fetch_log = {}

    for fed, ts_code, mkt in ticker_list:
        try:
            start_date = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")

            if mkt == "us":
                df = pro.us_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            else:
                df = pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

            if df is None or len(df) == 0:
                fetch_log[fed] = f"empty: {ts_code}"
                results[fed] = {"error": "tushare_empty", "ts_code": ts_code}
                continue

            df = df.sort_values("trade_date").reset_index(drop=True)
            close = df["close"]
            high = df["high"] if "high" in df.columns else close
            low = df["low"] if "low" in df.columns else close
            volume = df["vol"] if "vol" in df.columns else pd.Series([0] * len(df))

            latest_date = df["trade_date"].iloc[-1]

            # MA 系列
            ma5 = calc_ma(close, 5)
            ma20 = calc_ma(close, 20)
            ma40 = calc_ma(close, 40)
            ma60 = calc_ma(close, 60)
            ma120 = calc_ma(close, 120)
            ma150 = calc_ma(close, 150)
            ma250 = calc_ma(close, 250) if len(close) >= 250 else None

            # EMA 系列
            ema50 = calc_ema(close, 50)
            ema150 = calc_ema(close, 150)

            # 乖离率
            dev_ma20 = round((close.iloc[-1] / ma20 - 1) * 100, 2) if ma20 and ma20 > 0 else None
            dev_ma40 = round((close.iloc[-1] / ma40 - 1) * 100, 2) if ma40 and ma40 > 0 else None
            dev_ma60 = round((close.iloc[-1] / ma60 - 1) * 100, 2) if ma60 and ma60 > 0 else None
            dev_ma150 = round((close.iloc[-1] / ma150 - 1) * 100, 2) if ma150 and ma150 > 0 else None

            # 方向判定
            ma60_dir = "up" if ma60 and len(close) >= 20 and ma60 > calc_ma(close.iloc[:-20], 60) else "down" if ma60 else None

            # ATR + RSI + MACD + H20
            atr14 = calc_atr(high, low, close)
            atr_pct = round(atr14 / close.iloc[-1] * 100, 2) if atr14 and close.iloc[-1] > 0 else None
            rsi14 = calc_rsi(close)
            macd = calc_macd(close)
            h20 = calc_h20(close)
            vol_ma20 = calc_vol_ma20(volume)

            # 今日量比
            vol_ratio = round(volume.iloc[-1] / vol_ma20, 2) if vol_ma20 and vol_ma20 > 0 else None

            # ADX14
            adx_val = None
            if len(close) >= 28:
                try:
                    import numpy as np
                    tr = pd.DataFrame({
                        "tr": np.maximum(
                            high - low,
                            np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1)))
                        )
                    })
                    atr14_adx = tr["tr"].rolling(14).mean()

                    up_move = high.diff()
                    down_move = -low.diff()
                    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
                    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

                    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / atr14_adx
                    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / atr14_adx
                    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
                    adx_val = round(float(dx.rolling(14).mean().iloc[-1]), 2)
                except Exception:
                    pass

            # 20日回撤（用于SMIN/VNM/EWY轨道二）
            if len(close) >= 20:
                drawdown_20d = round((close.iloc[-1] / close.iloc[-20] - 1) * 100, 2)
            else:
                drawdown_20d = None

            results[fed] = {
                "latest_date": latest_date,
                "rows": len(df),
                "close": round(float(close.iloc[-1]), 4),
                # MA
                "ma5": ma5, "ma20": ma20, "ma40": ma40,
                "ma60": ma60, "ma120": ma120, "ma150": ma150, "ma250": ma250,
                # EMA
                "ema50": ema50, "ema150": ema150,
                # 乖离率
                "dev_ma20": dev_ma20, "dev_ma40": dev_ma40,
                "dev_ma60": dev_ma60, "dev_ma150": dev_ma150,
                # 方向
                "ma60_dir": ma60_dir,
                # 波动率
                "atr14": atr14, "atr_pct": atr_pct,
                # 动量
                "rsi14": rsi14,
                "macd": macd,
                # 极值
                "h20": h20,
                # 量
                "vol_ma20": vol_ma20, "vol_ratio": vol_ratio,
                # ADX
                "adx14": adx_val,
                # 轨道二
                "drawdown_20d": drawdown_20d,
            }

            fetch_log[fed] = f"ok: {len(df)} rows, latest={latest_date}"

        except Exception as e:
            fetch_log[fed] = f"error: {e}"
            results[fed] = {"error": str(e), "ts_code": ts_code}

    results["_log"] = fetch_log
    return results


# ============================================================
# 第三层：合并输出
# ============================================================
def fetch_all():
    """一键拉取全量：腾讯实时 + Tushare技术指标"""
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "realtime": fetch_tencent_realtime(),
        "indicators": fetch_tushare_indicators(),
    }

    # 合并：将腾讯实时价覆写到 indicators 的现价字段
    merged = {}
    for ticker in FULL_POOL:
        entry = {}
        # 腾讯实时
        rt = result["realtime"].get(ticker, {})
        entry["price"] = rt.get("price")
        entry["change_pct"] = rt.get("change_pct")
        entry["high"] = rt.get("high")
        entry["low"] = rt.get("low")
        entry["volume"] = rt.get("volume")
        entry["name"] = rt.get("name", "")
        entry["price_source"] = "tencent"

        # Tushare 技术指标
        ind = result["indicators"].get(ticker, {})
        if "error" not in ind:
            entry.update({k: v for k, v in ind.items() if k != "close" and k != "_log"})
            entry["tushare_latest"] = ind.get("latest_date")

        entry["type"] = FULL_POOL[ticker]["type"]
        merged[ticker] = entry

    # 附加拉取日志
    merged["_realtime_ts"] = result["timestamp"]
    merged["_tushare_log"] = result["indicators"].get("_log", {})
    return merged


# ============================================================
# 输出格式
# ============================================================
def output_table(data):
    """表格格式输出"""
    print(f"\n{'='*120}")
    print(f"  联邦投顾 全量行情 — {data.get('_realtime_ts', '')}")
    print(f"{'='*120}")
    print(f"{'标的':8s} | {'名称':16s} | {'现价':>10s} | {'涨跌':>8s} | {'MA20':>10s} | {'MA60':>10s} | {'ATR14':>8s} | {'MACD BAR':>9s} | {'RSI':>5s} | {'方向':4s}")
    print(f"{'-'*120}")

    # 先美股后A股
    us_tickers = [t for t, v in FULL_POOL.items() if v["type"] == "us" and t != "CANE"]
    a_tickers = [t for t, v in FULL_POOL.items() if v["type"] == "a"]

    for group, tickers in [("美股", us_tickers), ("A股", a_tickers)]:
        print(f"\n--- {group} ---")
        for t in tickers:
            d = data.get(t, {})
            price = d.get("price", "N/A")
            chg = d.get("change_pct", "N/A")
            ma20 = d.get("ma20", "N/A")
            ma60 = d.get("ma60", "N/A")
            atr = d.get("atr14", "N/A")
            macd_bar = d.get("macd", {}).get("bar", "N/A")
            rsi = d.get("rsi14", "N/A")
            ma60_dir = d.get("ma60_dir", "N/A")

            p_str = f"{price:>10.3f}" if isinstance(price, (int, float)) else f"{price:>10s}"
            chg_str = f"{chg:>+7.2f}%" if isinstance(chg, (int, float)) else f"{chg:>8s}"
            ma20_str = f"{ma20:>10.3f}" if isinstance(ma20, (int, float)) else f"{ma20:>10s}"
            ma60_str = f"{ma60:>10.3f}" if isinstance(ma60, (int, float)) else f"{ma60:>10s}"
            atr_str = f"{atr:>8.3f}" if isinstance(atr, (int, float)) else f"{atr:>8s}"
            macd_str = f"{macd_bar:>+9.4f}" if isinstance(macd_bar, (int, float)) else f"{macd_bar:>9s}"
            rsi_str = f"{rsi:>5.1f}" if isinstance(rsi, (int, float)) else f"{rsi:>5s}"

            print(f"{t:8s} | {d.get('name', ''):16s} | {p_str} | {chg_str} | {ma20_str} | {ma60_str} | {atr_str} | {macd_str} | {rsi_str} | {ma60_dir:4s}")

    # Tushare拉取日志
    print(f"\n--- Tushare拉取日志 ---")
    log = data.get("_tushare_log", {})
    for t, status in sorted(log.items()):
        print(f"  {t:8s}: {status}")


if __name__ == "__main__":
    import sys
    if "--table" in sys.argv:
        # 先输出Tushare探测
        print("  ⏳ 拉取Tushare四接口探测...")
        import tushare as ts
        pro = ts.pro_api()
        try:
            fd = pro.fund_daily(ts_code='513910.SH', start_date='20260720', end_date='20260724')
            print(f"     fund_daily: {len(fd)}行 ✅" if fd is not None and len(fd) > 0 else "     fund_daily: ❌")
        except Exception as e:
            print(f"     fund_daily: ❌ {e}")
        try:
            usd = pro.us_daily(ts_code='QQQ', start_date='20260720', end_date='20260724')
            print(f"     us_daily: {len(usd)}行 ✅" if usd is not None and len(usd) > 0 else "     us_daily: ❌")
        except Exception as e:
            print(f"     us_daily: ❌ {e}")
        try:
            sh = pro.shibor(start_date='20260724', end_date='20260724')
            print(f"     shibor: {len(sh)}行 ✅" if sh is not None and len(sh) > 0 else "     shibor: ❌")
        except Exception as e:
            print(f"     shibor: ❌ {e}")
        try:
            ty = pro.us_tycr(start_date='20260724', end_date='20260724')
            print(f"     us_tycr: {len(ty)}行 ✅" if ty is not None and len(ty) > 0 else "     us_tycr: ❌")
        except Exception as e:
            print(f"     us_tycr: ❌ {e}")

        print("\n  ⏳ 拉取腾讯实时行情...")
        data = fetch_all()
        output_table(data)
    elif "--ticker" in sys.argv:
        idx = sys.argv.index("--ticker")
        ticker = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if ticker:
            data = fetch_all()
            entry = data.get(ticker, {})
            print(json.dumps({ticker: entry}, ensure_ascii=False, indent=2))
        else:
            print("Usage: market_data.py --ticker <CODE>")
    else:
        data = fetch_all()
        print(json.dumps(data, ensure_ascii=False, indent=2))
