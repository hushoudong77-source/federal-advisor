#!/usr/bin/env python3
"""宏观锚点历史回测 V1.0"""
import tushare as ts
import pandas as pd
import numpy as np
import io, requests

pro = ts.pro_api()

print("=" * 80)
print("  宏观锚点历史回测 V1.0")
print("=" * 80)

# VIX
print("\n[1/3] VIX...")
vix_url = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
vix_raw = pd.read_csv(io.StringIO(requests.get(vix_url, timeout=15).text))
vix_raw['DATE'] = pd.to_datetime(vix_raw['DATE'])
vix_raw = vix_raw.rename(columns={'DATE':'date', 'CLOSE':'vix'}).sort_values('date')
print(f"  {len(vix_raw)}行, {vix_raw['date'].min().date()} ~ {vix_raw['date'].max().date()}")

# US10Y
print("[2/3] US10Y...")
df_ty = pro.us_tycr(start_date='20140101', end_date='20260630')
df_ty['date'] = pd.to_datetime(df_ty['date'])
df_ty['date_str'] = df_ty['date'].dt.strftime('%Y%m%d')
print(f"  {len(df_ty)}行")

# IVV
print("[3/3] IVV...")
df_ivv = pro.us_daily(ts_code='IVV', start_date='20140101', end_date='20260630')
df_ivv['trade_date'] = pd.to_datetime(df_ivv['trade_date'])
df_ivv['date_str'] = df_ivv['trade_date'].dt.strftime('%Y%m%d')
print(f"  {len(df_ivv)}行")

# 合并
vix_raw['date_str'] = vix_raw['date'].dt.strftime('%Y%m%d')
merged = df_ivv.merge(df_ty[['date_str','y10']], on='date_str', how='left')
merged = merged.merge(vix_raw[['date_str','vix']], on='date_str', how='left')
merged = merged.dropna(subset=['y10','vix']).sort_values('trade_date')
print(f"  合并: {len(merged)}行, {merged['trade_date'].min().date()} ~ {merged['trade_date'].max().date()}")

# ==========================================
# 回测一: US10Y
# ==========================================
print("\n" + "=" * 80)
print("  回测一: US10Y熔断阈值 (IVV)")
print("=" * 80)
print(f"  {'阈值':>6s}  {'天':>6s}  {'占比':>6s}  {'熔断日均':>10s}  {'正常日均':>10s}  {'差':>8s}  {'胜率':>7s}  {'后5日':>9s}  {'后20日':>10s}")

for t in np.arange(2.5, 5.25, 0.25):
    m = merged['y10'] >= t
    d = m.sum()
    if d < 10: continue
    mr = merged.loc[m, 'pct_change'].mean()
    nr = merged.loc[~m, 'pct_change'].mean()
    mw = (merged.loc[m, 'pct_change'] > 0).mean()
    f5 = []; f20 = []
    for idx in merged[m].index:
        ff5 = merged.loc[idx:].head(6)
        ff20 = merged.loc[idx:].head(21)
        if len(ff5)>=6: f5.append((ff5.iloc[5]['close']/ff5.iloc[0]['close']-1)*100)
        if len(ff20)>=21: f20.append((ff20.iloc[20]['close']/ff20.iloc[0]['close']-1)*100)
    print(f'{t:>5.2f}%  {d:>6d}  {d/len(merged)*100:>5.1f}%  {mr:>9.4f}%  {nr:>9.4f}%  {mr-nr:>7.3f}%  {mw:>6.1%}  {np.mean(f5):>8.2f}%  {np.mean(f20):>9.2f}%')

print("\n🔍 US10Y≥5.00%: Tushare 2018-2026触发0次 — 阈值从未被测试过")

# ==========================================
# 回测二: VIX
# ==========================================
print("\n" + "=" * 80)
print("  回测二: VIX危机阈值 (IVV)")
print("=" * 80)
print(f"  {'VIX>':>6s}  {'天':>6s}  {'占比':>6s}  {'危机日均':>10s}  {'正常日均':>10s}  {'差':>8s}  {'胜率':>7s}  {'后5日':>9s}  {'后20日':>10s}")

for t in [15,18,20,22,25,28,30,32,35,40,45,50]:
    m = merged['vix'] > t
    d = m.sum()
    if d < 5: continue
    cr = merged.loc[m, 'pct_change'].mean()
    nr = merged.loc[~m, 'pct_change'].mean()
    cw = (merged.loc[m, 'pct_change'] > 0).mean()
    f5 = []; f20 = []
    for idx in merged[m].index:
        ff5 = merged.loc[idx:].head(6)
        ff20 = merged.loc[idx:].head(21)
        if len(ff5)>=6: f5.append((ff5.iloc[5]['close']/ff5.iloc[0]['close']-1)*100)
        if len(ff20)>=21: f20.append((ff20.iloc[20]['close']/ff20.iloc[0]['close']-1)*100)
    print(f'{t:>6.0f}  {d:>6d}  {d/len(merged)*100:>5.1f}%  {cr:>9.4f}%  {nr:>9.4f}%  {cr-nr:>7.3f}%  {cw:>6.1%}  {np.mean(f5):>8.2f}%  {np.mean(f20):>9.2f}%')

# VIX分档
print("\n🔍 VIX四档:")
for label, lo, hi in [('NORMAL ≤20',0,20),('ALERT 20-35',20,35),('CRISIS 35-50',35,50),('MELTDOWN >50',50,999)]:
    if lo==0: m=merged['vix']<=hi
    elif hi==999: m=merged['vix']>lo
    else: m=(merged['vix']>lo)&(merged['vix']<=hi)
    d=m.sum()
    print(f"  {label:>15s}: {d:>5d}天 ({d/len(merged)*100:>4.1f}%)  IVV日均={merged.loc[m,'pct_change'].mean():+.4f}%")

# ==========================================
# 回测三: VIX各阶段IAU
# ==========================================
print("\n" + "=" * 80)
print("  回测三: VIX各阶段IAU(黄金)")
print("=" * 80)

iau = pro.us_daily(ts_code='IAU', start_date='20140101', end_date='20260630')
iau['trade_date'] = pd.to_datetime(iau['trade_date'])
iau['date_str'] = iau['trade_date'].dt.strftime('%Y%m%d')
iaum = iau.merge(vix_raw[['date_str','vix']], on='date_str', how='left').dropna(subset=['vix'])

print(f"  {'VIX区间':>20s}  {'天':>6s}  {'IAU日均':>10s}  {'胜率':>7s}  {'累计':>8s}")
for label, lo, hi in [('≤20 NORMAL',0,20),('20-35 ALERT',20,35),('35-50 CRISIS',35,50),('>50 MELTDOWN',50,999)]:
    if lo==0: m=iaum['vix']<=hi
    elif hi==999: m=iaum['vix']>lo
    else: m=(iaum['vix']>lo)&(iaum['vix']<=hi)
    d=m.sum()
    if d>0:
        s=iaum[m]
        print(f'{label:>20s}  {d:>6d}  {s["pct_change"].mean():>9.4f}%  {(s["pct_change"]>0).mean():>6.1%}  {s["pct_change"].sum():>7.2f}%')

# ==========================================
# 回测四: 五维简化
# ==========================================
print("\n" + "=" * 80)
print("  回测四: 五维评估简化 (利率方向+VIX)")
print("=" * 80)

merged['y10_ma20'] = merged['y10'].rolling(20).mean()
merged['y10_ma20_5d'] = merged['y10_ma20'].shift(5)
merged['rate_dir'] = np.where(merged['y10_ma20'] > merged['y10_ma20_5d'] + 0.03, 'UP',
                     np.where(merged['y10_ma20'] < merged['y10_ma20_5d'] - 0.03, 'DOWN', 'FLAT'))
merged['dim_r'] = merged['rate_dir'].map({'DOWN':2,'FLAT':1,'UP':0})
merged['dim_v'] = np.where(merged['vix']<=20,2,np.where(merged['vix']<=35,1,0))
merged['s2d'] = merged['dim_r'] + merged['dim_v']

print(f"  {'评分':>12s}  {'天':>6s}  {'占比':>6s}  {'日均':>9s}  {'胜率':>7s}  {'后5日':>9s}  {'后20日':>10s}")
for sc in range(5):
    m = merged['s2d'] == sc
    d = m.sum()
    if d<10: continue
    seg = merged[m]
    r = seg['pct_change'].mean()
    w = (seg['pct_change']>0).mean()
    f5=[]; f20=[]
    for idx in seg.index:
        ff5=merged.loc[idx:].head(6); ff20=merged.loc[idx:].head(21)
        if len(ff5)>=6: f5.append((ff5.iloc[5]['close']/ff5.iloc[0]['close']-1)*100)
        if len(ff20)>=21: f20.append((ff20.iloc[20]['close']/ff20.iloc[0]['close']-1)*100)
    lb = ['🔴🔴双杀','🔴偏空','🟡中性','🟡偏多','🟢双顺'][sc]
    print(f'{lb:>12s}  {d:>6d}  {d/len(merged)*100:>5.1f}%  {r:>8.4f}%  {w:>6.1%}  {np.mean(f5):>8.2f}%  {np.mean(f20):>9.2f}%')

print("\n✅ 回测完成")
