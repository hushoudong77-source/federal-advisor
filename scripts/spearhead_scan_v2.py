#!/usr/bin/env python3
"""
📜 513180 进攻策略回测 V2 — 参数全量扫描
修正：持仓期内不移除SRC-3（保留法典原规则），但扩展参数空间
"""

import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime

TUSHARE_CODE = '513180.SH'
WINDOW_DAYS = 2
C4_THRESHOLD = 0.98
VOL_THRESHOLD = 0.8
ATR_VOL_THRESHOLD = 1.1


def fetch_data():
    end = datetime.now().strftime('%Y%m%d')
    start = '20200101'
    pro = ts.pro_api()
    df = pro.fund_daily(ts_code=TUSHARE_CODE, start_date=start, end_date=end)
    if df is None or len(df) == 0: return None
    df = df.rename(columns={'trade_date':'Date','close':'Close','high':'High','low':'Low','open':'Open','vol':'Volume'})
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date').reset_index(drop=True)
    return df


def calc_indicators(df):
    df = df.copy()
    df['EMA30'] = df['Close'].ewm(span=30, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA150'] = df['Close'].ewm(span=150, adjust=False).mean()
    df['H20'] = df['Close'].rolling(window=20).max().shift(1)
    df['MA20_V'] = df['Volume'].rolling(window=20).mean()
    df['prev_close'] = df['Close'].shift(1)
    df['TR'] = df.apply(lambda r: max(r['High']-r['Low'], abs(r['High']-r['prev_close']) if pd.notna(r['prev_close']) else 0, abs(r['Low']-r['prev_close']) if pd.notna(r['prev_close']) else 0), axis=1)
    df['ATR14'] = df['TR'].rolling(window=14).mean()
    df['ATR14_MA20'] = df['ATR14'].rolling(window=20).mean()
    df['C1_raw'] = (df['EMA50']-df['EMA150'])/df['EMA150']*100
    df['C2_raw'] = (df['EMA30']-df['EMA50'])/df['EMA50']*100
    return df


def run_backtest(df, atr_mult, remove_src3=False, c3_cushion=0.0):
    """进攻策略回测"""
    n = len(df)
    trades = []
    c1, c2 = False, False
    in_attack = False
    entry_price = 0.0
    entry_date = None
    trail_stop = 0.0
    highest = 0.0
    window_active = False
    window_end = -1
    
    for i in range(200, n):
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
        
        # 过渡区
        cr1, cr2 = df.loc[i, 'C1_raw'], df.loc[i, 'C2_raw']
        if cr1 > 0.3: c1 = True
        elif cr1 < -0.3: c1 = False
        if cr2 > 0.3: c2 = True
        elif cr2 < -0.3: c2 = False
        
        c3 = close > ema50 * (1 - c3_cushion)  # C3容差（r27.4回退至0）
        
        # --- 持仓 ---
        if in_attack:
            if close > highest:
                highest = close
                trail_stop = highest - atr_mult * atr14
            
            reason = None
            if close <= trail_stop:
                reason = 'SRC-1追踪止损'
            pnl = (close - entry_price) / entry_price
            if pnl <= -0.08:
                reason = 'SRC-2硬止损(-8%)'
            if not remove_src3 and (not c1 or not c2):
                reason = 'SRC-3反转'
            if pnl <= -0.15:
                reason = 'SRC-6底线(-15%)'
            
            if reason:
                trades.append({
                    'entry': entry_date, 'entry_p': entry_price,
                    'exit': date, 'exit_p': close,
                    'pnl': round(pnl*100,2), 'hold': (date-entry_date).days,
                    'reason': reason
                })
                in_attack = False
                window_active = False
            continue
        
        # --- 非持仓 ---
        if not (c1 and c2 and c3):
            if window_active:
                window_active = False
            continue
        
        if i > 0 and abs(close-df.loc[i-1,'Close'])/df.loc[i-1,'Close'] > 0.30:
            if window_active: window_active = False
            continue
        
        c4 = (close >= h20*C4_THRESHOLD) and (volume > ma20_v*VOL_THRESHOLD or atr14 < atr14_ma20*ATR_VOL_THRESHOLD)
        
        if c4 and not window_active:
            window_active = True
            window_end = i + WINDOW_DAYS
        
        if window_active and i <= window_end and not in_attack:
            if c1 and c2 and c3:
                entry_price = close
                entry_date = date
                highest = close
                trail_stop = close - atr_mult * atr14
                in_attack = True
                window_active = False
    
    return trades


def calc_metrics(trades):
    if len(trades) == 0:
        return {'n':0,'wr':0,'pnl':0,'cagr':0,'dd':0,'exp':0,'avg_hold':0}
    pnls = [t['pnl'] for t in trades]
    wins = [t for t in trades if t['pnl']>0]
    losses = [t for t in trades if t['pnl']<=0]
    wr = len(wins)/len(trades)*100
    eq = 100.0
    peak = 100.0
    mdd = 0
    for p in pnls:
        eq *= (1+p/100)
        if eq > peak: peak = eq
        dd = (peak-eq)/peak*100
        mdd = max(mdd, dd)
    years = 5.0
    cagr = (eq/100)**(1/years)-1 if years>0 else 0
    avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl'] for t in losses]) if losses else 0
    exp = (wr/100*avg_win)+((1-wr/100)*avg_loss)
    return {
        'n': len(trades), 'wr': round(wr,1), 'pnl': round(sum(pnls),2),
        'cagr': round(cagr*100,2), 'dd': round(mdd,2), 'exp': round(exp,2),
        'avg_hold': round(np.mean([t['hold'] for t in trades]),1)
    }


def main():
    df = fetch_data()
    if df is None: return
    print(f"✅ {len(df)}行")
    df = calc_indicators(df)
    
    print(f"\n{'='*100}")
    print(f"  513180 进攻策略参数扫描 V2")
    print(f"  {'SRC-3保留(法典标准)':^30} | {'SRC-3移除(实验)':^30}")
    print(f"{'='*100}")
    print(f"  {'ATR×':<6} {'笔数':<5} {'胜率%':<6} {'收益%':<8} {'CAGR%':<8} {'回撤%':<8} {'期望':<7} | {'笔数':<5} {'胜率%':<6} {'收益%':<8} {'CAGR%':<8} {'回撤%':<8} {'期望':<7}")
    print(f"  {'─'*98}")
    
    for atr in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0]:
        t1 = run_backtest(df, atr, remove_src3=False)
        t2 = run_backtest(df, atr, remove_src3=True)
        m1 = calc_metrics(t1)
        m2 = calc_metrics(t2)
        print(f"  {atr:<5.1f}× {m1['n']:<5} {m1['wr']:<6} {m1['pnl']:>+7.2f} {m1['cagr']:>+6.2f} {m1['dd']:<8} {m1['exp']:<7} | {m2['n']:<5} {m2['wr']:<6} {m2['pnl']:>+7.2f} {m2['cagr']:>+6.2f} {m2['dd']:<8} {m2['exp']:<7}")
    
    # 最佳组合详情
    print(f"\n{'='*100}")
    print(f"  🏆 最佳组合详情")
    
    best_atr = 2.0
    best_trades = run_backtest(df, best_atr, remove_src3=False)
    best_m = calc_metrics(best_trades)
    
    print(f"  ATR {best_atr}× | SRC-3保留: {best_m['n']}笔 | 胜率{best_m['wr']}% | 总收益{best_m['pnl']:>+7.2f}% | CAGR {best_m['cagr']}% | 回撤{best_m['dd']}%")
    print(f"\n  {'入场日期':<12} {'入场价':<8} {'出场日期':<12} {'出场价':<8} {'盈亏%':<8} {'持仓天':<6} {'原因':<20}")
    print(f"  {'─'*70}")
    for t in best_trades:
        print(f"  {t['entry'].strftime('%Y-%m-%d'):<12} {t['entry_p']:<8.4f} {t['exit'].strftime('%Y-%m-%d'):<12} {t['exit_p']:<8.4f} {t['pnl']:>+7.2f}% {t['hold']:<6} {t['reason'][:20]}")
    
    # 尝试移除SRC-3的最佳
    best2 = run_backtest(df, 2.0, remove_src3=True)
    m2 = calc_metrics(best2)
    print(f"\n  ATR 2.0× | SRC-3移除(实验): {m2['n']}笔 | 胜率{m2['wr']}% | 总收益{m2['pnl']:>+7.2f}% | CAGR {m2['cagr']}% | 回撤{m2['dd']}%")


if __name__ == '__main__':
    main()
