#!/usr/bin/env python3
"""
通用止损参数回测脚本
用法: python3 scripts/stop_loss_backtest.py <ticker> [--range 1.0,10.0,0.5] [--start YYYYMMDD] [--end YYYYMMDD]
输出: 各止损倍数的全量回测绩效对比表 + 最优参数推荐
"""
import tushare as ts
import pandas as pd
import numpy as np
import argparse
import sys

ts.set_token('d4a1352a19c1e52c5f1d0df8b7ef8f67ed9d27806c4aec64297ce426f7c5')
pro = ts.pro_api()

# ── 美股代码映射 ──
US_TICKERS = {
    'VEA': 'VEA', 'VTI': 'VTI', 'QQQ': 'QQQ', 'IVV': 'IVV',
    'IAU': 'IAU', 'BBJP': 'BBJP', 'MUFG': 'MUFG', 'EWY': 'EWY',
    'VNM': 'VNM', 'FLIN': 'FLIN', 'SMIN': 'SMIN', 'BOTZ': 'BOTZ',
    'CANE': 'CANE', 'SGOV': 'SGOV'
}

# ── A股代码映射 ──
CN_TICKERS = {
    '588000': '588000.SH', '513180': '513180.SH', '513910': '513910.SH',
    '510500': '510500.SH', '518880': '518880.SH', '512100': '512100.SH',
    '510880': '510880.SH', '159530': '159530.SZ', '510300': '510300.SH',
    '159915': '159915.SZ', '513770': '513770.SH', '159545': '159545.SZ'
}


def fetch_data(ticker, start, end):
    """获取日线数据并计算ATR14"""
    if ticker in US_TICKERS:
        df = pro.us_daily(ts_code=US_TICKERS[ticker], start_date=start, end_date=end)
    elif ticker in CN_TICKERS:
        df = pro.fund_daily(ts_code=CN_TICKERS[ticker], start_date=start, end_date=end)
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

    # 剔除前14天（ATR计算窗口）
    df = df.iloc[14:].reset_index(drop=True)
    return df


def backtest_stop_loss(df, stop_mult, use_low=True):
    """
    止损回测：每笔以当日收盘价入场，止损=入场价-stop_mult*ATR14，触发即离场。
    下一交易日重新入场。
    use_low=True: 用当日最低价判断是否触发（更真实——止损可能盘中触发）
    """
    in_position = True
    entry_price = df.iloc[0]['close']
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        atr = row['ATR14']
        if pd.isna(atr) or atr <= 0:
            continue

        if in_position:
            stop_price = entry_price - stop_mult * atr
            trigger_price = row['low'] if use_low else row['close']

            if trigger_price <= stop_price:
                exit_price = min(row['open'], stop_price)  # 次日开盘执行
                ret_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    'exit_date': row['trade_date'].strftime('%Y%m%d'),
                    'entry_price': round(entry_price, 2),
                    'exit_price': round(exit_price, 2),
                    'ret_pct': round(ret_pct, 2)
                })
                in_position = False

        if not in_position:
            entry_price = row['close']
            in_position = True

    return trades


def compute_buy_and_hold(df):
    """计算Buy & Hold收益"""
    return (df.iloc[-1]['close'] - df.iloc[0]['close']) / df.iloc[0]['close'] * 100


def run(ticker, start='20140101', end='20260729', stop_range=None):
    if stop_range is None:
        stop_range = np.arange(1.0, 10.5, 0.5)

    df = fetch_data(ticker, start, end)
    bh_ret = compute_buy_and_hold(df)

    print(f"\n{'='*60}")
    print(f"  {ticker} 止损参数回测")
    print(f"  数据: {len(df)}个交易日, {df.iloc[0]['trade_date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['trade_date'].strftime('%Y-%m-%d')}")
    print(f"  Buy & Hold: {bh_ret:+.1f}%")
    print(f"{'='*60}")
    print(f"  {'倍数':>6s}  {'笔数':>4s}  {'胜率':>6s}  {'均收益':>8s}  {'累计':>8s}  {'最差':>7s}  {'连亏':>4s}")
    print(f"  {'─'*6}  {'─'*4}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*7}  {'─'*4}")

    best_cum = -999
    best_m = None

    for m in stop_range:
        trades = backtest_stop_loss(df, m)
        if not trades:
            print(f"  {m:6.1f}  {'0笔':>4s}  {'—':>6s}  {'—':>8s}  {'—':>8s}  {'—':>7s}  {'—':>4s}")
            continue

        rets = [t['ret_pct'] for t in trades]
        cum = np.prod([1 + r/100 for r in rets]) - 1
        cum_pct = cum * 100
        win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100
        avg_ret = np.mean(rets)
        max_dd = min(rets)

        # 最大连亏
        max_cons = 0
        cur = 0
        for r in rets:
            if r <= 0:
                cur += 1
                max_cons = max(max_cons, cur)
            else:
                cur = 0

        # 记录最优（累计收益最高）
        if cum_pct > best_cum:
            best_cum = cum_pct
            best_m = m

        print(f"  {m:6.1f}  {len(trades):4d}  {win_rate:5.0f}%  {avg_ret:+7.1f}%  {cum_pct:+7.1f}%  {max_dd:+6.1f}%  {max_cons:4d}")

    print(f"\n  📌 最优止损倍数: {best_m:.1f}×ATR (累计{best_cum:+.1f}%)")

    # 当前止损计算
    latest = df.iloc[-1]
    atr_now = latest['ATR14']
    price_now = latest['close']

    if best_m and not pd.isna(atr_now):
        # 用全量数据的ATR均值作为参考（而非单一最新值）
        atr_avg = df['ATR14'].tail(20).mean()
        print(f"\n  📊 当前参考:")
        print(f"     现价: ${price_now:.2f}")
        print(f"     ATR14(20日均): ${atr_avg:.2f}")
        print(f"     建议止损距: {best_m:.1f}×ATR = ${best_m * atr_avg:.2f}")
        print(f"     止损价(以现价计): ${price_now - best_m * atr_avg:.2f}")

    # 逐笔明细（最近5笔）
    if best_m:
        trades = backtest_stop_loss(df, best_m)
        if trades:
            print(f"\n  📋 最近5笔止损记录 ({best_m:.1f}×ATR):")
            for t in trades[-5:]:
                print(f"     {t['exit_date']} 入场${t['entry_price']:.2f} → 止损${t['exit_price']:.2f} ({t['ret_pct']:+.1f}%)")

    print()
    return df, best_m


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='通用止损参数回测')
    parser.add_argument('ticker', help='标的代码 (VEA, VTI, QQQ, 513910 等)')
    parser.add_argument('--start', default='20140101', help='起始日期 YYYYMMDD')
    parser.add_argument('--end', default='20260729', help='结束日期 YYYYMMDD')
    parser.add_argument('--range', default=None, help='止损倍数范围，格式: min,max,step (如 1.0,10.0,0.5)')
    args = parser.parse_args()

    if args.range:
        parts = [float(x) for x in args.range.split(',')]
        stop_range = np.arange(parts[0], parts[1] + parts[2]/2, parts[2])
    else:
        stop_range = np.arange(1.0, 10.5, 0.5)

    run(args.ticker.upper(), args.start, args.end, stop_range)
