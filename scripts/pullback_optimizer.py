#!/usr/bin/env python3
"""
回踩均线策略 — 逐标完整参数搜索
搜索空间: 均线周期 × 回踩容忍度 × MACD金叉窗口 × 缩量阈值 × 硬止损 × 止盈方式
"""
import tushare as ts
import pandas as pd
import numpy as np
import optuna
import json
import warnings
warnings.filterwarnings('ignore')

ts.set_token('026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')
pro = ts.pro_api()

TICKERS = {
    '512100': '512100.SH',
    '513180': '513180.SH',
    '588000': '588000.SH',
    '510500': '510500.SH',
}

TICKER_NAMES = {
    '512100': '中证1000ETF',
    '513180': '恒生科技ETF',
    '588000': '科创50ETF',
    '510500': '中证500ETF',
}

def calc_ma(df, window):
    return df['close'].rolling(window).mean()

def calc_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df['close'].ewm(span=fast).mean()
    ema_slow = df['close'].ewm(span=slow).mean()
    diff = ema_fast - ema_slow
    dea = diff.ewm(span=signal).mean()
    bar = 2 * (diff - dea)
    return diff, dea, bar

def calc_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def simulate(df, params):
    """模拟策略交易"""
    ma_period = int(params['ma_period'])
    pullback_tol = params['pullback_tol']  # 回踩容忍度 (0.01=1%)
    macd_window = int(params['macd_window'])  # MACD金叉回溯窗口（交易日）
    vol_threshold = params['vol_threshold']  # 缩量阈值（<1.0为缩量）
    hard_stop = params['hard_stop']  # 硬止损（如-0.08=-8%）
    take_profit_mode = int(params['take_profit_mode'])  # 0=MA, 1=ATR回撤, 2=固定%
    take_profit_val = params['take_profit_val']  # 止盈参数
    atr_stop_mult = params['atr_stop_mult']  # ATR止损倍数
    hold_days_max = int(params['hold_days_max'])  # 最大持仓天数
    
    n = len(df)
    
    # 计算指标
    ma = calc_ma(df, ma_period)
    diff, dea, bar = calc_macd(df)
    atr = calc_atr(df, 14)
    vol_ma20 = df['vol'].rolling(20).mean()
    vol_ratio = df['vol'] / vol_ma20
    
    # 信号
    ma_up = ma > ma.shift(5)  # MA方向向上
    near_ma = (df['close'] / ma - 1).abs() < pullback_tol  # 回踩到MA附近
    macd_golden = (bar > 0) & (bar.shift(1) <= 0)  # 当日金叉
    macd_golden_recent = pd.Series(False, index=df.index)
    for i in range(len(df)):
        if i < macd_window:
            continue
        # 回溯窗口内是否有金叉
        for j in range(max(0, i-macd_window), i+1):
            if j < len(df) and macd_golden.iloc[j]:
                macd_golden_recent.iloc[i] = True
                break
    volume_shrink = vol_ratio < vol_threshold  # 缩量
    
    # 入场: MA向上 + 回踩 + MACD金叉(窗口内) + 缩量
    entry = ma_up & near_ma & macd_golden_recent & volume_shrink
    
    trades = []
    in_position = False
    entry_idx = None
    entry_price = None
    highest_close = None
    
    for i in range(n):
        if not in_position:
            if entry.iloc[i] and i < n - 1:
                # 次日开盘入场
                entry_idx = i + 1
                entry_price = df['open'].iloc[entry_idx]
                highest_close = df['close'].iloc[entry_idx]
                in_position = True
        else:
            days_held = i - entry_idx
            current_close = df['close'].iloc[i]
            current_high = df['high'].iloc[i]
            current_low = df['low'].iloc[i]
            current_atr = atr.iloc[i]
            
            highest_close = max(highest_close, current_close)
            
            # 硬止损
            hard_stop_price = entry_price * (1 + hard_stop)
            # ATR止损
            atr_stop_price = entry_price - atr_stop_mult * current_atr
            stop_price = max(hard_stop_price, atr_stop_price)  # 取两者中较高的（更紧的止损）
            
            exit_reason = None
            exit_price = None
            
            # 止损检查
            if current_low <= stop_price:
                exit_price = min(current_low, stop_price)
                exit_reason = 'STOP'
            # 止盈检查
            elif take_profit_mode == 0:  # MA止盈
                if current_close >= ma.iloc[i]:
                    exit_price = current_close
                    exit_reason = 'TP_MA'
            elif take_profit_mode == 1:  # ATR回撤止盈
                if (highest_close - current_close) >= take_profit_val * current_atr:
                    exit_price = current_close
                    exit_reason = 'TP_ATR_DRAWDOWN'
            elif take_profit_mode == 2:  # 固定%止盈
                if current_close >= entry_price * (1 + take_profit_val):
                    exit_price = current_close
                    exit_reason = 'TP_FIXED'
            
            # 强制离场（最大持仓天数）
            if exit_reason is None and days_held >= hold_days_max:
                exit_price = current_close
                exit_reason = 'MAX_DAYS'
            
            if exit_reason is not None:
                pnl_pct = (exit_price / entry_price - 1)
                trades.append({
                    'entry_date': df.index[entry_idx],
                    'exit_date': df.index[i],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason,
                    'days_held': days_held,
                })
                in_position = False
                entry_idx = None
                entry_price = None
                highest_close = None
    
    # 未平仓按最后收盘价平仓
    if in_position:
        i = n - 1
        days_held = i - entry_idx
        pnl_pct = (df['close'].iloc[i] / entry_price - 1)
        trades.append({
            'entry_date': df.index[entry_idx],
            'exit_date': df.index[i],
            'entry_price': entry_price,
            'exit_price': df['close'].iloc[i],
            'pnl_pct': pnl_pct,
            'exit_reason': 'EOD',
            'days_held': days_held,
        })
    
    return trades

def objective(trial, ticker_code, df):
    """Optuna目标函数"""
    params = {
        'ma_period': trial.suggest_int('ma_period', 10, 60, step=5),
        'pullback_tol': trial.suggest_float('pullback_tol', 0.01, 0.05, step=0.005),
        'macd_window': trial.suggest_int('macd_window', 0, 5),
        'vol_threshold': trial.suggest_float('vol_threshold', 0.5, 1.2, step=0.1),
        'hard_stop': trial.suggest_float('hard_stop', -0.15, -0.03, step=0.01),
        'take_profit_mode': trial.suggest_int('take_profit_mode', 0, 2),  # 0=MA, 1=ATR回撤, 2=固定%
        'take_profit_val': trial.suggest_float('take_profit_val', 0.03, 0.20, step=0.01),
        'atr_stop_mult': trial.suggest_float('atr_stop_mult', 1.0, 3.0, step=0.25),
        'hold_days_max': trial.suggest_int('hold_days_max', 20, 120, step=10),
    }
    
    trades = simulate(df, params)
    
    if len(trades) < 5:
        return -9999
    
    pnl_list = [t['pnl_pct'] for t in trades]
    wins = sum(1 for p in pnl_list if p > 0)
    win_rate = wins / len(trades)
    avg_win = np.mean([p for p in pnl_list if p > 0]) if wins > 0 else 0
    avg_loss = np.mean([p for p in pnl_list if p <= 0]) if wins < len(trades) else 0
    total_return = np.prod([1 + p for p in pnl_list]) - 1
    
    # 综合得分: 胜率*0.3 + 总收益*0.3 + 盈亏比*0.2 + 信号数*0.1 + 最大回撤惩罚*0.1
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 5.0
    profit_factor = min(profit_factor, 5.0)
    
    # 最大回撤
    cumsum = np.cumprod([1 + p for p in pnl_list])
    peak = np.maximum.accumulate(cumsum)
    max_dd = np.min((cumsum - peak) / peak)
    
    dd_penalty = 1.0 if max_dd > -0.15 else (0.5 if max_dd > -0.25 else 0.0)
    
    score = (
        win_rate * 0.30 +
        min(total_return, 3.0) * 0.30 +
        profit_factor / 5.0 * 0.20 +
        min(len(trades), 50) / 50 * 0.10 +
        (1 - abs(dd_penalty)) * 0.10
    )
    
    return score

def main():
    print("=" * 80)
    print("回踩均线策略 — 逐标完整参数搜索")
    print("搜索空间: MA周期 × 回踩容忍度 × MACD窗口 × 缩量阈值 × 硬止损 × 止盈方式")
    print("=" * 80)
    
    for ticker, ts_code in TICKERS.items():
        print(f"\n{'='*60}")
        print(f"  {ticker} ({TICKER_NAMES[ticker]}) — Optuna TPE 参数搜索")
        print(f"{'='*60}")
        
        # 拉取全量日线
        df = pro.fund_daily(ts_code=ts_code, start_date='20180101', end_date='20260706')
        if df.empty:
            print(f"  ❌ 无数据，跳过")
            continue
        df = df.sort_values('trade_date').reset_index(drop=True)
        df.columns = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'change', 'pct_chg', 'vol', 'amount']
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.set_index('trade_date')
        
        print(f"  数据: {len(df)}条日线 ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")
        
        # Optuna优化
        study = optuna.create_study(
            direction='maximize',
            sampler=optuna.samplers.TPESampler(seed=42),
            pruner=optuna.pruners.MedianPruner(n_warmup_steps=20),
        )
        
        study.optimize(
            lambda trial: objective(trial, ticker, df),
            n_trials=300,
            show_progress_bar=False,
        )
        
        best = study.best_params
        best_score = study.best_value
        
        # 用最优参数跑一遍
        trades = simulate(df, best)
        pnl_list = [t['pnl_pct'] for t in trades]
        wins = sum(1 for p in pnl_list if p > 0)
        
        if len(trades) > 0:
            avg_pnl = np.mean(pnl_list)
            total_ret = np.prod([1 + p for p in pnl_list]) - 1
            avg_win = np.mean([p for p in pnl_list if p > 0]) if wins > 0 else 0
            avg_loss = np.mean([p for p in pnl_list if p <= 0]) if wins < len(trades) else 0
            
            cumsum = np.cumprod([1 + p for p in pnl_list])
            peak = np.maximum.accumulate(cumsum)
            max_dd = np.min((cumsum - peak) / peak)
            
            exit_reasons = {}
            for t in trades:
                r = t['exit_reason']
                exit_reasons[r] = exit_reasons.get(r, 0) + 1
        else:
            avg_pnl = total_ret = avg_win = avg_loss = max_dd = 0
            exit_reasons = {}
        
        print(f"\n  ✅ 最优参数:")
        print(f"     MA周期: {int(best['ma_period'])}")
        print(f"     回踩容忍度: {best['pullback_tol']:.1%}")
        print(f"     MACD金叉窗口: {int(best['macd_window'])}日")
        print(f"     缩量阈值: {best['vol_threshold']:.1f}×VOL_MA20")
        print(f"     硬止损: {best['hard_stop']:.1%}")
        print(f"     止盈模式: {'MA' if best['take_profit_mode']==0 else 'ATR回撤' if best['take_profit_mode']==1 else '固定%'}")
        print(f"     止盈值: {best['take_profit_val']:.1%}")
        print(f"     ATR止损倍数: {best['atr_stop_mult']:.1f}×ATR")
        print(f"     最大持仓: {int(best['hold_days_max'])}日")
        
        print(f"\n  📊 绩效:")
        print(f"     交易笔数: {len(trades)}")
        print(f"     胜率: {wins/len(trades)*100:.1f}%")
        print(f"     平均盈亏: {avg_pnl:+.2%}")
        print(f"     累计收益: {total_ret:+.1%}")
        print(f"     平均盈利: {avg_win:+.2%}  |  平均亏损: {avg_loss:+.2%}")
        print(f"     盈亏比: {abs(avg_win/avg_loss) if avg_loss != 0 else 99:.1f}")
        print(f"     最大回撤: {max_dd:.1%}")
        print(f"     退出分布: {exit_reasons}")
        print(f"     Optuna得分: {best_score:.3f}")
        
        # 前5笔交易详情
        print(f"\n  📋 最近5笔:")
        for t in trades[-5:]:
            print(f"     {t['entry_date'].strftime('%Y-%m-%d')} → {t['exit_date'].strftime('%Y-%m-%d')} | "
                  f"{t['entry_price']:.3f}→{t['exit_price']:.3f} | {t['pnl_pct']:+.2%} | "
                  f"{t['exit_reason']} | {t['days_held']}d")
        
        # 逐年绩效
        if len(trades) > 0:
            print(f"\n  📅 逐年绩效:")
            for year in range(2019, 2027):
                year_trades = [t for t in trades if t['entry_date'].year == year]
                if not year_trades:
                    continue
                y_pnl = [t['pnl_pct'] for t in year_trades]
                y_wins = sum(1 for p in y_pnl if p > 0)
                y_total = np.prod([1 + p for p in y_pnl]) - 1
                print(f"     {year}: {len(year_trades)}笔 | 胜率{y_wins/len(year_trades)*100:.0f}% | "
                      f"累计{y_total:+.1%} | 均{y_total/len(year_trades):+.2%}")

if __name__ == '__main__':
    main()
