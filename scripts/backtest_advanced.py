#!/usr/bin/env python3
"""
📜 高级回测引擎 V1.0 — P0三指标叠加层
签发：守东（资产规划部首席审计官）
生效日期：2026-06-14

基于 hitrate_backtest.py V2.0 的现有引擎，叠加三个P0级指标：
  P0-1: 滚动窗口漂移率（Rolling Window Drift）
  P0-2: 参数敏感度热力图（Parameter Sensitivity）
  P0-3: 最大连续亏损时间标记（Max Consec Loss Annotation）

用法：
  python3 scripts/backtest_advanced.py                    # 全池P0分析
  python3 scripts/backtest_advanced.py --ticker 513910    # 单标P0分析
  python3 scripts/backtest_advanced.py --sensitivity-only # 仅参数敏感度
  python3 scripts/backtest_advanced.py --export report.md # 导出报告
"""

import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# 导入现有引擎的全部函数
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hitrate_backtest import (
    TICKER_CONFIG, DEPRIVED, GOLD_SHIELD, ATTACK_ONLY,
    fetch_data, calc_technical_indicators, identify_signals,
    calc_signal_results, calc_metrics, run_backtest, run_all_backtest
)


# ============================================================
# P0-1: 滚动窗口漂移率
# ============================================================

def calc_rolling_window_drift(signals, windows=None):
    """
    计算多个滚动窗口的HR，检测策略漂移。
    
    windows: 窗口大小列表（月），默认 [36, 24, 12, 6, 3]
    返回: dict {window_months: {'hr': float, 'signals': int, 'first_date': str, 'last_date': str}}
    """
    if windows is None:
        windows = [36, 24, 12, 6, 3]
    
    valid = [s for s in signals if s['result'] in ('WIN', 'LOSS', 'STOP')]
    if not valid:
        return {'error': '无有效信号'}
    
    # 按日期排序
    valid_sorted = sorted(valid, key=lambda s: s['trigger_date'])
    latest_date = valid_sorted[-1]['trigger_date']
    
    full_hr = len([s for s in valid if s['result'] == 'WIN']) / len(valid) * 100
    
    results = {}
    for w in windows:
        cutoff_date = latest_date - timedelta(days=w * 30)
        window_signals = [s for s in valid_sorted if s['trigger_date'] >= cutoff_date]
        
        if len(window_signals) < 5:
            results[f'{w}月'] = {
                'hr': None, 'signals': len(window_signals),
                'warning': '⚠️ 样本不足(<5笔)',
                'first_date': None, 'last_date': None
            }
            continue
        
        wins = len([s for s in window_signals if s['result'] == 'WIN'])
        hr = wins / len(window_signals) * 100
        
        drift = hr - full_hr
        
        # 漂移判定
        if len(window_signals) >= 10:
            if drift < -20:
                level = '🔴🔴 严重恶化'
            elif drift < -10:
                level = '🔴 恶化'
            elif drift < -5:
                level = '🟡 轻微下降'
            elif drift > 10:
                level = '🟢 改善'
            else:
                level = '⚪ 稳定'
        else:
            level = '🟡 样本偏少'
        
        results[f'{w}月'] = {
            'hr': hr,
            'signals': len(window_signals),
            'drift_vs_full': drift,
            'level': level,
            'first_date': window_signals[0]['trigger_date'].strftime('%Y-%m-%d'),
            'last_date': window_signals[-1]['trigger_date'].strftime('%Y-%m-%d'),
        }
    
    return {
        'full_hr': full_hr,
        'total_signals': len(valid),
        'windows': results,
    }


# ============================================================
# P0-2: 参数敏感度
# ============================================================

def calc_parameter_sensitivity(ticker, cfg, years=3, deltas=None):
    """
    对k参数做邻域扫描，检测过拟合。
    
    deltas: k的偏移量列表，默认 [-0.50, -0.25, -0.10, -0.05, 0, +0.05, +0.10, +0.25, +0.50]
    返回: {k_value: {'hr': float, 'signals': int, 'pf': float, 'expectancy': float}}
    """
    if deltas is None:
        deltas = [-0.50, -0.25, -0.10, -0.05, 0, +0.05, +0.10, +0.25, +0.50]
    
    base_k = cfg['k']
    
    # 拉取数据（只拉一次）
    df = fetch_data(ticker, cfg, years=years)
    if df is None or len(df) < 200:
        return {'error': '数据不足'}
    
    df = calc_technical_indicators(df, cfg['anchor'])
    df = df.dropna(subset=['MA', 'ATR14']).reset_index(drop=True)
    df['ticker'] = ticker
    
    if len(df) < 50:
        return {'error': '技术指标计算后数据不足'}
    
    results = {}
    use_3d = (ticker == '588000')
    
    for delta in deltas:
        k_test = base_k + delta
        if k_test <= 0:
            continue
        
        signals = identify_signals(
            df, cfg['anchor'], k_test,
            cfg['hold_days'], cooldown=10, stop_mult=2.0,
            use_3d_filter=use_3d
        )
        signals = calc_signal_results(signals, df)
        metrics = calc_metrics(signals, df, cfg['anchor'], k_test)
        
        results[k_test] = {
            'hr': metrics['hit_rate'] * 100,
            'signals': metrics['total_signals'],
            'pf': metrics['profit_factor'],
            'expectancy': metrics['expectancy'],
            'max_consec': metrics['max_consec_losses'],
        }
    
    # 计算敏感度指标
    base = results[base_k]
    max_hr_drop = 0
    critical_delta = None
    
    for k_val, r in results.items():
        if k_val == base_k:
            continue
        drop = base['hr'] - r['hr']
        if drop > max_hr_drop:
            max_hr_drop = drop
            critical_delta = k_val - base_k
    
    # 过拟合判定
    if max_hr_drop > 15 and abs(critical_delta) <= 0.10 if critical_delta else False:
        overfit_warning = f'🔴 疑似过拟合：k偏移{critical_delta:+.2f}时HR暴跌{max_hr_drop:.1f}pp'
    elif max_hr_drop > 8:
        overfit_warning = f'🟡 敏感度偏高：最大HR降幅{max_hr_drop:.1f}pp'
    else:
        overfit_warning = '🟢 参数稳健'
    
    return {
        'base_k': base_k,
        'sensitivity': results,
        'max_hr_drop': max_hr_drop,
        'critical_delta': critical_delta,
        'overfit_warning': overfit_warning,
    }


# ============================================================
# P0-3: 最大连续亏损时间标记
# ============================================================

def calc_max_consec_loss_annotated(signals):
    """
    找到最大连续亏损段，标注时间和累计亏损。
    返回: {max_consec, consec_segments: [{start_date, end_date, count, total_loss_pct, ...}]}
    """
    valid = [s for s in signals if s['result'] in ('WIN', 'LOSS', 'STOP')]
    if not valid:
        return {'max_consec': 0, 'segments': []}
    
    # 找出所有连续亏损段
    segments = []
    cur_start = None
    cur_count = 0
    cur_losses = []
    
    for i, s in enumerate(valid):
        if s['result'] in ('LOSS', 'STOP'):
            if cur_start is None:
                cur_start = i
            cur_count += 1
            cur_losses.append(s['return_pct'])
        else:
            if cur_count > 0:
                segments.append({
                    'start_idx': cur_start,
                    'end_idx': i - 1,
                    'count': cur_count,
                    'total_loss_pct': sum(cur_losses),
                    'avg_loss_pct': np.mean(cur_losses),
                    'start_date': valid[cur_start]['trigger_date'],
                    'end_date': valid[i-1]['trigger_date'],
                })
            cur_start = None
            cur_count = 0
            cur_losses = []
    
    # 末尾段
    if cur_count > 0:
        segments.append({
            'start_idx': cur_start,
            'end_idx': len(valid) - 1,
            'count': cur_count,
            'total_loss_pct': sum(cur_losses),
            'avg_loss_pct': np.mean(cur_losses),
            'start_date': valid[cur_start]['trigger_date'],
            'end_date': valid[-1]['trigger_date'],
        })
    
    # 找最大段
    max_seg = max(segments, key=lambda s: s['count']) if segments else None
    
    # 找出≥5笔的所有危险段
    danger_segments = [s for s in segments if s['count'] >= 5]
    
    return {
        'max_consec': max_seg['count'] if max_seg else 0,
        'max_segment': max_seg,
        'danger_segments': danger_segments,
        'total_segments': len(segments),
    }


# ============================================================
# 综合P0分析（单标）
# ============================================================

def run_p0_analysis(ticker, cfg, years=3, verbose=True):
    """对单个标的执行完整P0三指标分析"""
    
    if verbose:
        print(f"\n{'='*70}")
        print(f"  🔬 P0高级分析: {ticker} {cfg['name']}")
        print(f"  {cfg['tier']} | MA{cfg['anchor']} × k={cfg['k']} | H={cfg['hold_days']}d")
        print(f"{'='*70}")
    
    # 先跑基础回测获取信号
    df = fetch_data(ticker, cfg, years=years)
    if df is None or len(df) < 200:
        print(f"  ❌ 数据不足")
        return None
    
    df = calc_technical_indicators(df, cfg['anchor'])
    df = df.dropna(subset=['MA', 'ATR14']).reset_index(drop=True)
    df['ticker'] = ticker
    
    use_3d = (ticker == '588000')
    signals = identify_signals(
        df, cfg['anchor'], cfg['k'],
        cfg['hold_days'], cooldown=10, stop_mult=2.0,
        use_3d_filter=use_3d
    )
    signals = calc_signal_results(signals, df)
    metrics = calc_metrics(signals, df, cfg['anchor'], cfg['k'])
    
    # ── P0-1: 滚动窗口漂移 ──
    drift = calc_rolling_window_drift(signals)
    
    # ── P0-2: 参数敏感度 ──
    sensitivity = calc_parameter_sensitivity(ticker, cfg, years=years)
    
    # ── P0-3: 最大连续亏损时间标记 ──
    consec = calc_max_consec_loss_annotated(signals)
    
    if verbose:
        _print_p0_report(ticker, cfg, metrics, drift, sensitivity, consec)
    
    return {
        'ticker': ticker,
        'name': cfg['name'],
        'metrics': metrics,
        'drift': drift,
        'sensitivity': sensitivity,
        'consec': consec,
    }


def _print_p0_report(ticker, cfg, metrics, drift, sensitivity, consec):
    """格式化输出P0三指标报告"""
    
    # ── 基础指标速览 ──
    print(f"\n  📊 全周期基准:")
    print(f"     信号: {metrics['total_signals']}笔 | HR: {metrics['hit_rate']*100:.1f}% | "
          f"PF: {metrics['profit_factor']:.2f} | EV: {metrics['expectancy']:+.2f}%")
    
    # ── P0-1: 滚动窗口漂移 ──
    print(f"\n  ── P0-1 滚动窗口漂移率 ──")
    if 'error' in drift:
        print(f"     {drift['error']}")
    else:
        print(f"     全周期HR: {drift['full_hr']:.1f}% ({drift['total_signals']}笔)")
        for window, data in drift['windows'].items():
            if data['hr'] is not None:
                print(f"     {window:>4}: HR={data['hr']:.1f}% | 信号{data['signals']}笔 | "
                      f"漂移{data['drift_vs_full']:+.1f}pp | {data['level']}")
            else:
                print(f"     {window:>4}: {data['warning']}")
    
    # ── P0-2: 参数敏感度 ──
    print(f"\n  ── P0-2 参数敏感度 ──")
    if 'error' in sensitivity:
        print(f"     {sensitivity['error']}")
    else:
        print(f"     基准k={sensitivity['base_k']} | {sensitivity['overfit_warning']}")
        print(f"     最大HR降幅: {sensitivity['max_hr_drop']:.1f}pp "
              f"(k{sensitivity['critical_delta']:+.2f})" if sensitivity['critical_delta'] else "")
        print(f"     {'k值':<8} {'HR':>7} {'信号':>5} {'PF':>6} {'EV':>7} {'最大连亏':>6}")
        print(f"     {'-'*8} {'-'*7} {'-'*5} {'-'*6} {'-'*7} {'-'*6}")
        for k_val in sorted(sensitivity['sensitivity'].keys()):
            r = sensitivity['sensitivity'][k_val]
            marker = ' ← 当前' if abs(k_val - sensitivity['base_k']) < 0.001 else ''
            print(f"     {k_val:<8.2f} {r['hr']:>6.1f}% {r['signals']:>5} "
                  f"{r['pf']:>6.2f} {r['expectancy']:>+6.2f}% {r['max_consec']:>4}笔{marker}")
    
    # ── P0-3: 最大连续亏损 ──
    print(f"\n  ── P0-3 最大连续亏损时间标记 ──")
    print(f"     总亏损段: {consec['total_segments']}段 | 最大连续亏损: {consec['max_consec']}笔")
    if consec['max_segment']:
        ms = consec['max_segment']
        print(f"     最大段: {ms['start_date'].strftime('%Y-%m-%d')} ~ {ms['end_date'].strftime('%Y-%m-%d')}")
        print(f"             {ms['count']}笔连续亏损 | 累计{ms['total_loss_pct']:+.2f}% | "
              f"平均{ms['avg_loss_pct']:+.2f}%/笔")
    
    if consec['danger_segments']:
        print(f"     ⚠️  ≥5笔连续亏损段: {len(consec['danger_segments'])}段")
        for i, ds in enumerate(consec['danger_segments']):
            print(f"        {i+1}. {ds['start_date'].strftime('%Y-%m-%d')} ~ "
                  f"{ds['end_date'].strftime('%Y-%m-%d')} "
                  f"({ds['count']}笔, 累计{ds['total_loss_pct']:+.2f}%)")
    
    print()


# ============================================================
# 全池P0分析
# ============================================================

def run_all_p0_analysis(years=3, verbose=True):
    """全池标的P0三指标分析"""
    results = []
    
    for ticker, cfg in TICKER_CONFIG.items():
        r = run_p0_analysis(ticker, cfg, years=years, verbose=verbose)
        if r:
            results.append(r)
    
    # ── 全池汇总 ──
    if results and verbose:
        _print_p0_summary(results)
    
    return results


def _print_p0_summary(results):
    """P0全池汇总表"""
    print(f"\n{'='*100}")
    print(f"  📊 P0三指标全池汇总")
    print(f"{'='*100}")
    
    # 表头
    print(f"{'标的':<8} {'全周期HR':>9} {'近6月HR':>9} {'近3月HR':>9} "
          f"{'漂移判定':<12} {'敏感度':<14} {'最大连亏':>8} {'连亏时段':<24}")
    print(f"{'-'*8} {'-'*9} {'-'*9} {'-'*9} {'-'*12} {'-'*14} {'-'*8} {'-'*24}")
    
    for r in results:
        ticker = r['ticker']
        full_hr = r['metrics']['hit_rate'] * 100
        
        # 近6月HR
        drift = r['drift']
        if 'error' not in drift:
            hr_6m = drift['windows'].get('6月', {}).get('hr')
            hr_3m = drift['windows'].get('3月', {}).get('hr')
            drift_6m = drift['windows'].get('6月', {}).get('drift_vs_full', 0) if hr_6m else 0
            drift_level = drift['windows'].get('6月', {}).get('level', '—')
        else:
            hr_6m = None
            hr_3m = None
            drift_level = '—'
        
        # 敏感度
        sens = r['sensitivity']
        if 'error' not in sens:
            sens_str = f"{sens['overfit_warning'][:12]}"
        else:
            sens_str = '—'
        
        # 最大连亏
        consec = r['consec']
        max_c = consec['max_consec']
        if consec['max_segment']:
            c_time = f"{consec['max_segment']['start_date'].strftime('%Y-%m')}~{consec['max_segment']['end_date'].strftime('%Y-%m')}"
        else:
            c_time = '—'
        
        hr_6m_str = f"{hr_6m:.1f}%" if hr_6m is not None else '—'
        hr_3m_str = f"{hr_3m:.1f}%" if hr_3m is not None else '—'
        
        print(f"{ticker:<8} {full_hr:>8.1f}% {hr_6m_str:>9} {hr_3m_str:>9} "
              f"{drift_level:<12} {sens_str:<14} {max_c:>6}笔 {c_time:<24}")
    
    print(f"{'='*100}")
    
    # 异常告警汇总
    alerts = []
    for r in results:
        drift = r['drift']
        if 'error' not in drift:
            for window, data in drift['windows'].items():
                if data.get('level', '').startswith('🔴'):
                    alerts.append(f"  🔴 {r['ticker']} {r['name']}: {window}HR漂移{data['drift_vs_full']:+.1f}pp → {data['level']}")
        
        sens = r['sensitivity']
        if 'error' not in sens and sens['overfit_warning'].startswith('🔴'):
            alerts.append(f"  🔴 {r['ticker']} {r['name']}: {sens['overfit_warning']}")
        
        consec = r['consec']
        if consec['max_consec'] >= 8:
            alerts.append(f"  🟡 {r['ticker']} {r['name']}: 最大连续亏损{consec['max_consec']}笔 — 执行心理风险")
    
    if alerts:
        print(f"\n  ⚠️ P0异常告警汇总:")
        for a in alerts:
            print(a)
    else:
        print(f"\n  ✅ 全池P0三指标无异常告警")
    
    print(f"{'='*100}\n")


# ============================================================
# Markdown导出
# ============================================================

def export_p0_to_markdown(results, filename=None):
    """导出P0分析Markdown报告"""
    if not results:
        return
    
    lines = []
    lines.append(f"# 🔬 P0高级回测报告 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"")
    lines.append(f"**引擎**: 高级回测引擎 V1.0 | **基于**: hitrate_backtest.py V2.0")
    lines.append(f"**三个P0指标**: 滚动窗口漂移率 | 参数敏感度 | 最大连续亏损时间标记")
    lines.append(f"")
    
    # 全池汇总表
    lines.append(f"## 全池P0汇总")
    lines.append(f"")
    lines.append(f"| 标的 | 全周期HR | 近6月HR | 近3月HR | 漂移判定 | 敏感度 | 最大连亏 | 连亏时段 |")
    lines.append(f"|:---:|:---:|:---:|:---:|:---|:---|:---:|:---|")
    
    for r in results:
        full_hr = r['metrics']['hit_rate'] * 100
        
        drift = r['drift']
        if 'error' not in drift:
            hr_6m = drift['windows'].get('6月', {}).get('hr')
            hr_3m = drift['windows'].get('3月', {}).get('hr')
            drift_6m = drift['windows'].get('6月', {}).get('level', '—')
        else:
            hr_6m, hr_3m, drift_6m = None, None, '—'
        
        sens = r['sensitivity']
        sens_str = sens.get('overfit_warning', '—') if 'error' not in sens else '—'
        
        consec = r['consec']
        max_c = consec['max_consec']
        if consec['max_segment']:
            c_time = f"{consec['max_segment']['start_date'].strftime('%Y-%m')}~{consec['max_segment']['end_date'].strftime('%Y-%m')}"
        else:
            c_time = '—'
        
        hr6_str = f"{hr_6m:.1f}%" if hr_6m is not None else '—'
        hr3_str = f"{hr_3m:.1f}%" if hr_3m is not None else '—'
        lines.append(f"| {r['ticker']} | {full_hr:.1f}% | "
                     f"{hr6_str} | {hr3_str} | "
                     f"{drift_6m} | {sens_str} | {max_c}笔 | {c_time} |")
    
    lines.append(f"")
    
    # 逐标详情
    for r in results:
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## {r['ticker']} {r['name']}")
        lines.append(f"")
        
        m = r['metrics']
        lines.append(f"### 基础指标")
        lines.append(f"")
        lines.append(f"- 信号数: {m['total_signals']} | HR: {m['hit_rate']*100:.1f}% | PF: {m['profit_factor']:.2f} | EV: {m['expectancy']:+.2f}%")
        lines.append(f"- WIN: {m['win_signals']} | LOSS: {m['loss_signals']} | STOP: {m['stop_signals']} | 最大连亏: {m['max_consec_losses']}笔")
        lines.append(f"")
        
        # P0-1
        drift = r['drift']
        if 'error' not in drift:
            lines.append(f"### P0-1 滚动窗口漂移率")
            lines.append(f"")
            lines.append(f"| 窗口 | HR | 信号数 | 漂移 | 判定 |")
            lines.append(f"|:---|:---:|:---:|:---:|:---|")
            lines.append(f"| 全周期 | {drift['full_hr']:.1f}% | {drift['total_signals']} | — | — |")
            for window, data in drift['windows'].items():
                if data['hr'] is not None:
                    lines.append(f"| {window} | {data['hr']:.1f}% | {data['signals']} | {data['drift_vs_full']:+.1f}pp | {data['level']} |")
                else:
                    lines.append(f"| {window} | — | {data['signals']} | — | {data['warning']} |")
            lines.append(f"")
        
        # P0-2
        sens = r['sensitivity']
        if 'error' not in sens:
            lines.append(f"### P0-2 参数敏感度")
            lines.append(f"")
            lines.append(f"- 基准k={sens['base_k']} | {sens['overfit_warning']}")
            lines.append(f"- 最大HR降幅: {sens['max_hr_drop']:.1f}pp (k偏移{sens['critical_delta']:+.2f})" if sens['critical_delta'] else "")
            lines.append(f"")
            lines.append(f"| k值 | HR | 信号数 | PF | EV | 最大连亏 |")
            lines.append(f"|:---:|:---:|:---:|:---:|:---:|:---:|")
            for k_val in sorted(sens['sensitivity'].keys()):
                sr = sens['sensitivity'][k_val]
                marker = ' ←' if abs(k_val - sens['base_k']) < 0.001 else ''
                lines.append(f"| {k_val:.2f}{marker} | {sr['hr']:.1f}% | {sr['signals']} | {sr['pf']:.2f} | {sr['expectancy']:+.2f}% | {sr['max_consec']}笔 |")
            lines.append(f"")
        
        # P0-3
        consec = r['consec']
        lines.append(f"### P0-3 最大连续亏损时间标记")
        lines.append(f"")
        lines.append(f"- 总亏损段: {consec['total_segments']}段 | 最大连续亏损: {consec['max_consec']}笔")
        if consec['max_segment']:
            ms = consec['max_segment']
            lines.append(f"- 最大段: {ms['start_date'].strftime('%Y-%m-%d')} ~ {ms['end_date'].strftime('%Y-%m-%d')}")
            lines.append(f"  - {ms['count']}笔连续亏损 | 累计{ms['total_loss_pct']:+.2f}% | 平均{ms['avg_loss_pct']:+.2f}%/笔")
        if consec['danger_segments']:
            lines.append(f"- ⚠️ ≥5笔连续亏损段: {len(consec['danger_segments'])}段")
            for i, ds in enumerate(consec['danger_segments']):
                lines.append(f"  {i+1}. {ds['start_date'].strftime('%Y-%m-%d')} ~ {ds['end_date'].strftime('%Y-%m-%d')} ({ds['count']}笔, 累计{ds['total_loss_pct']:+.2f}%)")
        lines.append(f"")
    
    content = '\n'.join(lines)
    
    if filename:
        os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n📄 P0高级回测报告已导出: {filename}")
    
    return content


# ============================================================
# CLI入口
# ============================================================

if __name__ == '__main__':
    years = 3
    export = False
    output_file = None
    sensitivity_only = False
    
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--years' and i+1 < len(args):
            years = int(args[i+1])
            i += 2
        elif arg == '--export' and i+1 < len(args):
            export = True
            output_file = args[i+1]
            i += 2
        elif arg == '--ticker' and i+1 < len(args):
            ticker = args[i+1].upper()
            if ticker in TICKER_CONFIG:
                run_p0_analysis(ticker, TICKER_CONFIG[ticker], years=years)
                sys.exit(0)
            elif ticker in DEPRIVED:
                print(f"⚠️ {ticker} ({DEPRIVED[ticker]['name']}) 已剥夺反击资格，不参与回测。")
                sys.exit(0)
            else:
                print(f"❌ 标的不在反击池内: {ticker}")
                sys.exit(1)
        elif arg == '--sensitivity-only':
            sensitivity_only = True
            i += 1
        else:
            i += 1
    
    if sensitivity_only:
        print("🔬 仅参数敏感度分析模式\n")
        for ticker, cfg in TICKER_CONFIG.items():
            print(f"\n{'='*60}")
            print(f"  {ticker} {cfg['name']} (k={cfg['k']})")
            print(f"{'='*60}")
            sens = calc_parameter_sensitivity(ticker, cfg, years=years)
            if 'error' not in sens:
                print(f"  {sens['overfit_warning']}")
                for k_val in sorted(sens['sensitivity'].keys()):
                    r = sens['sensitivity'][k_val]
                    marker = ' ← 当前' if abs(k_val - sens['base_k']) < 0.001 else ''
                    print(f"  k={k_val:.2f}: HR={r['hr']:.1f}% | {r['signals']}笔 | "
                          f"PF={r['pf']:.2f} | EV={r['expectancy']:+.2f}%{marker}")
    else:
        results = run_all_p0_analysis(years=years, verbose=True)
        
        if export and output_file:
            export_p0_to_markdown(results, output_file)
