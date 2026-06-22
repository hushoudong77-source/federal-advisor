#!/usr/bin/env python3
"""
📜 MACD+KDJ+OBV 三指标合体 vs 联邦法典 对比回测引擎 V1.0
签发：守东（资产规划部首席审计官）
生效日期：2026-06-22

目标：对比两套体系的命中率、盈亏比、最大回撤
├── 体系A: 联邦法典反击/进攻路由（现有）
└── 体系B: MACD+KDJ+OBV 三指标合体满分进场（守东体系）

§0 两套体系信号定义
§1 数据获取（Tushare）
§2 技术指标计算（MACD/KDJ/OBV + 法典MA/ATR）
§3 信号识别（体系A + 体系B）
§4 盈亏计算（统一持有期/止损规则）
§5 指标汇总

注意：KDJ/OBV 不入联邦法典路由，此为独立对比回测。
"""

import tushare as ts
import pandas as pd
import numpy as np
import sys
from datetime import datetime, timedelta

# ============================================================
# §0 标的配置
# ============================================================

TICKERS = {
    '513910': {
        'name': '港股通央企红利ETF', 'tushare_code': '513910.SH', 'type': 'fund_daily',
        'anchor': 40, 'k': 4.5,
        'system': 'counterpunch',  # 反击
    },
    '588000': {
        'name': '科创50ETF', 'tushare_code': '588000.SH', 'type': 'fund_daily',
        'anchor': 30, 'k': 5.0,
        'system': 'counterpunch',
    },
    'BBJP': {
        'name': '日股ETF', 'tushare_code': 'BBJP', 'type': 'us_daily',
        'anchor': 40, 'k': 2.5,
        'system': 'counterpunch',
    },
    'QQQ': {
        'name': '纳指100ETF', 'tushare_code': 'QQQ', 'type': 'us_daily',
        'system': 'spearhead',  # 进攻
    },
}

# ============================================================
# §1 数据获取
# ============================================================

def fetch_data(ticker, cfg):
    """从Tushare获取日线数据"""
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = '20180101'  # 从2018年开始，给均线足够预热

    try:
        pro = ts.pro_api()
        ts_code = cfg['tushare_code']

        if cfg['type'] == 'fund_daily':
            df = pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        elif cfg['type'] == 'us_daily':
            df = pro.us_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        else:
            return None

        if df is None or len(df) == 0:
            return None

        df = df.rename(columns={
            'trade_date': 'Date', 'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close', 'vol': 'Volume'
        })
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date').reset_index(drop=True)
        return df

    except Exception as e:
        print(f"  ❌ {ticker} 数据获取失败: {e}")
        return None


# ============================================================
# §2 技术指标计算
# ============================================================

def calc_all_indicators(df, anchor_period=40):
    """计算两套体系所需全部指标"""
    df = df.copy()

    # --- 均线 ---
    df['MA_anchor'] = df['Close'].rolling(window=anchor_period).mean()

    # --- ATR(14) ---
    df['prev_close'] = df['Close'].shift(1)
    df['TR'] = df.apply(
        lambda r: max(r['High'] - r['Low'],
                      abs(r['High'] - r['prev_close']) if pd.notna(r['prev_close']) else 0,
                      abs(r['Low'] - r['prev_close']) if pd.notna(r['prev_close']) else 0),
        axis=1
    )
    df['ATR14'] = df['TR'].rolling(window=14).mean()

    # --- MACD (12, 26, 9) ---
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD_DIF'] = ema12 - ema26
    df['MACD_DEA'] = df['MACD_DIF'].ewm(span=9, adjust=False).mean()
    df['MACD_BAR'] = 2 * (df['MACD_DIF'] - df['MACD_DEA'])

    # MACD金叉/死叉
    df['MACD_cross'] = 0
    for i in range(1, len(df)):
        if df.loc[i, 'MACD_DIF'] > df.loc[i, 'MACD_DEA'] and \
           df.loc[i-1, 'MACD_DIF'] <= df.loc[i-1, 'MACD_DEA']:
            df.loc[i, 'MACD_cross'] = 1  # 金叉
        elif df.loc[i, 'MACD_DIF'] < df.loc[i, 'MACD_DEA'] and \
             df.loc[i-1, 'MACD_DIF'] >= df.loc[i-1, 'MACD_DEA']:
            df.loc[i, 'MACD_cross'] = -1  # 死叉

    # MACD零轴位置
    df['MACD_above_zero'] = (df['MACD_DIF'] > 0) & (df['MACD_DEA'] > 0)

    # --- KDJ (9, 3, 3) ---
    low_9 = df['Low'].rolling(window=9).min()
    high_9 = df['High'].rolling(window=9).max()
    rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
    rsv = rsv.fillna(50)

    df['KDJ_K'] = rsv.ewm(com=2, adjust=False).mean()
    df['KDJ_D'] = df['KDJ_K'].ewm(com=2, adjust=False).mean()
    df['KDJ_J'] = 3 * df['KDJ_K'] - 2 * df['KDJ_D']

    # KDJ金叉/死叉
    df['KDJ_cross'] = 0
    for i in range(1, len(df)):
        if df.loc[i, 'KDJ_K'] > df.loc[i, 'KDJ_D'] and \
           df.loc[i-1, 'KDJ_K'] <= df.loc[i-1, 'KDJ_D']:
            df.loc[i, 'KDJ_cross'] = 1  # 金叉
        elif df.loc[i, 'KDJ_K'] < df.loc[i, 'KDJ_D'] and \
             df.loc[i-1, 'KDJ_K'] >= df.loc[i-1, 'KDJ_D']:
            df.loc[i, 'KDJ_cross'] = -1  # 死叉

    # KDJ超买超卖
    df['KDJ_oversold'] = df['KDJ_J'] < 20
    df['KDJ_overbought'] = df['KDJ_J'] > 80
    # KDJ回调低位（守东体系：「回调后低位金叉」——J从低位回升时的金叉）
    df['KDJ_pullback'] = df['KDJ_J'] < 50  # J<50 = 回调到中低位

    # --- OBV ---
    df['price_dir'] = np.sign(df['Close'].diff())
    df['obv_daily'] = df['Volume'] * df['price_dir']
    df['OBV'] = df['obv_daily'].cumsum()
    df['OBV'] = df['OBV'].fillna(0)

    # OBV 20日新高/新低
    df['OBV_20high'] = df['OBV'].rolling(window=20).max()
    df['OBV_20low'] = df['OBV'].rolling(window=20).min()
    df['OBV_new_high'] = df['OBV'] >= df['OBV_20high']
    df['OBV_new_low'] = df['OBV'] <= df['OBV_20low']

    # OBV背离检测（价新高OBV不跟 = 诱多；价新低OBV不跟 = 诱空）
    df['price_20high'] = df['Close'].rolling(window=20).max()
    df['price_20low'] = df['Close'].rolling(window=20).min()
    df['price_new_high'] = df['Close'] >= df['price_20high']
    df['price_new_low'] = df['Close'] <= df['price_20low']

    df['OBV_bearish_div'] = df['price_new_high'] & ~df['OBV_new_high']  # 价高OBV不跟
    df['OBV_bullish_div'] = df['price_new_low'] & ~df['OBV_new_low']   # 价低OBV不跟

    # OBV趋势（守东体系：「OBV同步走高」——OBV在MA20上方=资金流入趋势）
    df['OBV_MA20'] = df['OBV'].rolling(window=20).mean()
    df['OBV_uptrend'] = df['OBV'] > df['OBV_MA20']

    # --- 20日均量 ---
    df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()
    df['Volume_Ratio'] = df['Volume'] / df['Volume_MA20']

    # --- H20（20日最高，进攻C4用）---
    df['H20'] = df['Close'].rolling(window=20).max()

    # --- 趋势过滤 ---
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA150'] = df['Close'].ewm(span=150, adjust=False).mean()
    df['trend_up'] = df['EMA50'] > df['EMA150']

    return df


# ============================================================
# §3 信号识别
# ============================================================

def identify_signals_system_a(df, cfg):
    """
    体系A: 联邦法典
    - 反击: MA_anchor - k×ATR14 买入区间触发（冷却期30天）
    - 进攻: H20×0.98 买入区间触发（冷却期30天）
    """
    signals = []
    system = cfg['system']

    if system == 'counterpunch':
        anchor = cfg['anchor']
        k = cfg['k']
        cooldown = 30  # 反击冷却期30天
        stop_atr_mult = 2.0
        hold_days = 20

        last_trigger_idx = -999

        for i in range(150, len(df)):  # 跳过前150天给EMA预热
            ma_val = df.loc[i, 'MA_anchor']
            atr_val = df.loc[i, 'ATR14']
            price = df.loc[i, 'Close']

            if pd.isna(ma_val) or pd.isna(atr_val) or atr_val <= 0:
                continue

            zone_lower = ma_val - k * atr_val
            is_in_zone = (zone_lower <= price <= ma_val)

            # 冷却期
            if i - last_trigger_idx <= cooldown:
                is_in_zone = False

            if is_in_zone:
                stop_price = zone_lower - stop_atr_mult * atr_val
                signals.append({
                    'system': 'A_联邦法典',
                    'trigger_idx': i,
                    'trigger_date': df.loc[i, 'Date'],
                    'entry_price': price,
                    'stop_price': stop_price,
                    'hold_days': hold_days,
                })
                last_trigger_idx = i

    elif system == 'spearhead':
        # 进攻：C4 = H20 × 0.98
        cooldown = 30
        hold_days = 30
        stop_atr_mult = 5.0
        last_trigger_idx = -999

        for i in range(150, len(df)):
            h20 = df.loc[i, 'H20']
            price = df.loc[i, 'Close']
            atr_val = df.loc[i, 'ATR14']
            trend_ok = df.loc[i, 'trend_up']  # EMA50 > EMA150

            if pd.isna(h20) or pd.isna(atr_val) or atr_val <= 0:
                continue
            if not trend_ok:
                continue  # 趋势过滤

            c4_price = h20 * 0.98
            is_trigger = (price >= c4_price)

            if i - last_trigger_idx <= cooldown:
                is_trigger = False

            if is_trigger:
                stop_price = price - stop_atr_mult * atr_val
                signals.append({
                    'system': 'A_联邦法典',
                    'trigger_idx': i,
                    'trigger_date': df.loc[i, 'Date'],
                    'entry_price': price,
                    'stop_price': stop_price,
                    'hold_days': hold_days,
                })
                last_trigger_idx = i

    return signals


def identify_signals_system_b(df, cfg):
    """
    体系B: MACD+KDJ+OBV 三指标合体满分进场
    满分条件（三者同时满足）：
      1. MACD: 双线站稳零轴上方（MACD_above_zero = True）
      2. KDJ: 低位金叉（J<20 + K上穿D）
      3. OBV: 同步新高（OBV创20日新高）

    离场条件（任一触发）：
      1. MACD高位死叉
      2. KDJ高位死叉（J>80 + K下穿D）
      3. OBV背离（价新高OBV不跟）

    冷却期：30天（与法典统一）
    """
    signals = []
    cooldown = 30
    hold_days = 20  # 默认持有期
    stop_atr_mult = 2.0  # 止损ATR倍数（与反击统一）
    last_trigger_idx = -999

    for i in range(150, len(df)):
        price = df.loc[i, 'Close']
        atr_val = df.loc[i, 'ATR14']

        if pd.isna(atr_val) or atr_val <= 0:
            continue

        # 满分进场三条件（守东体系）
        c1_macd = df.loc[i, 'MACD_above_zero']  # MACD零轴上方（管大方向）
        c2_kdj = df.loc[i, 'KDJ_cross'] == 1   # KDJ金叉（管时机）
        c3_obv = df.loc[i, 'OBV_uptrend']       # OBV上行趋势（管真假）

        all_conditions = c1_macd and c2_kdj and c3_obv

        # 冷却期
        if i - last_trigger_idx <= cooldown:
            all_conditions = False

        if all_conditions:
            stop_price = price - stop_atr_mult * atr_val
            signals.append({
                'system': 'B_MACD_KDJ_OBV',
                'trigger_idx': i,
                'trigger_date': df.loc[i, 'Date'],
                'entry_price': price,
                'stop_price': stop_price,
                'hold_days': hold_days,
                'entry_conditions': {
                    'MACD_above_zero': c1_macd,
                    'KDJ_golden_cross': c2_kdj,
                    'OBV_uptrend': c3_obv,
                }
            })
            last_trigger_idx = i

    return signals


# ============================================================
# §4 盈亏计算（统一规则）
# ============================================================

def calc_signal_results(signals, df, ticker_name):
    """
    统一盈亏计算规则：
    - 持有期到期 → 按收盘价离场
    - 止损触发（盘中最低价 ≤ 止损价）→ 按止损价离场
    - 离场条件（体系B专用）：MACD死叉/KDJ死叉/OBV背离 → 提前离场
    """
    results = []

    for sig in signals:
        idx_entry = sig['trigger_idx']
        p_entry = sig['entry_price']
        p_stop = sig['stop_price']
        h = sig['hold_days']

        exit_price = None
        exit_date = None
        exit_reason = None

        for d in range(1, h + 1):
            idx_current = idx_entry + d

            if idx_current >= len(df):
                exit_price = df.loc[len(df)-1, 'Close']
                exit_date = df.loc[len(df)-1, 'Date']
                exit_reason = 'DATA_END'
                break

            p_low = df.loc[idx_current, 'Low']
            p_close = df.loc[idx_current, 'Close']
            date_current = df.loc[idx_current, 'Date']

            # 止损优先
            if p_low <= p_stop:
                exit_price = p_stop
                exit_date = date_current
                exit_reason = 'STOP_LOSS'
                break

            # 体系B专属离场条件（MACD死叉/KDJ死叉/OBV背离）
            if sig['system'] == 'B_MACD_KDJ_OBV':
                macd_dead = (df.loc[idx_current, 'MACD_cross'] == -1)
                kdj_dead = (df.loc[idx_current, 'KDJ_overbought'] and
                           df.loc[idx_current, 'KDJ_cross'] == -1)
                obv_diverge = df.loc[idx_current, 'OBV_bearish_div']

                if macd_dead or kdj_dead or obv_diverge:
                    exit_price = p_close
                    exit_date = date_current
                    reasons = []
                    if macd_dead: reasons.append('MACD死叉')
                    if kdj_dead: reasons.append('KDJ高位死叉')
                    if obv_diverge: reasons.append('OBV背离')
                    exit_reason = 'EXIT_' + '+'.join(reasons)
                    break

            # 持有期满
            if d == h:
                exit_price = p_close
                exit_date = date_current
                exit_reason = 'TIME_EXIT'

        # 计算收益率
        if exit_price is not None:
            ret_pct = (exit_price - p_entry) / p_entry * 100
        else:
            ret_pct = None

        results.append({
            **sig,
            'exit_price': exit_price,
            'exit_date': exit_date,
            'exit_reason': exit_reason,
            'return_pct': ret_pct,
        })

    return results


# ============================================================
# §5 指标汇总
# ============================================================

def calc_summary(results, system_name):
    """计算一套体系的汇总指标"""
    valid = [r for r in results if r['result'] is not None and r['return_pct'] is not None]
    total = len(valid)

    if total == 0:
        return {
            'system': system_name,
            'total_signals': 0,
            'win_rate': 0.0,
            'avg_return': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'profit_factor': 0.0,
            'max_win': 0.0,
            'max_loss': 0.0,
            'max_consec_loss': 0,
            'sharpe_approx': 0.0,
            'signals': [],
        }

    wins = [r for r in valid if r['return_pct'] > 0]
    losses = [r for r in valid if r['return_pct'] <= 0]
    stops = [r for r in valid if r['exit_reason'] == 'STOP_LOSS']

    win_rate = len(wins) / total

    avg_return = np.mean([r['return_pct'] for r in valid])
    avg_win = np.mean([r['return_pct'] for r in wins]) if wins else 0.0
    avg_loss = np.mean([r['return_pct'] for r in losses]) if losses else 0.0

    total_win = sum([r['return_pct'] for r in wins])
    total_loss = abs(sum([r['return_pct'] for r in losses]))
    pf = total_win / total_loss if total_loss > 0 else (float('inf') if total_win > 0 else 0.0)

    max_win = max([r['return_pct'] for r in wins]) if wins else 0.0
    max_loss = min([r['return_pct'] for r in losses]) if losses else 0.0

    # 最大连续亏损
    max_consec = 0
    cur = 0
    for r in valid:
        if r['return_pct'] <= 0:
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0

    # 近似夏普（无风险利率假设为0）
    returns = [r['return_pct'] for r in valid]
    sharpe = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0.0

    return {
        'system': system_name,
        'total_signals': total,
        'win_rate': win_rate,
        'avg_return': avg_return,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_factor': pf,
        'max_win': max_win,
        'max_loss': max_loss,
        'max_consec_loss': max_consec,
        'sharpe_approx': sharpe,
        'signals': valid,
    }


def add_result_tag(results):
    """给每条信号打上 WIN/LOSS/STOP 标签"""
    for r in results:
        if r['return_pct'] is None:
            r['result'] = 'NO_DATA'
        elif r['exit_reason'] and r['exit_reason'].startswith('STOP'):
            r['result'] = 'STOP'
        elif r['return_pct'] > 0:
            r['result'] = 'WIN'
        else:
            r['result'] = 'LOSS'
    return results


# ============================================================
# §6 主回测函数
# ============================================================

def run_comparison(ticker, cfg, verbose=True):
    """单标的双体系对比回测"""
    if verbose:
        print(f"\n{'='*70}")
        print(f"  [{ticker}] {cfg['name']} — 双体系对比回测")
        print(f"{'='*70}")

    # 取数
    df = fetch_data(ticker, cfg)
    if df is None or len(df) < 200:
        if verbose:
            print(f"  ❌ 数据不足，跳过")
        return None

    # 计算全部指标
    anchor = cfg.get('anchor', 40)
    df = calc_all_indicators(df, anchor_period=anchor)
    df = df.dropna(subset=['MA_anchor', 'ATR14', 'MACD_DIF', 'KDJ_K']).reset_index(drop=True)

    if len(df) < 100:
        if verbose:
            print(f"  ❌ 指标计算后数据不足，跳过")
        return None

    # 过滤到2019-01-01之后（给指标足够预热）
    df = df[df['Date'] >= '2019-01-01'].reset_index(drop=True)
    if len(df) < 50:
        if verbose:
            print(f"  ❌ 2019年后数据不足，跳过")
        return None

    if verbose:
        print(f"  📊 回测窗口: {df.iloc[0]['Date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['Date'].strftime('%Y-%m-%d')}")
        print(f"     总交易日: {len(df)}")

    # 体系A信号
    sigs_a = identify_signals_system_a(df, cfg)
    sigs_a = calc_signal_results(sigs_a, df, cfg['name'])
    sigs_a = add_result_tag(sigs_a)
    summary_a = calc_summary(sigs_a, 'A_联邦法典')

    # 体系B信号
    sigs_b = identify_signals_system_b(df, cfg)
    sigs_b = calc_signal_results(sigs_b, df, cfg['name'])
    sigs_b = add_result_tag(sigs_b)
    summary_b = calc_summary(sigs_b, 'B_MACD_KDJ_OBV')

    # 打印对比表
    if verbose:
        print(f"\n  {'指标':<20} {'联邦法典(A)':>15} {'三指标合体(B)':>15} {'差异':>10}")
        print(f"  {'-'*60}")
        print(f"  {'总信号数':<20} {summary_a['total_signals']:>15} {summary_b['total_signals']:>15}")
        print(f"  {'命中率':<20} {summary_a['win_rate']*100:>14.1f}% {summary_b['win_rate']*100:>14.1f}% "
              f"{'+' if summary_b['win_rate'] >= summary_a['win_rate'] else ''}"
              f"{(summary_b['win_rate'] - summary_a['win_rate'])*100:>9.1f}pp")
        print(f"  {'平均收益率':<20} {summary_a['avg_return']:>14.2f}% {summary_b['avg_return']:>14.2f}% "
              f"{summary_b['avg_return'] - summary_a['avg_return']:>+9.2f}%")
        print(f"  {'平均盈利':<20} {summary_a['avg_win']:>14.2f}% {summary_b['avg_win']:>14.2f}%")
        print(f"  {'平均亏损':<20} {summary_a['avg_loss']:>14.2f}% {summary_b['avg_loss']:>14.2f}%")
        print(f"  {'盈亏比(PF)':<20} {summary_a['profit_factor']:>14.2f} {summary_b['profit_factor']:>14.2f}")
        print(f"  {'最大盈利':<20} {summary_a['max_win']:>14.2f}% {summary_b['max_win']:>14.2f}%")
        print(f"  {'最大亏损':<20} {summary_a['max_loss']:>14.2f}% {summary_b['max_loss']:>14.2f}%")
        print(f"  {'最大连亏':<20} {summary_a['max_consec_loss']:>15} {summary_b['max_consec_loss']:>15}")
        print(f"  {'近似夏普':<20} {summary_a['sharpe_approx']:>14.3f} {summary_b['sharpe_approx']:>14.3f}")

        # 列出体系B最近5笔
        if summary_b['signals']:
            recent = summary_b['signals'][-5:]
            print(f"\n  📋 体系B最近5笔信号:")
            for r in recent:
                emoji = '🟢' if r['result'] == 'WIN' else ('🔴' if r['result'] in ('STOP', 'LOSS') else '⚪')
                conditions = r.get('entry_conditions', {})
                cond_str = f"MACD={conditions.get('MACD_above_zero','?')} KDJ金叉={conditions.get('KDJ_golden_cross','?')} OBV↑={conditions.get('OBV_uptrend','?')}"
                print(f"     {emoji} {r['trigger_date'].strftime('%Y-%m-%d')} "
                      f"入{r['entry_price']:.2f} → {r['exit_date'].strftime('%Y-%m-%d')} "
                      f"出{r['exit_price']:.2f} ({r['return_pct']:+.2f}%) [{r['exit_reason']}]")
                print(f"        条件: {cond_str}")

        # 信号重叠分析
        a_dates = set(r['trigger_date'] for r in sigs_a if r['result'] not in ('NO_DATA',))
        b_dates = set(r['trigger_date'] for r in sigs_b if r['result'] not in ('NO_DATA',))
        overlap = a_dates & b_dates
        a_only = a_dates - b_dates
        b_only = b_dates - a_dates
        print(f"\n  🔗 信号重叠分析:")
        print(f"     仅A触发: {len(a_only)}笔 | 仅B触发: {len(b_only)}笔 | 同时触发: {len(overlap)}笔")

    return {
        'ticker': ticker,
        'name': cfg['name'],
        'system_type': cfg.get('system', 'counterpunch'),
        'summary_a': summary_a,
        'summary_b': summary_b,
        'signals_a': sigs_a,
        'signals_b': sigs_b,
        'a_only': len(a_only),
        'b_only': len(b_only),
        'overlap': len(overlap),
    }


# ============================================================
# §7 全量汇总
# ============================================================

def print_grand_summary(all_results):
    """打印全量汇总对比表"""
    print(f"\n{'='*80}")
    print(f"  🏆 全量汇总 — MACD+KDJ+OBV vs 联邦法典")
    print(f"{'='*80}")

    # 汇总所有标的的信号
    all_a_signals = []
    all_b_signals = []

    for r in all_results:
        if r is None:
            continue
        all_a_signals.extend(r['summary_a']['signals'])
        all_b_signals.extend(r['summary_b']['signals'])

    # 体系A汇总
    total_a = len(all_a_signals)
    wins_a = sum(1 for s in all_a_signals if s['return_pct'] > 0)
    hr_a = wins_a / total_a if total_a > 0 else 0
    avg_ret_a = np.mean([s['return_pct'] for s in all_a_signals]) if total_a > 0 else 0

    # 体系B汇总
    total_b = len(all_b_signals)
    wins_b = sum(1 for s in all_b_signals if s['return_pct'] > 0)
    hr_b = wins_b / total_b if total_b > 0 else 0
    avg_ret_b = np.mean([s['return_pct'] for s in all_b_signals]) if total_b > 0 else 0

    print(f"\n  {'指标':<20} {'联邦法典(A)':>15} {'三指标合体(B)':>15} {'差异':>10}")
    print(f"  {'-'*60}")
    print(f"  {'总信号数':<20} {total_a:>15} {total_b:>15}")
    print(f"  {'命中率':<20} {hr_a*100:>14.1f}% {hr_b*100:>14.1f}% "
          f"{'+' if hr_b >= hr_a else ''}{(hr_b - hr_a)*100:>9.1f}pp")
    print(f"  {'平均收益率':<20} {avg_ret_a:>14.2f}% {avg_ret_b:>14.2f}% "
          f"{avg_ret_b - avg_ret_a:>+9.2f}%")

    # 逐标对比表
    print(f"\n  {'标的':<10} {'类型':<8} {'A信号':>6} {'A命中率':>8} {'B信号':>6} {'B命中率':>8} {'B-A(pp)':>9}")
    print(f"  {'-'*60}")
    for r in all_results:
        if r is None:
            continue
        sa = r['summary_a']
        sb = r['summary_b']
        diff = (sb['win_rate'] - sa['win_rate']) * 100
        print(f"  {r['ticker']:<10} {r['system_type']:<8} "
              f"{sa['total_signals']:>6} {sa['win_rate']*100:>7.1f}% "
              f"{sb['total_signals']:>6} {sb['win_rate']*100:>7.1f}% "
              f"{diff:>+8.1f}pp")


# ============================================================
# §8 入口
# ============================================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='MACD+KDJ+OBV vs 联邦法典 对比回测')
    parser.add_argument('--ticker', type=str, help='单标回测（如 513910）')
    parser.add_argument('--all', action='store_true', help='全量4标回测')
    parser.add_argument('--quiet', action='store_true', help='安静模式（仅汇总）')
    args = parser.parse_args()

    if args.ticker:
        tickers = {args.ticker: TICKERS[args.ticker]}
    elif args.all:
        tickers = TICKERS
    else:
        # 默认：全量
        tickers = TICKERS

    all_results = []

    for ticker, cfg in tickers.items():
        result = run_comparison(ticker, cfg, verbose=not args.quiet)
        all_results.append(result)

    # 多标时打印全量汇总
    if len(tickers) > 1:
        print_grand_summary(all_results)

    print(f"\n✅ 回测完成")
