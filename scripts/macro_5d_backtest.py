#!/usr/bin/env python3
"""
五维全量宏观锚点回测 (2026-06-28)
维度: 利率方向(US10Y MA20) / 美元方向(DXY MA20) / 恐慌烈度(VIX) / 事件静默(日历) / 博弈态(ADX+成交量)
数据源: Tushare (US10Y/VIX/DXY/ADX/成交量), 手动(事件日历)
"""

import tushare as ts
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta

# ============================================================
# 0. 初始化
# ============================================================
token = os.environ.get('TUSHARE_TOKEN', '')
if not token:
    token = '95e02772a2205c7cefc3e05725a84ce18347a3d5e9c710e9bf330387'
pro = ts.pro_api(token)

print("=" * 70)
print("五维全量宏观锚点回测")
print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

# ============================================================
# 1. 数据拉取
# ============================================================

# 1.1 IVV日线 (基准资产)
print("\n[1/5] 拉取 IVV 日线...")
ivv = pro.us_daily(ts_code='IVV', start_date='20180101', end_date='20260627')
ivv = ivv.sort_values('trade_date').reset_index(drop=True)
print(f"  IVV: {len(ivv)} 行, {ivv['trade_date'].iloc[0]} ~ {ivv['trade_date'].iloc[-1]}")

# 1.2 US10Y
print("[2/5] 拉取 US10Y...")
us10y = pro.us_tycr(start_date='20180101', end_date='20260627')
us10y = us10y.sort_values('date').reset_index(drop=True)
us10y.rename(columns={'date': 'trade_date', 'y10': 'close'}, inplace=True)
print(f"  US10Y: {len(us10y)} 行, {us10y['trade_date'].iloc[0]} ~ {us10y['trade_date'].iloc[-1]}")

# 1.3 VIX
print("[3/5] 拉取 VIX...")
vix = pro.index_global(ts_code='VIX', start_date='20180101', end_date='20260627')
if vix is None or len(vix) == 0:
    # fallback: use us_daily for VIX ETF proxy
    vix = pro.us_daily(ts_code='VXX', start_date='20180101', end_date='20260627')
    print(f"  VIX (VXX proxy): {len(vix)} 行")
else:
    vix = vix.sort_values('trade_date').reset_index(drop=True)
    print(f"  VIX: {len(vix)} 行, {vix['trade_date'].iloc[0]} ~ {vix['trade_date'].iloc[-1]}")

# 1.4 DXY
print("[4/5] 拉取 DXY...")
dxy = pro.index_global(ts_code='DXY', start_date='20180101', end_date='20260627')
if dxy is None or len(dxy) == 0:
    dxy = pro.us_daily(ts_code='UUP', start_date='20180101', end_date='20260627')
    print(f"  DXY (UUP proxy): {len(dxy)} 行")
else:
    dxy = dxy.sort_values('trade_date').reset_index(drop=True)
    print(f"  DXY: {len(dxy)} 行, {dxy['trade_date'].iloc[0]} ~ {dxy['trade_date'].iloc[-1]}")

# 1.5 IAU (黄金)
print("[5/5] 拉取 IAU...")
iau = pro.us_daily(ts_code='IAU', start_date='20180101', end_date='20260627')
iau = iau.sort_values('trade_date').reset_index(drop=True)
print(f"  IAU: {len(iau)} 行, {iau['trade_date'].iloc[0]} ~ {iau['trade_date'].iloc[-1]}")

# ============================================================
# 2. 指标计算
# ============================================================

# 2.1 IVV returns
ivv['ret'] = ivv['close'].pct_change()
ivv['ret_5d'] = ivv['close'].pct_change(5)
ivv['ret_20d'] = ivv['close'].pct_change(20)

# 2.2 US10Y MA20 direction
us10y['yield'] = pd.to_numeric(us10y['close'], errors='coerce')
us10y['ma20'] = us10y['yield'].rolling(20).mean()
us10y['ma20_dir'] = 'flat'
us10y.loc[us10y['ma20'].diff(5) > 0.03, 'ma20_dir'] = 'up'    # >3bp/5d
us10y.loc[us10y['ma20'].diff(5) < -0.03, 'ma20_dir'] = 'down'

# 2.3 VIX levels
vix['vix_val'] = pd.to_numeric(vix['close'], errors='coerce')

vix['vix_zone'] = 'NORMAL'
vix.loc[vix['vix_val'] > 20, 'vix_zone'] = 'ALERT'
vix.loc[vix['vix_val'] > 35, 'vix_zone'] = 'CRISIS'
vix.loc[vix['vix_val'] > 50, 'vix_zone'] = 'MELTDOWN'

# 2.4 DXY MA20 direction
dxy['val'] = pd.to_numeric(dxy['close'], errors='coerce')
dxy['ma20'] = dxy['val'].rolling(20).mean()
dxy['ma20_dir'] = 'flat'
dxy.loc[dxy['ma20'].diff(5) > 0, 'ma20_dir'] = 'up'    # any uptick
dxy.loc[dxy['ma20'].diff(5) < 0, 'ma20_dir'] = 'down'

# 2.5 IAU returns
iau['ret'] = iau['close'].pct_change()

# ============================================================
# 3. 合并数据
# ============================================================
print("\n[合并] 对齐日期...")

merged = ivv[['trade_date', 'close', 'ret', 'ret_5d', 'ret_20d']].copy()
merged.columns = ['trade_date', 'ivv_close', 'ivv_ret', 'ivv_ret_5d', 'ivv_ret_20d']

# merge US10Y
us10y_sub = us10y[['trade_date', 'yield', 'ma20_dir']].copy()
merged = merged.merge(us10y_sub, on='trade_date', how='left')
merged['ma20_dir'] = merged['ma20_dir'].fillna('flat')

# merge VIX
vix_sub = vix[['trade_date', 'vix_val', 'vix_zone']].copy()
merged = merged.merge(vix_sub, on='trade_date', how='left')

# merge DXY
dxy_sub = dxy[['trade_date', 'val', 'ma20_dir']].copy()
dxy_sub.columns = ['trade_date', 'dxy_val', 'dxy_ma20_dir']
merged = merged.merge(dxy_sub, on='trade_date', how='left')
merged['dxy_ma20_dir'] = merged['dxy_ma20_dir'].fillna('flat')

# merge IAU
iau_sub = iau[['trade_date', 'close', 'ret']].copy()
iau_sub.columns = ['trade_date', 'iau_close', 'iau_ret']
merged = merged.merge(iau_sub, on='trade_date', how='left')

merged = merged.dropna(subset=['ivv_ret'])
print(f"  合并后: {len(merged)} 行")

# ============================================================
# 4. 五维全量回测
# ============================================================

# Dimension scoring (simple version)
# 利率: down=🟢(1) flat=🟡(0) up=🔴(-1)
merged['d_ir'] = merged['ma20_dir'].map({'down': 1, 'flat': 0, 'up': -1})

# 美元: down=🟢(1) flat=🟡(0) up=🔴(-1)  -- inverted: weak dollar good for stocks
merged['d_dxy'] = merged['dxy_ma20_dir'].map({'down': 1, 'flat': 0, 'up': -1})

# VIX: NORMAL=🟢(2) ALERT=🟡(0) CRISIS=🔴(-2) MELTDOWN=🔴🔴(-3)
merged['d_vix'] = merged['vix_zone'].map({'NORMAL': 2, 'ALERT': 0, 'CRISIS': -2, 'MELTDOWN': -3})

# Total score (3 dims without events and game theory)
merged['score_3d'] = merged['d_ir'] + merged['d_dxy'] + merged['d_vix']

# 5D category
def classify_5d(row):
    ir = row['d_ir']
    dxy = row['d_dxy']
    vix = row['d_vix']
    score = ir + dxy + vix
    
    if vix <= -2:  # CRISIS or MELTDOWN
        return '🔴危机'
    if score >= 4:
        return '🟢全顺风'
    elif score >= 2:
        return '🟢偏顺风'
    elif score >= 0:
        return '🟡中性'
    elif score >= -1:
        return '🟡偏逆风'
    else:
        return '🔴逆风'

merged['cat_5d'] = merged.apply(classify_5d, axis=1)

# ============================================================
# 5. 回测结果
# ============================================================

print("\n" + "=" * 70)
print("五维全量回测结果 (3维可自动计算: 利率+美元+VIX)")
print("=" * 70)

# 5.1 逐类统计
for cat in ['🟢全顺风', '🟢偏顺风', '🟡中性', '🟡偏逆风', '🔴逆风', '🔴危机']:
    subset = merged[merged['cat_5d'] == cat]
    if len(subset) == 0:
        continue
    print(f"\n{cat}: {len(subset)}天 ({len(subset)/len(merged)*100:.1f}%)")
    print(f"  IVV日均: {subset['ivv_ret'].mean()*100:+.3f}% | 胜率: {(subset['ivv_ret']>0).mean()*100:.1f}%")
    print(f"  IVV后5日: {subset['ivv_ret_5d'].mean()*100:+.2f}% | 后20日: {subset['ivv_ret_20d'].mean()*100:+.2f}%")
    if 'iau_ret' in subset.columns:
        iau_subset = subset.dropna(subset=['iau_ret'])
        if len(iau_subset) > 0:
            print(f"  IAU日均: {iau_subset['iau_ret'].mean()*100:+.3f}%")

# 5.2 当前状态
current = merged.iloc[-1]
print(f"\n{'='*70}")
print(f"当前状态 ({current['trade_date']}):")
print(f"  US10Y: {current['yield']:.2f}% | MA20方向: {current['ma20_dir']} (+{int(current['d_ir'])})")
print(f"  DXY: {current.get('dxy_val', 0):.1f} | MA20方向: {current['dxy_ma20_dir']} (+{int(current['d_dxy'])})")
print(f"  VIX: {current['vix_val']:.1f} | 区域: {current['vix_zone']} ({int(current['d_vix']):+d})")
print(f"  总分: {int(current['score_3d']):+d} | 分类: {current['cat_5d']}")

# 5.3 两维 vs 三维对比
print(f"\n{'='*70}")
print("维度展开对比")
print("=" * 70)

# US10Y MA20 direction
for d in ['up', 'flat', 'down']:
    s = merged[merged['ma20_dir'] == d]
    if len(s) == 0: continue
    print(f"  US10Y MA20{d:>5s}: {len(s)}天 | IVV日均{s['ivv_ret'].mean()*100:+.3f}% | 胜率{(s['ivv_ret']>0).mean()*100:.1f}% | 后20日{s['ivv_ret_20d'].mean()*100:+.2f}%")

print()
for d in ['up', 'flat', 'down']:
    s = merged[merged['dxy_ma20_dir'] == d]
    if len(s) == 0: continue
    print(f"  DXY MA20{d:>5s}: {len(s)}天 | IVV日均{s['ivv_ret'].mean()*100:+.3f}% | 胜率{(s['ivv_ret']>0).mean()*100:.1f}% | 后20日{s['ivv_ret_20d'].mean()*100:+.2f}%")

# 5.4 Interaction matrix
print(f"\n{'='*70}")
print("交互矩阵: US10Y × DXY → IVV日均")
print("=" * 70)
for ir_dir in ['down', 'flat', 'up']:
    for dxy_dir in ['down', 'flat', 'up']:
        s = merged[(merged['ma20_dir'] == ir_dir) & (merged['dxy_ma20_dir'] == dxy_dir)]
        if len(s) < 10:
            continue
        print(f"  IR={ir_dir:>4s} × DXY={dxy_dir:>4s}: {len(s)}天 | IVV日均{s['ivv_ret'].mean()*100:+.3f}% | 胜率{(s['ivv_ret']>0).mean()*100:.1f}%")

# 5.5 VIX × IR interaction
print(f"\n{'='*70}")
print("交互矩阵: VIX区域 × US10Y方向 → IVV日均")
print("=" * 70)
for vz in ['NORMAL', 'ALERT', 'CRISIS', 'MELTDOWN']:
    for ir_dir in ['down', 'flat', 'up']:
        s = merged[(merged['vix_zone'] == vz) & (merged['ma20_dir'] == ir_dir)]
        if len(s) < 5:
            continue
        print(f"  VIX={vz:>8s} × IR={ir_dir:>4s}: {len(s)}天 | IVV日均{s['ivv_ret'].mean()*100:+.3f}%")

print("\n✅ 五维回测完成")
