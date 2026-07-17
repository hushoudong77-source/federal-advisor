#!/usr/bin/env python3
"""
MA60回踩策略 — 两轮全量网格遍历回测
标的: 512100(中证1000ETF) / 510500(中证500ETF)

第一轮: MA周期 × 容忍度 × 止盈值 (100组合)
第二轮: MACD窗口 × 缩量阈值 × 硬止损 × ATR倍数 × 最大持仓 (3125组合)
       基于第一轮Top 3骨架叠加

用法: python3 ma60_pullback_grid_search.py [512100|510500|all]
"""

import sys
import json
import numpy as np
import pandas as pd
from itertools import product
from datetime import datetime, timedelta
import tushare as ts

PRO = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

ROUND1_GRID = {
    'ma_period': [20, 30, 40, 50, 60],
    'tolerance': [0.02, 0.03, 0.04, 0.05],
    'tp_pct': [0.10, 0.15, 0.20, 0.25, 0.30],
}

ROUND2_GRID = {
    'macd_window': [1, 2, 3, 4, 5],
    'vol_ratio': [0.7, 0.8, 0.9, 1.0, 1.1],
    'hard_stop': [-0.02, -0.03, -0.04, -0.05, -0.06],
    'atr_mult': [1.5, 2.0, 2.5, 3.0, 3.5],
    'max_hold': [30, 50, 70, 90, 120],
}


def load_data(code):
    ts_code = f'{code}.SH'
    df = PRO.fund_daily(ts_code=ts_code, start_date='20160101', end_date='20260708')
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    
    for col in ['close', 'open', 'high', 'low', 'vol']:
        df[col] = df[col].astype(float)
    
    for p in [5, 10, 20, 30, 40, 50, 60, 150]:
        df[f'ma{p}'] = df['close'].rolling(p).mean()
    
    df['tr'] = np.maximum(df['high'] - df['low'],
        np.maximum(abs(df['high'] - df['close'].shift(1)),
                   abs(df['low'] - df['close'].shift(1))))
    df['atr14'] = df['tr'].rolling(14).mean()
    
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd_diff'] = ema12 - ema26
    df['macd_dea'] = df['macd_diff'].ewm(span=9, adjust=False).mean()
    df['macd_bar'] = 2 * (df['macd_diff'] - df['macd_dea'])
    df['macd_golden'] = (df['macd_bar'] > 0) & (df['macd_bar'].shift(1) <= 0)
    
    df['vol_ma20'] = df['vol'].rolling(20).mean()
    df['vol_ratio'] = df['vol'] / df['vol_ma20']
    
    df['ma60_slope'] = df['ma60'] - df['ma60'].shift(20)
    df['ma60_up'] = df['ma60_slope'] > 0
    df['bull_market'] = df['ma60_up'] & (df['close'] > df['ma60'])
    
    return df


def compute_scores(trades):
    if not trades:
        return {'trades': 0, 'win_rate': 0, 'avg_return': 0,
                'cum_return': 0, 'sharpe': 0, 'max_dd': 0,
                'max_consecutive_loss': 0, 'profit_factor': 0}
    
    returns = [t['return_pct'] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    
    n = len(trades)
    wr = len(wins) / n if n > 0 else 0
    avg_r = np.mean(returns) if returns else 0
    cum_r = np.prod([1 + r for r in returns]) - 1 if returns else 0
    
    if len(returns) > 1 and np.std(returns) > 0:
        sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(n)
    else:
        sharpe = 0
    
    max_cl = 0
    cl = 0
    for r in returns:
        if r <= 0:
            cl += 1
            max_cl = max(max_cl, cl)
        else:
            cl = 0
    
    total_win = sum(wins) if wins else 0
    total_loss = abs(sum(losses)) if losses else 1
    pf = total_win / total_loss if total_loss > 0 else 0
    
    cum_curve = np.cumprod([1 + r for r in returns])
    peak = np.maximum.accumulate(cum_curve)
    dd = (cum_curve - peak) / peak
    max_dd = dd.min()
    
    return {
        'trades': n, 'win_rate': round(wr, 4), 'avg_return': round(avg_r, 4),
        'cum_return': round(cum_r, 4), 'sharpe': round(sharpe, 4),
        'max_dd': round(max_dd, 4), 'max_consecutive_loss': max_cl,
        'profit_factor': round(pf, 4),
    }


def backtest(df, params):
    trades = []
    i = 60
    cooldown_until = None
    
    while i < len(df):
        row = df.iloc[i]
        
        if not row['bull_market']:
            i += 1
            continue
        if cooldown_until and row['trade_date'] < cooldown_until:
            i += 1
            continue
        if not row['ma60_up']:
            i += 1
            continue
        
        ma_val = row[f'ma{params["ma_period"]}']
        if pd.isna(ma_val):
            i += 1
            continue
        
        tol = params['tolerance']
        if not (ma_val * (1 - tol) <= row['close'] <= ma_val * (1 + tol)):
            i += 1
            continue
        
        macd_w = params['macd_window']
        start_i = max(0, i - macd_w + 1)
        if not df.iloc[start_i:i + 1]['macd_golden'].any():
            i += 1
            continue
        
        if row['vol_ratio'] >= params['vol_ratio']:
            i += 1
            continue
        
        entry_price = row['close']
        entry_date = row['trade_date']
        
        hard_stop_price = entry_price * (1 + params['hard_stop'])
        atr_stop_price = entry_price - params['atr_mult'] * row['atr14']
        stop_price = max(hard_stop_price, atr_stop_price)
        tp_price = entry_price * (1 + params['tp_pct'])
        
        exit_price = None
        exit_date = None
        exit_reason = None
        j = i
        
        end_j = min(i + params['max_hold'] + 1, len(df))
        for jj in range(i + 1, end_j):
            r = df.iloc[jj]
            if r['low'] <= stop_price:
                exit_price = stop_price
                exit_date = r['trade_date']
                exit_reason = 'stop_loss'
                j = jj
                break
            if r['high'] >= tp_price:
                exit_price = tp_price
                exit_date = r['trade_date']
                exit_reason = 'take_profit'
                j = jj
                break
        
        if exit_price is None:
            exit_idx = min(i + params['max_hold'], len(df) - 1)
            exit_price = df.iloc[exit_idx]['close']
            exit_date = df.iloc[exit_idx]['trade_date']
            exit_reason = 'force_exit'
            j = exit_idx
        
        ret = (exit_price - entry_price) / entry_price
        trades.append({
            'entry_date': str(entry_date.date()),
            'entry_price': round(entry_price, 4),
            'exit_date': str(exit_date.date()),
            'exit_price': round(exit_price, 4),
            'return_pct': round(ret, 4),
            'exit_reason': exit_reason,
            'hold_days': (exit_date - entry_date).days,
        })
        
        cooldown_until = exit_date + timedelta(days=30)
        i = j + 1
    
    return trades


def run_round1(code, df):
    n_combo = len(ROUND1_GRID['ma_period']) * len(ROUND1_GRID['tolerance']) * len(ROUND1_GRID['tp_pct'])
    print(f"\n{'='*60}")
    print(f"🔵 第一轮 — {code} | 组合数: {n_combo}")
    print(f"   固定: MACDw=2, 缩量=0.9, 硬止损=-3%, ATR=2.5x, 持仓=90天")
    print(f"{'='*60}")
    
    fixed = {'macd_window': 2, 'vol_ratio': 0.9, 'hard_stop': -0.03, 'atr_mult': 2.5, 'max_hold': 90}
    results = []
    count = 0
    
    for ma_p, tol, tp in product(ROUND1_GRID['ma_period'], ROUND1_GRID['tolerance'], ROUND1_GRID['tp_pct']):
        params = {'ma_period': ma_p, 'tolerance': tol, 'tp_pct': tp, **fixed}
        trades = backtest(df, params)
        scores = compute_scores(trades)
        scores.update({'ma_period': ma_p, 'tolerance': tol, 'tp_pct': tp, 'code': code})
        results.append(scores)
        count += 1
        if count % 20 == 0:
            print(f"   进度: {count}/{n_combo}")
    
    df_r = pd.DataFrame(results)
    df_r['composite'] = (
        df_r['win_rate'] * 0.30 + df_r['cum_return'] * 0.30 +
        df_r['sharpe'].clip(-1, 3) * 0.20 -
        df_r['max_consecutive_loss'] * 0.01 - abs(df_r['max_dd']) * 0.10
    )
    return df_r.sort_values('composite', ascending=False)


def run_round2(code, df, top3):
    n_per = 5**5
    n_total = 3 * n_per
    print(f"\n{'='*60}")
    print(f"🔴 第二轮 — {code} | 组合数: 3x{n_per}={n_total}")
    print(f"{'='*60}")
    
    all_results = []
    for rank, (_, sk) in enumerate(top3.iterrows()):
        ma_p, tol, tp = int(sk['ma_period']), sk['tolerance'], sk['tp_pct']
        print(f"\n   骨架{rank+1}: MA{ma_p} +-{tol*100:.0f}% TP+{tp*100:.0f}%")
        count = 0
        for mw, vr, hs, am, mh in product(*ROUND2_GRID.values()):
            params = {'ma_period': ma_p, 'tolerance': tol, 'tp_pct': tp,
                      'macd_window': mw, 'vol_ratio': vr, 'hard_stop': hs,
                      'atr_mult': am, 'max_hold': mh}
            trades = backtest(df, params)
            scores = compute_scores(trades)
            scores.update(params)
            scores['code'] = code
            scores['skeleton_rank'] = rank + 1
            all_results.append(scores)
            count += 1
            if count % 500 == 0:
                print(f"      进度: {count}/{n_per}")
    
    df_r = pd.DataFrame(all_results)
    df_r['composite'] = (
        df_r['win_rate'] * 0.30 + df_r['cum_return'] * 0.30 +
        df_r['sharpe'].clip(-1, 3) * 0.20 -
        df_r['max_consecutive_loss'] * 0.01 - abs(df_r['max_dd']) * 0.10
    )
    return df_r.sort_values('composite', ascending=False)


def print_top(df, title, n=10):
    print(f"\n{'='*100}")
    print(f"  {title}")
    print(f"{'='*100}")
    h = (f"{'#':>3} | {'MA':>3} {'Tol':>4} {'TP':>5} | "
         f"{'MACDw':>5} {'VolR':>4} {'Stop%':>5} {'ATR':>4} {'Hold':>4} | "
         f"{'T':>3} {'WR%':>6} {'Cum%':>7} {'Sh':>6} {'DD%':>6} {'CL':>3} | {'Score':>6}")
    print(h)
    print('-' * len(h))
    for rank, (_, row) in enumerate(df.head(n).iterrows()):
        print(f"{rank+1:>3} | {int(row.get('ma_period',0)):>3} "
              f"{row.get('tolerance',0)*100:>3.0f}% "
              f"{row.get('tp_pct',0)*100:>4.0f}% | "
              f"{int(row.get('macd_window',0)):>5} "
              f"{row.get('vol_ratio',0):>4.1f} "
              f"{row.get('hard_stop',0)*100:>4.0f}% "
              f"{row.get('atr_mult',0):>4.1f} "
              f"{int(row.get('max_hold',0)):>4} | "
              f"{int(row['trades']):>3} "
              f"{row['win_rate']*100:>5.1f}% "
              f"{row['cum_return']*100:>6.1f}% "
              f"{row['sharpe']:>6.3f} "
              f"{row['max_dd']*100:>5.1f}% "
              f"{int(row['max_consecutive_loss']):>3} | "
              f"{row['composite']:>6.4f}")


def main():
    codes = sys.argv[1:] if len(sys.argv) > 1 else ['512100', '510500']
    if 'all' in codes:
        codes = ['512100', '510500']
    
    all_final = {}
    
    for code in codes:
        print(f"\n{'#'*100}")
        print(f"#  {code} MA60回踩策略 — 两轮全量网格遍历回测")
        print(f"#  启动: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'#'*100}")
        
        df = load_data(code)
        n_days = len(df)
        d_min = df['trade_date'].min().date()
        d_max = df['trade_date'].max().date()
        print(f"\n数据加载: {n_days}行, {d_min} ~ {d_max}")
        
        r1 = run_round1(code, df)
        print(f"\n✅ 第一轮完成: {len(r1)}组合")
        print_top(r1, f"第一轮 Top 10 — {code}", 10)
        
        top3 = r1.head(3)
        r2 = run_round2(code, df, top3)
        print(f"\n✅ 第二轮完成: {len(r2)}组合")
        print_top(r2, f"第二轮 最终 Top 15 — {code}", 15)
        
        all_final[code] = r2
        
        outfile = f'/home/agent/cow/tmp/{code}_ma60_gridsearch.json'
        r2.head(50).to_json(outfile, orient='records', indent=2, force_ascii=False)
        print(f"\n💾 Top 50 已保存: {outfile}")
    
    if len(codes) == 2:
        print(f"\n{'#'*100}")
        print(f"#  两标最终 Top 5 汇总对比")
        print(f"{'#'*100}")
        for code in codes:
            print_top(all_final[code], f"{code} Top 5", 5)


if __name__ == '__main__':
    main()
