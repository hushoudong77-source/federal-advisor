#!/usr/bin/env python3
"""
回踩均线策略回测 — 四方案 × 四标的逐标对比
回测周期: 2025-07-07 ~ 2026-07-07 (约一年)
"""

import pickle, sys
import numpy as np
import pandas as pd

with open('/tmp/backtest_data.pkl', 'rb') as f:
    all_data = pickle.load(f)

SCHEMES = {
    'S1': {'name': '回踩MA20+MACD+缩量+RSI', 'ma': 20, 'require_macd_golden': True, 'require_volume_shrink': True, 'volume_threshold': 0.8, 'require_rsi': True, 'rsi_max': 50, 'require_yang': False, 'require_obv': False},
    'S2': {'name': '回踩MA20+OBV+缩量', 'ma': 20, 'require_macd_golden': False, 'require_volume_shrink': True, 'volume_threshold': 0.8, 'require_obv': True, 'require_yang': False},
    'S3': {'name': '回踩MA30+MACD金叉', 'ma': 30, 'require_macd_golden': True, 'require_volume_shrink': False, 'require_yang': False, 'require_obv': False},
    'S4': {'name': '回踩MA10+MACD金叉+缩量', 'ma': 10, 'require_macd_golden': True, 'require_volume_shrink': True, 'volume_threshold': 0.8, 'require_yang': False, 'require_obv': False},
}

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

def calc_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0); loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(period).mean(); avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def is_pullback_to_ma(df, i, ma_period):
    if i < ma_period + 5: return False
    ma_val = df['ma'].iloc[i]; low = df['low'].iloc[i]; close = df['close'].iloc[i]
    prev_close = df['close'].iloc[i-1]; prev_ma = df['ma'].iloc[i-1]
    if prev_close <= prev_ma: return False
    if not (ma_val * 0.99 <= low <= ma_val * 1.01): return False
    if close <= ma_val: return False
    return True

def backtest(df, scheme, start_date='20250707'):
    df = df.copy()
    for col in ['close','open','high','low','vol']:
        df[col] = df[col].astype(float)
    
    ma_period = scheme['ma']
    df['ma'] = calc_ma(df, ma_period)
    df['vol_ma20'] = df['vol'].rolling(20).mean()
    df['atr14'] = calc_atr(df, 14)
    diff, dea, bar = calc_macd(df)
    df['macd_diff'] = diff; df['macd_dea'] = dea; df['macd_bar'] = bar
    df['obv'] = calc_obv(df); df['obv_ma20'] = df['obv'].rolling(20).mean()
    df['rsi14'] = calc_rsi(df, 14)
    
    mask = df['trade_date'] >= start_date
    df = df[mask].reset_index(drop=True)
    if len(df) < 60: return None
    
    trades = []
    in_position = False
    entry_price = 0; entry_idx = 0; peak_price = 0
    
    for i in range(60, len(df)):
        if not in_position:
            if not is_pullback_to_ma(df, i, ma_period): continue
            if scheme.get('require_macd_golden'):
                if df['macd_bar'].iloc[i] <= 0 or df['macd_bar'].iloc[i-1] > 0: continue
            if scheme.get('require_volume_shrink'):
                if df['vol'].iloc[i] >= df['vol_ma20'].iloc[i] * scheme['volume_threshold']: continue
            if scheme.get('require_rsi'):
                if df['rsi14'].iloc[i] > scheme['rsi_max']: continue
            if scheme.get('require_obv'):
                if df['obv'].iloc[i] <= df['obv_ma20'].iloc[i]: continue
            if scheme.get('require_yang'):
                if df['close'].iloc[i] <= df['open'].iloc[i]: continue
            
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
                trades.append({'entry_date': df['trade_date'].iloc[entry_idx], 'exit_date': df['trade_date'].iloc[i],
                    'entry': entry_price, 'exit': exit_price, 'pnl_pct': pnl_pct, 'reason': exit_reason, 'hold_days': i - entry_idx})
                in_position = False
    
    if in_position:
        exit_price = df['close'].iloc[-1]
        pnl_pct = (exit_price / entry_price - 1) * 100
        trades.append({'entry_date': df['trade_date'].iloc[entry_idx], 'exit_date': df['trade_date'].iloc[-1],
            'entry': entry_price, 'exit': exit_price, 'pnl_pct': pnl_pct, 'reason': '强制平仓', 'hold_days': len(df)-1-entry_idx})
    
    if not trades: return {'n_trades': 0, 'win_rate': 0, 'avg_pnl': 0, 'cum_pnl': 0, 'max_dd': 0, 'sharpe': 0, 'trades': []}
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = sum(1 for p in pnls if p > 0); n = len(trades)
    cum = np.cumsum(pnls); dd = cum - np.maximum.accumulate(cum)
    
    return {'n_trades': n, 'win_rate': wins/n*100, 'avg_pnl': np.mean(pnls), 'cum_pnl': float(np.sum(pnls)),
        'max_dd': float(np.min(dd)), 'sharpe': np.mean(pnls)/np.std(pnls)*np.sqrt(n) if np.std(pnls)>0 else 0, 'trades': trades}

# ============ 主流程 ============
print("=" * 95)
print("  回踩均线策略 — 四方案 × 四标的 回测对比 (2025-07-07 ~ 2026-07-07)")
print("=" * 95)

all_results = {}
for code, df in all_data.items():
    print(f"\n{'='*95}\n  {code}\n{'='*95}")
    print(f"{'方案':<32} {'笔数':>4} {'胜率':>7} {'均盈亏':>8} {'累计':>9} {'最大回撤':>9} {'Sharpe':>7}")
    print("-" * 95)
    all_results[code] = {}
    for sid, scheme in SCHEMES.items():
        r = backtest(df, scheme)
        if r is None or r['n_trades'] == 0:
            print(f"{scheme['name']:<32} {'0':>4} {'—':>7} {'—':>8} {'—':>9} {'—':>9} {'—':>7}")
            all_results[code][sid] = None
        else:
            print(f"{scheme['name']:<32} {r['n_trades']:>4} {r['win_rate']:>6.1f}% {r['avg_pnl']:>+7.2f}% {r['cum_pnl']:>+8.2f}% {r['max_dd']:>+8.2f}% {r['sharpe']:>6.2f}")
            all_results[code][sid] = r

# 合并汇总
print(f"\n{'='*95}\n  合并汇总（四标合计）\n{'='*95}")
print(f"{'方案':<32} {'笔数':>4} {'胜率':>7} {'均盈亏':>8} {'累计':>9} {'最大回撤':>9} {'Sharpe':>7}")
print("-" * 95)
for sid, scheme in SCHEMES.items():
    total_trades = []
    for code in all_results:
        r = all_results[code].get(sid)
        if r: total_trades.extend(r['trades'])
    if total_trades:
        pnls = [t['pnl_pct'] for t in total_trades]; n = len(total_trades); wins = sum(1 for p in pnls if p>0)
        cum = np.cumsum(pnls); dd = cum - np.maximum.accumulate(cum)
        print(f"{scheme['name']:<32} {n:>4} {wins/n*100:>6.1f}% {np.mean(pnls):>+7.2f}% {np.sum(pnls):>+8.2f}% {np.min(dd):>+8.2f}% {np.mean(pnls)/np.std(pnls)*np.sqrt(n) if np.std(pnls)>0 else 0:>6.2f}")
    else:
        print(f"{scheme['name']:<32} {'0':>4} {'—':>7} {'—':>8} {'—':>9} {'—':>9} {'—':>7}")

# 逐标最优
print(f"\n{'='*95}\n  逐标最优方案\n{'='*95}")
for code in all_results:
    best_sid = None; best_score = -999
    for sid, scheme in SCHEMES.items():
        r = all_results[code].get(sid)
        if r and r['n_trades'] >= 3:
            score = r['win_rate']*0.3 + r['avg_pnl']*0.25 + r['cum_pnl']*0.25 + r['sharpe']*0.2
            if score > best_score: best_score = score; best_sid = sid
    if best_sid:
        r = all_results[code][best_sid]; scheme = SCHEMES[best_sid]
        print(f"  {code}: {scheme['name']} — {r['n_trades']}笔 胜率{r['win_rate']:.1f}% 累计{r['cum_pnl']:+.2f}% 回撤{r['max_dd']:+.2f}%")
    else:
        print(f"  {code}: ⚠️ 无有效方案（所有方案<3笔）")

print("\n✅ 回测完成")
