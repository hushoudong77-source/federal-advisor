#!/usr/bin/env python3
"""MA回踩第二轮 V2 — 修复格式+分段保存"""
import tushare as ts
import pandas as pd
import numpy as np
import itertools, pickle, warnings
warnings.filterwarnings('ignore')

pro = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

def load_data(code, ma_n):
    df = pro.fund_daily(ts_code=code, start_date='20180101', end_date='20260708')
    df = df.sort_values('trade_date').reset_index(drop=True)
    for col in ['close','open','high','low','vol']:
        df[col] = df[col].astype(float)
    
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    v = df['vol'].values
    n = len(df)
    
    ma = pd.Series(c).rolling(ma_n).mean().values
    ma60 = pd.Series(c).rolling(60).mean().values
    vol_ratio = v / pd.Series(v).rolling(20).mean().values
    
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    tr[0] = 0
    atr14 = pd.Series(tr).rolling(14).mean().values
    
    ema_fast = pd.Series(c).ewm(span=12, adjust=False).mean().values
    ema_slow = pd.Series(c).ewm(span=26, adjust=False).mean().values
    bar = 2 * ((ema_fast-ema_slow) - pd.Series(ema_fast-ema_slow).ewm(span=9, adjust=False).mean().values)
    golden = ((bar > 0) & (np.roll(bar,1) <= 0)).astype(int)
    
    bull = np.zeros(n, dtype=bool)
    for i in range(60, n):
        if not np.isnan(ma[i]) and not np.isnan(ma60[i]):
            bull[i] = ma60[i] > ma60[i-20] and c[i] > ma60[i]
    
    return {'c':c,'h':h,'l':l,'ma':ma,'vol_ratio':vol_ratio,'atr14':atr14,'golden':golden,'bull':bull,'n':n}

def run_one(ticker, code, ma_n, tol, tp):
    print(f"\n{'='*60}")
    print(f"回测: {ticker} | MA{ma_n}±{tol*100:.0f}% | TP+{tp*100:.0f}%")
    
    data = load_data(code, ma_n)
    c, h, l, ma, vol_ratio, atr14, golden, bull, n = (
        data['c'], data['h'], data['l'], data['ma'],
        data['vol_ratio'], data['atr14'], data['golden'], data['bull'], data['n']
    )
    
    results = []
    params = list(itertools.product(
        [0.5,0.6,0.7,0.8,0.9,1.0], [1,2,3,4,5],
        [-0.02,-0.03,-0.04,-0.05,-0.06], [1.5,2.0,2.5,3.0,3.5], [30,50,70,90,120]))
    total = len(params)
    
    for idx, (vt, mw, hs, am, mh) in enumerate(params):
        # 入场信号
        price_ok = np.abs(c - ma) / ma <= tol
        vol_ok = vol_ratio < vt
        macd_ok = np.zeros(n, dtype=bool)
        for i in range(n):
            macd_ok[i] = golden[max(0,i-mw+1):i+1].sum() > 0
        entry_signal = price_ok & vol_ok & macd_ok & bull
        
        trades = []
        i = 60
        while i < n:
            if not bull[i]:
                i += 1
                continue
            if entry_signal[i]:
                ep = c[i]
                ea = atr14[i]
                sl = min(ep*(1+hs), ep-am*ea)
                tp_px = ep*(1+tp)
                
                found = False
                for j in range(i+1, min(n, i+mh+1)):
                    if l[j] <= sl:
                        trades.append((sl-ep)/ep)
                        i = j
                        found = True
                        break
                    elif h[j] >= tp_px:
                        trades.append((tp_px-ep)/ep)
                        i = j
                        found = True
                        break
                    elif j == i + mh:
                        trades.append((c[j]-ep)/ep)
                        i = j
                        found = True
                        break
                if not found:
                    pass
            i += 1
        
        if not trades:
            continue
        
        rets = np.array(trades)
        wr = (rets>0).sum()/len(rets)
        cum = np.prod(1+rets)-1
        sharpe = np.mean(rets)/np.std(rets)*np.sqrt(len(rets)) if np.std(rets)>0 else 0
        
        streak = max_streak = 0
        for r in rets:
            if r <= 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        
        results.append([vt, mw, hs, am, mh, len(rets), wr, np.mean(rets), cum, sharpe, max_streak])
        
        if (idx+1) % 500 == 0:
            print(f"  {idx+1}/{total} ({(idx+1)/total*100:.0f}%)")
    
    cols = ['vol','macd_win','hard_stop','atr_mult','max_hold','n','wr','avg_ret','cum_ret','sharpe','max_lose']
    df_r = pd.DataFrame(results, columns=cols).sort_values('cum_ret', ascending=False)
    
    print(f"\n  Top 10:")
    print(f"  {'缩量':<6} {'MACD':<6} {'止损%':<7} {'ATR×':<6} {'持仓':<6} {'笔数':<5} {'胜率':<7} {'均收益':<8} {'累计':<10} {'Sharpe':<7} {'连亏':<4}")
    for _, r in df_r.head(10).iterrows():
        print(f"  {r['vol']:<6.1f} {r['macd_win']:<6.0f} {r['hard_stop']:<7.0%} {r['atr_mult']:<6.1f} {r['max_hold']:<6.0f} {r['n']:<5.0f} {r['wr']:<7.1%} {r['avg_ret']:<8.1%} {r['cum_ret']:<10.1%} {r['sharpe']:<7.3f} {r['max_lose']:<4.0f}")
    
    p = df_r[df_r['cum_ret']>0]
    print(f"\n  正期望: {len(p)}/{len(df_r)} ({len(p)/len(df_r)*100:.1f}%)")
    if len(p)>0:
        print(f"  正期望中位数: 累计+{p['cum_ret'].median():.2%} / 胜率{p['wr'].median():.1%} / {p['n'].median():.0f}笔")
    
    return df_r

# 主程序
r1 = run_one('512100', '512100.SH', 50, 0.02, 0.30)
r2 = run_one('510500', '510500.SH', 20, 0.02, 0.15)

with open('/home/agent/cow/tmp/ma_round2_results.pkl', 'wb') as f:
    pickle.dump({'512100':r1, '510500':r2}, f)
print("\n✅ 完成，已保存")
