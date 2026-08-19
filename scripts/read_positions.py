#!/usr/bin/env python3
"""
持仓数据只读脚本。
所有LLM输出需要持仓信息时，必须通过此脚本读取 positions.json，
禁止凭记忆/推理/缓存生成持仓数据。

用法:
  python3 read_positions.py              # 输出全部持仓
  python3 read_positions.py --ticker QQQ # 查单标的
  python3 read_positions.py --account A  # 查单账户
  python3 read_positions.py --summary    # 仅输出摘要
  python3 read_positions.py --check MUFG # 检查某标的是否持有
"""

import json
import sys
import os

POSITIONS_PATH = os.path.join(os.path.dirname(__file__), "positions.json")

def load():
    with open(POSITIONS_PATH, "r") as f:
        data = json.load(f)
    # positions.json 顶层结构为 {"positions": {...}}，统一剥掉外层取 positions
    return data.get("positions", data)

def get_holding(data, ticker):
    """返回 (account, holding_dict) 或 (None, None)"""
    for acc in ["A", "B"]:
        h = data["accounts"][acc]["holdings"].get(ticker)
        if h:
            return acc, h
    return None, None

def main():
    data = load()
    args = sys.argv[1:]

    if "--ticker" in args or "-t" in args:
        idx = args.index("--ticker") if "--ticker" in args else args.index("-t")
        ticker = args[idx + 1]
        acc, h = get_holding(data, ticker)
        if h:
            print(json.dumps({"ticker": ticker, "account": acc, **h}, indent=2, ensure_ascii=False))
        else:
            # 检查是否已清仓
            for a in ["A", "B"]:
                if ticker in data["accounts"][a].get("cleared", []):
                    print(json.dumps({"ticker": ticker, "status": "cleared", "account": a}, indent=2, ensure_ascii=False))
                    return
            # 检查是否从未持有
            for a in ["A", "B"]:
                if ticker in data["accounts"][a].get("never_held", []):
                    print(json.dumps({"ticker": ticker, "status": "never_held", "account": a}, indent=2, ensure_ascii=False))
                    return
            print(json.dumps({"ticker": ticker, "status": "not_found"}, indent=2, ensure_ascii=False))

    elif "--account" in args or "-a" in args:
        idx = args.index("--account") if "--account" in args else args.index("-a")
        acc = args[idx + 1].upper()
        print(json.dumps(data["accounts"][acc], indent=2, ensure_ascii=False))

    elif "--summary" in args or "-s" in args:
        print(json.dumps(data["summary"], indent=2, ensure_ascii=False))

    elif "--check" in args or "-c" in args:
        idx = args.index("--check") if "--check" in args else args.index("-c")
        ticker = args[idx + 1]
        acc, h = get_holding(data, ticker)
        if h:
            print(f"HOLDING|{ticker}|{acc}|{h['shares']}股|成本{h['cost']}")
        else:
            for a in ["A", "B"]:
                if ticker in data["accounts"][a].get("cleared", []):
                    print(f"CLEARED|{ticker}|{a}")
                    return
                if ticker in data["accounts"][a].get("never_held", []):
                    print(f"NEVER_HELD|{ticker}|{a}")
                    return
            print(f"NOT_FOUND|{ticker}")

    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
