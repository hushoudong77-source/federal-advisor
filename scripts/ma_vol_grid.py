#!/usr/bin/env python3
"""MA回踩+成交量+硬止损 全量网格回测 — 512100 & 510500"""
import tushare as ts, pandas as pd, numpy as np, sys, json
from itertools import product
import warnings; warnings.filterwarnings('ignore')

pro = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

# 配置
CONFIG = {
    '512100': {'code': '512100.SH', 'tp': 0.20},
    '510500': {'code': '510500.SH', 'tp': 0.15},
}

GRID = {
    'ma_p': [20, 30, 40, 50, 60],
    'tol': [0.02, 0.03, 0.04, 0.05],
    'vol_t': [0.6, 0.7, 0.8, 0.9, 1.0],
    'sl': [-0.02, -0.03, -0.04, -0.05, -0.06],
}

def pull(code):
    df = pro.fund_daily(ts_code=code, start_date='20180101', end_date='20260708')
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date').reset_index(drop=True)
    for c in ['close','open','high','low','vol']:
        df[c] = df[c].astype(float)
    return df

def backtest(df, ma_p, tol, vol_t, sl, tp):
    """向量化入场信号 + 逐笔模拟离场"""
    n = len(df)
    df = df.copy()
    df['MA'] = df['close'].rolling(ma_p).mean()
    df['V20'] = df['vol'].rolling(20).mean()
    
    # 入场条件向量化
    df['bull'] = (df['close'] > df['MA']) & (df['MA'] > df['MA'].shift(1))
    df['prev_above'] = df['close'].shift(1) > df['MA'].shift(1)
    df['low_touch'] = (abs(df['low'] - df['MA']) / df['MA']) <= tol
    df['vol_ok'] = (df['vol'] / df['V20']) < vol_t
    df['signal'] = df['bull'] & df['prev_above'] & df['low_touch'] & df['vol_ok']
    
    trades = []
    in_pos = False
    ep = 0; ei = 0; sl_p = 0; tp_p = 0
    
    for i in range(ma_p + 20, n):
        row = df.iloc[i]
        if not in_pos:
            if row['signal']:
                in_pos = True
                ep = row['close']
                ei = i
                sl_p = ep * (1 + sl)
                tp_p = ep * (1 + tp)
        else:
            h, l, c = row['high'], row['low'], row['close']
            days = i - ei
            if l <= sl_p:
                trades.append({'pnl': (sl_p-ep)/ep, 'exit': '止损', 'days': days})
                in_pos = False
            elif h >= tp_p:
                trades.append({'pnl': (tp_p-ep)/ep, 'exit': '止盈', 'days': days})
                in_pos = False
            elif days >= 120:
                trades.append({'pnl': (c-ep)/ep, 'exit': '强制', 'days': days})
                in_pos = False
    
    return trades

def score(trades):
    if not trades: return {'n':0,'wr':0,'total':0,'avg':0,'sr':0,'streak':0,'pf':0,'score':-999}
    pnls = [t['pnl'] for t in trades]
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    wr = wins/n
    total = sum(pnls)
    avg = np.mean(pnls)
    sr = avg/np.std(pnls) if np.std(pnls)>0 else 0
    streak = cur = 0
    for p in pnls:
        cur = cur+1 if p<=0 else 0; streak = max(streak,cur)
    aw = np.mean([p for p in pnls if p>0]) if wins>0 else 0
    al = abs(np.mean([p for p in pnls if p<=0])) if n-wins>0 else 0
    pf = aw/al if al>0 else 99
    sc = wr*0.30 + min(avg*100,10)*0.30 + min(pf,5)*0.20 + (n/100)*0.15 - streak*0.05
    return {'n':n,'wr':wr,'total':total,'avg':avg,'sr':sr,'streak':streak,'pf':pf,'score':sc}

# 运行
combos = list(product(*GRID.values()))
results_all = {}

for name, cfg in CONFIG.items():
    print(f'\n===== {name} (TP+{cfg["tp"]*100:.0f}%) =====')
    df = pull(cfg['code'])
    print(f'数据: {len(df)}条, {df.trade_date.min().date()} ~ {df.trade_date.max().date()}')
    
    res = []
    for idx, (ma_p, tol, vol_t, sl) in enumerate(combos):
        trades = backtest(df, ma_p, tol, vol_t, sl, cfg['tp'])
        r = score(trades)
        r.update({'ma_p':ma_p,'tol':tol,'vol_t':vol_t,'sl':sl})
        res.append(r)
        if (idx+1) % 100 == 0:
            print(f'  进度: {idx+1}/{len(combos)}')
    
    rdf = pd.DataFrame(res).sort_values('score', ascending=False)
    results_all[name] = rdf
    
    # Top 10
    print(f'\n  🏆 Top 10:')
    for rank, (_, row) in enumerate(rdf.head(10).iterrows(), 1):
        print(f'  {rank}. MA{int(row.ma_p):2d} ±{row.tol*100:.0f}% vol<{row.vol_t:.1f} sl−{abs(row.sl)*100:.0f}% | '
              f'{int(row.n):2d}笔 胜率{row.wr*100:4.0f}% 累计{row.total*100:+6.1f}% '
              f'SR{row.sr:+.3f} PF{row.pf:.2f} score={row.score:.4f}')
    
    # 统计
    n_pos = (rdf['total']>0).sum()
    n_zero = (rdf['n']==0).sum()
    print(f'\n  正期望: {n_pos}/{len(rdf)} ({n_pos/len(rdf)*100:.1f}%) | 零信号: {n_zero}')
    
    # 边际
    for dim, key, fmt in [('MA周期','ma_p','{}'),('容忍度','tol','±{:.0f}%'),('缩量','vol_t','<{:.1f}'),('硬止损','sl','−{:.0f}%')]:
        g = rdf.groupby(key)['score'].mean()
        print(f'  {dim} 边际最优: {fmt.format(g.idxmax())} (得分{g.max():.4f})')

# 保存
import os
os.makedirs('/home/agent/cow/tmp', exist_ok=True)
for name in results_all:
    results_all[name].to_csv(f'/home/agent/cow/tmp/{name}_grid_ma_vol.csv', index=False)
print('\n✅ 完成，结果已保存')
