#!/usr/bin/env python3
"""
联邦投顾 — 管道日志 V1.0
=======================
每次管道化指令（/扫描 /开火 /持仓 /大师对撞 /技术）触发时，
自动将脚本JSON输出持久化到 logs/ 目录，同时记录性能指标。

用法（被其他脚本 import）:
  from pipeline_logger import log_pipeline

  result = fire_report.main()  # 返回 JSON dict
  log_pipeline("fire", "all", result, elapsed_ms=1234)

用法（独立 CLI）:
  python3 scripts/pipeline_logger.py --list           # 列出最近10次记录
  python3 scripts/pipeline_logger.py --stats          # 汇总统计
  python3 scripts/pipeline_logger.py --show <log_id>  # 查看某次完整JSON
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent
LOGS_DIR = WORKSPACE / "logs"
PIPELINE_LOG = LOGS_DIR / "pipeline.jsonl"
PERF_LOG = LOGS_DIR / "perf.jsonl"
INDEX_DIR = LOGS_DIR / "index"


def ensure_dirs():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)


def log_pipeline(command: str, scope: str, json_data: dict, elapsed_ms: float = 0,
                 gate_result: dict = None, success: bool = True):
    """
    持久化一次管道执行记录。
    
    Args:
        command: 指令名 (scan/fire/position/masters/tech/offense/counterpunch)
        scope: 范围 (all/cn/us) 或标的代码
        json_data: 脚本输出的完整JSON
        elapsed_ms: 执行耗时（毫秒）
        gate_result: output_gate 的校验结果（可选）
        success: 是否成功
    """
    ensure_dirs()
    
    timestamp = datetime.now()
    ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    date_str = timestamp.strftime("%Y-%m-%d")
    log_id = timestamp.strftime("%Y%m%d_%H%M%S") + f"_{command}"
    
    # —— 完整 JSON 存档 ——
    json_path = LOGS_DIR / f"{date_str}" / f"{log_id}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump({
            "log_id": log_id,
            "command": command,
            "scope": scope,
            "timestamp": ts_str,
            "success": success,
            "elapsed_ms": elapsed_ms,
            "gate_result": gate_result,
            "data": json_data
        }, f, indent=2, ensure_ascii=False, default=str)
    
    # —— 摘要行（pipeline.jsonl） ——
    summary = {
        "log_id": log_id,
        "command": command,
        "scope": scope,
        "timestamp": ts_str,
        "success": success,
        "elapsed_ms": elapsed_ms,
        "gate": gate_result.get("gate") if gate_result else None,
        "data_keys": list(json_data.keys())[:10] if isinstance(json_data, dict) else [],
        "data_size_kb": round(len(json.dumps(json_data, default=str)) / 1024, 1)
    }
    with open(PIPELINE_LOG, "a") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    
    # —— 性能日志（perf.jsonl） ——
    perf = {
        "log_id": log_id,
        "command": command,
        "scope": scope,
        "timestamp": ts_str,
        "elapsed_ms": elapsed_ms,
        "gate_passed": gate_result.get("gate") == "PASS" if gate_result else None
    }
    with open(PERF_LOG, "a") as f:
        f.write(json.dumps(perf, ensure_ascii=False) + "\n")
    
    return log_id


def list_recent(n: int = 10):
    """列出最近 N 次管道执行记录"""
    ensure_dirs()
    if not PIPELINE_LOG.exists():
        return []
    
    lines = []
    with open(PIPELINE_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(json.loads(line))
    
    return lines[-n:]


def show_log(log_id: str):
    """根据 log_id 查找并返回完整 JSON"""
    ensure_dirs()
    # 从 log_id 提取日期: YYYYMMDD_HHMMSS_command
    date_str = log_id[:10].replace("_", "-")  # YYYYMMDD → YYYY-MM-DD
    date_dir = LOGS_DIR / date_str
    
    if not date_dir.exists():
        # 尝试在所有日期目录中搜索
        for d in sorted(LOGS_DIR.glob("*/"), reverse=True):
            f = d / f"{log_id}.json"
            if f.exists():
                with open(f) as fh:
                    return json.load(fh)
        return None
    
    json_path = date_dir / f"{log_id}.json"
    if json_path.exists():
        with open(json_path) as f:
            return json.load(f)
    return None


def get_stats(days: int = 7):
    """获取最近 N 天的性能统计"""
    ensure_dirs()
    if not PERF_LOG.exists():
        return {"total_calls": 0, "by_command": {}, "avg_elapsed_ms": 0}
    
    cutoff = datetime.now().timestamp() - days * 86400
    calls = []
    with open(PERF_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line)
                ts = datetime.strptime(d["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp()
                if ts >= cutoff:
                    calls.append(d)
    
    if not calls:
        return {"total_calls": 0, "by_command": {}, "avg_elapsed_ms": 0}
    
    by_cmd = {}
    for c in calls:
        cmd = c["command"]
        if cmd not in by_cmd:
            by_cmd[cmd] = {"count": 0, "total_ms": 0, "pass": 0, "block": 0}
        by_cmd[cmd]["count"] += 1
        by_cmd[cmd]["total_ms"] += c["elapsed_ms"]
        if c["gate_passed"] is True:
            by_cmd[cmd]["pass"] += 1
        elif c["gate_passed"] is False:
            by_cmd[cmd]["block"] += 1
    
    # 计算平均
    for cmd in by_cmd:
        by_cmd[cmd]["avg_ms"] = round(by_cmd[cmd]["total_ms"] / by_cmd[cmd]["count"])
    
    return {
        "total_calls": len(calls),
        "avg_elapsed_ms": round(sum(c["elapsed_ms"] for c in calls) / len(calls)),
        "by_command": by_cmd
    }


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args = sys.argv[1:]
    
    if not args:
        recent = list_recent(10)
        print(f"最近 {len(recent)} 次管道执行:\n")
        for r in recent:
            gate_icon = "✅" if r.get("gate") == "PASS" else ("❌" if r.get("gate") == "BLOCK" else "⚪")
            print(f"  {gate_icon} {r['log_id']}  {r['command']}/{r['scope']}  {r['elapsed_ms']}ms  {r['data_size_kb']}KB")
        sys.exit(0)
    
    if args[0] == "--list":
        n = int(args[1]) if len(args) > 1 else 10
        recent = list_recent(n)
        print(f"最近 {len(recent)} 次管道执行:\n")
        for r in recent:
            gate_icon = "✅" if r.get("gate") == "PASS" else ("❌" if r.get("gate") == "BLOCK" else "⚪")
            print(f"  {gate_icon} {r['log_id']}  {r['command']}/{r['scope']}  {r['elapsed_ms']}ms  {r['data_size_kb']}KB")
    
    elif args[0] == "--stats":
        days = int(args[1]) if len(args) > 1 else 7
        s = get_stats(days)
        print(f"近 {days} 天管道性能统计:\n")
        print(f"  总调用: {s['total_calls']} 次")
        print(f"  平均耗时: {s['avg_elapsed_ms']}ms\n")
        for cmd, stats in sorted(s['by_command'].items()):
            block_rate = f"{stats['block']}/{stats['count']}" if stats['block'] > 0 else "0"
            print(f"  {cmd:12s}  {stats['count']:3d}次  avg={stats['avg_ms']:4d}ms  gate拦截={block_rate}")
    
    elif args[0] == "--show":
        if len(args) < 2:
            print("用法: pipeline_logger.py --show <log_id>")
            sys.exit(1)
        data = show_log(args[1])
        if data:
            print(json.dumps(data, indent=2, ensure_ascii=False, default=str)[:5000])
        else:
            print(f"未找到 log_id={args[1]}")
    
    else:
        print("用法: pipeline_logger.py [--list N] [--stats [days]] [--show log_id]")
