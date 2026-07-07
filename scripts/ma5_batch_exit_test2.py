import tushare as ts
import pandas as pd
import numpy as np
import json

pro = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

TICKERS = {
    '588000': {'code': '588000.SH', 'stop_atr': 2.0, 'ma_period': 5},
    '510500': {'code': '510500.SH', 'stop_atr': 2.0, 'ma_period': 5},
}

# 分批止盈方案（统一pcts格式）
EXIT_STRATEGIES = {
    'full_20':            [(1.0, 0.20)],
    'full_25':            [(1.0, 0.25)],
    'full_30':            [(1.0, 0.30)],
    '50/50_20/30':        [(0.5, 0.20), (0.5, 0.30)],
    '50/50_15/25':        [(0.5, 0.15), (0.5, 0.25)],
    '50/50_20/40':        [(0.5, 0.20), (0.5, 0.40)],
    '30/70_15/25':        [(0.3, 0.15), (0.7, 0.25)],
    '30/70_20/35':        [(0.3, 0.20), (0.7, 0.35)],
    '30/30/40_15/25/40':  [(0.3, 0.15), (0.3, 0.25), (0.4, 0.40)],
    '30/30/40_20/35/50':  [(0.3, 0.20), (0.3, 0.35), (0.4, 0.50)],
}

def calc_ma5_signals(df, ma_period=5):
    df = df.copy()
    df['MA5'] = df['close'].rolling(ma_period).mean()
    df['MA60'] = df['close'].rolling(60).mean()
    df['ATR14'] = (df['high'] - df['low']).rolling(14).mean()
    
    df['MA60_up'] = df['MA60'].diff(20) > 0
    df['price_above_MA60'] = df['close'] > df['MA60']
    df['bull_market'] = df['MA60_up'] & df['price_above_MA60']
    
    df['prev_close'] = df['close'].shift(1)
    df['prev_MA5'] = df['MA5'].shift(1)
    df['prev_above_MA5'] = df['prev_close'] > df['prev_MA5']
    df['low_near_MA5'] = abs(df['low'] - df['MA5']) / df['MA5'] <= 0.005
    
    df['signal'] = df['bull_market'] & df['prev_above_MA5'] & df['low_near_MA5']
    return df

def backtest_batch_exit(df, stop_atr, exit_pcts, max_hold=120, cooldown=10):
    trades = []
    in_position = False
    entry_idx = None
    entry_price = None
    entry_atr = None
    remaining_pct = 1.0
    peak_price = None
    exit_plan = []
    last_exit_idx = -999
    
    for i in range(60, len(df)):
        row = df.iloc[i]
        
        if not in_position:
            if row['signal'] and (i - last_exit_idx > cooldown):
                if i + 1 < len(df):
                    in_position = True
                    entry_idx = i + 1
                    entry_price = df.iloc[i + 1]['open']
                    entry_atr = row['ATR14']
                    remaining_pct = 1.0
                    peak_price = entry_price
                    exit_plan = []
                    cum = 0
                    for bp, tp in exit_pcts:
                        exit_plan.append({
                            'batch_pct': bp, 'target_pct': tp,
                            'target_price': entry_price * (1 + tp),
                            'triggered': False
                        })
                        cum += bp
        else:
            peak_price = max(peak_price, row['high'])
            stop_price = entry_price - stop_atr * entry_atr
            
            # 止损
            if row['low'] <= stop_price:
                exit_price = min(stop_price, row['open'])
                pnl = (exit_price - entry_price) / entry_price
                trades.append({
                    'entry_date': df.iloc[entry_idx]['trade_date'],
                    'exit_date': row['trade_date'],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_pct': pnl * 100,
                    'exit_type': 'stop',
                })
                in_position = False
                last_exit_idx = i
                continue
            
            # 强制离场
            if i - entry_idx >= max_hold:
                exit_price = row['close']
                pnl = (exit_price - entry_price) / entry_price
                trades.append({
                    'entry_date': df.iloc[entry_idx]['trade_date'],
                    'exit_date': row['trade_date'],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_pct': pnl * 100,
                    'exit_type': 'force_close',
                })
                in_position = False
                last_exit_idx = i
                continue
            
            # 止盈档位
            any_triggered = False
            for ep in exit_plan:
                if not ep['triggered'] and row['high'] >= ep['target_price']:
                    ep['triggered'] = True
                    exit_price = ep['target_price']
                    pnl = (exit_price - entry_price) / entry_price
                    trades.append({
                        'entry_date': df.iloc[entry_idx]['trade_date'],
                        'exit_date': row['trade_date'],
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pnl_pct': pnl * 100,
                        'exit_type': f'profit_{ep["target_pct"]*100:.0f}%_{ep["batch_pct"]*100:.0f}%',
                    })
                    remaining_pct -= ep['batch_pct']
                    any_triggered = True
            
            if any_triggered and remaining_pct <= 0.001:
                in_position = False
                last_exit_idx = i
    
    return trades

def calc_stats(trades):
    if not trades:
        return {'count': 0, 'win_rate': 0, 'avg_return': 0, 'total_return': 0, 'pf': 0, 'max_dd': 0, 'sharpe': 0}
    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = np.mean(wins) if wins else 0
    avg_loss = abs(np.mean(losses)) if losses else 0
    pf = avg_win / avg_loss if avg_loss > 0 else float('inf')
    cumulative = np.cumprod([1 + p/100 for p in pnls])
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    rets = np.array(pnls) / 100
    sharpe = np.mean(rets) / np.std(rets) * np.sqrt(252) if len(rets) > 1 and np.std(rets) > 0 else 0
    return {
        'count': len(trades),
        'win_rate': len(wins)/len(pnls)*100,
        'avg_return': np.mean(pnls),
        'total_return': (np.prod([1+p/100 for p in pnls])-1)*100,
        'pf': pf,
        'max_dd': min(drawdowns)*100,
        'sharpe': sharpe,
    }

for ticker_name, config in TICKERS.items():
    print(f"\n{'='*70}")
    print(f"  {ticker_name}  MA5回踩 分批止盈对比")
    print(f"{'='*70}")
    df = pro.fund_daily(ts_code=config['code'], start_date='20180101', end_date='20260707')
    df = df.sort_values('trade_date').reset_index(drop=True)
    df_sig = calc_ma5_signals(df, config['ma_period'])
    
    rows = []
    for sname, spcts in EXIT_STRATEGIES.items():
        trades = backtest_batch_exit(df_sig, config['stop_atr'], spcts)
        s = calc_stats(trades)
        s['name'] = sname
        rows.append(s)
        if s['count'] > 0:
            print(f"  {sname:28s} {s['count']:3d}笔 | 胜率{s['win_rate']:5.1f}% | "
                  f"均收益{s['avg_return']:+6.2f}% | 累计{s['total_return']:+8.2f}% | "
                  f"PF {s['pf']:.2f} | Sharpe {s['sharpe']:+.3f} | 回撤{s['max_dd']:.1f}%")
        else:
            print(f"  {sname:28s} 0笔")
