#!/usr/bin/env python3
"""MA回踩第二轮（快速版）— 预计算所有指标，向量化回测"""
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

VOL_THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
MACD_WINDOWS = [1, 2, 3, 4, 5]
HARD_STOPS = [-0.02, -0.03, -0.04, -0.05, -0.06]
ATR_MULTS = [1.5, 2.0, 2.5, 3.0, 3.5]
MAX_HOLDS = [30, 50, 70, 90, 120]

def compute_macd(close):
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    diff = ema_fast - ema_slow
    dea = diff.ewm(span=9, adjust=False).mean()
    bar = 2 * (diff - dea)
    return bar

def backtest_vectorized(df, ma_n, tol, tp, vol_thresh, macd_win, hard_stop, atr_mult, max_hold):
    """向量化回测——单组参数"""
    n = len(df)
    
    # 预计算
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    open_ = df['open'].values
    ma = df['ma'].values
    ma60 = df['ma60'].values
    vol_ratio = df['vol_ratio'].values
    atr14 = df['atr14'].values
    macd_golden = df['macd_golden'].values
    
    trades = []
    in_pos = False
    entry_i = -1
    
    i = 60
    while i < n:
        if np.isnan(ma[i]) or np.isnan(ma60[i]):
            i += 1
            continue
        
        # 牛市判定
        is_bull = ma60[i] > ma60[i-20] and close[i] > ma60[i]
        if not is_bull:
            i += 1
            continue
        
        if not in_pos:
            # 入场
            price_ok = abs(close[i] - ma[i]) / ma[i] <= tol
            vol_ok = vol_ratio[i] < vol_thresh
            macd_ok = macd_golden[max(0,i-macd_win+1):i+1].sum() > 0
            
            if price_ok and vol_ok and macd_ok:
                entry_i = i
                entry_price = close[i]
                entry_atr = atr14[i]
                in_pos = True
        else:
            # 退出
            entry_price = close[entry_i]
            entry_atr_val = atr14[entry_i]
            
            hard_stop_px = entry_price * (1 + hard_stop)
            atr_stop_px = entry_price - atr_mult * entry_atr_val
            stop_loss = min(hard_stop_px, atr_stop_px)
            take_profit = entry_price * (1 + tp)
            hold_days = i - entry_i
            
            exit_reason = None
            exit_price = None
            
            if low[i] <= stop_loss:
                exit_reason = 'stop'
                exit_price = stop_loss
            elif high[i] >= take_profit:
                exit_reason = 'tp'
                exit_price = take_profit
            elif hold_days >= max_hold:
                exit_reason = 'maxhold'
                exit_price = close[i]
            
            if exit_reason:
                ret = (exit_price - entry_price) / entry_price
                trades.append({
                    'entry': entry_i, 'exit': i,
                    'return': ret, 'reason': exit_reason,
                    'hold_days': hold_days,
                })
                in_pos = False
                entry_i = -1
                # 重置到入场次日，继续搜索
                i = entry_i
                entry_i = -1
        
        i += 1
    
    return trades

def analyze_trades(trades):
    n = len(trades)
    if n == 0:
        return None
    
    rets = np.array([t['return'] for t in trades])
    wins = np.sum(rets > 0)
    wr = wins / n
    avg_ret = np.mean(rets)
    cum_ret = np.prod(1 + rets) - 1
    sharpe = np.mean(rets) / np.std(rets) * np.sqrt(n) if np.std(rets) > 0 else 0
    
    max_lose_streak = 0
    streak = 0
    for r in rets:
        if r <= 0:
            streak += 1
            max_lose_streak = max(max_lose_streak, streak)
        else:
            streak = 0
    
    return {
        'n_trades': n, 'wr': wr, 'avg_ret': avg_ret, 'cum_ret': cum_ret,
        'sharpe': sharpe, 'max_lose': max_lose_streak,
    }

def main():
    all_results = {}
    
    for ticker, config in TICKERS.items():
        code = config['code']
        ma_n = config['ma']
        tol = config['tol']
        tp = config['tp']
        
        print(f"\n{'='*60}")
        print(f"回测: {ticker} | MA{ma_n}±{tol*100:.0f}% | TP+{tp*100:.0f}%")
        
        # 拉数据
        df = pro.fund_daily(ts_code=code, start_date='20180101', end_date='20260708')
        if df.empty:
            print(f"  {ticker}: 数据拉取失败")
            continue
        df = df.sort_values('trade_date').reset_index(drop=True)
        df['close'] = df['close'].astype(float)
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['vol'] = df['vol'].astype(float)
        
        # 预计算所有指标（只算一次）
        df['ma'] = df['close'].rolling(ma_n).mean()
        df['ma60'] = df['close'].rolling(60).mean()
        df['vol_ma20'] = df['vol'].rolling(20).mean()
        df['vol_ratio'] = df['vol'] / df['vol_ma20']
        
        # ATR
        high, low, close = df['high'], df['low'], df['close']
        prev_close = close.shift(1)
        tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
        df['atr14'] = tr.rolling(14).mean()
        
        # MACD金叉
        df['macd_bar'] = compute_macd(df['close'])
        df['macd_golden'] = ((df['macd_bar'] > 0) & (df['macd_bar'].shift(1) <= 0)).astype(int)
        
        total = len(VOL_THRESHOLDS) * len(MACD_WINDOWS) * len(HARD_STOPS) * len(ATR_MULTS) * len(MAX_HOLDS)
        print(f"  预计算完成，开始{total}组参数回测...")
        
        results = []
        done = 0
        for vt, mw, hs, am, mh in itertools.product(VOL_THRESHOLDS, MACD_WINDOWS, HARD_STOPS, ATR_MULTS, MAX_HOLDS):
            trades = backtest_vectorized(df, ma_n, tol, tp, vt, mw, hs, am, mh)
            stats = analyze_trades(trades)
            if stats:
                results.append({
                    'vol_thresh': vt, 'macd_win': mw, 'hard_stop': hs, 'atr_mult': am, 'max_hold': mh,
                    **stats,
                })
            done += 1
            if done % 750 == 0:
                print(f"    {done}/{total} ({done/total*100:.0f}%)")
        
        df_r = pd.DataFrame(results)
        df_r = df_r.sort_values('cum_ret', ascending=False)
        
        # Top 10
        print(f"\n  Top 10 (按累计收益):")
        print(f"  {'缩量':<6} {'MACD窗':<8} {'硬止损':<8} {'ATR×':<6} {'持仓':<6} {'笔数':<5} {'胜率':<7} {'均收益':<8} {'累计':<8} {'Sharpe':<7} {'连亏':<4}")
        for _, r in df_r.head(10).iterrows():
            print(f"  {r['vol_thresh']:<6.1f} {r['macd_win']:<8d} {r['hard_stop']:<8.0%} {r['atr_mult']:<6.1f} {r['max_hold']:<6d} {r['n_trades']:<5d} {r['wr']:<7.1%} {r['avg_ret']:<8.1%} {r['cum_ret']:<8.1%} {r['sharpe']:<7.3f} {r['max_lose']:<4d}")
        
        positive = df_r[df_r['cum_ret'] > 0]
        print(f"\n  正期望组合: {len(positive)}/{len(df_r)} ({len(positive)/len(df_r)*100:.1f}%)")
        if len(positive) > 0:
            p = positive
            print(f"  正期望中位数: 累计+{p['cum_ret'].median():.2%} / 胜率{p['wr'].median():.1%} / {p['n_trades'].median():.0f}笔")
        
        # 参数影响力
        print(f"\n  参数维度影响力（Top20% vs Bottom20%）:")
        top20 = df_r.head(max(1, len(df_r)//5))
        bot20 = df_r.tail(max(1, len(df_r)//5))
        for dim, col in [('缩量阈值', 'vol_thresh'), ('MACD窗口', 'macd_win'), ('硬止损%', 'hard_stop'), ('ATR倍数', 'atr_mult'), ('最大持仓', 'max_hold')]:
            print(f"    {dim}: Top均值{top20[col].mean():.3f} vs Bot均值{bot20[col].mean():.3f}")
        
        all_results[ticker] = df_r
    
    with open('/home/agent/cow/tmp/ma_round2_results.pkl', 'wb') as f:
        pickle.dump(all_results, f)
    print("\n✅ 完成")

if __name__ == '__main__':
    main()
