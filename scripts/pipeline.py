#!/usr/bin/env python3
"""
pipeline.py V1.0 — 统一数据管道（2026-08-12 焊入）

联邦投顾代码化架构的核心：物理事实层（脚本管）与解读叙事层（LLM管）的接口边界。

设计原则：
  - 脚本输出纯JSON，不渲染Markdown
  - LLM读取JSON后做战场审计叙事
  - 接口边界 = JSON schema，不是Markdown模板

用法：
  # 扫描（全池/美股/A股）
  python3 scripts/pipeline.py scan              # 全池24标扫描数据
  python3 scripts/pipeline.py scan --scope us    # 美股12标
  python3 scripts/pipeline.py scan --scope cn    # A股12标

  # 开火（全量/仅进攻/仅反击）
  python3 scripts/pipeline.py fire               # /开火
  python3 scripts/pipeline.py fire --mode offense  # /进攻
  python3 scripts/pipeline.py fire --mode counterpunch  # /反击
  python3 scripts/pipeline.py fire --scope us    # /开火美股
  python3 scripts/pipeline.py fire --scope cn    # /开火A股

  # 持仓
  python3 scripts/pipeline.py position            # /持仓

  # 止损
  python3 scripts/pipeline.py stoploss MUFG       # /止损 <标的>

流水线：
  market_data.py → route_engine.py → positions.json → fire_signal
     → macro_gate → game_state → stop_loss_engine

输出：纯JSON到stdout，LLM读取后负责解读和叙事
"""

import json
import sys
import os
import subprocess
from datetime import datetime
from typing import Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(SCRIPT_DIR, "..")


def run_script(name: str, args: list = [], json_flag: str = "--json") -> dict:
    """运行同目录下的脚本并返回JSON"""
    script_path = os.path.join(SCRIPT_DIR, name)
    cmd = ["python3", script_path] + args
    if json_flag:
        cmd.append(json_flag)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        return {"error": f"脚本 {name} 执行失败", "stderr": result.stderr[:500]}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"JSON解析失败: {e}", "raw": result.stdout[:500]}


def pipeline_scan(scope: str = "all") -> dict:
    """扫描管道"""
    result = run_script("scan_report.py", [f"--scope", scope])
    return result


def pipeline_fire(scope: str = "all", mode: str = "full") -> dict:
    """开火管道"""
    args = [f"--scope", scope, f"--mode", mode]
    result = run_script("fire_report.py", args)
    return result


def pipeline_position() -> dict:
    """持仓管道"""
    result = run_script("position_report.py")
    return result


def pipeline_stoploss(ticker: str) -> dict:
    """止损管道 — stop_loss_engine 的 --json 在 ticker 后面"""
    result = run_script("stop_loss_engine.py", [ticker.upper(), "--json"], json_flag="")
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="联邦投顾统一数据管道")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # scan
    scan_parser = subparsers.add_parser("scan", help="扫描数据")
    scan_parser.add_argument("--scope", choices=["us", "cn", "all"], default="all")

    # fire
    fire_parser = subparsers.add_parser("fire", help="开火数据")
    fire_parser.add_argument("--scope", choices=["us", "cn", "all"], default="all")
    fire_parser.add_argument("--mode", choices=["full", "offense", "counterpunch"], default="full")

    # position
    subparsers.add_parser("position", help="持仓数据")

    # stoploss
    sl_parser = subparsers.add_parser("stoploss", help="止损数据")
    sl_parser.add_argument("ticker", help="标的代码")

    args = parser.parse_args()

    if args.command == "scan":
        result = pipeline_scan(args.scope)
    elif args.command == "fire":
        result = pipeline_fire(args.scope, args.mode)
    elif args.command == "position":
        result = pipeline_position()
    elif args.command == "stoploss":
        result = pipeline_stoploss(args.ticker)
    else:
        parser.print_help()
        sys.exit(1)

    # 统一输出
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
