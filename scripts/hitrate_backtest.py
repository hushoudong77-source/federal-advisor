#!/usr/bin/env python3
"""
📜 命中率回测引擎 — 法典嵌入版 V2.0
签发：守东（资产规划部首席审计官）
生效日期：2026-05-24

全量回测L1/L2反击策略标的，输出命中率(HR)+区间覆盖率(CR)双指标。

§0 定义：独立信号识别 + 持有期/止损双通道盈亏计算
§6 持有期差异化配置表内置
"""

import tushare as ts
import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime, timedelta

# ============================================================
# §6 标的配置表（持有期差异化 + 锚线/k参数）
# 真源：V5.8.2r27 法典 + r27校准 + 走廊测试裁决
# ============================================================

TICKER_CONFIG = {
    # === A股 ===
    '513910': {
        'name': '港股通央企红利ETF',
        'anchor': 40, 'k': 4.5, 'hold_days': 20,
        'tushare_code': '513910.SH', 'type': 'fund_daily',
        'tier': 'L1红利', 'note': 'r28 CR修正：锚线MA20→MA40，k维持4.5'
    },
    '159302': {
        'name': '恒生红利ETF',
        'anchor': 40, 'k': 4.0, 'hold_days': 20,
        'tushare_code': '159302.SZ', 'type': 'fund_daily',
        'tier': 'L1红利', 'note': '豁免分批，一次性建仓'
    },
    '588000': {
        'name': '科创50ETF',
        'anchor': 30, 'k': 5.0, 'hold_days': 10,
        'tushare_code': '588000.SH', 'type': 'fund_daily',
        'tier': 'L2成长', 'note': 'r28 CR修正：维持MA30×5.0，加码RSI(14)<40前置过滤'
    },
    '513770': {
        'name': '港股小盘ETF',
        'anchor': 40, 'k': 1.5, 'hold_days': 10,
        'tushare_code': '513770.SH', 'type': 'fund_daily',
        'tier': 'L2成长', 'note': 'r28 CR修正：锚线MA20→MA40，k=2.5→1.5'
    },
    '510500': {
        'name': '中证500ETF',
        'anchor': 60, 'k': 3.5, 'hold_days': 15,
        'tushare_code': '510500.SH', 'type': 'fund_daily',
        'tier': 'L3宽基', 'note': 'r28 CR修正：k=5.0→3.5，反击资格待审计（附带条件）'
    },
    # === 美股 ===
    'VTI': {
        'name': '美股全市场ETF',
        'anchor': 60, 'k': 4.0, 'hold_days': 15,
        'tushare_code': 'VTI', 'type': 'us_daily',
        'tier': 'L2发达', 'note': ''
    },
    'VEA': {
        'name': '发达市场ETF',
        'anchor': 60, 'k': 4.0, 'hold_days': 15,
        'tushare_code': 'VEA', 'type': 'us_daily',
        'tier': 'L2发达', 'note': ''
    },
    'BBJP': {
        'name': '日股ETF',
        'anchor': 40, 'k': 2.5, 'hold_days': 15,
        'tushare_code': 'BBJP', 'type': 'us_daily',
        'tier': 'L2发达', 'note': '日股夜间跳空多'
    },
    'MUFG': {
        'name': '三菱日联金融',
        'anchor': 40, 'k': 1.0, 'hold_days': 20,
        'tushare_code': 'MUFG', 'type': 'us_daily',
        'tier': 'L2发达', 'note': '银行低波动'
    },
    'VNM': {
        'name': '越南ETF',
        'anchor': 20, 'k': 1.0, 'hold_days': 10,
        'tushare_code': 'VNM', 'type': 'us_daily',
        'tier': 'L2新兴', 'note': '高波动'
    },
    'FLIN': {
        'name': '印度ETF',
        'anchor': 20, 'k': 1.0, 'hold_days': 10,
        'tushare_code': 'FLIN', 'type': 'us_daily',
        'tier': 'L2新兴', 'note': '高波动，暂停降仓'
    },
}

# 已剥夺反击资格，但保留配置供参考/历史比较
DEPRIVED = {
    'EWY': {'name': '韩国ETF', 'reason': '走廊测试裁决：全区间负Sharpe'},
    'SMIN': {'name': '印度小盘ETF', 'reason': 'Step 3回测裁决：PF=0.93'},
}

# 金盾体系，不适用反击回测
GOLD_SHIELD = ['IAU', '518880']

# 进攻专用标的，不适用反击回测
ATTACK_ONLY = ['QQQ', 'IVV']

# ============================================================
# §0.2 数据获取
# ============================================================

def fetch_data(ticker, cfg, years=3):
    """从Tushare获取日线数据，含OHLCV"""
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=years*365 + 200)).strftime('%Y%m%d')
    
    try:
        pro = ts.pro_api()
        
        if cfg['type'] == 'fund_daily':
            df = pro.fund_daily(ts_code=cfg['tushare_code'], 
                                start_date=start_date, end_date=end_date)
        elif cfg['type'] == 'us_daily':
            df = pro.us_daily(ts_code=cfg['tushare_code'],
                              start_date=start_date, end_date=end_date)
        else:
            return None
        
        if df is None or len(df) == 0:
            return None
        
        # 统一列名
        df = df.rename(columns={
            'trade_date': 'Date', 'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close', 'vol': 'Volume'
        })
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date').reset_index(drop=True)
        
        return df
    
    except Exception as e:
        print(f"  ⚠️ {ticker} 获取失败: {e}")
        return None


def calc_technical_indicators(df, anchor_period):
    """计算ATR(14)、MA(anchor_period)和RSI(14)"""
    df = df.copy()
    
    # MA
    df['MA'] = df['Close'].rolling(window=anchor_period).mean()
    
    # ATR(14)
    df['prev_close'] = df['Close'].shift(1)
    df['TR'] = df.apply(
        lambda r: max(r['High'] - r['Low'],
                      abs(r['High'] - r['prev_close']) if pd.notna(r['prev_close']) else 0,
                      abs(r['Low'] - r['prev_close']) if pd.notna(r['prev_close']) else 0),
        axis=1
    )
    df['ATR14'] = df['TR'].rolling(window=14).mean()
    
    # RSI(14) — 用于前置过滤
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['RSI14'] = 100 - (100 / (1 + rs))
    df['RSI14'] = df['RSI14'].fillna(50)  # 初始值填充
    
    return df


# ============================================================
# §1-2 买入区间 + 独立信号识别
# ============================================================

def identify_signals(df, anchor_period, k, hold_days, cooldown=10, stop_mult=2.0, rsi_filter=False, rsi_threshold=40):
    """
    §1 买入区间逐日计算
    §2 独立信号识别（冷却期去重）
    """
    signals = []
    n = len(df)
    
    in_zone = False
    cooling_end_idx = -1
    
    for i in range(n):
        if i < anchor_period + 14:  # 上市初期跳过（均线/ATR未稳定）
            continue
        
        ma_val = df.loc[i, 'MA']
        atr_val = df.loc[i, 'ATR14']
        price = df.loc[i, 'Close']
        
        if pd.isna(ma_val) or pd.isna(atr_val) or atr_val <= 0:
            continue
        
        zone_lower = ma_val - k * atr_val
        zone_upper = ma_val
        
        is_in_zone = (zone_lower <= price <= zone_upper)
        
        # 冷却期检查
        if cooling_end_idx > 0 and i <= cooling_end_idx:
            is_in_zone = False
        
        # 独立信号触发
        if is_in_zone and not in_zone:
            # RSI前置过滤（r28：588000专用）
            if rsi_filter:
                rsi_val = df.loc[i, 'RSI14']
                if pd.notna(rsi_val) and rsi_val >= rsi_threshold:
                    continue  # RSI未满足超卖条件，跳过此信号
            
            stop_price = zone_lower - stop_mult * atr_val
            
            signal = {
                'ticker': df.loc[i, 'ticker'] if 'ticker' in df.columns else '',
                'trigger_idx': i,
                'trigger_date': df.loc[i, 'Date'],
                'entry_price': price,
                'zone_lower': zone_lower,
                'zone_upper': zone_upper,
                'atr_at_trigger': atr_val,
                'stop_price': stop_price,
                'hold_days': hold_days,
                'cooldown_end': df.loc[i, 'Date'] + timedelta(days=cooldown),
                'cooldown_end_idx': i + cooldown,
            }
            signals.append(signal)
            
            cooling_end_idx = i + cooldown
            in_zone = True
        
        elif not is_in_zone:
            in_zone = False
    
    return signals


# ============================================================
# §3 逐信号盈亏计算
# ============================================================

def calc_signal_results(signals, df):
    """持有期 + 止损双通道"""
    for sig in signals:
        idx_entry = sig['trigger_idx']
        p_entry = sig['entry_price']
        p_stop = sig['stop_price']
        h = sig['hold_days']
        
        sig['result'] = None
        sig['exit_price'] = None
        sig['exit_date'] = None
        sig['exit_reason'] = None
        sig['return_pct'] = None
        
        for d in range(1, h + 1):
            idx_current = idx_entry + d
            
            if idx_current >= len(df):
                sig['result'] = 'DATA_INSUFFICIENT'
                sig['exit_price'] = df.loc[len(df)-1, 'Close']
                sig['exit_date'] = df.loc[len(df)-1, 'Date']
                sig['exit_reason'] = 'DATA_END'
                break
            
            p_low = df.loc[idx_current, 'Low']
            p_close = df.loc[idx_current, 'Close']
            date_current = df.loc[idx_current, 'Date']
            
            # 止损优先
            if p_low <= p_stop:
                sig['result'] = 'STOP'
                sig['exit_price'] = p_stop
                sig['exit_date'] = date_current
                sig['exit_reason'] = 'STOP_LOSS'
                break
            
            # 持有期满
            if d == h:
                if p_close > p_entry:
                    sig['result'] = 'WIN'
                else:
                    sig['result'] = 'LOSS'
                sig['exit_price'] = p_close
                sig['exit_date'] = date_current
                sig['exit_reason'] = 'TIME_EXIT'
        
        # 收益率
        if sig['exit_price'] is not None:
            sig['return_pct'] = (sig['exit_price'] - p_entry) / p_entry * 100
    
    return signals


# ============================================================
# §4 命中率与配套指标计算
# ============================================================

def calc_metrics(signals, df, anchor_period, k):
    """计算HR, CR, PF, 期望值等"""
    valid = [s for s in signals if s['result'] in ('WIN', 'LOSS', 'STOP')]
    total = len(valid)
    wins = len([s for s in valid if s['result'] == 'WIN'])
    losses = len([s for s in valid if s['result'] in ('LOSS', 'STOP')])
    stops = len([s for s in valid if s['result'] == 'STOP'])
    insufficient = len([s for s in signals if s['result'] == 'DATA_INSUFFICIENT'])
    
    hr = wins / total if total > 0 else 0.0
    
    # 盈亏比
    total_win_pct = sum([s['return_pct'] for s in valid if s['result'] == 'WIN'])
    total_loss_pct = abs(sum([s['return_pct'] for s in valid if s['result'] in ('LOSS', 'STOP')]))
    pf = total_win_pct / total_loss_pct if total_loss_pct > 0 else (float('inf') if total_win_pct > 0 else 0.0)
    
    # 平均盈亏
    avg_win = np.mean([s['return_pct'] for s in valid if s['result'] == 'WIN']) if wins > 0 else 0.0
    avg_loss = np.mean([s['return_pct'] for s in valid if s['result'] in ('LOSS', 'STOP')]) if losses > 0 else 0.0
    
    # 最大连续亏损
    max_consec = 0
    cur_consec = 0
    for s in valid:
        if s['result'] in ('LOSS', 'STOP'):
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0
    
    # 期望值
    expectancy = (hr * avg_win) - ((1 - hr) * abs(avg_loss))
    
    # 区间覆盖率（CR）
    n = len(df)
    zone_days = 0
    for i in range(anchor_period + 14, n):
        if i >= n: break
        ma_val = df.loc[i, 'MA']
        atr_val = df.loc[i, 'ATR14']
        if pd.isna(ma_val) or pd.isna(atr_val): continue
        price = df.loc[i, 'Close']
        lower = ma_val - k * atr_val
        if lower <= price <= ma_val:
            zone_days += 1
    
    total_days_valid = n - (anchor_period + 14)
    cr = zone_days / total_days_valid if total_days_valid > 0 else 0.0
    
    # 当前状态
    latest = df.iloc[-1]
    last_ma = df.iloc[-1]['MA']
    last_atr = df.iloc[-1]['ATR14']
    last_price = latest['Close']
    
    if pd.notna(last_ma) and pd.notna(last_atr):
        zone_lower = last_ma - k * last_atr
        if last_price <= zone_lower:
            current_status = '🔴 区间下方（超跌）'
        elif last_price >= last_ma:
            current_status = '🟡 区间上方（未触发）'
        else:
            current_status = '🟢 在区间内'
    else:
        current_status = '⚪ 数据不足'
    
    return {
        'total_signals': total,
        'win_signals': wins,
        'loss_signals': losses,
        'stop_signals': stops,
        'insufficient_signals': insufficient,
        'hit_rate': hr,
        'profit_factor': pf,
        'avg_win_pct': avg_win,
        'avg_loss_pct': avg_loss,
        'expectancy': expectancy,
        'max_consec_losses': max_consec,
        'coverage_rate': cr,
        'current_status': current_status,
    }


# ============================================================
# §5 输出报表
# ============================================================

def run_backtest(ticker, cfg, years=3, verbose=True):
    """单标的全量回测"""
    if verbose:
        print(f"\n{'='*60}")
        print(f"  {ticker} {cfg['name']}")
        print(f"  {cfg['tier']} | MA{cfg['anchor']} × {cfg['k']} | H={cfg['hold_days']}d")
        if cfg['note']:
            print(f"  📌 {cfg['note']}")
        print(f"{'='*60}")
    
    # 取数
    df = fetch_data(ticker, cfg, years=years)
    if df is None or len(df) < 200:
        if verbose:
            print(f"  ❌ 数据不足，跳过")
        return None
    
    # 计算技术指标
    df = calc_technical_indicators(df, cfg['anchor'])
    
    # 去NaN
    df = df.dropna(subset=['MA', 'ATR14']).reset_index(drop=True)
    
    if len(df) < 50:
        if verbose:
            print(f"  ❌ 技术指标计算后数据不足，跳过")
        return None
    
    # 添加ticker
    df['ticker'] = ticker
    
    # 识别信号
    rsi_filter = (ticker == '588000')
    signals = identify_signals(
        df, cfg['anchor'], cfg['k'], 
        cfg['hold_days'], cooldown=10, stop_mult=2.0,
        rsi_filter=rsi_filter, rsi_threshold=40
    )
    
    # 计算盈亏
    signals = calc_signal_results(signals, df)
    
    # 计算指标
    metrics = calc_metrics(signals, df, cfg['anchor'], cfg['k'])
    
    if verbose:
        print(f"  📊 回测周期: {df.iloc[0]['Date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['Date'].strftime('%Y-%m-%d')}")
        print(f"     总交易日: {len(df)}")
        print(f"  📈 信号统计:")
        print(f"     独立信号数: {metrics['total_signals']}")
        print(f"     WIN: {metrics['win_signals']} | LOSS: {metrics['loss_signals']} | STOP: {metrics['stop_signals']} | 数据不足: {metrics['insufficient_signals']}")
        print(f"  🎯 命中率(HR): {metrics['hit_rate']*100:.1f}%")
        print(f"  📊 区间覆盖率(CR): {metrics['coverage_rate']*100:.1f}%")
        print(f"  💰 盈亏比(PF): {metrics['profit_factor']:.2f}")
        awp = metrics['avg_win_pct']
        print(f"     平均盈利: {awp:+.2f}%")
        print(f"     平均亏损: {metrics['avg_loss_pct']:.2f}%")
        print(f"     期望值: {metrics['expectancy']:+.2f}%")
        print(f"     最大连续亏损: {metrics['max_consec_losses']} 笔")
        print(f"  🟢 当前状态: {metrics['current_status']}")
        
        # 列出最近5笔信号
        recent = [s for s in signals if s['result'] in ('WIN', 'LOSS', 'STOP')][-5:]
        if recent:
            print(f"  📋 最近5笔信号:")
            for s in recent:
                emoji = '🟢' if s['result'] == 'WIN' else ('🔴' if s['result'] == 'STOP' else '⚫')
                print(f"     {emoji} {s['trigger_date'].strftime('%Y-%m-%d')} 入场{s['entry_price']:.2f} → "
                      f"{s['exit_date'].strftime('%Y-%m-%d')} 退出{s['exit_price']:.2f} "
                      f"({s['return_pct']:+.2f}%) [{s['exit_reason']}]")
    
    return {
        'ticker': ticker,
        'name': cfg['name'],
        'tier': cfg['tier'],
        'config': f"MA{cfg['anchor']}×{cfg['k']}",
        'hold_days': cfg['hold_days'],
        'period': f"{df.iloc[0]['Date'].strftime('%Y-%m-%d')}~{df.iloc[-1]['Date'].strftime('%Y-%m-%d')}",
        'trading_days': len(df),
        **metrics
    }


def run_all_backtest(years=3, verbose=True):
    """全池回测"""
    results = []
    
    for ticker, cfg in TICKER_CONFIG.items():
        result = run_backtest(ticker, cfg, years=years, verbose=verbose)
        if result:
            results.append(result)
    
    # 汇总表
    if results:
        print(f"\n\n{'='*100}")
        print(f"  📊 全池反击命中率回测汇总 — {years}年数据")
        print(f"{'='*100}")
        print(f"{'标的':<8} {'名称':<16} {'层级':<10} {'参数':<12} {'H':>3} {'信号':>5} {'HR':>8} {'CR':>8} {'PF':>6} {'期望值':>8} {'最大连亏':>6} {'状态':<16}")
        print(f"{'-'*8} {'-'*16} {'-'*10} {'-'*12} {'-'*3} {'-'*5} {'-'*8} {'-'*8} {'-'*6} {'-'*8} {'-'*6} {'-'*16}")
        
        for r in results:
            print(f"{r['ticker']:<8} {r['name']:<16} {r['tier']:<10} {r['config']:<12} {r['hold_days']:>3} "
                  f"{r['total_signals']:>5} {r['hit_rate']*100:>7.1f}% {r['coverage_rate']*100:>7.1f}% "
                  f"{r['profit_factor']:>6.2f} {r['expectancy']:>+7.2f}% {r['max_consec_losses']:>4}笔 "
                  f"{r['current_status']:<16}")
        
        print(f"\n{'='*100}")
        print(f"  总标数: {len(results)} | 总信号数: {sum(r['total_signals'] for r in results)}")
        avg_hr = np.mean([r['hit_rate'] for r in results])
        avg_cr = np.mean([r['coverage_rate'] for r in results])
        print(f"  平均HR: {avg_hr*100:.1f}% | 平均CR: {avg_cr*100:.1f}%")
        print(f"{'='*100}")
    
    # 已剥夺标的备注
    if DEPRIVED:
        print(f"\n📌 已剥夺反击资格（不参与回测）:")
        for t, info in DEPRIVED.items():
            print(f"   {t} {info['name']} — {info['reason']}")
    
    return results


def export_to_markdown(results, filename=None):
    """导出Markdown报表"""
    if not results:
        return
    
    lines = []
    lines.append(f"# 📜 反击命中率回测报告 — {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"")
    lines.append(f"**生效**：守东（资产规划部首席审计官） | **引擎**：法典嵌入版 V2.0")
    lines.append(f"")
    lines.append(f"## 全池汇总")
    lines.append(f"")
    lines.append(f"| 标的 | 名称 | 层级 | 参数 | H | 信号数 | HR | CR | PF | 期望值 | 最大连亏 | 当前状态 |")
    lines.append(f"|:---:|:---|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|")
    
    for r in results:
        lines.append(f"| {r['ticker']} | {r['name']} | {r['tier']} | {r['config']} | {r['hold_days']}d | "
                     f"{r['total_signals']} | {r['hit_rate']*100:.1f}% | {r['coverage_rate']*100:.1f}% | "
                     f"{r['profit_factor']:.2f} | {r['expectancy']:+.2f}% | {r['max_consec_losses']}笔 | {r['current_status']} |")
    
    lines.append(f"")
    avg_hr = np.mean([r['hit_rate'] for r in results])
    avg_cr = np.mean([r['coverage_rate'] for r in results])
    lines.append(f"**总标数**: {len(results)} | **平均HR**: {avg_hr*100:.1f}% | **平均CR**: {avg_cr*100:.1f}%")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    
    # 逐标详情
    for r in results:
        lines.append(f"### {r['ticker']} {r['name']}")
        lines.append(f"")
        lines.append(f"- **层级/参数**: {r['tier']} | {r['config']} | H={r['hold_days']}d")
        lines.append(f"- **回测周期**: {r['period']} ({r['trading_days']}个交易日)")
        lines.append(f"- **信号统计**: 总{r['total_signals']}笔 | WIN={r['win_signals']} | LOSS={r['loss_signals']} | STOP={r['stop_signals']} | 数据不足={r['insufficient_signals']}")
        lines.append(f"- **命中率(HR)**: {r['hit_rate']*100:.1f}%")
        lines.append(f"- **区间覆盖率(CR)**: {r['coverage_rate']*100:.1f}%")
        lines.append(f"- **盈亏比(PF)**: {r['profit_factor']:.2f}")
        lines.append(f"- **平均盈利/亏损**: {r['avg_win_pct']:+.2f}% / {r['avg_loss_pct']:.2f}%")
        lines.append(f"- **期望值**: {r['expectancy']:+.2f}%")
        lines.append(f"- **最大连续亏损**: {r['max_consec_losses']}笔")
        lines.append(f"- **当前状态**: {r['current_status']}")
        lines.append(f"")
    
    content = '\n'.join(lines)
    
    if filename:
        os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n📄 报表已导出: {filename}")
    
    return content


# ============================================================
# CLI入口
# ============================================================

if __name__ == '__main__':
    years = 3
    export = False
    output_file = None
    
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == '--years' and i+1 < len(args):
            years = int(args[i+1])
        elif arg == '--export' and i+1 < len(args):
            export = True
            output_file = args[i+1]
        elif arg == '--ticker' and i+1 < len(args):
            ticker = args[i+1].upper()
            if ticker in TICKER_CONFIG:
                run_backtest(ticker, TICKER_CONFIG[ticker], years=years)
                sys.exit(0)
            elif ticker in DEPRIVED:
                print(f"⚠️ {ticker} ({DEPRIVED[ticker]['name']}) 已剥夺反击资格，不参与回测。")
                print(f"   原因: {DEPRIVED[ticker]['reason']}")
                sys.exit(0)
            else:
                print(f"❌ 标的不在反击池内: {ticker}")
                print(f"   可用标的: {', '.join(TICKER_CONFIG.keys())}")
                sys.exit(1)
    
    results = run_all_backtest(years=years, verbose=True)
    
    if export and output_file:
        export_to_markdown(results, output_file)
