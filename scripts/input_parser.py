#!/usr/bin/env python3
"""
/输入 指令解析器 — 确定性持仓数据提取与写入。

将守东的 /输入 消息解析为结构化 JSON，直接覆写 positions.json。
零 LLM 参与写入层——正则精确提取，不推断、不扩展、不编造。

用法:
  python3 input_parser.py "/输入 持仓确权：518880 7,000股(¥8.646) / 159915 8,500股(¥3.548)"
  python3 input_parser.py --file /tmp/input.txt            # 从文件读取
  python3 input_parser.py --dry-run "/输入 ..."             # 仅解析不写入
  python3 input_parser.py --account A "/输入 ..."           # 指定账户
  python3 input_parser.py --replace "/输入 ..."              # 全量替换（清空旧持仓）
  python3 input_parser.py --operation "已清仓 513180"       # 操作类指令
  python3 input_parser.py --operation "已买入 MUFG 500股@$21.50"  # 买入操作

支持格式:
  【持仓确权】: /输入 持仓确权：标的A X股(成本$X) / 标的B Y股(成本$Y)
  【持仓确权(逗号)】: /输入 518880 7000股, ¥8.646 / 159915 8500股, ¥3.548
  【操作指令】: /输入 操作：已清仓 513180
  【操作指令】: /输入 操作：已买入 MUFG 500股@$21.50
  【混合】: /输入 持仓确权：... 操作：...
"""

import json
import re
import sys
import os
from datetime import date
from typing import Optional

POSITIONS_PATH = os.path.join(os.path.dirname(__file__), "positions.json")

# ── 全池美股 ETF 代码清单（用于自动路由至 B 账户，美元计价）────
# 与 AGENT.md 模块零「全池标的硬编码白名单」美股段保持一致。
US_ETF_TICKERS = {
    "VTI", "VEA", "QQQ", "IVV", "IAU", "BBJP", "MUFG",
    "EWY", "VNM", "FLIN", "SMIN", "BOTZ", "CANE", "SGOV",
}

# ── 正则模式 ──────────────────────────────────────────────

# 持仓确权: "518880 7,000股(¥8.646)" 或 "518880 7000股 ¥8.646"
RE_HOLDING = re.compile(
    r'(?P<ticker>\d{6}|[A-Z]{2,5})\s+'          # 标的代码
    r'(?P<shares>[\d,]+)\s*股\s*'                # 股数
    r'[\(\（]?\s*[¥$]?\s*(?P<cost>[\d.]+)\s*[\)\）]?'  # 成本
)

# 宽松版: "518880 7000股 8.646" 或 "518880,7000,8.646"
RE_HOLDING_LOOSE = re.compile(
    r'(?P<ticker>\d{6}|[A-Z]{2,5})\s*[,/\s]\s*'  # 标的代码
    r'(?P<shares>[\d,]+)\s*[,/\s]?\s*'            # 股数
    r'[¥$]?\s*(?P<cost>[\d.]+)'                   # 成本
)

# 操作指令: "已清仓 513180" / "已买入 MUFG 500股@$21.50" / "买入 IAU 100股，成本82.415美元"
RE_OPERATION = re.compile(
    r'(?P<action>已?清仓|已?卖出|已?买入|已?加仓|已?减仓|已?建仓)\s+'
    r'(?P<ticker>\d{6}|[A-Z]{2,5})'
    r'(?:'
    r'\s*(?P<shares>[\d,]+)\s*股?'                    # 股数
    r'(?:'
    r'\s*@\s*'                                        # @ 分隔符
    r'|\s*[，,]\s*成本[：:\s]*'                        # 「，成本」分隔符
    r'|\s+'                                           # 或纯空白
    r')'
    r'(?:[¥$]\s*)?'                                   # 货币符号
    r'(?P<price>[\d.]+)'                               # 价格
    r'(?:\s*(?:美元|元|人民币))?'                       # 货币后缀词
    r')?'
)

# 从文本中剥离操作指令部分，避免被持仓确权正则误匹配
RE_OPERATION_SECTION = re.compile(
    r'操作[：:]\s*(.+?)(?=\s*(?:持仓确权|$))'
)

# 账户识别
RE_ACCOUNT = re.compile(r'[ABab]\s*账户|account\s*[ABab]', re.IGNORECASE)
RE_ACCOUNT_HINT = re.compile(r'(?<!\d)([AB])\s*账户', re.IGNORECASE)


def parse_shares(s: str) -> int:
    """解析股数，移除逗号"""
    return int(s.replace(",", ""))


def parse_cost(s: str) -> float:
    """解析成本"""
    return float(s)


def detect_account(text: str) -> Optional[str]:
    """尝试从文本中检测账户"""
    m = RE_ACCOUNT_HINT.search(text)
    if m:
        return m.group(1).upper()
    return None


def detect_us_tickers(text: str) -> list[str]:
    """从 /输入 文本中检测美股 ETF 代码（纯字母，非数字 A 股代码）。"""
    found = []
    for ticker in US_ETF_TICKERS:
        # 用词边界匹配，避免如 "IAU" 误匹配到别的单词
        if re.search(rf'\b{re.escape(ticker)}\b', text, re.IGNORECASE):
            found.append(ticker)
    return found


def route_account(text: str, explicit_account: Optional[str]) -> Optional[str]:
    """
    账户自动路由逻辑：
    1. 守东显式指定（--account 或文本内「X账户」）→ 以显式指定为准，绝不覆盖。
    2. 未显式指定 → 根据标的代码物理属性自动路由：
       - 含美股 ETF 代码 → B 账户（美元计价）
       - 仅含 A 股 6 位数字代码 → A 账户（人民币计价）
       - 两者皆无/混合不清 → None（保持默认 A，交由上层判定）
    """
    if explicit_account:
        return explicit_account

    us = detect_us_tickers(text)
    if us:
        return "B"
    return None


def parse_holdings(text: str) -> list[dict]:
    """
    从 /输入 文本中提取持仓确权条目。
    返回: [{"ticker": "518880", "shares": 7000, "cost": 8.646}, ...]
    """
    results = []

    # 先尝试标准格式
    for m in RE_HOLDING.finditer(text):
        results.append({
            "ticker": m.group("ticker"),
            "shares": parse_shares(m.group("shares")),
            "cost": parse_cost(m.group("cost")),
        })

    # 如果标准格式没命中，尝试宽松格式
    if not results:
        for m in RE_HOLDING_LOOSE.finditer(text):
            results.append({
                "ticker": m.group("ticker"),
                "shares": parse_shares(m.group("shares")),
                "cost": parse_cost(m.group("cost")),
            })

    return results


def parse_operations(text: str) -> list[dict]:
    """
    从 /输入 文本中提取操作指令。
    返回: [{"action": "已清仓", "ticker": "513180", "shares": None, "price": None}, ...]
    """
    results = []
    for m in RE_OPERATION.finditer(text):
        entry = {
            "action": m.group("action"),
            "ticker": m.group("ticker"),
        }
        if m.group("shares"):
            entry["shares"] = parse_shares(m.group("shares"))
            entry["price"] = parse_cost(m.group("price")) if m.group("price") else None
        results.append(entry)
    return results


def load_positions() -> dict:
    """加载当前 positions.json"""
    if os.path.exists(POSITIONS_PATH):
        with open(POSITIONS_PATH, "r") as f:
            data = json.load(f)
        # positions.json 顶层结构为 {"positions": {...}}，统一剥掉外层取 positions
        return data.get("positions", data)
    # 空模板
    return {
        "_meta": {
            "version": "1.0",
            "created": str(date.today()),
            "description": "持仓数据单一真源。",
            "update_rule": "仅守东通过 /输入 指令确权后才可修改此文件。"
        },
        "accounts": {
            "A": {"currency": "CNY", "holdings": {}, "cleared": [], "never_held": [], "cash_approx": 0},
            "B": {"currency": "USD", "holdings": {}, "cleared": [], "never_held": [], "cash_approx": 0}
        },
        "summary": {"total_holdings_count": 0, "A_account_tickers": [], "B_account_tickers": []}
    }


def apply_holdings(data: dict, holdings: list[dict], account: str, replace: bool = False):
    """
    将解析出的持仓确权写入 positions.json 结构。
    replace=True → 该账户旧持仓全部清空（全量替换）
    """
    acc = data["accounts"][account]

    if replace:
        # 全量替换：旧持仓全部移到 cleared（除非是现金等价物）
        old_tickers = list(acc["holdings"].keys())
        for t in old_tickers:
            h = acc["holdings"].pop(t)
            if t not in acc["cleared"]:
                acc["cleared"].append(t)

    for h in holdings:
        ticker = h["ticker"]
        # 从 cleared/never_held 中移除（因为现在持有了）
        if ticker in acc.get("cleared", []):
            acc["cleared"].remove(ticker)
        if ticker in acc.get("never_held", []):
            acc["never_held"].remove(ticker)

        acc["holdings"][ticker] = {
            "shares": h["shares"],
            "cost": h["cost"],
            "confirmed": str(date.today()),
        }

    # 更新 summary
    data["summary"]["A_account_tickers"] = sorted(acc["holdings"].keys())
    data["summary"]["B_account_tickers"] = sorted(data["accounts"]["B"]["holdings"].keys())
    data["summary"]["total_holdings_count"] = (
        len(acc["holdings"]) + len(data["accounts"]["B"]["holdings"])
    )


def apply_operations(data: dict, operations: list[dict], account: str):
    """应用操作指令（清仓/买入/加仓/减仓等）"""
    acc = data["accounts"][account]

    for op in operations:
        ticker = op["ticker"]
        action = op["action"]

        if action in ("已清仓", "已卖出"):
            if ticker in acc["holdings"]:
                del acc["holdings"][ticker]
            if ticker not in acc.get("cleared", []):
                acc.setdefault("cleared", []).append(ticker)

        elif action in ("已买入", "已建仓", "已加仓"):
            if op.get("shares") and op.get("price"):
                if ticker in acc["holdings"]:
                    # 加仓：合并成本
                    old = acc["holdings"][ticker]
                    total_shares = old["shares"] + op["shares"]
                    total_cost = (old["shares"] * old["cost"] + op["shares"] * op["price"]) / total_shares
                    acc["holdings"][ticker] = {
                        "shares": total_shares,
                        "cost": round(total_cost, 4),
                        "confirmed": str(date.today()),
                    }
                else:
                    # 新建仓
                    acc["holdings"][ticker] = {
                        "shares": op["shares"],
                        "cost": op["price"],
                        "confirmed": str(date.today()),
                    }
                # 从 cleared/never_held 中移除
                if ticker in acc.get("cleared", []):
                    acc["cleared"].remove(ticker)
                if ticker in acc.get("never_held", []):
                    acc["never_held"].remove(ticker)

        elif action == "已减仓":
            if ticker in acc["holdings"] and op.get("shares"):
                old = acc["holdings"][ticker]
                new_shares = old["shares"] - op["shares"]
                if new_shares <= 0:
                    del acc["holdings"][ticker]
                    if ticker not in acc.get("cleared", []):
                        acc.setdefault("cleared", []).append(ticker)
                else:
                    acc["holdings"][ticker]["shares"] = new_shares

    # 更新 summary
    data["summary"]["A_account_tickers"] = sorted(
        data["accounts"]["A"]["holdings"].keys()
    )
    data["summary"]["B_account_tickers"] = sorted(
        data["accounts"]["B"]["holdings"].keys()
    )
    data["summary"]["total_holdings_count"] = (
        len(data["accounts"]["A"]["holdings"])
        + len(data["accounts"]["B"]["holdings"])
    )


def update_checksum(data: dict):
    """计算并写入 positions.json 的防篡改校验和"""
    import hashlib
    from datetime import datetime, timezone, timedelta
    
    meta = data.get("_meta", {})
    meta.pop("checksum", None)
    meta.pop("checksum_algo", None)
    meta.pop("checksum_updated", None)
    
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    checksum = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    
    tz = timezone(timedelta(hours=8))
    data["_meta"]["checksum"] = checksum
    data["_meta"]["checksum_algo"] = "sha256_16"
    data["_meta"]["checksum_updated"] = datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    
    return checksum


def save_positions(data: dict):
    """写入 positions.json（自动更新防篡改校验和）"""
    update_checksum(data)
    # 写回时包回 positions 外层，与现有文件结构 {"positions": {...}} 保持一致
    with open(POSITIONS_PATH, "w") as f:
        json.dump({"positions": data}, f, indent=2, ensure_ascii=False)


def format_diff(old_data: dict, new_data: dict, account: str) -> list[str]:
    """生成变更摘要"""
    old_holdings = old_data["accounts"][account]["holdings"]
    new_holdings = new_data["accounts"][account]["holdings"]

    lines = []
    all_tickers = set(old_holdings.keys()) | set(new_holdings.keys())

    for t in sorted(all_tickers):
        old = old_holdings.get(t)
        new = new_holdings.get(t)
        if old and new:
            if old["shares"] != new["shares"] or old["cost"] != new["cost"]:
                lines.append(
                    f"  {t}: {old['shares']}股@{old['cost']} → {new['shares']}股@{new['cost']}"
                )
        elif old and not new:
            lines.append(f"  {t}: {old['shares']}股@{old['cost']} → 🔴已清仓")
        elif new and not old:
            lines.append(f"  {t}: → 🟢新建仓 {new['shares']}股@{new['cost']}")

    return lines


def main():
    args = sys.argv[1:]

    dry_run = "--dry-run" in args or "-n" in args
    replace = "--replace" in args or "-r" in args
    from_file = None
    text_input = None
    account = "A"  # 默认 A 账户
    account_explicit = False  # 是否为守东显式指定账户
    operation_mode = False

    # 解析参数
    i = 0
    while i < len(args):
        if args[i] == "--file" or args[i] == "-f":
            from_file = args[i + 1]
            i += 2
        elif args[i] == "--account" or args[i] == "-a":
            account = args[i + 1].upper()
            account_explicit = True
            i += 2
        elif args[i] == "--operation" or args[i] == "-o":
            operation_mode = True
            text_input = args[i + 1]
            i += 2
        elif args[i] in ("--dry-run", "-n", "--replace", "-r"):
            i += 1
        else:
            text_input = args[i]
            i += 1

    # 从文件读取
    if from_file:
        with open(from_file, "r") as f:
            text_input = f.read().strip()

    if not text_input:
        print("❌ 错误: 未提供 /输入 文本", file=sys.stderr)
        print("用法: python3 input_parser.py \"/输入 持仓确权：...\"", file=sys.stderr)
        sys.exit(1)

    # 尝试从文本中检测账户
    detected_account = detect_account(text_input)
    if detected_account:
        account = detected_account
        account_explicit = True

    # 自动路由：仅当未显式指定账户时，根据标的物理属性路由（美股→B账户）
    auto_routed = route_account(text_input, detected_account)
    if auto_routed and not account_explicit:
        account = auto_routed

    print(f"📋 解析 /输入 指令")
    print(f"   账户: {account}")
    if auto_routed and not account_explicit:
        print(f"       (自动路由: 检测到美股ETF标的 → B账户)")
    print(f"   模式: {'全量替换' if replace else '增量更新'}")
    print(f"   试运行: {'是' if dry_run else '否'}")
    print()

    # ── 解析 ──
    if operation_mode:
        # 纯操作模式：仅解析操作指令，跳过持仓确权
        holdings = []
        operations = parse_operations(text_input)
    else:
        # 混合模式：先分离操作部分
        op_section = RE_OPERATION_SECTION.search(text_input)
        clean_text = text_input
        if op_section:
            # 从文本中移除操作部分，避免被持仓确权正则误匹配
            clean_text = text_input[:op_section.start()] + text_input[op_section.end():]

        holdings = parse_holdings(clean_text)
        operations = parse_operations(text_input)  # 从原始文本解析操作

    if not holdings and not operations:
        print("❌ 未识别到任何持仓确权或操作指令")
        print(f"   输入文本: {text_input[:200]}")
        sys.exit(1)

    # ── 打印解析结果 ──
    if holdings:
        print("📊 持仓确权解析结果:")
        for h in holdings:
            print(f"   {h['ticker']}: {h['shares']:,}股 @ {h['cost']}")
        print()

    if operations:
        print("⚡ 操作指令解析结果:")
        for op in operations:
            detail = f"   {op['action']} {op['ticker']}"
            if op.get("shares"):
                detail += f" {op['shares']:,}股 @ {op.get('price', '?')}"
            print(detail)
        print()

    # ── 应用变更 ──
    old_data = load_positions()
    new_data = json.loads(json.dumps(old_data))  # deep copy

    if holdings:
        apply_holdings(new_data, holdings, account, replace=replace)

    if operations:
        apply_operations(new_data, operations, account)

    # ── 变更摘要 ──
    diff = format_diff(old_data, new_data, account)
    if diff:
        print("🔄 持仓变更:")
        for line in diff:
            print(line)
        print()

    if dry_run:
        print("⚠️ 试运行模式 — 未写入 positions.json")
        print(json.dumps(new_data["accounts"][account], indent=2, ensure_ascii=False))
    else:
        save_positions(new_data)
        print("✅ positions.json 已更新")
        held = len(new_data["accounts"][account]["holdings"])
        cleared = len(new_data["accounts"][account].get("cleared", []))
        print(f"   持仓: {held} 标 | 已清仓: {cleared} 标")


if __name__ == "__main__":
    main()
