#!/usr/bin/env python3
"""
📐 Optuna 512100 中证1000ETF 三参数联合优化引擎 V1.0
签发：守东 + 联邦投顾 | 2026-07-04

用途：对 512100 的 C3 独立参数进行 Optuna 三参数联合优化
      - k: ATR乘数（当前 2.0，搜索 0.5~5.0）
      - stop_mult: 止损ATR倍数（当前 1.5，搜索 0.5~3.5）
      - cooldown_days: 冷却期天数（当前 15，搜索 5~60）

回测框架：实战SOP（正金字塔两层 + 止损 + SRC-6−15%硬止损 + 120日强制离场 + 冷却期）
数据源：Tushare fund_daily 全量历史
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

TICKER = '512100'
TICKER_CFG = {
    'name': '中证1000ETF',
    'tushare_code': '512100.SH',
    'type': 'fund_daily',
    'anchor': 40,
    'current_k': 2.0,
    'current_stop_mult': 1.5,
    'current_cooldown': 15,
    'start_date': '20180101',
    'src6': -0.15,        # SRC-6 硬止损 −15%
    'max_hold': 120,       # 强制离场
}

# 搜索空间
K_MIN, K_MAX = 0.5, 5.0
STOP_MULT_MIN, STOP_MULT_MAX = 0.5, 3.5
COOLDOWN_MIN, COOLDOWN_MAX = 5, 60

N_TRIALS = 200
N_STARTUP = 40

# 正金字塔两层
BATCH_RATIOS = [0.30, 0.70]

# 综合得分权重
W_WIN = 0.30
W_EXPECT = 0.30
W_PF = 0.20
W_HR = 0.15
W_CONSEC = 0.05


# ============================================================
# §1 数据获取 + 指标计算
# ============================================================

def fetch_data():
    end_date = datetime.now().strftime('%Y%m%d')
    try:
        pro = ts.pro_api()
        df = pro.fund_daily(ts_code=TICKER_CFG['tushare_code'],
                            start_date=TICKER_CFG['start_date'],
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
        print(f"  ⚠️ 取数失败: {e}")
        return None


def calc_indicators(df, anchor=40):
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


# ============================================================
# §2 实战SOP回测引擎
# ============================================================

def backtest_512100(df, k, stop_mult, cooldown_days, anchor=40):
    """
    512100 反击策略实战SOP回测：
    - 买入区间 = [MA40 − k×ATR, MA40]
    - 正金字塔两层建仓（30%+70%）
    - 止损 = 买入均价 − stop_mult×ATR
    - SRC-6 硬止损 = −15%（从买入均价计算）
    - 120日强制离场
    - 冷却期 = cooldown_days
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
        zone_upper = ma  # 反击上沿 = 锚线

        if not (zone_lower <= price <= zone_upper):
            continue

        if i <= cooldown_end_idx:
            continue

        entry_date = df.loc[i, 'Date']

        # 两层建仓
        batch1_price = price
        batch1_ratio = BATCH_RATIOS[0]

        batch2_idx = i + cooldown_days
        batch2_price = None
        batch2_executed = False

        if batch2_idx < n:
            b2_ma = df.loc[batch2_idx, 'MA']
            b2_atr = df.loc[batch2_idx, 'ATR14']
            b2_price_val = df.loc[batch2_idx, 'Close']
            if pd.notna(b2_ma) and pd.notna(b2_atr):
                b2_lower = b2_ma - k * b2_atr
                if b2_lower <= b2_price_val <= b2_ma:
                    batch2_price = b2_price_val
                    batch2_executed = True

        if batch2_executed:
            avg_price = batch1_price * batch1_ratio + batch2_price * (1 - batch1_ratio)
        else:
            avg_price = batch1_price

        # 两个止损线取更严
        stop_atr = avg_price - stop_mult * atr
        stop_src6 = avg_price * (1 + TICKER_CFG['src6'])  # SRC-6 = −15%
        stop_price = max(stop_atr, stop_src6)  # 取更高（更紧）的止损

        cooldown_end_idx = i + cooldown_days

        # 逐日模拟持有
        exit_price = None
        exit_date = None
        exit_reason = None

        for d in range(1, TICKER_CFG['max_hold'] + 1):
            j = i + d
            if j >= n:
                exit_price = df.loc[n - 1, 'Close']
                exit_date = df.loc[n - 1, 'Date']
                exit_reason = 'DATA_END'
                break

            p_low = df.loc[j, 'Low']
            p_close = df.loc[j, 'Close']

            if p_low <= stop_price:
                exit_price = stop_price
                exit_date = df.loc[j, 'Date']
                exit_reason = 'STOP_LOSS'
                break

            if d == TICKER_CFG['max_hold']:
                exit_price = p_close
                exit_date = df.loc[j, 'Date']
                exit_reason = 'TIME_EXIT'

        if exit_price is None:
            continue

        return_pct = (exit_price - avg_price) / avg_price * 100

        trades.append({
            'entry_date': entry_date,
            'avg_price': avg_price,
            'batch2_executed': batch2_executed,
            'stop_price': stop_price,
            'stop_atr': stop_atr,
            'stop_src6': stop_src6,
            'exit_date': exit_date,
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'return_pct': return_pct,
            'zone_lower': zone_lower,
            'atr_at_entry': atr,
        })

    return trades


# ============================================================
# §3 绩效指标计算
# ============================================================

def calc_metrics(trades, df, k, anchor=40):
    n = len(trades)
    if n == 0:
        return {'total_trades': 0, 'score': -10.0}

    wins = [t for t in trades if t['return_pct'] > 0]
    losses = [t for t in trades if t['return_pct'] <= 0]
    stops = [t for t in trades if t['exit_reason'] == 'STOP_LOSS']

    win_rate = len(wins) / n
    avg_win = np.mean([t['return_pct'] for t in wins]) if wins else 0.0
    avg_loss = np.mean([t['return_pct'] for t in losses]) if losses else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss
    total_return = sum([t['return_pct'] for t in trades])

    total_win_pct = sum([t['return_pct'] for t in wins])
    total_loss_pct = abs(sum([t['return_pct'] for t in losses]))
    pf = total_win_pct / total_loss_pct if total_loss_pct > 0 else (float('inf') if total_win_pct > 0 else 0.0)

    max_consec = 0; cur = 0
    for t in trades:
        if t['return_pct'] <= 0:
            cur += 1; max_consec = max(max_consec, cur)
        else:
            cur = 0

    # 命中率
    total_days = len(df) - (anchor + 14)
    zone_days = 0
    for i in range(anchor + 14, len(df)):
        ma = df.loc[i, 'MA']; atr = df.loc[i, 'ATR14']; p = df.loc[i, 'Close']
        if pd.isna(ma) or pd.isna(atr): continue
        if ma - k * atr <= p <= ma: zone_days += 1
    hr = zone_days / total_days if total_days > 0 else 0.0

    score = (
        win_rate      * W_WIN * 100 +
        (expectancy + 5) * W_EXPECT +
        min(pf, 5.0)  * W_PF +
        hr            * W_HR * 100 -
        max_consec    * W_CONSEC * 10
    )

    return {
        'total_trades': n, 'win_rate': win_rate,
        'avg_win': avg_win, 'avg_loss': avg_loss,
        'expectancy': expectancy, 'total_return': total_return,
        'pf': pf, 'max_consec': max_consec, 'hr': hr,
        'stop_count': len(stops), 'score': score,
    }


# ============================================================
# §4 Optuna 目标函数
# ============================================================

def make_objective(df):
    def objective(trial):
        k = trial.suggest_float('k', K_MIN, K_MAX)
        stop_mult = trial.suggest_float('stop_mult', STOP_MULT_MIN, STOP_MULT_MAX)
        cooldown = trial.suggest_int('cooldown_days', COOLDOWN_MIN, COOLDOWN_MAX)

        trades = backtest_512100(df, k, stop_mult, cooldown, anchor=TICKER_CFG['anchor'])
        metrics = calc_metrics(trades, df, k, anchor=TICKER_CFG['anchor'])

        if metrics['total_trades'] == 0:
            return -10.0

        trial.set_user_attr('total_trades', metrics['total_trades'])
        trial.set_user_attr('win_rate', metrics['win_rate'])
        trial.set_user_attr('expectancy', metrics['expectancy'])
        trial.set_user_attr('total_return', metrics['total_return'])
        trial.set_user_attr('pf', metrics['pf'])
        trial.set_user_attr('max_consec', metrics['max_consec'])
        trial.set_user_attr('hr', metrics['hr'])
        trial.set_user_attr('stop_count', metrics['stop_count'])
        trial.set_user_attr('avg_win', metrics['avg_win'])
        trial.set_user_attr('avg_loss', metrics['avg_loss'])

        return metrics['score']

    return objective


# ============================================================
# §5 主程序
# ============================================================

def run():
    print(f"\n{'#'*80}")
    print(f"  📐 Optuna 512100 三参数联合优化引擎 V1.0")
    print(f"     标的: 512100 中证1000ETF | 锚线: MA40 | 区间: [MA40−k×ATR, MA40]")
    print(f"     框架: 正金字塔两层 + 止损 + SRC-6 −15% + 120日强制离场 + 冷却期")
    print(f"     参数: k∈[{K_MIN},{K_MAX}] | stop_mult∈[{STOP_MULT_MIN},{STOP_MULT_MAX}] | cooldown∈[{COOLDOWN_MIN},{COOLDOWN_MAX}]")
    print(f"     当前: k={TICKER_CFG['current_k']} | stop_mult={TICKER_CFG['current_stop_mult']} | cooldown={TICKER_CFG['current_cooldown']}")
    print(f"     试验: {N_TRIALS}次（含{N_STARTUP}次随机探索）")
    print(f"{'#'*80}")

    # 取数
    print(f"\n  📡 拉取 Tushare 数据...")
    df = fetch_data()
    if df is None:
        print("  ❌ 数据获取失败")
        return
    df = calc_indicators(df, anchor=TICKER_CFG['anchor'])
    df = df.dropna(subset=['MA', 'ATR14']).reset_index(drop=True)
    print(f"  ✅ {len(df)}行 | {df['Date'].min().date()} ~ {df['Date'].max().date()}")

    # 评估当前参数
    print(f"\n  📊 评估当前参数...")
    trades_cur = backtest_512100(df, TICKER_CFG['current_k'],
                                 TICKER_CFG['current_stop_mult'],
                                 TICKER_CFG['current_cooldown'])
    m_cur = calc_metrics(trades_cur, df, TICKER_CFG['current_k'])

    # Optuna
    print(f"\n  🔍 Optuna TPE 搜索中...")
    study = optuna.create_study(
        direction='maximize',
        sampler=optuna.samplers.TPESampler(n_startup_trials=N_STARTUP, seed=42),
        study_name='512100_3param'
    )
    obj = make_objective(df)
    study.optimize(obj, n_trials=N_TRIALS, show_progress_bar=False)

    best_k = study.best_params['k']
    best_stop = study.best_params['stop_mult']
    best_cool = study.best_params['cooldown_days']
    best_score = study.best_value

    trades_best = backtest_512100(df, best_k, best_stop, best_cool)
    m_best = calc_metrics(trades_best, df, best_k)

    # ============================================================
    # 输出
    # ============================================================
    print(f"\n{'='*80}")
    print(f"  📊 512100 三参数联合优化 结果")
    print(f"{'='*80}")

    print(f"\n  ┌{'─'*70}┐")
    print(f"  │ 当前参数: k={TICKER_CFG['current_k']}, stop={TICKER_CFG['current_stop_mult']}×ATR, cool={TICKER_CFG['current_cooldown']}d")
    print(f"  │   得分={m_cur['score']:.2f} | 交易={m_cur['total_trades']}笔 | 胜率={m_cur['win_rate']*100:.1f}% | 期望={m_cur['expectancy']:+.2f}% | PF={m_cur['pf']:.2f}")
    print(f"  │")
    print(f"  │ 最优参数: k={best_k:.2f}, stop={best_stop:.2f}×ATR, cool={best_cool}d")
    print(f"  │   得分={best_score:.2f} | 交易={m_best['total_trades']}笔 | 胜率={m_best['win_rate']*100:.1f}% | 期望={m_best['expectancy']:+.2f}% | PF={m_best['pf']:.2f}")
    print(f"  │   得分变化: {best_score - m_cur['score']:+.2f}")
    print(f"  ├{'─'*70}┤")
    print(f"  │ 最优参数详细:")
    print(f"  │   胜率:       {m_best['win_rate']*100:.1f}%")
    print(f"  │   期望值:     {m_best['expectancy']:+.2f}%")
    print(f"  │   累计收益:   {m_best['total_return']:+.1f}%")
    print(f"  │   盈亏比:     {m_best['pf']:.2f}")
    print(f"  │   平均盈利:   {m_best['avg_win']:+.2f}%")
    print(f"  │   平均亏损:   {m_best['avg_loss']:+.2f}%")
    print(f"  │   命中率(HR): {m_best['hr']*100:.1f}%")
    print(f"  │   最大连亏:   {m_best['max_consec']}笔")
    print(f"  │   止损次数:   {m_best['stop_count']}")
    print(f"  └{'─'*70}┘")

    # Top 20
    valid = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    valid.sort(key=lambda t: t.value, reverse=True)
    print(f"\n  🏆 Top 20 参数组合:")
    print(f"  {'排名':<5} {'k':<7} {'stop':<7} {'cool':<6} {'得分':<9} {'胜率':<7} {'期望':<8} {'交易':<5} {'PF':<7}")
    print(f"  {'-'*65}")
    for i, t in enumerate(valid[:20]):
        k = t.params['k']
        s = t.params['stop_mult']
        c = t.params['cooldown_days']
        wr = t.user_attrs.get('win_rate', 0)
        ex = t.user_attrs.get('expectancy', 0)
        tr = t.user_attrs.get('total_trades', 0)
        pf = t.user_attrs.get('pf', 0)
        pf_str = f"{pf:.2f}" if pf != float('inf') else "∞"
        print(f"  {i+1:<5} {k:<7.2f} {s:<7.2f} {c:<6} {t.value:<9.2f} {wr*100:<6.1f}% {ex:<7.2f}% {tr:<5} {pf_str:<7}")

    # 参数敏感性分析
    print(f"\n  📐 参数敏感性（固定两个维度，看第三个的影响）:")
    for param_name, param_key, current_val, best_val in [
        ('k', 'k', TICKER_CFG['current_k'], best_k),
        ('stop_mult', 'stop_mult', TICKER_CFG['current_stop_mult'], best_stop),
        ('cooldown', 'cooldown_days', TICKER_CFG['current_cooldown'], best_cool),
    ]:
        # 找到该参数维度上得分最高的5个试验
        by_param = sorted(valid, key=lambda t: abs(t.params[param_key] - best_val))
        print(f"  {param_name} 最优附近 (best={best_val:.2f}):")
        seen = set()
        for t in by_param[:5]:
            val = t.params[param_key]
            if val in seen: continue
            seen.add(val)
            wr = t.user_attrs.get('win_rate', 0)
            print(f"    {param_name}={val:.2f} → 得分={t.value:.2f} | 胜率={wr*100:.1f}% | 交易={t.user_attrs.get('total_trades',0)}笔")

    # 裁决
    print(f"\n  {'='*80}")
    print(f"  ⚡ 参数修正提案（修改权在守东）:\n")

    k_changed = abs(best_k - TICKER_CFG['current_k']) >= 0.3
    s_changed = abs(best_stop - TICKER_CFG['current_stop_mult']) >= 0.3
    c_changed = abs(best_cool - TICKER_CFG['current_cooldown']) >= 5

    if k_changed or s_changed or c_changed:
        print(f"  🔴 建议修正:")
        if k_changed:
            d = '↑' if best_k > TICKER_CFG['current_k'] else '↓'
            print(f"     k: {TICKER_CFG['current_k']} → {best_k:.2f} {d}")
        if s_changed:
            d = '↑' if best_stop > TICKER_CFG['current_stop_mult'] else '↓'
            print(f"     stop_mult: {TICKER_CFG['current_stop_mult']} → {best_stop:.2f} {d}")
        if c_changed:
            d = '↑' if best_cool > TICKER_CFG['current_cooldown'] else '↓'
            print(f"     cooldown: {TICKER_CFG['current_cooldown']} → {best_cool} {d}")
        print(f"     得分改善: {best_score - m_cur['score']:+.2f}")
        print(f"     → {'🟢建议修正' if best_score - m_cur['score'] > 2 else '🟡观察'}")
    else:
        print(f"  🟢 当前参数已处于最优区间，无需修正")

    print(f"\n  {'='*80}")
    print(f"  ⚠️ 以上为Optuna自动搜索结果，修改权在守东。任何参数变更需守东明确确认。")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--trials', type=int, default=N_TRIALS)
    p.add_argument('--quiet', action='store_true')
    args = p.parse_args()
    N_TRIALS = args.trials
    run()
