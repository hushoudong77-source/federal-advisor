#!/usr/bin/env python3
"""
金盾总纲 V1.4 全量回测脚本
覆盖：IAU.US / 518880.SH
入场：C1 ∧ C2 ∧ C3 ∧ C4 四条件AND
出场：S1/S2/S3/S4/S6 七级卖点体系
数据源：TickFlow SDK
"""
import sys
import os
import json
import math
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

sys.path.insert(0, '/home/agent/cow')
from tickflow import TickFlow

tf = TickFlow()

# ===================== 工具函数 =====================

def tf_to_df(data):
    """TickFlow dict → pandas DataFrame"""
    df = pd.DataFrame({
        'timestamp': pd.to_datetime(data['timestamp'], unit='ms', utc=True),
        'open': data['open'],
        'high': data['high'],
        'low': data['low'],
        'close': data['close'],
        'volume': data['volume'],
    })
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    return df

def calc_ma(series, n):
    return series.rolling(window=n).mean()

def calc_atr(df, n=14):
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(window=n).mean()

def calc_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    diff = ema_fast - ema_slow
    dea = diff.ewm(span=signal, adjust=False).mean()
    bar = 2 * (diff - dea)
    return diff, dea, bar

# ===================== DXY / US10Y 数据获取 =====================
def get_dxy_data():
    """获取美元指数日线（用UUP作为代理，或从TickFlow尝试DX-Y.NYB）"""
    try:
        data = tf.klines.get('UUP.US', period='1d', count=3000)
        df = tf_to_df(data)
        return df['close']
    except:
        return None

def get_us10y_data():
    """获取美债收益率（TickFlow不支持利率，用TLT作为代理——价格跌=收益率升）"""
    try:
        data = tf.klines.get('TLT.US', period='1d', count=3000)
        df = tf_to_df(data)
        # TLT价格跌 = US10Y升，用-TLT价格变化作为US10Y代理
        return df['close']
    except:
        return None

# ===================== 金盾四条件判定 =====================

def check_c1(df, idx, dxy_ma20, us10y_proxy_ma20):
    """C1: US10Y MA20↓ 或 DXY MA20↓"""
    i = df.index.get_loc(idx)
    if i < 21:
        return False, 0, 'insufficient_data'
    
    dxy_down = False
    us10y_down = False
    
    if dxy_ma20 is not None:
        dxy_idx = dxy_ma20.index.get_loc(idx) if idx in dxy_ma20.index else None
        if dxy_idx is not None and dxy_idx >= 20:
            dxy_down = dxy_ma20.iloc[dxy_idx] < dxy_ma20.iloc[dxy_idx - 1]
    
    if us10y_proxy_ma20 is not None:
        us10y_idx = us10y_proxy_ma20.index.get_loc(idx) if idx in us10y_proxy_ma20.index else None
        if us10y_idx is not None and us10y_idx >= 20:
            # TLT价格涨=收益率跌，所以TLT MA20↑ = US10Y MA20↓
            us10y_down = us10y_proxy_ma20.iloc[us10y_idx] > us10y_proxy_ma20.iloc[us10y_idx - 1]
    
    c1 = dxy_down or us10y_down
    
    # 权重
    if dxy_down and us10y_down:
        weight = 1.0
    elif (dxy_down and not us10y_down) or (not dxy_down and us10y_down):
        weight = 0.5
    else:
        weight = 0
    
    return c1, weight, f'dxy_down={dxy_down}, us10y_down={us10y_down}'

def check_c2(df, idx):
    """C2: MA60方向向上"""
    i = df.index.get_loc(idx)
    if i < 61:
        return False
    ma60 = df['close'].iloc[i-60:i].mean()
    ma60_prev = df['close'].iloc[i-61:i-1].mean()
    return ma60 > ma60_prev

def check_c3(df, idx):
    """C3: 收盘价 ≥ H15 且 成交量 ≥ MA20_VOL × 1.2"""
    i = df.index.get_loc(idx)
    if i < 20:
        return False
    h15 = df['high'].iloc[i-15:i].max()
    vol_ma20 = df['volume'].iloc[i-20:i].mean()
    close = df['close'].iloc[i]
    vol = df['volume'].iloc[i]
    return close >= h15 and vol >= vol_ma20 * 1.2

def check_c4(df, idx, atr_series, threshold):
    """C4: ATR14/收盘价 < threshold (IAU=2.0%, 518880=2.5%)"""
    i = df.index.get_loc(idx)
    if i < 15:
        return False
    atr = atr_series.iloc[i]
    close = df['close'].iloc[i]
    return atr / close < threshold

# ===================== 卖点判定 =====================

def check_s1(df, idx):
    """S1: MA60方向向下"""
    i = df.index.get_loc(idx)
    if i < 61:
        return False
    ma60 = df['close'].iloc[i-60:i].mean()
    ma60_prev = df['close'].iloc[i-61:i-1].mean()
    return ma60 < ma60_prev

def check_s3(df, idx, dxy_ma20, us10y_proxy_ma20):
    """S3: US10Y MA20日际变化≥2bp 且 DXY MA20日际变化>0（简化：用代理）"""
    # 简化版：US10Y代理方向↑ 且 DXY MA20↑
    if dxy_ma20 is None or us10y_proxy_ma20 is None:
        return False
    
    dxy_idx = dxy_ma20.index.get_loc(idx) if idx in dxy_ma20.index else None
    us10y_idx = us10y_proxy_ma20.index.get_loc(idx) if idx in us10y_proxy_ma20.index else None
    
    if dxy_idx is None or dxy_idx < 1 or us10y_idx is None or us10y_idx < 1:
        return False
    
    dxy_up = dxy_ma20.iloc[dxy_idx] > dxy_ma20.iloc[dxy_idx - 1]
    us10y_up = us10y_proxy_ma20.iloc[us10y_idx] < us10y_proxy_ma20.iloc[us10y_idx - 1]  # TLT跌=收益率升
    
    return dxy_up and us10y_up

def check_s4(df, idx, atr_series, threshold=0.035):
    """S4: ATR14/收盘价 > 3.5%"""
    i = df.index.get_loc(idx)
    if i < 15:
        return False
    return atr_series.iloc[i] / df['close'].iloc[i] > threshold

def check_s6(df, idx, atr_series, entry_price, peak_price):
    """S6: 收盘价 < (峰值 − 3×ATR14)"""
    i = df.index.get_loc(idx)
    if i < 15:
        return False
    stop = peak_price - 3 * atr_series.iloc[i]
    return df['close'].iloc[i] < stop

# ===================== 主回测逻辑 =====================

def backtest(ticker, c4_threshold, use_c1_weight=True, start_year=2015):
    """金盾V1.4全量回测"""
    print(f"\n{'='*60}")
    print(f"金盾 V1.4 回测: {ticker} (C4<{c4_threshold*100}%)")
    print(f"{'='*60}")
    
    # 拉取日线
    data = tf.klines.get(ticker, period='1d', count=3000)
    df = tf_to_df(data)
    print(f"日线: {len(df)}条, {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
    
    # 计算指标
    df['ma20'] = calc_ma(df['close'], 20)
    df['ma60'] = calc_ma(df['close'], 60)
    df['ma150'] = calc_ma(df['close'], 150)
    atr = calc_atr(df, 14)
    diff, dea, bar = calc_macd(df)
    vol_ma20 = df['volume'].rolling(20).mean()
    df['h15'] = df['high'].rolling(15).max()
    
    # 获取宏观数据
    dxy_close = get_dxy_data()
    us10y_proxy = get_us10y_data()
    
    dxy_ma20 = calc_ma(dxy_close, 20) if dxy_close is not None else None
    us10y_ma20 = calc_ma(us10y_proxy, 20) if us10y_proxy is not None else None
    
    # 状态机
    position = 0  # 0=空仓, 1=持有
    entry_price = 0
    entry_date = None
    peak_price = 0
    trades = []
    
    # 从第150条开始（MA150需要初始化）
    start_i = 150
    for i in range(start_i, len(df)):
        idx = df.index[i]
        close = df['close'].iloc[i]
        
        if position == 0:
            # 空仓 → 检查入场
            c1, weight, c1_detail = check_c1(df, idx, dxy_ma20, us10y_ma20)
            c2 = check_c2(df, idx)
            c3 = check_c3(df, idx)
            c4 = check_c4(df, idx, atr, c4_threshold)
            
            # IAU需要C1权重≥0.5，518880需要C1=True
            if use_c1_weight:
                c1_pass = weight >= 0.5
            else:
                c1_pass = c1
            
            if c1_pass and c2 and c3 and c4:
                # 入场
                position = 1
                entry_price = close
                entry_date = idx
                peak_price = close
                
        elif position == 1:
            # 持有 → 检查出场
            # 更新峰值
            if close > peak_price:
                peak_price = close
            
            s1 = check_s1(df, idx)
            s3 = check_s3(df, idx, dxy_ma20, us10y_ma20)
            s4 = check_s4(df, idx, atr, 0.035)
            s6 = check_s6(df, idx, atr, entry_price, peak_price)
            
            exit_reason = None
            exit_price = close
            
            if s1:
                exit_reason = 'S1(MA60↓)'
            elif s3:
                exit_reason = 'S3(双逆风)'
            elif s4:
                # S4: 浮盈>5%清仓，否则减仓50%
                pnl_pct = (close - entry_price) / entry_price
                if pnl_pct > 0.05:
                    exit_reason = 'S4(波动率异常,浮盈>5%清仓)'
                else:
                    exit_reason = 'S4(波动率异常,减仓50%)'
                    # 减仓50%：记录半仓出场
                    trades.append({
                        'entry_date': entry_date,
                        'exit_date': idx,
                        'entry_price': entry_price,
                        'exit_price': close,
                        'pnl_pct': pnl_pct * 0.5,  # 一半仓位
                        'reason': exit_reason,
                        'peak': peak_price,
                    })
                    # 剩余半仓继续持有
                    continue
            elif s6:
                exit_reason = f'S6(追踪止盈,peak={peak_price:.2f})'
            
            # S2假突破止损：收盘<H15突破日最低
            # 简化：检查是否收盘<H15突破日最低（以入场日最低为代理）
            entry_low = df.loc[entry_date, 'low'] if entry_date in df.index else df['low'].iloc[i]
            if not exit_reason and close < entry_low:
                exit_reason = 'S2(假突破)'
            
            if exit_reason:
                pnl_pct = (close - entry_price) / entry_price
                
                # 如果是S4减仓后的剩余半仓出场，需要特殊处理
                # 简化：直接记录全仓出场
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': idx,
                    'entry_price': entry_price,
                    'exit_price': close,
                    'pnl_pct': pnl_pct,
                    'reason': exit_reason,
                    'peak': peak_price,
                })
                position = 0
                entry_price = 0
                entry_date = None
                peak_price = 0
    
    # 如果最后还在持仓
    if position == 1:
        last_idx = df.index[-1]
        pnl_pct = (df['close'].iloc[-1] - entry_price) / entry_price
        trades.append({
            'entry_date': entry_date,
            'exit_date': last_idx,
            'entry_price': entry_price,
            'exit_price': df['close'].iloc[-1],
            'pnl_pct': pnl_pct,
            'reason': '持仓中',
            'peak': peak_price,
        })
    
    # ===================== 输出结果 =====================
    if not trades:
        print("\n⚠️ 零笔交易触发，金盾四条件从未同时满足")
        return None
    
    print(f"\n{'─'*80}")
    print(f"交易明细 ({len(trades)}笔)")
    print(f"{'─'*80}")
    print(f"{'#':>3} {'入场日':>10} {'出场日':>10} {'入场价':>8} {'出场价':>8} {'盈亏%':>8} {'峰值':>8} {'理由':>30}")
    print(f"{'─'*80}")
    
    total_pnl = 0
    wins = 0
    losses = 0
    pnl_list = []
    
    for j, t in enumerate(trades):
        pnl_list.append(t['pnl_pct'])
        total_pnl += t['pnl_pct']
        if t['pnl_pct'] > 0:
            wins += 1
        else:
            losses += 1
        
        print(f"{j+1:>3} {t['entry_date'].strftime('%Y-%m-%d'):>10} "
              f"{t['exit_date'].strftime('%Y-%m-%d'):>10} "
              f"{t['entry_price']:>8.2f} {t['exit_price']:>8.2f} "
              f"{t['pnl_pct']:>+7.2f}% {t['peak']:>8.2f} "
              f"{t['reason']:<30}")
    
    print(f"{'─'*80}")
    
    # 统计
    win_rate = wins / len(trades) * 100 if trades else 0
    avg_win = np.mean([p for p in pnl_list if p > 0]) if wins > 0 else 0
    avg_loss = np.mean([p for p in pnl_list if p < 0]) if losses > 0 else 0
    avg_pnl = np.mean(pnl_list) if pnl_list else 0
    cumulative = sum(pnl_list)
    
    # 复合收益（简化：算术累加）
    # 实际计算几何复合
    compound = 1.0
    for p in pnl_list:
        compound *= (1 + p / 100)
    compound = (compound - 1) * 100
    
    # Sharpe (近似，假设无风险利率=0)
    sharpe = np.mean(pnl_list) / np.std(pnl_list) * np.sqrt(len(pnl_list)) if len(pnl_list) > 1 and np.std(pnl_list) > 0 else 0
    
    # 最大连续亏损
    max_consecutive_loss = 0
    consecutive = 0
    for p in pnl_list:
        if p < 0:
            consecutive += 1
            max_consecutive_loss = max(max_consecutive_loss, consecutive)
        else:
            consecutive = 0
    
    # 最大回撤
    cum = np.cumprod([1 + p/100 for p in pnl_list])
    max_dd = 0
    peak_val = 1
    for v in cum:
        if v > peak_val:
            peak_val = v
        dd = (peak_val - v) / peak_val
        max_dd = max(max_dd, dd)
    
    # 盈亏比
    profit_factor = abs(sum(p for p in pnl_list if p > 0) / sum(p for p in pnl_list if p < 0)) if losses > 0 and sum(p for p in pnl_list if p < 0) != 0 else float('inf')
    
    print(f"\n📊 绩效统计:")
    print(f"{'─'*40}")
    print(f"  交易笔数:     {len(trades)}")
    print(f"  胜率:         {win_rate:.1f}%")
    print(f"  平均盈利:     {avg_win:+.2f}%")
    print(f"  平均亏损:     {avg_loss:+.2f}%")
    print(f"  平均盈亏:     {avg_pnl:+.2f}%")
    print(f"  累计收益(算术): {cumulative:+.2f}%")
    print(f"  累计收益(复合): {compound:+.2f}%")
    print(f"  Sharpe:       {sharpe:.3f}")
    print(f"  最大连续亏损: {max_consecutive_loss}笔")
    print(f"  最大回撤:     {max_dd*100:.1f}%")
    print(f"  盈亏比:       {profit_factor:.2f}")
    
    # C1-C4触发统计
    total_days = len(df) - start_i
    c1_count = 0
    c2_count = 0
    c3_count = 0
    c4_count = 0
    all_four = 0
    
    for i in range(start_i, len(df)):
        idx = df.index[i]
        c1, w, _ = check_c1(df, idx, dxy_ma20, us10y_ma20)
        c2 = check_c2(df, idx)
        c3 = check_c3(df, idx)
        c4 = check_c4(df, idx, atr, c4_threshold)
        if c1: c1_count += 1
        if c2: c2_count += 1
        if c3: c3_count += 1
        if c4: c4_count += 1
        if c1 and c2 and c3 and c4: all_four += 1
    
    print(f"\n📊 条件触发率 ({total_days}个交易日):")
    print(f"{'─'*40}")
    print(f"  C1(宏观顺风):    {c1_count:>5}天 ({c1_count/total_days*100:5.1f}%)")
    print(f"  C2(MA60↑):       {c2_count:>5}天 ({c2_count/total_days*100:5.1f}%)")
    print(f"  C3(H15突破+放量): {c3_count:>5}天 ({c3_count/total_days*100:5.1f}%)")
    print(f"  C4(波动率安全):   {c4_count:>5}天 ({c4_count/total_days*100:5.1f}%)")
    print(f"  四条件AND:        {all_four:>5}天 ({all_four/total_days*100:5.1f}%)")
    
    # 按年统计
    print(f"\n📊 按年统计:")
    print(f"{'─'*60}")
    print(f"{'年份':>6} {'笔数':>4} {'胜率':>7} {'累计盈亏':>9} {'C1触发率':>8} {'C3触发率':>8}")
    print(f"{'─'*60}")
    
    df_year = pd.DataFrame(trades)
    if len(df_year) > 0:
        df_year['year'] = df_year['entry_date'].apply(lambda x: x.year)
        for yr in sorted(df_year['year'].unique()):
            yr_trades = df_year[df_year['year'] == yr]
            yr_wins = sum(1 for p in yr_trades['pnl_pct'] if p > 0)
            yr_pnl = yr_trades['pnl_pct'].sum()
            yr_win_rate = yr_wins / len(yr_trades) * 100
            
            # 该年的C1/C3触发率
            yr_mask = (df.index >= pd.Timestamp(f'{yr}-01-01', tz='UTC')) & (df.index <= pd.Timestamp(f'{yr}-12-31', tz='UTC'))
            yr_df = df[yr_mask]
            if len(yr_df) > 150:
                yr_c1 = 0
                yr_c3 = 0
                yr_total = 0
                for ii in range(150, len(yr_df)):
                    iidx = yr_df.index[ii]
                    c1, _, _ = check_c1(df, iidx, dxy_ma20, us10y_ma20)
                    c3 = check_c3(df, iidx)
                    if c1: yr_c1 += 1
                    if c3: yr_c3 += 1
                    yr_total += 1
                yr_c1_rate = yr_c1 / yr_total * 100 if yr_total > 0 else 0
                yr_c3_rate = yr_c3 / yr_total * 100 if yr_total > 0 else 0
            else:
                yr_c1_rate = yr_c3_rate = 0
            
            print(f"  {yr:>4} {len(yr_trades):>4} {yr_win_rate:>6.1f}% {yr_pnl:>+8.2f}% {yr_c1_rate:>7.1f}% {yr_c3_rate:>7.1f}%")
    
    return {
        'ticker': ticker,
        'trades': trades,
        'compound': compound,
        'sharpe': sharpe,
        'win_rate': win_rate,
        'max_dd': max_dd,
        'all_four_days': all_four,
        'total_days': total_days,
    }


# ===================== 执行 =====================
print("=" * 60)
print("金盾总纲 V1.4 全量回测")
print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("数据源: TickFlow SDK")
print("=" * 60)

# 回测 IAU
result_iau = backtest('IAU.US', c4_threshold=0.02, use_c1_weight=True)

# 回测 518880
result_518880 = backtest('518880.SH', c4_threshold=0.025, use_c1_weight=False)

# 汇总对比
if result_iau and result_518880:
    print(f"\n{'='*60}")
    print(f"IAU vs 518880 对比")
    print(f"{'='*60}")
    print(f"{'指标':<20} {'IAU':>12} {'518880':>12}")
    print(f"{'─'*45}")
    print(f"{'交易笔数':<20} {result_iau['trades'].__len__():>12} {result_518880['trades'].__len__():>12}")
    print(f"{'胜率':<20} {result_iau['win_rate']:>11.1f}% {result_518880['win_rate']:>11.1f}%")
    print(f"{'累计收益(复合)':<20} {result_iau['compound']:>+11.2f}% {result_518880['compound']:>+11.2f}%")
    print(f"{'Sharpe':<20} {result_iau['sharpe']:>12.3f} {result_518880['sharpe']:>12.3f}")
    print(f"{'最大回撤':<20} {result_iau['max_dd']*100:>11.1f}% {result_518880['max_dd']*100:>11.1f}%")
    print(f"{'四条件触发天数':<20} {result_iau['all_four_days']:>12} {result_518880['all_four_days']:>12}")
    print(f"{'触发率':<20} {result_iau['all_four_days']/result_iau['total_days']*100:>11.1f}% {result_518880['all_four_days']/result_518880['total_days']*100:>11.1f}%")
