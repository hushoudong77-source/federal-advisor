#!/usr/bin/env python3
"""Phase 3 主执行脚本"""
import sys
sys.path.insert(0, '/home/agent/cow/abacktest')
from phase3_engine import *
import pandas as pd
import numpy as np

# 标的分类
SPEARHEAD_SYMBOLS = ['QQQ', 'IVV', 'BBJP', 'MUFG', 'EWY', 'VNM', 'FLIN']
COUNTERPUNCH_SYMBOLS = list(COUNTERPUNCH_PARAMS.keys())
ALL_SYMBOLS = sorted(set(SPEARHEAD_SYMBOLS) | set(COUNTERPUNCH_SYMBOLS))

print(f"Phase 3: {len(ALL_SYMBOLS)} symbols, 2018-2026")
print(f"Spearhead: {SPEARHEAD_SYMBOLS}")
print(f"Counterpunch: {COUNTERPUNCH_SYMBOLS}")
print("=" * 80)

# 加载US10Y
us10y_df = load_us10y()
print(f"US10Y loaded: {len(us10y_df)} rows, {us10y_df['date'].min()} to {us10y_df['date'].max()}")

# 回测
all_results = []

for symbol in ALL_SYMBOLS:
    df = load_data(symbol)
    if df is None:
        print(f"  {symbol}: DATA MISSING - SKIP")
        continue
    
    df = compute_indicators(df)
    print(f"  {symbol}: {len(df)} rows, {df['date'].min().date()} to {df['date'].max().date()}")
    
    # 进攻回测
    if symbol in SPEARHEAD_SYMBOLS:
        spear_trades = run_spearhead_backtest(symbol, df, us10y_df)
        for t in spear_trades:
            t['strategy'] = 'SPEARHEAD'
        all_results.extend(spear_trades)
    
    # 反击回测 (注意: 进攻和反击独立运行)
    if symbol in COUNTERPUNCH_SYMBOLS:
        counter_trades = run_counterpunch_backtest(symbol, df, us10y_df)
        for t in counter_trades:
            t['strategy'] = 'COUNTERPUNCH'
        all_results.extend(counter_trades)

# 保存原始结果
results_df = pd.DataFrame(all_results)
results_df.to_csv('/home/agent/cow/abacktest/phase3_raw_results.csv', index=False)
print(f"\nTotal trades: {len(results_df)}")
print(f"Saved to phase3_raw_results.csv")
