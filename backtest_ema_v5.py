"""
均线组合回测 V2.3 — 预计算EMA矩阵 + 向量化扫描
"""
import numpy as np, pandas as pd, pickle, time, warnings
warnings.filterwarnings('ignore')

with open('/tmp/backtest_data.pkl', 'rb') as f:
    cache = pickle.load(f)

SHORT = [10, 12, 14]
MID   = [45, 48, 51, 54]
LONG  = [80, 84, 88, 92]
ATRS  = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
ALL_P = SHORT + MID + LONG  # 预先算好所有EMA

def precompute(df):
    """一次性预计算所有需要的EMA和ATR"""
    c = df['close'].values
    h = df['high'].values
    lo = df['low'].values
    n = len(c)
    
    # ATR(14)
    tr = np.maximum(h-lo, np.maximum(np.abs(h-np.roll(c,1)), np.abs(lo-np.roll(c,1))))
    tr[0] = h[0]-lo[0]
    atr = np.zeros(n)
    for i in range(14, n):
        atr[i] = np.mean(tr[i-13:i+1])
    
    # 所有EMA预计算
    ema_dict = {}
    for p in ALL_P:
        alpha = 2/(p+1)
        ema = np.zeros(n)
        ema[0] = c[0]
        for i in range(1, n):
            ema[i] = c[i]*alpha + ema[i-1]*(1-alpha)
        ema_dict[p] = ema
    
    return {'c': c, 'atr': atr, 'ema': ema_dict, 'n': n}

def scan_params(pre, s, m, l, a):
    """对给定参数返回信号和40日收益"""
    c = pre['c']; atr = pre['atr']; n = pre['n']
    es = pre['ema'][s]; em = pre['ema'][m]; el = pre['ema'][l]
    
    # 条件
    anchor_up = em[5:] > em[:-5]  # shift 5
    # 对齐：anchor_up[i] 对应原始索引 i+5
    start = max(s,m,l) + 20
    
    sig_idx = []
    for i in range(start, n):
        if anchor_up[i-5] and c[i] <= em[i] and c[i] >= em[i]-a*atr[i] and es[i] > el[i]:
            sig_idx.append(i)
    
    if len(sig_idx) == 0:
        return None
    
    r40 = [(c[i+40]/c[i]-1)*100 for i in sig_idx if i+40 < n]
    if len(r40) < 3:
        return None
    
    return {
        'sig': len(sig_idx),
        'r40': round(np.mean(r40), 2),
        'w40': round(sum(1 for r in r40 if r > 0) / len(r40) * 100, 1),
    }

def backtest_symbol(df, name):
    n = len(df); split = n * 7 // 10
    pre_tr = precompute(df.iloc[:split])
    pre_ts = precompute(df.iloc[split:])
    pre_full = precompute(df)
    
    best_sc = -999; best_p = None; best_r = None
    for s in SHORT:
        for m in MID:
            for l in LONG:
                if not (s < m < l): continue
                for a in ATRS:
                    r = scan_params(pre_tr, s, m, l, a)
                    if r is None: continue
                    sc = r['r40'] * (r['w40']/100)
                    if sc > best_sc:
                        best_sc = sc; best_p = (s,m,l,a); best_r = r
    
    if best_p is None: return None
    s,m,l,a = best_p
    oos = scan_params(pre_ts, s, m, l, a)
    full = scan_params(pre_full, s, m, l, a)
    return {'name': name, 'params': best_p, 'train': best_r, 'oos': oos, 'full': full}

# 主循环
t0 = time.time()
results = []
for name, df in {**cache['a'], **cache['us']}.items():
    r = backtest_symbol(df, name)
    if r: results.append(r)
    elapsed = time.time() - t0
    print(f'{name:8s} done ({elapsed:.0f}s total)', flush=True)

print(f'\nAll done in {time.time()-t0:.0f}s')

# 输出
print("=" * 110)
print("EMA三层均线回测 V2.3 — 邻近遍历 + 70/30样本外校验")
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
    print(f"  训练: {tr['sig']:3d}次  40d={tr['r40']:+.2f}% W{tr['w40']:.0f}%")
    if oos:
        print(f"  样本外: {oos['sig']:3d}次  40d={oos['r40']:+.2f}% W{oos['w40']:.0f}%  {tag}" + (f" 衰减{deg:+.0f}%" if deg is not None else ""))
    else:
        print(f"  样本外: 无信号 {tag}")
    print(f"  全周期: {full['sig']:3d}次  40d={full['r40']:+.2f}% W{full['w40']:.0f}%")

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
