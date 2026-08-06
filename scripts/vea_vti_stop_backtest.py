#!/usr/bin/env python3
"""VEA/VTI 止损参数全量遍历回测
模拟：以当日收盘价入场，止损=入场价−N×ATR14，触发止损即离场。
遍历 N=1.0~10.0（步长0.5），统计胜率/累计收益/最大回撤/Sharpe。
"""

import tushare as ts
import pandas as pd
import numpy as np
import json

pro = ts.pro_api()

def compute_atr14(df):
    """计算ATR14"""
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['prev_close'] = df['close'].shift(1)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['prev_close'])
    df['tr3'] = abs(df['low'] - df['prev_close'])
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['atr14'] = df['tr'].rolling(14).mean()
    return df

def backtest_stop(df, stop_mult):
    """遍历止损倍数，每笔入场独立计算"""
    trades = []
    in_trade = False
    entry_price = 0
    entry_date = ''
    
    for i in range(len(df)):
        if pd.isna(df.loc[i, 'atr14']):
            continue
        
        if not in_trade:
            # 新入场：当日收盘价入场
            entry_price = df.loc[i, 'close']
            entry_date = df.loc[i, 'trade_date']
            stop_price = entry_price - stop_mult * df.loc[i, 'atr14']
            in_trade = True
            continue
        
        # 检查止损
        if df.loc[i, 'close'] <= stop_price:
            exit_price = df.loc[i, 'close']
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            trades.append({
                'entry_date': entry_date,
                'exit_date': df.loc[i, 'trade_date'],
                'entry': entry_price,
                'exit': exit_price,
                'pnl_pct': pnl_pct,
            })
            in_trade = False
            continue
    
    # 最后一笔未止损的，按最后交易日收盘价平仓
    if in_trade:
        last = df.iloc[-1]
        exit_price = last['close']
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        trades.append({
            'entry_date': entry_date,
            'exit_date': last['trade_date'],
            'entry': entry_price,
            'exit': exit_price,
            'pnl_pct': pnl_pct,
        })
    
    return trades

def compute_stats(trades):
    """计算统计指标"""
    if not trades:
        return None
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    # 累计收益（复利）
    cumulative = 1.0
    for p in pnls:
        cumulative *= (1 + p/100)
    cumulative_pnl = (cumulative - 1) * 100
    
    # Sharpe (简化: 均值/标准差，假定无风险利率=0)
    pnl_arr = np.array(pnls)
    sharpe = np.mean(pnl_arr) / np.std(pnl_arr) if np.std(pnl_arr) > 0 else 0
    
    # 最大回撤
    equity = [1.0]
    for p in pnls:
        equity.append(equity[-1] * (1 + p/100))
    peak = np.maximum.accumulate(equity)
    dd = (np.array(equity) - peak) / peak * 100
    max_dd = min(dd)
    
    # 最大连亏
    max_consec_loss = 0
    curr_consec = 0
    for p in pnls:
        if p <= 0:
            curr_consec += 1
            max_consec_loss = max(max_consec_loss, curr_consec)
        else:
            curr_consec = 0
    
    return {
        'trades': len(trades),
        'win_rate': len(wins)/len(trades)*100 if trades else 0,
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
        'max_win': max(pnls) if pnls else 0,
        'max_loss': min(pnls) if pnls else 0,
        'cumulative_pnl': cumulative_pnl,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'max_consec_loss': max_consec_loss,
        'avg_pnl': np.mean(pnl_arr),
    }

def main():
    results = {}
    
    for ticker in ['VEA', 'VTI']:
        print(f'\n{"="*60}')
        print(f'{ticker} 止损参数全量遍历')
        print(f'{"="*60}')
        
        raw = pro.us_daily(ts_code=ticker, start_date='20140101', end_date='20260730')
        df = raw.sort_values('trade_date').reset_index(drop=True)
        df = compute_atr14(df)
        print(f'数据: {len(df)}行, {df["trade_date"].min()} ~ {df["trade_date"].max()}')
        print(f'ATR14均值: ${df["atr14"].mean():.2f}')
        print(f'ATR14/价格: {df["atr14"].mean()/df["close"].mean()*100:.2f}%')
        
        ticker_results = []
        
        for mult in np.arange(1.0, 10.5, 0.5):
            trades = backtest_stop(df.copy(), mult)
            stats = compute_stats(trades)
            stats['stop_mult'] = mult
            ticker_results.append(stats)
            print(f'  {mult:.1f}×ATR:  {stats["trades"]:3d}笔  胜率{stats["win_rate"]:.1f}%  '
                  f'均收益{stats["avg_pnl"]:+.2f}%  累计{stats["cumulative_pnl"]:+.1f}%  '
                  f'Sharpe{stats["sharpe"]:.3f}  MaxDD{stats["max_dd"]:.1f}%  连亏{stats["max_consec_loss"]}笔')
        
        results[ticker] = ticker_results
    
    # 汇总最优
    print(f'\n{"="*60}')
    print('最优参数汇总')
    print(f'{"="*60}')
    for ticker in ['VEA', 'VTI']:
        best = max(results[ticker], key=lambda x: x['cumulative_pnl'])
        print(f'\n{ticker}:')
        print(f'  最优: {best["stop_mult"]:.1f}×ATR')
        print(f'  累计: {best["cumulative_pnl"]:+.1f}%')
        print(f'  笔数: {best["trades"]}笔')
        print(f'  胜率: {best["win_rate"]:.1f}%')
        print(f'  均收益: {best["avg_pnl"]:+.2f}%')
        print(f'  Sharpe: {best["sharpe"]:.3f}')
        print(f'  MaxDD: {best["max_dd"]:.1f}%')
        print(f'  连亏: {best["max_consec_loss"]}笔')
        
        # Buy & Hold对比
        raw = pro.us_daily(ts_code=ticker, start_date='20140101', end_date='20260730')
        df_raw = raw.sort_values('trade_date')
        bh_return = (df_raw.iloc[-1]['close'] - df_raw.iloc[0]['close']) / df_raw.iloc[0]['close'] * 100
        print(f'  Buy&Hold: {bh_return:+.1f}%')
        
        # 当前参数下的止损价
        current_price = df.iloc[-1]['close']
        stop_price = current_price - best['stop_mult'] * df.iloc[-1]['atr14']
        print(f'  当前止损价({best["stop_mult"]:.1f}×ATR): ${stop_price:.2f}')
    
    # 保存JSON
    with open('/home/agent/cow/tmp/vea_vti_stop_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print('\n结果已保存到 tmp/vea_vti_stop_results.json')

if __name__ == '__main__':
    main()
