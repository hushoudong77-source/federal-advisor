#!/usr/bin/env python3
"""
止损→空仓→买入区间再入场 回测（全池版 + SOP §6.3 三段分割）
逻辑：
  初始持有 → 止损触发离场 → 空仓等待 → 买入区间重新满足 → 重新入场 → 循环
  反击标的买入区间: MA40−k×ATR（取close <= MA40即可，这是均值回归策略）
  固定层买入区间: MA60−k×ATR ~ MA60+2×ATR
用法:
  python3 scripts/stop_loss_reentry_full.py 513910 [--stop 3.5] [--start 20180101]
  python3 scripts/stop_loss_reentry_full.py 513910 --segment  # SOP §6.3 三段分割模式
      如果不指定--stop，使用params.json中的默认stop_mult
"""
import tushare as ts
import pandas as pd
import numpy as np
import argparse
import sys
import json

ts.set_token('d4a1352a19c1e52c5f1d0df8b7ef8f67ed9d27806c4aec64297ce426f7c5')
pro = ts.pro_api()

# 加载params.json
with open('/home/agent/cow/scripts/params.json') as f:
    PARAMS = json.load(f)

US_TICKERS = PARAMS['pool']['tushare_codes']
CN_TICKERS = {k: v for k, v in US_TICKERS.items() if v['type'] == 'fund_daily'}
US_TICKERS = {k: v for k, v in US_TICKERS.items() if v['type'] == 'us_daily'}

COUNTERPUNCH = PARAMS['counterpunch']
FIXED_LAYER = PARAMS['fixed_layer']


def fetch_data(ticker, start, end):
    if ticker in US_TICKERS:
        code = US_TICKERS[ticker]['code']
        df = pro.us_daily(ts_code=code, start_date=start, end_date=end)
    elif ticker in CN_TICKERS:
        code = CN_TICKERS[ticker]['code']
        df = pro.fund_daily(ts_code=code, start_date=start, end_date=end)
    else:
        print(f"❌ 未知标的: {ticker}")
        sys.exit(1)

    if df is None or len(df) == 0:
        print(f"❌ Tushare返回空数据: {ticker}")
        sys.exit(1)

    df = df.sort_values('trade_date').reset_index(drop=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])

    # ATR14
    df['TR'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['ATR14'] = df['TR'].rolling(14).mean().shift(1)

    # MA40（反击策略锚线）
    df['MA40'] = df['close'].rolling(40).mean()

    # MA60（固定层锚线）
    df['MA60'] = df['close'].rolling(60).mean()

    # 买入区间
    is_counterpunch = ticker in COUNTERPUNCH
    is_fixed = ticker in FIXED_LAYER

    if is_counterpunch:
        cfg = COUNTERPUNCH[ticker]
        df['buy_zone_upper'] = df['MA40'] - cfg['k'] * df['ATR14']
        df['buy_zone_lower'] = None  # 反击策略买入区间 = 只要 <= MA40−k×ATR 即可
    elif is_fixed:
        cfg = FIXED_LAYER[ticker]
        df['buy_zone_upper'] = df['MA60'] + 2.0 * df['ATR14']
        df['buy_zone_lower'] = df['MA60'] - cfg['k'] * df['ATR14']
    else:
        df['buy_zone_upper'] = None
        df['buy_zone_lower'] = None

    # 剔除前60行（MA60初始化窗口）
    df = df.iloc[60:].reset_index(drop=True)
    return df


def backtest_stop_reentry(df, stop_mult, ticker):
    """止损→空仓→买入区间再入 回测"""
    in_position = True
    entry_price = df.iloc[0]['close']
    trades = []
    empty_days = 0

    is_counterpunch = ticker in COUNTERPUNCH

    for i in range(1, len(df)):
        row = df.iloc[i]
        atr = row['ATR14']
        buy_upper = row['buy_zone_upper']

        if pd.isna(atr) or atr <= 0:
            continue

        if in_position:
            # 持有中 → 检查止损
            stop_price = entry_price - stop_mult * atr
            if row['low'] <= stop_price:
                exit_price = min(row['open'], stop_price)
                ret_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    'type': 'STOP',
                    'date': row['trade_date'].strftime('%Y%m%d'),
                    'entry': round(entry_price, 2),
                    'exit': round(exit_price, 2),
                    'ret': round(ret_pct, 2),
                })
                in_position = False

        else:
            # 空仓中 → 检查买入区间
            empty_days += 1
            if is_counterpunch:
                # 反击策略：现价 <= MA40−k×ATR 即进入买入区间
                if pd.notna(buy_upper) and row['close'] <= buy_upper:
                    if i + 1 < len(df):
                        entry_price = df.iloc[i + 1]['open']
                        in_position = True
            else:
                # 固定层：现价在买入区间内
                buy_low = row['buy_zone_lower']
                if pd.notna(buy_upper) and pd.notna(buy_low) and buy_low <= row['close'] <= buy_upper:
                    if i + 1 < len(df):
                        entry_price = df.iloc[i + 1]['open']
                        in_position = True

    # 如果最后仍持有，按最后收盘价平仓
    if in_position:
        final_ret = (df.iloc[-1]['close'] - entry_price) / entry_price * 100
        trades.append({
            'type': 'HOLD',
            'date': df.iloc[-1]['trade_date'].strftime('%Y%m%d'),
            'entry': round(entry_price, 2),
            'exit': round(df.iloc[-1]['close'], 2),
            'ret': round(final_ret, 2),
        })

    # 累计收益
    cum = 1.0
    for t in trades:
        cum *= (1 + t['ret'] / 100)
    cum_pct = (cum - 1) * 100

    return trades, cum_pct, empty_days


def compute_buy_and_hold(df):
    return (df.iloc[-1]['close'] - df.iloc[0]['close']) / df.iloc[0]['close'] * 100


def run(ticker, start='20140101', end='20260729', stop_mult=None):
    # 如果没有指定stop_mult，使用params.json中的默认值
    if stop_mult is None:
        if ticker in COUNTERPUNCH:
            stop_mult = COUNTERPUNCH[ticker]['stop_mult']
        elif ticker in FIXED_LAYER:
            stop_mult = FIXED_LAYER[ticker].get('k', 4.5)
        else:
            print(f"❌ {ticker} 不在counterpunch或fixed_layer中")
            sys.exit(1)

    df = fetch_data(ticker, start, end)
    bh_ret = compute_buy_and_hold(df)

    is_counterpunch = ticker in COUNTERPUNCH
    cfg = COUNTERPUNCH.get(ticker) or FIXED_LAYER.get(ticker, {})

    print(f"\n{'='*65}")
    print(f"  {ticker} 止损→空仓→买入区间再入场 回测")
    print(f"  数据: {len(df)}个交易日, {df.iloc[0]['trade_date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['trade_date'].strftime('%Y-%m-%d')}")
    print(f"  Buy & Hold: {bh_ret:+.1f}%")
    print(f"  止损倍数: {stop_mult}×ATR")
    if is_counterpunch:
        print(f"  策略: 反击  |  锚线: MA40  |  k={cfg['k']}  |  买入区间: ≤MA40−{cfg['k']}×ATR")
    else:
        print(f"  策略: 固定层  |  锚线: MA60  |  买入区间: [MA60−{cfg['k']}×ATR, MA60+2×ATR]")
    print(f"{'='*65}")

    trades, cum_pct, empty_days = backtest_stop_reentry(df, stop_mult, ticker)

    if not trades:
        print(f"  ⚠️ 无交易记录")
        return df, None

    stop_trades = [t for t in trades if t['type'] == 'STOP']
    hold_trade = [t for t in trades if t['type'] == 'HOLD']

    print(f"\n  📊 止损交易 ({len(stop_trades)}笔):")
    for t in stop_trades:
        print(f"     {t['date']} 入场${t['entry']:.2f} → 止损${t['exit']:.2f} ({t['ret']:+.1f}%)")

    if hold_trade:
        print(f"\n  📊 当前持有:")
        print(f"     {hold_trade[0]['date']} 入场${hold_trade[0]['entry']:.2f} → 现价${hold_trade[0]['exit']:.2f} ({hold_trade[0]['ret']:+.1f}%)")

    print(f"\n  📌 累计损益: {cum_pct:+.1f}%  (Buy & Hold: {bh_ret:+.1f}%)")
    print(f"  📌 止损笔数: {len(stop_trades)} | 空仓天数: ~{empty_days}")

    if len(stop_trades) > 0:
        stop_avg = np.mean([t['ret'] for t in stop_trades])
        stop_worst = min(t['ret'] for t in stop_trades)
        print(f"  📌 止损均亏: {stop_avg:+.1f}% | 最差: {stop_worst:+.1f}%")

    # 当前状态
    latest = df.iloc[-1]
    atr_now = latest['ATR14']
    print(f"\n  📊 当前:")
    print(f"     现价: ${latest['close']:.2f} | ATR14: ${atr_now:.2f}")
    if is_counterpunch:
        print(f"     MA40: ${latest['MA40']:.2f}" if pd.notna(latest['MA40']) else "     MA40: N/A")
        if pd.notna(atr_now) and pd.notna(latest['MA40']):
            buy_zone = latest['MA40'] - cfg['k'] * atr_now
            print(f"     买入区间: ≤${buy_zone:.2f}")
            print(f"     止损价({stop_mult}×ATR): ${latest['close'] - stop_mult * atr_now:.2f}")
    else:
        print(f"     MA60: ${latest['MA60']:.2f}" if pd.notna(latest['MA60']) else "     MA60: N/A")
        if pd.notna(atr_now) and pd.notna(latest['MA60']):
            buy_low = latest['MA60'] - cfg['k'] * atr_now
            buy_high = latest['MA60'] + 2.0 * atr_now
            print(f"     买入区间: [${buy_low:.2f}, ${buy_high:.2f}]")
            print(f"     止损价({stop_mult}×ATR): ${latest['close'] - stop_mult * atr_now:.2f}")

    print()
    return df, trades


def run_segment(ticker, start='20140101', end='20260729', stop_range=(1.0, 10.0, 0.5)):
    """SOP §6.3 三段分割回测：样本内选最优 → 样本外验证 → 全量对照"""
    df = fetch_data(ticker, start, end)
    N = len(df)
    split_idx = int(N * 0.7)
    split_date = df.iloc[split_idx]['trade_date'].strftime('%Y-%m-%d')

    df_train = df.iloc[:split_idx].reset_index(drop=True)
    df_test = df.iloc[split_idx:].reset_index(drop=True)

    is_counterpunch = ticker in COUNTERPUNCH
    cfg = COUNTERPUNCH.get(ticker) or FIXED_LAYER.get(ticker, {})
    default_stop = cfg.get('stop_mult', 2.0)

    print(f"\n{'='*70}")
    print(f"  {ticker} SOP §6.3 三段分割回测（止损→空仓→买入区间再入）")
    print(f"  全量: {N}个交易日, {df.iloc[0]['trade_date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['trade_date'].strftime('%Y-%m-%d')}")
    print(f"  分割点: {split_date} (前70%={len(df_train)}日 / 后30%={len(df_test)}日)")
    print(f"{'='*70}")

    # ─── 段一：样本内训练（前70%）───
    print(f"\n{'─'*70}")
    print(f"  📐 段一：样本内训练（前70%，~{df_train.iloc[0]['trade_date'].strftime('%Y-%m-%d')} ~ {split_date}）")
    print(f"{'─'*70}")

    stop_vals = np.arange(stop_range[0], stop_range[1] + stop_range[2]/2, stop_range[2])
    best_score = -999
    best_stop = default_stop
    train_results = []

    for stop_mult in stop_vals:
        stop_mult = round(stop_mult, 1)
        trades, cum_pct, empty_days = backtest_stop_reentry(df_train, stop_mult, ticker)
        stop_trades = [t for t in trades if t['type'] == 'STOP']
        win_trades = [t for t in trades if t['ret'] > 0]
        win_rate = len(win_trades) / len(trades) * 100 if trades else 0
        avg_ret = np.mean([t['ret'] for t in trades]) if trades else 0
        score = win_rate * 0.5 + cum_pct * 0.3 - len(stop_trades) * 2
        if cum_pct > best_score:
            best_score = cum_pct
            best_stop = stop_mult
        train_results.append({
            'stop': stop_mult, 'trades': len(trades), 'win_rate': round(win_rate, 1),
            'avg_ret': round(avg_ret, 2), 'cum': round(cum_pct, 1),
            'stops': len(stop_trades), 'score': round(score, 1)
        })

    # 打印样本内遍历表
    print(f"\n  {'止损':<6} {'交易':<6} {'胜率':<8} {'均收益':<8} {'累计':<10} {'止损笔':<7} {'得分':<6}")
    print(f"  {'─'*6} {'─'*6} {'─'*8} {'─'*8} {'─'*10} {'─'*7} {'─'*6}")
    for r in train_results:
        flag = ' ←最优' if r['stop'] == best_stop else ''
        print(f"  {r['stop']:<6.1f} {r['trades']:<6} {r['win_rate']:<8.1f}% {r['avg_ret']:<+8.2f}% {r['cum']:<+10.1f}% {r['stops']:<7} {r['score']:<6.1f}{flag}")

    # ─── 段二：样本外验证（后30%）───
    print(f"\n{'─'*70}")
    print(f"  📐 段二：样本外验证（后30%，~{split_date} ~ {df_test.iloc[-1]['trade_date'].strftime('%Y-%m-%d')}）")
    print(f"  候选参数: stop={best_stop}×ATR（样本内最优）")
    print(f"{'─'*70}")

    test_trades, test_cum, test_empty = backtest_stop_reentry(df_test, best_stop, ticker)
    test_stops = [t for t in test_trades if t['type'] == 'STOP']
    test_wins = [t for t in test_trades if t['ret'] > 0]
    test_win_rate = len(test_wins) / len(test_trades) * 100 if test_trades else 0
    test_avg_ret = np.mean([t['ret'] for t in test_trades]) if test_trades else 0

    # 打印样本外交易明细
    print(f"\n  📊 样本外交易 ({len(test_trades)}笔):")
    for t in test_trades:
        tag = 'STOP' if t['type'] == 'STOP' else 'HOLD'
        print(f"     {t['date']} [{tag}] 入场${t['entry']:.2f} → 退出${t['exit']:.2f} ({t['ret']:+.1f}%)")

    # ─── 段三：全量对照 ───
    print(f"\n{'─'*70}")
    print(f"  📐 段三：全量对照（100%）")
    print(f"{'─'*70}")

    full_trades, full_cum, full_empty = backtest_stop_reentry(df, best_stop, ticker)
    full_stops = [t for t in full_trades if t['type'] == 'STOP']
    full_wins = [t for t in full_trades if t['ret'] > 0]
    full_win_rate = len(full_wins) / len(full_trades) * 100 if full_trades else 0
    full_avg_ret = np.mean([t['ret'] for t in full_trades]) if full_trades else 0
    bh_ret = compute_buy_and_hold(df)

    # 找到样本内该stop_mult的结果
    train_best = [r for r in train_results if r['stop'] == best_stop][0]

    # ─── 汇总对比表 ───
    print(f"\n{'='*70}")
    print(f"  📊 三段汇总对比")
    print(f"{'='*70}")
    print(f"\n  {'指标':<15} {'样本内(70%)':<15} {'样本外(30%)':<15} {'全量(100%)':<15}")
    print(f"  {'─'*15} {'─'*15} {'─'*15} {'─'*15}")
    print(f"  {'止损参数':<15} {best_stop:<15.1f}×ATR {best_stop:<15.1f}×ATR {best_stop:<15.1f}×ATR")
    print(f"  {'交易笔数':<15} {train_best['trades']:<15} {len(test_trades):<15} {len(full_trades):<15}")
    print(f"  {'胜率':<15} {train_best['win_rate']:<14.1f}% {test_win_rate:<14.1f}% {full_win_rate:<14.1f}%")
    print(f"  {'平均收益':<15} {train_best['avg_ret']:<+14.2f}% {test_avg_ret:<+14.2f}% {full_avg_ret:<+14.2f}%")
    print(f"  {'累计收益':<15} {train_best['cum']:<+14.1f}% {test_cum:<+14.1f}% {full_cum:<+14.1f}%")
    print(f"  {'止损笔数':<15} {train_best['stops']:<15} {len(test_stops):<15} {len(full_stops):<15}")

    # ─── L4裁决 ───
    print(f"\n  🔬 L4 样本外衰减判定:")
    if len(test_trades) < 5:
        verdict = '🔴 否决 — 样本外交易<5笔，无法得出统计结论'
    else:
        decay = test_win_rate / train_best['win_rate'] if train_best['win_rate'] > 0 else 0
        decay_cum = test_cum / train_best['cum'] if train_best['cum'] > 0 else 0
        print(f"     胜率衰减: {train_best['win_rate']:.1f}% → {test_win_rate:.1f}% (比率={decay:.2f})")
        print(f"     累计衰减: {train_best['cum']:+.1f}% → {test_cum:+.1f}% (比率={decay_cum:.2f})")
        if decay >= 0.70:
            verdict = f'✅ 通过 — 样本外表现可接受（胜率衰减≤30%）'
        elif decay >= 0.50:
            verdict = f'🟡 警告 — 样本外衰减风险（胜率衰减{((1-decay)*100):.0f}%），提案降级'
        else:
            verdict = f'🔴 否决 — 候选参数疑似过拟合（胜率衰减{(1-decay)*100:.0f}%>50%）'

    print(f"     裁决: {verdict}")
    print(f"\n  📌 Buy & Hold: {bh_ret:+.1f}% | 止损→再入: {full_cum:+.1f}% | 当前stop_mult={default_stop}×ATR")

    return df, best_stop, verdict


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='止损→空仓→买入区间再入场 回测（全池版 + SOP §6.3三段分割）')
    parser.add_argument('ticker', help='标的代码')
    parser.add_argument('--stop', type=float, default=None, help='止损ATR倍数（默认使用params.json中的值）')
    parser.add_argument('--start', default='20140101', help='起始日期')
    parser.add_argument('--end', default='20260729', help='结束日期')
    parser.add_argument('--segment', action='store_true', help='SOP §6.3 三段分割回测模式')
    args = parser.parse_args()

    if args.segment:
        run_segment(args.ticker.upper(), args.start, args.end)
    else:
        run(args.ticker.upper(), args.start, args.end, args.stop)
