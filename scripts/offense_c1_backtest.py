#!/usr/bin/env python3
"""
📜 美股进攻策略 C1 锚线松紧回测
签发：联邦投顾（资产审计官）
目的：回测 C1 条件（现价 < MA60）锚线松紧对美股进攻策略绩效的影响

待验证命题：
  美股进攻策略 C1 强制「现价 < MA60」是否过度收紧信号？
  松绑 C1（MA40/MA20/取消C1）是「释放被埋没的进攻机会」还是「放进更多亏损单」？

策略定义（fire_signal.py 第137行）：
  C1: 现价 < MA线   (待测: MA60 现状 / MA40 / MA20 / 取消C1)
  C2: 量比 > 1.20
  C4: 现价 ≤ H20 × 0.98   (H20 = 前20日最高收盘价，不含当日)
  C3: 宏观事件 — 回测无法量化，恒真（与生产一致）

回测口径：
  - 数据源: TickFlow 不复权日线（真源）
  - 标的: QQQ / IVV / MUFG / BOTZ（美股进攻四标）
  - 历史: 每标 2000 条（约2018-08 至今 8年）
  - 开火: 四条件AND满足当日 → 次日开盘价买入
  - 退出: 固定持有N日后按收盘价卖出（无止损版，先隔离C1锚线纯效应）
          另跑带止损版(现价跌破入场价-X%)，两者对照
  - 仓位: 每笔等权 10%（单笔），复利累计
  - 冷却: 不加冷却（先隔离C1纯效应，冷却与C1正交）
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TICKERS = {
    "QQQ":  "QQQ.US",
    "IVV":  "IVV.US",
    "MUFG": "MUFG.US",
    "BOTZ": "BOTZ.US",
}

C4_FACTOR = 0.98
VOL_THRESHOLD = 1.2
HOLD_DAYS = 20          # 固定持有20交易日
STOP_PCT = 0.08         # 带止损版：跌破入场价8%止损

# C1 口径定义
C1_VARIANTS = {
    "MA60_现状": "MA60",
    "MA40":      "MA40",
    "MA20":      "MA20",
    "取消C1":    None,
}


def fetch(tf, symbol, count=2000):
    df = tf.klines.get(symbol, period="1d", count=count, as_dataframe=True)
    if df is None or len(df) == 0:
        return None
    df = df.sort_values("trade_date").reset_index(drop=True)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    return df


def add_indicators(df):
    df = df.copy()
    for p in [20, 40, 60]:
        df[f"MA{p}"] = df["close"].rolling(p).mean()
    df["VOL_MA20"] = df["volume"].rolling(20).mean()
    df["H20"] = df["close"].rolling(20).max().shift(1)  # 前20日最高，不含当日
    df["vol_ratio"] = df["volume"] / df["VOL_MA20"]
    return df


def run_backtest(df, c1_ma, use_stop=False):
    """
    返回: (trades, stats)
    trades: list of dict(entry_date, entry_price, exit_date, exit_price, ret)
    """
    df = df.reset_index(drop=True)
    n = len(df)
    trades = []

    i = 60  # 从第60根开始（保证MA60初始化）
    while i < n - 1:
        row = df.loc[i]
        price = row["close"]
        h20 = row["H20"]
        vol_ratio = row["vol_ratio"]
        ma60 = row["MA60"]

        if pd.isna(h20) or pd.isna(vol_ratio) or pd.isna(ma60):
            i += 1
            continue

        c4 = h20 * C4_FACTOR

        # C1
        if c1_ma is None:
            c1 = True
        else:
            ma_val = row[c1_ma]
            if pd.isna(ma_val):
                i += 1
                continue
            c1 = price < ma_val

        # C2
        c2 = vol_ratio > VOL_THRESHOLD
        # C4
        c4_met = price <= c4

        if c1 and c2 and c4_met:
            entry_idx = i + 1
            if entry_idx >= n:
                break
            entry_price = df.loc[entry_idx, "open"]  # 次日开盘买入
            if pd.isna(entry_price) or entry_price <= 0:
                i += 1
                continue

            # 持有逻辑
            exit_idx = None
            exit_price = None
            exit_reason = None
            if use_stop:
                stop_price = entry_price * (1 - STOP_PCT)
                j = entry_idx + 1
                while j < n:
                    lo = df.loc[j, "low"]
                    cl = df.loc[j, "close"]
                    if not pd.isna(lo) and lo <= stop_price:
                        exit_idx = j
                        exit_price = stop_price
                        exit_reason = "止损"
                        break
                    if j - entry_idx >= HOLD_DAYS:
                        exit_idx = j
                        exit_price = cl
                        exit_reason = "到期"
                        break
                    j += 1
                if exit_idx is None:
                    exit_idx = n - 1
                    exit_price = df.loc[exit_idx, "close"]
                    exit_reason = "期末"
            else:
                exit_idx = entry_idx + HOLD_DAYS
                if exit_idx >= n:
                    exit_idx = n - 1
                exit_price = df.loc[exit_idx, "close"]
                exit_reason = "到期"

            if pd.isna(exit_price) or exit_price <= 0 or pd.isna(entry_price):
                i += 1
                continue

            ret = exit_price / entry_price - 1.0
            trades.append({
                "entry_date": str(df.loc[entry_idx, "trade_date"]),
                "entry_price": round(float(entry_price), 4),
                "exit_date": str(df.loc[exit_idx, "trade_date"]),
                "exit_price": round(float(exit_price), 4),
                "exit_reason": exit_reason,
                "ret": round(float(ret), 6),
            })
            i = exit_idx + 1  # 退出后再找下一信号
        else:
            i += 1

    return trades


def stats(trades):
    if not trades:
        return {"n": 0, "win_rate": None, "cum": 0.0, "avg_ret": None,
                "max_dd": 0.0, "max_win": None, "max_loss": None}
    rets = np.array([t["ret"] for t in trades])
    cum = float(np.prod(1 + rets) - 1)
    equity = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    max_dd = float(dd.min())
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    return {
        "n": len(trades),
        "win_rate": round(float((rets > 0).mean()) * 100, 2),
        "cum": round(cum * 100, 2),
        "avg_ret": round(float(rets.mean()) * 100, 2),
        "max_dd": round(max_dd * 100, 2),
        "max_win": round(float(wins.max()) * 100, 2) if len(wins) else None,
        "max_loss": round(float(losses.min()) * 100, 2) if len(losses) else None,
    }


def main():
    from tickflow import TickFlow
    tf = TickFlow(os.environ["TICKFLOW_API_KEY"])

    print("=" * 72)
    print("📜 美股进攻策略 C1 锚线松紧回测")
    print(f"   标的: {list(TICKERS.keys())} | 数据源: TickFlow 不复权")
    print(f"   C4: H20×{C4_FACTOR} | C2: 量比>{VOL_THRESHOLD} | 持有{HOLD_DAYS}日")
    print("=" * 72)

    results = {}  # variant -> ticker -> trades

    for ticker, symbol in TICKERS.items():
        df = fetch(tf, symbol)
        if df is None:
            print(f"\n⚠️ {ticker} 数据拉取失败，跳过")
            continue
        df = add_indicators(df)
        print(f"\n📊 {ticker} ({symbol}) 数据: {len(df)}条 "
              f"[{df['trade_date'].min()} ~ {df['trade_date'].max()}]")

        for vname, c1_ma in C1_VARIANTS.items():
            for stop_flag, stop_label in [(False, "无止损"), (True, f"止损{int(STOP_PCT*100)}%")]:
                trades = run_backtest(df, c1_ma, use_stop=stop_flag)
                s = stats(trades)
                key = (vname, stop_label)
                results.setdefault(key, {})[ticker] = s

                print(f"  {vname:<8} {stop_label:<6} | 笔数={s['n']:>3} "
                      f"胜率={s['win_rate'] if s['win_rate'] is not None else '—':>6}% "
                      f"累计={s['cum']:>8}% "
                      f"均盈亏={s['avg_ret'] if s['avg_ret'] is not None else '—':>7}% "
                      f"最大回撤={s['max_dd']:>7}%")

    # ============================================================
    # L4 样本外校验（70/30 时间分割）
    # 前70%训练 / 后30%样本外。通过标准：样本外胜率 ≥ 样本内×0.70 且 样本外≥5笔
    # ============================================================
    print("\n" + "=" * 72)
    print("🛡️ L4 样本外校验（70/30 时间分割，无止损口径）")
    print("=" * 72)
    l4_results = {}
    for ticker, symbol in TICKERS.items():
        df = fetch(tf, symbol)
        if df is None:
            continue
        df = add_indicators(df)
        n = len(df)
        split = int(n * 0.70)
        df_in = df.iloc[:split].reset_index(drop=True)
        df_out = df.iloc[split:].reset_index(drop=True)
        for vname, c1_ma in C1_VARIANTS.items():
            tr_in = run_backtest(df_in, c1_ma, use_stop=False)
            tr_out = run_backtest(df_out, c1_ma, use_stop=False)
            s_in = stats(tr_in)
            s_out = stats(tr_out)
            l4_results[(ticker, vname)] = (s_in, s_out)

    # 汇总判定
    print(f"\n{'标的':<6}{'C1口径':<10}{'样本内笔数/胜率':<18}{'样本外笔数/胜率':<18}{'判定':<8}")
    for ticker in TICKERS:
        for vname in C1_VARIANTS:
            s_in, s_out = l4_results.get((ticker, vname), (stats([]), stats([])))
            win_in = s_in["win_rate"]
            win_out = s_out["win_rate"]
            n_out = s_out["n"]
            if win_in is None or win_out is None or n_out < 5:
                verdict = "⚠️样本少"
            elif win_out >= win_in * 0.70:
                verdict = "✅通过"
            else:
                verdict = "🔴退化"
            wi = f"{s_in['n']}笔/{win_in}%" if win_in is not None else "—"
            wo = f"{s_out['n']}笔/{win_out}%" if win_out is not None else "—"
            print(f"{ticker:<6}{vname:<10}{wi:<18}{wo:<18}{verdict:<8}")

    # 汇总：四标合计（等权）
    print("\n" + "=" * 72)
    print("📌 四标合计（等权平均）")
    print("=" * 72)
    for stop_label in ["无止损", f"止损{int(STOP_PCT*100)}%"]:
        print(f"\n--- [{stop_label}] C1 口径对比 ---")
        for vname in C1_VARIANTS:
            agg = {}
            for ticker in TICKERS:
                if ticker in results.get((vname, stop_label), {}):
                    s = results[(vname, stop_label)][ticker]
                    agg["n"] = agg.get("n", 0) + s["n"]
                    agg["cum"] = agg.get("cum", 0.0) + s["cum"]
                    agg["dd"] = agg.get("dd", 0.0) + s["max_dd"]
            nt = max(len([t for t in TICKERS if t in results.get((vname, stop_label), {})]), 1)
            print(f"  {vname:<8} | 总笔数={agg.get('n',0):>4} "
                  f"累计合计={round(agg.get('cum',0.0),2):>9}% "
                  f"平均回撤={round(agg.get('dd',0.0)/nt,2):>7}%")

    # 输出 JSON 供追溯
    out = {"tickers": TICKERS, "results": {}}
    for (vname, stop_label), tickers_map in results.items():
        for ticker, s in tickers_map.items():
            out["results"].setdefault(f"{vname}|{stop_label}", {})[ticker] = s
    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "offense_c1_backtest.json")
    os.makedirs(os.path.dirname(outpath), exist_ok=True)
    with open(outpath, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已落盘: {outpath}")


if __name__ == "__main__":
    main()
