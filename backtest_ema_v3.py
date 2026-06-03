"""
均线组合回测 V2.1 — 本地数据 + 邻近遍历 + 样本外校验
"""
import numpy as np
import pandas as pd
import pickle, warnings
warnings.filterwarnings('ignore')

# 加载缓存数据
with open('/tmp/backtest_data.pkl', 'rb') as f:
    cache = pickle.load(f)

SHORT_RANGE = [10, 12, 14]
MID_RANGE   = [45, 48, 51, 54]
LONG_RANGE  = [80, 84, 88, 92]
ATR_RANGE   = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

def run_segment(df, s, m, l, a):
    df = df.copy()
    df['ema_s'] = df['close'].ewm(span=s, adjust=False).mean()
    df['ema_m'] = df['close'].ewm(span=m, adjust=False).mean()
    df['ema_l'] = df['close'].ewm(span=l, adjust=False).mean()
    
    df['tr'] = np.maximum(df['high']-df['low'],
        np.maximum(abs(df['high']-df['close'].shift(1)),
                   abs(df['low']-df['close'].shift(1))))
    df['atr14'] = df['tr'].rolling(14).mean()
    
    df['anchor_up'] = df['ema_m'] > df['ema_m'].shift(5)
    df['price_below'] = df['close'] <= df['ema_m']
    df['buy_lower'] = df['ema_m'] - a * df['atr14']
    df['price_above_lower'] = df['close'] >= df['buy_lower']
    df['bull_align'] = df['ema_s'] > df['ema_l']
    df['buy_signal'] = df['anchor_up'] & df['price_below'] & df['price_above_lower'] & df['bull_align']
    
    min_pre = max(s,m,l) + 14 + 10
    df_v = df.iloc[min_pre:].reset_index(drop=True)
    if len(df_v) < 50:
        return None
    
    r20, r40, r60 = [], [], []
    for i in range(len(df_v)):
        if df_v['buy_signal'].iloc[i]:
            e = df_v['close'].iloc[i]
            if i+20 < len(df_v): r20.append((df_v['close'].iloc[i+20]/e-1)*100)
            if i+40 < len(df_v): r40.append((df_v['close'].iloc[i+40]/e-1)*100)
            if i+60 < len(df_v): r60.append((df_v['close'].iloc[i+60]/e-1)*100)
    
    sc = int(df_v['buy_signal'].sum())
    if sc == 0 or len(r40) < 3:
        return None
    
    return {
        'signal_count': sc,
        'signal_pct': round(sc/len(df_v)*100,2),
        'avg_20d': round(np.mean(r20),2) if r20 else None,
        'avg_40d': round(np.mean(r40),2) if r40 else None,
        'avg_60d': round(np.mean(r60),2) if r60 else None,
        'wr_20d': round(sum(1 for r in r20 if r>0)/len(r20)*100,1) if r20 else None,
        'wr_40d': round(sum(1 for r in r40 if r>0)/len(r40)*100,1) if r40 else None,
        'wr_60d': round(sum(1 for r in r60 if r>0)/len(r60)*100,1) if r60 else None,
        'n_20d': len(r20), 'n_40d': len(r40), 'n_60d': len(r60),
    }

def backtest_symbol(df, name):
    n = len(df)
    split = int(n * 0.70)
    df_train = df.iloc[:split].copy()
    df_test = df.iloc[split:].copy()
    
    best_score = -999
    best_params = None
    best_train = None
    
    for s in SHORT_RANGE:
        for m in MID_RANGE:
            for l in LONG_RANGE:
                if not (s < m < l):
                    continue
                for a in ATR_RANGE:
                    r = run_segment(df_train, s, m, l, a)
                    if r is None:
                        continue
                    score = r['avg_40d'] * (r['wr_40d']/100)
                    if score > best_score:
                        best_score = score
                        best_params = (s,m,l,a)
                        best_train = r
    
    if best_params is None:
        return None
    
    s,m,l,a = best_params
    oos = run_segment(df_test, s, m, l, a)
    full = run_segment(df, s, m, l, a)
    
    return {'name': name, 'params': best_params, 'train': best_train, 'oos': oos, 'full': full,
            'train_days': len(df_train), 'test_days': len(df_test)}

# 跑全部
results = []
for name, df in cache['a'].items():
    r = backtest_symbol(df, name)
    if r: results.append(r)

for name, df in cache['us'].items():
    r = backtest_symbol(df, name)
    if r: results.append(r)

# 输出
print("=" * 120)
print("均线组合回测 V2.1 — 邻近遍历 + 70/30样本外校验")
print(f"参数空间: 短{SHORT_RANGE} × 中{MID_RANGE} × 长{LONG_RANGE} × ATR{ATR_RANGE}")
print("=" * 120)

robust, decay, fail = [], [], []

for r in results:
    n = r['name']
    s,m,l,a = r['params']
    tr = r['train']
    oos = r['oos']
    full = r['full']
    
    if oos and oos['avg_40d'] is not None:
        oos_score = oos['avg_40d'] * (oos['wr_40d']/100)
        train_score = tr['avg_40d'] * (tr['wr_40d']/100)
        deg = (oos_score - train_score) / abs(train_score) * 100 if train_score != 0 else 0
        if oos_score > 0 and deg > -50:
            tag = '✅稳健'
            robust.append({**r, 'deg': deg})
        elif oos_score > 0:
            tag = '⚠️衰减'
            decay.append({**r, 'deg': deg})
        else:
            tag = '🔴失效'
            fail.append({**r, 'deg': deg})
    else:
        tag = '🔴无信号'
        oos_score = None
        deg = None
        fail.append({**r, 'deg': None})
    
    print(f"\n{'─'*100}")
    print(f"  {n:8s}  EMA{s}/{m}/{l}  ATR×{a:.1f}")
    print(f"  训练({r['train_days']}天): 信号{tr['signal_count']:3d}次  40d={tr['avg_40d']:+.2f}% W{tr['wr_40d']:.0f}%  60d={tr['avg_60d']:+.2f}% W{tr['wr_60d']:.0f}%")
    if oos:
        print(f"  样本外({r['test_days']}天): 信号{oos['signal_count']:3d}次  40d={oos['avg_40d']:+.2f}% W{oos['wr_40d']:.0f}%  60d={oos['avg_60d']:+.2f}% W{oos['wr_60d']:.0f}%  → {tag}" + (f" (衰减{deg:+.0f}%)" if deg is not None else ""))
    else:
        print(f"  样本外: 无有效信号 → {tag}")
    print(f"  全周期: 信号{full['signal_count']:3d}次  40d={full['avg_40d']:+.2f}% W{full['wr_40d']:.0f}%  60d={full['avg_60d']:+.2f}% W{full['wr_60d']:.0f}%")

# 汇总
print(f"\n\n{'='*120}")
print(f"汇总: ✅稳健 {len(robust)} | ⚠️衰减 {len(decay)} | 🔴失效 {len(fail)}")
print(f"{'='*120}")

if robust:
    print(f"\n✅ 样本外稳健 ({len(robust)}只):")
    for r in robust:
        print(f"  {r['name']:8s}  EMA{int(r['params'][0])}/{int(r['params'][1])}/{int(r['params'][2])} ATR×{r['params'][3]:.1f}  "
              f"样本外40d={r['oos']['avg_40d']:+.2f}% W{r['oos']['wr_40d']:.0f}%  全周期={r['full']['avg_40d']:+.2f}% W{r['full']['wr_40d']:.0f}%")

if decay:
    print(f"\n⚠️ 衰减但正收益 ({len(decay)}只):")
    for r in decay:
        print(f"  {r['name']:8s}  EMA{int(r['params'][0])}/{int(r['params'][1])}/{int(r['params'][2])} ATR×{r['params'][3]:.1f}  "
              f"样本外40d={r['oos']['avg_40d']:+.2f}% W{r['oos']['wr_40d']:.0f}%  衰减{r['deg']:+.0f}%")

if fail:
    print(f"\n🔴 失效/无信号 ({len(fail)}只):")
    for r in fail:
        oos_str = f"样本外40d={r['oos']['avg_40d']:+.2f}% W{r['oos']['wr_40d']:.0f}%" if r['oos'] else "无信号"
        print(f"  {r['name']:8s}  EMA{int(r['params'][0])}/{int(r['params'][1])}/{int(r['params'][2])} ATR×{r['params'][3]:.1f}  {oos_str}")

print(f"\n✅ 完成")
