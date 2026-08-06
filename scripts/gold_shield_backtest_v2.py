#!/usr/bin/env python3
"""
金盾总纲 V1.4 全量回测脚本 V2
修复S4减仓逻辑 + 输出格式化
"""
import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, '/home/agent/cow')
from tickflow import TickFlow

tf = TickFlow()

def tf_to_df(data):
    df = pd.DataFrame({
        'timestamp': pd.to_datetime(data['timestamp'], unit='ms', utc=True),
        'open': data['open'], 'high': data['high'], 'low': data['low'],
        'close': data['close'], 'volume': data['volume'],
    })
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    return df

def calc_ma(series, n):
    return series.rolling(window=n).mean()

def calc_atr(df, n=14):
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(window=n).mean()

def get_dxy_data():
    try:
        data = tf.klines.get('UUP.US', period='1d', count=3000)
        return tf_to_df(data)['close']
    except:
        return None

def get_us10y_proxy():
    try:
        data = tf.klines.get('TLT.US', period='1d', count=3000)
        return tf_to_df(data)['close']
    except:
        return None

def backtest(ticker, c4_threshold, use_c1_weight=True, c3_vol_mult=1.2, verbose=True):
    """金盾V1.4全量回测"""
    
    data = tf.klines.get(ticker, period='1d', count=3000)
    df = tf_to_df(data)
    
    atr = calc_atr(df, 14)
    df['ma60'] = calc_ma(df['close'], 60)
    df['h15'] = df['high'].rolling(15).max()
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    
    dxy_close = get_dxy_data()
    tlt_close = get_us10y_proxy()
    dxy_ma20 = calc_ma(dxy_close, 20) if dxy_close is not None else None
    tlt_ma20 = calc_ma(tlt_close, 20) if tlt_close is not None else None
    
    # 状态机
    position = 0          # 0=空仓, 1=满仓, 2=S4减仓后半仓
    entry_price = 0
    entry_date = None
    peak_price = 0
    half_exit_price = 0   # S4减仓时的价格（用于半仓盈亏计算）
    trades = []
    
    start_i = 150
    
    for i in range(start_i, len(df)):
        idx = df.index[i]
        close = df['close'].iloc[i]
        
        # === 判定C1-C4 ===
        c1 = c2 = c3 = c4 = False
        weight = 0
        
        # C1
        if dxy_ma20 is not None and tlt_ma20 is not None:
            dxy_i = dxy_ma20.index.get_loc(idx) if idx in dxy_ma20.index else None
            tlt_i = tlt_ma20.index.get_loc(idx) if idx in tlt_ma20.index else None
            if dxy_i is not None and dxy_i >= 20 and tlt_i is not None and tlt_i >= 20:
                dxy_down = dxy_ma20.iloc[dxy_i] < dxy_ma20.iloc[dxy_i - 1]
                us10y_down = tlt_ma20.iloc[tlt_i] > tlt_ma20.iloc[tlt_i - 1]  # TLT涨=收益率跌
                c1 = dxy_down or us10y_down
                if dxy_down and us10y_down:
                    weight = 1.0
                elif dxy_down or us10y_down:
                    weight = 0.5
        
        # C2
        if i >= 61:
            ma60 = df['close'].iloc[i-60:i].mean()
            ma60_prev = df['close'].iloc[i-61:i-1].mean()
            c2 = ma60 > ma60_prev
        
        # C3
        if i >= 20:
            h15 = df['high'].iloc[i-15:i].max()
            vol_ma20 = df['volume'].iloc[i-20:i].mean()
            c3 = (close >= h15) and (df['volume'].iloc[i] >= vol_ma20 * c3_vol_mult)
        
        # C4
        if i >= 15:
            c4 = atr.iloc[i] / close < c4_threshold
        
        # === 判定S1-S6 ===
        s1 = s2 = s3 = s4 = s6 = False
        
        # S1: MA60↓
        if i >= 61:
            ma60 = df['close'].iloc[i-60:i].mean()
            ma60_prev = df['close'].iloc[i-61:i-1].mean()
            s1 = ma60 < ma60_prev
        
        # S2: 假突破（收盘<H15突破日最低，简化：用入场日最低）
        if position > 0 and entry_date in df.index:
            s2 = close < df.loc[entry_date, 'low']
        
        # S3: 双逆风
        if dxy_ma20 is not None and tlt_ma20 is not None:
            dxy_i = dxy_ma20.index.get_loc(idx) if idx in dxy_ma20.index else None
            tlt_i = tlt_ma20.index.get_loc(idx) if idx in tlt_ma20.index else None
            if dxy_i is not None and dxy_i >= 1 and tlt_i is not None and tlt_i >= 1:
                dxy_up = dxy_ma20.iloc[dxy_i] > dxy_ma20.iloc[dxy_i - 1]
                us10y_up = tlt_ma20.iloc[tlt_i] < tlt_ma20.iloc[tlt_i - 1]  # TLT跌=收益率升
                s3 = dxy_up and us10y_up
        
        # S4: 波动率异常
        if i >= 15:
            s4 = atr.iloc[i] / close > 0.035
        
        # S6: 追踪止盈
        if position > 0 and i >= 15:
            s6 = close < (peak_price - 3 * atr.iloc[i])
        
        # === 状态转换 ===
        if position == 0:
            # 空仓 → 检查入场
            c1_pass = (weight >= 0.5) if use_c1_weight else c1
            if c1_pass and c2 and c3 and c4:
                position = 1
                entry_price = close
                entry_date = idx
                peak_price = close
        
        elif position == 1:
            # 满仓持有 → 检查出场
            if close > peak_price:
                peak_price = close
            
            # 优先级: S1/S3 > S2 > S6 > S4
            if s1:
                pnl = (close - entry_price) / entry_price
                trades.append({'entry': entry_date, 'exit': idx, 'entry_px': entry_price,
                               'exit_px': close, 'pnl': pnl, 'reason': 'S1(MA60↓)', 'peak': peak_price})
                position = 0
            elif s3:
                pnl = (close - entry_price) / entry_price
                trades.append({'entry': entry_date, 'exit': idx, 'entry_px': entry_price,
                               'exit_px': close, 'pnl': pnl, 'reason': 'S3(双逆风)', 'peak': peak_price})
                position = 0
            elif s2:
                pnl = (close - entry_price) / entry_price
                trades.append({'entry': entry_date, 'exit': idx, 'entry_px': entry_price,
                               'exit_px': close, 'pnl': pnl, 'reason': 'S2(假突破)', 'peak': peak_price})
                position = 0
            elif s6:
                pnl = (close - entry_price) / entry_price
                trades.append({'entry': entry_date, 'exit': idx, 'entry_px': entry_price,
                               'exit_px': close, 'pnl': pnl, 'reason': f'S6(peak={peak_price:.2f})', 'peak': peak_price})
                position = 0
            elif s4:
                pnl_pct = (close - entry_price) / entry_price
                if pnl_pct > 0.05:
                    # 浮盈>5% → 清仓
                    trades.append({'entry': entry_date, 'exit': idx, 'entry_px': entry_price,
                                   'exit_px': close, 'pnl': pnl_pct, 'reason': 'S4(浮盈>5%清仓)', 'peak': peak_price})
                    position = 0
                else:
                    # 减仓50%，剩余半仓继续
                    half_exit_price = close
                    half_pnl = pnl_pct * 0.5
                    trades.append({'entry': entry_date, 'exit': idx, 'entry_px': entry_price,
                                   'exit_px': close, 'pnl': half_pnl, 'reason': 'S4(减仓50%)', 'peak': peak_price, 'half': True})
                    position = 2  # 转入半仓状态
        
        elif position == 2:
            # 半仓持有 → 检查剩余半仓出场
            if close > peak_price:
                peak_price = close
            
            if s1:
                remaining_pnl = (close - half_exit_price) / half_exit_price * 0.5
                trades.append({'entry': entry_date, 'exit': idx, 'entry_px': half_exit_price,
                               'exit_px': close, 'pnl': remaining_pnl, 'reason': 'S1(MA60↓,剩余半仓)', 'peak': peak_price})
                position = 0
            elif s3:
                remaining_pnl = (close - half_exit_price) / half_exit_price * 0.5
                trades.append({'entry': entry_date, 'exit': idx, 'entry_px': half_exit_price,
                               'exit_px': close, 'pnl': remaining_pnl, 'reason': 'S3(双逆风,剩余半仓)', 'peak': peak_price})
                position = 0
            elif s6:
                remaining_pnl = (close - half_exit_price) / half_exit_price * 0.5
                trades.append({'entry': entry_date, 'exit': idx, 'entry_px': half_exit_price,
                               'exit_px': close, 'pnl': remaining_pnl, 'reason': f'S6(peak={peak_price:.2f},剩余半仓)', 'peak': peak_price})
                position = 0
            elif s4:
                # 第二次S4 → 清仓剩余
                remaining_pnl = (close - half_exit_price) / half_exit_price * 0.5
                trades.append({'entry': entry_date, 'exit': idx, 'entry_px': half_exit_price,
                               'exit_px': close, 'pnl': remaining_pnl, 'reason': 'S4(二次触发,清仓)', 'peak': peak_price})
                position = 0
    
    # 持仓到期
    if position > 0:
        last_close = df['close'].iloc[-1]
        if position == 1:
            pnl = (last_close - entry_price) / entry_price
            trades.append({'entry': entry_date, 'exit': df.index[-1], 'entry_px': entry_price,
                           'exit_px': last_close, 'pnl': pnl, 'reason': '持仓中(满仓)', 'peak': peak_price})
        else:
            pnl = (last_close - half_exit_price) / half_exit_price * 0.5
            trades.append({'entry': entry_date, 'exit': df.index[-1], 'entry_px': half_exit_price,
                           'exit_px': last_close, 'pnl': pnl, 'reason': '持仓中(半仓)', 'peak': peak_price})
    
    # === 输出 ===
    if not trades:
        if verbose:
            print(f"\n⚠️ {ticker}: 零笔交易触发")
        return None
    
    pnl_list = [t['pnl'] for t in trades]
    cumulative = sum(pnl_list)
    compound = np.prod([1 + p for p in pnl_list])
    compound = (compound - 1)
    
    wins = sum(1 for p in pnl_list if p > 0)
    losses = sum(1 for p in pnl_list if p < 0)
    win_rate = wins / len(trades) * 100
    avg_win = np.mean([p for p in pnl_list if p > 0]) if wins > 0 else 0
    avg_loss = np.mean([p for p in pnl_list if p < 0]) if losses > 0 else 0
    avg_pnl = np.mean(pnl_list)
    
    # Sharpe (annualized approximation)
    sharpe = np.mean(pnl_list) / np.std(pnl_list) * np.sqrt(len(pnl_list)) if len(pnl_list) > 1 and np.std(pnl_list) > 0 else 0
    
    # 最大连续亏损
    max_consec = consec = 0
    for p in pnl_list:
        if p < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    
    # 最大回撤
    cum_eq = np.cumprod([1 + p for p in pnl_list])
    max_dd = 0; peak_val = 1
    for v in cum_eq:
        peak_val = max(peak_val, v)
        max_dd = max(max_dd, (peak_val - v) / peak_val)
    
    # 盈亏比
    gross_profit = sum(p for p in pnl_list if p > 0)
    gross_loss = abs(sum(p for p in pnl_list if p < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"金盾 V1.4: {ticker} (C4<{c4_threshold*100}%, C3vol≥{c3_vol_mult}×)")
        print(f"数据: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')} ({len(df)-start_i}天)")
        print(f"{'='*60}")
        
        print(f"\n{'─'*90}")
        print(f"{'#':>3} {'入场':>10} {'出场':>10} {'入场价':>8} {'出场价':>8} {'盈亏%':>8} {'理由':<30}")
        print(f"{'─'*90}")
        for j, t in enumerate(trades):
            print(f"{j+1:>3} {t['entry'].strftime('%Y-%m-%d'):>10} {t['exit'].strftime('%Y-%m-%d'):>10} "
                  f"{t['entry_px']:>8.2f} {t['exit_px']:>8.2f} {t['pnl']*100:>+7.2f}% {t['reason']:<30}")
        print(f"{'─'*90}")
        
        print(f"\n📊 绩效:")
        print(f"  交易笔数: {len(trades)} | 胜率: {win_rate:.1f}% | 平均盈亏: {avg_pnl*100:+.2f}%")
        print(f"  累计(算术): {cumulative*100:+.2f}% | 累计(复合): {compound*100:+.2f}%")
        print(f"  Sharpe: {sharpe:.3f} | 最大回撤: {max_dd*100:.1f}% | 最大连亏: {max_consec}笔")
        print(f"  平均盈利: {avg_win*100:+.2f}% | 平均亏损: {avg_loss*100:+.2f}% | 盈亏比: {pf:.2f}")
        
        # 按出场理由统计
        from collections import Counter
        reason_counts = Counter(t['reason'].split('(')[0] for t in trades)
        print(f"\n📊 出场理由分布:")
        for r, c in reason_counts.most_common():
            r_trades = [t for t in trades if t['reason'].startswith(r)]
            r_pnl = sum(t['pnl'] for t in r_trades)
            r_wr = sum(1 for t in r_trades if t['pnl'] > 0) / len(r_trades) * 100
            print(f"  {r:<15} {c:>3}笔  累计{r_pnl*100:>+7.2f}%  胜率{r_wr:>5.1f}%")
    
    return {
        'ticker': ticker,
        'trades': trades,
        'cumulative': cumulative,
        'compound': compound,
        'sharpe': sharpe,
        'win_rate': win_rate,
        'max_dd': max_dd,
        'max_consec': max_consec,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'avg_pnl': avg_pnl,
        'pf': pf,
        'pnl_list': pnl_list,
    }


# ===================== 执行 =====================
print("=" * 60)
print("金盾总纲 V1.4 全量回测 V2")
print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# 1. IAU 标准参数 (C3 vol≥1.2×, C4<2.0%)
r1 = backtest('IAU.US', 0.02, True, 1.2)

# 2. 518880 放宽C3 (vol≥1.0×, C4<2.5%)  
r2 = backtest('518880.SH', 0.025, False, 1.0)

# 3. 518880 C3 vol≥0.8× (最宽)
r3 = backtest('518880.SH', 0.025, False, 0.8)

# === 对比总结 ===
print(f"\n{'='*70}")
print(f"金盾 V1.4 对比总结")
print(f"{'='*70}")

results = []
if r1: results.append(('IAU (vol≥1.2×)', r1))
if r2: results.append(('518880 (vol≥1.0×)', r2))
if r3: results.append(('518880 (vol≥0.8×)', r3))

for label, r in results:
    print(f"\n{'─'*50}")
    print(f"  {label}")
    print(f"  交易: {len(r['trades'])}笔 | 胜率: {r['win_rate']:.1f}% | 复合收益: {r['compound']*100:+.2f}%")
    print(f"  Sharpe: {r['sharpe']:.3f} | 最大回撤: {r['max_dd']*100:.1f}% | 盈亏比: {r['pf']:.2f}")
    print(f"  平均盈亏: {r['avg_pnl']*100:+.2f}% | 平均盈利: {r['avg_win']*100:+.2f}% | 平均亏损: {r['avg_loss']*100:+.2f}%")

# 按年份统计IAU
if r1:
    print(f"\n{'─'*70}")
    print(f"IAU 按年份绩效")
    print(f"{'─'*70}")
    print(f"{'年份':>6} {'笔数':>4} {'胜率':>7} {'累计':>8} {'说明':>20}")
    
    df_t = pd.DataFrame(r1['trades'])
    df_t['year'] = df_t['entry'].apply(lambda x: x.year)
    for yr in sorted(df_t['year'].unique()):
        yr_t = df_t[df_t['year'] == yr]
        yr_wr = sum(1 for p in yr_t['pnl'] if p > 0) / len(yr_t) * 100
        yr_pnl = yr_t['pnl'].sum() * 100
        reasons = yr_t['reason'].str.extract(r'(\w+)')[0].value_counts().to_dict()
        reason_str = ','.join(f'{k}:{v}' for k,v in sorted(reasons.items(), key=lambda x:-x[1])[:3])
        print(f"  {yr:>4} {len(yr_t):>4} {yr_wr:>6.1f}% {yr_pnl:>+7.2f}% {reason_str:<20}")
