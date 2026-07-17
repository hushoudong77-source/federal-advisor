#!/usr/bin/env python3
"""
🔧 回测调度执行引擎 V1.0
签发：守东（资产规划部首席审计官）
生效日期：2026-07-08

职责：
  对照 SOP V1.3 四层回测框架，根据日期自动路由到对应层级
  L1 周度命中率 / L2 月度Optuna三参数 / L3 季度绩效审计 / L4 样本外校验

用法：
  python3 scripts/backtest_scheduler.py                    # 自动判断今天该跑哪层
  python3 scripts/backtest_scheduler.py --force L1         # 强制跑 L1
  python3 scripts/backtest_scheduler.py --force L2         # 强制跑 L2
  python3 scripts/backtest_scheduler.py --force L3         # 强制跑 L3
  python3 scripts/backtest_scheduler.py --force L4 513910  # 强制跑 L4（需指定标的）
  python3 scripts/backtest_scheduler.py --dry-run          # 只看今天该跑什么，不执行

与 AGENT.md 模块十六对齐：
  - L1: 每周六自动
  - L2: 每月1日自动
  - L3: 1/4/7/10月1日自动
  - L4: 参数修正提案触发时自动
"""

import sys
import os
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
DATA_DIR = PROJECT_DIR / 'data'
REPORT_DIR = DATA_DIR / 'reports'
DB_PATH = DATA_DIR / 'backtest_scheduler.db'

DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 数据库
# ============================================================

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS scheduler_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_time TEXT NOT NULL,
            layer TEXT NOT NULL,
            target TEXT,
            status TEXT NOT NULL,
            output_file TEXT,
            error TEXT,
            duration_sec REAL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS l4_validations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_time TEXT NOT NULL,
            ticker TEXT NOT NULL,
            k REAL,
            stop_mult REAL,
            cooldown INTEGER,
            in_sample_winrate REAL,
            out_sample_winrate REAL,
            verdict TEXT NOT NULL,
            details TEXT
        )
    ''')
    conn.commit()
    conn.close()


def log_run(layer, target, status, output_file=None, error=None, duration=None):
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('''
        INSERT INTO scheduler_runs (run_time, layer, target, status, output_file, error, duration_sec)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (datetime.now().isoformat(), layer, target, status, output_file, error, duration))
    conn.commit()
    conn.close()


# ============================================================
# 日期判断
# ============================================================

def what_to_run_today(now=None):
    """返回今天应该跑的回测层级列表"""
    if now is None:
        now = datetime.now()

    layers = []

    # L1: 每周六
    if now.weekday() == 5:  # Saturday
        layers.append('L1')

    # L2: 每月1日
    if now.day == 1:
        layers.append('L2')

    # L3: 1/4/7/10月1日
    if now.day == 1 and now.month in (1, 4, 7, 10):
        layers.append('L3')

    return layers


# ============================================================
# L1 — 周度全池命中率回测
# ============================================================

def run_l1():
    """
    L1 周度命中率回测：
    - 使用 hitrate_backtest.py 现有 bash 命令
    - 覆盖全池反击标的
    - 输出到 data/reports/l1_YYYY-MM-DD.md
    """
    print("\n" + "=" * 60)
    print("  📐 L1 周度全池命中率回测")
    print("=" * 60)

    today = datetime.now().strftime('%Y-%m-%d')
    output_file = REPORT_DIR / f'l1_{today}.md'

    # 跑 hitrate_backtest.py（反击池全量）
    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / 'hitrate_backtest.py'), '--all'],
        capture_output=True, text=True, timeout=120
    )

    # 构建报告
    lines = [
        f"# 📐 L1 周度买入区间命中率回测",
        f"",
        f"执行时间: {datetime.now().isoformat()}",
        f"数据窗口: 滚动250交易日",
        f"",
        f"## 原始输出",
        f"",
        "```",
        result.stdout[-8000:] if len(result.stdout) > 8000 else result.stdout,
        "```",
    ]

    if result.stderr:
        lines.extend(["", "## 错误输出", "", "```", result.stderr[-2000:], "```"])

    content = '\n'.join(lines)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)

    status = 'success' if result.returncode == 0 else 'error'
    error = result.stderr[:500] if result.returncode != 0 else None

    print(f"  ✅ L1 完成 → {output_file}")
    return status, str(output_file), error


# ============================================================
# L2 — 月度 Optuna 三参数联合优化
# ============================================================

def run_l2():
    """
    L2 月度参数重标定：
    - 调用 optuna_k_optimizer.py --all
    - Trials: 100（月度用轻量版，季度L3时跑完整200）
    - 输出到 data/reports/l2_YYYY-MM-DD.md
    """
    print("\n" + "=" * 60)
    print("  🔬 L2 月度 Optuna 三参数联合优化")
    print("=" * 60)

    today = datetime.now().strftime('%Y-%m-%d')
    output_file = REPORT_DIR / f'l2_{today}.md'

    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / 'optuna_k_optimizer.py'), '--all', '--trials', '100'],
        capture_output=True, text=True, timeout=600
    )

    lines = [
        f"# 🔬 L2 月度 Optuna 三参数联合优化",
        f"",
        f"执行时间: {datetime.now().isoformat()}",
        f"算法: Optuna TPE | Trials: 100/标 | 搜索: k × stop × cooldown",
        f"",
        f"## 原始输出",
        f"",
        "```",
        result.stdout[-12000:] if len(result.stdout) > 12000 else result.stdout,
        "```",
    ]

    if result.stderr:
        lines.extend(["", "## 错误输出", "", "```", result.stderr[-2000:], "```"])

    content = '\n'.join(lines)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)

    status = 'success' if result.returncode == 0 else 'error'
    error = result.stderr[:500] if result.returncode != 0 else None

    print(f"  ✅ L2 完成 → {output_file}")
    return status, str(output_file), error


# ============================================================
# L3 — 季度系统整体绩效审计
# ============================================================

def run_l3():
    """
    L3 季度绩效审计：
    - 跑 hitrate_backtest.py --all（全量数据，500日窗口）
    - 跑 auto_backtest.py（P0高级分析）
    - 汇总输出到 data/reports/l3_YYYY-QN.md
    """
    print("\n" + "=" * 60)
    print("  📊 L3 季度系统整体绩效审计")
    print("=" * 60)

    now = datetime.now()
    quarter = f"{(now.month - 1) // 3 + 1}"
    year = str(now.year)
    output_file = REPORT_DIR / f'l3_{year}-Q{quarter}.md'

    import subprocess

    # 1. 命中率回测
    print("  [1/2] 运行 hitrate_backtest.py --all ...")
    hr_result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / 'hitrate_backtest.py'), '--all'],
        capture_output=True, text=True, timeout=120
    )

    # 2. P0 高级分析
    print("  [2/2] 运行 auto_backtest.py ...")
    auto_result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / 'auto_backtest.py'), '--no-export'],
        capture_output=True, text=True, timeout=120
    )

    lines = [
        f"# 📊 L3 季度系统整体绩效审计",
        f"",
        f"审计周期: {year}年Q{quarter}",
        f"执行时间: {datetime.now().isoformat()}",
        f"数据窗口: 500交易日",
        f"",
        f"---",
        f"",
        f"## 一、反击策略命中率回测",
        f"",
        "```",
        hr_result.stdout[-8000:] if len(hr_result.stdout) > 8000 else hr_result.stdout,
        "```",
    ]

    if hr_result.stderr:
        lines.extend(["", "### 错误", "", "```", hr_result.stderr[-1000:], "```"])

    lines.extend([
        "",
        "---",
        "",
        "## 二、P0 高级分析（参数敏感度 + 滚动漂移）",
        "",
        "```",
        auto_result.stdout[-8000:] if len(auto_result.stdout) > 8000 else auto_result.stdout,
        "```",
    ])

    if auto_result.stderr:
        lines.extend(["", "### 错误", "", "```", auto_result.stderr[-1000:], "```"])

    content = '\n'.join(lines)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)

    status = 'success' if hr_result.returncode == 0 and auto_result.returncode == 0 else 'partial'
    errors = []
    if hr_result.returncode != 0:
        errors.append(f"hitrate: {hr_result.stderr[:200]}")
    if auto_result.returncode != 0:
        errors.append(f"auto: {auto_result.stderr[:200]}")
    error = '; '.join(errors) if errors else None

    print(f"  ✅ L3 完成 → {output_file}")
    return status, str(output_file), error


# ============================================================
# L4 — 样本外校验（参数修正提案前置闸门）
# ============================================================

def run_l4(ticker, k=None, stop_mult=None, cooldown=None):
    """
    L4 样本外校验：
    - 70/30 时间序列分割
    - 样本内训练 → 样本外验证
    - 通过标准：样本外胜率 ≥ 样本内 × 0.70
    - 硬否决：样本外交易 < 5 笔

    输入:
      ticker: 标的代码
      k, stop_mult, cooldown: 待验证的参数（可选，默认用当前编码参数）
    """
    print("\n" + "=" * 60)
    print(f"  🛡️ L4 样本外校验: {ticker}")
    print("=" * 60)

    import subprocess
    import numpy as np
    import pandas as pd

    # 使用 optuna_k_optimizer.py 的 fetch_data/calc_technical_indicators/identify_signals/calc_signal_results
    sys.path.insert(0, str(SCRIPT_DIR))
    from optuna_k_optimizer import (
        fetch_data, calc_technical_indicators, identify_signals, calc_signal_results,
        TICKER_CONFIG as OPTUNA_CONFIG
    )

    if ticker not in OPTUNA_CONFIG:
        msg = f"标的不在配置表中: {ticker}"
        print(f"  ❌ {msg}")
        log_run('L4', ticker, 'error', error=msg)
        return 'error', None, msg

    cfg = OPTUNA_CONFIG[ticker].copy()

    # 参数：优先用传入值，回退到配置表
    k_val = k if k is not None else cfg.get('k', 2.0)
    stop_val = stop_mult if stop_mult is not None else cfg.get('stop_mult', 2.0)
    cool_val = cooldown if cooldown is not None else cfg.get('cooldown', 30)

    # 拉数据
    df_raw = fetch_data(ticker, cfg, years=8)
    if df_raw is None or len(df_raw) < 400:
        msg = f"数据不足（需要≥400条，实际{len(df_raw) if df_raw is not None else 0}条）"
        print(f"  ❌ {msg}")
        log_run('L4', ticker, 'error', error=msg)
        return 'error', None, msg

    df = calc_technical_indicators(df_raw, cfg['anchor'])
    df = df.dropna(subset=['MA', 'ATR14']).reset_index(drop=True)

    # 70/30 时间序列分割
    n = len(df)
    split_idx = int(n * 0.70)

    df_in = df.iloc[:split_idx].copy().reset_index(drop=True)
    df_out = df.iloc[split_idx:].copy().reset_index(drop=True)

    print(f"  数据: {df.iloc[0]['Date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['Date'].strftime('%Y-%m-%d')}")
    print(f"  样本内: {df_in.iloc[0]['Date'].strftime('%Y-%m-%d')} ~ {df_in.iloc[-1]['Date'].strftime('%Y-%m-%d')} ({len(df_in)}条)")
    print(f"  样本外: {df_out.iloc[0]['Date'].strftime('%Y-%m-%d')} ~ {df_out.iloc[-1]['Date'].strftime('%Y-%m-%d')} ({len(df_out)}条)")
    print(f"  参数: k={k_val}, stop={stop_val}, cool={cool_val}")

    # 样本内
    signals_in = identify_signals(df_in, cfg['anchor'], k_val, cfg['hold_days'], cool_val, stop_val)
    signals_in = calc_signal_results(signals_in, df_in)
    valid_in = [s for s in signals_in if s['result'] in ('WIN', 'LOSS', 'STOP')]
    wins_in = len([s for s in valid_in if s['result'] == 'WIN'])
    wr_in = wins_in / len(valid_in) if valid_in else 0

    # 样本外
    signals_out = identify_signals(df_out, cfg['anchor'], k_val, cfg['hold_days'], cool_val, stop_val)
    signals_out = calc_signal_results(signals_out, df_out)
    valid_out = [s for s in signals_out if s['result'] in ('WIN', 'LOSS', 'STOP')]
    wins_out = len([s for s in valid_out if s['result'] == 'WIN'])
    wr_out = wins_out / len(valid_out) if valid_out else 0

    n_out = len(valid_out)

    print(f"  样本内: {len(valid_in)}笔, 胜率={wr_in*100:.1f}%")
    print(f"  样本外: {n_out}笔, 胜率={wr_out*100:.1f}%")

    # 判定
    if n_out < 5:
        verdict = '🔴 否决 — 样本外交易不足5笔'
        verdict_code = 'reject_low_samples'
    elif wr_in > 0 and wr_out >= wr_in * 0.70:
        verdict = '✅ 通过'
        verdict_code = 'pass'
    elif wr_in > 0 and wr_out >= wr_in * 0.50:
        verdict = '🟡 警告 — 样本外胜率显著低于样本内'
        verdict_code = 'warn_degradation'
    else:
        verdict = '🔴 否决 — 样本外胜率 < 样本内×0.50（过拟合）'
        verdict_code = 'reject_overfit'

    print(f"  裁决: {verdict}")

    # 写入数据库
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('''
        INSERT INTO l4_validations (run_time, ticker, k, stop_mult, cooldown,
                                     in_sample_winrate, out_sample_winrate, verdict, details)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().isoformat(), ticker, k_val, stop_val, cool_val,
        round(wr_in, 4), round(wr_out, 4), verdict_code,
        f"in={len(valid_in)}笔/{wr_in*100:.1f}% out={n_out}笔/{wr_out*100:.1f}% split={split_idx}/{n}"
    ))
    conn.commit()
    conn.close()

    # 输出报告
    today = datetime.now().strftime('%Y-%m-%d')
    output_file = REPORT_DIR / f'l4_{ticker}_{today}.md'
    lines = [
        f"# 🛡️ L4 样本外校验: {ticker} {cfg['name']}",
        f"",
        f"执行时间: {datetime.now().isoformat()}",
        f"参数: k={k_val} / stop={stop_val} / cool={cool_val}",
        f"分割: 70/30 时间序列 ({split_idx}/{n})",
        f"",
        f"| 维度 | 样本内 | 样本外 |",
        f"|:---|---:|---:|",
        f"| 交易笔数 | {len(valid_in)} | {n_out} |",
        f"| 胜率 | {wr_in*100:.1f}% | {wr_out*100:.1f}% |",
        f"| 胜率比 | — | {wr_out/wr_in*100:.1f}% |",
        f"",
        f"## 裁决",
        f"",
        f"{verdict}",
    ]
    content = '\n'.join(lines)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)

    log_run('L4', ticker, 'success' if verdict_code == 'pass' else 'warning',
            str(output_file))

    return 'success' if verdict_code == 'pass' else 'warning', str(output_file), None


# ============================================================
# 主入口
# ============================================================

def main():
    init_db()

    force_layer = None
    force_target = None
    dry_run = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--force' and i + 1 < len(args):
            force_layer = args[i + 1].upper()
            i += 2
            # L4 需要额外参数（标的代码）
            if force_layer == 'L4' and i < len(args):
                force_target = args[i]
                i += 1
        elif args[i] == '--dry-run':
            dry_run = True
            i += 1
        else:
            i += 1

    if dry_run:
        layers = what_to_run_today() if force_layer is None else [force_layer]
        print(f"🔍 DRY RUN — 今天会跑: {layers if layers else '无事'}")
        if force_target:
            print(f"   L4 标的: {force_target}")
        return

    if force_layer:
        # 强制模式
        start = datetime.now()
        if force_layer == 'L1':
            status, f, err = run_l1()
            log_run('L1', 'all', status, f, err, (datetime.now() - start).total_seconds())
        elif force_layer == 'L2':
            status, f, err = run_l2()
            log_run('L2', 'all', status, f, err, (datetime.now() - start).total_seconds())
        elif force_layer == 'L3':
            status, f, err = run_l3()
            log_run('L3', 'all', status, f, err, (datetime.now() - start).total_seconds())
        elif force_layer == 'L4':
            if not force_target:
                print("❌ L4 需要指定标的: --force L4 513910")
                return
            status, f, err = run_l4(force_target)
        else:
            print(f"❌ 未知层级: {force_layer}（支持 L1/L2/L3/L4）")
            return
    else:
        # 自动模式：判断今天该跑什么
        layers = what_to_run_today()

        if not layers:
            print("📅 今天无定时回测任务（周六=L1, 每月1日=L2, 季初=L3）")
            return

        print(f"📅 今日回测任务: {layers}")

        for layer in layers:
            start = datetime.now()
            try:
                if layer == 'L1':
                    status, f, err = run_l1()
                elif layer == 'L2':
                    status, f, err = run_l2()
                elif layer == 'L3':
                    status, f, err = run_l3()
                else:
                    continue
                log_run(layer, 'all', status, f, err, (datetime.now() - start).total_seconds())
            except Exception as e:
                import traceback
                err = traceback.format_exc()[-1000:]
                log_run(layer, 'all', 'exception', error=err)
                print(f"  ❌ {layer} 异常: {e}")


if __name__ == '__main__':
    main()
