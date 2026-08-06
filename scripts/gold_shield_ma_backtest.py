#!/usr/bin/env python3
"""金盾入场MA周期对比回测 — 518880"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tickflow import TickFlow
import pandas as pd
import numpy as np

tf = TickFlow(os.environ.get('TICKFLOW_API_KEY', ''))
result = tf.klines.batch(['518880.SH'], period='1d', count=3000, adjust='forward')
raw = result['518880.SH']
df = pd.DataFrame({
    'date': pd.to_datetime(raw['timestamp'], unit='ms'),
    'open': raw['open'], 'high': raw['high'],
    'low': raw['low'], 'close': raw['close'],
    'volume': raw['volume']
}).set_index('date').sort_index()
print(f"数据: {len(df)}行, {df.index[0].date()} ~ {df.index[-1].date()}")

df = df[df.index >= '2015-01-01']
print(f"回测区间: {df.index[0].date()} ~ {df.index[-1].date()}, {len(df)}行")


def calc_atr(d, period=14):
    h, l, c = d['high'], d['low'], d['close']
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def backtest(df, ma_period):
    d = df.copy()
    d['MA'] = d['close'].rolling(ma_period).mean()
    d['MA_dir'] = (d['MA'] - d['MA'].shift(20)) / d['MA'].shift(20)  # 20日斜率
    d['ATR14'] = calc_atr(d, 14)
    d['ATR_pct'] = d['ATR14'] / d['close']
    d['C2'] = d['MA_dir'] > 0
    d['C3'] = d['close'] > d['MA']
    d['C4'] = d['ATR_pct'] < 0.035
    d['signal'] = d['C2'] & d['C3'] & d['C4']

    trades = []
    pos = False
    ep, peak = 0.0, 0.0
    edate = None
    start = ma_period + 30

    for i in range(start, len(d)):
        dt = d.index[i]
        cl = d['close'].iloc[i]

        if not pos:
            if d['signal'].iloc[i]:
                if trades and (dt - trades[-1]['exit_date']).days < 10:
                    continue
                edate, ep, peak = dt, cl, cl
                pos = True
        else:
            days = (dt - edate).days
            if cl > peak:
                peak = cl
            s3 = (d['MA_dir'].iloc[i] < 0) and (cl < d['MA'].iloc[i])
            s6 = (peak - cl) > 3 * d['ATR14'].iloc[i]
            force = days >= 120
            if s3 or s6 or force:
                reason = 'S3' if s3 else ('S6' if s6 else 'Force')
                trades.append({
                    'entry': edate, 'exit': dt,
                    'ret': (cl-ep)/ep, 'days': days, 'reason': reason
                })
                pos = False
    return trades


results = {}
for p in [30, 40, 60]:
    tr = backtest(df, p)
    if tr:
        rets = [t['ret'] for t in tr]
        w = sum(1 for r in rets if r > 0)
        results[p] = {
            'n': len(tr), 'wr': w/len(tr), 'avg': np.mean(rets),
            'cum': np.exp(sum(np.log1p(r) for r in rets)) - 1,
            'days': np.mean([t['days'] for t in tr]),
            'best': max(rets), 'worst': min(rets),
            'sr': np.mean(rets)/np.std(rets)*np.sqrt(252/np.mean([t['days'] for t in tr])) if np.std(rets)>0 else 0,
            'rs': {r: sum(1 for t in tr if t['reason']==r) for r in set(t['reason'] for t in tr)}
        }

print("\n" + "="*70)
print("金盾入场MA周期对比 — 518880 (2015-2026)")
print("入场: C2(MA↑) + C3(价>MA) + C4(ATR<3.5%)")
print("="*70)

for p in [30, 40, 60]:
    r = results[p]
    print(f"\nMA{p}: {r['n']}笔 | 胜率{r['wr']:.0%} | 均{r['avg']:+.2%} | 累计{r['cum']:+.1%}")
    print(f"  均持{r['days']:.0f}天 | 最佳{r['best']:+.2%} | 最差{r['worst']:+.2%} | SR={r['sr']:.2f} | 离场:{r['rs']}")

print("\n--- 裁决 ---")
for metric, label in [('cum','累计'),('sr','Sharpe'),('wr','胜率')]:
    best = max(results, key=lambda k: results[k][metric])
    print(f"{label}最优: MA{best}")
