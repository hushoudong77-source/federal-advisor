"""
MA5回踩分批止盈回测
对比：全仓固定%止盈 vs 分批止盈（50%+50%、30%+70%等）
针对 588000 / 510500
"""
import tushare as ts
import pandas as pd
import numpy as np
import json

pro = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

TICKERS = {
    '588000': {'code': '588000.SH', 'stop_atr': 2.0, 'ma_period': 5},
    '510500': {'code': '510500.SH', 'stop_atr': 2.0, 'ma_period': 5},
}

# 止盈方案
EXIT_STRATEGIES = {
    # 基准：全仓固定%
    'full_20':    {'type': 'fixed', 'pcts': [(1.0, 0.20)]},
    'full_25':    {'type': 'fixed', 'pcts': [(1.0, 0.25)]},
    'full_30':    {'type': 'fixed', 'pcts': [(1.0, 0.30)]},
    # 分批：50%+50%
    'batch5050_20_30': {'type': 'fixed', 'pcts': [(0.5, 0.20), (0.5, 0.30)]},
    'batch5050_15_25': {'type': 'fixed', 'pcts': [(0.5, 0.15), (0.5, 0.25)]},
    'batch5050_20_40': {'type': 'fixed', 'pcts': [(0.5, 0.20), (0.5, 0.40)]},
    # 分批：30%+70%
    'batch3070_15_25': {'type': 'fixed', 'pcts': [(0.3, 0.15), (0.7, 0.25)]},
    'batch3070_20_35': {'type': 'fixed', 'pcts': [(0.3, 0.20), (0.7, 0.35)]},
    # 三批：30%+30%+40%
    'batch3_15_25_40': {'type': 'fixed', 'pcts': [(0.3, 0.15), (0.3, 0.25), (0.4, 0.40)]},
    # MA20基准（原方案）
    'ma20': {'type': 'ma', 'ma_period': 20},
}

def calc_ma5_signals(df, ma_period=5):
    """MA5回踩入场信号"""
    df = df.copy()
    df['MA5'] = df['close'].rolling(ma_period).mean()
    df['MA60'] = df['close'].rolling(60).mean()
    df['ATR14'] = (df['high'] - df['low']).rolling(14).mean()
    
    # 牛市判定
    df['MA60_up'] = df['MA60'].diff(20) > 0
    df['price_above_MA60'] = df['close'] > df['MA60']
    df['bull_market'] = df['MA60_up'] & df['price_above_MA60']
    
    # MA5回踩信号：前日收盘>MA5 + 当日最低触及MA5(±0.5%)
    df['prev_close'] = df['close'].shift(1)
    df['prev_MA5'] = df['MA5'].shift(1)
    df['prev_above_MA5'] = df['prev_close'] > df['prev_MA5']
    df['low_near_MA5'] = abs(df['low'] - df['MA5']) / df['MA5'] <= 0.005
    
    df['signal'] = df['bull_market'] & df['prev_above_MA5'] & df['low_near_MA5']
    return df

def backtest_with_exit(df, stop_atr, exit_strategy, max_hold=120):
    """回测MA5回踩策略，指定止盈方案"""
    trades = []
    in_position = False
    entry_idx = None
    entry_price = None
    entry_atr = None
    remaining_pct = 1.0  # 剩余仓位比例
    peak_price = None
    
    for i in range(60, len(df)):  # 从第60天开始
        row = df.iloc[i]
        
        if not in_position:
            if row['signal']:
                # 入场（次日开盘）
                if i + 1 < len(df):
                    in_position = True
                    entry_idx = i + 1
                    entry_price = df.iloc[i + 1]['open']
                    entry_atr = row['ATR14']  # 用信号日ATR
                    remaining_pct = 1.0
                    peak_price = entry_price
                    # 初始化止盈档位
                    exit_plan = []
                    cum_pct = 0
                    for batch_pct, target_pct in exit_strategy['pcts']:
                        exit_plan.append({
                            'batch_pct': batch_pct,
                            'target_pct': target_pct,
                            'target_price': entry_price * (1 + target_pct),
                            'triggered': False
                        })
                        cum_pct += batch_pct
        else:
            # 更新峰值
            peak_price = max(peak_price, row['high'])
            
            # 检查止损
            stop_price = entry_price - stop_atr * entry_atr
            if row['low'] <= stop_price:
                # 止损触发
                exit_price = min(stop_price, row['open'])
                pnl = (exit_price - entry_price) / entry_price
                trades.append({
                    'entry_date': df.iloc[entry_idx]['trade_date'],
                    'exit_date': row['trade_date'],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_pct': pnl * 100,
                    'exit_type': 'stop',
                    'peak_price': peak_price,
                })
                in_position = False
                continue
            
            # 检查强制离场
            days_held = i - entry_idx
            if days_held >= max_hold:
                exit_price = row['close']
                pnl = (exit_price - entry_price) / entry_price
                trades.append({
                    'entry_date': df.iloc[entry_idx]['trade_date'],
                    'exit_date': row['trade_date'],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_pct': pnl * 100,
                    'exit_type': 'force_close',
                    'peak_price': peak_price,
                })
                in_position = False
                continue
            
            # 检查止盈档位
            for ep in exit_plan:
                if not ep['triggered'] and row['high'] >= ep['target_price']:
                    # 触发！
                    ep['triggered'] = True
                    exit_price = ep['target_price']
                    pnl = (exit_price - entry_price) / entry_price
                    trades.append({
                        'entry_date': df.iloc[entry_idx]['trade_date'],
                        'exit_date': row['trade_date'],
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pnl_pct': pnl * 100,
                        'exit_type': f'profit_{ep["target_pct"]*100:.0f}pct_{ep["batch_pct"]*100:.0f}pct_batch',
                        'peak_price': peak_price,
                    })
                    remaining_pct -= ep['batch_pct']
                    
                    if remaining_pct <= 0.001:
                        in_position = False
                        break
    
    return trades

def calc_stats(trades):
    if not trades:
        return {'count': 0, 'win_rate': 0, 'avg_return': 0, 'total_return': 0, 'pf': 0, 'max_dd': 0}
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    avg_win = np.mean(wins) if wins else 0
    avg_loss = abs(np.mean(losses)) if losses else 0
    pf = avg_win / avg_loss if avg_loss > 0 else float('inf')
    
    cumulative = np.cumprod([1 + p/100 for p in pnls])
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    
    return {
        'count': len(trades),
        'win_rate': len(wins) / len(pnls) * 100,
        'avg_return': np.mean(pnls),
        'total_return': (np.prod([1 + p/100 for p in pnls]) - 1) * 100,
        'pf': pf,
        'max_dd': min(drawdowns) * 100,
    }

results = {}

for ticker_name, config in TICKERS.items():
    print(f"\n{'='*60}")
    print(f"  {ticker_name}")
    print(f"{'='*60}")
    
    # 拉数据
    df = pro.fund_daily(ts_code=config['code'], start_date='20180101', end_date='20260707')
    df = df.sort_values('trade_date').reset_index(drop=True)
    print(f"  数据: {len(df)} 行, {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}")
    
    df_sig = calc_ma5_signals(df, config['ma_period'])
    
    ticker_results = []
    
    for strat_name, strat in EXIT_STRATEGIES.items():
        trades = backtest_with_exit(df_sig, config['stop_atr'], strat)
        stats = calc_stats(trades)
        stats['strategy'] = strat_name
        ticker_results.append(stats)
        
        # 简洁输出
        if stats['count'] > 0:
            print(f"  {strat_name:25s}: {stats['count']:3d}笔 | 胜率{stats['win_rate']:5.1f}% | "
                  f"均收益{stats['avg_return']:+6.2f}% | 累计{stats['total_return']:+8.2f}% | "
                  f"PF {stats['pf']:.2f} | 最大回撤{stats['max_dd']:.1f}%")
        else:
            print(f"  {strat_name:25s}: 0笔")
    
    results[ticker_name] = ticker_results

# 输出JSON便于分析
print("\n\n=== JSON OUTPUT ===")
print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
