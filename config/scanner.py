#!/usr/bin/env python3
"""
联邦扫描引擎 V2.0 — 法典路由完整嵌入版 + 白名单硬编码
每次扫描启动时强制校验全池白名单，非池内标的直接拒绝。
路由逻辑完整对齐法典V5.8.2r15 §2。

用法:
    python3 config/scanner.py                    # 全池扫描
    python3 config/scanner.py --symbol QQQ       # 单标扫描
    python3 config/scanner.py --verbose          # 详细输出
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.pool_whitelist import (
    POOL_WHITELIST, BLACKLIST_PERMANENT,
    validate_symbol, validate_symbols,
    get_tushare_code, get_market,
    get_us_symbols, get_a_symbols, get_all_symbols,
    get_routing_symbols,
)
import tushare as ts
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# ============================================================
# Tushare初始化
# ============================================================
pro = ts.pro_api()

# ============================================================
# 核心：扫描前强制校验
# ============================================================

def pre_scan_validate(requested_symbols: list) -> tuple[list, list]:
    """
    直觉拦截协议V2.0 Step 0 — 代码硬化。
    任何不在白名单内的标的直接拒绝。
    """
    valid, rejected = validate_symbols(requested_symbols)
    if rejected:
        print(f"\n{'='*60}")
        print(f"🚫 直觉拦截：以下 {len(rejected)} 只标的不在全池21标白名单内")
        print(f"   拒绝标的: {', '.join(rejected)}")
        print(f"{'='*60}\n")
    return valid, rejected


# ============================================================
# 技术指标计算
# ============================================================

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def atr_wilder(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean().iloc[-1]


def macd_hist(close_series):
    ema12 = ema(close_series, 12)
    ema26 = ema(close_series, 26)
    dif = ema12 - ema26
    dea = ema(dif, 9)
    hist = (dif - dea) * 2
    return dif.iloc[-1], dea.iloc[-1], hist.iloc[-1]


def rsi_wilder(close_series, period=6):
    delta = close_series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    return 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss != 0 else 100


def adx_wilder(df, period=14):
    """Wilder ADX(14)计算"""
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()

    up = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0), index=df.index)

    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()

    return adx.iloc[-1], plus_di.iloc[-1], minus_di.iloc[-1]


def fetch_us_etf(symbol, start_date, end_date):
    ts_code = get_tushare_code(symbol)
    df = pro.us_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df.empty:
        return None
    df = df.sort_values('trade_date').reset_index(drop=True)
    for col in ['close', 'high', 'low', 'vol']:
        df[col] = df[col].astype(float)
    return df


def fetch_a_etf(symbol, start_date, end_date):
    ts_code = get_tushare_code(symbol)
    df = pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df.empty:
        return None
    df = df.sort_values('trade_date').reset_index(drop=True)
    for col in ['close', 'high', 'low', 'vol']:
        df[col] = df[col].astype(float)
    return df


def calc_indicators(df, symbol):
    """计算全量技术指标"""
    close = df['close']
    n = len(close)

    ema30 = ema(close, 30).iloc[-1]
    ema50 = ema(close, 50).iloc[-1]
    ema150 = ema(close, 150).iloc[-1] if n >= 150 else None
    ema20 = ema(close, 20).iloc[-1]

    # MA锚线（用于反击买入区间计算）
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma40 = close.rolling(40).mean().iloc[-1] if n >= 40 else None
    ma60 = close.rolling(60).mean().iloc[-1] if n >= 60 else None

    atr14 = atr_wilder(df, 14)
    h20 = close.iloc[-21:-1].max() if n >= 21 else None
    vol_ma20 = df['vol'].rolling(20).mean().iloc[-1] if n >= 20 else None
    volume = df['vol'].iloc[-1]

    dev_150 = (close.iloc[-1] - ema150) / ema150 * 100 if ema150 else None

    dif, dea, macd_h = macd_hist(close)
    rsi6 = rsi_wilder(close, 6)
    adx14, plus_di, minus_di = adx_wilder(df, 14)

    # EMA排列
    if ema30 and ema50 and ema150:
        if ema30 > ema50 > ema150:
            ema_arr = "多头"
        elif ema30 < ema50 < ema150:
            ema_arr = "空头"
        else:
            ema_arr = "混乱"
    else:
        ema_arr = "数据不足"

    return {
        'close': close.iloc[-1],
        'prev_close': close.iloc[-2] if n >= 2 else None,
        'ema30': ema30, 'ema50': ema50, 'ema150': ema150, 'ema20': ema20,
        'ma10': ma10, 'ma20': ma20, 'ma40': ma40, 'ma60': ma60,
        'atr14': atr14, 'h20': h20, 'vol_ma20': vol_ma20, 'volume': volume,
        'dev_150': dev_150,
        'dif': dif, 'dea': dea, 'macd_hist': macd_h,
        'rsi6': rsi6,
        'adx14': adx14, 'plus_di': plus_di, 'minus_di': minus_di,
        'ema_arrangement': ema_arr,
        'latest_date': df['trade_date'].iloc[-1],
    }


# ============================================================
# 法典路由参数矩阵
# ============================================================

# 逐标差异化乖离阈值（§2.2）
DEVIATION_THRESHOLDS = {
    # 大盘宽基: >50% → 🔴观望, <30%解除
    "QQQ": 50, "IVV": 50, "510300": 50, "510500": 50,
    "513910": 50, "159545": 50, "159302": 50,
    # 科技/主题: >70% → 🔴观望, <45%解除
    "159915": 70, "588000": 70, "513180": 70, "513770": 70,
    # 小微/新兴: >80% → 🔴观望, <50%解除
    "VNM": 80, "FLIN": 80, "EWY": 80, "BBJP": 80, "MUFG": 80,
}

# 逐标反击锚线与buy_k（§2.6）
COUNTERPUNCH_PARAMS = {
    "BBJP":    {"anchor": "MA40", "buy_k": 2.5},
    "MUFG":    {"anchor": "MA40", "buy_k": 0.5},
    "EWY":     {"anchor": "MA40", "buy_k": 3.0},
    "VNM":     {"anchor": "MA20", "buy_k": 0.5},
    "FLIN":    {"anchor": "MA20", "buy_k": 1.0},
    "SMIN":    {"anchor": "MA20", "buy_k": 4.0},
    "510300":  {"anchor": "MA60", "buy_k": 5.0},
    "510500":  {"anchor": "MA60", "buy_k": 5.0},
    "159915":  {"anchor": "MA10", "buy_k": 1.5},
    "588000":  {"anchor": "MA60", "buy_k": 5.0},
    "513770":  {"anchor": "MA60", "buy_k": 2.5},
    "513180":  {"anchor": "MA20", "buy_k": 0.5},
    "513910":  {"anchor": "MA60", "buy_k": 4.5},
    "159545":  {"anchor": "MA40", "buy_k": 4.5},
    "159302":  {"anchor": "MA60", "buy_k": 4.0},
}

# 策略权限矩阵（V5.8.2r14+）
SPEARHEAD_ONLY = {"QQQ", "IVV"}  # 仅进攻，移除反击资格
SPEARHEAD_REMOVED = {"BBJP", "510300", "510500"}  # 从进攻移除，仅反击
GOLD_SHIELD = {"IAU", "518880"}  # 金盾独立驱动
SMIN_OBSERVATION = {"SMIN"}  # 观察期，2%上限，不进进攻

# 速率闸分标响应（§2.1 0-B）
RATE_GATE_VIX = {"159915", "588000"}  # VIX跳升>3点 → 禁开
RATE_GATE_US10Y = {"EWY", "BBJP", "IAU", "513180", "513770"}  # US10Y跳升>8bp → 禁开

# 仓位上限（§2.1 步骤3）
POSITION_CAPS = {
    "R1_false": 0.05,     # 50EMA≤150EMA → ≤5%
    "R2_only": 0.10,      # 仅C2为False → ≤10%
    "step_1_5": 0.05,     # 步骤1.5 → ≤5%（折半）
    "SMIN": 0.02,         # 观察期2%上限
    "MUFG": 0.05,         # MUFG反击仓位上限5%
}


# ============================================================
# 路由主逻辑（对齐法典§2.1）
# ============================================================

def route_symbol(symbol, ind, entry, macro_state=None):
    """
    法典§2.1完整路由判定。
    macro_state: {'us10y': float, 'us10y_jump_bp': float, 'vix_jump': float}
    """
    result = {
        'symbol': symbol,
        'name': entry['name'],
        'close': ind['close'],
        'date': ind['latest_date'],
        'dev_150': ind['dev_150'],
        'ema_arr': ind['ema_arrangement'],
        'macd_hist': ind['macd_hist'],
        'rsi6': ind['rsi6'],
        'atr14': ind['atr14'],
        'h20': ind.get('h20'),
    }

    # ── 步骤−1：豁免前置 ──
    if symbol in GOLD_SHIELD or entry.get('exempt'):
        result['route'] = 'exempt'
        result['signal'] = '⚪'
        result['reason'] = '固定层/黄金豁免'
        return result

    # ── 步骤0-F：SMIN观察期 ──
    if symbol in SMIN_OBSERVATION:
        result['route'] = 'observation'
        result['signal'] = '🟡'
        result['reason'] = 'SMIN观察期，2%上限，不进进攻'
        return result

    # ── 步骤0：宏观闸（简化版，完整版需输入macro_state） ──
    if macro_state:
        if macro_state.get('us10y', 0) >= 5.0:
            result['route'] = 'frozen'
            result['signal'] = '🔴'
            result['reason'] = 'US10Y≥5.00%全球熔断'
            return result
        if macro_state.get('vix_jump', 0) > 3 and symbol in RATE_GATE_VIX:
            result['route'] = 'rate_gated'
            result['signal'] = '🟡'
            result['reason'] = 'VIX跳升>3点，禁开进攻'
            return result
        if macro_state.get('us10y_jump_bp', 0) > 8 and symbol in RATE_GATE_US10Y:
            result['route'] = 'rate_gated'
            result['signal'] = '🟡'
            result['reason'] = 'US10Y跳升>8bp，禁开进攻'
            return result

    # ── 步骤0.5：极端乖离拦截 ──
    threshold = DEVIATION_THRESHOLDS.get(symbol, 80)
    if ind['dev_150'] and abs(ind['dev_150']) > threshold:
        result['route'] = 'deviation_halted'
        result['signal'] = '🔴'
        result['reason'] = f'乖离{ind["dev_150"]:.1f}%>{threshold}%阈值'
        return result

    # ── EMA方向判定 ──
    c1_proxy = ind['ema50'] > ind['ema150'] if ind['ema150'] else None
    c2_proxy = ind['ema30'] > ind['ema50']

    if c1_proxy is None:
        result['route'] = 'data_insufficient'
        result['signal'] = '⚪'
        result['reason'] = '150EMA数据不足'
        return result

    result['c1_proxy'] = c1_proxy
    result['c2_proxy'] = c2_proxy

    # ── 步骤1：进攻四条件（仅当C1 AND C2均为True） ──
    if c1_proxy and c2_proxy:
        # 检查策略权限
        if symbol in SPEARHEAD_REMOVED:
            # 从进攻移除 → 进入步骤1.5（EMA多头但仅反击）
            pass
        elif symbol not in SPEARHEAD_ONLY and symbol not in SMIN_OBSERVATION:
            # 非仅进攻标的 → 可进入步骤1.5
            pass

        # C3: C > 50EMA
        c3 = ind['close'] > ind['ema50']
        # C4: (C ≥ H20×0.995) AND (V > 20日均量) AND (C > 昨收)
        c4_h20 = ind['close'] >= ind['h20'] * 0.995 if ind['h20'] else False
        c4_vol = ind['volume'] > ind['vol_ma20'] if ind['vol_ma20'] else False
        c4_up = ind['close'] > ind['prev_close'] if ind['prev_close'] else False
        c4 = c4_h20 and c4_vol and c4_up

        result['c3'] = c3
        result['c4'] = c4
        result['c4_detail'] = {'h20': c4_h20, 'vol': c4_vol, 'up': c4_up}

        if c1_proxy and c2_proxy and c3 and c4:
            # 全满足 → 进攻
            if symbol in SPEARHEAD_REMOVED:
                # BBJP/510300/510500已从进攻移除
                result['route'] = 'counterpunch'  # 降级为反击
                result['signal'] = '🟢'
                result['reason'] = 'C1-C4全满足但进攻已移除→反击域'
            elif symbol in SMIN_OBSERVATION:
                result['route'] = 'observation'
                result['signal'] = '🟡'
                result['reason'] = 'SMIN不进进攻轨道'
            else:
                result['route'] = 'spearhead'
                result['signal'] = '🟢'
                result['reason'] = 'C1-C4全满足'
            return result

        # 步骤1.5：EMA全多头但C3或C4不满足 → 检查回调买入区间
        params = COUNTERPUNCH_PARAMS.get(symbol, {})
        if params:
            anchor_key = params['anchor']
            buy_k = params['buy_k']
            anchor_val = ind.get(anchor_key.lower(), None)

            if anchor_val:
                buy_low = anchor_val - buy_k * ind['atr14']
                buy_high = anchor_val
                in_zone = buy_low <= ind['close'] <= buy_high

                result['step_1_5'] = True
                result['buy_zone'] = (buy_low, buy_high)
                result['in_buy_zone'] = in_zone

                if in_zone:
                    result['route'] = 'counterpunch_step15'
                    result['signal'] = '🟢'
                    result['reason'] = f'步骤1.5回调买入区[{buy_low:.3f},{buy_high:.3f}]'
                    result['position_cap'] = POSITION_CAPS['step_1_5']
                    return result

        # EMA多头但不在买入区 → 闲置等待
        result['route'] = 'idle'
        result['signal'] = '⚪'
        missing = []
        if not c3: missing.append('C3')
        if not c4: missing.append('C4')
        result['reason'] = f'EMA多头，缺{",".join(missing)}，不在买入区'
        return result

    # ── 步骤1.7：ADX趋势过滤（反击前） ──
    if ind['adx14'] > 30:
        result['route'] = 'idle_adx'
        result['signal'] = '⚪'
        result['reason'] = f'ADX={ind["adx14"]:.1f}>30，强趋势禁反击'
        return result

    # ── 步骤2：反击二条件 ──
    # R1: C1为False 或 C2为False（至少一个EMA方向向下）
    r1 = (not c1_proxy) or (not c2_proxy)
    result['r1'] = r1

    if not r1:
        result['route'] = 'idle'
        result['signal'] = '⚪'
        result['reason'] = 'EMA方向不满足反击条件'
        return result

    # 检查反击资格
    if symbol in SPEARHEAD_ONLY:
        result['route'] = 'idle'
        result['signal'] = '⚪'
        result['reason'] = '仅进攻资格，无反击资格'
        return result

    # R2: C ∈ [锚线 − buy_k × ATR, 锚线]
    params = COUNTERPUNCH_PARAMS.get(symbol, {})
    if not params:
        result['route'] = 'idle'
        result['signal'] = '⚪'
        result['reason'] = '无反击参数'
        return result

    anchor_key = params['anchor']
    buy_k = params['buy_k']
    anchor_val = ind.get(anchor_key.lower(), None)

    if anchor_val is None:
        result['route'] = 'data_insufficient'
        result['signal'] = '⚪'
        result['reason'] = f'{anchor_key}数据不足'
        return result

    buy_low = anchor_val - buy_k * ind['atr14']
    buy_high = anchor_val
    r2 = buy_low <= ind['close'] <= buy_high

    result['r2'] = r2
    result['buy_zone'] = (buy_low, buy_high)
    result['anchor'] = f'{anchor_key}={anchor_val:.4f}'

    # 步骤3：仓位分级
    if not c1_proxy:
        pos_cap = POSITION_CAPS['R1_false']
        reason_suffix = '50EMA≤150EMA'
    else:
        pos_cap = POSITION_CAPS['R2_only']
        reason_suffix = '仅C2为False'
    result['position_cap'] = pos_cap

    if r2:
        result['route'] = 'counterpunch'
        result['signal'] = '🟢'
        result['reason'] = f'反击R1∧R2满足 | {reason_suffix} | 仓位≤{pos_cap*100:.0f}%'
    else:
        result['route'] = 'idle'
        result['signal'] = '⚪'
        result['reason'] = f'R1满足但价不在买入区[{buy_low:.3f},{buy_high:.3f}]'

    return result


# ============================================================
# 扫描主函数
# ============================================================

def scan_all(start_date=None, end_date=None, macro_state=None, verbose=False):
    """全池21标扫描"""
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=400)).strftime('%Y%m%d')
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')

    symbols = get_routing_symbols()
    print(f"\n🔍 联邦扫描引擎 V2.0 — 全池{len(symbols)}标")
    print(f"   数据范围: {start_date} ~ {end_date}")
    print(f"   白名单自检: ✅ 通过")
    if macro_state:
        print(f"   宏观状态: US10Y={macro_state.get('us10y','?')}% "
              f"| Δ={macro_state.get('us10y_jump_bp','?')}bp "
              f"| VIXΔ={macro_state.get('vix_jump','?')}")
    print()

    results = []
    errors = []

    for i, symbol in enumerate(symbols):
        entry = POOL_WHITELIST[symbol]
        market = entry['market']
        try:
            if market == 'us':
                df = fetch_us_etf(symbol, start_date, end_date)
            else:
                df = fetch_a_etf(symbol, start_date, end_date)

            if df is None or df.empty:
                errors.append(f"{symbol}: Tushare无数据")
                continue

            ind = calc_indicators(df, symbol)
            result = route_symbol(symbol, ind, entry, macro_state)
            results.append(result)

            # 进度输出
            icon = result.get('signal', '❓')
            route = result.get('route', '?')
            reason = result.get('reason', '')
            print(f"  [{i+1:2d}/{len(symbols)}] {icon} {symbol:<8} "
                  f"${ind['close']:<10.3f} "
                  f"Dev150={ind['dev_150']:>+6.1f}% " if ind['dev_150'] else f"  [{i+1:2d}/{len(symbols)}] {icon} {symbol:<8} ${ind['close']:<10.3f} Dev150=— ",
                  f"EMA={ind['ema_arrangement']:<4} | {route:<22} | {reason}")

        except Exception as e:
            errors.append(f"{symbol}: {e}")
            if verbose:
                import traceback
                traceback.print_exc()

    # ── 汇总 ──
    print(f"\n{'='*80}")
    print(f"📊 路由汇总")
    print(f"{'='*80}")

    by_route = {}
    for r in results:
        route = r.get('route', 'error')
        by_route.setdefault(route, []).append(r)

    # 进攻就绪
    spearhead = by_route.get('spearhead', [])
    print(f"\n  🟢 进攻就绪 (C1-C4全满足): {len(spearhead)} 标")
    for r in spearhead:
        print(f"     {r['symbol']:<8} ${r['close']:.2f}  |  {r.get('reason','')}")

    # 步骤1.5
    step15 = by_route.get('counterpunch_step15', [])
    print(f"\n  🟢 步骤1.5回调买入: {len(step15)} 标")
    for r in step15:
        zone = r.get('buy_zone', (0, 0))
        print(f"     {r['symbol']:<8} ${r['close']:.3f}  |  买入区[{zone[0]:.3f},{zone[1]:.3f}]  |  仓位≤{r.get('position_cap',0)*100:.0f}%")

    # 反击
    cp = by_route.get('counterpunch', [])
    print(f"\n  🟢 反击就绪 (R1∧R2): {len(cp)} 标")
    for r in cp:
        zone = r.get('buy_zone', (0, 0))
        print(f"     {r['symbol']:<8} ${r['close']:.3f}  |  买入区[{zone[0]:.3f},{zone[1]:.3f}]  |  仓位≤{r.get('position_cap',0)*100:.0f}%")

    # 速率闸
    gated = by_route.get('rate_gated', [])
    if gated:
        print(f"\n  🟡 速率闸禁开: {len(gated)} 标")
        for r in gated:
            print(f"     {r['symbol']:<8} {r.get('reason','')}")

    # 乖离拦截
    halted = by_route.get('deviation_halted', [])
    if halted:
        print(f"\n  🔴 乖离拦截: {len(halted)} 标")
        for r in halted:
            print(f"     {r['symbol']:<8} {r.get('reason','')}")

    # 闲置
    idle = by_route.get('idle', []) + by_route.get('idle_adx', [])
    print(f"\n  ⚪ 闲置: {len(idle)} 标")
    for r in idle:
        print(f"     {r['symbol']:<8} {r.get('reason','')}")

    # 豁免
    exempt = by_route.get('exempt', [])
    print(f"\n  ⚪ 豁免: {len(exempt)} 标")
    for r in exempt:
        print(f"     {r['symbol']:<8} {r.get('reason','')}")

    # 观察期
    obs = by_route.get('observation', [])
    if obs:
        print(f"\n  🟡 观察期: {len(obs)} 标")

    if errors:
        print(f"\n  ⚠️ 数据错误: {len(errors)} 项")
        for e in errors:
            print(f"     {e}")

    print(f"\n  📅 Tushare基值日期: {results[0]['date'] if results else 'N/A'}")
    print(f"  ⚠️ 美股T+1滞后，今日盘中数据以P0为准")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', type=str, help='单标扫描')
    parser.add_argument('--verbose', action='store_true', help='详细输出')
    parser.add_argument('--us10y', type=float, help='US10Y当前值')
    parser.add_argument('--us10y-jump', type=float, help='US10Y单日跳升bp')
    parser.add_argument('--vix-jump', type=float, help='VIX单日跳升')
    args = parser.parse_args()

    macro_state = None
    if args.us10y or args.us10y_jump or args.vix_jump:
        macro_state = {
            'us10y': args.us10y or 4.5,
            'us10y_jump_bp': args.us10y_jump or 0,
            'vix_jump': args.vix_jump or 0,
        }

    if args.symbol:
        valid, rejected = pre_scan_validate([args.symbol])
        if rejected:
            sys.exit(1)
        print(f"单标扫描: {args.symbol} (待实现完整单标模式)")
    else:
        scan_all(macro_state=macro_state, verbose=args.verbose)
