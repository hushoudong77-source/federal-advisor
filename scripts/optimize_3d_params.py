#!/usr/bin/env python3
"""
🔬 588000 二维参数优化 — Layer 2 单维度敏感度扫描（去掉量能）
签发：r28.4 优化流程
目标：找到乖离/RSI的最优阈值区间（量能维度已确认无区分度，剔除）
"""

import tushare as ts
import pandas as pd
import numpy as np
import sys
from datetime import datetime, timedelta

TICKER = '588000'
TUSHARE_CODE = '588000.SH'
ANCHOR = 30
K = 4.0
HOLD_DAYS = 15
COOLDOWN = 10
STOP_MULT = 2.0
YEARS = 3

def fetch_and_calc():
    pro = ts.pro_api()
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=YEARS*365 + 200)).strftime('%Y%m%d')
    
    df = pro.fund_daily(ts_code=TUSHARE_CODE, start_date=start_date, end_date=end_date)
    if df is None or len(df) == 0:
        print("❌ Tushare fund_daily returned empty")
        sys.exit(1)
    
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['Date'] = pd.to_datetime(df['trade_date'])
    df = df.rename(columns={'close': 'Close', 'vol': 'Volume'})
    df['Close'] = df['Close'].astype(float)
    df['Volume'] = df['Volume'].astype(float)
    
    df['MA30'] = df['Close'].rolling(ANCHOR).mean()
    
    df['H'] = df['Close'].rolling(2).max()
    df['L'] = df['Close'].rolling(2).min()
    df['TR'] = np.maximum(
        df['H'] - df['L'],
        np.maximum(
            (df['H'] - df['Close'].shift(1)).abs(),
            (df['L'] - df['Close'].shift(1)).abs()
        )
    )
    df['ATR14'] = df['TR'].rolling(14).mean()
    
    df['DeviationMA30'] = (df['Close'] - df['MA30']) / df['MA30'] * 100
    
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df['RSI14'] = 100 - (100 / (1 + rs))
    
    df = df.dropna().reset_index(drop=True)
    return df


def identify_signals_2d(df, dev_threshold, rsi_threshold):
    """二维过滤：乖离+RSI，去掉量能"""
    signals = []
    n = len(df)
    in_zone = False
    cooling_end_idx = -1
    
    for i in range(n):
        ma_val = df.loc[i, 'MA30']
        atr_val = df.loc[i, 'ATR14']
        price = df.loc[i, 'Close']
        
        if pd.isna(ma_val) or pd.isna(atr_val) or atr_val <= 0:
            continue
        
        zone_lower = ma_val - K * atr_val
        zone_upper = ma_val
        is_in_zone = (zone_lower <= price <= zone_upper)
        
        if cooling_end_idx > 0 and i <= cooling_end_idx:
            is_in_zone = False
        
        if is_in_zone and not in_zone:
            dev = df.loc[i, 'DeviationMA30']
            rsi_val = df.loc[i, 'RSI14']
            
            if pd.isna(dev) or pd.isna(rsi_val):
                continue
            if dev >= dev_threshold:
                continue
            if rsi_val >= rsi_threshold:
                continue
            
            stop_price = zone_lower - STOP_MULT * atr_val
            
            signals.append({
                'trigger_idx': i,
                'trigger_date': df.loc[i, 'Date'],
                'entry_price': price,
                'stop_price': stop_price,
            })
            cooling_end_idx = i + COOLDOWN
            in_zone = True
        elif not is_in_zone:
            in_zone = False
    
    return signals


def calc_results(signals, df):
    n = len(df)
    for s in signals:
        i = s['trigger_idx']
        entry = s['entry_price']
        stop_price = s['stop_price']
        
        s['result'] = 'DATA_INSUFFICIENT'
        s['return_pct'] = 0.0
        
        for j in range(i + 1, min(i + HOLD_DAYS + 1, n)):
            low = df.loc[j, 'Close']
            if low <= stop_price:
                s['result'] = 'STOP'
                s['return_pct'] = (stop_price - entry) / entry * 100
                break
        
        if s['result'] == 'DATA_INSUFFICIENT':
            exit_idx = min(i + HOLD_DAYS, n - 1)
            exit_price = df.loc[exit_idx, 'Close']
            ret = (exit_price - entry) / entry * 100
            s['result'] = 'WIN' if ret >= 0 else 'LOSS'
            s['return_pct'] = ret
    
    return signals


def calc_metrics(signals):
    valid = [s for s in signals if s['result'] in ('WIN', 'LOSS', 'STOP')]
    total = len(valid)
    if total == 0:
        return None
    
    wins = len([s for s in valid if s['result'] == 'WIN'])
    losses = len([s for s in valid if s['result'] in ('LOSS', 'STOP')])
    hr = wins / total if total > 0 else 0
    
    total_win = sum([s['return_pct'] for s in valid if s['result'] == 'WIN'])
    total_loss = abs(sum([s['return_pct'] for s in valid if s['result'] in ('LOSS', 'STOP')]))
    pf = total_win / total_loss if total_loss > 0 else (float('inf') if total_win > 0 else 0.0)
    
    avg_win = np.mean([s['return_pct'] for s in valid if s['result'] == 'WIN']) if wins > 0 else 0.0
    avg_loss = np.mean([s['return_pct'] for s in valid if s['result'] in ('LOSS', 'STOP')]) if losses > 0 else 0.0
    ev = (hr * avg_win) - ((1 - hr) * abs(avg_loss))
    
    max_consec = 0
    cur = 0
    for s in valid:
        if s['result'] in ('LOSS', 'STOP'):
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0
    
    return {
        'total': total, 'wins': wins, 'losses': losses,
        'hr': hr, 'pf': pf, 'avg_win': avg_win, 'avg_loss': avg_loss,
        'ev': ev, 'max_consec': max_consec,
    }


def scan_pairwise(df, dev_vals, rsi_vals):
    n_combos = len(dev_vals) * len(rsi_vals)
    print(f"\n{'='*60}")
    print(f"  二维交叉验证 ({n_combos}组: 乖离{len(dev_vals)} × RSI{len(rsi_vals)})")
    print(f"{'='*60}")
    
    results = []
    for dev in dev_vals:
        for rsi in rsi_vals:
            signals = identify_signals_2d(df, dev, rsi)
            signals = calc_results(signals, df)
            m = calc_metrics(signals)
            
            if m:
                results.append({'dev': dev, 'rsi': rsi, **m})
                
                status = ""
                if m['total'] >= 8 and m['hr'] >= 0.55 and m['pf'] >= 1.5 and m['max_consec'] <= 4:
                    status = " ✅"
                elif m['total'] >= 5 and m['hr'] >= 0.50 and m['pf'] >= 1.0:
                    status = " 🟡"
                
                print(f"  乖离<{dev}% RSI<{rsi}  "
                      f"信号{m['total']:3d} HR={m['hr']*100:5.1f}% EV={m['ev']:+.2f}% "
                      f"PF={m['pf']:.2f} 连亏{m['max_consec']:d}{status}")
    
    return results


def judge(results, min_signals=8, min_hr=0.55, min_pf=1.5, max_consec=4):
    valid = [r for r in results if (
        r['total'] >= min_signals and r['hr'] >= min_hr and
        r['pf'] >= min_pf and r['max_consec'] <= max_consec
    )]
    valid.sort(key=lambda x: x['ev'], reverse=True)
    return valid


def main():
    print("🔬 588000 二维参数优化 — 去掉量能维度")
    print(f"   固定: MA{ANCHOR} x {K} | H={HOLD_DAYS}d | 冷却{COOLDOWN}d")
    
    df = fetch_and_calc()
    print(f"✅ 数据: {df.iloc[0]['Date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['Date'].strftime('%Y-%m-%d')} ({len(df)}天)")
    
    # 精细扫描：乖离[-3, -4, -5, -6, -7, -8] × RSI[25, 30, 35, 40, 45, 50]
    dev_vals = [-3, -4, -5, -6, -7, -8]
    rsi_vals = [25, 30, 35, 40, 45, 50]
    
    cross = scan_pairwise(df, dev_vals, rsi_vals)
    
    # 裁决
    print(f"\n{'='*60}")
    print(f"  ⚖️ 裁决: 信号>=8 + HR>=55% + PF>=1.5 + 连亏<=4")
    print(f"{'='*60}")
    
    passing = judge(cross)
    if passing:
        print(f"\n  ✅ 通过 {len(passing)} 组:")
        for i, r in enumerate(passing):
            print(f"  {i+1:2d}. 乖离<{r['dev']}% RSI<{r['rsi']}  "
                  f"信号{r['total']:3d} HR={r['hr']*100:5.1f}% EV={r['ev']:+.2f}% "
                  f"PF={r['pf']:.2f} 连亏{r['max_consec']:d}")
        
        best = passing[0]
        print(f"\n  🏆 最优: 乖离<{best['dev']}% + RSI<{best['rsi']}")
        print(f"     EV={best['ev']:+.2f}% HR={best['hr']*100:.1f}% PF={best['pf']:.2f} 信号{best['total']}笔")
    else:
        print(f"\n  ⚠️ 无组合通过全部条件。")
    
    # 放宽条件展示
    print(f"\n  🟡 放宽条件 (信号>=5 + HR>=50% + PF>=1.0):")
    relaxed = judge(cross, min_signals=5, min_hr=0.50, min_pf=1.0, max_consec=5)
    for i, r in enumerate(relaxed[:10]):
        print(f"  {i+1:2d}. 乖离<{r['dev']}% RSI<{r['rsi']}  "
              f"信号{r['total']:3d} HR={r['hr']*100:5.1f}% EV={r['ev']:+.2f}% "
              f"PF={r['pf']:.2f} 连亏{r['max_consec']:d}")
    
    # 信号数>=8的所有组合（不限制HR/PF）
    print(f"\n  🔵 仅看信号>=8的组合:")
    sig8 = [r for r in cross if r['total'] >= 8]
    sig8.sort(key=lambda x: x['ev'], reverse=True)
    for i, r in enumerate(sig8):
        print(f"  {i+1:2d}. 乖离<{r['dev']}% RSI<{r['rsi']}  "
              f"信号{r['total']:3d} HR={r['hr']*100:5.1f}% EV={r['ev']:+.2f}% "
              f"PF={r['pf']:.2f} 连亏{r['max_consec']:d}")
    
    # 当前 vs 最优
    print(f"\n{'='*60}")
    print(f"  📊 当前三维B vs 二维最优")
    print(f"{'='*60}")
    
    # 当前（含量能1.0）
    curr_sig = identify_signals_2d(df, -5.0, 35)
    curr_sig = calc_results(curr_sig, df)
    curr_m = calc_metrics(curr_sig)
    
    if curr_m:
        print(f"  当前三维B: 乖离<-5% RSI<35 (量能>1.0已剔除)")
        print(f"    信号{curr_m['total']:d} HR={curr_m['hr']*100:.1f}% EV={curr_m['ev']:+.2f}% PF={curr_m['pf']:.2f} 连亏{curr_m['max_consec']:d}")
    
    if passing:
        print(f"  最优二维: 乖离<{best['dev']}% RSI<{best['rsi']}")
        print(f"    信号{best['total']:d} HR={best['hr']*100:.1f}% EV={best['ev']:+.2f}% PF={best['pf']:.2f} 连亏{best['max_consec']:d}")
    
    # 推荐
    print(f"\n{'='*60}")
    print(f"  🎯 推荐方案")
    print(f"{'='*60}")
    
    if sig8:
        best_sig8 = sig8[0]
        print(f"  A) 信号优先: 乖离<{best_sig8['dev']}% RSI<{best_sig8['rsi']}")
        print(f"     信号{best_sig8['total']}笔 HR={best_sig8['hr']*100:.1f}% EV={best_sig8['ev']:+.2f}% PF={best_sig8['pf']:.2f}")
    
    if relaxed:
        best_relax = relaxed[0]
        if not sig8 or best_relax['ev'] > sig8[0]['ev']:
            print(f"  B) EV优先: 乖离<{best_relax['dev']}% RSI<{best_relax['rsi']}")
            print(f"     信号{best_relax['total']}笔 HR={best_relax['hr']*100:.1f}% EV={best_relax['ev']:+.2f}% PF={best_relax['pf']:.2f}")
    
    print(f"\n✅ 二维扫描完成")


if __name__ == '__main__':
    main()
