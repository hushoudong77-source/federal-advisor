#!/usr/bin/env python3
"""
📜 进攻策略参数扫描 — 513180 Spearhead Parameter Scan V1.0
扫描不同锚线+ATR乘数组合的进攻策略表现
"""

import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

TUSHARE_CODE = '513180.SH'
WINDOW_DAYS = 2
C4_THRESHOLD = 0.98
VOL_THRESHOLD = 0.8
ATR_VOL_THRESHOLD = 1.1


def fetch_data():
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = '20200101'
    pro = ts.pro_api()
    df = pro.fund_daily(ts_code=TUSHARE_CODE, start_date=start_date, end_date=end_date)
    if df is None or len(df) == 0:
        return None
    df = df.rename(columns={
        'trade_date': 'Date', 'open': 'Open', 'high': 'High',
        'low': 'Low', 'close': 'Close', 'vol': 'Volume'
    })
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date').reset_index(drop=True)
    return df


def calc_indicators(df):
    df = df.copy()
    # EMA
    df['EMA30'] = df['Close'].ewm(span=30, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA150'] = df['Close'].ewm(span=150, adjust=False).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA20_V'] = df['Volume'].rolling(window=20).mean()
    df['H20'] = df['Close'].rolling(window=20).max().shift(1)
    # MA for anchor
    for p in [10, 20, 30, 40, 60]:
        df[f'MA{p}'] = df['Close'].rolling(window=p).mean()
    
    df['prev_close'] = df['Close'].shift(1)
    df['TR'] = df.apply(
        lambda r: max(r['High'] - r['Low'],
                      abs(r['High'] - r['prev_close']) if pd.notna(r['prev_close']) else 0,
                      abs(r['Low'] - r['prev_close']) if pd.notna(r['prev_close']) else 0), axis=1
    )
    df['ATR14'] = df['TR'].rolling(window=14).mean()
    df['ATR14_MA20'] = df['ATR14'].rolling(window=20).mean()
    df['C1_raw'] = (df['EMA50'] - df['EMA150']) / df['EMA150'] * 100
    df['C2_raw'] = (df['EMA30'] - df['EMA50']) / df['EMA50'] * 100
    return df


def run_backtest(df, anchor_period, atr_mult):
    """跑进攻策略回测"""
    n = len(df)
    start_idx = max(200, anchor_period + 14)
    if start_idx >= n:
        return []
    
    trades = []
    c1, c2 = False, False
    in_attack = False
    attack_entry_price = 0.0
    attack_entry_date = None
    trail_stop = 0.0
    highest_since_entry = 0.0
    window_active = False
    window_end_idx = -1
    anchor_col = f'MA{anchor_period}'
    
    for i in range(start_idx, n):
        close = df.loc[i, 'Close']
        date = df.loc[i, 'Date']
        ema50 = df.loc[i, 'EMA50']
        atr14 = df.loc[i, 'ATR14']
        h20 = df.loc[i, 'H20']
        volume = df.loc[i, 'Volume']
        ma20_v = df.loc[i, 'MA20_V']
        atr14_ma20 = df.loc[i, 'ATR14_MA20']
        
        if pd.isna(atr14) or pd.isna(h20) or atr14 <= 0:
            continue
        
        c1_raw = df.loc[i, 'C1_raw']
        c2_raw = df.loc[i, 'C2_raw']
        
        # 过渡区
        if c1_raw > 0.3: c1 = True
        elif c1_raw < -0.3: c1 = False
        if c2_raw > 0.3: c2 = True
        elif c2_raw < -0.3: c2 = False
        
        c3 = close > ema50
        
        # --- 持仓状态 ---
        if in_attack:
            if close > highest_since_entry:
                highest_since_entry = close
                trail_stop = highest_since_entry - atr_mult * atr14
            
            exit_reason = None
            if close <= trail_stop:
                exit_reason = 'SRC-1追踪止损'
            
            pnl_pct = (close - attack_entry_price) / attack_entry_price
            if pnl_pct <= -0.08:
                exit_reason = 'SRC-2硬止损'
            if not c1 or not c2:
                exit_reason = 'SRC-3反转'
            if pnl_pct <= -0.15:
                exit_reason = 'SRC-6底线'
            
            if exit_reason:
                hold_days = (date - attack_entry_date).days
                trades.append({
                    'entry_date': attack_entry_date, 'entry_price': attack_entry_price,
                    'exit_date': date, 'exit_price': close,
                    'pnl_pct': pnl_pct * 100, 'hold_days': hold_days, 'exit_reason': exit_reason
                })
                in_attack = False
                window_active = False
            continue
        
        # --- 非持仓：检查信号 ---
        if not (c1 and c2 and c3):
            if window_active:
                window_active = False
            continue
        
        if i > 0 and abs(close - df.loc[i-1, 'Close'])/df.loc[i-1, 'Close'] > 0.30:
            if window_active:
                window_active = False
            continue
        
        c4 = (close >= h20 * C4_THRESHOLD) and (volume > ma20_v * VOL_THRESHOLD or atr14 < atr14_ma20 * ATR_VOL_THRESHOLD)
        
        if c4 and not window_active:
            window_active = True
            window_end_idx = i + WINDOW_DAYS
        
        if window_active and i <= window_end_idx and not in_attack:
            if c1 and c2 and c3:
                attack_entry_price = close
                attack_entry_date = date
                highest_since_entry = close
                trail_stop = close - atr_mult * atr14
                in_attack = True
                window_active = False
    
    return trades


def calc_metrics(trades):
    if len(trades) == 0:
        return {'total_trades': 0, 'win_rate': 0, 'total_pnl': 0, 'cagr': 0, 'max_dd': 0, 'expectancy': 0}
    
    total_pnl = sum(t['pnl_pct'] for t in trades)
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    wr = len(wins)/len(trades)*100 if len(trades) > 0 else 0
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
    expectancy = (wr/100*avg_win) + ((1-wr/100)*avg_loss)
    
    equity = 100
    peak = 100
    max_dd = 0
    for t in trades:
        equity *= (1 + t['pnl_pct']/100)
        if equity > peak: peak = equity
        dd = (peak - equity)/peak*100
        max_dd = max(max_dd, dd)
    
    years = 5.0
    cagr = (equity/100)**(1/years)-1 if years > 0 else 0
    
    return {
        'total_trades': len(trades),
        'win_rate': round(wr, 1),
        'total_pnl': round(total_pnl, 2),
        'cagr': round(cagr*100, 2),
        'max_dd': round(max_dd, 2),
        'expectancy': round(expectancy, 2),
        'avg_hold': round(np.mean([t['hold_days'] for t in trades]), 1) if trades else 0,
    }


def main():
    print(f"🔄 获取数据...")
    df = fetch_data()
    if df is None or len(df) < 200:
        print("❌ 数据不足")
        return
    print(f"✅ {len(df)}行 ({df['Date'].min().strftime('%Y-%m-%d')} ~ {df['Date'].max().strftime('%Y-%m-%d')})")
    
    df = calc_indicators(df)
    
    # 扫描参数空间
    anchors = [20, 30, 40, 60]
    atr_mults = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    
    print(f"\n{'='*90}")
    print(f"  513180 进攻策略参数扫描")
    print(f"{'='*90}")
    print(f"  {'锚线':<8} {'ATR×':<8} {'笔数':<6} {'胜率%':<8} {'总收益%':<10} {'CAGR%':<8} {'最大回撤%':<10} {'期望值':<8} {'均持仓天':<8}")
    print(f"  {'─'*80}")
    
    results = []
    for anc in anchors:
        for atr in atr_mults:
            trades = run_backtest(df, anc, atr)
            m = calc_metrics(trades)
            results.append((anc, atr, m))
            
            # 着色：正CAGR绿色标记
            cagr_str = f"{m['cagr']:>+6.2f}"
            print(f"  MA{anc:<4} {atr:<6.1f}× {m['total_trades']:<6} {m['win_rate']:<8} {m['total_pnl']:>+8.2f} {cagr_str:<8} {m['max_dd']:<10} {m['expectancy']:<8} {m['avg_hold']:<8}")
    
    # 最佳组合（按总收益排序）
    best = sorted(results, key=lambda x: -x[2]['total_pnl'])
    print(f"\n{'='*90}")
    print(f"  🏆 最佳组合 Top 5")
    print(f"{'='*90}")
    for i, (anc, atr, m) in enumerate(best[:5]):
        print(f"  #{i+1}: MA{anc} × {atr}× | {m['total_trades']}笔 | 胜率{m['win_rate']}% | "
              f"总收益{m['total_pnl']:>+7.2f}% | CAGR{m['cagr']}% | 回撤{m['max_dd']}% | 期望{m['expectancy']}")
    
    # 最佳组合详情
    if best:
        best_anc, best_atr, best_m = best[0]
        print(f"\n{'='*90}")
        print(f"  📋 最佳组合详情: MA{best_anc} × {best_atr}×")
        print(f"{'='*90}")
        trades = run_backtest(df, best_anc, best_atr)
        print(f"  {f'入场日期':<12} {f'入场价':<8} {f'出场日期':<12} {f'出场价':<8} {f'盈亏%':<8} {f'持仓天':<6} {f'原因':<20}")
        print(f"  {'─'*70}")
        for t in trades[-15:]:
            print(f"  {t['entry_date'].strftime('%Y-%m-%d'):<12} {t['entry_price']:<8.4f} "
                  f"{t['exit_date'].strftime('%Y-%m-%d'):<12} {t['exit_price']:<8.4f} "
                  f"{t['pnl_pct']:>+7.2f}% {t['hold_days']:<6} {t['exit_reason'][:20]}")
        
        # 离场原因
        reasons = {}
        for t in trades:
            r = t['exit_reason']
            if r not in reasons: reasons[r] = {'count': 0, 'wins': 0, 'total_pnl': 0}
            reasons[r]['count'] += 1
            reasons[r]['total_pnl'] += t['pnl_pct']
            if t['pnl_pct'] > 0: reasons[r]['wins'] += 1
        print(f"\n  离场原因:")
        for r, v in sorted(reasons.items(), key=lambda x: -x[1]['count']):
            print(f"    {r}: {v['count']}笔 | 胜率{v['wins']/v['count']*100:.0f}% | 总收益{v['total_pnl']:+.1f}%")


if __name__ == '__main__':
    main()
