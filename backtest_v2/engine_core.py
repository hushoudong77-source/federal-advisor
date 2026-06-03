"""
engine_core.py — V1.2 冻结执行版 交易引擎核心
=============================================
硬规格（全部来自 V1.2 冻结方案）:
  - 四状态仓位机: S0(0%) / S1(33.3%) / S2(66.7%) / S3(100%)
  - 六级优先级: P1(宏观熔断) > P2(SL2止损) > P3(SL3时间退出) > P4(SL4熔断清仓) > P5(SL1止盈减仓) > P6(B1/B2/B3买入)
  - 单日单次转移 + 卖出优先 + 熔断覆盖
  - ATR 动态止损 (只上移不下调) + 绝对止损 (逐标)
  - 动态止盈跟踪线 (只上移不下调)
  - 时间衰减退出: 持有>=60日 -> 强制退出
  - 交易成本: 滑点+佣金+冲击成本(境内0.2%/跨境0.5%)
  - 止损冷却期: 连续3次止损 -> 休眠60日 (法典 V20.56.27a)

用法:
  from engine_core import TradingEngine

  engine = TradingEngine(
      price_df,           # DataFrame: date, open, high, low, close, volume, regime
      ma_period=40,       # 均线周期
      atr_period=20,      # ATR 周期
      atr_mult=2.5,       # ATR 乘数 k
      sell_k=2.0,         # 动态止盈 ATR 乘数
      abs_stop_pct=-0.07, # 绝对止损线
      cross_border=False, # 跨境ETF -> 冲击成本0.5%
      fixed_hold_days=None, # 固定持有期 (None=不固定, 40=40日强制退出)
  )
  trades, daily = engine.run()
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import IntEnum


# ============================================================
# 硬编码常量 (V1.2 冻结)
# ============================================================

class State(IntEnum):
    S0 = 0    # 空仓 0%
    S1 = 1    # 轻仓 33.3%
    S2 = 2    # 中仓 66.7%
    S3 = 3    # 满仓 100%

STATE_WEIGHT = {
    State.S0: 0.0,
    State.S1: 1/3,
    State.S2: 2/3,
    State.S3: 1.0,
}

PRIORITY = {
    "MACRO_FREEZE": 1,
    "SL2_STOP": 2,
    "SL3_TIME": 3,
    "SL4_CIRCUIT": 4,
    "SL1_TAKE_PROFIT": 5,
    "B1_ENTER": 6,
    "B2_ADD": 6,
    "B3_FULL": 6,
}

# 交易成本
COST_SLIPPAGE = 0.001
COST_COMMISSION_CN = 0.0005
COST_COMMISSION_US = 0.0003
COST_IMPACT_DOMESTIC = 0.002
COST_IMPACT_CROSS = 0.005

# 止损冷却期
STOP_OUT_COOLING = 60
STOP_OUT_CONSECUTIVE = 3

# 宏观熔断阈值
MACRO_THRESHOLDS = {
    "vix": 35,
    "us10y_daily_bp": 15,
    "dxy_daily_pct": 1.5,
    "ivix": 25,
    "liquidity": 30,
}

DEFAULT_SELL_K = 2.0


@dataclass
class Trade:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: int
    entry_state: State
    exit_reason: str
    return_pct: float
    return_after_cost: float
    hold_days: int
    is_partial: bool = False


@dataclass
class Position:
    state: State = State.S0
    entry_price: float = 0.0
    shares: int = 0
    entry_dates: List[pd.Timestamp] = field(default_factory=list)
    entry_prices: List[float] = field(default_factory=list)
    entry_shares: List[int] = field(default_factory=list)
    high_since_entry: float = 0.0
    atr_at_entry: float = 0.0
    stop_price: float = 0.0


class TradingEngine:

    def __init__(
        self,
        price_df: pd.DataFrame,
        ma_period: int = 40,
        atr_period: int = 20,
        atr_mult: float = 2.5,
        sell_k: float = DEFAULT_SELL_K,
        abs_stop_pct: float = -0.07,
        cross_border: bool = False,
        fixed_hold_days: Optional[int] = None,
        symbol: str = "???",
        capital: float = 100000.0,
    ):
        self.df = price_df.copy()
        self.df = self.df.sort_values("date").reset_index(drop=True)
        self.ma_period = ma_period
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.sell_k = sell_k
        self.abs_stop_pct = abs_stop_pct
        self.cross_border = cross_border
        self.fixed_hold_days = fixed_hold_days
        self.symbol = symbol

        if cross_border:
            self.impact_cost = COST_IMPACT_CROSS
        else:
            self.impact_cost = COST_IMPACT_DOMESTIC
        self.commission = COST_COMMISSION_CN if symbol[0].isdigit() else COST_COMMISSION_US
        self.cost_round_trip = COST_SLIPPAGE * 2 + self.commission * 2 + self.impact_cost * 2

        self._precompute()
        self.capital = capital

    def _precompute(self):
        df = self.df
        df["ma"] = df["close"].rolling(self.ma_period).mean()
        df["tr"] = np.maximum(
            df["high"] - df["low"],
            np.maximum(
                abs(df["high"] - df["close"].shift(1)),
                abs(df["low"] - df["close"].shift(1)),
            )
        )
        df["atr"] = df["tr"].rolling(self.atr_period).mean()
        df["buy_zone_high"] = df["ma"]
        df["buy_zone_low"] = df["ma"] - self.atr_mult * df["atr"]
        df["b1_trigger"] = df["ma"]
        df["b2_trigger"] = df["ma"] - 1.5 * self.atr_mult * df["atr"]
        df["b3_trigger"] = df["ma"] - 2.0 * self.atr_mult * df["atr"]
        df["trailing_line"] = np.nan

    def _get_dynamic_stop(self, pos: Position, current_close: float, current_atr: float) -> float:
        abs_stop = pos.entry_price * (1 + self.abs_stop_pct)
        atr_stop = pos.entry_price - 2.0 * pos.atr_at_entry
        return max(abs_stop, atr_stop)

    def _apply_cost(self, price: float, is_buy: bool) -> float:
        if is_buy:
            return price * (1 + COST_SLIPPAGE + self.commission + self.impact_cost)
        else:
            return price * (1 - COST_SLIPPAGE - self.commission - self.impact_cost)

    def run(self) -> Tuple[List[Trade], pd.DataFrame]:
        df = self.df
        n = len(df)

        pos = Position()
        trades: List[Trade] = []
        daily_records: List[Dict] = []

        # 止损冷却期追踪 (跨持仓)
        consecutive_stops = 0
        cooling_until_date = None

        # 宏观熔断 (简化: 无宏观数据时始终 False)
        macro_freeze = False
        macro_circuit = False

        start_idx = max(self.ma_period, self.atr_period) + 1
        if start_idx >= n:
            return trades, pd.DataFrame()

        for i in range(start_idx, n):
            row = df.iloc[i]
            date = row["date"]
            close = row["close"]
            atr = row["atr"]
            ma = row["ma"]

            if pd.isna(ma) or pd.isna(atr) or atr <= 0:
                daily_records.append({
                    "date": date, "state": int(pos.state), "close": close,
                    "position_value": 0, "trigger": "N/A"
                })
                continue

            # --- 确定当日触发条件 ---
            triggers = []

            if macro_freeze:
                triggers.append(("MACRO_FREEZE", PRIORITY["MACRO_FREEZE"], "macro_freeze"))
            if macro_circuit:
                triggers.append(("SL4_CIRCUIT", PRIORITY["SL4_CIRCUIT"], "macro_circuit"))

            # SL2: 止损
            if pos.state > State.S0:
                stop_price = self._get_dynamic_stop(pos, close, atr)
                if close <= stop_price:
                    triggers.append(("SL2_STOP", PRIORITY["SL2_STOP"], f"stop:{stop_price:.4f}"))

            # SL3: 时间退出
            if pos.state > State.S0:
                hold_days = (date - pos.entry_dates[0]).days
                if self.fixed_hold_days and hold_days >= self.fixed_hold_days:
                    triggers.append(("SL3_TIME", PRIORITY["SL3_TIME"], f"time:{hold_days}d"))
                elif not self.fixed_hold_days and hold_days >= 60:
                    triggers.append(("SL3_TIME", PRIORITY["SL3_TIME"], f"time:{hold_days}d"))

            # SL1: Dynamic trailing stop (Codex V20.56.27a)
            # Trigger: close < trailing_line (breach = sell one tier)
            # trailing_line = highest_close_since_entry - sell_k × ATR (ratchet up only)
            if pos.state > State.S0 and pos.high_since_entry > 0:
                trail = pos.high_since_entry - self.sell_k * atr
                # Ratchet up only
                if hasattr(pos, 'trail_line') and pos.trail_line is not None:
                    trail = max(trail, pos.trail_line)
                pos.trail_line = trail
                df.loc[df.index[i], "trailing_line"] = trail
                
                if close < trail:
                    triggers.append(("SL1_TAKE_PROFIT", PRIORITY["SL1_TAKE_PROFIT"], 
                                     f"tp:close={close:.2f}<trail={trail:.2f}"))

            # 买入条件 (非熔断 + 非冷却期)
            in_cooling = (cooling_until_date is not None and date <= cooling_until_date)
            if not macro_freeze and not macro_circuit and not in_cooling:
                if pos.state == State.S0 and close < row["b1_trigger"]:
                    triggers.append(("B1_ENTER", PRIORITY["B1_ENTER"], f"buy1:{close:.4f}<{row['b1_trigger']:.4f}"))
                elif pos.state == State.S1 and close < row["b2_trigger"]:
                    triggers.append(("B2_ADD", PRIORITY["B2_ADD"], f"buy2:{close:.4f}<{row['b2_trigger']:.4f}"))
                elif pos.state == State.S2 and close < row["b3_trigger"]:
                    triggers.append(("B3_FULL", PRIORITY["B3_FULL"], f"buy3:{close:.4f}<{row['b3_trigger']:.4f}"))

            # --- 按优先级执行 ---
            if triggers:
                triggers.sort(key=lambda x: x[1])
                trigger_name, _, trigger_detail = triggers[0]
                old_state = pos.state

                if trigger_name == "MACRO_FREEZE":
                    pass

                elif trigger_name == "SL2_STOP":
                    exit_price = self._apply_cost(close, is_buy=False)
                    if pos.entry_shares:
                        avg_entry = sum(p * s for p, s in zip(pos.entry_prices, pos.entry_shares)) / sum(pos.entry_shares)
                    else:
                        avg_entry = pos.entry_price
                    ret = (exit_price / avg_entry - 1)
                    ret_cost = ret - self.cost_round_trip
                    trade = Trade(
                        symbol=self.symbol, entry_date=pos.entry_dates[0], exit_date=date,
                        entry_price=avg_entry, exit_price=exit_price, shares=pos.shares,
                        entry_state=old_state, exit_reason="SL2_STOP",
                        return_pct=ret * 100, return_after_cost=ret_cost * 100,
                        hold_days=(date - pos.entry_dates[0]).days,
                    )
                    trades.append(trade)
                    consecutive_stops += 1
                    if consecutive_stops >= STOP_OUT_CONSECUTIVE:
                        cooling_until_date = date + pd.Timedelta(days=STOP_OUT_COOLING)
                    pos = Position()

                elif trigger_name == "SL4_CIRCUIT":
                    exit_price = self._apply_cost(close, is_buy=False)
                    if pos.entry_shares:
                        avg_entry = sum(p * s for p, s in zip(pos.entry_prices, pos.entry_shares)) / sum(pos.entry_shares)
                    else:
                        avg_entry = pos.entry_price
                    ret = (exit_price / avg_entry - 1)
                    ret_cost = ret - self.cost_round_trip
                    trade = Trade(
                        symbol=self.symbol, entry_date=pos.entry_dates[0], exit_date=date,
                        entry_price=avg_entry, exit_price=exit_price, shares=pos.shares,
                        entry_state=old_state, exit_reason="SL4_CIRCUIT",
                        return_pct=ret * 100, return_after_cost=ret_cost * 100,
                        hold_days=(date - pos.entry_dates[0]).days,
                    )
                    trades.append(trade)
                    consecutive_stops += 1
                    if consecutive_stops >= STOP_OUT_CONSECUTIVE:
                        cooling_until_date = date + pd.Timedelta(days=STOP_OUT_COOLING)
                    pos = Position()

                elif trigger_name == "SL3_TIME":
                    exit_price = self._apply_cost(close, is_buy=False)
                    if pos.entry_shares:
                        avg_entry = sum(p * s for p, s in zip(pos.entry_prices, pos.entry_shares)) / sum(pos.entry_shares)
                    else:
                        avg_entry = pos.entry_price
                    ret = (exit_price / avg_entry - 1)
                    ret_cost = ret - self.cost_round_trip
                    trade = Trade(
                        symbol=self.symbol, entry_date=pos.entry_dates[0], exit_date=date,
                        entry_price=avg_entry, exit_price=exit_price, shares=pos.shares,
                        entry_state=old_state, exit_reason="SL3_TIME",
                        return_pct=ret * 100, return_after_cost=ret_cost * 100,
                        hold_days=(date - pos.entry_dates[0]).days,
                    )
                    trades.append(trade)
                    consecutive_stops += 1
                    if consecutive_stops >= STOP_OUT_CONSECUTIVE:
                        cooling_until_date = date + pd.Timedelta(days=STOP_OUT_COOLING)
                    pos = Position()

                elif trigger_name == "SL1_TAKE_PROFIT":
                    exit_price = self._apply_cost(close, is_buy=False)
                    if pos.entry_shares:
                        last_shares = pos.entry_shares[-1]
                        last_price = pos.entry_prices[-1]
                        ret = (exit_price / last_price - 1)
                        ret_cost = ret - self.cost_round_trip
                        trade = Trade(
                            symbol=self.symbol, entry_date=pos.entry_dates[-1], exit_date=date,
                            entry_price=last_price, exit_price=exit_price, shares=last_shares,
                            entry_state=old_state, exit_reason="SL1_TAKE_PROFIT",
                            return_pct=ret * 100, return_after_cost=ret_cost * 100,
                            hold_days=(date - pos.entry_dates[-1]).days, is_partial=True,
                        )
                        trades.append(trade)
                        if ret > 0:
                            consecutive_stops = 0
                            cooling_until_date = None
                        pos.shares -= last_shares
                        pos.entry_dates.pop()
                        pos.entry_prices.pop()
                        pos.entry_shares.pop()
                    if old_state == State.S3:
                        pos.state = State.S2
                    elif old_state == State.S2:
                        pos.state = State.S1
                    else:
                        pos.state = State.S0
                        pos = Position()

                elif trigger_name in ("B1_ENTER", "B2_ADD", "B3_FULL"):
                    buy_price = self._apply_cost(close, is_buy=True)
                    buy_shares = 100
                    pos.entry_dates.append(date)
                    pos.entry_prices.append(buy_price)
                    pos.entry_shares.append(buy_shares)
                    pos.shares += buy_shares
                    pos.entry_price = sum(p * s for p, s in zip(pos.entry_prices, pos.entry_shares)) / pos.shares
                    pos.atr_at_entry = atr
                    pos.high_since_entry = close
                    if pos.state == State.S0:
                        pos.state = State.S1
                    elif pos.state == State.S1:
                        pos.state = State.S2
                    else:
                        pos.state = State.S3

            # --- Update high watermark (for SL1 trailing stop) ---
            if pos.state > State.S0:
                pos.high_since_entry = max(pos.high_since_entry, close)

            # --- 每日状态记录 ---
            daily_records.append({
                "date": date,
                "state": int(pos.state),
                "close": close,
                "ma": ma,
                "atr": atr,
                "buy_zone_high": row["buy_zone_high"],
                "buy_zone_low": row["buy_zone_low"],
                "position_shares": pos.shares,
                "position_value": pos.shares * close if pos.state > State.S0 else 0,
                "trigger": triggers[0][0] if triggers else "NONE",
                "trailing_line": df.loc[df.index[i], "trailing_line"] if pos.state > State.S0 else np.nan,
            })

        daily = pd.DataFrame(daily_records)
        return trades, daily


@dataclass
class BacktestResult:
    symbol: str
    ma_period: int
    atr_mult: float
    sell_k: float
    abs_stop_pct: float
    n_trades: int
    n_wins: int
    win_rate: float
    avg_return: float
    avg_return_cost: float
    total_return: float
    max_drawdown: float
    calmar: float
    avg_hold_days: float
    annual_trades: float
    regime_breakdown: Dict[str, float]
    trades: List[Trade]


def compute_backtest_result(
    trades: List[Trade],
    daily: pd.DataFrame,
    symbol: str,
    ma_period: int,
    atr_mult: float,
    sell_k: float,
    abs_stop_pct: float,
) -> BacktestResult:
    n_trades = len(trades)
    if n_trades == 0:
        return BacktestResult(
            symbol=symbol, ma_period=ma_period, atr_mult=atr_mult,
            sell_k=sell_k, abs_stop_pct=abs_stop_pct,
            n_trades=0, n_wins=0, win_rate=0.0, avg_return=0.0, avg_return_cost=0.0,
            total_return=0.0, max_drawdown=0.0, calmar=0.0, avg_hold_days=0.0,
            annual_trades=0.0, regime_breakdown={}, trades=[],
        )

    returns = [t.return_after_cost for t in trades]
    n_wins = sum(1 for r in returns if r > 0)
    win_rate = n_wins / n_trades
    avg_return = float(np.mean([t.return_pct for t in trades]))
    avg_return_cost = float(np.mean(returns))
    total_return = float(sum(returns))

    if len(daily) > 0 and "position_value" in daily.columns:
        cummax = daily["position_value"].cummax()
        dd = (daily["position_value"] - cummax) / cummax.replace(0, np.nan) * 100
        max_dd = abs(dd.min()) if not dd.isna().all() else 0.0
    else:
        max_dd = 0.0

    if max_dd > 0 and len(daily) > 0:
        days_span = (daily["date"].max() - daily["date"].min()).days
        years = days_span / 365.25
        if years > 0:
            annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100
            calmar = annual_return / max_dd
        else:
            calmar = 0.0
    else:
        calmar = 0.0

    avg_hold_days = float(np.mean([t.hold_days for t in trades]))

    if len(daily) > 0:
        days_span = (daily["date"].max() - daily["date"].min()).days
        years_span = max(days_span / 365.25, 0.01)
        annual_trades = n_trades / years_span
    else:
        annual_trades = 0.0

    regime_breakdown = {}
    for t in trades:
        regime = "normal"
        regime_breakdown[regime] = regime_breakdown.get(regime, 0.0) + t.return_after_cost

    return BacktestResult(
        symbol=symbol, ma_period=ma_period, atr_mult=atr_mult,
        sell_k=sell_k, abs_stop_pct=abs_stop_pct,
        n_trades=n_trades, n_wins=n_wins, win_rate=win_rate,
        avg_return=avg_return, avg_return_cost=avg_return_cost,
        total_return=total_return, max_drawdown=max_dd, calmar=calmar,
        avg_hold_days=avg_hold_days, annual_trades=annual_trades,
        regime_breakdown=regime_breakdown, trades=trades,
    )
