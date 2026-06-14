#!/usr/bin/env python3
"""
🤖 自动化回测调度引擎 V1.0
签发：守东（资产规划部首席审计官）
生效日期：2026-06-14

功能：
  1. 定时拉取Tushare最新数据 → 跑全池P0高级回测
  2. 结果持久化到 SQLite 数据库
  3. 与上次回测结果对比 → 检测参数漂移/HR恶化
  4. 异常自动告警

用法：
  python3 scripts/auto_backtest.py                        # 手动触发全池回测 + 导出MD
  python3 scripts/auto_backtest.py --schedule             # 启动定时调度（每周六06:00）
  python3 scripts/auto_backtest.py --report               # 查看历史趋势报告
  python3 scripts/auto_backtest.py --ticker 513910        # 单标自动回测
  python3 scripts/auto_backtest.py --no-export            # 不导出MD报告
"""

import sys
import os
import json
import sqlite3
import time
import signal
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest_advanced import (
    TICKER_CONFIG, DEPRIVED, GOLD_SHIELD, ATTACK_ONLY,
    run_p0_analysis, run_all_p0_analysis,
    calc_parameter_sensitivity, calc_rolling_window_drift
)
from hitrate_backtest import fetch_data, calc_technical_indicators, identify_signals

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'backtest_history.db')
REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'reports')

ALERT_THRESHOLDS = {
    'hr_drop_vs_last': -5.0,
    'hr_drop_vs_peak': -10.0,
    'rolling_3m_drop': -15.0,
    'rolling_6m_drop': -20.0,
    'overfit_k_neighbor_drop': -15.0,
    'max_consec_loss': 8,
}


def init_db():
    """初始化 SQLite 数据库"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS backtest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_time TEXT NOT NULL,
            ticker TEXT NOT NULL,
            name TEXT,
            data_start TEXT,
            data_end TEXT,
            total_signals INTEGER,
            hr REAL,
            cr REAL,
            ev REAL,
            pf REAL,
            max_dd REAL,
            max_consec_loss INTEGER,
            rolling_36m_hr REAL,
            rolling_24m_hr REAL,
            rolling_12m_hr REAL,
            rolling_6m_hr REAL,
            rolling_3m_hr REAL,
            drift_warning TEXT,
            sensitivity_max_drop REAL,
            sensitivity_overfit TEXT,
            k_value REAL,
            UNIQUE(run_time, ticker)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_time TEXT NOT NULL,
            ticker TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            details TEXT,
            acknowledged INTEGER DEFAULT 0
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS trend_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            hr REAL,
            ev REAL,
            rolling_6m_hr REAL,
            total_signals INTEGER,
            UNIQUE(snapshot_date, ticker)
        )
    ''')
    
    conn.commit()
    conn.close()



def _hr_pct(base):
    """将 hit_rate (0-1小数) 转为百分比"""
    hr = base.get('hit_rate')
    return hr * 100 if hr is not None else None

def _get_window_hr(drift, window_name):
    """安全提取滚动窗口HR"""
    if 'windows' in drift and window_name in drift['windows']:
        return drift['windows'][window_name].get('hr')
    return None


def save_run(run_time, ticker, name, result):
    """保存单次回测结果到数据库"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    drift = result.get('drift', {})
    sens = result.get('sensitivity', {})
    consec = result.get('consec', {})
    base = result.get('metrics', {})
    
    drift_warnings = []
    if 'windows' in drift:
        for w_name, w_data in drift['windows'].items():
            if 'warning' in w_data:
                drift_warnings.append(f"{w_name}: {w_data['warning']}")
    
    c.execute('''
        INSERT OR REPLACE INTO backtest_runs (
            run_time, ticker, name, data_start, data_end,
            total_signals, hr, cr, ev, pf, max_dd, max_consec_loss,
            rolling_36m_hr, rolling_24m_hr, rolling_12m_hr, rolling_6m_hr, rolling_3m_hr,
            drift_warning, sensitivity_max_drop, sensitivity_overfit, k_value
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        run_time, ticker, name,
        result.get('data_start'), result.get('data_end'),
        base.get('total_signals'),
        _hr_pct(base) or 0, base.get('coverage_rate'), base.get('expectancy'), base.get('profit_factor'), base.get('max_dd'),
        consec.get('max_consec'),
        _get_window_hr(drift, '36月'), _get_window_hr(drift, '24月'),
        _get_window_hr(drift, '12月'), _get_window_hr(drift, '6月'),
        _get_window_hr(drift, '3月'),
        '; '.join(drift_warnings) if drift_warnings else None,
        sens.get('max_hr_drop') if 'error' not in sens else None,
        sens.get('overfit_warning') if 'error' not in sens else None,
        result.get('k_value')
    ))
    
    conn.commit()
    conn.close()


def save_alert(alert_time, ticker, alert_type, severity, message, details=None):
    """保存告警到数据库"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO alerts (alert_time, ticker, alert_type, severity, message, details)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (alert_time, ticker, alert_type, severity, message, 
          json.dumps(details) if details else None))
    conn.commit()
    conn.close()


def get_last_run(ticker=None):
    """获取上次回测结果"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if ticker:
        c.execute('SELECT * FROM backtest_runs WHERE ticker=? ORDER BY run_time DESC LIMIT 1', (ticker,))
    else:
        c.execute('SELECT MAX(run_time) FROM backtest_runs')
        last_time = c.fetchone()[0]
        if last_time:
            c.execute('SELECT * FROM backtest_runs WHERE run_time=?', (last_time,))
        else:
            conn.close()
            return []
    
    rows = c.fetchall()
    conn.close()
    return rows


def save_trend_snapshot(snapshot_date, results):
    """保存趋势快照"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    for ticker, result in results.items():
        base = result.get('metrics', {})
        drift = result.get('drift', {})
        rolling_6m = _get_window_hr(drift, '6月')
        
        c.execute('''
            INSERT OR REPLACE INTO trend_snapshots 
            (snapshot_date, ticker, hr, ev, rolling_6m_hr, total_signals)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            snapshot_date, ticker,
            _hr_pct(base) or 0, base.get('expectancy'),
            rolling_6m, base.get('total_signals')
        ))
    
    conn.commit()
    conn.close()


def check_alerts(ticker, name, result, previous_run=None):
    """检测并生成告警"""
    alerts = []
    run_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    base = result.get('metrics', {})
    drift = result.get('drift', {})
    sens = result.get('sensitivity', {})
    consec = result.get('consec', {})
    hr_current = _hr_pct(base) or 0
    
    # 1. 滚动窗口漂移告警
    if 'windows' in drift:
        for w_name, w_data in drift['windows'].items():
            w_hr = w_data.get('hr')
            if w_hr is None or hr_current is None:
                continue
            drift_pp = w_hr - hr_current
            
            if w_name == '3月' and drift_pp <= ALERT_THRESHOLDS['rolling_3m_drop']:
                msg = f"近3月HR={w_hr:.1f}% 较全周期{hr_current:.1f}% 恶化{drift_pp:.1f}pp"
                alerts.append(('drift', '🔴', msg, 
                    {'window': '3月', 'hr': w_hr, 'full_hr': hr_current, 'drift_pp': drift_pp}))
            elif w_name == '6月' and drift_pp <= ALERT_THRESHOLDS['rolling_6m_drop']:
                msg = f"近6月HR={w_hr:.1f}% 较全周期{hr_current:.1f}% 恶化{drift_pp:.1f}pp"
                alerts.append(('drift', '🔴', msg,
                    {'window': '6月', 'hr': w_hr, 'full_hr': hr_current, 'drift_pp': drift_pp}))
            elif w_name == '12月' and drift_pp <= ALERT_THRESHOLDS['rolling_3m_drop']:
                msg = f"近12月HR={w_hr:.1f}% 较全周期{hr_current:.1f}% 恶化{drift_pp:.1f}pp"
                alerts.append(('drift', '🟡', msg,
                    {'window': '12月', 'hr': w_hr, 'full_hr': hr_current, 'drift_pp': drift_pp}))
    
    # 2. 参数过拟合告警
    if 'error' not in sens and sens.get('max_hr_drop', 0) is not None:
        max_drop = sens['max_hr_drop']
        critical_delta = sens.get('critical_delta', 0)
        if max_drop <= ALERT_THRESHOLDS['overfit_k_neighbor_drop'] and abs(critical_delta) <= 0.10:
            msg = f"参数过拟合风险：邻域k偏移{critical_delta:+.2f}时HR降幅{max_drop:.1f}pp"
            alerts.append(('overfit', '🔴', msg, 
                {'max_drop': max_drop, 'critical_delta': critical_delta}))
    
    # 3. 连续亏损告警
    max_consec = consec.get('max_consec', 0)
    if max_consec >= ALERT_THRESHOLDS['max_consec_loss']:
        msg = f"最大连续亏损{max_consec}笔 ≥ {ALERT_THRESHOLDS['max_consec_loss']}笔 — 执行心理风险"
        if consec.get('max_segment'):
            seg = consec['max_segment']
            msg += f"（{seg.get('start_date', '?')} ~ {seg.get('end_date', '?')}）"
        alerts.append(('consec_loss', '🔴', msg, {'max_consec': max_consec}))
    
    # 4. 与上次对比告警
    if previous_run:
        prev_hr = previous_run[6]
        if prev_hr is not None and hr_current is not None:
            hr_change = hr_current - prev_hr
            if hr_change <= ALERT_THRESHOLDS['hr_drop_vs_last']:
                msg = f"HR较上次下降{hr_change:.1f}pp（{prev_hr:.1f}% → {hr_current:.1f}%）"
                alerts.append(('hr_decline', '🟡', msg,
                    {'prev_hr': prev_hr, 'current_hr': hr_current, 'change': hr_change}))
    
    # 入库告警
    for alert in alerts:
        save_alert(run_time, ticker, alert[0], alert[1], f"[{name}] {alert[2]}", alert[3])
    
    return alerts


def run_auto_backtest(ticker=None, check_only=False, export_md=True):
    """
    执行自动回测
    - ticker: 指定标的（None=全池）
    - check_only: 保留参数，暂未实现数据新鲜度检查
    - export_md: 是否导出Markdown报告
    """
    run_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    snapshot_date = datetime.now().strftime('%Y-%m-%d')
    
    print(f"\n{'='*60}")
    print(f"🤖 自动化回测引擎 V1.0")
    print(f"   触发时间: {run_time}")
    mode_desc = f"单标({ticker})" if ticker else "全池"
    print(f"   模式: {mode_desc} | {'导出MD' if export_md else '仅入库'}")
    print(f"{'='*60}\n")
    
    init_db()
    
    all_alerts = {}
    all_results = {}
    
    tickers_to_test = [ticker] if ticker else list(TICKER_CONFIG.keys())
    
    for t in tickers_to_test:
        cfg = TICKER_CONFIG[t]
        name = cfg['name']
        
        print(f"📊 [{t}] {name} ...", end=' ', flush=True)
        
        try:
            result = run_p0_analysis(t, cfg, years=3, verbose=False)
            all_results[t] = result
            
            prev_runs = get_last_run(t)
            prev_run = prev_runs[0] if prev_runs else None
            
            alerts = check_alerts(t, name, result, prev_run)
            all_alerts[t] = alerts
            
            save_run(run_time, t, name, result)
            
            base = result.get('metrics', {})
            hr = _hr_pct(base) or 0
            drift = result.get('drift', {})
            r6m_val = _get_window_hr(drift, '6月')
            rolling_6m = f"{r6m_val:.1f}%" if r6m_val is not None else '-'
            
            status = f"HR={hr:.1f}% | 近6月={rolling_6m}"
            if alerts:
                status += f" | ⚠️ {len(alerts)}条告警"
            print(status)
            
            for alert in alerts:
                print(f"  {alert[1]} [{alert[0]}] {alert[2]}")
        
        except Exception as e:
            print(f"❌ 回测失败: {e}")
            import traceback
            traceback.print_exc()
    
    if all_results:
        save_trend_snapshot(snapshot_date, all_results)
    
    if export_md and all_results:
        os.makedirs(REPORT_DIR, exist_ok=True)
        filename = os.path.join(REPORT_DIR, f'auto_backtest_{snapshot_date}.md')
        export_summary_md(all_results, all_alerts, run_time, filename)
        print(f"\n📄 报告已导出: {filename}")
    
    total_alerts = sum(len(a) for a in all_alerts.values())
    print(f"\n{'='*60}")
    print(f"✅ 自动回测完成 | {len(all_results)}/{len(tickers_to_test)}标成功 | {total_alerts}条告警")
    print(f"{'='*60}\n")
    
    return all_results, all_alerts


def export_summary_md(results, alerts, run_time, filename):
    """导出汇总 Markdown 报告"""
    lines = [
        f"# 🤖 自动化回测报告",
        f"",
        f"**运行时间**: {run_time}",
        f"**标的数量**: {len(results)}",
        f"",
        f"---",
        f"",
        f"## 📊 全池概览",
        f"",
        f"| 标的 | 名称 | HR | EV | PF | 信号数 | 近6月HR | 近12月HR | 连亏 | 告警 |",
        f"|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    
    for t, r in results.items():
        cfg = TICKER_CONFIG[t]
        base = r.get('metrics', {})
        drift = r.get('drift', {})
        consec = r.get('consec', {})
        ticker_alerts = alerts.get(t, [])
        
        r6m = f"{_get_window_hr(drift, '6月'):.1f}%" if _get_window_hr(drift, '6月') is not None else '-'
        r12m = f"{_get_window_hr(drift, '12月'):.1f}%" if _get_window_hr(drift, '12月') is not None else '-'
        
        alert_icon = '🔴' if any(a[1] == '🔴' for a in ticker_alerts) else ('🟡' if ticker_alerts else '✅')
        
        lines.append(
            f"| {t} | {cfg['name']} | {(_hr_pct(base) or 0):.1f}% | {base.get('expectancy', 0):+.2f}% | "
            f"{base.get('profit_factor', 0):.2f} | {base.get('total_signals', 0)} | {r6m} | {r12m} | "
            f"{consec.get('max_consec', '-')}笔 | {alert_icon} |"
        )
    
    if any(alerts.values()):
        lines.extend(["", "---", "", "## ⚠️ 告警详情", ""])
        for t, ticker_alerts in alerts.items():
            if ticker_alerts:
                cfg = TICKER_CONFIG[t]
                lines.append(f"### {t} {cfg['name']}")
                for a in ticker_alerts:
                    lines.append(f"- {a[1]} [{a[0]}] {a[2]}")
                lines.append("")
    
    lines.extend(["", "---", "", "## 📈 趋势变化", "",
                   "运行 `--report` 查看完整历史趋势。", ""])
    
    content = '\n'.join(lines)
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)


def show_trend_report():
    """展示历史趋势报告"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('SELECT DISTINCT snapshot_date FROM trend_snapshots ORDER BY snapshot_date DESC LIMIT 10')
    dates = [r[0] for r in c.fetchall()]
    
    if not dates:
        print("📭 暂无历史回测数据。运行一次自动回测后会生成趋势。")
        conn.close()
        return
    
    print(f"\n{'='*60}")
    print(f"📈 历史回测趋势报告")
    print(f"   数据范围: {dates[-1]} ~ {dates[0]} ({len(dates)}次快照)")
    print(f"{'='*60}\n")
    
    for ticker, cfg in TICKER_CONFIG.items():
        c.execute('''
            SELECT snapshot_date, hr, rolling_6m_hr, total_signals 
            FROM trend_snapshots WHERE ticker=? 
            ORDER BY snapshot_date DESC LIMIT 5
        ''', (ticker,))
        rows = c.fetchall()
        
        if rows:
            print(f"📊 {ticker} {cfg['name']}")
            for row in rows:
                date, hr, r6m, signals = row
                hr_s = f"HR={hr:.1f}%" if hr else "HR=N/A"
                r6m_s = f"近6月={r6m:.1f}%" if r6m else "近6月=N/A"
                sig_s = f"信号={signals}" if signals else ""
                print(f"  {date}: {hr_s} | {r6m_s} | {sig_s}")
            print()
    
    conn.close()


def run_scheduler():
    """定时调度模式 — 每周六06:00自动执行"""
    print("🤖 自动回测调度器已启动")
    print("   执行时间: 每周六 06:00")
    print("   按 Ctrl+C 停止\n")
    
    running = True
    
    def handler(sig, frame):
        nonlocal running
        print("\n⏹ 调度器停止")
        running = False
    
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    
    last_run_date = None
    
    while running:
        now = datetime.now()
        current_date = now.strftime('%Y-%m-%d')
        
        is_saturday = now.weekday() == 5
        is_trigger = now.hour == 6 and now.minute < 5
        
        if is_saturday and is_trigger and last_run_date != current_date:
            print(f"\n⏰ 触发定时回测: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            try:
                run_auto_backtest(export_md=True)
            except Exception as e:
                print(f"❌ 定时回测异常: {e}")
                import traceback
                traceback.print_exc()
            last_run_date = current_date
        
        time.sleep(30)


# ============================================================
# CLI 入口
# ============================================================

if __name__ == '__main__':
    if '--schedule' in sys.argv:
        run_scheduler()
    
    elif '--report' in sys.argv:
        show_trend_report()
    
    elif '--ticker' in sys.argv:
        idx = sys.argv.index('--ticker')
        if idx + 1 < len(sys.argv):
            ticker = sys.argv[idx + 1].upper()
            if ticker in TICKER_CONFIG:
                export_md = '--no-export' not in sys.argv
                run_auto_backtest(ticker=ticker, export_md=export_md)
            else:
                print(f"❌ 标的不在反击池内: {ticker}")
                print(f"   可用: {', '.join(TICKER_CONFIG.keys())}")
                sys.exit(1)
        else:
            print("❌ 缺少标的参数")
            sys.exit(1)
    
    else:
        export_md = '--no-export' not in sys.argv
        run_auto_backtest(export_md=export_md)
