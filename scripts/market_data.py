#!/usr/bin/env python3
"""
联邦投顾 — 全量行情取数工具 V5.3
数据源：腾讯API（实时现价）+ TickFlow批量日线（全池25标，batch()一次调用~0.6秒）
V5.3: adjust="none"（不复权）真正生效——V5.2注释说none但代码写的是backward，6个标的MA60严重错误。
不复权=真实成交价=均线正确，与腾讯实时现价在同一价格坐标系。
美股T+1滞后（技术指标计算不受影响），A股当日15:00后入库。
盘中现价走腾讯API实时。

用法：
  python3 scripts/market_data.py              # 全量输出JSON
  python3 scripts/market_data.py --table       # 表格格式输出
  python3 scripts/market_data.py --ticker QQQ  # 单标查询
"""

import urllib.request
import json
import sys
import os
import time
import hashlib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# ── 落盘缓存路径（供 output_gate.py --check fire-invoked 校验「脚本是否真实运行过」）──
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_FILE = os.path.join(CACHE_DIR, "market_data.json")

# ============================================================
# V5.2 更新：adjust="none"（不复权），V5.1 backward在部分标的上反向复权已修复
# 后复权不受除权事件影响，消除规则M.2/M.2.5的前复权均线失真问题。
# 前复权（默认）因分红除权压平历史价格→MA/EMA/H20系统性偏低。
# 510880前复权vs后复权偏差可达+82%（红利ETF频繁分红）。
# ============================================================

# ============================================================
# 全池24标硬编码（真源：AGENT.md 白名单）+ CANE（不入池持仓展示）
# ============================================================
FULL_POOL = {
    # 美股13标（含CANE）
    "VTI":   {"qt": "usVTI",   "tickflow": "VTI.US",   "type": "us"},
    "VEA":   {"qt": "usVEA",   "tickflow": "VEA.US",   "type": "us"},
    "QQQ":   {"qt": "usQQQ",   "tickflow": "QQQ.US",   "type": "us"},
    "IVV":   {"qt": "usIVV",   "tickflow": "IVV.US",   "type": "us"},
    "IAU":   {"qt": "usIAU",   "tickflow": "IAU.US",   "type": "us"},
    "BBJP":  {"qt": "usBBJP",  "tickflow": "BBJP.US",  "type": "us"},
    "MUFG":  {"qt": "usMUFG",  "tickflow": "MUFG.US",  "type": "us"},
    "EWY":   {"qt": "usEWY",   "tickflow": "EWY.US",   "type": "us"},
    "VNM":   {"qt": "usVNM",   "tickflow": "VNM.US",   "type": "us"},
    "FLIN":  {"qt": "usFLIN",  "tickflow": "FLIN.US",  "type": "us"},
    "SMIN":  {"qt": "usSMIN",  "tickflow": "SMIN.US",  "type": "us"},
    "BOTZ":  {"qt": "usBOTZ",  "tickflow": "BOTZ.US",  "type": "us"},
    "CANE":  {"qt": "usCANE",  "tickflow": "CANE.US",  "type": "us"},
    # A股12标
    "588000": {"qt": "sh588000", "tickflow": "588000.SH", "type": "a"},
    "513180": {"qt": "sh513180", "tickflow": "513180.SH", "type": "a"},
    "513910": {"qt": "sh513910", "tickflow": "513910.SH", "type": "a"},
    "510500": {"qt": "sh510500", "tickflow": "510500.SH", "type": "a"},
    "518880": {"qt": "sh518880", "tickflow": "518880.SH", "type": "a"},
    "512100": {"qt": "sh512100", "tickflow": "512100.SH", "type": "a"},
    "510880": {"qt": "sh510880", "tickflow": "510880.SH", "type": "a"},
    "159530": {"qt": "sz159530", "tickflow": "159530.SZ", "type": "a"},
    "510300": {"qt": "sh510300", "tickflow": "510300.SH", "type": "a"},
    "159915": {"qt": "sz159915", "tickflow": "159915.SZ", "type": "a"},
    "513770": {"qt": "sh513770", "tickflow": "513770.SH", "type": "a"},
    "159545": {"qt": "sz159545", "tickflow": "159545.SZ", "type": "a"},
}

# TickFlow 配置
TICKFLOW_API_KEY = os.environ.get("TICKFLOW_API_KEY", "")
TICKFLOW_KLINES_LIMIT = 300  # 日线条数（覆盖MA250，Pro支持全量）
# 批量模式：自定义功能 daily_kline:US + daily_kline_backup 已配，batch() 一次拉取全池25标

# 时段判定
def _is_a_stock_session():
    """判定当前是否A股盘中（09:30-15:00）"""
    now = datetime.now()
    t = now.hour * 100 + now.minute
    return 930 <= t < 1500

def _is_us_stock_session():
    """判定当前是否美股盘中（21:30-04:00）"""
    now = datetime.now()
    t = now.hour * 100 + now.minute
    return t >= 2130 or t < 400


# ============================================================
# 第一层：腾讯API — 全池实时现价（一次请求，A股+美股统一）
# ============================================================
def fetch_tencent_realtime():
    """腾讯API拉取全池实时行情"""
    codes = [v["qt"] for v in FULL_POOL.values()]
    url = "http://qt.gtimg.cn/q=" + ",".join(codes)

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk")
    except Exception as e:
        return {"_error": f"tencent_unavailable: {e}"}

    results = {}
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("~")
        if len(parts) < 5:
            continue

        qt_code = parts[0].split("=")[0].replace("v_", "")
        name = parts[1]
        price = parts[3]
        prev_close = parts[4] if len(parts) > 4 else "N/A"
        change_pct = parts[32] if len(parts) > 32 else "N/A"
        change_amt = parts[31] if len(parts) > 31 else "N/A"
        high = parts[33] if len(parts) > 33 else "N/A"
        low = parts[34] if len(parts) > 34 else "N/A"
        volume = parts[6] if len(parts) > 6 else "0"

        for fed, info in FULL_POOL.items():
            if info["qt"] == qt_code:
                results[fed] = {
                    "name": name,
                    "price": _sf(price),
                    "prev_close": _sf(prev_close),
                    "change_pct": _sf(change_pct),
                    "change_amt": _sf(change_amt),
                    "high": _sf(high),
                    "low": _sf(low),
                    "volume": _si(volume),
                }
                break
    return results


# ============================================================
# 第二层：TickFlow SDK — 全池24标日线 + 全量技术指标自算
# ============================================================
def _sf(v):
    """安全 float"""
    try: return round(float(v), 4)
    except: return None

def _si(v):
    """安全 int"""
    try: return int(v)
    except: return 0

def _calc_ma(close, period):
    if len(close) < period: return None
    return round(float(close.iloc[-period:].mean()), 4)


def _ma_dir(ma_now, ma_ago, volatility_eps=None):
    """均线方向三态判定（斜率死区 ε 波动率自适应）。
    r33.95 修复：原二值判定（> 则 up 否则 down）把走平区间误判为下降。
    r33.96 修复（守东裁决②）：死区从固定 0.3% 改为波动率自适应——
    ε = max(0.3% 地板, ATR14/价格)。高波动标的（如 EWY ATR≈5%）走平会被
    固定 0.3% 死区误判为 down；自适应死区让「走平」真正落到 flat 态。
    返回 'up' / 'flat' / 'down'。"""
    if ma_now is None or ma_ago is None or ma_now <= 0 or ma_ago <= 0:
        return None
    chg = (ma_now - ma_ago) / ma_ago
    # 地板 0.3% 兜底；有波动率则用 max(0.3%, ATR/价格)
    eps = 0.003
    if volatility_eps is not None and volatility_eps > 0:
        eps = max(0.003, volatility_eps)
    if chg > eps:
        return "up"
    elif chg < -eps:
        return "down"
    else:
        return "flat"

def _calc_ema(close, period):
    if len(close) < period: return None
    return round(float(close.ewm(span=period, adjust=False).mean().iloc[-1]), 4)

def _calc_atr(high, low, close, period=14):
    if len(close) < period + 1: return None
    tr = pd.Series([
        max(high.iloc[i] - low.iloc[i],
            abs(high.iloc[i] - close.iloc[i-1]),
            abs(low.iloc[i] - close.iloc[i-1]))
        for i in range(1, len(close))
    ], index=close.index[1:])
    return round(float(tr.rolling(period).mean().iloc[-1]), 4)

def _calc_macd(close):
    if len(close) < 35: return {"diff": None, "dea": None, "bar": None, "bar_prev": None}
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    diff = ema12 - ema26
    dea = diff.ewm(span=9, adjust=False).mean()
    bar = 2 * (diff - dea)
    return {
        "diff": round(float(diff.iloc[-1]), 4),
        "dea": round(float(dea.iloc[-1]), 4),
        "bar": round(float(bar.iloc[-1]), 4),
        "bar_prev": round(float(bar.iloc[-2]), 4) if len(bar) >= 2 else None,
    }

def _calc_rsi(close, period=14):
    if len(close) < period + 1: return None
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return round(float(100 - (100 / (1 + rs.iloc[-1]))), 2)

def _calc_adx(high, low, close, period=14):
    if len(close) < period * 2 + 1: return None
    try:
        tr = pd.Series(np.maximum(
            high - low,
            np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1)))
        ))
        atr_s = tr.rolling(period).mean()

        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        plus_di = 100 * pd.Series(plus_dm).rolling(period).mean() / atr_s
        minus_di = 100 * pd.Series(minus_dm).rolling(period).mean() / atr_s
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
        return round(float(dx.rolling(period).mean().iloc[-1]), 2)
    except:
        return None

def _calc_kdj(high, low, close, n=9, m1=3, m2=3):
    """KDJ(9,3,3) — 返回 K, D, J, 金叉/死叉, 超买超卖"""
    if len(close) < n + 2: return None
    try:
        low_n = low.rolling(window=n).min()
        high_n = high.rolling(window=n).max()
        rsv = (close - low_n) / (high_n - low_n + 1e-9) * 100
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        d = k.ewm(com=m2-1, adjust=False).mean()
        j = 3 * k - 2 * d

        # 金叉/死叉
        cross = 0
        if k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2]:
            cross = 1  # 金叉
        elif k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2]:
            cross = -1  # 死叉

        return {
            "k": round(float(k.iloc[-1]), 2),
            "d": round(float(d.iloc[-1]), 2),
            "j": round(float(j.iloc[-1]), 2),
            "cross": cross,
            "oversold": float(j.iloc[-1]) < 20,
            "overbought": float(j.iloc[-1]) > 80,
        }
    except:
        return None

def _calc_obv(close, volume):
    """OBV — 返回最新OBV, OBV_MA20, 是否在MA20上方, 20日新高/新低, 背离"""
    if len(close) < 25: return None
    try:
        price_dir = np.sign(close.diff().fillna(0))
        obv = (volume * price_dir).cumsum()
        obv_ma20 = obv.rolling(20).mean()
        obv_20high = obv.rolling(20).max()
        obv_20low = obv.rolling(20).min()
        price_20high = close.rolling(20).max()
        price_20low = close.rolling(20).min()

        return {
            "obv": round(float(obv.iloc[-1]), 0),
            "obv_ma20": round(float(obv_ma20.iloc[-1]), 0),
            "obv_above_ma20": bool(obv.iloc[-1] > obv_ma20.iloc[-1]),
            "obv_new_high": bool(obv.iloc[-1] >= obv_20high.iloc[-1]),
            "obv_new_low": bool(obv.iloc[-1] <= obv_20low.iloc[-1]),
            "bearish_div": bool(close.iloc[-1] >= price_20high.iloc[-1] and obv.iloc[-1] < obv_20high.iloc[-1]),
            "bullish_div": bool(close.iloc[-1] <= price_20low.iloc[-1] and obv.iloc[-1] > obv_20low.iloc[-1]),
        }
    except:
        return None

def _calc_bottom_seq_full(open_, high, low, close, volume):
    """底部序列检测（完整版，含 open 序列）。

    返回 (bool 当前确认状态, int 最近恐慌日距今天数, int 最近止跌日距今天数)。
    确认条件（AND）:
      ① 近20个交易日内存在恐慌日（跌幅>3% 且 量比>1.5）
      ② 恐慌日之后存在止跌日（|close-open|<0.3×ATR14 且 量比<0.8）
    """
    try:
        close = pd.Series(close).astype(float).reset_index(drop=True)
        open_ = pd.Series(open_).astype(float).reset_index(drop=True)
        high = pd.Series(high).astype(float).reset_index(drop=True)
        low = pd.Series(low).astype(float).reset_index(drop=True)
        volume = pd.Series(volume).astype(float).reset_index(drop=True)
    except Exception:
        return (False, None, None)

    if len(close) < 25:
        return (False, None, None)

    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    vol_ma20 = volume.rolling(20).mean()
    vol_ratio = volume / vol_ma20
    pct_chg = close.pct_change() * 100
    body_ratio = (close - open_).abs() / atr14

    n = len(close)
    window_start = max(0, n - 20)
    panic_idx = None
    # ① 找近20日内最近的恐慌日
    for i in range(window_start, n):
        if pd.isna(pct_chg.iloc[i]) or pd.isna(vol_ratio.iloc[i]):
            continue
        if pct_chg.iloc[i] < -3 and vol_ratio.iloc[i] > 1.5:
            panic_idx = i
            # ② 恐慌日之后找止跌日
            for j in range(i + 1, n):
                if pd.isna(body_ratio.iloc[j]) or pd.isna(vol_ratio.iloc[j]):
                    continue
                if body_ratio.iloc[j] < 0.3 and vol_ratio.iloc[j] < 0.8:
                    days_panic = n - 1 - i
                    days_stop = n - 1 - j
                    return (True, days_panic, days_stop)
            break  # 最近的恐慌日之后无止跌日 → 不满足
    return (False, None, None)


def fetch_tickflow_all():
    """TickFlow批量拉取全池25标日线 + 自算全部技术指标。
    batch() 一次调用完成，~0.6秒。
    V5.1: adjust="backward"（后复权），消除分红除权对均线/H20的失真。
    美股T+1滞后（最新=前一交易日收盘），A股当日15:00后入库。
    """
    # 依赖自愈：会话环境不持久，tickflow 可能丢失 → 自动补装
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    try:
        from self_heal import ensure_tickflow
        ensure_tickflow()
    except Exception:
        pass
    from tickflow import TickFlow
    tf = TickFlow(TICKFLOW_API_KEY)

    results = {}
    fetch_log = {}
    start_time = time.time()

    # 收集全部 tf_symbol
    ticker_map = {}  # tf_symbol -> fed_code
    for fed, info in FULL_POOL.items():
        tfs = info["tickflow"]
        ticker_map[tfs] = fed

    tf_symbols = list(ticker_map.keys())

    # 批量拉取（as_dataframe=True 返回 DataFrame 而非列式 dict）
    # V5.3: adjust="none" — 不复权。V5.2注释说"不复权"但代码写的是 backward（后复权），
    # 后复权在TickFlow A股ETF上返回除权调整后的非真实价格，导致MA/乖离率全部错乱
    # （512100 MA60=1.234 vs 真实3.283，偏差-62%）。不复权=真实成交价=均线正确。
    try:
        batch_results = tf.klines.batch(tf_symbols, period="1d",
                                        count=TICKFLOW_KLINES_LIMIT,
                                        adjust="none",
                                        as_dataframe=True)
    except Exception as e:
        for fed in FULL_POOL:
            fetch_log[fed] = f"batch_error: {type(e).__name__}: {e}"
            results[fed] = {"error": str(e)}
        results["_log"] = fetch_log
        results["_call_count"] = 0
        results["_elapsed"] = round(time.time() - start_time, 1)
        return results

    # 逐标处理批量返回的 DataFrame
    for tf_symbol, df in batch_results.items():
        fed = ticker_map.get(tf_symbol)
        if not fed:
            continue

        if df is None or len(df) == 0:
            fetch_log[fed] = f"empty: {tf_symbol}"
            results[fed] = {"error": "empty", "tf_symbol": tf_symbol}
            continue

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        latest_date = str(df["trade_date"].iloc[-1])

        # MA 系列
        ma5  = _calc_ma(close, 5)
        ma20 = _calc_ma(close, 20)
        ma40 = _calc_ma(close, 40)
        ma60 = _calc_ma(close, 60)
        ma120 = _calc_ma(close, 120) if len(close) >= 120 else None
        ma150 = _calc_ma(close, 150) if len(close) >= 150 else None
        ma250 = _calc_ma(close, 250) if len(close) >= 250 else None

        # EMA
        ema50 = _calc_ema(close, 50)
        ema150 = _calc_ema(close, 150) if len(close) >= 150 else None

        # 乖离率
        dev_ma20 = round((close.iloc[-1] / ma20 - 1) * 100, 2) if ma20 and ma20 > 0 else None
        dev_ma40 = round((close.iloc[-1] / ma40 - 1) * 100, 2) if ma40 and ma40 > 0 else None
        dev_ma60 = round((close.iloc[-1] / ma60 - 1) * 100, 2) if ma60 and ma60 > 0 else None
        dev_ma150 = round((close.iloc[-1] / ma150 - 1) * 100, 2) if ma150 and ma150 > 0 else None

        # ATR（先于 MA 方向判定计算，供波动率自适应死区用）
        atr14 = _calc_atr(high, low, close)
        atr_pct = round(atr14 / close.iloc[-1] * 100, 2) if atr14 and close.iloc[-1] > 0 else None

        # MA60 方向（20日变化，含波动率自适应死区三态判定 — r33.96）
        ma60_dir = None
        if ma60 and len(close) >= 20:
            ma60_20d_ago = _calc_ma(close.iloc[:-20], 60)
            if ma60_20d_ago and ma60_20d_ago > 0:
                eps60 = (atr_pct / 100.0) if atr_pct else None
                ma60_dir = _ma_dir(ma60, ma60_20d_ago, eps60)

        # MA40 方向（20日变化，金盾V1.6用，同含波动率自适应死区）
        ma40_dir = None
        if ma40 and len(close) >= 20:
            ma40_20d_ago = _calc_ma(close.iloc[:-20], 40)
            if ma40_20d_ago and ma40_20d_ago > 0:
                eps40 = (atr_pct / 100.0) if atr_pct else None
                ma40_dir = _ma_dir(ma40, ma40_20d_ago, eps40)

        # MA40 5日变化率（金盾V1.6走平过渡态判定用）
        ma40_5d_chg = None
        ma40_5d_up_streak = None
        if ma40 and len(close) >= 5:
            ma40_5d_ago = _calc_ma(close.iloc[:-5], 40)
            if ma40_5d_ago and ma40_5d_ago > 0:
                ma40_5d_chg = round((ma40 / ma40_5d_ago - 1) * 100, 4)
            # 连续符号确认：MA40 5日变化率连续 N 日 > 0 的真实上翘天数
            # （独立于死区判定，解决"MA40上翘被ATR死区吞掉"的问题）
            up_streak = 0
            for i in range(5, 0, -1):
                if len(close) < 40 + i:
                    continue
                ma_now = _calc_ma(close.iloc[:-i], 40)
                ma_prev = _calc_ma(close.iloc[:-i-5], 40)
                if ma_now and ma_prev and ma_prev > 0 and ma_now > ma_prev:
                    up_streak += 1
                else:
                    break
            ma40_5d_up_streak = up_streak

        # ATR / RSI / MACD / H20（atr14/atr_pct 已在 MA 方向判定前计算）
        rsi14 = _calc_rsi(close)
        macd = _calc_macd(close)
        h20 = round(float(close.iloc[-20:].max()), 4) if len(close) >= 20 else None
        vol_ma20 = round(float(volume.rolling(20).mean().iloc[-1]), 0) if len(volume) >= 20 else None
        vol_ratio = round(float(volume.iloc[-1] / vol_ma20), 2) if vol_ma20 and vol_ma20 > 0 else None

        # ADX14
        adx_val = _calc_adx(high, low, close)

        # KDJ (9,3,3)
        kdj = _calc_kdj(high, low, close)

        # OBV
        obv = _calc_obv(close, volume)

        # 20日回撤（轨道二用）
        drawdown_20d = round((close.iloc[-1] / close.iloc[-20] - 1) * 100, 2) if len(close) >= 20 else None

        # 底部序列（r33.77 — 反击R0.5过滤替代MA40方向）
        bottom_seq, bottom_panic_days, bottom_stop_days = _calc_bottom_seq_full(
            df["open"], high, low, close, volume)

        results[fed] = {
            "latest_date": latest_date,
            "rows": len(close),
            "close": round(float(close.iloc[-1]), 4),
            "open": round(float(df["open"].iloc[-1]), 4),  # 最新开盘价
            # MA
            "ma5": ma5, "ma20": ma20, "ma40": ma40,
            "ma60": ma60, "ma120": ma120, "ma150": ma150, "ma250": ma250,
            # EMA
            "ema50": ema50, "ema150": ema150,
            # 乖离率
            "dev_ma20": dev_ma20, "dev_ma40": dev_ma40,
            "dev_ma60": dev_ma60, "dev_ma150": dev_ma150,
            # 方向
            "ma60_dir": ma60_dir, "ma40_dir": ma40_dir,
            "ma40_5d_chg": ma40_5d_chg,
            "ma40_5d_up_streak": ma40_5d_up_streak,
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
            # KDJ
            "kdj": kdj,
            # OBV
            "obv": obv,
            # 轨道二
            "drawdown_20d": drawdown_20d,
            # 底部序列（r33.96）
            "bottom_seq": bottom_seq,
            "bottom_panic_days": bottom_panic_days,
            "bottom_stop_days": bottom_stop_days,
            # 数据源
            "data_source": "tickflow",
            "tf_symbol": tf_symbol,
        }

        fetch_log[fed] = f"ok: {len(close)} rows, latest={latest_date}"

    results["_log"] = fetch_log
    results["_call_count"] = 1  # 一次批量调用
    results["_elapsed"] = round(time.time() - start_time, 1)
    return results


# ============================================================
# 合并输出
# ============================================================
def fetch_all():
    """一键拉取全量：腾讯实时 + TickFlow全池日线"""
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "realtime": fetch_tencent_realtime(),
        "indicators": fetch_tickflow_all(),
    }

    # 合并
    merged = {}
    for ticker, info in FULL_POOL.items():
        entry = {}
        rt = result["realtime"].get(ticker, {})
        entry["price"] = rt.get("price")
        entry["change_pct"] = rt.get("change_pct")
        entry["high"] = rt.get("high")
        entry["low"] = rt.get("low")
        entry["volume"] = rt.get("volume")
        entry["name"] = rt.get("name", "")
        entry["price_source"] = "tencent"

        ind = result["indicators"].get(ticker, {})
        if "error" not in ind:
            # TickFlow 日线 OHLCV → 透传（close/open/high/low 以 TickFlow 日线为准）
            for key in ("close", "open", "high", "low"):
                if key in ind:
                    entry[key] = ind[key]
            # 其他技术指标全部透传
            entry.update({k: v for k, v in ind.items()
                         if k not in ("close", "open", "high", "low", "_log", "_call_count")})

        entry["type"] = info["type"]
        merged[ticker] = entry

    merged["_realtime_ts"] = result["timestamp"]
    merged["_tickflow_log"] = result["indicators"].get("_log", {})
    merged["_tickflow_calls"] = result["indicators"].get("_call_count", 0)
    merged["_tickflow_elapsed"] = result["indicators"].get("_elapsed", 0)

    # ── 落盘缓存 + 调用指纹（供 output_gate --check fire-invoked 强制调用自证）──
    try:
        _cache_payload = {
            "_invoked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "_invoked_epoch": time.time(),
            "_pid": os.getpid(),
            "_realtime_ts": result["timestamp"],
            "_tickflow_calls": merged.get("_tickflow_calls", 0),
            # 🔴 2026-08-17 焊入：落全量现价 + TickFlow 最新日期，
            # 供 output_gate --check intraday 的 Layer 2 做「现价=日线收盘价」陷阱检测。
            "_prices": {t: merged[t].get("price") for t in merged
                        if t not in ("_realtime_ts", "_tickflow_log", "_tickflow_calls", "_tickflow_elapsed")},
            "_tickflow_latest": {t: merged[t].get("latest_date") for t in merged
                                 if isinstance(merged.get(t), dict) and merged[t].get("latest_date")},
            "_close": {t: merged[t].get("close") for t in merged
                       if isinstance(merged.get(t), dict) and merged[t].get("close") is not None},
        }
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache_payload, f, ensure_ascii=False)
    except Exception:
        pass  # 落盘失败不影响主流程

    return merged


# ============================================================
# 输出格式
# ============================================================
def output_table(data):
    """表格格式输出"""
    print(f"\n{'='*120}")
    print(f"  联邦投顾 全量行情 V5.3 — {data.get('_realtime_ts', '')}")
    print(f"  数据源: 腾讯实时(现价) + TickFlow不复权(日线+技术指标)")
    print(f"  TickFlow调用: {data.get('_tickflow_calls', 0)}次 / {data.get('_tickflow_elapsed', 'N/A')}s")
    print(f"{'='*120}")
    print(f"{'标的':8s} | {'名称':16s} | {'现价':>10s} | {'涨跌':>8s} | {'MA20':>10s} | {'MA60':>10s} | {'ATR14':>8s} | {'MACD BAR':>9s} | {'RSI':>5s} | {'方向':4s}")
    print(f"{'-'*120}")

    us_tickers = [t for t, v in FULL_POOL.items() if v["type"] == "us" and t != "CANE"]
    a_tickers = [t for t, v in FULL_POOL.items() if v["type"] == "a"]

    for group, tickers in [("美股 (TickFlow)", us_tickers), ("A股 (TickFlow)", a_tickers), ("CANE", ["CANE"])]:
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

            print(f"{t:8s} | {d.get('name', ''):16s} | {p_str} | {chg_str} | {ma20_str} | {ma60_str} | {atr_str} | {macd_str} | {rsi_str} | {ma60_dir or 'N/A':4s}")

    # 拉取日志
    print(f"\n--- TickFlow 拉取日志 ---")
    tickflow_log = data.get("_tickflow_log", {})
    ok_count = sum(1 for v in tickflow_log.values() if v.startswith("ok"))
    err_count = sum(1 for v in tickflow_log.values() if v.startswith("error"))
    for t, status in sorted(tickflow_log.items()):
        icon = "✅" if status.startswith("ok") else "❌"
        print(f"  {icon} {t:8s}: {status}")
    print(f"  总计: {ok_count} 成功 / {err_count} 失败 / {data.get('_tickflow_calls', 0)}次调用")


if __name__ == "__main__":
    if "--table" in sys.argv:
        # N.1.2 探测（TickFlow免费版）
        print("  ⏳ TickFlow Pro 探测...")
        try:
            from tickflow import TickFlow
            tf = TickFlow(TICKFLOW_API_KEY)
            probe_symbols = ["QQQ.US", "VTI.US", "513910.SH", "510500.SH"]
            for s in probe_symbols:
                try:
                    df = tf.klines.get(s, period="1d", count=5, as_dataframe=True)
                    print(f"     {s}: {len(df)}条, latest={df['trade_date'].iloc[-1]} ✅")
                except Exception as e:
                    print(f"     {s}: ❌ {e}")
        except Exception as e:
            print(f"     TickFlow初始化: ❌ {e}")

        print("\n  ⏳ 拉取腾讯实时 + TickFlow免费版全池日线（约10秒）...\n")
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
