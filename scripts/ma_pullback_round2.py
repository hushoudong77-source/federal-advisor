#!/usr/bin/env python3
"""MA回踩第二轮 — 三指标（MA+缩量+MACD金叉）× 止损ATR × 最大持仓 全量网格回测"""
import tushare as ts
import pandas as pd
import numpy as np
import itertools, json, sys, warnings
warnings.filterwarnings('ignore')

pro = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

# ============ 配置 ============
TICKERS = {
    '512100': {'code': '512100.SH', 'ma': 50, 'tol': 0.02, 'tp': 0.30},
    '510500': {'code': '510500.SH', 'ma': 20, 'tol': 0.02, 'tp': 0.15},
}

# 搜索空间
VOL_THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
MACD_WINDOWS = [1, 2, 3, 4, 5]
HARD_STOPS = [-0.02, -0.03, -0.04, -0.05, -0.06]
ATR_MULTS = [1.5, 2.0, 2.5, 3.0, 3.5]
MAX_HOLDS = [30, 50, 70, 90, 120]

def compute_macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    diff = ema_fast - ema_slow
    dea = diff.ewm(span=signal, adjust=False).mean()
    bar = 2 * (diff - dea)
    return diff, dea, bar

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def backtest_ticker(ticker, config):
    code = config['code']
    ma_n = config['ma']
    tol = config['tol']
    tp = config['tp']
    
    # 拉数据
    df = pro.fund_daily(ts_code=code, start_date='20180101', end_date='20260708')
    if df.empty:
        return None
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['close'] = df['close'].astype(float)
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['vol'] = df['vol'].astype(float)
    
    # 计算指标
    df['ma'] = df['close'].rolling(ma_n).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['vol_ma20'] = df['vol'].rolling(20).mean()
    df['vol_ratio'] = df['vol'] / df['vol_ma20']
    df['atr14'] = compute_atr(df, 14)
    
    # MACD
    diff, dea, bar = compute_macd(df['close'])
    df['macd_bar'] = bar
    # 金叉信号: BAR>0 且前日BAR<=0
    df['macd_golden'] = ((df['macd_bar'] > 0) & (df['macd_bar'].shift(1) <= 0)).astype(int)
    
    results = []
    
    for vt, mw, hs, am, mh in itertools.product(VOL_THRESHOLDS, MACD_WINDOWS, HARD_STOPS, ATR_MULTS, MAX_HOLDS):
        trades = []
        in_position = False
        entry_idx = None
        
        for i in range(60, len(df)):
            row = df.iloc[i]
            
            # 牛市判定
            if row['ma60'] != row['ma60'] or row['ma'] != row['ma']:
                continue
            is_bull = row['ma60'] > df.iloc[i-20]['ma60'] and row['close'] > row['ma60']
            if not is_bull:
                continue
            
            if not in_position:
                # 入场条件: MA回踩 + 缩量 + 近N日有MACD金叉
                price_in_zone = abs(row['close'] - row['ma']) / row['ma'] <= tol
                vol_shrink = row['vol_ratio'] < vt
                macd_recent = df.iloc[max(0,i-mw+1):i+1]['macd_golden'].sum() > 0
                
                if price_in_zone and vol_shrink and macd_recent:
                    entry_idx = i
                    entry_price = row['close']
                    entry_ma = row['ma']
                    entry_atr = row['atr14']
                    in_position = True
                    trades.append({
                        'entry_date': row['trade_date'],
                        'entry_price': entry_price,
                        'entry_ma': entry_ma,
                    })
            else:
                # 退出判定
                row_entry = df.iloc[entry_idx]
                entry_price = row_entry['close']
                entry_atr_val = row_entry['atr14']
                
                # 止损: min(硬止损, ATR止损)
                hard_stop = entry_price * (1 + hs)
                atr_stop = entry_price - am * entry_atr_val
                stop_loss = min(hard_stop, atr_stop)
                
                # 止盈
                take_profit = entry_price * (1 + tp)
                
                # 最大持仓
                hold_days = i - entry_idx
                
                exit_reason = None
                exit_price = None
                
                if row['low'] <= stop_loss:
                    exit_reason = 'stop_loss'
                    exit_price = stop_loss
                elif row['high'] >= take_profit:
                    exit_reason = 'take_profit'
                    exit_price = take_profit
                elif hold_days >= mh:
                    exit_reason = 'max_hold'
                    exit_price = row['close']
                
                if exit_reason:
                    ret = (exit_price - entry_price) / entry_price
                    trades[-1].update({
                        'exit_date': row['trade_date'],
                        'exit_price': exit_price,
                        'exit_reason': exit_reason,
                        'return': ret,
                        'hold_days': hold_days,
                    })
                    in_position = False
                    entry_idx = None
        
        # 统计
        closed = [t for t in trades if 'return' in t]
        n_trades = len(closed)
        if n_trades == 0:
            continue
        
        wins = sum(1 for t in closed if t['return'] > 0)
        wr = wins / n_trades
        avg_ret = np.mean([t['return'] for t in closed])
        cum_ret = np.prod([1 + t['return'] for t in closed]) - 1
        rets = [t['return'] for t in closed]
        sharpe = np.mean(rets) / np.std(rets) * np.sqrt(n_trades) if np.std(rets) > 0 else 0
        
        # 连亏
        max_lose_streak = 0
        current_streak = 0
        for t in closed:
            if t['return'] <= 0:
                current_streak += 1
                max_lose_streak = max(max_lose_streak, current_streak)
            else:
                current_streak = 0
        
        results.append({
            'vol_thresh': vt, 'macd_win': mw, 'hard_stop': hs, 'atr_mult': am, 'max_hold': mh,
            'n_trades': n_trades, 'wr': wr, 'avg_ret': avg_ret, 'cum_ret': cum_ret,
            'sharpe': sharpe, 'max_lose': max_lose_streak,
            'trades': trades,
        })
    
    return results

def main():
    all_results = {}
    
    for ticker, config in TICKERS.items():
        print(f"\n{'='*60}")
        print(f"回测: {ticker} | MA{config['ma']}±{config['tol']*100:.0f}% | TP+{config['tp']*100:.0f}%")
        print(f"搜索: 缩量{len(VOL_THRESHOLDS)}×MACD窗{len(MACD_WINDOWS)}×硬止损{len(HARD_STOPS)}×ATR{len(ATR_MULTS)}×持仓{len(MAX_HOLDS)} = {len(VOL_THRESHOLDS)*len(MACD_WINDOWS)*len(HARD_STOPS)*len(ATR_MULTS)*len(MAX_HOLDS)}组合")
        
        results = backtest_ticker(ticker, config)
        if not results:
            print(f"  {ticker}: 数据拉取失败")
            continue
        
        df_r = pd.DataFrame(results)
        # 按累计收益排序
        df_r = df_r.sort_values('cum_ret', ascending=False)
        
        # Top 10
        print(f"\n  Top 10 (按累计收益):")
        print(f"  {'缩量':<6} {'MACD窗':<8} {'硬止损':<8} {'ATR×':<6} {'持仓':<6} {'笔数':<5} {'胜率':<7} {'均收益':<8} {'累计':<8} {'Sharpe':<7} {'连亏':<4}")
        for _, r in df_r.head(10).iterrows():
            print(f"  {r['vol_thresh']:<6.1f} {r['macd_win']:<8d} {r['hard_stop']:<8.0%} {r['atr_mult']:<6.1f} {r['max_hold']:<6d} {r['n_trades']:<5d} {r['wr']:<7.1%} {r['avg_ret']:<8.1%} {r['cum_ret']:<8.1%} {r['sharpe']:<7.3f} {r['max_lose']:<4d}")
        
        # 正期望统计
        positive = df_r[df_r['cum_ret'] > 0]
        print(f"\n  正期望组合: {len(positive)}/{len(df_r)} ({len(positive)/len(df_r)*100:.1f}%)")
        if len(positive) > 0:
            print(f"  正期望中位数: 累计+{positive['cum_ret'].median():.2%} / 胜率{positive['wr'].median():.1%} / {positive['n_trades'].median():.0f}笔")
        
        # 参数统计
        print(f"\n  参数维度影响力（Top20% vs Bottom20%）:")
        top20 = df_r.head(len(df_r)//5)
        bot20 = df_r.tail(len(df_r)//5)
        for dim, col in [('缩量阈值', 'vol_thresh'), ('MACD窗口', 'macd_win'), ('硬止损%', 'hard_stop'), ('ATR倍数', 'atr_mult'), ('最大持仓', 'max_hold')]:
            print(f"    {dim}: Top均值{top20[col].mean():.3f} vs Bot均值{bot20[col].mean():.3f}")
        
        all_results[ticker] = df_r
    
    # 保存
    import pickle
    with open('/home/agent/cow/tmp/ma_round2_results.pkl', 'wb') as f:
        pickle.dump(all_results, f)
    print("\n✅ 结果已保存至 tmp/ma_round2_results.pkl")

if __name__ == '__main__':
    main()
