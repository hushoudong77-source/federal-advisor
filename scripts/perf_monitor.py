#!/usr/bin/env python3
"""
联邦投顾 — 性能监控面板 V1.0
============================
读取 perf.jsonl 和 pipeline.jsonl 生成性能汇总仪表盘。

用法:
  python3 scripts/perf_monitor.py                    # 全文输出
  python3 scripts/perf_monitor.py --days 7            # 最近7天
  python3 scripts/perf_monitor.py --json              # JSON输出(供LLM消费)
  python3 scripts/perf_monitor.py --alerts            # 仅输出告警项
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

WORKSPACE = Path(__file__).parent.parent
LOGS_DIR = WORKSPACE / "logs"
PERF_PATH = LOGS_DIR / "perf.jsonl"
PIPELINE_PATH = LOGS_DIR / "pipeline.jsonl"


def load_logs(path, days=None):
    """加载JSONL日志，可选天数过滤"""
    if not path.exists():
        return []
    cutoff = None
    if days:
        cutoff = datetime.now() - timedelta(days=days)
    logs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if cutoff:
                    ts = entry.get("timestamp", "")
                    try:
                        t = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
                        if t < cutoff:
                            continue
                    except ValueError:
                        pass
                logs.append(entry)
            except json.JSONDecodeError:
                continue
    return logs


def fmt_ms(ms):
    """格式化毫秒"""
    if ms is None:
        return "N/A"
    if ms < 1000:
        return f"{ms:.0f}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    else:
        return f"{ms/60000:.1f}min"


def build_summary(perf_logs, pipeline_logs, output_json=False):
    """构建性能汇总"""
    # 按指令分组统计
    cmd_stats = defaultdict(lambda: {"count": 0, "total_ms": 0, "min_ms": float("inf"), "max_ms": 0,
                                       "success": 0, "fail": 0, "gate_passed": 0, "gate_blocked": 0,
                                       "data_sizes_kb": []})
    timeline = []

    for p in pipeline_logs:
        cmd = p.get("command", "unknown")
        elapsed = p.get("elapsed_ms", 0) or 0
        success = p.get("success", False)
        data_kb = p.get("data_size_kb", 0) or 0
        gate = p.get("gate")

        s = cmd_stats[cmd]
        s["count"] += 1
        s["total_ms"] += elapsed
        if elapsed < s["min_ms"]:
            s["min_ms"] = elapsed
        if elapsed > s["max_ms"]:
            s["max_ms"] = elapsed
        if success:
            s["success"] += 1
        else:
            s["fail"] += 1
        if gate == "PASSED":
            s["gate_passed"] += 1
        elif gate == "BLOCKED":
            s["gate_blocked"] += 1
        if data_kb:
            s["data_sizes_kb"].append(data_kb)

        timeline.append({
            "timestamp": p.get("timestamp", ""),
            "command": cmd,
            "scope": p.get("scope", ""),
            "elapsed_ms": elapsed,
            "success": success,
            "gate": gate
        })

    # 汇总
    total_calls = sum(s["count"] for s in cmd_stats.values())
    total_ms = sum(s["total_ms"] for s in cmd_stats.values())
    total_success = sum(s["success"] for s in cmd_stats.values())
    total_fail = sum(s["fail"] for s in cmd_stats.values())

    # 逐指令
    cmd_rows = []
    for cmd, s in sorted(cmd_stats.items()):
        avg_ms = s["total_ms"] / s["count"] if s["count"] > 0 else 0
        avg_kb = sum(s["data_sizes_kb"]) / len(s["data_sizes_kb"]) if s["data_sizes_kb"] else 0
        cmd_rows.append({
            "command": cmd,
            "count": s["count"],
            "avg_ms": avg_ms,
            "min_ms": s["min_ms"] if s["min_ms"] != float("inf") else 0,
            "max_ms": s["max_ms"],
            "success_rate": f"{s['success']}/{s['count']}",
            "gate_passed": s["gate_passed"],
            "gate_blocked": s["gate_blocked"],
            "avg_data_kb": avg_kb
        })

    # 告警
    alerts = []
    for row in cmd_rows:
        if row["avg_ms"] > 60000:  # 超过60秒
            alerts.append(f"⚠️ {row['command']} 平均耗时 {fmt_ms(row['avg_ms'])}，可能性能退化")
        if row["gate_blocked"] > 0:
            alerts.append(f"🔴 {row['command']} gate拦截 {row['gate_blocked']} 次，存在LLM数字偏差")
        if row["avg_data_kb"] > 500:
            alerts.append(f"🟡 {row['command']} JSON体积大 ({row['avg_data_kb']:.0f}KB)，可能影响LLM解析")

    # 最近调用
    recent = sorted(timeline, key=lambda x: x.get("timestamp", ""), reverse=True)[:10]

    if output_json:
        return {
            "summary": {
                "total_calls": total_calls,
                "total_time_ms": total_ms,
                "total_time_human": fmt_ms(total_ms),
                "success": total_success,
                "fail": total_fail,
                "overall_success_rate": f"{total_success}/{total_calls}" if total_calls > 0 else "N/A"
            },
            "by_command": cmd_rows,
            "alerts": alerts,
            "recent_calls": recent,
            "log_files": {
                "perf_lines": len(perf_logs),
                "pipeline_lines": len(pipeline_logs)
            }
        }
    else:
        return cmd_rows, alerts, recent, total_calls, total_ms, total_success, total_fail


def render_markdown(cmd_rows, alerts, recent, total_calls, total_ms, total_success, total_fail):
    """Markdown 格式输出"""
    lines = []
    lines.append("# 📊 联邦管道性能监控面板")
    lines.append("")
    lines.append(f"**统计周期**: 全部历史 ({total_calls} 次调用)")
    lines.append("")
    lines.append("## 一、总体概览")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|:---|---:|")
    lines.append(f"| 总调用次数 | {total_calls} |")
    lines.append(f"| 总耗时 | {fmt_ms(total_ms)} |")
    lines.append(f"| 成功 | {total_success} |")
    lines.append(f"| 失败 | {total_fail} |")
    lines.append(f"| 成功率 | {total_success}/{total_calls}" if total_calls > 0 else "| 成功率 | N/A |")
    lines.append("")

    if cmd_rows:
        lines.append("## 二、逐指令性能")
        lines.append("")
        lines.append("| 指令 | 调用次数 | 平均耗时 | 最慢 | 最快 | 成功率 | Gate拦截 | 平均数据量 |")
        lines.append("|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
        for row in cmd_rows:
            lines.append(f"| {row['command']} | {row['count']} | {fmt_ms(row['avg_ms'])} | {fmt_ms(row['max_ms'])} | {fmt_ms(row['min_ms'])} | {row['success_rate']} | {row['gate_blocked']} | {row['avg_data_kb']:.0f}KB |")
        lines.append("")

    if alerts:
        lines.append("## 三、告警")
        lines.append("")
        for alert in alerts:
            lines.append(f"- {alert}")
        lines.append("")

    if recent:
        lines.append("## 四、最近调用")
        lines.append("")
        lines.append("| 时间 | 指令 | 耗时 | 状态 | Gate |")
        lines.append("|:---|:---|:---|:---|:---|")
        for r in recent:
            ts = r.get("timestamp", "")[:19]
            gs = "✅" if r.get("gate") == "PASSED" else ("🔴" if r.get("gate") == "BLOCKED" else "—")
            ss = "✅" if r.get("success") else "❌"
            lines.append(f"| {ts} | {r.get('command','')} | {fmt_ms(r.get('elapsed_ms',0))} | {ss} | {gs} |")
        lines.append("")

    lines.append("---")
    lines.append("📌 日志位置: `logs/perf.jsonl` + `logs/pipeline.jsonl`")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="联邦投顾性能监控面板")
    parser.add_argument("--days", type=int, default=None, help="最近N天")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--alerts", action="store_true", help="仅告警")
    args = parser.parse_args()

    perf_logs = load_logs(PERF_PATH, args.days)
    pipeline_logs = load_logs(PIPELINE_PATH, args.days)

    if args.json:
        summary = build_summary(perf_logs, pipeline_logs, output_json=True)
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    elif args.alerts:
        _, alerts, _, _, _, _, _ = build_summary(perf_logs, pipeline_logs)
        if alerts:
            for a in alerts:
                print(a)
        else:
            print("✅ 无告警")
    else:
        cmd_rows, alerts, recent, total_calls, total_ms, total_success, total_fail = \
            build_summary(perf_logs, pipeline_logs)
        print(render_markdown(cmd_rows, alerts, recent, total_calls, total_ms, total_success, total_fail))


if __name__ == "__main__":
    main()
