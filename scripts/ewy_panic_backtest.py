#!/usr/bin/env python3
"""EWY 恐慌抄底轨道二 全量回测"""
import tushare as ts
import pandas as pd
import numpy as np
from itertools import product

ts.set_token('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')
pro = ts.pro_api()

r = pro.us_daily(ts_code='EWY', start_date='20140101', end_date='20260717')
r = r.sort_values('trade_date')
closes = r['close'].astype(float).values
highs = r['high'].astype(float).values
lows = r['low'].astype(float).values
n = len(closes)

tr_list = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, n)]
atr14_series = pd.Series([np.nan]*14 + [np.mean(tr_list[i-13:i+1]) for i in range(13, n-1)])
ret20 = pd.Series([np.nan]*20 + [closes[i]/closes[i-20]-1 for i in range(20, n)])

print(f'EWY全量: {n}条, {r.iloc[0]["trade_date"]} ~ {r.iloc[-1]["trade_date"]}')
print(f'最新: C={closes[-1]:.2f}, 20日回撤={ret20.iloc[-1]*100:.1f}%, ATR14={atr14_series.iloc[-1]:.4f}\n')

thresholds = [-10, -12, -14, -15, -16, -18, -20]
stops = [10, 12, 15, 18, 20]
retrace_atr = [2.0, 2.5, 3.0, 3.5, 4.0]
cooldowns = [5, 10, 15, 20, 30]

results = []
for th, stop, ratr, cool in product(thresholds, stops, retrace_atr, cooldowns):
    trades = []
    i = 20
    while i < n:
        if not np.isnan(ret20.iloc[i]) and ret20.iloc[i] < th/100:
            entry_idx = i; entry_price = closes[entry_idx]
            if trades and entry_idx - trades[-1]['exit_idx'] < cool:
                i += 1; continue
            stop_price = entry_price * (1 - stop/100)
            peak = entry_price; exit_idx = None; exit_reason = None; phase2 = False
            for j in range(entry_idx+1, min(entry_idx+252, n)):
                cur = closes[j]
                if cur > peak: peak = cur
                ea = atr14_series.iloc[entry_idx] if entry_idx < len(atr14_series) else np.nan
                if not phase2 and not np.isnan(ea) and peak - entry_price >= ratr * ea:
                    phase2 = True
                if cur <= stop_price:
                    exit_idx = j; exit_reason = 'stop'; break
                if phase2:
                    ca = atr14_series.iloc[j] if j < len(atr14_series) else ea
                    if not np.isnan(ca) and cur <= peak - ratr * ca:
                        exit_idx = j; exit_reason = 'trailing'; break
            if exit_idx is None:
                exit_idx = min(entry_idx+120, n-1); exit_reason = 'timeout'
            exit_price = closes[exit_idx]
            pnl = (exit_price/entry_price - 1) * 100
            trades.append({
                'entry_date': r.iloc[entry_idx]['trade_date'],
                'entry': entry_price, 'exit_date': r.iloc[exit_idx]['trade_date'],
                'exit': exit_price, 'pnl': pnl, 'reason': exit_reason,
                'days': exit_idx-entry_idx, 'phase2': phase2, 'exit_idx': exit_idx
            })
            i = exit_idx + 1
        else:
            i += 1
    if not trades: continue
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins)/len(trades)
    avg_w = np.mean([t['pnl'] for t in wins]) if wins else 0
    avg_l = np.mean([t['pnl'] for t in losses]) if losses else 0
    avg_pnl = np.mean([t['pnl'] for t in trades])
    cum = np.prod([1+t['pnl']/100 for t in trades]) - 1
    max_cl = 0; cc = 0
    for t in trades:
        cc = cc+1 if t['pnl'] <= 0 else 0
        max_cl = max(max_cl, cc)
    pf = abs(avg_w/avg_l) if avg_l != 0 else 5
    pf = min(pf, 5)
    sp = max(0, (5-len(trades))*0.02) if len(trades) < 5 else 0
    score = wr*0.30 + min(cum, 3.0)/3*0.30 + pf/5*0.20 - max_cl/10*0.10 - sp
    results.append({
        'th': th, 'stop': stop, 'ratr': ratr, 'cool': cool,
        'n': len(trades), 'wr': wr, 'avg': avg_pnl, 'cum': cum,
        'pf': pf, 'max_cl': max_cl, 'score': score, 'trades': trades
    })

results.sort(key=lambda x: x['score'], reverse=True)

print(f'=== Top 20 ({len(thresholds)*len(stops)*len(retrace_atr)*len(cooldowns)}组合) ===')
print(f'{"阈值":<6} {"止损":<6} {"回撤ATR":<9} {"冷却":<6} {"笔":<4} {"胜率":<7} {"均收益":<9} {"累计":<9} {"PF":<6} {"连亏":<4} {"得分":<7}')
print('-'*82)
for r in results[:20]:
    print(f'{r["th"]:>5}% {r["stop"]:>4}%  {r["ratr"]:>5.1f}x    {r["cool"]:>4}d  {r["n"]:>3}  {r["wr"]*100:>5.1f}%  {r["avg"]:>+8.2f}% {r["cum"]*100:>+8.1f}% {r["pf"]:>5.2f}  {r["max_cl"]:>3}  {r["score"]:>5.3f}')

best = results[0]
print(f'\n=== 最优参数 ===')
print(f'阈值: {best["th"]}% | 止损: {best["stop"]}% | 动态回撤: {best["ratr"]}xATR | 冷却: {best["cool"]}d')
print(f'交易: {best["n"]}笔 | 胜率: {best["wr"]*100:.1f}% | 均收益: {best["avg"]:+.2f}% | 累计: {best["cum"]*100:+.1f}%')
print(f'PF: {best["pf"]:.2f} | 最大连亏: {best["max_cl"]}笔')
print('\n逐笔:')
for t in best['trades']:
    print(f'  {t["entry_date"]} -> {t["exit_date"]} | ${t["entry"]:.2f}->${t["exit"]:.2f} | {t["pnl"]:+.1f}% | {t["reason"]:8s} | {t["days"]:3d} | P2:{"Y" if t["phase2"] else "N"}')

# 正金字塔(3/7)
print(f'\n=== 正金字塔(3/7) ===')
th = best['th']; stop = best['stop']; ratr = best['ratr']; cool = best['cool']
ptrades = []
i = 20
while i < n:
    if not np.isnan(ret20.iloc[i]) and ret20.iloc[i] < th/100:
        entry_idx = i
        b1 = closes[min(entry_idx+1, n-1)]
        b2_idx = min(entry_idx+5, n-1)
        if b2_idx >= n:
            i += 1; continue
        b2 = closes[b2_idx]
        avg_price = 0.3*b1 + 0.7*b2
        stop_price = avg_price * (1 - stop/100)
        peak = max(b1, b2); exit_idx = None; exit_reason = None; phase2 = False
        for j in range(b2_idx+1, min(b2_idx+252, n)):
            cur = closes[j]
            if cur > peak: peak = cur
            ea = atr14_series.iloc[b2_idx] if b2_idx < len(atr14_series) else np.nan
            if not phase2 and not np.isnan(ea) and peak - avg_price >= ratr * ea:
                phase2 = True
            if cur <= stop_price:
                exit_idx = j; exit_reason = 'stop'; break
            if phase2:
                ca = atr14_series.iloc[j] if j < len(atr14_series) else ea
                if not np.isnan(ca) and cur <= peak - ratr * ca:
                    exit_idx = j; exit_reason = 'trailing'; break
        if exit_idx is None:
            exit_idx = min(b2_idx+120, n-1); exit_reason = 'timeout'
        exit_price = closes[exit_idx]
        pnl = (exit_price/avg_price - 1) * 100
        ptrades.append({
            'entry_date': r.iloc[entry_idx]['trade_date'],
            'avg': avg_price, 'exit': exit_price, 'pnl': pnl,
            'reason': exit_reason, 'days': exit_idx-entry_idx, 'phase2': phase2
        })
        i = exit_idx + 1
    else:
        i += 1

if ptrades:
    wins = [t for t in ptrades if t['pnl'] > 0]
    wr = len(wins)/len(ptrades)
    avg_pnl = np.mean([t['pnl'] for t in ptrades])
    cum = np.prod([1+t['pnl']/100 for t in ptrades]) - 1
    print(f'{len(ptrades)}笔 | 胜率: {wr*100:.1f}% | 均: {avg_pnl:+.2f}% | 累计: {cum*100:+.1f}%')
    for t in ptrades:
        print(f'  {t["entry_date"]} | 均价${t["avg"]:.2f}->${t["exit"]:.2f} | {t["pnl"]:+.1f}% | {t["reason"]:8s} | {t["days"]:3d}')
else:
    print('无信号')

print(f'\n=== 阈值灵敏度 ===')
for th in thresholds:
    sigs = sum(1 for i in range(20, n) if not np.isnan(ret20.iloc[i]) and ret20.iloc[i] < th/100)
    print(f'  {th}%: 原始信号{sigs}次, 年均{sigs/12.5:.1f}次')
