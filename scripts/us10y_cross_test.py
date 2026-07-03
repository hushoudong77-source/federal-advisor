#!/usr/bin/env python3
"""
US10Y 变动率 × 绝对水平 2×2 交叉测试
审计问题：跳降≥10bp的"顺风信号"是否主要来自低利率区间？
"""
import tushare as ts
import pandas as pd
import numpy as np

pro = ts.pro_api()

# 拉全量US10Y
df_ty = pro.us_tycr(start_date='20180101', end_date='20260703')
df_ty = df_ty.sort_values('date').reset_index(drop=True)

# 拉IVV日线
df_ivv = pro.us_daily(ts_code='IVV', start_date='20180101', end_date='20260703')
df_ivv = df_ivv.sort_values('trade_date').reset_index(drop=True)

# 合并
df = df_ty.merge(df_ivv[['trade_date', 'close']], left_on='date', right_on='trade_date', how='inner')
df['us10y'] = df['y10'].astype(float)
df['close'] = df['close'].astype(float)
df['date'] = pd.to_datetime(df['date'])

# 日变动
df['d_us10y'] = df['us10y'].diff() * 100  # bp
df['d_us10y_pct'] = df['us10y'].pct_change()

# Fwd20D
df['fwd20d'] = df['close'].shift(-20) / df['close'] - 1

# 分类
df['rate_regime'] = 'low'
df.loc[df['us10y'] >= 4.50, 'rate_regime'] = 'high'

# 跳降≥10bp
df['drop_10bp'] = df['d_us10y'] <= -10

# 跳升≥8bp
df['jump_8bp'] = df['d_us10y'] >= 8

print("=" * 70)
print("US10Y 变动率 × 绝对水平 2×2 交叉测试")
print("数据范围:", df['date'].min().strftime('%Y-%m-%d'), "~", df['date'].max().strftime('%Y-%m-%d'))
print("总观测:", len(df))
print("=" * 70)

# 2×2矩阵: 跳降≥10bp
print("\n## 矩阵1: 跳降≥10bp × 利率水平")
print(f"{'':>20} {'US10Y < 4.50%':>25} {'US10Y ≥ 4.50%':>25}")
print("-" * 70)

for label, cond in [('跳降≥10bp', df['drop_10bp']), ('非跳降', ~df['drop_10bp'])]:
    low = df[cond & (df['rate_regime'] == 'low')]
    high = df[cond & (df['rate_regime'] == 'high')]
    low_fwd = low['fwd20d'].dropna()
    high_fwd = high['fwd20d'].dropna()
    print(f"{label:>20} | n={len(low_fwd):<4} Fwd20D={low_fwd.mean()*100:+.2f}% SR={low_fwd.mean()/low_fwd.std():.2f} | n={len(high_fwd):<4} Fwd20D={high_fwd.mean()*100:+.2f}% SR={high_fwd.mean()/high_fwd.std():.2f}")

# 2×2矩阵: 跳升≥8bp
print("\n## 矩阵2: 跳升≥8bp × 利率水平")
print(f"{'':>20} {'US10Y < 4.50%':>25} {'US10Y ≥ 4.50%':>25}")
print("-" * 70)

for label, cond in [('跳升≥8bp', df['jump_8bp']), ('非跳升', ~df['jump_8bp'])]:
    low = df[cond & (df['rate_regime'] == 'low')]
    high = df[cond & (df['rate_regime'] == 'high')]
    low_fwd = low['fwd20d'].dropna()
    high_fwd = high['fwd20d'].dropna()
    print(f"{label:>20} | n={len(low_fwd):<4} Fwd20D={low_fwd.mean()*100:+.2f}% SR={low_fwd.mean()/low_fwd.std():.2f} | n={len(high_fwd):<4} Fwd20D={high_fwd.mean()*100:+.2f}% SR={high_fwd.mean()/high_fwd.std():.2f}")

# 详细：跳降≥10bp + US10Y≥4.50% 逐笔列出
print("\n## 跳降≥10bp + US10Y≥4.50% 逐笔明细")
high_drops = df[(df['drop_10bp']) & (df['rate_regime'] == 'high')].copy()
high_drops = high_drops.sort_values('date')
for _, row in high_drops.iterrows():
    fwd = row['fwd20d']
    print(f"  {row['date'].strftime('%Y-%m-%d')}  US10Y={row['us10y']:.2f}%  d={row['d_us10y']:+.1f}bp  Fwd20D={fwd*100:+.2f}%")

print(f"\n该象限总样本: {len(high_drops)}")

# 补充：跳降≥10bp 在US10Y<4.50%时的分桶
print("\n## 跳降≥10bp + US10Y<4.50% 按利率分桶")
low_drops = df[(df['drop_10bp']) & (df['rate_regime'] == 'low')].copy()
bins = [0, 2.0, 3.0, 3.5, 4.0, 4.5]
labels = ['<2%', '2-3%', '3-3.5%', '3.5-4%', '4-4.5%']
low_drops['bucket'] = pd.cut(low_drops['us10y'], bins=bins, labels=labels)
for b in labels:
    sub = low_drops[low_drops['bucket'] == b]
    fwd = sub['fwd20d'].dropna()
    if len(fwd):
        print(f"  {b}: n={len(fwd):<4} Fwd20D={fwd.mean()*100:+.2f}% 胜率={len(fwd[fwd>0])/len(fwd)*100:.0f}%")

# 利率方向 × 绝对水平 联合信号
print("\n## 利率方向 × 绝对水平 联合信号")
df['rate_dir'] = 'flat'
df.loc[df['d_us10y'] <= -5, 'rate_dir'] = 'down'
df.loc[df['d_us10y'] >= 5, 'rate_dir'] = 'up'

for regime in ['low', 'high']:
    for direction in ['down', 'flat', 'up']:
        sub = df[(df['rate_regime'] == regime) & (df['rate_dir'] == direction)]
        fwd = sub['fwd20d'].dropna()
        if len(fwd) > 5:
            print(f"  {regime:>5}+{direction:>5}: n={len(fwd):<5} Fwd20D={fwd.mean()*100:+.2f}% 胜率={len(fwd[fwd>0])/len(fwd)*100:.0f}%")

print("\n✅ 交叉测试完成")
