"""
MA5回踩 吊灯止盈（Trailing Stop）回测
对比：固定%止盈 vs ATR吊灯止盈 vs 分批+吊灯混合
"""
import tushare as ts
import pandas as pd
import numpy as np
import json

pro = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

TICKERS = {
    '588000': {'code': '588000.SH', 'stop_atr': 2.0},
    '510500': {'code': '510500.SH', 'stop_atr': 2.0},
}

# ============ 止盈方案 ============
EXIT_STRATEGIES = {}

# 1. 纯吊灯：从最高收盘价回撤N×ATR
for mult in [2.0, 2.5, 3.0, 3.5, 4.0]:
    EXIT_STRATEGIES[f'吊灯{mult}×ATR'] = {
        'type': 'trailing',
        'atr_mult': mult,
        'activation': 0,  # 立即激活
    }

# 2. 激活后才吊灯（浮盈达到X倍ATR后激活）
for act in [1.0, 1.5, 2.0]:
    for mult in [2.0, 2.5, 3.0]:
        EXIT_STRATEGIES[f'激活{act}×ATR→吊灯{mult}×ATR'] = {
            'type': 'trailing_activated',
            'activation': act,
            'atr_mult': mult,
        }

# 3. 分批+吊灯混合：第一档固定%锁定，剩余用吊灯
for first_pct in [0.15, 0.20]:
    for first_batch in [0.3, 0.5]:
        for mult in [2.5, 3.0, 3.5]:
            EXIT_STRATEGIES[f'{first_batch*100:.0f}%@{int(first_pct*100)}%+吊灯{mult}×ATR'] = {
                'type': 'batch_trailing',
                'first_batch': first_batch,
                'first_target': first_pct,
                'trail_mult': mult,
            }

# 4. 基准：最优固定%和最优分批
EXIT_STRATEGIES['基准_全仓+20%'] = {'type': 'fixed', 'targets': [1.0, 0.20]}
EXIT_STRATEGIES['基准_30/30/40_20/35/50'] = {
    'type': 'fixed_batch',
    'batches': [(0.3, 0.20), (0.3, 0.35), (0.4, 0.50)]
}
EXIT_STRATEGIES['基准_50/50_15/25'] = {
    'type': 'fixed_batch',
    'batches': [(0.5, 0.15), (0.5, 0.25)]
}

def calc_ma5_signals(df):
    df = df.copy()
    df['MA5'] = df['close'].rolling(5).mean()
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

def backtest(df_sig, stop_atr, strat, max_hold=120, cooldown=10):
    trades = []
    in_position = False
    position = None  # dict with entry info
    last_exit_idx = -999
    
    # 展开固定%止盈到统一格式
    if strat['type'] == 'fixed':
        batches = [(1.0, strat['targets'][1])]
    elif strat['type'] == 'fixed_batch':
        batches = strat['batches']
    else:
        batches = None
    
    for i in range(60, len(df_sig)):
        row = df_sig.iloc[i]
        
        if not in_position:
            if row['signal'] and (i - last_exit_idx > cooldown):
                if i + 1 < len(df_sig):
                    in_position = True
                    entry_price = df_sig.iloc[i + 1]['open']
                    position = {
                        'entry_idx': i + 1,
                        'entry_date': df_sig.iloc[i + 1]['trade_date'],
                        'entry_price': entry_price,
                        'entry_atr': row['ATR14'],
                        'remaining_pct': 1.0,
                        'peak_close': entry_price,
                        'peak_high': entry_price,
                        # 吊灯档位
                        'trailing_activated': False,
                        'trail_stop': None,
                        # 固定%档位
                        'fixed_plan': [],
                        'fixed_done': set(),
                    }
                    if batches:
                        for bp, tp in batches:
                            position['fixed_plan'].append({
                                'batch_pct': bp,
                                'target_pct': tp,
                                'target_price': entry_price * (1 + tp),
                                'triggered': False,
                            })
        else:
            pos = position
            # 更新峰值
            pos['peak_close'] = max(pos['peak_close'], row['close'])
            pos['peak_high'] = max(pos['peak_high'], row['high'])
            
            # 止损
            stop_price = pos['entry_price'] - stop_atr * pos['entry_atr']
            if row['low'] <= stop_price:
                exit_price = min(stop_price, row['open'])
                pnl = (exit_price - pos['entry_price']) / pos['entry_price']
                trades.append({
                    'entry_date': pos['entry_date'],
                    'exit_date': row['trade_date'],
                    'pnl_pct': pnl * 100,
                    'exit_type': 'stop',
                })
                in_position = False
                last_exit_idx = i
                continue
            
            # 强制离场
            if i - pos['entry_idx'] >= max_hold:
                exit_price = row['close']
                pnl = (exit_price - pos['entry_price']) / pos['entry_price']
                trades.append({
                    'entry_date': pos['entry_date'],
                    'exit_date': row['trade_date'],
                    'pnl_pct': pnl * 100,
                    'exit_type': 'force_close',
                })
                in_position = False
                last_exit_idx = i
                continue
            
            # === 吊灯止盈逻辑 ===
            if strat['type'] in ('trailing', 'trailing_activated'):
                if strat['type'] == 'trailing':
                    pos['trailing_activated'] = True
                elif not pos['trailing_activated']:
                    # 检查激活条件
                    gain_atr = (pos['peak_close'] - pos['entry_price']) / pos['entry_atr']
                    if gain_atr >= strat['activation']:
                        pos['trailing_activated'] = True
                
                if pos['trailing_activated']:
                    trail_stop = pos['peak_close'] - strat['atr_mult'] * row['ATR14']
                    if row['low'] <= trail_stop:
                        exit_price = min(trail_stop, row['open'])
                        pnl = (exit_price - pos['entry_price']) / pos['entry_price']
                        trades.append({
                            'entry_date': pos['entry_date'],
                            'exit_date': row['trade_date'],
                            'pnl_pct': pnl * 100,
                            'exit_type': f'trail_{strat["atr_mult"]}xATR',
                        })
                        in_position = False
                        last_exit_idx = i
                        continue
            
            # === 分批+吊灯混合 ===
            elif strat['type'] == 'batch_trailing':
                # 先检查固定第一档
                first_triggered = False
                for fp in pos.get('fixed_plan', []):
                    if not fp['triggered'] and row['high'] >= fp['target_price']:
                        fp['triggered'] = True
                        exit_price = fp['target_price']
                        pnl = (exit_price - pos['entry_price']) / pos['entry_price']
                        trades.append({
                            'entry_date': pos['entry_date'],
                            'exit_date': row['trade_date'],
                            'pnl_pct': pnl * 100,
                            'exit_type': f'fixed_{int(fp["target_pct"]*100)}%',
                        })
                        pos['remaining_pct'] -= fp['batch_pct']
                        first_triggered = True
                        # 激活吊灯
                        pos['trailing_activated'] = True
                
                # 剩余仓位吊灯
                if pos['trailing_activated'] and pos['remaining_pct'] > 0.001:
                    trail_stop = pos['peak_close'] - strat['trail_mult'] * row['ATR14']
                    if row['low'] <= trail_stop:
                        exit_price = min(trail_stop, row['open'])
                        pnl = (exit_price - pos['entry_price']) / pos['entry_price']
                        trades.append({
                            'entry_date': pos['entry_date'],
                            'exit_date': row['trade_date'],
                            'pnl_pct': pnl * 100,
                            'exit_type': f'trail_rest_{strat["trail_mult"]}xATR',
                        })
                        pos['remaining_pct'] = 0
                
                if pos['remaining_pct'] <= 0.001:
                    in_position = False
                    last_exit_idx = i
                    continue
            
            # === 固定%止盈（含分批）===
            elif strat['type'] in ('fixed', 'fixed_batch'):
                any_triggered = False
                for fp in pos['fixed_plan']:
                    if not fp['triggered'] and row['high'] >= fp['target_price']:
                        fp['triggered'] = True
                        exit_price = fp['target_price']
                        pnl = (exit_price - pos['entry_price']) / pos['entry_price']
                        trades.append({
                            'entry_date': pos['entry_date'],
                            'exit_date': row['trade_date'],
                            'pnl_pct': pnl * 100,
                            'exit_type': f'fixed_{int(fp["target_pct"]*100)}%',
                        })
                        pos['remaining_pct'] -= fp['batch_pct']
                        any_triggered = True
                
                if any_triggered and pos['remaining_pct'] <= 0.001:
                    in_position = False
                    last_exit_idx = i
                    continue
    
    return trades

def calc_stats(trades):
    if not trades:
        return {'count': 0, 'win_rate': 0, 'avg_return': 0, 'total_return': 0, 
                'pf': 0, 'max_dd': 0, 'sharpe': 0}
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
    sharpe = np.mean(rets) / np.std(rets) * np.sqrt(252) if len(rets)>1 and np.std(rets)>0 else 0
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
    print(f"\n{'='*80}")
    print(f"  {ticker_name}  吊灯止盈 vs 固定%止盈 vs 混合")
    print(f"{'='*80}")
    
    df = pro.fund_daily(ts_code=config['code'], start_date='20180101', end_date='20260707')
    df = df.sort_values('trade_date').reset_index(drop=True)
    df_sig = calc_ma5_signals(df)
    
    results = []
    for sname, strat in EXIT_STRATEGIES.items():
        trades = backtest(df_sig, config['stop_atr'], strat)
        s = calc_stats(trades)
        s['name'] = sname
        results.append(s)
    
    # 按Sharpe排序输出前15
    sorted_r = sorted(results, key=lambda x: x['sharpe'], reverse=True)
    
    print(f"\n  {'方案':<35s} {'笔数':>3s} {'胜率':>5s} {'累计':>8s} {'PF':>5s} {'Sharpe':>7s} {'回撤':>5s}")
    print(f"  {'─'*35} {'─'*3} {'─'*5} {'─'*8} {'─'*5} {'─'*7} {'─'*5}")
    
    for s in sorted_r[:20]:
        if s['count'] > 0:
            print(f"  {s['name']:<35s} {s['count']:3d} {s['win_rate']:4.1f}% "
                  f"{s['total_return']:+7.1f}% {s['pf']:4.2f} {s['sharpe']:+7.3f} {s['max_dd']:4.1f}%")
    
    # 基准线
    print(f"\n  ── 基准对比 ──")
    for s in sorted_r:
        if '基准' in s['name'] and s['count'] > 0:
            print(f"  {s['name']:<35s} {s['count']:3d} {s['win_rate']:4.1f}% "
                  f"{s['total_return']:+7.1f}% {s['pf']:4.2f} {s['sharpe']:+7.3f} {s['max_dd']:4.1f}%")

