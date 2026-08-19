#!/usr/bin/env python3
"""
📜 MUFG 深跌抄底精细化验证
签发：联邦投顾（资产审计官）

目的：回答两个问题
  1. MUFG 深跌抄底（从滚动高点回撤 N% 入场）去极端后的 +12.2%，
     是「真 alpha」还是「幸存者偏差 + 薄利」？
  2. 分年度拆解 + 胜率/盈亏比，判断策略是否值得当真。

策略定义（待验证）：
  - 入场触发：收盘价较「滚动高点(不含当日)」回撤 ≥ 15%
  - 入场时点：触发次日开盘价买入
  - 退出：固定持有 40 交易日 → 收盘价卖出（stop 版另跑）
  - 持仓中再次触发深跌信号：忽略（不叠加仓位，简化）
  - 冷却：不加（隔离深跌纯效应）

数据源：TickFlow 不复权日线（真源），MUFG 拉满 2000 条
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DIP_THRESHOLD = 0.15   # 深跌阈值 15%
HOLD_DAYS = 40         # 持有 40 交易日
STOP_PCT = 0.08        # 带止损版：跌破入场价 8%


def fetch(tf, symbol="MUFG.US", count=2000):
    df = tf.klines.get(symbol, period="1d", count=count, as_dataframe=True)
    df = df.sort_values("trade_date").reset_index(drop=True)
    for c in ["close", "open", "high", "low", "volume"]:
        df[c] = df[c].astype(float)
    return df


def run(df, use_stop=False):
    """深跌抄底回测。返回 trades 列表。"""
    close = df["close"].values
    open_ = df["open"].values
    dates = df["trade_date"].values
    n = len(df)

    # 滚动高点（不含当日）：前一日为止的最高收盘价
    rolling_high = np.full(n, np.nan)
    run_max = -np.inf
    for i in range(1, n):
        run_max = max(run_max, close[i - 1])
        rolling_high[i] = run_max

    trades = []
    i = 0
    while i < n - 1:
        # 触发条件：回撤 ≥ 15%
        if not np.isnan(rolling_high[i]) and rolling_high[i] > 0:
            dd = close[i] / rolling_high[i] - 1.0
            if dd <= -DIP_THRESHOLD:
                entry_idx = i + 1
                if entry_idx >= n:
                    break
                entry_price = open_[entry_idx]
                if np.isnan(entry_price) or entry_price <= 0:
                    i += 1
                    continue
                # 退出逻辑
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
                    # 数据尾部不够持有期
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
                # 持仓期间不重复触发，跳到退出日之后
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
    # 去极端：剔除单笔最大盈利
    sorted_rets = sorted(rets)
    excluded = sorted_rets[-1] if sorted_rets else 0.0
    trimmed = sorted_rets[:-1] if len(sorted_rets) > 1 else []

    # 累计（等权复利）
    equity = 1.0
    for r in rets:
        equity *= (1 + r)

    # 去极端累计
    equity_trim = 1.0
    for r in trimmed:
        equity_trim *= (1 + r)

    return {
        "n": len(rets),
        "win_rate": len(wins) / len(rets) if rets else 0,
        "avg_ret": np.mean(rets),
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": np.mean(losses) if losses else 0,
        "profit_loss_ratio": (np.mean(wins) / abs(np.mean(losses))) if losses else float("inf"),
        "max_win": max(rets),
        "max_loss": min(rets),
        "cum": equity - 1.0,
        "excluded": excluded,
        "cum_trim": equity_trim - 1.0,
    }


def yearly(trades):
    """分年度拆解"""
    if not trades:
        return {}
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
        out[y] = {
            "n": len(rets),
            "cum": cum - 1.0,
            "win_rate": sum(1 for r in rets if r > 0) / len(rets),
        }
    return out


def main():
    from tickflow import TickFlow
    tf = TickFlow(os.environ["TICKFLOW_API_KEY"])
    print(f"数据源: TickFlow 不复权 | 标的 MUFG.US | 深跌阈值 {DIP_THRESHOLD:.0%} | 持有 {HOLD_DAYS}天")
    df = fetch(tf)
    print(f"日线: {len(df)} 条 | {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}\n")

    for label, use_stop in [("无止损版", False), (f"带止损版({STOP_PCT:.0%})", True)]:
        trades = run(df, use_stop=use_stop)
        s = stats(trades)
        print(f"===== {label} =====")
        if s is None:
            print("  无交易\n")
            continue
        print(f"  总笔数: {s['n']}")
        print(f"  胜率: {s['win_rate']:.1%}")
        print(f"  平均收益: {s['avg_ret']:+.2%}")
        print(f"  平均盈利: {s['avg_win']:+.2%} | 平均亏损: {s['avg_loss']:+.2%}")
        print(f"  盈亏比: {s['profit_loss_ratio']:.2f}")
        print(f"  最大盈利: {s['max_win']:+.2%} | 最大亏损: {s['max_loss']:+.2%}")
        print(f"  累计(含极端): {s['cum']:+.2%}")
        print(f"  被剔除极端单笔: {s['excluded']:+.2%}")
        print(f"  累计(去极端): {s['cum_trim']:+.2%}")

        print(f"  --- 分年度 ---")
        for y, info in yearly(trades).items():
            print(f"    {y}: {info['n']:>2}笔 | 胜率{info['win_rate']:.0%} | 累计{info['cum']:+.2%}")
        print()


if __name__ == "__main__":
    main()
