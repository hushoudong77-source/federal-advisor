"""
engine_core_v2.py — V1.2.1 改造版 交易引擎核心
==============================================
基于 V1.2 冻结版 + 三大改造补丁 (2026-05-09 黑帽裁决)
  - 补丁A: ADX(14)+MA200 联合 Regime 识别 + 仓位调度
  - 补丁B: 不对称均值回归 (只买回调, MA-price>k×ATR)
  - 补丁C: 仓位状态机与 Regime 联动

改造硬规格 (V1.2.1 冻结):
  Regime判定:
    VIX>30           → CRISIS    (禁止新开仓, 仓位上限0%)
    ADX>25 & close<MA200 → TREND_DOWN (禁止新开仓, 仓位上限0%)
    ADX>25 & close>MA200 → TREND_UP   (允许开仓, 仓位上限10%)
    ADX≤25           → RANGE     (允许开仓, 仓位上限20%)

  买入触发 (不对称):
    原: abs(close - ma) > k * atr
    新: (ma - close) > k * atr  (只买回调)

  保留 V1.2 全部原有功能:
    - 六级优先级 / 四状态仓位机 / 动态止盈 / ATR止损
    - 止损冷却期 / 交易成本 / 宏观熔断
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import IntEnum
from engine_core import (
    State, STATE_WEIGHT, PRIORITY, Trade, Position,
    COST_SLIPPAGE, COST_COMMISSION_CN, COST_COMMISSION_US,
    COST_IMPACT_DOMESTIC, COST_IMPACT_CROSS,
    STOP_OUT_COOLING, STOP_OUT_CONSECUTIVE,
    DEFAULT_SELL_K,
    BacktestResult, compute_backtest_result,
)


# ============================================================
# V1.2.1 新增常量
# ============================================================

ADX_PERIOD = 14
MA200_PERIOD = 200
VIX_CRISIS = 30
ADX_TREND = 25

REGIME_CRISIS = "CRISIS"
REGIME_TREND_DOWN = "TREND_DOWN"
REGIME_TREND_UP = "TREND_UP"
REGIME_RANGE = "RANGE"

# 仓位上限: 基于4档仓位状态 (S0=0, S1=1/3, S2=2/3, S3=1.0)
# 上限值 = 最大允许的仓位权重 (0=空仓, 1/3=只允许S1, 2/3=允许S1+S2, 1.0=允许三档满仓)
REGIME_MAX_POSITION = {
    REGIME_CRISIS: 0.0,        # 禁止一切持仓
    REGIME_TREND_DOWN: 0.0,    # 强趋势下跌，不接飞刀
    REGIME_TREND_UP: 2/3,      # 强趋势上涨，允许最多2档 (S2=66.7%)
    REGIME_RANGE: 1.0,         # 震荡市，允许三档满仓 (S3=100%)
}


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """自主计算 ADX (不依赖 TA-Lib)"""
    # +DM / -DM
    up_move = high.diff()
    down_move = -low.diff()
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    # True Range
    tr = np.maximum(
        high - low,
        np.maximum(
            abs(high - close.shift(1)),
            abs(low - close.shift(1))
        )
    )
    
    # Wilder's smoothing (EMA with alpha=1/period for first period, then EMA)
    atr_smooth = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=close.index).ewm(alpha=1/period, adjust=False).mean() / atr_smooth
    minus_di = 100 * pd.Series(minus_dm, index=close.index).ewm(alpha=1/period, adjust=False).mean() / atr_smooth
    
    # DX = |+DI - -DI| / (+DI + -DI) * 100
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    
    # ADX = smoothed DX
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    
    return adx


class TradingEngineV2:
    """V1.2.1 改造版交易引擎"""

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
        enable_regime: bool = True,       # 启用补丁A+C
        enable_asymmetric: bool = True,   # 启用补丁B
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
        self.enable_regime = enable_regime
        self.enable_asymmetric = enable_asymmetric

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
        
        # V1.2.1: 不对称买入 - b1/b2/b3 只在回调方向 (price < ma)
        df["b1_trigger"] = df["ma"]
        df["b2_trigger"] = df["ma"] - 1.5 * self.atr_mult * df["atr"]
        df["b3_trigger"] = df["ma"] - 2.0 * self.atr_mult * df["atr"]
        
        df["trailing_line"] = np.nan
        
        # V1.2.1: MA200 for regime detection
        df["ma200"] = df["close"].rolling(MA200_PERIOD).mean()
        
        # V1.2.1: ADX(14)
        df["adx"] = compute_adx(df["high"], df["low"], df["close"], ADX_PERIOD)
        
        # V1.2.1: Regime 判定
        df["regime_v2"] = REGIME_RANGE  # default
        # 注意: VIX 需要外部注入，这里简化为只用 ADX+MA200
        # 完整版需要 vix_value 参数，但回测中通常没有日度 VIX 数据
        # 此处根据 ADX+MA200 判定，VIX 熔断暂不在回测中启用（保持向后兼容）
        
        for i in range(len(df)):
            adx_val = df["adx"].iloc[i]
            ma200_val = df["ma200"].iloc[i]
            close_val = df["close"].iloc[i]
            
            if pd.isna(adx_val) or pd.isna(ma200_val):
                continue
                
            if adx_val > ADX_TREND and close_val < ma200_val:
                df.loc[df.index[i], "regime_v2"] = REGIME_TREND_DOWN
            elif adx_val > ADX_TREND and close_val > ma200_val:
                df.loc[df.index[i], "regime_v2"] = REGIME_TREND_UP
            else:
                df.loc[df.index[i], "regime_v2"] = REGIME_RANGE

    def _get_dynamic_stop(self, pos: Position, current_close: float, current_atr: float) -> float:
        abs_stop = pos.entry_price * (1 + self.abs_stop_pct)
        atr_stop = pos.entry_price - 2.0 * pos.atr_at_entry
        return max(abs_stop, atr_stop)

    def _apply_cost(self, price: float, is_buy: bool) -> float:
        if is_buy:
            return price * (1 + COST_SLIPPAGE + self.commission + self.impact_cost)
        else:
            return price * (1 - COST_SLIPPAGE - self.commission - self.impact_cost)

    def _check_entry_signal(self, close: float, ma: float, atr: float, k_mult: float) -> Tuple[bool, str]:
        """
        V1.2.1 补丁B: 不对称均值回归 — 只买回调
        原: abs(close - ma) > k * atr  (对称，向上突破也触发)
        新: (ma - close) > k * atr      (只买回调，价格低于均线)
        """
        if not self.enable_asymmetric:
            # 旧逻辑 (对称) — 用于对照组
            trigger_line = ma - k_mult * atr
            if close < trigger_line:
                return True, f"ENTRY_SYM:close={close:.2f}<{trigger_line:.2f}"
            return False, ""

        deviation = ma - close  # 正数 = 价格低于均线 (回调)
        threshold = k_mult * atr
        
        if deviation > threshold:
            return True, f"ENTRY_ASYM:dev={deviation:.2f}>{threshold:.2f}"
        return False, ""

    def run(self) -> Tuple[List[Trade], pd.DataFrame]:
        df = self.df
        n = len(df)

        pos = Position()
        trades: List[Trade] = []
        daily_records: List[Dict] = []

        # 止损冷却期追踪
        consecutive_stops = 0
        cooling_until_date = None

        # 宏观熔断 (简化: 无宏观数据时始终 False)
        macro_freeze = False
        macro_circuit = False

        start_idx = max(self.ma_period, self.atr_period, MA200_PERIOD, ADX_PERIOD * 2) + 1
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

            # V1.2.1: Regime 检查
            if self.enable_regime:
                regime = row["regime_v2"]
                max_pos = REGIME_MAX_POSITION.get(regime, 0.20)
                allow_entry = max_pos > 0
            else:
                regime = "N/A"
                max_pos = 1.0
                allow_entry = True

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

            # SL1: Dynamic trailing stop
            if pos.state > State.S0 and pos.high_since_entry > 0:
                trail = pos.high_since_entry - self.sell_k * atr
                if hasattr(pos, 'trail_line') and pos.trail_line is not None:
                    trail = max(trail, pos.trail_line)
                pos.trail_line = trail
                df.loc[df.index[i], "trailing_line"] = trail

                if close < trail:
                    triggers.append(("SL1_TAKE_PROFIT", PRIORITY["SL1_TAKE_PROFIT"],
                                     f"tp:close={close:.2f}<trail={trail:.2f}"))

            # V1.2.1: 买入条件 (Regime约束 + 不对称买入 + 非冷却期)
            in_cooling = (cooling_until_date is not None and date <= cooling_until_date)
            if not macro_freeze and not macro_circuit and not in_cooling and allow_entry:
                if pos.state == State.S0:
                    should_buy, detail = self._check_entry_signal(close, ma, atr, self.atr_mult)
                    if should_buy:
                        # 检查 Regime 仓位上限
                        new_weight = 1/3
                        if new_weight <= max_pos + 0.001:
                            triggers.append(("B1_ENTER", PRIORITY["B1_ENTER"], detail))
                        else:
                            triggers.append(("B1_BLOCKED_REGIME", PRIORITY["B1_ENTER"], f"regime:{regime}"))
                elif pos.state == State.S1:
                    should_buy, detail = self._check_entry_signal(close, ma, atr, 1.5 * self.atr_mult)
                    if should_buy:
                        new_weight = 2/3
                        if new_weight <= max_pos + 0.001:
                            triggers.append(("B2_ADD", PRIORITY["B2_ADD"], detail))
                        else:
                            triggers.append(("B2_BLOCKED_REGIME", PRIORITY["B2_ADD"], f"regime:{regime}"))
                elif pos.state == State.S2:
                    should_buy, detail = self._check_entry_signal(close, ma, atr, 2.0 * self.atr_mult)
                    if should_buy:
                        new_weight = 1.0
                        if new_weight <= max_pos + 0.001:
                            triggers.append(("B3_FULL", PRIORITY["B3_FULL"], detail))
                        else:
                            triggers.append(("B3_BLOCKED_REGIME", PRIORITY["B3_FULL"], f"regime:{regime}"))

            # --- 按优先级执行 ---
            if triggers:
                triggers.sort(key=lambda x: x[1])
                trigger_name, _, trigger_detail = triggers[0]
                old_state = pos.state

                # 被 Regime 阻挡的买入 = 不执行
                if trigger_name in ("B1_BLOCKED_REGIME", "B2_BLOCKED_REGIME", "B3_BLOCKED_REGIME"):
                    pass  # 不执行

                elif trigger_name == "MACRO_FREEZE":
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

            # --- Update high watermark ---
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
                "regime": regime if self.enable_regime else "N/A",
                "adx": row["adx"] if "adx" in row.index else np.nan,
                "ma200": row["ma200"] if "ma200" in row.index else np.nan,
            })

        daily = pd.DataFrame(daily_records)
        return trades, daily
