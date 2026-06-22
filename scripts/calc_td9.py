#!/usr/bin/env python3
"""
TD9 计算引擎 V1.0 — 2026-06-22 焊入
基于Tushare日线自算全池18标TD9状态，三级输出：结构状态/当前计数/确认条件

低位9转（下跌衰竭）= 收盘连续9天低于4天前 → 买入信号
高位9转（上涨衰竭）= 收盘连续9天高于4天前 → 卖出信号

确认条件（三AND）：
  C1: 结构完整性 — 计数=9
  C2: 缩量确认   — 第9天成交量 < 20日均量的80%
  C3: 小实体确认  — 第9天实体 ≤ ATR14的30%
"""

import pandas as pd
import numpy as np


def calc_td9(df: pd.DataFrame) -> dict:
    """
    输入: Tushare日线DataFrame，必须含 trade_date, close, open, vol
    输出: dict with:
        - td9_status: '低位9转完成' | '高位9转完成' | '进行中(N/9)' | '无信号'
        - td9_count: 当前连续计数 (int)
        - td9_interrupted_days: 最近一次中断距今几天
        - c2_volume_ratio: 第9天成交量/20日均量 (float or None)
        - c3_body_ratio: 第9天实体/ATR14 (float or None)
        - c1_pass / c2_pass / c3_pass: bool
        - td9_confirmed: bool (三条件AND)
        - td9_direction: 'low' | 'high' | None
    """
    result = {
        'td9_status': '无信号',
        'td9_count': 0,
        'td9_interrupted_days': 0,
        'c2_volume_ratio': None,
        'c3_body_ratio': None,
        'c1_pass': False,
        'c2_pass': False,
        'c3_pass': False,
        'td9_confirmed': False,
        'td9_direction': None,
    }

    if len(df) < 14:
        return result

    df = df.sort_values('trade_date').reset_index(drop=True)
    closes = df['close'].values
    opens = df['open'].values
    vols = df['vol'].values
    highs = df['high'].values
    lows = df['low'].values

    # ---- ATR14 自算 ----
    if len(closes) >= 15:
        prev_closes = np.roll(closes, 1)
        prev_closes[0] = closes[0]
        tr = np.maximum(highs - lows,
                        np.maximum(np.abs(highs - prev_closes),
                                   np.abs(lows - prev_closes)))
        atr14 = pd.Series(tr).rolling(14).mean().iloc[-1]
    else:
        atr14 = None

    # ---- 20日均量 ----
    if len(vols) >= 20:
        vol_ma20 = np.mean(vols[-20:])
    else:
        vol_ma20 = np.mean(vols)

    # ---- TD9 结构扫描（从最新一根K线往前） ----
    # 同时扫描低位9转和高位9转，取最近完成的结构
    n = len(closes)

    def count_td_sequence(closes_array, direction='low'):
        """方向: 'low'=C_i<C_{i-4}低位9转, 'high'=C_i>C_{i-4}高位9转"""
        count = 0
        for i in range(n - 1, 3, -1):  # 从最新往前，至少需要i-4存在
            if direction == 'low':
                condition = closes_array[i] < closes_array[i - 4]
            else:
                condition = closes_array[i] > closes_array[i - 4]
            if condition:
                count += 1
            else:
                break
        return count

    low_count = count_td_sequence(closes, 'low')
    high_count = count_td_sequence(closes, 'high')

    # 判定方向：取计数最大的方向，若相等取低位（均值回归优先）
    if low_count >= high_count:
        direction = 'low'
        count = low_count
    else:
        direction = 'high'
        count = high_count

    result['td9_direction'] = direction
    result['td9_count'] = count

    if count >= 9:
        if direction == 'low':
            result['td9_status'] = '低位9转完成'
        else:
            result['td9_status'] = '高位9转完成'
        result['c1_pass'] = True
    elif count >= 1:
        result['td9_status'] = f'进行中({count}/9)'
    else:
        result['td9_status'] = '无信号'

    # 中断天数
    if count == 0:
        # 找最近一次中断——从最新一根往前，第一个不满足的之后就是中断
        interrupted_idx = None
        for i in range(n - 1, 3, -1):
            if direction == 'low':
                cond = closes[i] >= closes[i - 4]
            else:
                cond = closes[i] <= closes[i - 4]
            if cond:
                interrupted_idx = i
                break
        if interrupted_idx is not None:
            result['td9_interrupted_days'] = n - 1 - interrupted_idx
        else:
            result['td9_interrupted_days'] = -1  # 从未形成过序列

    # ---- 确认条件 C2 + C3（仅当计数=9时计算） ----
    if count >= 9:
        # C2: 第9天成交量 / 20日均量
        day9_vol = vols[-1]  # 最新一根K线是第9天
        if vol_ma20 > 0:
            result['c2_volume_ratio'] = round(day9_vol / vol_ma20, 3)
            result['c2_pass'] = result['c2_volume_ratio'] < 0.8

        # C3: 第9天实体 / ATR14
        day9_open = opens[-1]
        day9_close = closes[-1]
        day9_body = abs(day9_close - day9_open)
        if atr14 is not None and atr14 > 0:
            result['c3_body_ratio'] = round(day9_body / atr14, 3)
            result['c3_pass'] = result['c3_body_ratio'] < 0.3

        result['td9_confirmed'] = result['c1_pass'] and result['c2_pass'] and result['c3_pass']

    return result


def calc_td9_batch(dfs: dict) -> dict:
    """批量计算全池标的TD9状态"""
    results = {}
    for code, df in dfs.items():
        results[code] = calc_td9(df)
    return results


if __name__ == '__main__':
    # 测试
    import sys
    if len(sys.argv) > 1:
        print("TD9 计算引擎 V1.0 就绪")
        print("用法: import calc_td9; calc_td9(df)")
    else:
        print("TD9 计算引擎 V1.0 就绪")
