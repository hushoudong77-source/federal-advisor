"""
run_p2_t1.py — V1.2 P2 滚动前向验证 (T1 梯队)
==============================================
8只标的: QQQ, IVV, IAU, 510300, 518880, BBJP, EWY, 513910
每只标的: 5个滚动窗口 × 逐标参数网格 = 约5×7=35次/标的
总计约280次引擎运行，预计10-15分钟

参数网格: 围绕法典V20.56.27a逐标最优参数，±1~2步微调
"""

import sys
sys.path.insert(0, "/home/agent/cow/backtest_v2")

import pandas as pd
import numpy as np
from engine_core import TradingEngine, compute_backtest_result, BacktestResult
from data_pipeline import load_all, split_time
import warnings
warnings.filterwarnings("ignore")

# ============================================================
# T1 标的参数网格 (围绕法典 V20.56.27a 最优参数)
# ============================================================

T1_CONFIGS = {
    "QQQ": {
        "ma_options": [20],                # 法典最优: MA20
        "atr_mult_options": [1.5, 2.0, 2.5],  # 法典: 2.0, 上下微调
        "sell_k_options": [2.0, 2.5, 3.0],
        "abs_stop_pct": -0.07,
        "cross_border": True,
    },
    "IVV": {
        "ma_options": [20],
        "atr_mult_options": [3.0, 4.0, 5.0],  # 法典: 4.0
        "sell_k_options": [2.0, 2.5, 3.0],
        "abs_stop_pct": -0.07,
        "cross_border": True,
    },
    "IAU": {
        "ma_options": [10],                # 法典: MA10×1.0 (豁免标的不适用买入区间公式, 但V1.2仍需参数)
        "atr_mult_options": [0.5, 1.0, 1.5],
        "sell_k_options": [1.5, 2.0, 2.5],
        "abs_stop_pct": -0.07,
        "cross_border": True,
    },
    "510300": {
        "ma_options": [20],
        "atr_mult_options": [1.5, 2.0, 2.5],  # 法典: 2.0
        "sell_k_options": [2.0, 2.5, 3.0],
        "abs_stop_pct": -0.07,
        "cross_border": False,
    },
    "518880": {
        # 豁免标的, 沿用现有参数
        "ma_options": [30],
        "atr_mult_options": [3.0, 3.5, 4.0],  # 法典: 3.5
        "sell_k_options": [2.0, 2.5, 3.0],
        "abs_stop_pct": -0.07,
        "cross_border": False,
    },
    "BBJP": {
        "ma_options": [40],
        "atr_mult_options": [2.0, 2.5, 3.0],  # 法典: 2.5
        "sell_k_options": [2.0, 2.5, 3.0],
        "abs_stop_pct": -0.07,
        "cross_border": True,
    },
    "EWY": {
        "ma_options": [40],
        "atr_mult_options": [2.0, 3.0, 4.0],  # 法典: 3.0
        "sell_k_options": [2.0, 2.5, 3.0],
        "abs_stop_pct": -0.07,
        "cross_border": True,
    },
    "513910": {
        # 豁免标的 (数据不足, V1.2方法不可用)
        # 用现有数据做简单验证
        "ma_options": [60],
        "atr_mult_options": [3.5, 4.5, 5.5],  # 法典: 4.5
        "sell_k_options": [2.0, 2.5, 3.0],
        "abs_stop_pct": -0.07,
        "cross_border": False,  # 港股通, 按境内成本
    },
}

# 滚动窗口定义
TRAIN_CUTOFFS = [
    pd.Timestamp("2020-12-31"),
    pd.Timestamp("2021-12-31"),
    pd.Timestamp("2022-12-31"),
    pd.Timestamp("2023-06-30"),
    pd.Timestamp("2023-12-31"),
]

VAL_WINDOWS = [
    ("2021-01-01", "2022-01-01"),
    ("2022-01-01", "2023-01-01"),
    ("2023-01-01", "2024-01-01"),
    ("2023-07-01", "2024-07-01"),
    ("2024-01-01", "2025-01-01"),
]

TEST_WINDOW = ("2024-07-01", "2025-04-30")


def run_rolling_validation(symbol, config, price_df):
    """对单个标的在5个滚动窗口上运行参数网格"""
    results = []
    
    for ma in config["ma_options"]:
        for k in config["atr_mult_options"]:
            for sk in config["sell_k_options"]:
                params = (ma, k, sk)
                
                val_returns = []
                for window_idx, (val_start, val_end) in enumerate(VAL_WINDOWS):
                    val_df = price_df[
                        (price_df["date"] >= pd.Timestamp(val_start)) &
                        (price_df["date"] < pd.Timestamp(val_end))
                    ].copy()
                    
                    if len(val_df) < 60:  # 数据不足跳过
                        val_returns.append(np.nan)
                        continue
                    
                    try:
                        engine = TradingEngine(
                            val_df,
                            ma_period=ma,
                            atr_period=20,
                            atr_mult=k,
                            sell_k=sk,
                            abs_stop_pct=config["abs_stop_pct"],
                            cross_border=config["cross_border"],
                            fixed_hold_days=None,
                            symbol=symbol,
                        )
                        trades, daily = engine.run()
                        result = compute_backtest_result(trades, daily, symbol, ma, k, sk, config["abs_stop_pct"])
                        val_returns.append(result.total_return)
                    except Exception as e:
                        # DEBUG: 首次报错时输出
                        if window_idx == 0 and ma == config["ma_options"][0] and k == config["atr_mult_options"][0] and sk == config["sell_k_options"][0]:
                            print(f"  ⚠ 引擎异常: {e}")
                        val_returns.append(np.nan)
                
                # 计算验证集平均收益
                valid_returns = [r for r in val_returns if not np.isnan(r)]
                # DEBUG
                if ma == config["ma_options"][0] and k == config["atr_mult_options"][0] and sk == config["sell_k_options"][0]:
                    print(f"  DEBUG MA{ma}×{k} sk={sk}: val_returns={[f'{r:+.1f}%' if not np.isnan(r) else 'NaN' for r in val_returns]}, valid={len(valid_returns)}")
                if len(valid_returns) >= 2:
                    val_mean = np.mean(valid_returns)
                    val_std = np.std(valid_returns)
                    # 剔除异常波动 (std > 50%)
                    if val_std < 50:
                        results.append({
                            "symbol": symbol,
                            "ma": ma,
                            "k": k,
                            "sell_k": sk,
                            "val_mean_return": val_mean,
                            "val_std": val_std,
                            "val_n_windows": len(valid_returns),
                            "val_returns": val_returns,
                        })
    
    if not results:
        return results
    
    # 按验证集平均收益排序
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("val_mean_return", ascending=False)
    
    return results_df


def run_test_eval(symbol, best_params, price_df):
    """在 Test 集上评估最优参数"""
    test_start, test_end = TEST_WINDOW
    test_df = price_df[
        (price_df["date"] >= pd.Timestamp(test_start)) &
        (price_df["date"] < pd.Timestamp(test_end))
    ].copy()
    
    if len(test_df) < 60:
        return None
    
    config = T1_CONFIGS[symbol]
    engine = TradingEngine(
        test_df,
        ma_period=int(best_params["ma"]),
        atr_period=20,
        atr_mult=best_params["k"],
        sell_k=best_params["sell_k"],
        abs_stop_pct=config["abs_stop_pct"],
        cross_border=config["cross_border"],
        fixed_hold_days=None,
        symbol=symbol,
    )
    trades, daily = engine.run()
    result = compute_backtest_result(trades, daily, symbol, 
                                      int(best_params["ma"]), best_params["k"],
                                      best_params["sell_k"], config["abs_stop_pct"])
    return result


def main():
    print("=" * 70)
    print("V1.2 P2 滚动前向验证 — T1 梯队 (8只)")
    print("=" * 70)
    
    # 加载数据
    print("\n[1/3] 加载数据...")
    raw = load_all("/home/agent/cow/data/v12_backtest")
    
    summary_rows = []
    
    for symbol in T1_CONFIGS:
        print(f"\n{'─'*60}")
        print(f"[{symbol}] 开始 P2 验证...")
        
        if symbol not in raw:
            print(f"  ⚠ {symbol} 无数据, 跳过")
            continue
        
        price_df = raw[symbol]
        print(f"  数据: {len(price_df)} 行, "
              f"{price_df['date'].min().date()} ~ {price_df['date'].max().date()}")
        
        # 滚动验证
        val_results = run_rolling_validation(symbol, T1_CONFIGS[symbol], price_df)
        
        if val_results is None or len(val_results) == 0:
            print(f"  ❌ 无有效验证结果")
            continue
        
        # 最优参数
        best = val_results.iloc[0]
        print(f"  最优参数: MA{int(best['ma'])} × {best['k']} ATR, sell_k={best['sell_k']}")
        print(f"  Val 平均收益: {best['val_mean_return']:+.2f}% ± {best['val_std']:.2f}% "
              f"({int(best['val_n_windows'])}/5 窗口)")
        
        # Test 集评估
        test_result = run_test_eval(symbol, best, price_df)
        
        if test_result:
            print(f"  Test 集 ({TEST_WINDOW[0]}~{TEST_WINDOW[1]}):")
            print(f"    交易次数: {test_result.n_trades}")
            print(f"    胜率: {test_result.win_rate:.1%}")
            print(f"    总收益: {test_result.total_return:+.2f}%")
            print(f"    平均收益: {test_result.avg_return_cost:+.2f}%")
            print(f"    Calmar: {test_result.calmar:.2f}")
            print(f"    平均持有: {test_result.avg_hold_days:.0f}天")
            print(f"    年化交易: {test_result.annual_trades:.1f}次")
            
            # 判断是否通过 V1.2 验证
            passed = (test_result.total_return > 0 and 
                      test_result.calmar > 0.3 and
                      test_result.win_rate > 0.4)
            verdict = "✅ 通过" if passed else "❌ 未通过"
            
            summary_rows.append({
                "symbol": symbol,
                "best_ma": int(best["ma"]),
                "best_k": best["k"],
                "best_sell_k": best["sell_k"],
                "val_mean": best["val_mean_return"],
                "test_total": test_result.total_return,
                "test_win_rate": test_result.win_rate,
                "test_calmar": test_result.calmar,
                "test_n_trades": test_result.n_trades,
                "verdict": verdict,
                "passed": passed,
            })
        else:
            print(f"  ⚠ Test 集数据不足, 无法评估")
    
    # ─── 汇总 ───
    print("\n" + "=" * 70)
    print("T1 梯队 P2 验证汇总")
    print("=" * 70)
    
    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        print(f"\n{'标 的':<10} {'MAxk':<12} {'Val均值':>8} {'Test总收益':>10} "
              f"{'胜率':>8} {'Calmar':>8} {'交易':>5} {'判决':<10}")
        print("-" * 75)
        for _, row in summary_df.iterrows():
            print(f"{row['symbol']:<10} MA{int(row['best_ma'])}×{row['best_k']:<3.1f} "
                  f"{row['val_mean']:>7.1f}% {row['test_total']:>9.1f}% "
                  f"{row['test_win_rate']:>7.1%} {row['test_calmar']:>7.2f} "
                  f"{int(row['test_n_trades']):>4} {row['verdict']:<10}")
        
        passed_count = sum(1 for r in summary_rows if r["passed"])
        print(f"\n通过: {passed_count}/{len(summary_rows)}")
        
        # 保存结果
        pd.DataFrame(summary_rows).to_csv(
            "/home/agent/cow/backtest_v2/output/p2_t1_summary.csv", index=False
        )
        print("结果已保存至 output/p2_t1_summary.csv")
    
    print("\n✅ P2 T1 执行完成")


if __name__ == "__main__":
    main()
