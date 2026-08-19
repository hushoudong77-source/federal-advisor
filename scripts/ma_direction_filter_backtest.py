#!/usr/bin/env python3
"""
全池反击标的 MA 方向过滤对比回测 — 与 tmp/ma_filter_compare_510300.py 完全同口径
口径: 反击框架(k/stop_mult逐标) + 正金字塔30/70建仓 + -15%硬止损下限 + 120日强制离场
数据: TickFlow 前复权(forward) — 与上一轮510300单测一致
方向过滤: "MA向上" = 今日MA > 20日前MA (与 market_data.py 一致)
"""
import pandas as pd, numpy as np, os, json, sys, time
from tickflow import TickFlow

BASE = os.path.dirname(os.path.abspath(__file__))
PARAMS = json.load(open(os.path.join(BASE, 'params.json')))
CP = PARAMS['counterpunch']
POOL = PARAMS['pool']

FORCE_EXIT = 120  # 与上一轮一致

def tf_code(tk):
    code = POOL['tushare_codes'][tk]['code']
    typ = POOL['tushare_codes'][tk]['type']
    if typ == 'us_daily' and '.' not in code:
        return code + '.US'
    return code

def fetch(tk, count=10000):
    tf = TickFlow(api_key=os.environ.get('TICKFLOW_API_KEY'))
    for attempt in range(5):
        try:
            r = tf.klines.get(tf_code(tk), period='1d', count=count, adjust='forward')
            break
        except Exception as e:
            if attempt < 4:
                time.sleep(2)
            else:
                raise
    if not r or len(r.get('close', [])) == 0:
        return None
    df = pd.DataFrame({
        'date': pd.to_datetime(r['timestamp'], unit='ms'),
        'open': r['open'], 'high': r['high'], 'low': r['low'],
        'close': r['close'], 'volume': r['volume']
    })
    df = df.sort_values('date').reset_index(drop=True)
    return df

def run_one(tk, cfg, filter_mode):
    df = fetch(tk)
    if df is None or len(df) < 200:
        return {'ticker': tk, 'filter': filter_mode, 'error': '数据不足'}

    k = cfg.get('k', 2.0)
    stop_mult = cfg.get('stop_mult', 2.0)
    cooldown = cfg.get('cooldown', 10)

    c = df['close']
    df['MA20'] = c.rolling(20).mean()
    df['MA30'] = c.rolling(30).mean()
    df['MA40'] = c.rolling(40).mean()

    h, l = df['high'], df['low']
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df['ATR14'] = tr.rolling(14).mean()

    # 方向序列
    if filter_mode == 'none':
        df['dir_up'] = True
    else:
        period = {'ma20': 20, 'ma30': 30, 'ma40': 40}[filter_mode]
        ma = c.rolling(period).mean()
        df['dir_up'] = ma > ma.shift(20)

    bz = df['MA40'] - k * df['ATR14']
    n = len(df)
    cool_end = -1
    trades = []

    for i in range(40, n):
        if pd.isna(bz.iloc[i]) or pd.isna(df['ATR14'].iloc[i]) or df['ATR14'].iloc[i] <= 0:
            continue
        if not df['dir_up'].iloc[i]:
            continue
        if c.iloc[i] > bz.iloc[i]:
            continue
        if cool_end > 0 and i <= cool_end:
            continue
        # 命中信号
        trades.append(i)
        cool_end = i + cooldown

    if not trades:
        return {'ticker': tk, 'filter': filter_mode, 'n': 0, 'winrate': None, 'avg': None,
                'cum': 0.0, 'sharpe': None, 'maxdd': None}

    rets = []
    for sig in trades:
        r = sim_trade(df, sig, k, stop_mult)
        if r is not None:
            rets.append(r)

    if not rets:
        return {'ticker': tk, 'filter': filter_mode, 'n': 0, 'winrate': None, 'avg': None,
                'cum': 0.0, 'sharpe': None, 'maxdd': None}

    rets = np.array(rets)
    return {
        'ticker': tk, 'filter': filter_mode, 'n': len(rets),
        'winrate': (rets > 0).mean() * 100,
        'avg': rets.mean() * 100,
        'cum': ((1 + rets).prod() - 1) * 100,
        'sharpe': rets.mean() / rets.std() if rets.std() > 0 else 0.0,
        'maxdd': max_drawdown(rets)
    }

def sim_trade(df, sig, k, stop_mult):
    """正金字塔30/70 + -15%硬止损下限 + 120日强制离场 — 与上一轮一致"""
    if sig + 5 >= len(df):
        return None
    e = df['close'].iloc[sig]
    ae = df['ATR14'].iloc[sig]
    stop = max(e - stop_mult * ae, e * 0.85)  # 硬止损下限 -15%
    # 正金字塔：首批30%当日，次批70%第5日
    b2 = sig + 5
    avg = 0.3 * e + 0.7 * df['close'].iloc[b2]
    for i in range(sig + 1, min(sig + FORCE_EXIT + 1, len(df))):
        if df['low'].iloc[i] <= stop:
            return (df['close'].iloc[i] - avg) / avg
        if i - sig >= FORCE_EXIT:
            return (df['close'].iloc[i] - avg) / avg
    return (df['close'].iloc[min(sig + FORCE_EXIT, len(df) - 1)] - avg) / avg

def max_drawdown(rets):
    eq = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(eq)
    return ((eq - peak) / peak).min() * 100

def main():
    tickers = [t for t in CP if not t.startswith('_meta')]
    filters = ['none', 'ma20', 'ma30', 'ma40']
    results = {}
    print("=" * 112)
    print("全池反击标的 MA 方向过滤对比回测（正金字塔30/70 + 前复权 + 120日离场 + -15%硬下限）")
    print("口径与上一轮510300单测完全一致 | 方向='今日MA>20日前MA'")
    print("=" * 112)
    header = f"{'标的':8s} | {'过滤':6s} | {'笔数':>4s} | {'胜率':>6s} | {'均收益':>7s} | {'累计':>9s} | {'Sharpe':>7s} | {'最大回撤':>8s}"
    print(header)
    print("-" * 112)

    for tk in tickers:
        cfg = CP[tk]
        results[tk] = {}
        for fm in filters:
            r = run_one(tk, cfg, fm)
            results[tk][fm] = r
            if 'error' in r:
                print(f"{tk:8s} | {fm:6s} | {r['error']}")
            elif r['n'] == 0:
                print(f"{tk:8s} | {fm:6s} | {'0':>4s} | {'—':>6s} | {'—':>7s} | {'0.0%':>9s} | {'—':>7s} | {'—':>8s}")
            else:
                print(f"{tk:8s} | {fm:6s} | {r['n']:>4d} | {r['winrate']:>5.1f}% | {r['avg']:>+6.2f}% | {r['cum']:>+8.1f}% | {r['sharpe']:>7.3f} | {r['maxdd']:>7.1f}%")
        print("-" * 112)

    with open(os.path.join(BASE, '.ma_filter_full.json'), 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("已保存: scripts/.ma_filter_full.json")

if __name__ == '__main__':
    main()
