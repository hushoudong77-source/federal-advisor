#!/usr/bin/env python3
"""
美股进攻策略 C2 量能条件 — 三方案对照回测
=============================================
问题：量能作为开火前置条件是否合适？（守东 2026-08-19 质疑）

真回测：用 TickFlow 历史日线完整复刻美股进攻策略（QQQ/IVV/MUFG/BOTZ）
的 C1-C4 判定 + 逐标止损/止盈，对比三种 C2 方案：

  方案 A（现状）: C2 = 量比 > 1.2  （放量确认）
  方案 B      : C2 = 量比 < 0.8  （缩量回踩）
  方案 C      : C2 = 不设量能条件（只用 C1 ∧ C4）

框架复刻（fire_signal.py compute_offense_us）:
  C1: 现价 < MA20
  C4: 现价 ≤ H20 × 0.98
  C3: 宏观（LLM层，回测中恒 True）
  triggered = C1 ∧ C2 ∧ C3 ∧ C4

止损逐标独立（params.json us_offensive）:
  QQQ=8.0×ATR / IVV=2.0×ATR / MUFG=7.0×ATR / BOTZ=2.0×ATR

止盈逐标独立（params.json）:
  QQQ = 动态回撤（浮盈≥+20%激活，从峰值回撤2.5×ATR）
  IVV = 仅止损
  MUFG = 固定+50%
  BOTZ = 仅止损

回测口径：
  - 入场价 = 触发日次日开盘价（避免未来函数）
  - 逐日检查止损/止盈，触发即离场（次日开盘成交）
  - 每笔等权 1 单位，累计复利收益
  - 冷却期已废除（r33.68），仅加仓过热约束，回测中不限制入场频率

数据源：TickFlow SDK（adjust="none" 不复权真实成交价）
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from self_heal import ensure_tickflow
    ensure_tickflow()
except Exception:
    pass
from tickflow import TickFlow
import pandas as pd
import numpy as np

TICKFLOW_API_KEY = os.environ.get("TICKFLOW_API_KEY", "")

# 逐标参数（与 params.json us_offensive 一致）
STOP_MULT = {"QQQ": 8.0, "IVV": 2.0, "MUFG": 7.0, "BOTZ": 2.0}
TAKE_PROFIT = {
    "QQQ": {"type": "dynamic_drawdown", "activation": 0.20, "dd_mult": 2.5},
    "IVV": {"type": "stop_only"},
    "MUFG": {"type": "fixed", "threshold": 0.50},
    "BOTZ": {"type": "stop_only"},
}
C4_FACTOR = 0.98

TICKERS = ["QQQ", "IVV", "MUFG", "BOTZ"]


def fetch_ohlcv(tf, sym):
    """拉取单标历史日线（不复权）。"""
    df = tf.klines.get(sym, period="1d", count=10000, adjust="none", as_dataframe=True)
    if df is None or len(df) == 0:
        return None
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def add_indicators(df):
    """复刻 market_data.py 的指标计算（向量化）。"""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    df["ma20"] = close.rolling(20).mean()
    df["h20"] = close.rolling(20).max()

    # ATR14（Wilder）
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14).mean()

    # 量比 = 当日量 / 20日均量
    df["vol_ma20"] = volume.rolling(20).mean()
    df["vol_ratio"] = volume / df["vol_ma20"]

    return df


def run_backtest(ticker, df, c2_mode):
    """运行单一 C2 方案回测。返回交易列表。"""
    stop_mult = STOP_MULT[ticker]
    tp = TAKE_PROFIT[ticker]

    trades = []
    i = 20  # 从 MA20/H20 可用开始
    n = len(df)

    while i < n - 1:
        # 触发日 i 的判定
        price = df["close"].iloc[i]  # 用收盘价判定（与 fire_signal 用现价一致，回测用收盘近似）
        ma20 = df["ma20"].iloc[i]
        h20 = df["h20"].iloc[i]
        atr = df["atr14"].iloc[i]
        vol_ratio = df["vol_ratio"].iloc[i]

        if pd.isna(ma20) or pd.isna(h20) or pd.isna(atr):
            i += 1
            continue

        c4 = h20 * C4_FACTOR
        c1 = price < ma20
        c4_cond = price <= c4

        if c2_mode == "A":
            c2 = vol_ratio > 1.2
        elif c2_mode == "B":
            c2 = vol_ratio < 0.8
        elif c2_mode == "C":
            c2 = True
        else:
            c2 = True

        if not (c1 and c2 and c4_cond):
            i += 1
            continue

        # 触发 → 次日开盘入场
        entry_idx = i + 1
        if entry_idx >= n:
            break
        entry_price = df["open"].iloc[entry_idx]
        if pd.isna(entry_price) or entry_price <= 0:
            i += 1
            continue

        stop_loss = entry_price - stop_mult * atr
        # 止盈初始化
        peak = entry_price
        dynamic_active = False
        fixed_tp_price = None
        if tp["type"] == "fixed":
            fixed_tp_price = entry_price * (1 + tp["threshold"])

        exit_price = None
        exit_idx = None
        exit_reason = None

        # 从入场次日起逐日检查
        j = entry_idx + 1
        while j < n:
            c = df["close"].iloc[j]
            h = df["high"].iloc[j]
            l = df["low"].iloc[j]
            atr_j = df["atr14"].iloc[j]

            # 止损（盘中低点触及）
            if l <= stop_loss:
                exit_price = stop_loss
                exit_idx = j
                exit_reason = "止损"
                break

            # 止盈
            if tp["type"] == "fixed" and fixed_tp_price:
                if h >= fixed_tp_price:
                    exit_price = fixed_tp_price
                    exit_idx = j
                    exit_reason = "固定止盈"
                    break
            elif tp["type"] == "dynamic_drawdown":
                # 更新峰值
                if c > peak:
                    peak = c
                # 激活
                if not dynamic_active and peak >= entry_price * (1 + tp["activation"]):
                    dynamic_active = True
                if dynamic_active and not pd.isna(atr_j):
                    dd_line = peak - tp["dd_mult"] * atr_j
                    if l <= dd_line:
                        exit_price = dd_line
                        exit_idx = j
                        exit_reason = "动态回撤止盈"
                        break
            # stop_only: 无止盈

            j += 1

        # 未触发离场 → 持有至最后，用最后收盘价结算
        if exit_price is None:
            exit_idx = n - 1
            exit_price = df["close"].iloc[exit_idx]
            exit_reason = "持有到期"

        ret = exit_price / entry_price - 1
        hold_days = exit_idx - entry_idx

        trades.append({
            "entry_date": str(df["trade_date"].iloc[entry_idx]),
            "entry_price": round(entry_price, 4),
            "exit_date": str(df["trade_date"].iloc[exit_idx]),
            "exit_price": round(exit_price, 4),
            "return": round(ret * 100, 2),
            "reason": exit_reason,
            "hold_days": hold_days,
        })

        # 跳转到离场日之后继续扫描
        i = exit_idx + 1

    return trades


def summarize(ticker, trades):
    if not trades:
        return {"ticker": ticker, "n": 0, "win_rate": None, "avg": None,
                "cum": 0.0, "max_win": None, "max_loss": None, "profit_factor": None}
    rets = [t["return"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    cum = np.prod([1 + r / 100 for r in rets]) - 1
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float("inf")
    return {
        "ticker": ticker,
        "n": len(trades),
        "win_rate": round(len(wins) / len(rets) * 100, 1),
        "avg": round(sum(rets) / len(rets), 2),
        "cum": round(cum * 100, 2),
        "max_win": round(max(rets), 2),
        "max_loss": round(min(rets), 2),
        "profit_factor": round(pf, 2) if pf != float("inf") else "∞",
    }


def main():
    modes = {"A": "量比>1.2（放量·现状）", "B": "量比<0.8（缩量回踩）", "C": "不设量能（仅C1∧C4）"}

    tf = TickFlow(TICKFLOW_API_KEY)
    print("拉取 TickFlow 历史日线...")
    data = {}
    for t in TICKERS:
        df = fetch_ohlcv(tf, f"{t}.US")
        if df is None:
            print(f"  ⚠️ {t} 拉取失败")
            continue
        data[t] = add_indicators(df)
        print(f"  ✅ {t}: {len(df)} 行, {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}")

    print("\n" + "=" * 90)
    print("回测中（三方案 × 四标的）...")
    print("=" * 90)

    all_results = {m: {} for m in modes}

    for mode, label in modes.items():
        print(f"\n### 方案 {mode}: {label}")
        print(f"{'标的':<7}{'笔数':<6}{'胜率':<8}{'均收益':<9}{'累计':<10}{'最大盈':<9}{'最大亏':<9}{'盈亏比':<8}")
        print("-" * 70)
        for t in TICKERS:
            if t not in data:
                continue
            trades = run_backtest(t, data[t], mode)
            s = summarize(t, trades)
            all_results[mode][t] = {"summary": s, "trades": trades}
            pf = s["profit_factor"]
            print(f"{s['ticker']:<7}{s['n']:<6}"
                  f"{'-' if s['win_rate'] is None else str(s['win_rate'])+'%':<8}"
                  f"{'-' if s['avg'] is None else str(s['avg'])+'%':<9}"
                  f"{s['cum']:+.2f}%{'':<4}"
                  f"{'-' if s['max_win'] is None else str(s['max_win'])+'%':<9}"
                  f"{'-' if s['max_loss'] is None else str(s['max_loss'])+'%':<9}"
                  f"{pf:<8}")

    # 汇总对比
    print("\n\n" + "=" * 90)
    print("三方案汇总对比（四标的合并）")
    print("=" * 90)
    print(f"{'方案':<28}{'总笔数':<8}{'总胜率':<8}{'平均收益':<10}{'等权累计':<12}")
    print("-" * 70)
    for mode, label in modes.items():
        all_trades = []
        for t in TICKERS:
            if t in all_results[mode]:
                all_trades.extend(all_results[mode][t]["trades"])
        if not all_trades:
            print(f"{label:<28}{0:<8}{'-':<8}{'-':<10}{'-':<12}")
            continue
        rets = [x["return"] for x in all_trades]
        wins = [r for r in rets if r > 0]
        wr = len(wins) / len(rets) * 100
        avg = sum(rets) / len(rets)
        cum_eq = np.prod([1 + r / 100 for r in rets]) - 1
        print(f"{label:<28}{len(rets):<8}{wr:.1f}%{'':<3}{avg:+.2f}%{'':<4}{cum_eq:+.2f}%")

    # 保存结果
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "results": {m: {t: all_results[m][t]["summary"] for t in all_results[m]}
                       for m in modes}}
    out_path = os.path.join(os.path.dirname(__file__), "offense_c2_volume_result.json")
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
