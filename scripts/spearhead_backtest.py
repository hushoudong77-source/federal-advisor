#!/usr/bin/env python3
"""
📜 进攻策略回测引擎 — Spearhead Backtest Engine V1.0
签发：联邦投顾（资产审计官）
生效日期：2026-05-29

目标标的：513180（恒生科技ETF）
回测框架：C1-C4四条件 + 攻击窗口 + 5.0×ATR追踪止损
数据源：Tushare fund_daily
"""

import tushare as ts
import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime, timedelta

# ============================================================
# 配置区
# ============================================================

TICKER = '513180'
TUSHARE_CODE = '513180.SH'
DATA_TYPE = 'fund_daily'
NAME = '恒生科技ETF易方达'

# 进攻参数（V5.8.2r28.2初始值）
ATR_MULT = 5.0        # 追踪止损乘数
C3_CUSHION = 0.0      # C3容差（r27.4回退至无容差）
C4_THRESHOLD = 0.98   # C4突破阈值 H20×0.98
VOL_THRESHOLD = 0.8   # 量能阈值 MA20_V×0.8
ATR_VOL_THRESHOLD = 1.1  # 波动率豁免阈值 ATR14_MA20×1.1

# 攻击窗口
WINDOW_DAYS = 2       # 2个交易日

# 仓位假设
ACCOUNT_VALUE = 100000  # 假设账户100K，用百分比算即可
POSITION_PCT = 0.10     # 10%仓位


def fetch_data():
    """获取Tushare日线"""
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = '20200101'  # 多拉一些确保150EMA
    
    pro = ts.pro_api()
    
    if DATA_TYPE == 'fund_daily':
        df = pro.fund_daily(ts_code=TUSHARE_CODE, start_date=start_date, end_date=end_date)
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


def calc_indicators(df):
    """计算进攻策略所需全部技术指标"""
    df = df.copy()
    
    # EMA
    df['EMA30'] = df['Close'].ewm(span=30, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA150'] = df['Close'].ewm(span=150, adjust=False).mean()
    
    # MA20（用于量能计算）
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA20_V'] = df['Volume'].rolling(window=20).mean()
    
    # H20 — 前20日最高收盘价
    df['H20'] = df['Close'].rolling(window=20).max().shift(1)  # 不含当日
    
    # ATR(14)
    df['prev_close'] = df['Close'].shift(1)
    df['TR'] = df.apply(
        lambda r: max(
            r['High'] - r['Low'],
            abs(r['High'] - r['prev_close']) if pd.notna(r['prev_close']) else 0,
            abs(r['Low'] - r['prev_close']) if pd.notna(r['prev_close']) else 0
        ), axis=1
    )
    df['ATR14'] = df['TR'].rolling(window=14).mean()
    df['ATR14_MA20'] = df['ATR14'].rolling(window=20).mean()
    
    # EMA过渡区（±0.3%）
    df['C1_raw'] = (df['EMA50'] - df['EMA150']) / df['EMA150'] * 100
    df['C2_raw'] = (df['EMA30'] - df['EMA50']) / df['EMA50'] * 100
    
    return df


def check_c1_c2_with_buffer(prev_c1, prev_c2, c1_raw, c2_raw):
    """
    EMA过渡区逻辑（±0.3%缓冲区）
    差值∈[-0.3%, +0.3%] → 维持上一交易日状态
    """
    c1 = prev_c1
    if c1_raw > 0.3:
        c1 = True
    elif c1_raw < -0.3:
        c1 = False
    # else: 维持prev_c1
    
    c2 = prev_c2
    if c2_raw > 0.3:
        c2 = True
    elif c2_raw < -0.3:
        c2 = False
    
    return c1, c2


def run_backtest(df):
    """执行进攻策略全量回测"""
    n = len(df)
    if n < 200:
        return []
    
    trades = []
    
    # 状态变量
    c1, c2 = False, False
    in_attack = False          # ATTACK_LOCKED状态
    attack_entry_price = 0.0
    attack_entry_idx = -1
    attack_entry_date = None
    trail_stop = 0.0
    highest_since_entry = 0.0
    
    # 攻击窗口
    window_active = False
    window_end_idx = -1
    c4_trigger_idx = -1
    c4_trigger_date = None
    
    # 统计
    for i in range(200, n):  # 从第200行开始（确保所有指标稳定）
        close = df.loc[i, 'Close']
        date = df.loc[i, 'Date']
        ema30 = df.loc[i, 'EMA30']
        ema50 = df.loc[i, 'EMA50']
        ema150 = df.loc[i, 'EMA150']
        atr14 = df.loc[i, 'ATR14']
        h20 = df.loc[i, 'H20']
        volume = df.loc[i, 'Volume']
        ma20_v = df.loc[i, 'MA20_V']
        atr14_ma20 = df.loc[i, 'ATR14_MA20']
        
        # 跳过指标未就绪
        if pd.isna(ema150) or pd.isna(atr14) or pd.isna(h20):
            continue
        
        # --- 更新C1/C2（含过渡区） ---
        c1_raw = df.loc[i, 'C1_raw']
        c2_raw = df.loc[i, 'C2_raw']
        c1, c2 = check_c1_c2_with_buffer(c1, c2, c1_raw, c2_raw)
        
        # C3: C > 50EMA（无容差）
        c3 = close > ema50
        
        # --- 如果已在持仓中 ---
        if in_attack:
            # 更新最高价
            if close > highest_since_entry:
                highest_since_entry = close
                trail_stop = highest_since_entry - ATR_MULT * atr14
            
            # 检查离场条件
            exit_reason = None
            
            # SRC-1: 追踪止损
            if close <= trail_stop:
                exit_reason = 'SRC-1 追踪止损'
            
            # SRC-2: 8%硬止损
            pnl_pct = (close - attack_entry_price) / attack_entry_price
            if pnl_pct <= -0.08:
                exit_reason = 'SRC-2 硬止损(-8%)'
            
            # SRC-3: C1/C2反转
            if not c1 or not c2:
                exit_reason = 'SRC-3 C1/C2反转'
            
            # SRC-6: -15%绝对底线
            if pnl_pct <= -0.15:
                exit_reason = 'SRC-6 绝对底线(-15%)'
            
            if exit_reason:
                hold_days = (date - attack_entry_date).days
                trade = {
                    'entry_date': attack_entry_date,
                    'entry_price': round(attack_entry_price, 4),
                    'exit_date': date,
                    'exit_price': round(close, 4),
                    'pnl_pct': round(pnl_pct * 100, 2),
                    'hold_days': hold_days,
                    'exit_reason': exit_reason,
                }
                trades.append(trade)
                
                in_attack = False
                window_active = False
                # 冷却期（r27.4已删除，但这里保留作为统计）
                continue
        
        # --- 非持仓状态：检查进攻信号 ---
        
        # C1 ∧ C2 ∧ C3 前置条件
        if not (c1 and c2 and c3):
            # 窗口期内C1/C2/C3失效 → 窗口关闭
            if window_active:
                window_active = False
            continue
        
        # 异常波动过滤（单日涨跌幅>30%跳过）
        if i > 0:
            prev_close = df.loc[i-1, 'Close']
            pct_change = abs(close - prev_close) / prev_close
            if pct_change > 0.30:
                if window_active:
                    window_active = False
                continue
        
        # C4突破确认
        c4_price = (close >= h20 * C4_THRESHOLD)
        c4_vol = (volume > ma20_v * VOL_THRESHOLD)
        c4_atr = (atr14 < atr14_ma20 * ATR_VOL_THRESHOLD)
        
        c4 = c4_price and (c4_vol or c4_atr)
        
        if c4 and not window_active:
            # 🟢 进攻触发 + 开启攻击窗口
            window_active = True
            window_end_idx = i + WINDOW_DAYS
            c4_trigger_idx = i
            c4_trigger_date = date
        
        # 攻击窗口期内首次开火
        if window_active and i <= window_end_idx:
            if not in_attack:
                # 窗口期内C1/C2/C3仍满足 → 执行开火
                if c1 and c2 and c3:
                    # 开火
                    attack_entry_price = close
                    attack_entry_idx = i
                    attack_entry_date = date
                    highest_since_entry = close
                    trail_stop = close - ATR_MULT * atr14
                    in_attack = True
                    window_active = False  # 单次窗口1次开火权
    
    return trades


def calc_metrics(trades, df):
    """计算绩效指标"""
    if len(trades) == 0:
        return {}
    
    total_pnl_pct = sum(t['pnl_pct'] for t in trades)
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    win_rate = len(wins) / len(trades) * 100
    
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
    
    avg_hold = np.mean([t['hold_days'] for t in trades])
    max_hold = max(t['hold_days'] for t in trades)
    
    # 期望值
    expectancy = (win_rate/100 * avg_win) + ((1-win_rate/100) * avg_loss)
    
    # 最大连续亏损
    seq = 0
    max_seq = 0
    for t in trades:
        if t['pnl_pct'] <= 0:
            seq += 1
            max_seq = max(max_seq, seq)
        else:
            seq = 0
    
    # 最大回撤（简单版：从峰值回撤）
    equity = 100
    peak = 100
    max_dd = 0
    for t in trades:
        equity *= (1 + t['pnl_pct'] / 100)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)
    
    # CAGR（年化）
    if len(df) > 0:
        years = (df['Date'].max() - df['Date'].min()).days / 365.25
        final_equity = 100
        for t in trades:
            final_equity *= (1 + t['pnl_pct'] / 100)
        cagr = (final_equity / 100) ** (1 / years) - 1 if years > 0 else 0
    else:
        cagr = 0
    
    return {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(win_rate, 1),
        'total_pnl_pct': round(total_pnl_pct, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'avg_hold_days': round(avg_hold, 1),
        'max_hold_days': max_hold,
        'expectancy': round(expectancy, 2),
        'max_consec_losses': max_seq,
        'max_drawdown_pct': round(max_dd, 2),
        'cagr_pct': round(cagr * 100, 2),
    }


def print_report(ticker, name, trades, metrics, df):
    """输出回测报告"""
    first_date = df['Date'].min().strftime('%Y-%m-%d')
    last_date = df['Date'].max().strftime('%Y-%m-%d')
    years = (df['Date'].max() - df['Date'].min()).days / 365.25
    
    print(f"\n{'='*60}")
    print(f"  📊 进攻策略回测报告 — {name} ({ticker})")
    print(f"{'='*60}")
    print(f"  数据范围: {first_date} ~ {last_date} ({years:.1f}年)")
    print(f"  总交易日: {len(df)}")
    print(f"  参数: ATR乘数={ATR_MULT}×, C4阈值=H20×{C4_THRESHOLD}, 量能阈值=MA20_V×{VOL_THRESHOLD}")
    print(f"  攻击窗口: {WINDOW_DAYS}个交易日")
    print(f"{'='*60}")
    
    if len(trades) == 0:
        print("  ⚠️ 零交易记录 — 策略未触发任何进攻信号")
        return
    
    print(f"\n  📈 核心绩效")
    print(f"  ├── 总交易笔数: {metrics['total_trades']}")
    print(f"  ├── 盈利笔数: {metrics['wins']} | 亏损笔数: {metrics['losses']}")
    print(f"  ├── 胜率: {metrics['win_rate']}%")
    print(f"  ├── 总收益率(单利): {metrics['total_pnl_pct']}%")
    print(f"  ├── CAGR(年化): {metrics['cagr_pct']}%")
    print(f"  ├── 平均盈利: +{metrics['avg_win']}%")
    print(f"  ├── 平均亏损: {metrics['avg_loss']}%")
    print(f"  ├── 期望值: {metrics['expectancy']}%")
    print(f"  ├── 平均持仓: {metrics['avg_hold_days']}天")
    print(f"  ├── 最长持仓: {metrics['max_hold_days']}天")
    print(f"  ├── 最大连续亏损: {metrics['max_consec_losses']}笔")
    print(f"  └── 最大回撤: {metrics['max_drawdown_pct']}%")
    
    # 按离场原因分组
    reasons = {}
    for t in trades:
        r = t['exit_reason']
        if r not in reasons:
            reasons[r] = {'count': 0, 'wins': 0, 'total_pnl': 0}
        reasons[r]['count'] += 1
        reasons[r]['total_pnl'] += t['pnl_pct']
        if t['pnl_pct'] > 0:
            reasons[r]['wins'] += 1
    
    print(f"\n  🚪 离场原因分布")
    for r, v in sorted(reasons.items(), key=lambda x: -x[1]['count']):
        wr = v['wins']/v['count']*100 if v['count'] > 0 else 0
        print(f"  ├── {r}: {v['count']}笔 (胜率{wr:.0f}%, 总收益{v['total_pnl']:+.1f}%)")
    
    # 最近10笔交易
    print(f"\n  📋 最近10笔交易")
    print(f"  {'入场日期':<12} {'入场价':<8} {'出场日期':<12} {'出场价':<8} {'盈亏%':<8} {'持仓天':<6} {'原因':<20}")
    print(f"  {'─'*70}")
    recent = trades[-10:] if len(trades) > 10 else trades
    for t in recent:
        print(f"  {t['entry_date'].strftime('%Y-%m-%d'):<12} {t['entry_price']:<8} "
              f"{t['exit_date'].strftime('%Y-%m-%d'):<12} {t['exit_price']:<8} "
              f"{t['pnl_pct']:>+6.2f}% {t['hold_days']:<6} {t['exit_reason'][:20]:<20}")
    
    # 年度分布
    trades_df = pd.DataFrame(trades)
    trades_df['year'] = trades_df['entry_date'].dt.year
    yearly = trades_df.groupby('year').agg(
        笔数=('pnl_pct', 'count'),
        胜率=('pnl_pct', lambda x: (x>0).sum()/len(x)*100),
        总收益=('pnl_pct', 'sum')
    ).round(2)
    
    print(f"\n  📅 年度分布")
    print(f"  {'年份':<8} {'笔数':<6} {'胜率%':<8} {'总收益%':<10}")
    print(f"  {'─'*32}")
    for yr, row in yearly.iterrows():
        print(f"  {int(yr):<8} {int(row['笔数']):<6} {row['胜率']:<8} {row['总收益']:<+10.2f}")
    
    print(f"\n  {'='*60}")
    print(f"  ✅ 回测完成")
    print(f"  {'='*60}\n")


def main():
    print(f"🔄 正在获取{TICKER}数据...")
    df = fetch_data()
    
    if df is None or len(df) < 200:
        print(f"❌ 数据获取失败或数据不足")
        return
    
    print(f"✅ 获取完成: {len(df)}行 ({df['Date'].min().strftime('%Y-%m-%d')} ~ {df['Date'].max().strftime('%Y-%m-%d')})")
    
    print(f"🔄 计算技术指标...")
    df = calc_indicators(df)
    
    print(f"🔄 执行进攻策略回测...")
    trades = run_backtest(df)
    
    metrics = calc_metrics(trades, df)
    
    print_report(TICKER, NAME, trades, metrics, df)
    
    # 额外：参数敏感性测试（锚线MA20不变，测试不同ATR乘数）
    print(f"\n{'='*60}")
    print(f"  🔬 参数敏感性测试 — ATR乘数遍历")
    print(f"{'='*60}")
    
    for atr_mult in [3.0, 4.0, 5.0, 6.0, 7.0]:
        global ATR_MULT
        org_atr = ATR_MULT
        ATR_MULT = atr_mult
        t = run_backtest(df)
        m = calc_metrics(t, df)
        if m:
            print(f"  ATR {atr_mult}×: {m['total_trades']}笔 | 胜率{m['win_rate']}% | 收益{m['total_pnl_pct']:>+7.2f}% | "
                  f"CAGR {m['cagr_pct']}% | 回撤{m['max_drawdown_pct']}% | 期望{m['expectancy']}")
        ATR_MULT = org_atr


if __name__ == '__main__':
    main()
