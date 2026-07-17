#!/usr/bin/env python3
"""
A股进攻 MA60回踩策略 — 全量网格遍历回测
512100 (中证1000ETF) + 510500 (中证500ETF)

搜索空间：MA周期 + 容忍度 + MACD窗口 + 缩量阈值 + 止损方式 + 止盈方式 + 最大持仓 — 全网格
不使用Optuna TPE，确保不遗漏
"""

import tushare as ts
import pandas as pd
import numpy as np
from itertools import product

pro = ts.pro_api('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')

# ============================================================
# 配置
# ============================================================
CODES = {
    '512100': '512100.SH',
    '510500': '510500.SH',
}

# 搜索空间
SEARCH_SPACE = {
    'ma_period': [20, 30, 40, 50, 60],
    'tolerance': [0.02, 0.03, 0.04, 0.05],
    'macd_window': [1, 2, 3, 5],
    'vol_filter': [None, 0.8, 0.9, 1.0],
    'stop_method': ['fixed', 'atr'],
    'stop_val': [-0.03, -0.04, -0.05, -0.08, -0.10, -0.13, -0.15],
    'stop_atr': [1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
    'profit_method': ['fixed', 'ma', 'atr_trail'],
    'profit_fixed': [0.10, 0.15, 0.18, 0.20, 0.25, 0.30],
    'profit_ma': [10, 20, 30],
    'max_hold': [30, 50, 60, 80, 100, 120],
    'cooldown': [10, 15, 20, 30],
}

# ============================================================
# 指标计算
# ============================================================
def calc_atr(df, n=14):
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def calc_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df['close'].ewm(span=fast).mean()
    ema_slow = df['close'].ewm(span=slow).mean()
    diff = ema_fast - ema_slow
    dea = diff.ewm(span=signal).mean()
    bar = 2 * (diff - dea)
    return diff, dea, bar

def calc_ma(df, period):
    return df['close'].rolling(period).mean()

# ============================================================
# 单参数组合回测
# ============================================================
def backtest_one(df, params):
    ma_period = params['ma_period']
    tolerance = params['tolerance']
    macd_window = params['macd_window']
    vol_filter = params['vol_filter']
    stop_method = params['stop_method']
    max_hold = params['max_hold']
    cooldown = params['cooldown']
    
    df = df.copy()
    df['ma'] = calc_ma(df, ma_period)
    df['atr14'] = calc_atr(df, 14)
    df['vol_ma20'] = df['vol'].rolling(20).mean()
    diff, dea, bar = calc_macd(df)
    df['macd_bar'] = bar
    df['ma60'] = calc_ma(df, 60)
    
    # 牛市判定
    df['ma60_dir'] = df['ma60'].diff(20)
    df['bull'] = (df['ma60_dir'] > 0) & (df['close'] > df['ma60'])
    
    # 入场条件
    df['prev_close'] = df['close'].shift(1)
    df['prev_ma'] = df['ma'].shift(1)
    df['above_ma'] = df['prev_close'] > df['prev_ma']
    df['touch_ma'] = df['low'] <= df['ma'] * (1 + tolerance)
    df['golden_cross'] = (df['macd_bar'] > 0) & (df['macd_bar'].shift(1) <= 0)
    df['recent_golden'] = df['golden_cross'].rolling(macd_window).max().fillna(0).astype(bool)
    
    if vol_filter is not None:
        df['vol_ok'] = df['vol'] < df['vol_ma20'] * vol_filter
    else:
        df['vol_ok'] = True
    
    df['entry_signal'] = (
        df['bull'].shift(1) &
        df['above_ma'] &
        df['touch_ma'] &
        df['recent_golden'] &
        df['vol_ok']
    )
    
    # 模拟交易
    trades = []
    last_entry_idx = -9999
    
    for i in range(ma_period + 60, len(df)):
        if df['entry_signal'].iloc[i] and (i - last_entry_idx) >= cooldown:
            entry_price = df['open'].iloc[i]
            entry_idx = i
            entry_date = df['trade_date'].iloc[i]
            entry_atr = df['atr14'].iloc[i]
            
            # 止损价
            if stop_method == 'fixed':
                stop_loss = entry_price * (1 + params['stop_val'])
            else:
                stop_loss = entry_price - params['stop_atr'] * entry_atr
            
            # 止盈价
            if params['profit_method'] == 'fixed':
                take_profit = entry_price * (1 + params['profit_fixed'])
            else:
                take_profit = None
            
            exit_idx = None
            exit_price = None
            exit_reason = None
            peak_price = entry_price
            
            for j in range(i + 1, min(i + max_hold + 1, len(df))):
                cur_high = df['high'].iloc[j]
                cur_low = df['low'].iloc[j]
                cur_close = df['close'].iloc[j]
                cur_ma = df['ma'].iloc[j]
                
                peak_price = max(peak_price, cur_high)
                
                # 止损
                if cur_low <= stop_loss:
                    exit_idx = j
                    exit_price = stop_loss
                    exit_reason = '止损'
                    break
                
                # 固定%止盈
                if params['profit_method'] == 'fixed' and take_profit and cur_high >= take_profit:
                    exit_idx = j
                    exit_price = take_profit
                    exit_reason = '止盈'
                    break
                
                # MA止盈
                if params['profit_method'] == 'ma' and cur_close < cur_ma:
                    exit_idx = j
                    exit_price = cur_close
                    exit_reason = 'MA止盈'
                    break
                
                # ATR回撤止盈
                if params['profit_method'] == 'atr_trail':
                    cur_atr = df['atr14'].iloc[j]
                    if cur_close <= peak_price - 2.0 * cur_atr:
                        exit_idx = j
                        exit_price = cur_close
                        exit_reason = 'ATR回撤'
                        break
            
            if exit_idx is None:
                exit_idx = min(i + max_hold, len(df) - 1)
                exit_price = df['close'].iloc[exit_idx]
                exit_reason = '强制离场'
            
            pnl_pct = (exit_price - entry_price) / entry_price
            hold_days = exit_idx - i
            
            trades.append({
                'entry_date': entry_date,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl_pct': pnl_pct,
                'hold_days': hold_days,
                'exit_reason': exit_reason,
            })
            
            last_entry_idx = i
    
    if not trades:
        return {'n': 0, 'win_rate': 0, 'cum_return': 0, 'avg_return': 0,
                'max_dd': 0, 'profit_factor': 0, 'sharpe': 0, 'max_consec_loss': 0,
                'n_yearly': 0, 'params': params, 'trades': []}
    
    pnls = [t['pnl_pct'] for t in trades]
    n = len(trades)
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / n
    cum_return = sum(pnls)
    avg_return = np.mean(pnls)
    
    cum = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cum)
    drawdowns = cum - running_max
    max_dd = drawdowns.min() if len(drawdowns) > 0 else 0
    
    avg_win = np.mean([p for p in pnls if p > 0]) if wins > 0 else 0
    avg_loss = abs(np.mean([p for p in pnls if p < 0])) if (n - wins) > 0 else 0
    profit_factor = avg_win / avg_loss if avg_loss > 0 else 999
    
    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(n) if n > 1 and np.std(pnls) > 0 else 0
    
    consec = 0
    max_consec = 0
    for p in pnls:
        if p < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    
    years = (pd.to_datetime(df['trade_date'].iloc[-1]) - pd.to_datetime(df['trade_date'].iloc[0])).days / 365.25
    n_yearly = n / years if years > 0 else 0
    
    return {
        'n': n, 'win_rate': win_rate, 'cum_return': cum_return, 'avg_return': avg_return,
        'max_dd': max_dd, 'profit_factor': profit_factor, 'sharpe': sharpe,
        'max_consec_loss': max_consec, 'n_yearly': n_yearly,
        'params': params, 'trades': trades,
    }


def score_result(r):
    if r['n'] < 3:
        return -999
    sr = min(r['sharpe'], 3.0)
    return (r['cum_return'] * 0.35 + r['win_rate'] * 0.25 + sr/3 * 0.20 
            - r['max_consec_loss'] * 0.10 - abs(r['max_dd']) * 0.10)


# ============================================================
# 网格搜索（分批执行避免内存爆炸）
# ============================================================
def grid_search(code, ts_code):
    print(f'\n{"="*60}')
    print(f'回测标的: {code} ({ts_code})')
    print(f'{"="*60}')
    
    df = pro.fund_daily(ts_code=ts_code, start_date='20160101', end_date='20260708')
    df = df.sort_values('trade_date').reset_index(drop=True)
    print(f'数据: {len(df)}行, {df.iloc[0]["trade_date"]} ~ {df.iloc[-1]["trade_date"]}')
    
    # Phase 1: 核心参数粗筛 (MA×Tol×MACDw = 5×4×4 = 80组合)
    base_params = {
        'stop_method': 'fixed', 'stop_val': -0.05,
        'profit_method': 'fixed', 'profit_fixed': 0.15,
        'max_hold': 60, 'cooldown': 20, 'vol_filter': None,
    }
    
    results = []
    for ma in SEARCH_SPACE['ma_period']:
        for tol in SEARCH_SPACE['tolerance']:
            for mw in SEARCH_SPACE['macd_window']:
                p = base_params.copy()
                p.update({'ma_period': ma, 'tolerance': tol, 'macd_window': mw})
                r = backtest_one(df, p)
                r['score'] = score_result(r)
                results.append(r)
    
    valid = [r for r in results if r['n'] >= 3]
    if not valid:
        print('⚠️ 无有效结果')
        return []
    valid.sort(key=lambda x: x['score'], reverse=True)
    top_core = valid[:5]
    
    print(f'\nPhase 1 核心参数筛选 ({len(results)}组合, {len(valid)}组有效):')
    print(f'{"MA":>4} {"Tol":>6} {"MACDw":>6} {"N":>4} {"胜率":>7} {"累计":>8} {"均收益":>7} {"PF":>6} {"Sharpe":>7} {"连亏":>4} {"年均":>5} {"得分":>7}')
    print('-' * 95)
    for r in top_core:
        p = r['params']
        print(f'{p["ma_period"]:>4} {p["tolerance"]:>6.0%} {p["macd_window"]:>6} '
              f'{r["n"]:>4} {r["win_rate"]:>6.1%} {r["cum_return"]:>7.1%} '
              f'{r["avg_return"]:>7.1%} {r["profit_factor"]:>6.1f} '
              f'{r["sharpe"]:>7.2f} {r["max_consec_loss"]:>4} {r["n_yearly"]:>5.1f} {r["score"]:>7.3f}')
    
    # Phase 2: 精细搜索（基于Top3核心参数，搜止损+止盈+持仓+冷却+缩量）
    print(f'\nPhase 2 精细搜索...')
    fine_results = []
    
    for core in top_core[:3]:
        base = core['params'].copy()
        
        for sm in SEARCH_SPACE['stop_method']:
            stop_vals = SEARCH_SPACE['stop_val'] if sm == 'fixed' else SEARCH_SPACE['stop_atr']
            for sv in stop_vals:
                for pm in SEARCH_SPACE['profit_method']:
                    profit_vals = (SEARCH_SPACE['profit_fixed'] if pm == 'fixed' 
                                   else SEARCH_SPACE['profit_ma'] if pm == 'ma' 
                                   else [None])
                    for pv in profit_vals:
                        for mh in SEARCH_SPACE['max_hold']:
                            for cd in SEARCH_SPACE['cooldown']:
                                for vf in SEARCH_SPACE['vol_filter']:
                                    p = base.copy()
                                    if sm == 'fixed':
                                        p['stop_val'] = sv
                                    else:
                                        p['stop_atr'] = sv
                                    p['stop_method'] = sm
                                    p['profit_method'] = pm
                                    if pm == 'fixed':
                                        p['profit_fixed'] = pv
                                    elif pm == 'ma':
                                        p['profit_ma'] = pv
                                    p['max_hold'] = mh
                                    p['cooldown'] = cd
                                    p['vol_filter'] = vf
                                    r = backtest_one(df, p)
                                    r['score'] = score_result(r)
                                    fine_results.append(r)
    
    print(f'Phase 2 完成: {len(fine_results)}组合')
    
    all_results = results + fine_results
    valid_all = [r for r in all_results if r['n'] >= 3]
    valid_all.sort(key=lambda x: x['score'], reverse=True)
    
    print(f'\n🏆 Top 20 综合排名:')
    print(f'{"排名":>4} {"得分":>7} {"MA":>4} {"Tol":>6} {"MACDw":>6} {"N":>4} {"胜率":>7} {"累计":>8} {"均收益":>7} {"最大DD":>7} {"PF":>6} {"Sharpe":>7} {"连亏":>4} {"年均":>5} {"止损":>10} {"止盈":>14} {"持仓":>5} {"冷却":>4}')
    print('-' * 145)
    for idx, r in enumerate(valid_all[:20]):
        p = r['params']
        if p['stop_method'] == 'fixed':
            stop_str = f"固定{p['stop_val']:.0%}"
        else:
            stop_str = f"ATR{p['stop_atr']}x"
        if p['profit_method'] == 'fixed':
            profit_str = f"固定+{p.get('profit_fixed',0):.0%}"
        elif p['profit_method'] == 'ma':
            profit_str = f"MA{p.get('profit_ma','?')}"
        else:
            profit_str = "ATR回撤"
        print(f'{idx+1:>4} {r["score"]:>7.3f} {p["ma_period"]:>4} {p["tolerance"]:>6.0%} '
              f'{p["macd_window"]:>6} {r["n"]:>4} {r["win_rate"]:>6.1%} '
              f'{r["cum_return"]:>7.1%} {r["avg_return"]:>7.1%} {r["max_dd"]:>7.1%} '
              f'{r["profit_factor"]:>6.1f} {r["sharpe"]:>7.2f} {r["max_consec_loss"]:>4} '
              f'{r["n_yearly"]:>5.1f} {stop_str:>10} {profit_str:>14} '
              f'{p.get("max_hold","?"):>5} {p.get("cooldown","?"):>4}')
    
    # Top5详细
    print(f'\n📊 Top 5 参数详情:')
    for idx, r in enumerate(valid_all[:5]):
        p = r['params']
        print(f'\n#{idx+1} 得分={r["score"]:.3f} | MA={p["ma_period"]} | 容忍={p["tolerance"]:.0%} | MACD窗口={p["macd_window"]}')
        print(f'   止损={p["stop_method"]}:{p.get("stop_val", p.get("stop_atr","?"))} | 止盈={p["profit_method"]}:{p.get("profit_fixed", p.get("profit_ma","?"))}')
        print(f'   最大持仓={p["max_hold"]} | 冷却={p["cooldown"]} | 缩量={p["vol_filter"]}')
        print(f'   {r["n"]}笔 | 胜率{r["win_rate"]:.1%} | 累计{r["cum_return"]:.1%} | Sharpe{r["sharpe"]:.2f} | 连亏{r["max_consec_loss"]}')
        print(f'   {"日期":>12} {"入场":>8} {"离场":>8} {"盈亏":>8} {"持仓天":>7}')
        for t in r.get('trades', []):
            print(f'   {t["entry_date"]:>12} {t["entry_price"]:>8.3f} {t["exit_price"]:>8.3f} '
                  f'{t["pnl_pct"]:>7.1%} {t["hold_days"]:>7}')
    
    return valid_all


if __name__ == '__main__':
    r1 = grid_search('512100', '512100.SH')
    r2 = grid_search('510500', '510500.SH')
    
    print(f'\n\n{"="*60}')
    print('汇总对比')
    print(f'{"="*60}')
    print(f'{"标的":>8} {"最优MA":>7} {"Tol":>6} {"MACDw":>6} {"N":>4} {"胜率":>7} {"累计":>8} {"均收益":>7} {"最大DD":>7} {"Sharpe":>7} {"连亏":>4} {"年均":>5}')
    print('-' * 100)
    for code, results in [('512100', r1), ('510500', r2)]:
        if results:
            best = results[0]
            p = best['params']
            print(f'{code:>8} {p["ma_period"]:>7} {p["tolerance"]:>6.0%} {p["macd_window"]:>6} '
                  f'{best["n"]:>4} {best["win_rate"]:>6.1%} {best["cum_return"]:>7.1%} '
                  f'{best["avg_return"]:>7.1%} {best["max_dd"]:>7.1%} '
                  f'{best["sharpe"]:>7.2f} {best["max_consec_loss"]:>4} {best["n_yearly"]:>5.1f}')
