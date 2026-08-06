#!/usr/bin/env python3
"""底部反转三维确认回测 — L4样本外校验"""
import json, numpy as np, pandas as pd
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

with open('tmp/market_data.json') as f:
    raw = json.load(f)
all_data = raw.get('data', {})
fund_data = raw.get('fund_data', {})

params = {
    '513910': {'k': 2.7, 'stop_atr': 3.5}, '512100': {'k': 2.0, 'stop_atr': 3.0},
    '510500': {'k': 2.8, 'stop_atr': 2.5}, '588000': {'k': 4.7, 'stop_atr': 3.0},
    '510880': {'k': 2.0, 'stop_atr': 3.0}, '159530': {'k': 1.5, 'stop_atr': 4.0},
    '510300': {'k': 2.0, 'stop_atr': 4.0}, '159915': {'k': 2.0, 'stop_atr': 4.0},
    'BBJP': {'k': 4.3, 'stop_atr': 2.0}, 'VNM': {'k': 5.0, 'stop_atr': 1.5},
}

def calc_indicators(df):
    df = df.copy()
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA20'] = df['close'].rolling(20).mean()
    df['MA40'] = df['close'].rolling(40).mean()
    h, l, c = df['high'].astype(float), df['low'].astype(float), df['close'].astype(float)
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    df['ATR14'] = tr.rolling(14).mean()
    df['VOL_MA20'] = df['vol'].rolling(20).mean()
    df['vol_ratio'] = df['vol'] / df['VOL_MA20']
    df['pct_chg'] = df['close'].pct_change() * 100
    df['body'] = (df['close'] - df['open']).abs()
    df['body_ratio'] = df['body'] / df['ATR14']
    return df

def is_panic(df, i):
    return df.iloc[i]['pct_chg'] < -3 and df.iloc[i]['vol_ratio'] > 1.5

def is_stop(df, i):
    return df.iloc[i]['body_ratio'] < 0.3 and df.iloc[i]['vol_ratio'] < 0.8

def ma_decel(df, i):
    if i < 20: return False
    ma5, ma5_prev = df.iloc[i]['MA5'], df.iloc[i-1]['MA5']
    c1 = ma5 >= ma5_prev
    if i >= 5:
        c1b = abs(ma5 - df.iloc[i-5:i]['MA5'].min()) < 0.5 * df.iloc[i]['ATR14']
    else:
        c1b = False
    ma20, ma20_5 = df.iloc[i]['MA20'], df.iloc[i-5]['MA20'] if i >= 5 else df.iloc[i]['MA20']
    c2 = (ma20 - ma20_5) / ma20_5 * 100 > -0.3
    return (c1 or c1b) and c2

def check_2d(df, sig):
    for pi in range(max(0, sig-19), sig+1):
        if pi < 20: continue
        if is_panic(df, pi):
            for si in range(pi+1, sig+1):
                if is_stop(df, si): return True
    return False

def check_3d(df, sig):
    for pi in range(max(0, sig-19), sig+1):
        if pi < 20: continue
        if is_panic(df, pi):
            for si in range(pi+1, sig+1):
                if is_stop(df, si) and ma_decel(df, si): return True
    return False

def find_signals(df, p):
    bz = df['MA40'] - p['k'] * df['ATR14']
    sigs = []
    for i in range(40, len(df)):
        if pd.notna(df.iloc[i]['close']) and pd.notna(bz.iloc[i]):
            if df.iloc[i]['close'] <= bz.iloc[i]:
                sigs.append(i)
    return sigs

def sim_trade(df, sig, p, days=60):
    if sig + days >= len(df): return None
    e, ae = df.iloc[sig]['close'], df.iloc[sig]['ATR14']
    stop = max(e - p['stop_atr'] * ae, e * 0.85)
    b2 = min(sig+5, sig+days)
    avg = 0.3 * e + 0.7 * df.iloc[b2]['close']
    for i in range(sig+1, min(sig+days+1, len(df))):
        if df.iloc[i]['low'] <= stop:
            return (df.iloc[i]['close'] - avg) / avg * 100
        if i - sig >= 120:
            return (df.iloc[i]['close'] - avg) / avg * 100
    return (df.iloc[min(sig+days, len(df)-1)]['close'] - avg) / avg * 100

results = []
for tk, p in params.items():
    df = pd.DataFrame(fund_data.get(tk) or all_data.get(tk, []))
    if len(df) < 300: continue
    df = calc_indicators(df)
    sigs = find_signals(df, p)
    if not sigs: continue
    sp = int(len(sigs) * 0.7)
    ins, outs = sigs[:sp], sigs[sp:]

    def stats(slist, checker):
        rets = []
        for s in slist:
            if checker(df, s):
                r = sim_trade(df, s, p)
                if r is not None: rets.append(r)
        if not rets: return (0, 0.0, 0.0, 0.0)
        return (len(rets), round(sum(1 for x in rets if x>0)/len(rets)*100,1),
                round(np.mean(rets),2), round(np.mean(rets)/np.std(rets),3) if np.std(rets)>0 else 0.0)

    raw_in = stats(ins, lambda df,s: True)
    raw_out = stats(outs, lambda df,s: True)
    d2_in = stats(ins, check_2d)
    d2_out = stats(outs, check_2d)
    d3_in = stats(ins, check_3d)
    d3_out = stats(outs, check_3d)

    l4r = round(raw_out[1]/raw_in[1],2) if raw_in[1]>0 else 0
    l4d2 = round(d2_out[1]/d2_in[1],2) if d2_in[1]>0 else 0
    l4d3 = round(d3_out[1]/d3_in[1],2) if d3_in[1]>0 else 0

    results.append({'tk':tk,'total':len(sigs),
        'raw_in':raw_in,'raw_out':raw_out,'raw_l4':l4r,
        'd2_in':d2_in,'d2_out':d2_out,'d2_l4':l4d2,
        'd3_in':d3_in,'d3_out':d3_out,'d3_l4':l4d3})

print("="*110)
print("底部反转序列回测 — 全池反击标的 | L4样本外校验(70/30)")
print("="*110)
print(f"{'标的':<8} {'R2':<5} {'方案':<5} {'样本内':>28} {'样本外':>28} {'L4':>8}")
print(f"{'':8} {'':5} {'':5} {'笔 胜率  均收益  Sharpe':>24} {'笔 胜率  均收益  Sharpe':>24} {'胜率比':>8}")
print("-"*110)

for r in results:
    for label, si, so, l4 in [('原始',r['raw_in'],r['raw_out'],r['raw_l4']),
                                ('二维',r['d2_in'],r['d2_out'],r['d2_l4']),
                                ('三维',r['d3_in'],r['d3_out'],r['d3_l4'])]:
        if si[0]==0 and so[0]==0: continue
        ins = f"{si[0]:>3} {si[1]:>5.1f}% {si[2]:>+6.2f}% {si[3]:>6.3f}"
        outs = f"{so[0]:>3} {so[1]:>5.1f}% {so[2]:>+6.2f}% {so[3]:>6.3f}"
        flag = "✅" if l4>=0.7 else ("🟡" if l4>=0.5 else "🔴")
        print(f"{r['tk']:<8} {r['total']:<5} {label:<5} {ins}  {outs}  {flag}{l4:.2f}")

print("-"*110)
all_r = sum(r['raw_in'][0]+r['raw_out'][0] for r in results)
all_d2 = sum(r['d2_in'][0]+r['d2_out'][0] for r in results)
all_d3 = sum(r['d3_in'][0]+r['d3_out'][0] for r in results)
print(f"\n全池: 原始{all_r}笔 → 二维{all_d2}笔({round(all_d2/all_r*100,1)}%) → 三维{all_d3}笔({round(all_d3/all_r*100,1)}%)")

def wl4(key):
    wi,wo,ci,co=0,0,0,0
    for r in results:
        si,so=r[key+'_in'],r[key+'_out']
        if si[0]>0: wi+=si[1]*si[0]; ci+=si[0]
        if so[0]>0: wo+=so[1]*so[0]; co+=so[0]
    return round((wo/co)/(wi/ci),2) if ci>0 and co>0 else 0

print(f"加权L4: 原始{wl4('raw'):.2f} / 二维{wl4('d2'):.2f} / 三维{wl4('d3'):.2f}")
print("\n✅ 完成")
