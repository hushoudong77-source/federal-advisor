#!/usr/bin/env python3
"""
512100 / 510500 MA回踩 + 成交量 + 硬止损 全量网格遍历回测
三维：MA周期 × 容忍度 × 缩量阈值 × 硬止损%
止盈固定：512100=+20%, 510500=+15%
数据源：Tushare fund_daily 全量日线
"""

import tushare as ts
import pandas as pd
import numpy as np
from itertools import product
import json
import warnings
warnings.filterwarnings('ignore')

# Tushare token
pro = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

# ==================== 配置 ====================
TICKERS = {
    '512100': {'code': '512100.SH', 'tp_pct': 0.20},
    '510500': {'code': '510500.SH', 'tp_pct': 0.15},
}

GRID = {
    'ma_period': [20, 30, 40, 50, 60],
    'tolerance': [0.02, 0.03, 0.04, 0.05],
    'volume_threshold': [0.6, 0.7, 0.8, 0.9, 1.0],
    'stop_loss': [-0.02, -0.03, -0.04, -0.05, -0.06],
}

def pull_data(code):
    """拉取全量日线"""
    df = pro.fund_daily(ts_code=code, start_date='20180101', end_date='20260708')
    if df is None or len(df) == 0:
        raise RuntimeError(f"Tushare返回空: {code}")
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df['close'] = df['close'].astype(float)
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['vol'] = df['vol'].astype(float)
    return df

def add_indicators(df, ma_period, vol_threshold):
    """计算MA和成交量指标"""
    df = df.copy()
    df['MA'] = df['close'].rolling(ma_period).mean()
    df['VOL_MA20'] = df['vol'].rolling(20).mean()
    df['vol_ratio'] = df['vol'] / df['VOL_MA20']
    
    # MA方向：MA上升
    df['MA_up'] = df['MA'] > df['MA'].shift(1)
    
    # 牛市判定：价格 > MA 且 MA上升
    df['bull'] = (df['close'] > df['MA']) & df['MA_up']
    
    return df

def backtest_single(df, params, tp_pct):
    """单参数组合回测"""
    ma_period = params['ma_period']
    tolerance = params['tolerance']
    vol_threshold = params['volume_threshold']
    stop_loss = params['stop_loss']
    
    df = add_indicators(df, ma_period, vol_threshold)
    
    trades = []
    
    # 逐日扫描
    for i in range(ma_period + 20, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]
        
        # 入场条件（四条件AND）：
        # ① 牛市：价格>MA 且 MA上升
        # ② 回踩：前日收盘>MA，当日最低触及MA±容忍度
        # ③ 缩量：当日vol_ratio < 阈值
        # ④ 不在持仓中
        
        if not row['bull']:
            continue
        
        # 检查回踩
        ma_val = row['MA']
        low_touch = abs(row['low'] - ma_val) / ma_val <= tolerance
        
        # 前日收盘>MA
        prev_above = prev_row['close'] > prev_row['MA']
        
        # 缩量
        vol_ok = row['vol_ratio'] < vol_threshold
        
        if prev_above and low_touch and vol_ok:
            # 入场
            entry_price = row['close']
            entry_date = row['trade_date']
            entry_idx = i
            
            # 止损价
            sl_price = entry_price * (1 + stop_loss)
            
            # 止盈价
            tp_price = entry_price * (1 + tp_pct)
            
            # 模拟持仓（最多120交易日）
            max_hold = 120
            exit_idx = None
            exit_price = None
            exit_reason = None
            
            for j in range(i + 1, min(i + 1 + max_hold, len(df))):
                h = df.iloc[j]['high']
                l = df.iloc[j]['low']
                c = df.iloc[j]['close']
                
                # 止损先触发？
                if l <= sl_price:
                    exit_price = sl_price
                    exit_idx = j
                    exit_reason = '止损'
                    break
                
                # 止盈先触发？
                if h >= tp_price:
                    exit_price = tp_price
                    exit_idx = j
                    exit_reason = '止盈'
                    break
                
                # 强制离场
                if j == min(i + max_hold, len(df)) - 1:
                    exit_price = c
                    exit_idx = j
                    exit_reason = '强制离场'
            
            if exit_idx is not None:
                pnl_pct = (exit_price - entry_price) / entry_price
                trades.append({
                    'entry_date': entry_date,
                    'entry_price': entry_price,
                    'exit_date': df.iloc[exit_idx]['trade_date'],
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason,
                    'hold_days': exit_idx - entry_idx,
                })
    
    return trades

def run_grid(name, code, tp_pct):
    """运行全量网格遍历"""
    print(f"\n{'='*60}")
    print(f"  {name} ({code}) — 全量网格遍历")
    print(f"  MA周期×容忍度×缩量×硬止损 = {len(GRID['ma_period'])}×{len(GRID['tolerance'])}×{len(GRID['volume_threshold'])}×{len(GRID['stop_loss'])} = {len(GRID['ma_period'])*len(GRID['tolerance'])*len(GRID['volume_threshold'])*len(GRID['stop_loss'])} 组合")
    print(f"{'='*60}")
    
    # 拉数据
    print(f"  [1/2] 拉取Tushare全量日线...")
    df = pull_data(code)
    print(f"  → {len(df)} 条日线, {df['trade_date'].min().date()} ~ {df['trade_date'].max().date()}")
    
    # 生成所有参数组合
    keys = list(GRID.keys())
    combinations = list(product(*[GRID[k] for k in keys]))
    print(f"  [2/2] 运行 {len(combinations)} 组回测...")
    
    results = []
    for idx, combo in enumerate(combinations):
        params = dict(zip(keys, combo))
        trades = backtest_single(df, params, tp_pct)
        
        n_trades = len(trades)
        if n_trades > 0:
            wins = sum(1 for t in trades if t['pnl_pct'] > 0)
            winrate = wins / n_trades
            total_pnl = sum(t['pnl_pct'] for t in trades)
            avg_pnl = np.mean([t['pnl_pct'] for t in trades])
            max_pnl = max(t['pnl_pct'] for t in trades)
            min_pnl = min(t['pnl_pct'] for t in trades)
            
            # Sharpe（简化：基于每笔交易的pnl序列）
            pnls = [t['pnl_pct'] for t in trades]
            sharpe = np.mean(pnls) / np.std(pnls) if np.std(pnls) > 0 else 0
            
            # 最大连续亏损笔数
            max_losing_streak = 0
            current_streak = 0
            for p in pnls:
                if p <= 0:
                    current_streak += 1
                    max_losing_streak = max(max_losing_streak, current_streak)
                else:
                    current_streak = 0
            
            # 盈亏比
            avg_win = np.mean([t['pnl_pct'] for t in trades if t['pnl_pct'] > 0]) if wins > 0 else 0
            avg_loss = abs(np.mean([t['pnl_pct'] for t in trades if t['pnl_pct'] <= 0])) if n_trades - wins > 0 else 0
            profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')
            
            # 综合得分（与optuna一致）
            score = winrate * 0.30 + min(avg_pnl * 100, 10) * 0.30 + min(profit_factor, 5) * 0.20 + (n_trades / 100) * 0.15 - max_losing_streak * 0.05
        else:
            winrate = 0
            total_pnl = 0
            avg_pnl = 0
            max_pnl = 0
            min_pnl = 0
            sharpe = 0
            max_losing_streak = 0
            profit_factor = 0
            score = -999
        
        results.append({
            **params,
            'n_trades': n_trades,
            'winrate': winrate,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'max_pnl': max_pnl,
            'min_pnl': min_pnl,
            'sharpe': sharpe,
            'max_losing_streak': max_losing_streak,
            'profit_factor': profit_factor,
            'score': score,
        })
        
        if (idx + 1) % 100 == 0:
            print(f"  进度: {idx+1}/{len(combinations)}")
    
    # 排序
    results_df = pd.DataFrame(results).sort_values('score', ascending=False)
    
    return results_df, df

# ==================== 运行 ====================
all_results = {}

for name, cfg in TICKERS.items():
    results_df, df = run_grid(name, cfg['code'], cfg['tp_pct'])
    all_results[name] = {
        'results': results_df,
        'data_info': f"{len(df)}条日线, {df['trade_date'].min().date()} ~ {df['trade_date'].max().date()}"
    }

# ==================== 输出 ====================
print("\n\n")
print("=" * 80)
print("  全量网格遍历回测 — 最终结果")
print("=" * 80)

for name in TICKERS:
    cfg = TICKERS[name]
    r = all_results[name]['results']
    info = all_results[name]['data_info']
    
    print(f"\n{'─'*80}")
    print(f"  {name} (止盈固定+{cfg['tp_pct']*100:.0f}%) | {info}")
    print(f"{'─'*80}")
    
    # Top 10
    top10 = r.head(10)
    print(f"\n  🏆 Top 10 参数组合:")
    print(f"  {'排名':<4} {'MA周期':<6} {'容忍度':<7} {'缩量':<6} {'硬止损':<7} {'笔数':<5} {'胜率':<7} {'累计':<9} {'均收益':<8} {'Sharpe':<8} {'盈亏比':<7} {'连亏':<4} {'得分':<8}")
    print(f"  {'─'*4} {'─'*6} {'─'*7} {'─'*6} {'─'*7} {'─'*5} {'─'*7} {'─'*9} {'─'*8} {'─'*8} {'─'*7} {'─'*4} {'─'*8}")
    
    for rank, (_, row) in enumerate(top10.iterrows(), 1):
        print(f"  {rank:<4} {int(row['ma_period']):<6} ±{row['tolerance']*100:.0f}%{'':<2} <{row['volume_threshold']:.1f}{'':<2} −{abs(row['stop_loss'])*100:.0f}%{'':<2} "
              f"{int(row['n_trades']):<5} {row['winrate']*100:.1f}%{'':<2} {row['total_pnl']*100:+.2f}%{'':<3} "
              f"{row['avg_pnl']*100:+.2f}%{'':<2} {row['sharpe']:+.3f}{'':<3} {row['profit_factor']:.2f}{'':<3} "
              f"{int(row['max_losing_streak']):<4} {row['score']:+.4f}")
    
    # 统计
    n_pos = (r['total_pnl'] > 0).sum()
    n_neg = (r['total_pnl'] <= 0).sum()
    n_zero = (r['n_trades'] == 0).sum()
    n_total = len(r)
    
    print(f"\n  📊 全量统计 ({n_total}组):")
    print(f"  正期望: {n_pos} ({n_pos/n_total*100:.1f}%) | 负期望: {n_neg} ({n_neg/n_total*100:.1f}%) | 零信号: {n_zero} ({n_zero/n_total*100:.1f}%)")
    
    if n_pos > 0:
        best = r.iloc[0]
        print(f"\n  最优: MA{int(best['ma_period'])} ±{best['tolerance']*100:.0f}% 缩量<{best['volume_threshold']:.1f} 止损−{abs(best['stop_loss'])*100:.0f}%")
        print(f"  {int(best['n_trades'])}笔 | 胜率{best['winrate']*100:.1f}% | 累计{best['total_pnl']*100:+.2f}% | Sharpe{best['sharpe']:+.3f} | PF{best['profit_factor']:.2f}")
    
    # 逐维度边际分析
    print(f"\n  📐 逐维度边际分析（均值）:")
    for dim in ['ma_period', 'tolerance', 'volume_threshold', 'stop_loss']:
        dim_stats = r.groupby(dim).agg(
            avg_score=('score', 'mean'),
            avg_pnl=('total_pnl', 'mean'),
            avg_winrate=('winrate', 'mean'),
            avg_trades=('n_trades', 'mean'),
        ).round(4)
        
        best_dim = dim_stats['avg_score'].idxmax()
        print(f"  {dim}: 最优={best_dim} (得分{dim_stats.loc[best_dim, 'avg_score']:.4f})")
        for val, srow in dim_stats.iterrows():
            marker = ' ←' if val == best_dim else ''
            print(f"    {val}: 得分{srow['avg_score']:.4f} | 均收益{srow['avg_pnl']*100:+.2f}% | 胜率{srow['avg_winrate']*100:.1f}% | 均笔数{srow['avg_trades']:.1f}{marker}")

# 保存完整结果
import os
os.makedirs('/home/agent/cow/tmp', exist_ok=True)
for name in TICKERS:
    all_results[name]['results'].to_csv(f'/home/agent/cow/tmp/{name}_grid_backtest.csv', index=False)

print(f"\n\n✅ 完整结果已保存至 tmp/512100_grid_backtest.csv 和 tmp/510500_grid_backtest.csv")
