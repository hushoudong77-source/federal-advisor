"""
run_p2_t1_v2.py — V1.2.1 改造版 P2 T1 对比验证
==============================================
对照设计:
  - 改造组: TradingEngineV2 (补丁A+B+C启用)
  - 对照组: TradingEngineV1 (原引擎，无改造)
  - 8只标的: QQQ, IVV, IAU, 510300, 518880, BBJP, EWY, 513910
  - 时间窗口: 2020-01-01 ~ 2025-04-30 (全量对比，不分Train/Val/Test)
  - 通过标准: Calmar>0 且胜率>35% 且相对对照组Calmar提升>0.3

冻结规格，不再变更。
"""

import sys
sys.path.insert(0, "/home/agent/cow/backtest_v2")

import pandas as pd
import numpy as np
from engine_core import TradingEngine, compute_backtest_result
from engine_core_v2 import TradingEngineV2
from data_pipeline import load_all
import warnings
warnings.filterwarnings("ignore")


# ============================================================
# T1 标的参数 (法典 V20.56.27a 逐标最优)
# ============================================================

T1_PARAMS = {
    "QQQ":     {"ma": 20, "k": 2.0, "sell_k": 2.0, "cross_border": True},
    "IVV":     {"ma": 20, "k": 4.0, "sell_k": 2.0, "cross_border": True},
    "IAU":     {"ma": 10, "k": 1.0, "sell_k": 2.0, "cross_border": True},
    "510300":  {"ma": 20, "k": 2.0, "sell_k": 2.0, "cross_border": False},
    "518880":  {"ma": 30, "k": 3.5, "sell_k": 2.0, "cross_border": False},
    "BBJP":    {"ma": 40, "k": 2.5, "sell_k": 2.0, "cross_border": True},
    "EWY":     {"ma": 40, "k": 3.0, "sell_k": 2.0, "cross_border": True},
    "513910":  {"ma": 60, "k": 4.5, "sell_k": 2.0, "cross_border": False},
}


def run_single(symbol, params, price_df, use_v2, fixed_hold_days=None):
    """运行单次引擎"""
    if use_v2:
        engine = TradingEngineV2(
            price_df,
            ma_period=params["ma"],
            atr_period=20,
            atr_mult=params["k"],
            sell_k=params["sell_k"],
            abs_stop_pct=-0.07,
            cross_border=params["cross_border"],
            fixed_hold_days=fixed_hold_days,
            symbol=symbol,
            enable_regime=True,
            enable_asymmetric=True,
        )
    else:
        engine = TradingEngine(
            price_df,
            ma_period=params["ma"],
            atr_period=20,
            atr_mult=params["k"],
            sell_k=params["sell_k"],
            abs_stop_pct=-0.07,
            cross_border=params["cross_border"],
            fixed_hold_days=fixed_hold_days,
            symbol=symbol,
        )
    trades, daily = engine.run()
    result = compute_backtest_result(
        trades, daily, symbol,
        params["ma"], params["k"], params["sell_k"], -0.07
    )
    return result


def main():
    print("=" * 80)
    print("V1.2.1 改造版 P2 T1 对比验证 — 补丁A+B+C vs 原始引擎")
    print("=" * 80)

    # 加载数据
    print("\n[1/3] 加载数据...")
    raw = load_all("/home/agent/cow/data/v12_backtest")

    # 时间窗口: 2020-01-01 ~ 2025-04-30
    FULL_START = "2020-01-01"
    FULL_END = "2025-04-30"

    results = []

    for symbol in T1_PARAMS:
        print(f"\n{'─' * 70}")
        print(f"[{symbol}] 开始对比验证...")

        if symbol not in raw:
            print(f"  ⚠ {symbol} 无数据, 跳过")
            continue

        price_df = raw[symbol]
        # 截取时间窗口
        price_df = price_df[
            (price_df["date"] >= pd.Timestamp(FULL_START)) &
            (price_df["date"] <= pd.Timestamp(FULL_END))
        ].copy()
        print(f"  数据: {len(price_df)} 行, "
              f"{price_df['date'].min().date()} ~ {price_df['date'].max().date()}")

        params = T1_PARAMS[symbol]

        # 对照组: V1 (无改造)
        print(f"  对照组(V1): MA{params['ma']}×{params['k']}...")
        try:
            result_v1 = run_single(symbol, params, price_df, use_v2=False)
            print(f"    V1: 交易{result_v1.n_trades}次 | 胜率{result_v1.win_rate:.1%} | "
                  f"总收益{result_v1.total_return:+.2f}% | Calmar {result_v1.calmar:.2f} | "
                  f"持有{result_v1.avg_hold_days:.0f}天")
        except Exception as e:
            print(f"    V1 ❌ 异常: {e}")
            result_v1 = None

        # 改造组: V2 (补丁A+B+C)
        print(f"  改造组(V2): MA{params['ma']}×{params['k']} + Regime + Asymmetric...")
        try:
            result_v2 = run_single(symbol, params, price_df, use_v2=True)
            print(f"    V2: 交易{result_v2.n_trades}次 | 胜率{result_v2.win_rate:.1%} | "
                  f"总收益{result_v2.total_return:+.2f}% | Calmar {result_v2.calmar:.2f} | "
                  f"持有{result_v2.avg_hold_days:.0f}天")
        except Exception as e:
            print(f"    V2 ❌ 异常: {e}")
            import traceback
            traceback.print_exc()
            result_v2 = None

        # 对比
        if result_v1 and result_v2:
            calmar_delta = result_v2.calmar - result_v1.calmar
            return_delta = result_v2.total_return - result_v1.total_return

            # 通过标准
            v2_passed = (
                result_v2.calmar > 0 and
                result_v2.win_rate >= 0.35 and
                calmar_delta > 0.3
            )

            results.append({
                "symbol": symbol,
                "v1_n_trades": result_v1.n_trades,
                "v1_win_rate": result_v1.win_rate,
                "v1_total_return": result_v1.total_return,
                "v1_calmar": result_v1.calmar,
                "v1_avg_hold": result_v1.avg_hold_days,
                "v2_n_trades": result_v2.n_trades,
                "v2_win_rate": result_v2.win_rate,
                "v2_total_return": result_v2.total_return,
                "v2_calmar": result_v2.calmar,
                "v2_avg_hold": result_v2.avg_hold_days,
                "calmar_delta": calmar_delta,
                "return_delta": return_delta,
                "v2_calmar_ok": result_v2.calmar > 0,
                "v2_winrate_ok": result_v2.win_rate >= 0.35,
                "delta_ok": calmar_delta > 0.3,
                "passed": v2_passed,
            })

            verdict = "✅ 通过" if v2_passed else "❌ 未通过"
            print(f"  对比: Calmar Δ={calmar_delta:+.2f} | 收益Δ={return_delta:+.1f}% | {verdict}")
        elif result_v2:
            results.append({
                "symbol": symbol,
                "v1_n_trades": None, "v1_win_rate": None, "v1_total_return": None,
                "v1_calmar": None, "v1_avg_hold": None,
                "v2_n_trades": result_v2.n_trades,
                "v2_win_rate": result_v2.win_rate,
                "v2_total_return": result_v2.total_return,
                "v2_calmar": result_v2.calmar,
                "v2_avg_hold": result_v2.avg_hold_days,
                "calmar_delta": None, "return_delta": None,
                "v2_calmar_ok": result_v2.calmar > 0,
                "v2_winrate_ok": result_v2.win_rate >= 0.35,
                "delta_ok": False,
                "passed": False,
            })

    # ─── 汇总 ───
    print("\n" + "=" * 80)
    print("T1 梯队 V1.2.1 改造对比汇总")
    print("=" * 80)

    if results:
        summary_df = pd.DataFrame(results)

        # 表头
        print(f"\n{'标的':<10} {'V1交易':>5} {'V1胜率':>7} {'V1收益':>8} {'V1Calmar':>8} "
              f"{'V2交易':>5} {'V2胜率':>7} {'V2收益':>8} {'V2Calmar':>8} "
              f"{'ΔCalmar':>8} {'Δ收益':>8} {'判决':<10}")
        print("-" * 95)
        for _, row in summary_df.iterrows():
            def fmt(x, spec):
                if pd.isna(x) or x is None:
                    return "N/A".rjust(len(spec) - 1) + " "
                return f"{x:{spec}}"
            v1_t = fmt(row['v1_n_trades'], '>5.0f') if row['v1_n_trades'] is not None else "  N/A "
            v1_wr = fmt(row['v1_win_rate'], '>6.1%') if row['v1_win_rate'] is not None else "  N/A "
            v1_tr = fmt(row['v1_total_return'], '>+7.1f') if row['v1_total_return'] is not None else "  N/A "
            v1_c = fmt(row['v1_calmar'], '>7.2f') if row['v1_calmar'] is not None else "  N/A "
            v2_t = f"{int(row['v2_n_trades']):>5d}" if not pd.isna(row['v2_n_trades']) else "  N/A "
            v2_wr = f"{row['v2_win_rate']:>6.1%}" if not pd.isna(row['v2_win_rate']) else "  N/A "
            v2_tr = f"{row['v2_total_return']:>+7.1f}%" if not pd.isna(row['v2_total_return']) else "  N/A "
            v2_c = f"{row['v2_calmar']:>7.2f}" if not pd.isna(row['v2_calmar']) else "  N/A "
            cd = f"{row['calmar_delta']:>+7.2f}" if row['calmar_delta'] is not None else "  N/A "
            rd = f"{row['return_delta']:>+7.1f}%" if row['return_delta'] is not None else "  N/A "
            vd = "✅ 通过" if row['passed'] else "❌ 未通过"
            print(f"{row['symbol']:<10} {v1_t} {v1_wr} {v1_tr} {v1_c} "
                  f"{v2_t} {v2_wr} {v2_tr} {v2_c} "
                  f"{cd} {rd} {vd:<10}")

        passed_count = sum(1 for r in results if r["passed"])
        print(f"\n通过: {passed_count}/{len(results)}")

        if passed_count >= 3:
            print("\n✅ 改造方向正确 — 建议立即全量跑 P0-P7")
        elif passed_count >= 1:
            print("\n🟡 改造部分有效 — 需追加补丁")
        else:
            print("\n🔴 改造无效 — 需重新审视策略方向")

        # 保存结果
        summary_df.to_csv("/home/agent/cow/backtest_v2/output/p2_t1_v2_comparison.csv", index=False)
        print("\n结果已保存至 output/p2_t1_v2_comparison.csv")

        # 保存详细结果 JSON
        import json
        detail_output = []
        for r in results:
            detail_output.append({
                k: (float(v) if isinstance(v, (np.floating, np.integer)) else
                    v.isoformat() if isinstance(v, pd.Timestamp) else v)
                for k, v in r.items()
            })
        with open("/home/agent/cow/backtest_v2/output/p2_t1_v2_detail.json", "w") as f:
            json.dump(detail_output, f, indent=2, default=str)

    print("\n✅ P2 T1 V2 对比验证完成")


if __name__ == "__main__":
    main()
