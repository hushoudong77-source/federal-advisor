#!/usr/bin/env python3
"""
🔬 Optuna 三参数联合优化引擎 — 反击策略 k × 止损ATR × 冷却期
签发：守东（资产规划部首席审计官）
生效日期：2026-07-04

替代手动遍历 k=1.0~5.0，使用 TPE sampler 在连续空间中搜索最优参数组合。
目标函数：综合得分 = 胜率×0.30 + 期望值×0.30 + PF×0.20 + HR×0.15 − 连续亏损×0.05
"""

import tushare as ts
import pandas as pd
import numpy as np
import optuna
import sys
import os
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 标的配置（从 hitrate_backtest.py 同步）
# ============================================================

TICKER_CONFIG = {
    '513910': {
        'name': '港股通央企红利ETF', 'k': 2.7, 'stop_mult': 2.8, 'cooldown': 16,
        'anchor': 40, 'hold_days': 20,
        'tushare_code': '513910.SH', 'type': 'fund_daily',
    },
    '512100': {
        'name': '中证1000ETF', 'k': 2.0, 'stop_mult': 1.5, 'cooldown': 15,
        'anchor': 40, 'hold_days': 15,
        'tushare_code': '512100.SH', 'type': 'fund_daily',
    },
    '510500': {
        'name': '中证500ETF', 'k': 4.9, 'stop_mult': 2.8, 'cooldown': 60,
        'anchor': 40, 'hold_days': 15,
        'tushare_code': '510500.SH', 'type': 'fund_daily',
    },
    '588000': {
        'name': '科创50ETF', 'k': 4.7, 'stop_mult': 3.5, 'cooldown': 15,
        'anchor': 40, 'hold_days': 15,
        'tushare_code': '588000.SH', 'type': 'fund_daily',
    },
    '510880': {
        'name': '红利ETF易方达', 'k': 2.0, 'stop_mult': 2.0, 'cooldown': 30,
        'anchor': 40, 'hold_days': 20,
        'tushare_code': '510880.SH', 'type': 'fund_daily',
    },
    'BBJP': {
        'name': '日股ETF', 'k': 5.0, 'stop_mult': 3.5, 'cooldown': 14,
        'anchor': 40, 'hold_days': 15,
        'tushare_code': 'BBJP', 'type': 'us_daily',
    },
    'VNM': {
        'name': '越南ETF', 'k': 5.0, 'stop_mult': 1.5, 'cooldown': 9,
        'anchor': 40, 'hold_days': 10,
        'tushare_code': 'VNM', 'type': 'us_daily',
    },
}


# ============================================================
# 数据获取与指标计算（从 hitrate_backtest.py 移植）
# ============================================================

def fetch_data(ticker, cfg, years=5):
    """从Tushare获取日线数据"""
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=years*365 + 200)).strftime('%Y%m%d')
    
    try:
        pro = ts.pro_api()
        if cfg['type'] == 'fund_daily':
            df = pro.fund_daily(ts_code=cfg['tushare_code'],
                                start_date=start_date, end_date=end_date)
        elif cfg['type'] == 'us_daily':
            df = pro.us_daily(ts_code=cfg['tushare_code'],
                              start_date=start_date, end_date=end_date)
        else:
            return None
        
        if df is None or len(df) == 0:
            return None
        
        df = df.rename(columns={
            'trade_date': 'Date', 'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close', 'vol': 'Volume'
        })
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date').reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  ⚠️ {ticker} 获取失败: {e}")
        return None


def calc_technical_indicators(df, anchor_period):
    """计算 MA、ATR14"""
    df = df.copy()
    df['MA'] = df['Close'].rolling(window=anchor_period).mean()
    
    df['prev_close'] = df['Close'].shift(1)
    df['TR'] = df.apply(
        lambda r: max(r['High'] - r['Low'],
                      abs(r['High'] - r['prev_close']) if pd.notna(r['prev_close']) else 0,
                      abs(r['Low'] - r['prev_close']) if pd.notna(r['prev_close']) else 0),
        axis=1
    )
    df['ATR14'] = df['TR'].rolling(window=14).mean()
    return df


def identify_signals(df, anchor_period, k, hold_days, cooldown, stop_mult):
    """
    独立信号识别（从 hitrate_backtest.py 移植，去掉 588000 三维过滤）
    """
    signals = []
    n = len(df)
    cooling_end_idx = -1
    in_zone = False
    
    for i in range(n):
        if i < anchor_period + 14:
            continue
        
        ma_val = df.loc[i, 'MA']
        atr_val = df.loc[i, 'ATR14']
        price = df.loc[i, 'Close']
        
        if pd.isna(ma_val) or pd.isna(atr_val) or atr_val <= 0:
            continue
        
        zone_lower = ma_val - k * atr_val
        zone_upper = ma_val
        
        is_in_zone = (zone_lower <= price <= zone_upper)
        
        if cooling_end_idx > 0 and i <= cooling_end_idx:
            is_in_zone = False
        
        if is_in_zone and not in_zone:
            stop_price = zone_lower - stop_mult * atr_val
            
            signal = {
                'trigger_idx': i,
                'trigger_date': df.loc[i, 'Date'],
                'entry_price': price,
                'zone_lower': zone_lower,
                'stop_price': stop_price,
                'hold_days': hold_days,
            }
            signals.append(signal)
            cooling_end_idx = i + cooldown
            in_zone = True
        elif not is_in_zone:
            in_zone = False
    
    return signals


def calc_signal_results(signals, df):
    """逐信号盈亏计算"""
    for sig in signals:
        idx_entry = sig['trigger_idx']
        p_entry = sig['entry_price']
        p_stop = sig['stop_price']
        h = sig['hold_days']
        
        sig['result'] = None
        sig['exit_price'] = None
        sig['return_pct'] = None
        
        for d in range(1, h + 1):
            idx_current = idx_entry + d
            if idx_current >= len(df):
                sig['result'] = 'DATA_INSUFFICIENT'
                sig['exit_price'] = df.loc[len(df)-1, 'Close']
                break
            
            p_low = df.loc[idx_current, 'Low']
            p_close = df.loc[idx_current, 'Close']
            
            if p_low <= p_stop:
                sig['result'] = 'STOP'
                sig['exit_price'] = p_stop
                break
            
            if d == h:
                sig['result'] = 'WIN' if p_close > p_entry else 'LOSS'
                sig['exit_price'] = p_close
        
        if sig['exit_price'] is not None:
            sig['return_pct'] = (sig['exit_price'] - p_entry) / p_entry * 100
    
    return signals


# ============================================================
# Optuna 目标函数
# ============================================================

def create_objective(ticker, cfg, n_trials_hint=200):
    """
    创建 Optuna 目标函数。
    
    搜索空间：
    - k: [0.5, 5.0] 连续
    - stop_mult: [1.0, 4.0] 连续
    - cooldown: [5, 60] 整数
    
    目标函数（综合得分）= 
        胜率 × 0.30 + 期望值 × 0.30 + PF × 0.20 + HR × 0.15 − 连续亏损 × 0.05
    
    其中 PF 截断到 [0, 5]，期望值截断到 [−5, +10]，避免极端值主导。
    """
    
    # 一次性拉取数据（所有 trial 共享）
    print(f"\n{'='*60}")
    print(f"  🔬 Optuna 优化: {ticker} {cfg['name']}")
    print(f"     搜索空间: k∈[0.5, 5.0] | stop∈[1.0, 4.0] | cool∈[5, 60]")
    print(f"     算法: TPE sampler | 目标: {n_trials_hint} trials")
    print(f"{'='*60}\n")
    
    df_raw = fetch_data(ticker, cfg, years=5)
    if df_raw is None or len(df_raw) < 200:
        print(f"  ❌ 数据不足，无法优化")
        return None
    
    df_raw = calc_technical_indicators(df_raw, cfg['anchor'])
    df_raw = df_raw.dropna(subset=['MA', 'ATR14']).reset_index(drop=True)
    
    print(f"  📊 数据: {df_raw.iloc[0]['Date'].strftime('%Y-%m-%d')} ~ "
          f"{df_raw.iloc[-1]['Date'].strftime('%Y-%m-%d')} "
          f"({len(df_raw)} 交易日)\n")
    
    # 缓存：k × stop × cooldown → 得分
    cache = {}
    
    def objective(trial):
        # 采样
        k = trial.suggest_float('k', 0.5, 5.0)
        stop_mult = trial.suggest_float('stop_mult', 1.0, 4.0)
        cooldown = trial.suggest_int('cooldown', 5, 60)
        
        # 缓存键（四舍五入到合理精度避免缓存爆炸）
        cache_key = (round(k, 2), round(stop_mult, 2), cooldown)
        if cache_key in cache:
            return cache[cache_key]
        
        # 跑回测
        signals = identify_signals(
            df_raw, cfg['anchor'], k, cfg['hold_days'], cooldown, stop_mult
        )
        signals = calc_signal_results(signals, df_raw)
        
        valid = [s for s in signals if s['result'] in ('WIN', 'LOSS', 'STOP')]
        n = len(valid)
        
        if n == 0:
            # 零信号 → 最低分
            cache[cache_key] = -999.0
            return -999.0
        
        wins = [s for s in valid if s['result'] == 'WIN']
        losses = [s for s in valid if s['result'] in ('LOSS', 'STOP')]
        
        n_win = len(wins)
        n_loss = len(losses)
        
        # 胜率
        win_rate = n_win / n if n > 0 else 0
        
        # 平均盈亏
        avg_win = np.mean([s['return_pct'] for s in wins]) if n_win > 0 else 0.0
        avg_loss = abs(np.mean([s['return_pct'] for s in losses])) if n_loss > 0 else 0.0
        
        # 期望值（截断）
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        expectancy_clipped = np.clip(expectancy, -5.0, 10.0)
        
        # 盈亏比 PF（截断）
        total_win = sum([s['return_pct'] for s in wins])
        total_loss = abs(sum([s['return_pct'] for s in losses]))
        pf = total_win / total_loss if total_loss > 0 else (5.0 if total_win > 0 else 0.0)
        pf_clipped = min(pf, 5.0)
        
        # 命中率 HR = 区间内天数 / 总交易日
        n_rows = len(df_raw)
        zone_days = 0
        for i in range(cfg['anchor'] + 14, n_rows):
            ma_val = df_raw.loc[i, 'MA']
            atr_val = df_raw.loc[i, 'ATR14']
            if pd.isna(ma_val) or pd.isna(atr_val):
                continue
            price = df_raw.loc[i, 'Close']
            lower = ma_val - k * atr_val
            if lower <= price <= ma_val:
                zone_days += 1
        total_days = n_rows - (cfg['anchor'] + 14)
        hr = zone_days / total_days if total_days > 0 else 0.0
        
        # 最大连续亏损
        max_consec = 0
        cur = 0
        for s in valid:
            if s['result'] in ('LOSS', 'STOP'):
                cur += 1
                max_consec = max(max_consec, cur)
            else:
                cur = 0
        
        # 综合得分
        score = (
            win_rate * 0.30 +
            expectancy_clipped * 0.30 +
            pf_clipped * 0.20 +
            hr * 0.15 -
            max_consec * 0.05
        )
        
        # 附加属性（用于后续分析）
        trial.set_user_attr('n_signals', n)
        trial.set_user_attr('win_rate', win_rate)
        trial.set_user_attr('expectancy', expectancy)
        trial.set_user_attr('pf', pf)
        trial.set_user_attr('hr', hr)
        trial.set_user_attr('max_consec', max_consec)
        trial.set_user_attr('avg_win', avg_win)
        trial.set_user_attr('avg_loss', avg_loss)
        
        cache[cache_key] = score
        return score
    
    return objective, df_raw


# ============================================================
# 结果输出
# ============================================================

def print_results(study, ticker, cfg):
    """打印优化结果"""
    best = study.best_trial
    
    print(f"\n{'='*60}")
    print(f"  ✅ 优化完成: {ticker} {cfg['name']}")
    print(f"{'='*60}")
    print(f"  最优参数:")
    print(f"    k          = {best.params['k']:.2f}")
    print(f"    stop_mult  = {best.params['stop_mult']:.2f}")
    print(f"    cooldown   = {best.params['cooldown']}")
    print(f"  最优得分: {best.value:.4f}")
    print(f"")
    print(f"  性能指标:")
    print(f"    信号数:     {best.user_attrs['n_signals']}")
    print(f"    胜率:       {best.user_attrs['win_rate']*100:.1f}%")
    print(f"    期望值:     {best.user_attrs['expectancy']:+.2f}%")
    print(f"    PF:         {best.user_attrs['pf']:.2f}")
    print(f"    HR:         {best.user_attrs['hr']*100:.1f}%")
    print(f"    平均盈利:   {best.user_attrs['avg_win']:+.2f}%")
    print(f"    平均亏损:   {best.user_attrs['avg_loss']:.2f}%")
    print(f"    最大连亏:   {best.user_attrs['max_consec']} 笔")
    print(f"")
    print(f"  搜索统计:")
    print(f"    总 trials:  {len(study.trials)}")
    print(f"    完成:       {len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])}")
    print(f"    剪枝:       {len([t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED])}")
    print(f"    耗时:       {study.trials[-1].datetime_complete - study.trials[0].datetime_start if study.trials else 'N/A'}")
    
    # 对比当前参数
    current_k = cfg.get('k', 2.0)
    current_stop = cfg.get('stop_mult', 2.0)
    current_cool = cfg.get('cooldown', 30)
    
    print(f"\n  📊 当前参数 vs 最优参数:")
    print(f"    {'参数':<15} {'当前':>8} {'最优':>8} {'变化':>8}")
    print(f"    {'-'*15} {'-'*8} {'-'*8} {'-'*8}")
    print(f"    {'k':<15} {current_k:>8.2f} {best.params['k']:>8.2f} {best.params['k']-current_k:>+8.2f}")
    print(f"    {'stop_mult':<15} {current_stop:>8.2f} {best.params['stop_mult']:>8.2f} {best.params['stop_mult']-current_stop:>+8.2f}")
    print(f"    {'cooldown':<15} {current_cool:>8} {best.params['cooldown']:>8} {best.params['cooldown']-current_cool:>+8}")
    
    # 建议
    k_diff = abs(best.params['k'] - current_k)
    stop_diff = abs(best.params['stop_mult'] - current_stop)
    cool_diff = abs(best.params['cooldown'] - current_cool)
    
    if k_diff < 0.3 and stop_diff < 0.3 and cool_diff < 5:
        print(f"\n  🟢 裁决: 参数稳定，维持当前不变")
    elif best.value > 0 and k_diff > 1.0:
        print(f"\n  🔴 建议: k 参数差距显著，建议修正 → k={best.params['k']:.1f}")
    else:
        print(f"\n  🟡 裁决: 观察，与手动遍历对撞后再决定")
    
    return best


def run_optuna_optimization(ticker, n_trials=200, seed=42):
    """运行单标 Optuna 优化"""
    if ticker not in TICKER_CONFIG:
        print(f"❌ 标的不在配置表中: {ticker}")
        return None
    
    cfg = TICKER_CONFIG[ticker].copy()
    
    # 注入当前参数用于对比
    from hitrate_backtest import TICKER_CONFIG as BT_CFG
    if ticker in BT_CFG:
        cfg['k'] = BT_CFG[ticker]['k']
        cfg['stop_mult'] = BT_CFG[ticker].get('stop_mult', 2.0)
        cfg['cooldown'] = BT_CFG[ticker].get('cooldown', 30)
    else:
        cfg['k'] = 2.0
        cfg['stop_mult'] = 2.0
        cfg['cooldown'] = 30
    
    obj_and_df = create_objective(ticker, cfg, n_trials)
    if obj_and_df is None:
        return None
    
    objective, df_raw = obj_and_df
    
    # 创建 study
    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(
        direction='maximize',
        sampler=sampler,
        study_name=f'{ticker}_optuna_k_stop_cool',
    )
    
    # 运行
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
    
    # 输出
    best = print_results(study, ticker, cfg)
    
    return study, best


# ============================================================
# CLI
# ============================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Optuna 三参数联合优化')
    parser.add_argument('ticker', nargs='?', default='513910',
                        help='标的代码 (默认: 513910)')
    parser.add_argument('--trials', type=int, default=200,
                        help='Optuna trials 数 (默认: 200)')
    parser.add_argument('--seed', type=int, default=42,
                        help='随机种子 (默认: 42)')
    parser.add_argument('--all', action='store_true',
                        help='优化所有反击标的')
    
    args = parser.parse_args()
    
    if args.all:
        for ticker in TICKER_CONFIG:
            print(f"\n{'#'*60}")
            print(f"#  {ticker}")
            print(f"{'#'*60}")
            run_optuna_optimization(ticker, n_trials=args.trials, seed=args.seed)
    else:
        run_optuna_optimization(args.ticker, n_trials=args.trials, seed=args.seed)
