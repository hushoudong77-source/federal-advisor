#!/usr/bin/env python3
"""
MA5回踩策略止盈参数对比回测
对比: MA20 / MA60 / 固定%止盈(5/10/15/20/25/30%)
标的: 513180 / 588000 / 510500
"""

import tushare as ts
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

pro = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

TICKERS = {
    '513180': {'ts_code': '513180.SH', 'name': '恒生科技', 'stop_atr': 2.0, 'cooldown': 10},
    '588000': {'ts_code': '588000.SH', 'name': '科创50',   'stop_atr': 2.0, 'cooldown': 10},
    '510500': {'ts_code': '510500.SH', 'name': '中证500',  'stop_atr': 2.0, 'cooldown': 10},
}

TAKE_PROFIT_MODES = [
    ('MA20', 'ma', 'MA20'),
    ('MA60', 'ma', 'MA60'),
    ('+5%',  'pct', 0.05),
    ('+10%', 'pct', 0.10),
    ('+15%', 'pct', 0.15),
    ('+20%', 'pct', 0.20),
    ('+25%', 'pct', 0.25),
    ('+30%', 'pct', 0.30),
]

def calc_atr(df, window=14):
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    N = len(df)
    tr = np.zeros(N)
    for i in range(1, N):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    tr[0] = high[0] - low[0]
    atr = pd.Series(tr).rolling(window).mean()
    return atr

def is_bull(df, idx, ma5, ma60):
    if idx < 60:
        return False
    if pd.isna(ma60[idx]) or pd.isna(ma60[idx-5]):
        return False
    return ma60[idx] > ma60[idx-5] and df['close'].iloc[idx] > ma60[idx]

def detect_entry(df, idx, ma5):
    if idx < 6:
        return False
    prev_close = df['close'].iloc[idx-1]
    prev_ma5 = ma5[idx-1]
    today_low = df['low'].iloc[idx]
    today_ma5 = ma5[idx]
    if pd.isna(prev_ma5) or pd.isna(today_ma5):
        return False
    if prev_close <= prev_ma5:
        return False
    touch_zone = today_ma5 * 1.005
    return today_low <= touch_zone

def backtest(ticker_info, tp_name, tp_mode, tp_val):
    ts_code = ticker_info['ts_code']
    stop_atr = ticker_info['stop_atr']
    cooldown = ticker_info['cooldown']
    
    df = pro.fund_daily(ts_code=ts_code, start_date='20180101', end_date='20260706')
    if df is None or len(df) == 0:
        return None
    df = df.sort_values('trade_date').reset_index(drop=True)
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    open_ = df['open'].values
    dates = df['trade_date'].values
    
    # 计算均线
    ma5 = pd.Series(close).rolling(5).mean().values
    ma20 = pd.Series(close).rolling(20).mean().values
    ma60 = pd.Series(close).rolling(60).mean().values
    atr14 = calc_atr(df, 14).values
    
    trades = []
    cooldown_until = -1
    
    for idx in range(60, len(df)):
        if idx <= cooldown_until:
            continue
        if not is_bull(df, idx, ma5, ma60):
            continue
        if not detect_entry(df, idx, ma5):
            continue
        
        entry_idx = idx + 1
        if entry_idx >= len(df):
            break
        
        entry_price = open_[entry_idx]
        entry_atr = atr14[entry_idx]
        if pd.isna(entry_atr) or entry_atr <= 0:
            continue
        
        stop_price = entry_price - stop_atr * entry_atr
        
        # 止盈目标
        if tp_mode == 'ma':
            tp_line_arr = ma20 if tp_val == 'MA20' else ma60
            tp_target_arr = tp_line_arr
        else:
            tp_target_price = entry_price * (1 + tp_val)
        
        exit_idx = None
        exit_price = None
        exit_reason = None
        
        for j in range(entry_idx + 1, min(len(df), entry_idx + 121)):
            h = high[j]
            l = low[j]
            c = close[j]
            
            # 止损
            if l <= stop_price:
                exit_idx = j
                exit_price = min(stop_price, open_[j])
                exit_reason = '止损'
                break
            
            # 止盈
            if tp_mode == 'ma':
                tp_line = tp_target_arr[j]
                if not pd.isna(tp_line) and c >= tp_line:
                    exit_idx = j
                    exit_price = c
                    exit_reason = f'止盈({tp_val})'
                    break
            else:
                if h >= tp_target_price:
                    exit_idx = j
                    exit_price = tp_target_price
                    exit_reason = f'止盈({tp_name})'
                    break
        
        if exit_idx is None:
            force_idx = min(entry_idx + 120, len(df) - 1)
            exit_idx = force_idx
            exit_price = close[force_idx]
            exit_reason = '强制离场'
        
        pnl_pct = (exit_price - entry_price) / entry_price
        
        trades.append({
            'entry_date': dates[entry_idx],
            'entry_price': entry_price,
            'exit_date': dates[exit_idx],
            'exit_price': exit_price,
            'pnl_pct': pnl_pct,
            'reason': exit_reason,
        })
        
        cooldown_until = exit_idx + cooldown
    
    if len(trades) == 0:
        return None
    
    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df['pnl_pct'] > 0]
    losses = trades_df[trades_df['pnl_pct'] <= 0]
    
    avg_win = wins['pnl_pct'].mean() if len(wins) > 0 else 0
    avg_loss = losses['pnl_pct'].mean() if len(losses) > 0 else 0
    cumulative = (1 + trades_df['pnl_pct']).prod() - 1
    returns = trades_df['pnl_pct'].values
    
    sharpe = np.mean(returns) / np.std(returns) * np.sqrt(len(returns)) if len(returns) > 1 and np.std(returns) > 0 else 0
    
    max_cons = 0
    cur = 0
    for r in returns:
        if r <= 0:
            cur += 1
            max_cons = max(max_cons, cur)
        else:
            cur = 0
    
    wr = len(wins) / len(trades)
    pf = abs(avg_win / avg_loss) if avg_loss != 0 else 5.0
    score = wr * 0.30 + np.clip(np.mean(returns), -0.1, 0.2) * 5 * 0.30 + min(pf, 5) * 0.20 + (len(trades) / 15) * 0.15 - max_cons * 0.02
    
    return {
        'ticker': ts_code,
        'tp_name': tp_name,
        'n_trades': len(trades),
        'win_rate': wr,
        'avg_return': np.mean(returns),
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'cumulative': cumulative,
        'sharpe': sharpe,
        'max_cons': max_cons,
        'pf': pf,
        'score': score,
        'trades': trades_df,
    }

print("=" * 90)
print("MA5回踩策略 — 止盈参数对比回测 (2018-2026)")
print("=" * 90)

all_results = []

for ticker_code, ticker_info in TICKERS.items():
    print(f"\n{'='*70}")
    print(f"📊 {ticker_code} {ticker_info['name']}")
    print(f"{'='*70}")
    
    results = []
    for tp_name, tp_mode, tp_val in TAKE_PROFIT_MODES:
        r = backtest(ticker_info, tp_name, tp_mode, tp_val)
        if r:
            results.append(r)
            all_results.append(r)
    
    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        
        print(f"\n{'止盈':<10} {'笔数':>4} {'胜率':>7} {'均收益':>8} {'均盈':>8} {'均亏':>8} {'累计':>9} {'Sharpe':>7} {'PF':>6} {'连亏':>4} {'得分':>7}")
        print("-" * 85)
        for r in results:
            print(f"{r['tp_name']:<10} {r['n_trades']:>4} {r['win_rate']:>6.1%} {r['avg_return']:>7.2%} {r['avg_win']:>7.2%} {r['avg_loss']:>7.2%} {r['cumulative']:>8.2%} {r['sharpe']:>6.3f} {r['pf']:>5.2f} {r['max_cons']:>4} {r['score']:>7.4f}")
        
        best = results[0]
        cur_ma20 = [r for r in results if r['tp_name'] == 'MA20']
        cur_score = cur_ma20[0]['score'] if cur_ma20 else 0
        
        print(f"\n🏆 最优: {best['tp_name']} 得分={best['score']:.4f} | 当前MA20得分={cur_score:.4f} | Δ={best['score']-cur_score:+.4f}")

print(f"\n{'='*90}")
print("📋 汇总建议")
print(f"{'='*90}")
print(f"\n{'标的':<10} {'当前MA20':<15} {'最优方案':<15} {'得分Δ':>7} {'主要改善':>30}")
print("-" * 80)

for ticker_code in TICKERS:
    ticker_results = [r for r in all_results if r['ticker'].startswith(ticker_code)]
    if not ticker_results:
        continue
    ticker_results.sort(key=lambda x: x['score'], reverse=True)
    best = ticker_results[0]
    cur_ma20 = [r for r in ticker_results if r['tp_name'] == 'MA20']
    
    if cur_ma20:
        cur = cur_ma20[0]
        delta = best['score'] - cur['score']
        improvements = []
        if best['win_rate'] > cur['win_rate'] + 0.03:
            improvements.append(f"胜率{cur['win_rate']:.0%}→{best['win_rate']:.0%}")
        if best['cumulative'] > cur['cumulative'] + 0.05:
            improvements.append(f"累计{cur['cumulative']:.0%}→{best['cumulative']:.0%}")
        if best['sharpe'] > cur['sharpe'] + 0.1:
            improvements.append(f"Sharpe{cur['sharpe']:.2f}→{best['sharpe']:.2f}")
        if best['n_trades'] != cur['n_trades']:
            improvements.append(f"信号{cur['n_trades']}→{best['n_trades']}笔")
        if not improvements:
            improvements.append(f"综合得分提升")
        
        print(f"{ticker_code:<10} 累计{cur['cumulative']:.0%}/胜率{cur['win_rate']:.0%}  {best['tp_name']:<6} 累计{best['cumulative']:.0%}/胜率{best['win_rate']:.0%}  {delta:>+6.4f}  {', '.join(improvements)}")

print("\n⚠️ 以上为回测数据，修改权在守东。")
