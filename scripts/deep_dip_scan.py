#!/usr/bin/env python3
"""
📜 深跌抄底通用扫描（IVV / BOTZ）
签发：联邦投顾（资产审计官）

复用 mufg_deep_dip_dig.py 的同一套逻辑，对 IVV 和 BOTZ 做阈值遍历，
找到「从滚动高点回撤 N% 入场 + 8% 止损 + 持有40天」的最优阈值。

阈值候选：15% / 20% / 25% / 30%
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOLD_DAYS = 40
STOP_PCT = 0.08
THRESHOLDS = [0.15, 0.20, 0.25, 0.30]


def fetch(tf, symbol, count=2000):
    df = tf.klines.get(symbol, period="1d", count=count, as_dataframe=True)
    df = df.sort_values("trade_date").reset_index(drop=True)
    for c in ["close", "open", "high", "low", "volume"]:
        df[c] = df[c].astype(float)
    return df


def run(df, dip_threshold, use_stop=True):
    close = df["close"].values
    open_ = df["open"].values
    dates = df["trade_date"].values
    n = len(df)

    rolling_high = np.full(n, np.nan)
    run_max = -np.inf
    for i in range(1, n):
        run_max = max(run_max, close[i - 1])
        rolling_high[i] = run_max

    trades = []
    i = 0
    while i < n - 1:
        if not np.isnan(rolling_high[i]) and rolling_high[i] > 0:
            dd = close[i] / rolling_high[i] - 1.0
            if dd <= -dip_threshold:
                entry_idx = i + 1
                if entry_idx >= n:
                    break
                entry_price = open_[entry_idx]
                if np.isnan(entry_price) or entry_price <= 0:
                    i += 1
                    continue
                exit_price = None
                exit_idx = None
                exit_reason = "hold"
                stop_price = entry_price * (1 - STOP_PCT)
                j = entry_idx + 1
                while j < n:
                    if use_stop and df["low"].values[j] <= stop_price:
                        exit_price = stop_price
                        exit_idx = j
                        exit_reason = "stop"
                        break
                    if j - entry_idx >= HOLD_DAYS:
                        exit_price = close[j]
                        exit_idx = j
                        exit_reason = "hold"
                        break
                    j += 1
                if exit_price is None or exit_idx is None:
                    i += 1
                    continue
                ret = exit_price / entry_price - 1.0
                trades.append({
                    "entry_date": str(dates[entry_idx]),
                    "entry_price": round(float(entry_price), 4),
                    "exit_date": str(dates[exit_idx]),
                    "exit_price": round(float(exit_price), 4),
                    "ret": ret,
                    "reason": exit_reason,
                })
                i = exit_idx + 1
                continue
        i += 1
    return trades


def stats(trades):
    if not trades:
        return None
    rets = [t["ret"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    sorted_rets = sorted(rets)
    excluded = sorted_rets[-1] if sorted_rets else 0.0
    trimmed = sorted_rets[:-1] if len(sorted_rets) > 1 else []

    equity = 1.0
    for r in rets:
        equity *= (1 + r)
    equity_trim = 1.0
    for r in trimmed:
        equity_trim *= (1 + r)

    return {
        "n": len(rets),
        "win_rate": len(wins) / len(rets) if rets else 0,
        "avg_ret": np.mean(rets),
        "profit_loss_ratio": (np.mean(wins) / abs(np.mean(losses))) if losses else float("inf"),
        "max_win": max(rets),
        "max_loss": min(rets),
        "cum": equity - 1.0,
        "excluded": excluded,
        "cum_trim": equity_trim - 1.0,
    }


def yearly(trades):
    d = {}
    for t in trades:
        y = t["entry_date"][:4]
        d.setdefault(y, []).append(t["ret"])
    out = {}
    for y in sorted(d):
        rets = d[y]
        cum = 1.0
        for r in rets:
            cum *= (1 + r)
        out[y] = {"n": len(rets), "cum": cum - 1.0,
                  "win_rate": sum(1 for r in rets if r > 0) / len(rets)}
    return out


def main():
    from tickflow import TickFlow
    tf = TickFlow(os.environ["TICKFLOW_API_KEY"])

    for symbol in ["IVV.US", "BOTZ.US"]:
        print(f"{'=' * 70}")
        print(f"标的: {symbol} | 持有 {HOLD_DAYS}天 | 止损 {STOP_PCT:.0%} | 阈值遍历 {[f'{t:.0%}' for t in THRESHOLDS]}")
        print(f"{'=' * 70}")
        df = fetch(tf, symbol)
        print(f"日线: {len(df)} 条 | {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}\n")

        for th in THRESHOLDS:
            trades = run(df, th, use_stop=True)
            s = stats(trades)
            print(f"--- 阈值 {th:.0%} ---")
            if s is None:
                print("  无交易\n")
                continue
            print(f"  笔数: {s['n']} | 胜率: {s['win_rate']:.0%} | 盈亏比: {s['profit_loss_ratio']:.2f}")
            print(f"  平均收益: {s['avg_ret']:+.2%} | 最大盈: {s['max_win']:+.2%} | 最大亏: {s['max_loss']:+.2%}")
            print(f"  累计(含极端): {s['cum']:+.2%} | 剔除极端单笔: {s['excluded']:+.2%} | 累计(去极端): {s['cum_trim']:+.2%}")
            ydata = yearly(trades)
            ystr = " ".join(f"{y}:{info['n']}笔/{info['cum']:+.0%}" for y, info in ydata.items())
            print(f"  分年度: {ystr}")
            # 明细
            for t in trades:
                print(f"    {t['entry_date']} → {t['exit_date']} | {t['reason']:4s} | {t['ret']:+.2%}")
            print()
        print()


if __name__ == "__main__":
    main()
