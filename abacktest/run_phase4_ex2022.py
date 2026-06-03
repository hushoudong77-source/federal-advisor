#!/usr/bin/env python3
"""Phase 4 剔除2022年回测 — 守东2026-05-16指令"""
import sys
sys.path.insert(0, '/home/agent/cow/abacktest')
from phase3_engine import *
import pandas as pd
import numpy as np

EXCLUDE_YEARS = {2022}

SPEARHEAD_SYMBOLS = ['QQQ', 'IVV', 'BBJP', 'MUFG', 'EWY', 'VNM', 'FLIN']
COUNTERPUNCH_SYMBOLS = list(COUNTERPUNCH_PARAMS.keys())
ALL_SYMBOLS = sorted(set(SPEARHEAD_SYMBOLS) | set(COUNTERPUNCH_SYMBOLS))

print(f"Phase 4 剔除2022年: {len(ALL_SYMBOLS)} symbols, 2018-2026 (excl 2022)")
print(f"Spearhead: {SPEARHEAD_SYMBOLS}")
print(f"Counterpunch: {COUNTERPUNCH_SYMBOLS}")
print("=" * 80)

# 加载US10Y，也剔除2022年
us10y_df = load_us10y()
us10y_df = us10y_df[~us10y_df['date'].dt.year.isin(EXCLUDE_YEARS)].reset_index(drop=True)
print(f"US10Y loaded: {len(us10y_df)} rows, {us10y_df['date'].min()} to {us10y_df['date'].max()}")

all_results = []

for symbol in ALL_SYMBOLS:
    df = load_data(symbol, exclude_years=EXCLUDE_YEARS)
    if df is None:
        print(f"  {symbol}: DATA MISSING - SKIP")
        continue
    
    df = compute_indicators(df)
    print(f"  {symbol}: {len(df)} rows, {df['date'].min().date()} to {df['date'].max().date()}")
    
    if symbol in SPEARHEAD_SYMBOLS:
        spear_trades = run_spearhead_backtest(symbol, df, us10y_df)
        for t in spear_trades:
            t['strategy'] = 'SPEARHEAD'
        all_results.extend(spear_trades)
    
    if symbol in COUNTERPUNCH_SYMBOLS:
        counter_trades = run_counterpunch_backtest(symbol, df, us10y_df)
        for t in counter_trades:
            t['strategy'] = 'COUNTERPUNCH'
        all_results.extend(counter_trades)

results_df = pd.DataFrame(all_results)
results_df.to_csv('/home/agent/cow/abacktest/phase4_ex2022_raw.csv', index=False)
print(f"\nTotal trades: {len(results_df)}")
print(f"Saved to phase4_ex2022_raw.csv")
