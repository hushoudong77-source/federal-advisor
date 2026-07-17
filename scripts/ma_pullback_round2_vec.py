#!/usr/bin/env python3
"""MA回踩第二轮（纯向量化版）— 一次性预计算所有入场条件矩阵"""
import tushare as ts
import pandas as pd
import numpy as np
import itertools, pickle, warnings
warnings.filterwarnings('ignore')

pro = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

TICKERS = {
    '512100': {'code': '512100.SH', 'ma': 50, 'tol': 0.02, 'tp': 0.30},
    '510500': {'code': '510500.SH', 'ma': 20, 'tol': 0.02, 'tp': 0.15},
}

def load_and_precompute(code, ma_n):
    """拉数据+预计算所有指标"""
    df = pro.fund_daily(ts_code=code, start_date='20180101', end_date='20260708')
    df = df.sort_values('trade_date').reset_index(drop=True)
    for col in ['close','open','high','low','vol']:
        df[col] = df[col].astype(float)
    
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    v = df['vol'].values
    n = len(df)
    
    # MA
    ma = pd.Series(c).rolling(ma_n).mean().values
    ma60 = pd.Series(c).rolling(60).mean().values
    vol_ma20 = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_ma20
    
    # ATR14
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    tr[0] = 0
    atr14 = pd.Series(tr).rolling(14).mean().values
    
    # MACD
    ema_fast = pd.Series(c).ewm(span=12, adjust=False).mean().values
    ema_slow = pd.Series(c).ewm(span=26, adjust=False).mean().values
    diff = ema_fast - ema_slow
    dea = pd.Series(diff).ewm(span=9, adjust=False).mean().values
    bar = 2 * (diff - dea)
    golden = ((bar > 0) & (np.roll(bar,1) <= 0)).astype(int)
    
    # 牛市
    bull = np.zeros(n, dtype=bool)
    for i in range(60, n):
        if np.isnan(ma[i]) or np.isnan(ma60[i]):
            continue
        bull[i] = ma60[i] > ma60[i-20] and c[i] > ma60[i]
    
    return {
        'df': df, 'n': n,
        'close': c, 'high': h, 'low': l,
        'ma': ma, 'ma60': ma60,
        'vol_ratio': vol_ratio, 'atr14': atr14,
        'golden': golden, 'bull': bull,
    }

def run_grid(data, ma_n, tol, tp):
    """对单标的跑全网格"""
    c = data['close']
    h = data['high']
    l = data['low']
    ma = data['ma']
    vol_ratio = data['vol_ratio']
    atr14 = data['atr14']
    golden = data['golden']
    bull = data['bull']
    n = data['n']
    
    results = []
    total = 6*5*5*5*5
    done = 0
    
    for vt, mw, hs, am, mh in itertools.product(
        [0.5,0.6,0.7,0.8,0.9,1.0], [1,2,3,4,5],
        [-0.02,-0.03,-0.04,-0.05,-0.06], [1.5,2.0,2.5,3.0,3.5], [30,50,70,90,120]):
        
        # 入场条件矩阵（向量化）
        price_ok = np.abs(c - ma) / ma <= tol
        vol_ok = vol_ratio < vt
        
        # MACD近N日有金叉（滑动窗口）
        macd_ok = np.zeros(n, dtype=bool)
        for i in range(n):
            if golden[max(0,i-mw+1):i+1].sum() > 0:
                macd_ok[i] = True
        
        entry_signal = price_ok & vol_ok & macd_ok & bull
        
        # 序列回测（这部分必须串行，但已预计算所有条件）
        trades = []
        i = 60
        while i < n:
            if not bull[i]:
                i += 1
                continue
            
            if entry_signal[i]:
                entry_i = i
                entry_price = c[i]
                entry_atr = atr14[i]
                
                # 扫描退出
                hard_stop_px = entry_price * (1 + hs)
                atr_stop_px = entry_price - am * entry_atr
                stop_loss = min(hard_stop_px, atr_stop_px)
                take_profit = entry_price * (1 + tp)
                
                for j in range(i+1, min(n, i+mh+1)):
                    if l[j] <= stop_loss:
                        ret = (stop_loss - entry_price) / entry_price
                        trades.append({'return': ret, 'reason': 'stop', 'days': j-i})
                        i = j
                        break
                    elif h[j] >= take_profit:
                        ret = (take_profit - entry_price) / entry_price
                        trades.append({'return': ret, 'reason': 'tp', 'days': j-i})
                        i = j
                        break
                    elif j == i + mh:
                        ret = (c[j] - entry_price) / entry_price
                        trades.append({'return': ret, 'reason': 'maxhold', 'days': mh})
                        i = j
                        break
                else:
                    # 未触发任何退出（到数据末尾）
                    pass
            
            i += 1
        
        if len(trades) == 0:
            done += 1
            continue
        
        rets = np.array([t['return'] for t in trades])
        wins = np.sum(rets > 0)
        wr = wins / len(trades)
        avg_ret = np.mean(rets)
        cum_ret = np.prod(1 + rets) - 1
        sharpe = np.mean(rets) / np.std(rets) * np.sqrt(len(trades)) if np.std(rets) > 0 else 0
        
        max_lose_streak = 0
        streak = 0
        for r in rets:
            if r <= 0:
                streak += 1
                max_lose_streak = max(max_lose_streak, streak)
            else:
                streak = 0
        
        results.append({
            'vol_thresh': vt, 'macd_win': mw, 'hard_stop': hs, 'atr_mult': am, 'max_hold': mh,
            'n_trades': len(trades), 'wr': wr, 'avg_ret': avg_ret, 'cum_ret': cum_ret,
            'sharpe': sharpe, 'max_lose': max_lose_streak,
        })
        
        done += 1
        if done % 750 == 0:
            print(f"    {done}/{total} ({done/total*100:.0f}%)")
    
    return pd.DataFrame(results).sort_values('cum_ret', ascending=False)

def main():
    all_results = {}
    
    for ticker, config in TICKERS.items():
        code = config['code']
        ma_n = config['ma']
        tol = config['tol']
        tp = config['tp']
        
        print(f"\n{'='*60}")
        print(f"回测: {ticker} | MA{ma_n}±{tol*100:.0f}% | TP+{tp*100:.0f}% | 3750组合")
        
        data = load_and_precompute(code, ma_n)
        df_r = run_grid(data, ma_n, tol, tp)
        
        if df_r.empty:
            print(f"  {ticker}: 无有效结果")
            continue
        
        print(f"\n  Top 10:")
        print(f"  {'缩量':<6} {'MACD':<6} {'止损%':<7} {'ATR×':<6} {'持仓':<6} {'笔数':<5} {'胜率':<7} {'均收益':<8} {'累计':<8} {'Sharpe':<7} {'连亏':<4}")
        for _, r in df_r.head(10).iterrows():
            print(f"  {r['vol_thresh']:<6.1f} {r['macd_win']:<6d} {r['hard_stop']:<7.0%} {r['atr_mult']:<6.1f} {r['max_hold']:<6d} {r['n_trades']:<5d} {r['wr']:<7.1%} {r['avg_ret']:<8.1%} {r['cum_ret']:<8.1%} {r['sharpe']:<7.3f} {r['max_lose']:<4d}")
        
        p = df_r[df_r['cum_ret'] > 0]
        print(f"\n  正期望: {len(p)}/{len(df_r)} ({len(p)/len(df_r)*100:.1f}%)")
        if len(p) > 0:
            print(f"  正期望中位数: 累计+{p['cum_ret'].median():.2%} / 胜率{p['wr'].median():.1%} / {p['n_trades'].median():.0f}笔")
        
        all_results[ticker] = df_r
    
    with open('/home/agent/cow/tmp/ma_round2_results.pkl', 'wb') as f:
        pickle.dump(all_results, f)
    print("\n✅ 完成")

if __name__ == '__main__':
    main()
