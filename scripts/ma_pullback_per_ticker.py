#!/usr/bin/env python3
"""
逐标回踩均线参数搜索 — 每标的独立最优 MA周期 + 确认条件
搜索空间: MA∈[5,10,15,20,25,30,40,50,60] × 确认条件组合 × 缩量阈值
回测周期: 全量历史 (2018-2026)
"""

import pickle, sys
import numpy as np
import pandas as pd

with open('/tmp/backtest_data.pkl', 'rb') as f:
    all_data = pickle.load(f)

# ============ 搜索空间 ============
MA_PERIODS = [5, 10, 15, 20, 25, 30, 40, 50, 60]

# 确认条件组合
CONFIRM_COMBOS = [
    {'name': '纯回踩(无确认)', 'macd': False, 'shrink': False, 'yang': False, 'obv': False},
    {'name': '回踩+MACD金叉', 'macd': True, 'shrink': False, 'yang': False, 'obv': False},
    {'name': '回踩+缩量', 'macd': False, 'shrink': True, 'shrink_ratio': 0.8, 'yang': False, 'obv': False},
    {'name': '回踩+阳线', 'macd': False, 'shrink': False, 'yang': True, 'obv': False},
    {'name': '回踩+MACD+缩量', 'macd': True, 'shrink': True, 'shrink_ratio': 0.8, 'yang': False, 'obv': False},
    {'name': '回踩+MACD+阳线', 'macd': True, 'shrink': False, 'yang': True, 'obv': False},
    {'name': '回踩+缩量+阳线', 'macd': False, 'shrink': True, 'shrink_ratio': 0.8, 'yang': True, 'obv': False},
    {'name': '回踩+OBV多头', 'macd': False, 'shrink': False, 'yang': False, 'obv': True},
]

# 缩量阈值备选
SHRINK_RATIOS = [0.6, 0.7, 0.8, 0.9]

# ============ 指标计算 ============
def calc_ma(df, period):
    return df['close'].rolling(period).mean()

def calc_ema(df, period):
    return df['close'].ewm(span=period, adjust=False).mean()

def calc_macd(df):
    ema12 = calc_ema(df, 12); ema26 = calc_ema(df, 26)
    diff = ema12 - ema26; dea = diff.ewm(span=9, adjust=False).mean()
    return diff, dea, 2 * (diff - dea)

def calc_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high-low, abs(high-prev_close), abs(low-prev_close)], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_obv(df):
    obv = [0]
    for i in range(1, len(df)):
        if df['close'].iloc[i] > df['close'].iloc[i-1]: obv.append(obv[-1] + df['vol'].iloc[i])
        elif df['close'].iloc[i] < df['close'].iloc[i-1]: obv.append(obv[-1] - df['vol'].iloc[i])
        else: obv.append(obv[-1])
    return pd.Series(obv, index=df.index)

def is_pullback_to_ma(df, i, ma_period):
    """回踩判定：前日收盘>MA，当日最低触及MA±1.5%，收盘>MA"""
    if i < ma_period + 5: return False
    ma_val = df['ma'].iloc[i]; low = df['low'].iloc[i]; close = df['close'].iloc[i]
    prev_close = df['close'].iloc[i-1]; prev_ma = df['ma'].iloc[i-1]
    if prev_close <= prev_ma: return False
    if not (ma_val * 0.985 <= low <= ma_val * 1.015): return False
    if close <= ma_val: return False
    return True

# ============ 回测引擎 ============
def backtest_one(df_orig, ma_period, combo, start_date='20180101'):
    df = df_orig.copy()
    for col in ['close','open','high','low','vol']:
        df[col] = df[col].astype(float)
    
    df['ma'] = calc_ma(df, ma_period)
    df['vol_ma20'] = df['vol'].rolling(20).mean()
    df['atr14'] = calc_atr(df, 14)
    diff, dea, bar = calc_macd(df)
    df['macd_bar'] = bar
    df['obv'] = calc_obv(df); df['obv_ma20'] = df['obv'].rolling(20).mean()
    
    mask = df['trade_date'] >= start_date
    df = df[mask].reset_index(drop=True)
    if len(df) < 100: return None
    
    trades = []
    in_position = False
    entry_price = 0; entry_idx = 0; peak_price = 0
    
    for i in range(max(ma_period+10, 60), len(df)):
        if not in_position:
            if not is_pullback_to_ma(df, i, ma_period): continue
            if combo.get('macd'):
                if df['macd_bar'].iloc[i] <= 0: continue
            if combo.get('shrink'):
                ratio = combo.get('shrink_ratio', 0.8)
                if df['vol'].iloc[i] >= df['vol_ma20'].iloc[i] * ratio: continue
            if combo.get('yang'):
                if df['close'].iloc[i] <= df['open'].iloc[i]: continue
            if combo.get('obv'):
                if df['obv'].iloc[i] <= df['obv_ma20'].iloc[i]: continue
            
            entry_price = df['close'].iloc[i]; entry_idx = i; peak_price = entry_price
            in_position = True
        else:
            peak_price = max(peak_price, df['high'].iloc[i])
            stop_loss = entry_price - 2 * df['atr14'].iloc[i]
            ma60 = df['close'].rolling(60).mean().iloc[i]
            exit_signal = False; exit_price = 0; exit_reason = ''
            
            if df['low'].iloc[i] <= stop_loss:
                exit_price = stop_loss; exit_signal = True; exit_reason = '止损'
            elif df['close'].iloc[i] >= ma60 and ma60 > 0:
                exit_price = df['close'].iloc[i]; exit_signal = True; exit_reason = '止盈MA60'
            
            if exit_signal:
                pnl_pct = (exit_price / entry_price - 1) * 100
                trades.append({'pnl_pct': pnl_pct})
                in_position = False
    
    if in_position:
        exit_price = df['close'].iloc[-1]
        pnl_pct = (exit_price / entry_price - 1) * 100
        trades.append({'pnl_pct': pnl_pct})
    
    if not trades: return None
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = sum(1 for p in pnls if p > 0); n = len(trades)
    cum = np.cumsum(pnls); dd = cum - np.maximum.accumulate(cum)
    
    return {
        'n_trades': n, 'win_rate': wins/n*100, 'avg_pnl': np.mean(pnls),
        'cum_pnl': float(np.sum(pnls)), 'max_dd': float(np.min(dd)),
        'sharpe': np.mean(pnls)/np.std(pnls)*np.sqrt(n) if np.std(pnls)>0 and n>1 else 0,
        'score': wins/n*100*0.3 + np.mean(pnls)*0.3 + float(np.sum(pnls))*0.25 + (np.mean(pnls)/np.std(pnls)*np.sqrt(n) if np.std(pnls)>0 and n>1 else 0)*0.15
    }

# ============ 主流程 ============
# 只对 512100/513180/588000/510500 搜索（A股进攻候选）
TARGETS = ['512100', '513180', '588000', '510500']

print("=" * 100)
print("  逐标回踩均线参数搜索 — MA周期 + 确认条件 + 缩量阈值")
print("  回测周期: 全量历史 (2018-2026)")
print("=" * 100)

all_best = {}

for code in TARGETS:
    if code not in all_data:
        print(f"\n{code}: 无数据")
        continue
    
    df = all_data[code]
    print(f"\n{'='*100}")
    print(f"  {code} — 搜索中 ({len(MA_PERIODS)} MA周期 × {len(CONFIRM_COMBOS)} 确认组合)...")
    
    best = None; best_score = -999; all_configs = []
    
    for ma in MA_PERIODS:
        for combo in CONFIRM_COMBOS:
            # 如果组合有缩量，测试不同缩量阈值
            if combo.get('shrink'):
                for sr in SHRINK_RATIOS:
                    c = combo.copy()
                    c['shrink_ratio'] = sr
                    r = backtest_one(df, ma, c)
                    if r and r['n_trades'] >= 3:
                        r['ma'] = ma; r['combo'] = c['name']; r['shrink_ratio'] = sr
                        all_configs.append(r)
                        if r['score'] > best_score:
                            best_score = r['score']; best = r
            else:
                r = backtest_one(df, ma, combo)
                if r and r['n_trades'] >= 3:
                    r['ma'] = ma; r['combo'] = combo['name']; r['shrink_ratio'] = None
                    all_configs.append(r)
                    if r['score'] > best_score:
                        best_score = r['score']; best = r
    
    if best:
        all_best[code] = best
        print(f"  最优: MA{best['ma']} + {best['combo']}" + (f" (缩量阈值{best['shrink_ratio']})" if best['shrink_ratio'] else ""))
    
    # 输出 Top 5
    sorted_configs = sorted(all_configs, key=lambda x: x['score'], reverse=True)[:5]
    print(f"  {'排名':<4} {'MA':<4} {'确认条件':<22} {'缩量':<4} {'笔数':>4} {'胜率':>7} {'均盈亏':>8} {'累计':>9} {'回撤':>8} {'得分':>7}")
    print(f"  {'-'*90}")
    for rank, cfg in enumerate(sorted_configs, 1):
        print(f"  {rank:<4} {cfg['ma']:<4} {cfg['combo']:<22} {cfg.get('shrink_ratio','—'):<4} {cfg['n_trades']:>4} {cfg['win_rate']:>6.1f}% {cfg['avg_pnl']:>+7.2f}% {cfg['cum_pnl']:>+8.2f}% {cfg['max_dd']:>+7.2f}% {cfg['score']:>+6.2f}")

# ============ 汇总 ============
print(f"\n{'='*100}")
print("  逐标最优汇总")
print(f"{'='*100}")
print(f"{'标的':<8} {'MA':<4} {'确认条件':<24} {'缩量':<4} {'笔数':>4} {'胜率':>7} {'均盈亏':>8} {'累计':>9} {'回撤':>8} {'得分':>7}")
print("-" * 100)

total_trades_all = 0; total_pnl_all = 0
for code in TARGETS:
    if code in all_best:
        b = all_best[code]
        sr = b.get('shrink_ratio', '—')
        print(f"{code:<8} {b['ma']:<4} {b['combo']:<24} {sr:<4} {b['n_trades']:>4} {b['win_rate']:>6.1f}% {b['avg_pnl']:>+7.2f}% {b['cum_pnl']:>+8.2f}% {b['max_dd']:>+7.2f}% {b['score']:>+6.2f}")
        total_trades_all += b['n_trades']; total_pnl_all += b['cum_pnl']
    else:
        print(f"{code:<8} {'—':<4} {'无有效配置':<24} {'—':<4} {'—':>4} {'—':>7} {'—':>8} {'—':>9} {'—':>8} {'—':>7}")

print(f"\n  逐标最优合计: {total_trades_all}笔, 累计{total_pnl_all:+.2f}%")

# 对比动量跟随策略
print(f"\n  ⚔️ 对比: 现有动量跟随 V1.1 (MACD金叉+价<MA20, 动态回撤止盈)")
print(f"  FLIN: 23笔 胜率60.9% 累计+36.9% | SMIN: 34笔 胜率52.9% 累计+27.9%")
print(f"  EWY:  24笔 胜率54.2% 累计+33.9% | 588000: 17笔 胜率52.9% 累计+11.9%")

print("\n✅ 搜索完成")
