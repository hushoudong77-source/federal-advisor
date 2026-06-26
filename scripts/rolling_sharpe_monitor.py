#!/usr/bin/env python3
"""
📐 滚动12月Sharpe监控引擎 — 参数失效预警 V1.0
签发：守东（资产规划部首席审计官）
生效日期：2026-06-22

功能：
  - 对全池反击标的计算滚动12个月Sharpe Ratio
  - 对比全周期基准Sharpe，比率<50%触发⚠️黄色警报
  - 输出逐标参数失效风险矩阵

用法：
  python3 scripts/rolling_sharpe_monitor.py              # 全池
  python3 scripts/rolling_sharpe_monitor.py --ticker 513910  # 单标
  python3 scripts/rolling_sharpe_monitor.py --export report.md

原理：
  滚动Sharpe = 最近252个交易日(约12个月)的日收益率均值 / 日收益率标准差 × √252
  全周期Sharpe = 全部可用数据的日收益率均值 / 日收益率标准差 × √252
  比率 = 滚动Sharpe / 全周期Sharpe
  比率 < 0.50 → ⚠️ 参数失效黄色警报（不是改参数，是降低仓位+增加确认条件）
"""

import tushare as ts
import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime, timedelta

# ============================================================
# §1 标的配置表（与 hitrate_backtest.py 同步）
# ============================================================

TICKER_CONFIG = {
    '513910': {
        'name': '港股通央企红利ETF',
        'tushare_code': '513910.SH', 'type': 'fund_daily',
        'anchor': 40, 'k': 4.5, 'tier': 'L1红利',
    },
    '159302': {
        'name': '恒生红利ETF',
        'tushare_code': '159302.SZ', 'type': 'fund_daily',
        'anchor': 40, 'k': 4.0, 'tier': 'L1红利',
    },
    '588000': {
        'name': '科创50ETF',
        'tushare_code': '588000.SH', 'type': 'fund_daily',
        'anchor': 30, 'k': 5.0, 'tier': 'L2成长',
    },
    '513770': {
        'name': '港股小盘ETF',
        'tushare_code': '513770.SH', 'type': 'fund_daily',
        'anchor': 40, 'k': 1.5, 'tier': 'L2成长',
    },
    '510500': {
        'name': '中证500ETF',
        'tushare_code': '510500.SH', 'type': 'fund_daily',
        'anchor': 60, 'k': 3.5, 'tier': 'L3宽基',
    },
    '512100': {
        'name': '中证1000ETF',
        'tushare_code': '512100.SH', 'type': 'fund_daily',
        'anchor': 40, 'k': 2.0, 'tier': 'L3宽基',
    },
    '510880': {
        'name': '红利ETF易方达',
        'tushare_code': '510880.SH', 'type': 'fund_daily',
        'anchor': 40, 'k': 2.0, 'tier': 'L1红利',
    },
    'VTI': {
        'name': '美股全市场ETF',
        'tushare_code': 'VTI', 'type': 'us_daily',
        'anchor': 60, 'k': 4.0, 'tier': 'L2发达',
    },
    'VEA': {
        'name': '发达市场ETF',
        'tushare_code': 'VEA', 'type': 'us_daily',
        'anchor': 60, 'k': 4.0, 'tier': 'L2发达',
    },
    'BBJP': {
        'name': '日股ETF',
        'tushare_code': 'BBJP', 'type': 'us_daily',
        'anchor': 40, 'k': 2.5, 'tier': 'L2发达',
    },
    'MUFG': {
        'name': '三菱日联金融',
        'tushare_code': 'MUFG', 'type': 'us_daily',
        'anchor': 40, 'k': 1.0, 'tier': 'L2发达',
    },
    'VNM': {
        'name': '越南ETF',
        'tushare_code': 'VNM', 'type': 'us_daily',
        'anchor': 20, 'k': 1.0, 'tier': 'L2新兴',
    },
    'FLIN': {
        'name': '印度ETF',
        'tushare_code': 'FLIN', 'type': 'us_daily',
        'anchor': 20, 'k': 1.0, 'tier': 'L2新兴',
    },
}

# 已剥夺反击资格的标的，仍需监控（参数失效可能意味着可以重新评估）
DEPRIVED = {
    'EWY': {'name': '韩国ETF', 'reason': '走廊测试：全区间负Sharpe'},
    'SMIN': {'name': '印度小盘ETF', 'reason': 'Step 3回测：PF=0.93'},
}


# ============================================================
# §2 数据获取
# ============================================================

def fetch_data(ticker, cfg):
    """从Tushare获取全部可用日线数据"""
    end_date = datetime.now().strftime('%Y%m%d')
    # 拉取全部可用数据（最多10年）
    start_date = (datetime.now() - timedelta(days=10*365)).strftime('%Y%m%d')

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

        df = df.rename(columns={
            'trade_date': 'Date', 'close': 'Close'
        })
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date').reset_index(drop=True)

        return df[['Date', 'Close']]

    except Exception as e:
        print(f"  ⚠️ {ticker} 获取失败: {e}")
        return None


# ============================================================
# §3 Sharpe计算
# ============================================================

def calc_daily_returns(df):
    """计算日收益率序列"""
    df = df.copy()
    df['Return'] = df['Close'].pct_change()
    return df.dropna(subset=['Return'])


def calc_sharpe(returns, annual_factor=np.sqrt(252)):
    """计算年化Sharpe Ratio"""
    if len(returns) < 20:
        return None
    mean_ret = returns.mean()
    std_ret = returns.std()
    if std_ret == 0 or pd.isna(std_ret):
        return None
    return (mean_ret / std_ret) * annual_factor


def calc_rolling_sharpe(df, window=252):
    """计算滚动Sharpe序列"""
    df = df.copy()
    sharpe_series = []

    for i in range(window, len(df)):
        window_returns = df['Return'].iloc[i-window:i]
        s = calc_sharpe(window_returns)
        sharpe_series.append({
            'Date': df['Date'].iloc[i],
            'Rolling_Sharpe': s,
        })

    return pd.DataFrame(sharpe_series)


def run_monitor(ticker=None, verbose=True):
    """运行滚动Sharpe监控"""
    if ticker:
        tickers = {ticker: TICKER_CONFIG.get(ticker)}
        if ticker not in TICKER_CONFIG:
            print(f"❌ 标的不在监控池内: {ticker}")
            print(f"   可用标的: {', '.join(TICKER_CONFIG.keys())}")
            return None
    else:
        tickers = TICKER_CONFIG

    results = []

    for tkr, cfg in tickers.items():
        if verbose:
            print(f"\n{'='*60}")
            print(f"  {tkr} {cfg['name']} ({cfg['tier']})")
            print(f"{'='*60}")

        # 取数
        df = fetch_data(tkr, cfg)
        if df is None or len(df) < 300:
            print(f"  ❌ 数据不足（需要≥300个交易日），跳过")
            continue

        # 计算日收益率
        df = calc_daily_returns(df)
        if len(df) < 252:
            print(f"  ❌ 有效交易日不足252天，跳过")
            continue

        # 全周期Sharpe
        full_sharpe = calc_sharpe(df['Return'])
        if full_sharpe is None:
            print(f"  ❌ 全周期Sharpe计算失败，跳过")
            continue

        # 滚动12月Sharpe
        rolling_df = calc_rolling_sharpe(df, window=252)
        if len(rolling_df) == 0:
            print(f"  ❌ 滚动Sharpe计算失败，跳过")
            continue

        latest_rolling = rolling_df['Rolling_Sharpe'].iloc[-1]
        latest_date = rolling_df['Date'].iloc[-1]

        if latest_rolling is None or pd.isna(latest_rolling):
            print(f"  ❌ 最新滚动Sharpe为空，跳过")
            continue

        # 比率
        ratio = latest_rolling / full_sharpe if full_sharpe != 0 else None

        # 警报判定
        if ratio is None:
            alert = '⚪ 无法判定'
        elif ratio < 0:
            alert = '🔴 滚动Sharpe为负（策略正在亏钱）'
        elif ratio < 0.50:
            alert = f'⚠️ 黄色警报——滚动Sharpe仅为全周期的{ratio*100:.0f}%'
        else:
            alert = f'🟢 正常——滚动Sharpe为全周期的{ratio*100:.0f}%'

        # 滚动Sharpe趋势（最近6个月 vs 前6个月）
        half = len(rolling_df) // 2
        if half >= 126:
            recent_sharpe = rolling_df['Rolling_Sharpe'].iloc[-126:].mean()
            earlier_sharpe = rolling_df['Rolling_Sharpe'].iloc[:half][-126:].mean()
            if pd.notna(recent_sharpe) and pd.notna(earlier_sharpe) and earlier_sharpe != 0:
                trend = (recent_sharpe - earlier_sharpe) / abs(earlier_sharpe) * 100
                trend_str = f"{'↑' if trend > 0 else '↓'}{abs(trend):.0f}%"
            else:
                trend_str = '—'
        else:
            trend_str = '—'

        result = {
            'ticker': tkr,
            'name': cfg['name'],
            'tier': cfg['tier'],
            'full_sharpe': full_sharpe,
            'rolling_sharpe': latest_rolling,
            'rolling_date': latest_date,
            'ratio': ratio,
            'alert': alert,
            'trend': trend_str,
            'data_days': len(df),
            'rolling_window_days': len(rolling_df),
        }

        if verbose:
            print(f"  📊 全周期Sharpe: {full_sharpe:+.3f}")
            print(f"  📊 滚动12月Sharpe: {latest_rolling:+.3f} ({latest_date.strftime('%Y-%m-%d')})")
            print(f"  📊 比率: {ratio*100:.0f}%" if ratio is not None else "  📊 比率: N/A")
            print(f"  📊 6月趋势: {trend_str}")
            print(f"  🚨 判定: {alert}")
            print(f"  📅 数据: {len(df)}个交易日 | 滚动窗口: {len(rolling_df)}个")

        results.append(result)

    return results


def export_to_markdown(results, filename=None):
    """导出Markdown报告"""
    if not results:
        return ""

    lines = []
    lines.append(f"# 📐 滚动12月Sharpe监控 — {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"")
    lines.append(f"**签发**：守东（资产规划部首席审计官） | **引擎**：滚动Sharpe监控 V1.0")
    lines.append(f"")
    lines.append(f"## 参数失效风险矩阵")
    lines.append(f"")
    lines.append(f"| 标的 | 名称 | 层级 | 全周期Sharpe | 滚动12月Sharpe | 比率 | 6月趋势 | 警报 |")
    lines.append(f"|:---:|:---|---:|---:|---:|:---:|:---:|")
    for r in results:
        ratio_str = f"{r['ratio']*100:.0f}%" if r['ratio'] is not None else "N/A"
        lines.append(f"| {r['ticker']} | {r['name']} | {r['tier']} | "
                     f"{r['full_sharpe']:+.3f} | {r['rolling_sharpe']:+.3f} | "
                     f"{ratio_str} | {r['trend']} | {r['alert']} |")

    lines.append(f"")
    lines.append(f"## 判定规则")
    lines.append(f"")
    lines.append(f"- **比率 = 滚动12月Sharpe / 全周期Sharpe**")
    lines.append(f"- ⚠️ 比率 < 50% → **黄色警报**：参数可能失效，降低仓位 + 增加确认条件")
    lines.append(f"- 🔴 滚动Sharpe为负 → **红色警报**：当前参数组合在近12个月持续亏钱")
    lines.append(f"- 🟢 比率 ≥ 50% → **正常**：参数在近12个月表现与历史一致")
    lines.append(f"")
    lines.append(f"## 数据窗口")
    lines.append(f"")
    for r in results:
        lines.append(f"- **{r['ticker']}**: {r['data_days']}个交易日 | 滚动窗口: {r['rolling_window_days']}个 "
                     f"| 最新滚动日: {r['rolling_date'].strftime('%Y-%m-%d')}")

    content = '\n'.join(lines)

    if filename:
        os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n📄 报告已导出: {filename}")

    return content


# ============================================================
# CLI入口
# ============================================================

if __name__ == '__main__':
    ticker = None
    export = False
    output_file = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--ticker' and i+1 < len(args):
            ticker = args[i+1].upper()
            i += 2
        elif args[i] == '--export' and i+1 < len(args):
            export = True
            output_file = args[i+1]
            i += 2
        else:
            i += 1

    results = run_monitor(ticker=ticker, verbose=True)

    if export and output_file and results:
        export_to_markdown(results, output_file)
