#!/usr/bin/env python3
"""
scan_engine.py V1.0 — 全池扫描引擎（2026-06-27 焊入）
联邦投顾 /扫描 /扫描美股 /扫描A股 的数据底座

功能：
  1. Tushare 全池日线拉取 → 自算全部技术指标（规则M.1新鲜度强制）
  2. 腾讯API 实时行情覆写现价（规则G）
  3. 博弈态 D2(ADX中位数) + D3(成交量比值中位数) 全量计算
  4. 输出标准化JSON → 模型直接用于填充扫描模板

用法:
  python scripts/scan_engine.py                          # 全池20标
  python scripts/scan_engine.py --scope us               # 仅美股12标
  python scripts/scan_engine.py --scope cn               # 仅A股8标
  python scripts/scan_engine.py --no-realtime            # 跳过腾讯实时（调试用）
  python scripts/scan_engine.py --json                   # JSON输出（默认）
  python scripts/scan_engine.py --summary                # 人类可读摘要输出
"""

import os, sys, json, argparse, urllib.request, re
import numpy as np
import pandas as pd
from datetime import datetime

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
LOOKBACK_DAYS = 400  # 往回拉400条日线（覆盖150EMA+安全余量）

# ── 全池20标硬编码白名单（唯一真源，与AGENT.md §直觉拦截协议V2.1同步）──
FULL_POOL = {
    # 美股ETF (12)
    "QQQ":    {"ts": "QQQ",    "market": "us", "route": "offense",   "name": "纳指100ETF"},
    "IVV":    {"ts": "IVV",    "market": "us", "route": "offense",   "name": "标普500ETF-iShares"},
    "IAU":    {"ts": "IAU",    "market": "us", "route": "goldshield","name": "黄金信托ETF-iShares"},
    "BBJP":   {"ts": "BBJP",   "market": "us", "route": "counter",   "name": "JPMorgan日本ETF"},
    "MUFG":   {"ts": "MUFG",   "market": "us", "route": "offense",   "name": "三菱日联金融"},
    "EWY":    {"ts": "EWY",    "market": "us", "route": "momentum",  "name": "韩国ETF-iShares MSCI"},
    "VNM":    {"ts": "VNM",    "market": "us", "route": "counter",   "name": "越南ETF-VanEck"},
    "FLIN":   {"ts": "FLIN",   "market": "us", "route": "momentum",  "name": "印度ETF-Franklin"},
    "SMIN":   {"ts": "SMIN",   "market": "us", "route": "momentum",  "name": "印度小盘股ETF-iShares"},
    "VEA":    {"ts": "VEA",    "market": "us", "route": "fixed",     "name": "发达市场ETF-Vanguard"},
    "VTI":    {"ts": "VTI",    "market": "us", "route": "fixed",     "name": "全美市场ETF-Vanguard"},
    "BOTZ":   {"ts": "BOTZ",   "market": "us", "route": "offense",   "name": "机器人AI ETF-Global X"},
    # A股ETF (8)
    "588000": {"ts": "588000.SH", "market": "cn", "route": "counter", "name": "科创50ETF华夏"},
    "513180": {"ts": "513180.SH", "market": "cn", "route": "offense", "name": "恒生科技ETF华夏"},
    "513910": {"ts": "513910.SH", "market": "cn", "route": "counter", "name": "港股通央企红利ETF华夏"},
    "510500": {"ts": "510500.SH", "market": "cn", "route": "counter", "name": "中证500ETF南方"},
    "518880": {"ts": "518880.SH", "market": "cn", "route": "goldshield","name":"黄金ETF华安"},
    "512100": {"ts": "512100.SH", "market": "cn", "route": "counter", "name": "中证1000ETF南方"},
    "510880": {"ts": "510880.SH", "market": "cn", "route": "counter", "name": "红利ETF易方达"},
    "159530": {"ts": "159530.SZ", "market": "cn", "route": "counter", "name": "机器人ETF易方达"},
}

# ── 腾讯API映射（与qt_realtime.py同步）──
QT_SYMBOLS = {
    "513910": "sh513910", "588000": "sh588000", "512100": "sh512100",
    "510880": "sh510880", "510500": "sh510500", "513180": "sh513180",
    "518880": "sh518880", "511880": "sh511880", "159530": "sz159530",
    "159302": "sz159302", "159545": "sz159545",
    "BBJP": "usBBJP", "EWY": "usEWY", "FLIN": "usFLIN", "IAU": "usIAU",
    "IVV": "usIVV", "MUFG": "usMUFG", "QQQ": "usQQQ", "SMIN": "usSMIN",
    "VEA": "usVEA", "VNM": "usVNM", "VTI": "usVTI", "BOTZ": "usBOTZ",
    "CANE": "usCANE",
}


# ══════════════════════════════════════════════════════════════
# 技术指标计算函数
# ══════════════════════════════════════════════════════════════

def calc_ma(series, window):
    if len(series) < window:
        return None, None, None
    val = series.iloc[-window:].mean()
    start_date = str(series.index[-window].date())
    end_date = str(series.index[-1].date())
    return round(float(val), 4), start_date, end_date

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

def calc_adx(df, window=14):
    """ADX14 全量计算"""
    if len(df) < window * 2:
        return None, None, None
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=window).mean()
    up = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    plus_di = 100 * (plus_dm.rolling(window=window).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=window).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.rolling(window=window).mean()
    return (
        round(float(adx.iloc[-1]), 2),
        round(float(plus_di.iloc[-1]), 2),
        round(float(minus_di.iloc[-1]), 2),
        str(adx.index[-window].date()),
        str(adx.index[-1].date())
    )

def calc_volume_ratio(df, window=20):
    """成交量比值 = 当日量 / 20日均量"""
    if len(df) < window + 1:
        return None, None
    vol = df["vol"]
    ma20 = vol.rolling(window=window).mean()
    ratio = vol.iloc[-1] / ma20.iloc[-1] if ma20.iloc[-1] > 0 else None
    return round(float(ratio), 3) if ratio is not None else None, round(float(ma20.iloc[-1]), 0)

def calc_volume_shrink_days(df, window=20):
    """连续缩量天数（成交量 < 20日均量的80%）"""
    if len(df) < window + 1:
        return 0
    vol = df["vol"]
    ma20 = vol.rolling(window=window).mean()
    shrink = vol < ma20 * 0.8
    days = 0
    for i in range(len(shrink) - 1, -1, -1):
        if shrink.iloc[i]:
            days += 1
        else:
            break
    return days

def calc_deviation(price, ma_val):
    if price is None or ma_val is None or ma_val == 0:
        return None
    return round((price - ma_val) / ma_val * 100, 2)

def calc_ma_direction(series, window, lookback=5):
    """MA方向：近lookback日MA值的斜率方向"""
    if len(series) < window + lookback:
        return "→"
    ma = series.rolling(window=window).mean()
    recent = ma.iloc[-lookback:]
    if len(recent) < 2:
        return "→"
    # 简单判定：最后值 vs 5日前值
    if recent.iloc[-1] > recent.iloc[0] * 1.001:
        return "↑"
    elif recent.iloc[-1] < recent.iloc[0] * 0.999:
        return "↓"
    else:
        return "→"


# ══════════════════════════════════════════════════════════════
# 腾讯实时行情拉取
# ══════════════════════════════════════════════════════════════

def fetch_qt_realtime(symbols_subset=None):
    """拉取腾讯实时行情，返回 {symbol: {price, prev_close, pct}}"""
    if symbols_subset:
        codes = [QT_SYMBOLS[s] for s in symbols_subset if s in QT_SYMBOLS]
    else:
        codes = list(set(QT_SYMBOLS.values()))
    
    if not codes:
        return {}
    
    url = f"http://qt.gtimg.cn/q={','.join(codes)}"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'http://finance.qq.com'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('gbk', errors='replace')
    except Exception as e:
        return {"_error": f"腾讯API请求失败: {e}"}
    
    qt_to_symbol = {v: k for k, v in QT_SYMBOLS.items()}
    result = {}
    
    for line in raw.strip().split('\n'):
        if '=' not in line:
            continue
        match = re.match(r'v_(\S+)="(.*)"', line.strip())
        if not match:
            continue
        qt_code = match.group(1)
        fields = match.group(2).split('~')
        if len(fields) < 5:
            continue
        
        symbol = qt_to_symbol.get(qt_code)
        if symbol is None:
            continue
        
        try:
            price = float(fields[3]) if fields[3] else None
        except ValueError:
            price = None
        try:
            prev_close = float(fields[4]) if fields[4] else None
        except ValueError:
            prev_close = None
        
        pct_str = fields[32] if len(fields) > 32 else ''
        try:
            pct = float(pct_str.replace('%', '')) if pct_str else None
        except (ValueError, TypeError):
            pct = None
        
        result[symbol] = {
            "price": price,
            "prev_close": prev_close,
            "pct": pct
        }
    
    return result


# ══════════════════════════════════════════════════════════════
# 单标全量计算
# ══════════════════════════════════════════════════════════════

def compute_one(symbol, info, pro):
    """计算单标全部技术指标"""
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
    
    ind = {}
    
    # MA系列 (5/20/30/40/50/60/150)
    for w in [5, 20, 30, 40, 50, 60, 150]:
        val, w_start, w_end = calc_ma(close, w)
        if val is not None:
            dev = calc_deviation(latest_close, val)
            direction = calc_ma_direction(close, w)
            ind[f"MA{w}"] = {
                "value": val, "deviation_pct": dev, "direction": direction,
                "window": [w_start, w_end], "freshness": w_end
            }
    
    # EMA系列 (30/50/150)
    for w in [30, 50, 150]:
        val, w_start, w_end = calc_ema(close, w)
        if val is not None:
            dev = calc_deviation(latest_close, val)
            direction = calc_ma_direction(close, w)
            ind[f"EMA{w}"] = {
                "value": val, "deviation_pct": dev, "direction": direction,
                "window": [w_start, w_end], "freshness": w_end
            }
    
    # ATR14
    atr_val, atr_start, atr_end = calc_atr(df)
    if atr_val is not None:
        ind["ATR14"] = {
            "value": atr_val, "window": [atr_start, atr_end], "freshness": atr_end
        }
    
    # MACD
    dif, dea, bar, macd_start, macd_end = calc_macd(close)
    if dif is not None:
        # 判断金叉/死叉
        ema_fast = close.ewm(span=12, adjust=False).mean()
        ema_slow = close.ewm(span=26, adjust=False).mean()
        dif_full = ema_fast - ema_slow
        dea_full = dif_full.ewm(span=9, adjust=False).mean()
        prev_dif = float(dif_full.iloc[-2]) if len(dif_full) >= 2 else dif
        prev_dea = float(dea_full.iloc[-2]) if len(dea_full) >= 2 else dea
        cross = "金叉🟢" if (prev_dif <= prev_dea and dif > dea) else ("死叉🔴" if (prev_dif >= prev_dea and dif < dea) else "持续")
        
        ind["MACD"] = {
            "DIF": dif, "DEA": dea, "BAR": bar, "cross": cross,
            "window": [macd_start, macd_end], "freshness": macd_end
        }
    
    # RSI14
    rsi_val, rsi_start, rsi_end = calc_rsi(close)
    if rsi_val is not None:
        ind["RSI14"] = {
            "value": rsi_val, "window": [rsi_start, rsi_end], "freshness": rsi_end
        }
    
    # H20
    h20_val, h20_start, h20_end = calc_h20(df["high"])
    if h20_val is not None:
        ind["H20"] = {
            "value": h20_val, "window": [h20_start, h20_end], "freshness": h20_end
        }
    
    # ADX14
    adx_val, plus_di, minus_di, adx_start, adx_end = calc_adx(df)
    if adx_val is not None:
        ind["ADX14"] = {
            "value": adx_val, "plus_di": plus_di, "minus_di": minus_di,
            "window": [adx_start, adx_end], "freshness": adx_end
        }
    
    # 成交量比值
    vol_ratio, vol_ma20 = calc_volume_ratio(df)
    if vol_ratio is not None:
        ind["VOL_RATIO"] = {
            "value": vol_ratio, "vol_ma20": vol_ma20
        }
        ind["VOL_SHRINK_DAYS"] = {
            "value": calc_volume_shrink_days(df)
        }
    
    # 新鲜度统一检查
    freshness_dates = set()
    for v in ind.values():
        if "freshness" in v:
            freshness_dates.add(v["freshness"])
    
    result = {
        "symbol": symbol,
        "ts_code": ts_code,
        "market": market,
        "route": info["route"],
        "name": info["name"],
        "latest_date": latest_date,
        "close_tushare": latest_close,
        "rows": len(df),
        "indicators": ind,
        "freshness_ok": len(freshness_dates) <= 1,
        "freshness_dates": sorted(freshness_dates)
    }
    
    return result


# ══════════════════════════════════════════════════════════════
# 博弈态 D2/D3 全池聚合计算
# ══════════════════════════════════════════════════════════════

def compute_game_state_d2d3(results):
    """从全池结果中计算ADX中位数和成交量比值中位数"""
    adx_values = []
    vol_ratios = []
    vol_shrink_days_list = []
    
    for r in results:
        if "error" in r:
            continue
        ind = r.get("indicators", {})
        if "ADX14" in ind:
            adx_values.append(ind["ADX14"]["value"])
        if "VOL_RATIO" in ind:
            vol_ratios.append(ind["VOL_RATIO"]["value"])
        if "VOL_SHRINK_DAYS" in ind:
            vol_shrink_days_list.append(ind["VOL_SHRINK_DAYS"]["value"])
    
    n = len(adx_values)
    if n == 0:
        return {"error": "无有效ADX数据"}
    
    adx_sorted = sorted(adx_values)
    adx_median = adx_sorted[n // 2] if n % 2 == 1 else (adx_sorted[n // 2 - 1] + adx_sorted[n // 2]) / 2
    
    vol_sorted = sorted(vol_ratios)
    vol_median = vol_sorted[len(vol_sorted) // 2] if len(vol_sorted) % 2 == 1 else (
        (vol_sorted[len(vol_sorted) // 2 - 1] + vol_sorted[len(vol_sorted) // 2]) / 2
    ) if len(vol_sorted) > 0 else None
    
    vol_shrink_median = int(np.median(vol_shrink_days_list)) if vol_shrink_days_list else 0
    
    return {
        "adx_median": round(adx_median, 2),
        "adx_sample_count": n,
        "vol_ratio_median": round(vol_median, 3) if vol_median is not None else None,
        "vol_shrink_median_days": vol_shrink_median,
        "adx_range": f"{min(adx_values):.1f}-{max(adx_values):.1f}",
        "vol_range": f"{min(vol_ratios):.3f}-{max(vol_ratios):.3f}"
    }


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def run_scan(scope="all", use_realtime=True):
    """执行全池扫描，返回标准化JSON"""
    
    import tushare as ts
    pro = ts.pro_api(TUSHARE_TOKEN)
    
    # 按scope筛选标的
    if scope == "us":
        pool = {k: v for k, v in FULL_POOL.items() if v["market"] == "us"}
    elif scope == "cn":
        pool = {k: v for k, v in FULL_POOL.items() if v["market"] == "cn"}
    else:
        pool = FULL_POOL
    
    # Step 1: Tushare批量拉取 + 指标计算
    results = []
    tushare_errors = 0
    for sym, info in pool.items():
        r = compute_one(sym, info, pro)
        if "error" in r:
            tushare_errors += 1
        results.append(r)
    
    # Step 2: 腾讯实时行情覆写现价
    qt_data = {}
    qt_error = None
    if use_realtime:
        qt_data = fetch_qt_realtime(list(pool.keys()))
        if "_error" in qt_data:
            qt_error = qt_data["_error"]
            qt_data = {}
    
    # 覆写现价
    for r in results:
        sym = r["symbol"]
        if sym in qt_data and qt_data[sym].get("price") is not None:
            r["price_realtime"] = qt_data[sym]["price"]
            r["prev_close"] = qt_data[sym].get("prev_close")
            r["pct_change"] = qt_data[sym].get("pct")
            # 重新计算基于实时价的乖离率
            realtime_price = qt_data[sym]["price"]
            for key in r.get("indicators", {}):
                if key.startswith("MA") or key.startswith("EMA"):
                    ma_val = r["indicators"][key].get("value")
                    if ma_val:
                        r["indicators"][key]["deviation_pct"] = calc_deviation(realtime_price, ma_val)
        else:
            r["price_realtime"] = r.get("close_tushare")
            r["pct_change"] = None
    
    # Step 3: 博弈态 D2/D3 聚合
    game_state = compute_game_state_d2d3(results)
    
    # Step 4: 组装最终输出
    output = {
        "meta": {
            "version": "V1.0",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "scope": scope,
            "pool_count": len(pool),
            "tushare_errors": tushare_errors,
            "qt_error": qt_error,
            "qt_success_count": len(qt_data) - (1 if "_error" in qt_data else 0)
        },
        "game_state": game_state,
        "indicators": {}
    }
    
    for r in results:
        output["indicators"][r["symbol"]] = r
    
    return output


def print_summary(output):
    """人类可读摘要输出"""
    meta = output["meta"]
    gs = output["game_state"]
    
    print(f"{'='*80}")
    print(f"  scan_engine V1.0 — {meta['scope']}池扫描结果")
    print(f"  生成时间: {meta['generated_at']}")
    print(f"  标的数: {meta['pool_count']} | Tushare错误: {meta['tushare_errors']} | 腾讯实时: {meta['qt_success_count']}")
    print(f"{'='*80}")
    
    print(f"\n📊 博弈态 D2/D3:")
    print(f"  ADX14中位数: {gs.get('adx_median')} (n={gs.get('adx_sample_count')}, 范围{gs.get('adx_range')})")
    print(f"  成交量比值中位数: {gs.get('vol_ratio_median')}")
    print(f"  缩量中位天数: {gs.get('vol_shrink_median_days')}")
    
    print(f"\n📋 逐标摘要:")
    print(f"  {'标的':<8} {'现价':>10} {'涨跌':>8} {'MA40':>10} {'偏离':>7} {'MA60':>10} {'MACD':>6} {'RSI':>6} {'ATR14':>8} {'ADX':>6} {'路由'}")
    print(f"  {'─'*100}")
    
    for sym, r in output["indicators"].items():
        if "error" in r:
            print(f"  {sym:<8} {'⚠️ ' + r['error'][:50]:>60}")
            continue
        
        ind = r["indicators"]
        price = r.get("price_realtime", r.get("close_tushare", "N/A"))
        pct = r.get("pct_change")
        pct_str = f"{pct:+.2f}%" if pct is not None else "N/A"
        
        ma40 = f"{ind['MA40']['value']:.4f}" if "MA40" in ind else "N/A"
        dev40 = f"{ind['MA40']['deviation_pct']:+.1f}%" if "MA40" in ind and ind['MA40'].get('deviation_pct') is not None else "N/A"
        ma60 = f"{ind['MA60']['value']:.4f}" if "MA60" in ind else "N/A"
        
        macd_bar = ind["MACD"]["BAR"] if "MACD" in ind else None
        macd_str = f"{macd_bar:+.4f}" if macd_bar is not None else "N/A"
        
        rsi = f"{ind['RSI14']['value']:.1f}" if "RSI14" in ind else "N/A"
        atr = f"{ind['ATR14']['value']:.4f}" if "ATR14" in ind else "N/A"
        adx = f"{ind['ADX14']['value']:.1f}" if "ADX14" in ind else "N/A"
        
        route = r["route"]
        
        print(f"  {sym:<8} {price:>10.4f} {pct_str:>8} {ma40:>10} {dev40:>7} {ma60:>10} {macd_str:>6} {rsi:>6} {atr:>8} {adx:>6} {route}")
    
    print(f"\n{'='*80}")
    # 新鲜度统计
    ok = sum(1 for r in output["indicators"].values() if r.get("freshness_ok"))
    total = len(output["indicators"])
    print(f"  新鲜度: {ok}/{total} 通过")
    print(f"{'='*80}")


def main():
    parser = argparse.ArgumentParser(description="全池扫描引擎 V1.0")
    parser.add_argument("--scope", choices=["all", "us", "cn"], default="all",
                        help="扫描范围: all(全池20标) / us(美股12标) / cn(A股8标)")
    parser.add_argument("--no-realtime", action="store_true",
                        help="跳过腾讯实时行情（调试用）")
    parser.add_argument("--json", action="store_true", default=True,
                        help="JSON输出（默认）")
    parser.add_argument("--summary", action="store_true",
                        help="人类可读摘要输出")
    args = parser.parse_args()
    
    output = run_scan(scope=args.scope, use_realtime=not args.no_realtime)
    
    if args.summary:
        print_summary(output)
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
