#!/usr/bin/env python3
"""
📐 Optuna 固定层 k参数联合优化引擎 V1.0
签发：守东 + 联邦投顾 | 2026-07-04

用途：对固定层 VTI/VEA 的 k 参数（ATR乘数）进行 Optuna 联合优化
      买入区间 = [MA60 − k×ATR, MA60 + 2×ATR)
      回测框架 = 宪法级无止损框架（正金字塔两层 + 永续持有 + 冷却期去重）

与已有 optuna_k_optimizer.py 的区别：
1. 锚线固定 MA60（不是 MA40）
2. 买入区间含上沿 MA60+2×ATR（反击只有 MA40 上沿=MA40）
3. 建仓方式 = 正金字塔两层（30%+70%），非一次性全仓
4. 止损 = 买入均价−2×ATR，非入场价−2×ATR
5. 回测窗口 = 全量历史（2018~今），非固定3年
"""
import tushare as ts
import pandas as pd
import numpy as np
import optuna
import sys
from datetime import datetime, timedelta

# ============================================================
# §0 配置
# ============================================================

FIXED_TICKERS = ['VTI', 'VEA']

TICKER_CFG = {
    'VTI': {
        'name': '美股全市场ETF',
        'tushare_code': 'VTI',
        'type': 'us_daily',
        'anchor': 60,
        'current_k': 4.5,
        'start_date': '20180101',
    },
    'VEA': {
        'name': '发达市场ETF',
        'tushare_code': 'VEA',
        'type': 'us_daily',
        'anchor': 60,
        'current_k': 4.0,
        'start_date': '20180101',
    },
}

# 搜索空间
K_MIN, K_MAX = 1.0, 6.0
N_TRIALS_PER_TICKER = 150
N_STARTUP_TRIALS = 30

# 固定层实战SOP参数
COOLDOWN_DAYS = 5         # 建仓冷却期 ≥ 5个交易日
BATCH_RATIOS = [0.30, 0.70]  # 正金字塔两层

# 综合得分权重
W_WIN = 0.30
W_EXPECT = 0.30
W_PF = 0.20
W_HR = 0.15
W_CONSEC = 0.05


# ============================================================
# §1 固定层专用回测引擎
# ============================================================

def fetch_fixed_data(ticker, cfg):
    """从Tushare获取全量历史日线"""
    end_date = datetime.now().strftime('%Y%m%d')
    try:
        pro = ts.pro_api()
        df = pro.us_daily(ts_code=cfg['tushare_code'],
                          start_date=cfg['start_date'],
                          end_date=end_date)
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
        print(f"  ⚠️ {ticker} 取数失败: {e}")
        return None


def calc_fixed_indicators(df, anchor=60):
    """计算MA60 + ATR14"""
    df = df.copy()
    df['MA'] = df['Close'].rolling(window=anchor).mean()
    df['prev_close'] = df['Close'].shift(1)
    df['TR'] = df.apply(
        lambda r: max(r['High'] - r['Low'],
                      abs(r['High'] - r['prev_close']) if pd.notna(r['prev_close']) else 0,
                      abs(r['Low'] - r['prev_close']) if pd.notna(r['prev_close']) else 0),
        axis=1
    )
    df['ATR14'] = df['TR'].rolling(window=14).mean()
    return df


def backtest_fixed_layer(df, k, anchor=60):
    """
    固定层买入区间回测（宪法级无止损框架）：
    
    固定层宪法§0.1明确规定：
    「不设 ATR 止损、绝对底线止损、动态止盈——不设任何技术指标驱动的自动离场条件」
    
    因此回测逻辑是：
    - 买入区间 = [MA60 − k×ATR, MA60 + 2×ATR)
    - 正金字塔两层建仓（30%+70%）
    - **无止损**——建仓后永续持有
    - 退出 = 持有至数据末尾（模拟「买入后持有至今」）
    - 冷却期 = 5个交易日（仅用于信号去重，防止同一区间连续触发）
    
    目标：评估不同k值下，在区间内建仓的长期持有收益。
    """
    n = len(df)
    trades = []
    cooldown_end_idx = -1

    for i in range(anchor + 14, n):
        ma = df.loc[i, 'MA']
        atr = df.loc[i, 'ATR14']
        price = df.loc[i, 'Close']

        if pd.isna(ma) or pd.isna(atr) or atr <= 0:
            continue

        zone_lower = ma - k * atr
        zone_upper = ma + 2.0 * atr

        if not (zone_lower <= price < zone_upper):
            continue

        if i <= cooldown_end_idx:
            continue

        entry_date = df.loc[i, 'Date']

        # 两层建仓
        batch1_price = price
        batch1_ratio = BATCH_RATIOS[0]

        batch2_idx = i + COOLDOWN_DAYS
        batch2_price = None
        batch2_executed = False

        if batch2_idx < n:
            b2_ma = df.loc[batch2_idx, 'MA']
            b2_atr = df.loc[batch2_idx, 'ATR14']
            b2_price_val = df.loc[batch2_idx, 'Close']
            if pd.notna(b2_ma) and pd.notna(b2_atr):
                b2_lower = b2_ma - k * b2_atr
                b2_upper = b2_ma + 2.0 * b2_atr
                if b2_lower <= b2_price_val < b2_upper:
                    batch2_price = b2_price_val
                    batch2_executed = True

        if batch2_executed:
            avg_price = batch1_price * batch1_ratio + batch2_price * (1 - batch1_ratio)
        else:
            avg_price = batch1_price

        cooldown_end_idx = i + COOLDOWN_DAYS

        # 持有至数据末尾 → 计算最终收益
        exit_idx = n - 1
        exit_price = df.loc[n - 1, 'Close']
        exit_date = df.loc[n - 1, 'Date']
        
        return_pct = (exit_price - avg_price) / avg_price * 100
        hold_days = (exit_date - entry_date).days

        trades.append({
            'entry_date': entry_date,
            'entry_idx': i,
            'batch1_price': batch1_price,
            'batch2_price': batch2_price,
            'batch2_executed': batch2_executed,
            'avg_price': avg_price,
            'exit_date': exit_date,
            'exit_price': exit_price,
            'return_pct': return_pct,
            'hold_days': hold_days,
            'zone_lower': zone_lower,
            'zone_upper': zone_upper,
            'atr_at_entry': atr,
        })

    return trades


def calc_fixed_metrics(trades, df, k, anchor=60):
    """计算固定层绩效指标（宪法级无止损框架）"""
    n = len(trades)
    if n == 0:
        return {'total_trades': 0, 'score': -10.0}

    wins = [t for t in trades if t['return_pct'] > 0]
    losses = [t for t in trades if t['return_pct'] <= 0]

    win_rate = len(wins) / n
    avg_win = np.mean([t['return_pct'] for t in wins]) if wins else 0.0
    avg_loss = np.mean([t['return_pct'] for t in losses]) if losses else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    total_win = sum([t['return_pct'] for t in wins])
    total_loss = abs(sum([t['return_pct'] for t in losses]))
    pf = total_win / total_loss if total_loss > 0 else (float('inf') if total_win > 0 else 0.0)

    # 年化收益（基于平均持有天数）
    avg_hold_days = np.mean([t['hold_days'] for t in trades]) if trades else 0
    annualized_return = ((1 + expectancy/100) ** (365 / avg_hold_days) - 1) * 100 if avg_hold_days > 0 else 0

    # 最大连续亏损
    max_consec = 0
    cur = 0
    for t in trades:
        if t['return_pct'] <= 0:
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0

    # 命中率 HR = 区间内天数 / 总有效天数
    total_days = len(df) - (anchor + 14)
    zone_days = 0
    for i in range(anchor + 14, len(df)):
        ma = df.loc[i, 'MA']
        atr = df.loc[i, 'ATR14']
        price = df.loc[i, 'Close']
        if pd.isna(ma) or pd.isna(atr):
            continue
        lower = ma - k * atr
        upper = ma + 2.0 * atr
        if lower <= price < upper:
            zone_days += 1
    hr = zone_days / total_days if total_days > 0 else 0.0

    # 综合得分
    score = (
        win_rate      * W_WIN * 100 +
        (expectancy + 5) * W_EXPECT +
        min(pf, 5.0)  * W_PF +
        hr            * W_HR * 100 -
        max_consec    * W_CONSEC * 10
    )

    return {
        'total_trades': n,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'expectancy': expectancy,
        'pf': pf,
        'max_consec': max_consec,
        'hr': hr,
        'annualized_return': annualized_return,
        'avg_hold_days': avg_hold_days,
        'score': score,
    }


# ============================================================
# §2 Optuna 目标函数
# ============================================================

def make_fixed_objective(ticker, cfg):
    def objective(trial):
        k = trial.suggest_float('k', K_MIN, K_MAX, step=0.1)

        df = fetch_fixed_data(ticker, cfg)
        if df is None or len(df) < 200:
            return -float('inf')

        df = calc_fixed_indicators(df, anchor=cfg['anchor'])
        df = df.dropna(subset=['MA', 'ATR14']).reset_index(drop=True)

        if len(df) < 100:
            return -float('inf')

        trades = backtest_fixed_layer(df, k, anchor=cfg['anchor'])
        metrics = calc_fixed_metrics(trades, df, k, anchor=cfg['anchor'])

        if metrics['total_trades'] == 0:
            return -10.0

        # 记录中间值
        trial.set_user_attr('total_trades', metrics['total_trades'])
        trial.set_user_attr('win_rate', metrics['win_rate'])
        trial.set_user_attr('expectancy', metrics['expectancy'])
        trial.set_user_attr('pf', metrics['pf'])
        trial.set_user_attr('hr', metrics['hr'])
        trial.set_user_attr('max_consec', metrics['max_consec'])
        trial.set_user_attr('avg_win', metrics['avg_win'])
        trial.set_user_attr('avg_loss', metrics['avg_loss'])
        trial.set_user_attr('annualized_return', metrics['annualized_return'])
        trial.set_user_attr('avg_hold_days', metrics['avg_hold_days'])

        return metrics['score']

    return objective


# ============================================================
# §3 逐标优化 + 汇总报告
# ============================================================

def run_fixed_optimization(verbose=True):
    results = []

    print(f"\n{'#'*80}")
    print(f"  📐 Optuna 固定层 k参数联合优化引擎 V1.0")
    print(f"     标的: VTI + VEA | 锚线: MA60 | 区间: [MA60−k×ATR, MA60+2×ATR)")
    print(f"     框架: 正金字塔两层 + 2×ATR止损 + 5日冷却 + 120日强制离场")
    print(f"     搜索: k ∈ [{K_MIN}, {K_MAX}] | {N_TRIALS_PER_TICKER}次/标")
    print(f"     日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'#'*80}")

    for ticker in FIXED_TICKERS:
        cfg = TICKER_CFG[ticker]
        current_k = cfg['current_k']

        print(f"\n{'='*70}")
        print(f"  🎯 {ticker} {cfg['name']} — k参数优化")
        print(f"     当前k={current_k} | 搜索范围 [{K_MIN}, {K_MAX}]")
        print(f"{'='*70}")

        # 先评估当前k
        df = fetch_fixed_data(ticker, cfg)
        df = calc_fixed_indicators(df, anchor=cfg['anchor'])
        df = df.dropna(subset=['MA', 'ATR14']).reset_index(drop=True)
        trades_cur = backtest_fixed_layer(df, current_k, anchor=cfg['anchor'])
        metrics_cur = calc_fixed_metrics(trades_cur, df, current_k, anchor=cfg['anchor'])

        # Optuna搜索
        study = optuna.create_study(
            direction='maximize',
            sampler=optuna.samplers.TPESampler(
                n_startup_trials=N_STARTUP_TRIALS, seed=42
            ),
            study_name=f"{ticker}_fixed_k"
        )

        obj = make_fixed_objective(ticker, cfg)
        study.optimize(obj, n_trials=N_TRIALS_PER_TICKER, show_progress_bar=False)

        best_k = study.best_params['k']
        best_score = study.best_value

        # 用最优k重跑
        trades_best = backtest_fixed_layer(df, best_k, anchor=cfg['anchor'])
        metrics_best = calc_fixed_metrics(trades_best, df, best_k, anchor=cfg['anchor'])

        current_score = metrics_cur['score']

        print(f"\n  📊 优化结果:")
        print(f"  ┌{'─'*57}┐")
        print(f"  │ 当前k = {current_k:.1f} → 得分: {current_score:.2f} | 交易: {metrics_cur['total_trades']}笔 | 胜率: {metrics_cur['win_rate']*100:.1f}%")
        print(f"  │ 最优k = {best_k:.1f} → 得分: {best_score:.2f} | 交易: {metrics_best['total_trades']}笔 | 胜率: {metrics_best['win_rate']*100:.1f}%")
        print(f"  │ 得分变化: {best_score - current_score:+.2f}")
        print(f"  ├{'─'*57}┤")
        print(f"  │ 最优参数详细:")
        print(f"  │   胜率:       {metrics_best['win_rate']*100:.1f}%")
        print(f"  │   期望值:     {metrics_best['expectancy']:+.2f}%")
        print(f"  │   盈亏比:     {metrics_best['pf']:.2f}")
        print(f"  │   平均盈利:   {metrics_best['avg_win']:+.2f}%")
        print(f"  │   平均亏损:   {metrics_best['avg_loss']:+.2f}%")
        print(f"  │   命中率(HR): {metrics_best['hr']*100:.1f}%")
        print(f"  │   最大连亏:   {metrics_best['max_consec']}笔")
        print(f"  │   年化收益:   {metrics_best['annualized_return']:+.1f}%")
        print(f"  │   均持天数:   {metrics_best['avg_hold_days']:.0f}天")
        print(f"  └{'─'*57}┘")

        # Top 10
        valid = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        valid.sort(key=lambda t: t.value, reverse=True)
        print(f"\n  🏆 Top 10 k值:")
        print(f"  {'排名':<6} {'k':<8} {'得分':<10} {'胜率':<8} {'PF':<8} {'交易':<6} {'HR':<8}")
        for i, t in enumerate(valid[:10]):
            k_val = t.params['k']
            wr = t.user_attrs.get('win_rate', 0)
            pf_val = t.user_attrs.get('pf', 0)
            trades_n = t.user_attrs.get('total_trades', 0)
            hr_val = t.user_attrs.get('hr', 0)
            pf_str = f"{pf_val:.2f}" if pf_val != float('inf') else "∞"
            print(f"  {i+1:<6} {k_val:<8.1f} {t.value:<10.2f} {wr*100:<7.1f}% {pf_str:<8} {trades_n:<6} {hr_val*100:<7.1f}%")

        results.append({
            'ticker': ticker,
            'name': cfg['name'],
            'current_k': current_k,
            'current_score': current_score,
            'current_trades': metrics_cur['total_trades'],
            'current_win_rate': metrics_cur['win_rate'],
            'current_expectancy': metrics_cur['expectancy'],
            'current_pf': metrics_cur['pf'],
            'current_hr': metrics_cur['hr'],
            'best_k': round(best_k, 1),
            'best_score': best_score,
            'best_trades': metrics_best['total_trades'],
            'best_win_rate': metrics_best['win_rate'],
            'best_expectancy': metrics_best['expectancy'],
            'best_pf': metrics_best['pf'],
            'best_hr': metrics_best['hr'],
            'best_max_consec': metrics_best['max_consec'],
            'best_avg_win': metrics_best['avg_win'],
            'best_avg_loss': metrics_best['avg_loss'],
            'best_annualized': metrics_best['annualized_return'],
            'best_avg_hold': metrics_best['avg_hold_days'],
        })

    # ============================================================
    # §4 汇总报告
    # ============================================================
    print(f"\n\n{'='*100}")
    print(f"  📊 Optuna 固定层 k参数优化 汇总报告")
    print(f"{'='*100}\n")

    header = f"  {'标的':<6} {'当前k':>6} {'最优k':>6} {'得分Δ':>8} {'胜率':>8} {'期望':>8} {'PF':>6} {'HR':>8} {'交易':>5} {'连亏':>4} {'年化':>8}"
    print(header)
    print(f"  {'-'*78}")

    for r in results:
        delta = r['best_score'] - r['current_score']
        ds = f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"
        print(f"  {r['ticker']:<6} {r['current_k']:>6.1f} {r['best_k']:>6.1f} {ds:>8} "
              f"{r['best_win_rate']*100:>7.1f}% {r['best_expectancy']:>7.2f}% "
              f"{r['best_pf']:>6.2f} {r['best_hr']*100:>7.1f}% {r['best_trades']:>5} {r['best_max_consec']:>4} "
              f"{r['best_annualized']:>7.1f}%")

    print(f"\n  {'='*100}")
    print(f"  ⚡ 参数修正提案（修改权在守东）:\n")

    changed = 0
    for r in results:
        diff = abs(r['best_k'] - r['current_k'])
        if diff >= 0.5:
            d = '↑' if r['best_k'] > r['current_k'] else '↓'
            print(f"  🔴 {r['ticker']} {r['name']}: k={r['current_k']:.1f} → k={r['best_k']:.1f} {d}")
            print(f"     得分: {r['current_score']:.1f}→{r['best_score']:.1f} ({r['best_score']-r['current_score']:+.1f})")
            print(f"     胜率: {r['current_win_rate']*100:.1f}%→{r['best_win_rate']*100:.1f}% | "
                  f"期望: {r['current_expectancy']:+.2f}%→{r['best_expectancy']:+.2f}%")
            print(f"     交易: {r['current_trades']}→{r['best_trades']}笔 | PF: {r['current_pf']:.2f}→{r['best_pf']:.2f}")
            print(f"     年化: {r['best_annualized']:+.1f}% | 均持: {r['best_avg_hold']:.0f}天")
            print(f"     → {'🟢建议修正' if r['best_score'] - r['current_score'] > 2 else '🟡观察'}\n")
            changed += 1
        else:
            print(f"  🟢 {r['ticker']} {r['name']}: k={r['current_k']:.1f} → k={r['best_k']:.1f}（差异<0.5，维持）\n")

    if changed == 0:
        print(f"  ✅ 固定层当前k参数已处于最优区间，无需修正")

    print(f"  {'='*100}")
    print(f"\n  ⚠️ 以上为Optuna自动搜索结果，修改权在守东。任何参数变更需守东明确确认。")

    return results


# ============================================================
# §5 CLI入口
# ============================================================

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Optuna 固定层 k参数联合优化')
    p.add_argument('--ticker', type=str, help='单标优化（VTI/VEA）')
    p.add_argument('--trials', type=int, default=N_TRIALS_PER_TICKER, help='试验次数')
    p.add_argument('--quiet', action='store_true')
    args = p.parse_args()

    N_TRIALS_PER_TICKER = args.trials

    if args.ticker:
        t = args.ticker.upper()
        if t in TICKER_CFG:
            cfg = TICKER_CFG[t]
            df = fetch_fixed_data(t, cfg)
            df = calc_fixed_indicators(df, anchor=cfg['anchor'])
            df = df.dropna(subset=['MA', 'ATR14']).reset_index(drop=True)

            # 当前k
            trades_cur = backtest_fixed_layer(df, cfg['current_k'], anchor=cfg['anchor'])
            metrics_cur = calc_fixed_metrics(trades_cur, df, cfg['current_k'], anchor=cfg['anchor'])

            # Optuna
            study = optuna.create_study(
                direction='maximize',
                sampler=optuna.samplers.TPESampler(n_startup_trials=N_STARTUP_TRIALS, seed=42),
                study_name=f"{t}_fixed_k"
            )
            obj = make_fixed_objective(t, cfg)
            study.optimize(obj, n_trials=N_TRIALS_PER_TICKER, show_progress_bar=not args.quiet)

            best_k = study.best_params['k']
            trades_best = backtest_fixed_layer(df, best_k, anchor=cfg['anchor'])
            metrics_best = calc_fixed_metrics(trades_best, df, best_k, anchor=cfg['anchor'])

            print(f"\n{t} 当前k={cfg['current_k']}: 得分={metrics_cur['score']:.2f} | {metrics_cur['total_trades']}笔 | 胜率={metrics_cur['win_rate']*100:.1f}%")
            print(f"{t} 最优k={best_k:.1f}: 得分={metrics_best['score']:.2f} | {metrics_best['total_trades']}笔 | 胜率={metrics_best['win_rate']*100:.1f}%")
        else:
            print(f"❌ 未知标的: {t}")
            sys.exit(1)
    else:
        run_fixed_optimization(verbose=not args.quiet)
