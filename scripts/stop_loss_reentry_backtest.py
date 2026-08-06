#!/usr/bin/env python3
"""
止损→空仓→买入区间再入场 回测脚本
逻辑：
  初始持有 → 止损触发离场 → 空仓等待 → 买入区间重新满足 → 重新入场 → 循环
买入区间：VTI [MA60−4.5×ATR, MA60+2×ATR], VEA [MA60−4×ATR, MA60+2×ATR]
用法: python3 scripts/stop_loss_reentry_backtest.py VEA [--stop 8.5] [--start 20140101]
"""
import tushare as ts
import pandas as pd
import numpy as np
import argparse
import sys

ts.set_token('d4a1352a19c1e52c5f1d0df8b7ef8f67ed9d27806c4aec64297ce426f7c5')
pro = ts.pro_api()

# 买入区间参数
BUY_ZONE = {
    'VEA': {'k_low': 4.0, 'k_high': 2.0},   # MA60−4×ATR ~ MA60+2×ATR
    'VTI': {'k_low': 4.5, 'k_high': 2.0},   # MA60−4.5×ATR ~ MA60+2×ATR
}

US_TICKERS = {
    'VEA': 'VEA', 'VTI': 'VTI', 'QQQ': 'QQQ', 'IVV': 'IVV',
    'IAU': 'IAU', 'BBJP': 'BBJP', 'MUFG': 'MUFG', 'EWY': 'EWY',
    'VNM': 'VNM', 'FLIN': 'FLIN', 'SMIN': 'SMIN', 'BOTZ': 'BOTZ',
    'CANE': 'CANE', 'SGOV': 'SGOV'
}

CN_TICKERS = {
    '588000': '588000.SH', '513180': '513180.SH', '513910': '513910.SH',
    '510500': '510500.SH', '518880': '518880.SH', '512100': '512100.SH',
    '510880': '510880.SH', '159530': '159530.SZ', '510300': '510300.SH',
    '159915': '159915.SZ', '513770': '513770.SH', '159545': '159545.SZ'
}


def fetch_data(ticker, start, end):
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

    # MA60
    df['MA60'] = df['close'].rolling(60).mean()

    # 买入区间上下沿
    if ticker in BUY_ZONE:
        k_low = BUY_ZONE[ticker]['k_low']
        k_high = BUY_ZONE[ticker]['k_high']
        df['buy_low'] = df['MA60'] - k_low * df['ATR14']
        df['buy_high'] = df['MA60'] + k_high * df['ATR14']
    else:
        df['buy_low'] = None
        df['buy_high'] = None

    # 剔除前60行（MA60初始化窗口）
    df = df.iloc[60:].reset_index(drop=True)
    return df


def backtest_stop_reentry(df, stop_mult):
    """
    止损→空仓→买入区间再入 回测
    初始状态: 持有
    持有期间: 每日检查是否触发止损（low <= stop_price）
    空仓期间: 每日检查是否回到买入区间（close <= buy_high）
    """
    in_position = True
    entry_price = df.iloc[0]['close']
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        atr = row['ATR14']
        buy_low = row['buy_low']
        buy_high = row['buy_high']

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
            if pd.notna(buy_high) and row['close'] <= buy_high:
                # 现价在买入区间内 → 重新入场（次日开盘价）
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

    # 如果最后空仓，不计入（空仓期间无收益）
    return trades


def compute_buy_and_hold(df):
    return (df.iloc[-1]['close'] - df.iloc[0]['close']) / df.iloc[0]['close'] * 100


def run(ticker, start='20140101', end='20260729', stop_mult=8.5):
    df = fetch_data(ticker, start, end)
    bh_ret = compute_buy_and_hold(df)

    print(f"\n{'='*65}")
    print(f"  {ticker} 止损→空仓→买入区间再入场 回测")
    print(f"  数据: {len(df)}个交易日, {df.iloc[0]['trade_date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['trade_date'].strftime('%Y-%m-%d')}")
    print(f"  Buy & Hold: {bh_ret:+.1f}%")
    print(f"  止损倍数: {stop_mult}×ATR")
    if ticker in BUY_ZONE:
        print(f"  买入区间: MA60−{BUY_ZONE[ticker]['k_low']}×ATR ~ MA60+{BUY_ZONE[ticker]['k_high']}×ATR")
    print(f"{'='*65}")

    trades = backtest_stop_reentry(df, stop_mult)

    if not trades:
        print(f"  ⚠️ 无交易记录")
        return df, None

    # 分类统计
    stop_trades = [t for t in trades if t['type'] == 'STOP']
    hold_trade = [t for t in trades if t['type'] == 'HOLD']

    # 总累计 = 止损交易复利 × 最终持有收益
    cum = 1.0
    for t in stop_trades:
        cum *= (1 + t['ret'] / 100)
    if hold_trade:
        cum *= (1 + hold_trade[0]['ret'] / 100)
    cum_pct = (cum - 1) * 100

    # 总空仓天数
    total_days = len(df)
    holding_days = total_days  # 近似，精确计算需逐日统计

    print(f"\n  📊 止损交易 ({len(stop_trades)}笔):")
    for t in stop_trades:
        print(f"     {t['date']} 入场${t['entry']:.2f} → 止损${t['exit']:.2f} ({t['ret']:+.1f}%)")

    if hold_trade:
        print(f"\n  📊 当前持有:")
        print(f"     {hold_trade[0]['date']} 入场${hold_trade[0]['entry']:.2f} → 现价${hold_trade[0]['exit']:.2f} ({hold_trade[0]['ret']:+.1f}%)")

    print(f"\n  📌 累计损益: {cum_pct:+.1f}%  (Buy & Hold: {bh_ret:+.1f}%)")
    print(f"  📌 止损笔数: {len(stop_trades)} | 胜率: {sum(1 for t in stop_trades if t['ret']>0)/max(len(stop_trades),1)*100:.0f}%")

    if len(stop_trades) > 0:
        print(f"  📌 止损均亏: {np.mean([t['ret'] for t in stop_trades]):+.1f}% | 最差: {min(t['ret'] for t in stop_trades):+.1f}%")

    # 当前状态
    latest = df.iloc[-1]
    atr_now = latest['ATR14']
    print(f"\n  📊 当前:")
    print(f"     现价: ${latest['close']:.2f} | ATR14: ${atr_now:.2f}" if pd.notna(atr_now) else f"     现价: ${latest['close']:.2f}")
    print(f"     MA60: ${latest['MA60']:.2f}" if pd.notna(latest['MA60']) else "     MA60: N/A")
    if ticker in BUY_ZONE and pd.notna(atr_now) and pd.notna(latest['MA60']):
        buy_high = latest['MA60'] + BUY_ZONE[ticker]['k_high'] * atr_now
        buy_low = latest['MA60'] - BUY_ZONE[ticker]['k_low'] * atr_now
        print(f"     买入区间: [{buy_low:.2f}, {buy_high:.2f}]")
        print(f"     止损价({stop_mult}×ATR): ${latest['close'] - stop_mult * atr_now:.2f}")

    print()
    return df, trades


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='止损→空仓→买入区间再入场 回测')
    parser.add_argument('ticker', help='标的代码 (VEA, VTI)')
    parser.add_argument('--stop', type=float, default=8.5, help='止损ATR倍数')
    parser.add_argument('--start', default='20140101', help='起始日期')
    parser.add_argument('--end', default='20260729', help='结束日期')
    args = parser.parse_args()

    run(args.ticker.upper(), args.start, args.end, args.stop)
