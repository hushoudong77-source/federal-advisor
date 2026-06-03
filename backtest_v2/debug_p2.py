"""
debug_p2.py — 诊断单只标的 V1.2 引擎为何全负
"""
import sys
sys.path.insert(0, "/home/agent/cow/backtest_v2")

import pandas as pd
import numpy as np
from engine_core import TradingEngine, compute_backtest_result
from data_pipeline import load_all

raw = load_all("/home/agent/cow/data/v12_backtest")

# ============================================================
# 诊断 QQQ (最成熟的标的, 1718行, 2018-2025)
# ============================================================
symbol = "QQQ"
price_df = raw[symbol]
print(f"=== {symbol} 诊断 ===")
print(f"数据: {len(price_df)} 行, {price_df['date'].min().date()} ~ {price_df['date'].max().date()}")
print(f"价格范围: {price_df['close'].min():.1f} ~ {price_df['close'].max():.1f}")

# 用法典最优参数跑一遍
engine = TradingEngine(
    price_df,
    ma_period=20,
    atr_period=20,
    atr_mult=2.0,
    sell_k=2.0,
    abs_stop_pct=-0.07,
    cross_border=True,
    fixed_hold_days=None,
    symbol="QQQ",
)
trades, daily = engine.run()

print(f"\n总交易: {len(trades)}")
print(f"退出原因分布:")
for reason in ["SL2_STOP", "SL3_TIME", "SL4_CIRCUIT", "SL1_TAKE_PROFIT"]:
    count = sum(1 for t in trades if t.exit_reason == reason)
    if count > 0:
        print(f"  {reason}: {count}")

print(f"\n前15笔交易:")
for i, t in enumerate(trades[:15]):
    print(f"  {t.entry_date.date()} → {t.exit_date.date()} ({t.hold_days}d) "
          f"入场{t.entry_price:.2f} 出场{t.exit_price:.2f} "
          f"收益{t.return_after_cost:+.2f}% 原因:{t.exit_reason} "
          f"仓位:{t.entry_state.name}")

# 看收益率分布
returns = [t.return_after_cost for t in trades]
print(f"\n收益率: min={min(returns):.1f}% max={max(returns):.1f}% mean={np.mean(returns):.1f}%")
print(f"正收益: {sum(1 for r in returns if r>0)}/{len(returns)}")

# 看持有期
holds = [t.hold_days for t in trades]
print(f"持有期: min={min(holds)}d max={max(holds)}d mean={np.mean(holds):.0f}d")

# 检查: 止损触发频率
stops = [t for t in trades if t.exit_reason == "SL2_STOP"]
print(f"\n止损交易: {len(stops)}")
for t in stops[:10]:
    print(f"  {t.entry_date.date()} 入场{t.entry_price:.2f} → {t.exit_date.date()} 出场{t.exit_price:.2f} "
          f"收益{t.return_after_cost:+.2f}% {t.hold_days}d")

# 检查: 是否有盈利交易
wins = [t for t in trades if t.return_after_cost > 0]
print(f"\n盈利交易: {len(wins)}")
for t in wins[:10]:
    print(f"  {t.entry_date.date()} 入场{t.entry_price:.2f} → {t.exit_date.date()} 出场{t.exit_price:.2f} "
          f"收益{t.return_after_cost:+.2f}% {t.hold_days}d 原因:{t.exit_reason}")

# ─── 关键诊断: 买入区间是否合理 ───
print(f"\n=== 买入区间诊断 ===")
# 算一下 MA20 和 ATR 的典型值
ma20 = price_df["close"].rolling(20).mean()
atr = (price_df["high"] - price_df["low"]).rolling(20).mean()
print(f"MA20 范围: {ma20.min():.1f} ~ {ma20.max():.1f}")
print(f"ATR 范围: {atr.min():.1f} ~ {atr.max():.1f}")
print(f"买入区间下沿 (MA20-2.0×ATR) 范围: {(ma20-2*atr).min():.1f} ~ {(ma20-2*atr).max():.1f}")

# 检查: 有多少天收盘价在买入区间内?
in_zone = (price_df["close"] < ma20) & (price_df["close"] > ma20 - 2*atr)
print(f"在买入区间内的天数: {in_zone.sum()}/{len(price_df)} ({in_zone.sum()/len(price_df)*100:.1f}%)")

# 检查: 新冠崩盘期的买入触发
covid = price_df[(price_df["date"] >= "2020-02-19") & (price_df["date"] <= "2020-04-07")]
print(f"\n新冠期 (2020-02-19~04-07): {len(covid)} 天")
covid_trigger = covid[covid["close"] < covid["close"].shift(20).rolling(20).mean().shift(0)]
print(f"  跌破MA20 天数: 直接用引擎看")

# ─── 用引擎重新跑，看每日状态 ───
print(f"\n=== 每日状态抽样 (前20条有触发的) ===")
triggers = daily[daily["trigger"] != "NONE"]
print(f"有触发的天数: {len(triggers)}/{len(daily)}")
for _, row in triggers.head(30).iterrows():
    print(f"  {row['date'].date()} state=S{int(row['state'])} close={row['close']:.2f} "
          f"trigger={row['trigger']} ma={row['ma']:.2f} "
          f"zone=[{row['buy_zone_low']:.2f}, {row['buy_zone_high']:.2f}]")
