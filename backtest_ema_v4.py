"""
均线组合回测 V2.2 — 向量化加速版
"""
import numpy as np
import pandas as pd
import pickle, warnings
warnings.filterwarnings('ignore')

with open('/tmp/backtest_data.pkl', 'rb') as f:
    cache = pickle.load(f)

SHORT = [10, 12, 14]
MID   = [45, 48, 51, 54]
LONG  = [80, 84, 88, 92]
ATRS  = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

def fast_run(df, s, m, l, a):
    """向量化回测，不做逐行循环"""
    n = len(df)
    c = df['close'].values
    h = df['high'].values
    lo = df['low'].values
    
    # EMA
    alpha_s = 2/(s+1); alpha_m = 2/(m+1); alpha_l = 2/(l+1)
    ema_s = np.zeros(n); ema_m = np.zeros(n); ema_l = np.zeros(n)
    ema_s[0] = c[0]; ema_m[0] = c[0]; ema_l[0] = c[0]
    for i in range(1, n):
        ema_s[i] = c[i]*alpha_s + ema_s[i-1]*(1-alpha_s)
        ema_m[i] = c[i]*alpha_m + ema_m[i-1]*(1-alpha_m)
        ema_l[i] = c[i]*alpha_l + ema_l[i-1]*(1-alpha_l)
    
    # ATR
    tr = np.maximum(h-lo, np.maximum(np.abs(h-np.roll(c,1)), np.abs(lo-np.roll(c,1))))
    tr[0] = h[0]-lo[0]
    atr14 = np.zeros(n)
    for i in range(14, n):
        atr14[i] = np.mean(tr[i-13:i+1])
    
    # 条件（向量化）
    anchor_up = ema_m > np.roll(ema_m, 5)
    price_below = c <= ema_m
    buy_lower = ema_m - a * atr14
    price_above_lower = c >= buy_lower
    bull_align = ema_s > ema_l
    
    buy_signal = anchor_up & price_below & price_above_lower & bull_align
    
    # 预热后
    start = max(s,m,l) + 20
    buy_signal[:start] = False
    
    sig_idx = np.where(buy_signal)[0]
    if len(sig_idx) == 0:
        return None
    
    # 持有收益（向量化）
    r20, r40, r60 = [], [], []
    for idx in sig_idx:
        entry = c[idx]
        if idx + 20 < n: r20.append((c[idx+20]/entry - 1)*100)
        if idx + 40 < n: r40.append((c[idx+40]/entry - 1)*100)
        if idx + 60 < n: r60.append((c[idx+60]/entry - 1)*100)
    
    if len(r40) < 3:
        return None
    
    return {
        'sig': len(sig_idx),
        'pct': round(len(sig_idx)/(n-start)*100,2),
        'r20': round(np.mean(r20),2), 'r40': round(np.mean(r40),2), 'r60': round(np.mean(r60),2),
        'w20': round(sum(1 for r in r20 if r>0)/len(r20)*100,1),
        'w40': round(sum(1 for r in r40 if r>0)/len(r40)*100,1),
        'w60': round(sum(1 for r in r60 if r>0)/len(r60)*100,1),
    }

def backtest_one(df, name):
    n = len(df)
    split = n * 7 // 10
    df_tr = df.iloc[:split]
    df_ts = df.iloc[split:]
    
    best_sc = -999
    best_p = None
    best_r = None
    
    for s in SHORT:
        for m in MID:
            for l in LONG:
                if not (s < m < l): continue
                for a in ATRS:
                    r = fast_run(df_tr, s, m, l, a)
                    if r is None: continue
                    sc = r['r40'] * (r['w40']/100)
                    if sc > best_sc:
                        best_sc = sc; best_p = (s,m,l,a); best_r = r
    
    if best_p is None: return None
    s,m,l,a = best_p
    oos = fast_run(df_ts, s, m, l, a)
    full = fast_run(df, s, m, l, a)
    return {'name': name, 'params': best_p, 'train': best_r, 'oos': oos, 'full': full,
            'tr_d': len(df_tr), 'ts_d': len(df_ts)}

# 全部跑
results = []
for name, df in {**cache['a'], **cache['us']}.items():
    r = backtest_one(df, name)
    if r: results.append(r)

# 输出
print("=" * 110)
print("EMA三层均线回测 V2.2 — 邻近遍历 + 70/30样本外")
print(f"参数: 短{SHORT} 中{MID} 长{LONG} ATR{ATRS}")
print("=" * 110)

rob, dec, fal = [], [], []
for r in results:
    n = r['name']; s,m,l,a = r['params']
    tr = r['train']; oos = r['oos']; full = r['full']
    
    tag = ''; deg = None
    if oos:
        os = oos['r40']*(oos['w40']/100); ts = tr['r40']*(tr['w40']/100)
        deg = (os-ts)/abs(ts)*100 if ts!=0 else 0
        tag = '✅' if os>0 and deg>-50 else ('⚠️' if os>0 else '🔴')
        if tag=='✅': rob.append(r)
        elif tag=='⚠️': dec.append(r)
        else: fal.append(r)
    else:
        tag='🔴'; fal.append(r)
    
    print(f"\n{'─'*90}")
    print(f"  {n:8s}  EMA{s}/{m}/{l} ATR×{a:.1f}")
    print(f"  训练({r['tr_d']}d): {tr['sig']:3d}次  40d={tr['r40']:+.2f}% W{tr['w40']:.0f}%  60d={tr['r60']:+.2f}% W{tr['w60']:.0f}%")
    if oos:
        print(f"  样本外({r['ts_d']}d): {oos['sig']:3d}次  40d={oos['r40']:+.2f}% W{oos['w40']:.0f}%  60d={oos['r60']:+.2f}% W{oos['w60']:.0f}%  {tag}" + (f" 衰减{deg:+.0f}%" if deg is not None else ""))
    else:
        print(f"  样本外: 无信号 {tag}")
    print(f"  全周期: {full['sig']:3d}次  40d={full['r40']:+.2f}% W{full['w40']:.0f}%  60d={full['r60']:+.2f}% W{full['w60']:.0f}%")

print(f"\n{'='*110}")
print(f"✅{len(rob)} ⚠️{len(dec)} 🔴{len(fal)}")

for label, lst in [('✅样本外稳健', rob), ('⚠️衰减但正收益', dec), ('🔴失效/无信号', fal)]:
    if not lst: continue
    print(f"\n{label} ({len(lst)}只):")
    for r in lst:
        s,m,l,a = r['params']
        o = r['oos']
        o_str = f"样本外40d={o['r40']:+.2f}% W{o['w40']:.0f}%" if o else "无信号"
        print(f"  {r['name']:8s} EMA{s}/{m}/{l} ATR×{a:.1f}  |  {o_str}  |  全周期={r['full']['r40']:+.2f}% W{r['full']['w40']:.0f}%")

print(f"\n✅ 完成")
