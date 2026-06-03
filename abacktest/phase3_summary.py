#!/usr/bin/env python3
"""Phase 3 绩效汇总"""
import pandas as pd
import numpy as np

df = pd.read_csv('/home/agent/cow/abacktest/phase3_raw_results.csv')
df['date'] = pd.to_datetime(df['date'])

# 分离进攻和反击
spear = df[df['strategy'] == 'SPEARHEAD']
counter = df[df['strategy'] == 'COUNTERPUNCH']

print("=" * 100)
print("PHASE 3 全量绩效回测 — V5.8.2r11 完整规则")
print(f"数据范围: 2018-01-02 ~ 2026-05-15 | 17标 | 总交易笔数: {len(df)}")
print("=" * 100)

# ======== 进攻策略 ========
print("\n" + "=" * 100)
print("§3.1 进攻策略 (Spearhead) 绩效汇总")
print("=" * 100)

spear_entries = spear[spear['type'] == 'ENTRY']
spear_exits = spear[spear['type'] == 'EXIT']

spear_summary = []
for sym in sorted(spear['symbol'].unique()):
    s_entries = spear_entries[spear_entries['symbol'] == sym]
    s_exits = spear_exits[spear_exits['symbol'] == sym]
    n_trades = len(s_exits)
    if n_trades == 0:
        continue
    wins = (s_exits['pnl_pct'] > 0).sum()
    losses = (s_exits['pnl_pct'] <= 0).sum()
    win_rate = wins / n_trades * 100
    avg_pnl = s_exits['pnl_pct'].mean()
    total_pnl = s_exits['pnl_pct'].sum()
    max_win = s_exits['pnl_pct'].max()
    max_loss = s_exits['pnl_pct'].min()
    avg_hold = s_exits['hold_days'].mean()
    
    # 按离场原因统计
    reasons = s_exits['reason'].value_counts().to_dict()
    
    spear_summary.append({
        'symbol': sym, 'trades': n_trades, 'wins': wins, 'losses': losses,
        'win_rate': win_rate, 'total_pnl': total_pnl, 'avg_pnl': avg_pnl,
        'max_win': max_win, 'max_loss': max_loss, 'avg_hold': avg_hold,
        'reasons': reasons
    })

spear_df = pd.DataFrame(spear_summary)
spear_df = spear_df.sort_values('total_pnl', ascending=False)
print(f"{'标的':<8s} {'笔数':>4s} {'胜率':>6s} {'总收益%':>8s} {'均笔%':>7s} {'最大赢%':>8s} {'最大亏%':>8s} {'均持日':>6s}")
print("-" * 80)
for _, r in spear_df.iterrows():
    print(f"{r['symbol']:<8s} {int(r['trades']):>4d} {r['win_rate']:>5.1f}% {r['total_pnl']:>7.2f}% {r['avg_pnl']:>6.2f}% {r['max_win']:>7.2f}% {r['max_loss']:>7.2f}% {r['avg_hold']:>5.0f}d")

# ======== 反击策略 ========
print("\n" + "=" * 100)
print("§3.2 反击策略 (Counterpunch) 绩效汇总")
print("=" * 100)

counter_entries = counter[counter['type'] == 'ENTRY']
counter_exits = counter[counter['type'] == 'EXIT']

counter_summary = []
for sym in sorted(counter['symbol'].unique()):
    c_entries = counter_entries[counter_entries['symbol'] == sym]
    c_exits = counter_exits[counter_exits['symbol'] == sym]
    n_trades = len(c_exits)
    if n_trades == 0:
        continue
    wins = (c_exits['pnl_pct'] > 0).sum()
    losses = (c_exits['pnl_pct'] <= 0).sum()
    win_rate = wins / n_trades * 100
    avg_pnl = c_exits['pnl_pct'].mean()
    total_pnl = c_exits['pnl_pct'].sum()
    max_win = c_exits['pnl_pct'].max()
    max_loss = c_exits['pnl_pct'].min()
    avg_hold = c_exits['hold_days'].mean()
    avg_batches = c_exits['batches'].mean()
    
    reasons = c_exits['reason'].value_counts().to_dict()
    
    counter_summary.append({
        'symbol': sym, 'trades': n_trades, 'wins': wins, 'losses': losses,
        'win_rate': win_rate, 'total_pnl': total_pnl, 'avg_pnl': avg_pnl,
        'max_win': max_win, 'max_loss': max_loss, 'avg_hold': avg_hold,
        'avg_batches': avg_batches, 'reasons': reasons
    })

counter_df = pd.DataFrame(counter_summary)
counter_df = counter_df.sort_values('total_pnl', ascending=False)
print(f"{'标的':<8s} {'笔数':>4s} {'胜率':>6s} {'总收益%':>8s} {'均笔%':>7s} {'最大赢%':>8s} {'最大亏%':>8s} {'均持日':>6s} {'均批次':>6s}")
print("-" * 80)
for _, r in counter_df.iterrows():
    print(f"{r['symbol']:<8s} {int(r['trades']):>4d} {r['win_rate']:>5.1f}% {r['total_pnl']:>7.2f}% {r['avg_pnl']:>6.2f}% {r['max_win']:>7.2f}% {r['max_loss']:>7.2f}% {r['avg_hold']:>5.0f}d {r['avg_batches']:>5.1f}")

# ======== 离场原因分布 ========
print("\n" + "=" * 100)
print("离场原因分布")
print("=" * 100)

print("\n进攻策略离场原因:")
all_spear_reasons = {}
for _, r in spear_df.iterrows():
    for reason, count in r['reasons'].items():
        all_spear_reasons[reason] = all_spear_reasons.get(reason, 0) + count

for reason, count in sorted(all_spear_reasons.items(), key=lambda x: -x[1]):
    print(f"  {reason:<30s}: {count:>4d}")

print("\n反击策略离场原因:")
all_counter_reasons = {}
for _, r in counter_df.iterrows():
    for reason, count in r['reasons'].items():
        all_counter_reasons[reason] = all_counter_reasons.get(reason, 0) + count

for reason, count in sorted(all_counter_reasons.items(), key=lambda x: -x[1]):
    print(f"  {reason:<30s}: {count:>4d}")

# ======== 宏观闸触发 ========
print("\n" + "=" * 100)
print("宏观闸触发统计")
print("=" * 100)
us10y = pd.read_csv('/home/agent/cow/data/us10y_2018_2026.csv')
us10y['date'] = pd.to_datetime(us10y['date'])
us10y['y10'] = us10y['y10'].astype(float)
us10y['surge'] = us10y['y10'].diff() * 100

red_days = us10y[us10y['y10'] >= 5.00]
yellow_days = us10y[(us10y['y10'] >= 4.50) & (us10y['y10'] < 5.00)]
surge_days = us10y[us10y['surge'] > 8]

print(f"US10Y≥5.00% (红灯): {len(red_days)} 日")
print(f"US10Y≥4.50% (黄灯): {len(yellow_days)} 日")
print(f"US10Y单日跳升>8bp: {len(surge_days)} 日")

if len(yellow_days) > 0:
    print(f"黄灯区间: {yellow_days['date'].min().date()} ~ {yellow_days['date'].max().date()}")

print("\n✅ Phase 3 完成")
