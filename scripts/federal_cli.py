#!/usr/bin/env python3
"""
联邦投顾 — 统一调度入口 V1.0
============================
替代 LLM 记住 11 个独立脚本的调用方式，统一为一个入口。

用法:
  python3 scripts/federal_cli.py scan [--scope all|cn|us] [--json]
  python3 scripts/federal_cli.py fire [--mode full|offense|counterpunch] [--scope all|cn|us] [--json]
  python3 scripts/federal_cli.py position [--json]
  python3 scripts/federal_cli.py masters <ticker> [--json]
  python3 scripts/federal_cli.py tech <ticker> [--json]
  python3 scripts/federal_cli.py stoploss <ticker> [--json]
  python3 scripts/federal_cli.py gate [--check <type>] [--json-file <path>]
  python3 scripts/federal_cli.py log [--list] [--stats] [--show <id>]
  python3 scripts/federal_cli.py premarket [--json] [--table]
  python3 scripts/federal_cli.py perf [--days N] [--json] [--alerts]

输出:
  --json: 输出纯 JSON + 记录到 pipeline 日志
  无 --json: 输出 Markdown + 记录到 pipeline 日志
"""

import json
import sys
import os
import subprocess
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WORKSPACE = SCRIPT_DIR.parent
LOGS_DIR = WORKSPACE / "logs"


def run_script(script_name: str, args: list, timeout: int = 60) -> dict:
    """运行指定脚本并返回 JSON"""
    script_path = SCRIPT_DIR / script_name
    if not script_path.exists():
        return {"error": f"脚本不存在: {script_name}", "gate": "ERROR"}
    
    cmd = ["python3", str(script_path)] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        
        if result.returncode != 0 and result.stderr:
            return {"error": result.stderr.strip(), "gate": "ERROR", "stdout": result.stdout}
        
        # 尝试解析 JSON
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            # 不是 JSON 输出（可能是 Markdown 模式）
            return {"markdown": result.stdout, "gate": "PASS"}
    
    except subprocess.TimeoutExpired:
        return {"error": f"脚本超时 ({timeout}s)", "gate": "ERROR"}
    except Exception as e:
        return {"error": str(e), "gate": "ERROR"}


def log_and_output(result: dict, command: str, scope: str, elapsed_ms: float):
    """写入 pipeline 日志 + 输出"""
    try:
        from pipeline_logger import log_pipeline
        log_id = log_pipeline(command, scope, result, elapsed_ms)
        if "markdown" not in result:
            result["_log_id"] = log_id
    except ImportError:
        pass
    
    if "markdown" in result:
        print(result["markdown"])
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def cmd_scan(args):
    """ /扫描 /扫描A股 /扫描美股 """
    scope = "all"
    use_json = False
    for a in args:
        if a.startswith("--scope="):
            scope = a.split("=", 1)[1]
        elif a == "--scope":
            idx = args.index("--scope")
            if idx + 1 < len(args):
                scope = args[idx + 1]
        elif a == "--json":
            use_json = True
    
    t0 = time.time()
    script_args = ["--scope", scope]
    if use_json:
        script_args.append("--json")
    result = run_script("scan_report.py", script_args, timeout=90)
    elapsed = (time.time() - t0) * 1000
    
    log_and_output(result, "scan", scope, elapsed)
    return result


def cmd_fire(args):
    """ /开火 /开火A股 /开火美股 /进攻 /反击 """
    mode = "full"
    scope = "all"
    use_json = False
    
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--mode="):
            mode = a.split("=", 1)[1]
        elif a == "--mode":
            if i + 1 < len(args):
                mode = args[i + 1]
                i += 1
        elif a.startswith("--scope="):
            scope = a.split("=", 1)[1]
        elif a == "--scope":
            if i + 1 < len(args):
                scope = args[i + 1]
                i += 1
        elif a == "--json":
            use_json = True
        i += 1
    
    t0 = time.time()
    script_args = ["--mode", mode, "--scope", scope]
    if use_json:
        script_args.append("--json")
    result = run_script("fire_report.py", script_args, timeout=90)
    elapsed = (time.time() - t0) * 1000
    
    log_and_output(result, f"fire_{mode}", scope, elapsed)
    return result


def cmd_position(args):
    """ /持仓 """
    use_json = "--json" in args
    
    t0 = time.time()
    script_args = ["--json"] if use_json else []
    result = run_script("position_report.py", script_args, timeout=45)
    elapsed = (time.time() - t0) * 1000
    
    log_and_output(result, "position", "all", elapsed)
    return result


def cmd_masters(args):
    """ /大师对撞 """
    ticker = args[0] if args and not args[0].startswith("--") else None
    if not ticker:
        return {"error": "需要标的代码: federal_cli.py masters QQQ", "gate": "ERROR"}
    
    use_json = "--json" in args
    
    t0 = time.time()
    script_args = [ticker, "--json"] if use_json else [ticker]
    result = run_script("masters_collision.py", script_args, timeout=60)
    elapsed = (time.time() - t0) * 1000
    
    log_and_output(result, "masters", ticker, elapsed)
    return result


def cmd_tech(args):
    """ /技术 """
    ticker = args[0] if args and not args[0].startswith("--") else None
    if not ticker:
        return {"error": "需要标的代码: federal_cli.py tech 513910", "gate": "ERROR"}
    
    use_json = "--json" in args
    
    t0 = time.time()
    script_args = [ticker, "--json"] if use_json else [ticker]
    result = run_script("tech_report.py", script_args, timeout=60)
    elapsed = (time.time() - t0) * 1000
    
    log_and_output(result, "tech", ticker, elapsed)
    return result


def cmd_stoploss(args):
    """ /止损 /止盈 """
    ticker = args[0] if args and not args[0].startswith("--") else None
    if not ticker:
        return {"error": "需要标的代码: federal_cli.py stoploss MUFG", "gate": "ERROR"}
    
    use_json = "--json" in args
    
    t0 = time.time()
    script_args = [ticker, "--json"] if use_json else [ticker]
    result = run_script("stop_loss_engine.py", script_args, timeout=45)
    elapsed = (time.time() - t0) * 1000
    
    log_and_output(result, "stoploss", ticker, elapsed)
    return result


def cmd_gate(args):
    """ output_gate 代理 """
    gate_args = []
    json_file = None
    
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--check":
            gate_args.append(a)
            if i + 1 < len(args):
                gate_args.append(args[i + 1])
                i += 1
        elif a == "--json-file" or a == "--json":
            if i + 1 < len(args):
                json_file = args[i + 1]
                i += 1
        else:
            gate_args.append(a)
        i += 1
    
    if json_file:
        gate_args.append(json_file)
    
    result = run_script("output_gate.py", gate_args, timeout=30)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return result


def cmd_premarket(args):
    """/盘前 管道化 — 调用 premarket_report.py"""
    from pipeline_logger import log_pipeline as log_pl
    
    script = SCRIPT_DIR / "premarket_report.py"
    if not script.exists():
        print("❌ premarket_report.py 不存在")
        sys.exit(1)

    use_json = "--json" in args
    use_table = "--table" in args

    cmd = [sys.executable, str(script)]
    if use_json:
        cmd.append("--json")
    elif use_table:
        cmd.append("--table")

    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"❌ premarket_report.py 失败: {result.stderr}")
        sys.exit(1)

    output = result.stdout.strip()

    if use_json:
        log_pl("premarket", {"scope": "macro"}, elapsed, True, output)
        print(output)
    else:
        log_pl("premarket", {"scope": "macro"}, elapsed, True)
        print(output)


def cmd_perf(args):
    """性能监控面板 — 调用 perf_monitor.py"""
    script = SCRIPT_DIR / "perf_monitor.py"
    if not script.exists():
        print("❌ perf_monitor.py 不存在")
        sys.exit(1)

    cmd = [sys.executable, str(script)]
    for a in args:
        cmd.append(a)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"❌ perf_monitor.py 失败: {result.stderr}")
        sys.exit(1)

    print(result.stdout)


def cmd_log(args):
    """ pipeline 日志查询 """
    try:
        from pipeline_logger import list_recent, get_stats, show_log
    except ImportError:
        print(json.dumps({"error": "pipeline_logger.py 不可用"}, indent=2, ensure_ascii=False))
        return
    
    if "--stats" in args:
        days = 7
        try:
            idx = args.index("--stats")
            if idx + 1 < len(args) and args[idx + 1].isdigit():
                days = int(args[idx + 1])
        except:
            pass
        s = get_stats(days)
        print(json.dumps(s, indent=2, ensure_ascii=False))
    
    elif "--show" in args:
        try:
            idx = args.index("--show")
            if idx + 1 < len(args):
                data = show_log(args[idx + 1])
                if data:
                    print(json.dumps(data, indent=2, ensure_ascii=False, default=str)[:5000])
                else:
                    print(json.dumps({"error": f"未找到 {args[idx+1]}"}, indent=2, ensure_ascii=False))
        except:
            pass
    
    else:
        n = 10
        try:
            idx = args.index("--list")
            if idx + 1 < len(args) and args[idx + 1].isdigit():
                n = int(args[idx + 1])
        except:
            pass
        recent = list_recent(n)
        for r in recent:
            gate_icon = "✅" if r.get("gate") == "PASS" else ("❌" if r.get("gate") == "BLOCK" else "⚪")
            print(f"{gate_icon} {r['log_id']}  {r['command']:16s} {r['scope']:6s}  {int(r['elapsed_ms']):5d}ms  {r['data_size_kb']:5.1f}KB")


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

COMMANDS = {
    "scan": cmd_scan,
    "fire": cmd_fire,
    "position": cmd_position,
    "masters": cmd_masters,
    "tech": cmd_tech,
    "stoploss": cmd_stoploss,
    "gate": cmd_gate,
    "log": cmd_log,
    "premarket": cmd_premarket,
    "perf": cmd_perf,
}


def main():
    if len(sys.argv) < 2:
        print("联邦投顾统一调度入口 V1.0\n")
        print("用法: python3 scripts/federal_cli.py <指令> [参数]\n")
        print("指令:")
        print("  scan [--scope all|cn|us] [--json]        # /扫描")
        print("  fire [--mode full|offense|counterpunch]   # /开火 /进攻 /反击")
        print("       [--scope all|cn|us] [--json]")
        print("  position [--json]                         # /持仓")
        print("  masters <ticker> [--json]                 # /大师对撞")
        print("  tech <ticker> [--json]                    # /技术")
        print("  stoploss <ticker> [--json]                # /止损 /止盈")
        print("  gate --check <type> [--json-file <path>]  # output_gate")
        print("  log [--list N] [--stats [days]] [--show id]  # 管道日志")
        print("  premarket [--json] [--table]              # /盘前")
        print("  perf [--days N] [--json] [--alerts]       # 性能监控面板")
        sys.exit(0)
    
    cmd = sys.argv[1]
    args = sys.argv[2:]
    
    if cmd not in COMMANDS:
        print(f"未知指令: {cmd}")
        print(f"可用: {', '.join(COMMANDS.keys())}")
        sys.exit(1)
    
    COMMANDS[cmd](args)


if __name__ == "__main__":
    main()
