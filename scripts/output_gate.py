#!/usr/bin/env python3
"""
联邦投顾 — 输出闸门 V1.0
================================
解决「LLM生成快于校验」的架构性问题：

核心逻辑：
  涉及实时数据/持仓/成本/执行事实的输出前，
  必须先跑此脚本，脚本返回「数据已确权」令牌，
  LLM 看到令牌后才允许输出。

设计原则：
  - 脚本不替代LLM思考——脚本只做数据拉取和事实校验
  - 脚本是「闸门」不是「大脑」——通过=数据新鲜，不通过=禁止输出
  - 与 execution_chain.py 互补——chain管全池扫描时的大流程，gate管单次输出的快速校验

用法：
  python3 output_gate.py --check vix          # VIX实时校验
  python3 output_gate.py --check macro        # 宏观锚点全量校验
  python3 output_gate.py --check position QQQ # 单标持仓校验
  python3 output_gate.py --check cost MUFG    # 单标成本校验
  python3 output_gate.py --check execution    # 执行事实校验（扫MEMORY/决策日志）
  python3 output_gate.py --check backtest     # 回测推断拦截（防LLM编造回测数字）
  python3 output_gate.py --check all          # 全量校验（/扫描 /开火 前）
  python3 output_gate.py --check realtime     # 盘中实时数据强制拉取

输出：
  JSON: { "gate": "PASS"|"BLOCK", "checks": [...], "data": {...}, "token": "..." }
  状态码: 0=通过, 1=拦截
"""

import json
import sys
import os
import re
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.parent
MEMORY_MD = WORKSPACE / "MEMORY.md"
MEMORY_DIR = WORKSPACE / "memory"
POSITIONS_JSON = WORKSPACE / "scripts" / "positions.json"
PARAMS_JSON = WORKSPACE / "scripts" / "params.json"
DECISION_LOG_DIR = WORKSPACE / "knowledge" / "analysis" / "decision-log"
SCRIPTS_DIR = WORKSPACE / "scripts"

# ── 工具函数 ──────────────────────────────────────────────────
def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def is_market_open():
    """判断当前是否在盘中时段"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    weekday = now.weekday()
    
    if weekday >= 5:  # 周六日
        return {"a_stock": False, "us_stock": False}
    
    time_val = hour * 60 + minute
    
    return {
        "a_stock": 9*60+30 <= time_val < 15*60,      # 09:30-15:00
        "us_stock": time_val >= 21*60+30 or time_val < 4*60,  # 21:30-04:00
    }

def fetch_anysearch(query, freshness="day"):
    """通过AnySearch CLI获取实时数据"""
    import subprocess
    cli = str(SCRIPTS_DIR.parent / "skills" / "anysearch" / "scripts" / "anysearch_cli.py")
    try:
        result = subprocess.run(
            ["python3", cli, "search", query, "--freshness", freshness, "--max_results", "3"],
            capture_output=True, text=True, timeout=15
        )
        return result.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"

def read_file(path):
    if isinstance(path, str):
        path = Path(path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")

def read_json(path):
    if isinstance(path, str):
        path = Path(path)
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {}

# ══════════════════════════════════════════════════════════════
# 校验模块
# ══════════════════════════════════════════════════════════════

def check_vix():
    """
    校验 VIX 实时数据
    判定标准：必须通过AnySearch拉取到当日VIX数据，禁止使用缓存
    """
    result = {
        "check": "VIX实时校验",
        "status": "PENDING",
        "value": None,
        "source": None,
        "freshness": None,
        "error": None
    }
    
    # Step 1: AnySearch拉取
    raw = fetch_anysearch("CBOE VIX index real-time value today", "day")
    
    if raw.startswith("ERROR"):
        result["status"] = "BLOCK"
        result["error"] = f"AnySearch不可用: {raw}"
        return result
    
    # Step 2: 从返回中提取VIX数值
    vix_patterns = [
        r'VIX[:\s]*(\d+\.?\d*)',
        r'CBOE Volatility Index[:\s]*(\d+\.?\d*)',
        r'波动率指数[:\s]*(\d+\.?\d*)',
        r'at\s+(\d+\.?\d*)',
    ]
    
    for pattern in vix_patterns:
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            vix_val = float(match.group(1))
            if 5 < vix_val < 100:  # 合理范围
                result["status"] = "PASS"
                result["value"] = vix_val
                result["source"] = "AnySearch CBOE"
                result["freshness"] = today_str()
                return result
    
    # Step 3: 提取失败
    result["status"] = "BLOCK"
    result["error"] = f"无法从AnySearch返回中提取VIX数值（返回长度: {len(raw)}字符）"
    result["raw_sample"] = raw[:300] if raw else "(empty)"
    return result


def check_macro():
    """
    宏观锚点全量校验：VIX + DXY + US10Y + ES/NQ
    每个锚点必须通过API获取，禁止使用缓存/记忆/推断
    """
    results = []
    
    # VIX
    vix = check_vix()
    results.append(vix)
    
    # DXY
    dxy_result = {
        "check": "DXY实时校验",
        "status": "PENDING",
        "value": None,
        "source": None,
        "error": None
    }
    raw = fetch_anysearch("DXY US Dollar Index today", "day")
    if raw and not raw.startswith("ERROR"):
        # 多种正则模式匹配DXY——不同数据源格式各异
        dxy_patterns = [
            r'(?:DXY|Dollar Index)[^0-9]*?(\d{2,3}\.\d{2,3})',  # DXY 101.29
            r'(\d{2,3}\.\d{2,3})\s*-\d\.\d{2}\s*\([^)]*\)\s*Real-time',  # Investing.com
            r'USDIDX[^0-9]*?(\d{2,3}\.\d{2,3})',  # USDIDX
            r'US Dollar Index[^0-9]*?(\d{2,3}\.\d{2,3})',
        ]
        for pattern in dxy_patterns:
            dxy_match = re.search(pattern, raw, re.IGNORECASE)
            if dxy_match:
                dxy_val = float(dxy_match.group(1))
                if 80 < dxy_val < 120:
                    dxy_result["status"] = "PASS"
                    dxy_result["value"] = dxy_val
                    dxy_result["source"] = "AnySearch"
                    break
        if dxy_result["status"] != "PASS":
            dxy_result["status"] = "BLOCK"
            dxy_result["error"] = f"无法提取DXY数值（返回{len(raw)}字符）"
    else:
        dxy_result["status"] = "BLOCK"
        dxy_result["error"] = "AnySearch不可用"
    results.append(dxy_result)
    
    # US10Y
    us10y_result = {
        "check": "US10Y实时校验",
        "status": "PENDING",
        "value": None,
        "source": None,
        "error": None
    }
    raw = fetch_anysearch("US 10-year Treasury yield today", "day")
    if raw and not raw.startswith("ERROR"):
        yld_patterns = [
            r'(\d\.\d{2,3})%',  # 4.25%
            r'(\d\.\d{2,3})\s*%',
            r'US10Y[^0-9]*?(\d\.\d{2,3})',
            r'10[-\s]?[Yy]ear[^0-9]*?(\d\.\d{2,3})',
        ]
        for pattern in yld_patterns:
            yld_match = re.search(pattern, raw)
            if yld_match:
                yld_val = float(yld_match.group(1))
                if 2 < yld_val < 8:
                    us10y_result["status"] = "PASS"
                    us10y_result["value"] = yld_val
                    us10y_result["source"] = "AnySearch"
                    break
        if us10y_result["status"] != "PASS":
            us10y_result["status"] = "BLOCK"
            us10y_result["error"] = f"无法提取US10Y数值（返回{len(raw)}字符）"
    else:
        us10y_result["status"] = "BLOCK"
        us10y_result["error"] = "AnySearch不可用"
    results.append(us10y_result)
    
    # ES/NQ (S&P 500 futures)
    es_result = {
        "check": "ES/NQ实时校验",
        "status": "PENDING",
        "value": None,
        "source": None,
        "error": None
    }
    raw = fetch_anysearch("S&P 500 index SPX level", "day")
    if raw and not raw.startswith("ERROR"):
        es_patterns = [
            r'(\d{4,5}\.\d{1,2})\s*[+-]\d+\.\d{1,2}\s*\(',  # SPX 5,500.00 +50.00 (
            r'S&P 500[^0-9]*?(\d{1,2},\d{3}\.\d{1,2})',  # 5,500.00
            r'SPX[^0-9]*?(\d{4,5}\.\d{1,2})',
            r'(\d{4,5}\.\d{1,2})\s*[+-]\d+\.\d{1,2}%',
        ]
        for pattern in es_patterns:
            es_match = re.search(pattern, raw, re.IGNORECASE)
            if es_match:
                es_val = float(es_match.group(1).replace(",", ""))
                if 3000 < es_val < 10000:
                    es_result["status"] = "PASS"
                    es_result["value"] = es_val
                    es_result["source"] = "AnySearch"
                    break
        if es_result["status"] != "PASS":
            es_result["status"] = "BLOCK"
            es_result["error"] = f"无法提取ES数值（返回{len(raw)}字符）"
    else:
        es_result["status"] = "BLOCK"
        es_result["error"] = "AnySearch不可用"
    results.append(es_result)
    
    return results


def check_position(ticker):
    """
    持仓事实校验（硬锁零.十）
    必须从 positions.json 读取，禁止从记忆/缓存获取
    """
    result = {
        "check": f"持仓校验:{ticker}",
        "status": "PENDING",
        "shares": None,
        "cost": None,
        "account": None,
        "source": None,
        "error": None
    }
    
    # 从 positions.json 读取（唯一真源）
    data = read_json(POSITIONS_JSON)
    if not data:
        result["status"] = "BLOCK"
        result["error"] = "positions.json 不可用或为空"
        return result
    
    for acc in ["A", "B"]:
        h = data.get("accounts", {}).get(acc, {}).get("holdings", {}).get(ticker)
        if h:
            result["status"] = "PASS"
            result["shares"] = h.get("shares")
            result["cost"] = h.get("cost")
            result["account"] = acc
            result["source"] = f"positions.json (确权: {h.get('confirmed', 'unknown')})"
            return result
        
        # 检查已清仓
        if ticker in data.get("accounts", {}).get(acc, {}).get("cleared", []):
            result["status"] = "PASS"
            result["shares"] = 0
            result["cost"] = None
            result["account"] = acc
            result["source"] = "positions.json (已清仓)"
            return result
    
    # 未找到
    result["status"] = "PASS"
    result["shares"] = 0
    result["cost"] = None
    result["account"] = None
    result["source"] = "positions.json (未持有)"
    return result


def check_cost(ticker):
    """
    成本强制校验（规则K.6）
    必须从 MEMORY.md 或 positions.json 追溯到守东确权
    """
    result = {
        "check": f"成本校验:{ticker}",
        "status": "PENDING",
        "cost": None,
        "source": None,
        "confirmed_date": None,
        "error": None
    }
    
    # 优先从 positions.json 读取
    data = read_json(POSITIONS_JSON)
    if data:
        for acc in ["A", "B"]:
            h = data.get("accounts", {}).get(acc, {}).get("holdings", {}).get(ticker)
            if h and h.get("cost"):
                result["status"] = "PASS"
                result["cost"] = h["cost"]
                result["source"] = f"positions.json ({acc}账户)"
                result["confirmed_date"] = h.get("confirmed", "unknown")
                return result
    
    # 降级：从 MEMORY.md 提取
    memory_text = read_file(MEMORY_MD)
    if memory_text:
        pattern = re.compile(
            rf'{ticker}\s+[\d,]+\s*股?\s*[\(（]\s*[¥$]?\s*([\d.]+)\s*[\)）]',
            re.IGNORECASE
        )
        match = pattern.search(memory_text)
        if match:
            result["status"] = "PASS"
            result["cost"] = float(match.group(1))
            result["source"] = "MEMORY.md (需确认确权日期)"
            result["confirmed_date"] = "待确权"
            return result
    
    # 未找到
    result["status"] = "BLOCK"
    result["error"] = f"未找到{ticker}的成本确权记录。禁止输出止损/止盈/浮盈亏计算。"
    return result


def check_execution_facts(target_text=None):
    """
    执行事实校验（硬锁零 + 规则P）
    扫描即将输出的文本，检测是否存在「未经守东确权的执行事实断言」
    
    target_text: 如果提供，校验这段文本；否则返回「需要LLM自行扫描」的提示
    """
    result = {
        "check": "执行事实校验",
        "status": "PENDING",
        "violations": [],
        "error": None
    }
    
    # 敏感词列表——任何包含这些词的断言必须追溯到守东确权
    forbidden_patterns = [
        (r'已清仓|已卖出|已止损|已止盈', '执行确认'),
        (r'已买入|已建仓|已加仓|已补仓', '建仓确认'),
        (r'已执行|已完成|已离场', '操作确认'),
        (r'已减仓|已调仓', '仓位调整确认'),
    ]
    
    if target_text is None:
        result["status"] = "PASS"
        result["note"] = "无目标文本，LLM需在输出前自行扫描以下敏感词：" + \
                         str([p[0] for p in forbidden_patterns])
        return result
    
    for pattern, category in forbidden_patterns:
        matches = re.finditer(pattern, target_text)
        for m in matches:
            # 检查该断言是否有来源标注
            context_start = max(0, m.start() - 50)
            context_end = min(len(target_text), m.end() + 50)
            context = target_text[context_start:context_end]
            
            # 检查是否标注了来源
            has_source = any(marker in context for marker in [
                "守东确认", "守东确权", "守东说", "来源:", "决策日志",
                "信号触发，待执行", "⚠️信号触发", "⚠️持仓状态待确权"
            ])
            
            if not has_source:
                result["violations"].append({
                    "match": m.group(),
                    "position": m.start(),
                    "category": category,
                    "context": context.strip(),
                    "issue": "执行事实断言未标注守东确权来源"
                })
    
    if result["violations"]:
        result["status"] = "BLOCK"
    else:
        result["status"] = "PASS"
    
    return result


def check_realtime_data(tickers=None):
    """
    盘中实时数据强制拉取（规则M.4）
    拉取腾讯实时API，确认现价是最新的而非Tushare T+1
    """
    market_status = is_market_open()
    
    result = {
        "check": "盘中实时数据校验",
        "status": "PENDING",
        "market_status": market_status,
        "data_fresh": False,
        "source": None,
        "error": None
    }
    
    # 如果不在任何盘中时段，实时数据非强制
    if not market_status["a_stock"] and not market_status["us_stock"]:
        result["status"] = "PASS"
        result["note"] = "当前非盘中时段，腾讯实时API非强制。可用Tushare/T+0收盘。"
        return result
    
    # 盘中时段——必须拉取腾讯实时API
    import subprocess
    qt_script = str(SCRIPTS_DIR / "qt_realtime.py")
    if not Path(qt_script).exists():
        # 尝试 market_data.py
        qt_script = str(SCRIPTS_DIR / "market_data.py")
    
    try:
        if tickers:
            ticker_arg = tickers[0]
            proc = subprocess.run(
                ["python3", qt_script, "--ticker", ticker_arg],
                capture_output=True, text=True, timeout=15
            )
        else:
            proc = subprocess.run(
                ["python3", qt_script],
                capture_output=True, text=True, timeout=15
            )
        
        if proc.returncode == 0 and proc.stdout.strip():
            result["status"] = "PASS"
            result["data_fresh"] = True
            result["source"] = f"腾讯实时API ({now_iso()})"
            result["raw_length"] = len(proc.stdout)
        else:
            result["status"] = "BLOCK"
            result["error"] = f"腾讯API返回异常: returncode={proc.returncode}"
    except Exception as e:
        result["status"] = "BLOCK"
        result["error"] = f"腾讯API不可用: {e}"
    
    return result


def check_backtest_inference(target_text=None):
    """
    回测推断拦截（模块十七 人格级）
    检测输出中是否包含回测类数字但无对应的脚本调用记录
    
    触发条件：输出中出现累计收益/止损笔数/胜率/平均盈亏/最大回撤/Buy&Hold对比
    等回测特征数字，但没有对应的脚本调用痕迹。
    
    排除：stop_loss_reentry 等脚本自身的输出回显。
    """
    result = {
        "check": "回测推断拦截",
        "status": "PENDING",
        "violations": [],
        "error": None
    }
    
    if target_text is None:
        result["status"] = "PASS"
        result["note"] = "无目标文本"
        return result
    
    # 回测类数字模式
    backtest_patterns = [
        (r'累计[收益损益]*\s*[:：]?\s*[＋+\-−]\s*\d+\.?\d*\s*%', '累计收益'),
        (r'累计\s*[＋+\-−]\s*\d+\.?\d*\s*%', '累计百分比'),
        (r'止损笔?数\s*[:：]?\s*\d+\s*笔', '止损笔数'),
        (r'止损交易\s*\(?\s*\d+\s*笔', '止损交易笔数'),
        (r'\d+\s*笔\s*止损', '止损笔数(后置)'),
        (r'胜率\s*[:：]?\s*\d+\.?\d*\s*%', '胜率'),
        (r'止损均[亏赔]\s*[:：]?\s*[＋+\-−]\s*\d+\.?\d*\s*%', '止损均亏'),
        (r'最差\s*[:：]?\s*[＋+\-−]\s*\d+\.?\d*\s*%', '最差止损'),
        (r'Buy\s*&\s*Hold\s*[:：]?\s*[＋+\-−]\s*\d+\.?\d*\s*%', 'Buy&Hold对比'),
        (r'空仓天数\s*[:：]?\s*~?\s*\d+\s*天', '空仓天数'),
        (r'回测[^，。,\n]*?[＋+\-−]\s*\d+\.?\d*\s*%', '回测结论'),
    ]
    
    # ── 简化逻辑：检测是否有脚本调用的证据 ──
    # 如果有脚本输出特征 → 这是真实回测结果，PASS
    # 如果没有 → 这是LLM推断，BLOCK
    
    script_evidence = [
        r'📌\s*累计损益',           # stop_loss_reentry.py 格式化输出
        r'📊\s*止损交易',            # 同上
        r'止损→空仓→买入区间',       # 脚本特有的逻辑描述
        r'stop_loss_reentry',        # 脚本文件名
        r'python3\s+scripts/',       # 命令调用
        r'={50,}',                   # 长分隔线（脚本输出）
    ]
    
    has_script_evidence = any(re.search(p, target_text, re.IGNORECASE) for p in script_evidence)
    
    if has_script_evidence:
        # 有脚本证据 → 这是真实回测输出 → 通过
        result["status"] = "PASS"
        result["note"] = "检测到脚本输出特征，视为真实回测结果"
        return result
    
    # 无脚本证据 → 这是LLM文本 → 检测回测特征数字
    for pattern, category in backtest_patterns:
        matches = re.finditer(pattern, target_text, re.IGNORECASE)
        for m in matches:
            context_start = max(0, m.start() - 80)
            context_end = min(len(target_text), m.end() + 80)
            context = target_text[context_start:context_end]
            
            result["violations"].append({
                "match": m.group(),
                "position": m.start(),
                "category": category,
                "context": context.strip()[:120],
                "issue": "回测数据无脚本调用记录——可能是LLM推断而非真实回测"
            })
    
    if result["violations"]:
        result["status"] = "BLOCK"
    else:
        result["status"] = "PASS"
    
    return result


def check_memory_contamination():
    """
    记忆污染自检（硬锁零.七）
    检查 MEMORY.md 持仓确权段 vs positions.json 是否一致
    """
    result = {
        "check": "记忆污染自检",
        "status": "PENDING",
        "inconsistencies": [],
        "error": None
    }
    
    # 读取两个源
    memory_text = read_file(MEMORY_MD)
    positions_data = read_json(POSITIONS_JSON)
    
    if not positions_data:
        result["status"] = "BLOCK"
        result["error"] = "positions.json 不可用"
        return result
    
    if not memory_text:
        result["status"] = "PASS"
        result["note"] = "MEMORY.md 不可用，以 positions.json 为准"
        return result
    
    # 从 positions.json 提取所有持仓
    json_holdings = {}
    for acc in ["A", "B"]:
        for ticker, h in positions_data.get("accounts", {}).get(acc, {}).get("holdings", {}).items():
            json_holdings[ticker] = {"shares": h.get("shares"), "account": acc}
    
    # 从 MEMORY.md 提取持仓（简单模式匹配）
    # A账户
    a_pattern = re.findall(
        r'(\d{6}\.?\w*)\s+([\d,]+)股\s*\([¥$]([\d.]+)\)',
        memory_text
    )
    for ticker_raw, shares_str, cost in a_pattern:
        ticker = ticker_raw.replace(".SH", "").replace(".SZ", "")
        shares = int(shares_str.replace(",", ""))
        if ticker in json_holdings:
            if json_holdings[ticker]["shares"] != shares:
                result["inconsistencies"].append({
                    "ticker": ticker,
                    "memory_shares": shares,
                    "json_shares": json_holdings[ticker]["shares"],
                    "resolution": "以 positions.json 为准"
                })
    
    if result["inconsistencies"]:
        result["status"] = "BLOCK"
    else:
        result["status"] = "PASS"
    
    return result


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def main():
    args = sys.argv[1:]
    
    if not args:
        print(json.dumps({
            "gate": "ERROR",
            "error": "缺少 --check 参数。用法: output_gate.py --check <vix|macro|position|cost|execution|realtime|all>",
            "timestamp": now_iso()
        }, indent=2, ensure_ascii=False))
        sys.exit(1)
    
    if "--check" not in args:
        print(json.dumps({"gate": "ERROR", "error": "需要 --check 参数"}, indent=2, ensure_ascii=False))
        sys.exit(1)
    
    idx = args.index("--check")
    check_type = args[idx + 1] if idx + 1 < len(args) else "all"
    
    results = []
    all_pass = True
    
    # ── 分发 ──
    if check_type in ("vix", "all"):
        vix = check_vix()
        results.append(vix)
        if vix["status"] == "BLOCK":
            all_pass = False
    
    if check_type in ("macro", "all"):
        macros = check_macro()
        results.extend(macros)
        for m in macros:
            if m["status"] == "BLOCK":
                all_pass = False
    
    if check_type in ("position", "all"):
        ticker_arg = args[idx + 2] if idx + 2 < len(args) and not args[idx + 2].startswith("--") else None
        if ticker_arg:
            pos = check_position(ticker_arg)
            results.append(pos)
            if pos["status"] == "BLOCK":
                all_pass = False
        elif check_type != "all":
            print(json.dumps({"gate": "ERROR", "error": "position校验需要标的代码: --check position QQQ"}, indent=2, ensure_ascii=False))
            sys.exit(1)
    
    if check_type in ("cost", "all"):
        ticker_arg = args[idx + 2] if idx + 2 < len(args) and not args[idx + 2].startswith("--") else None
        if ticker_arg:
            cost = check_cost(ticker_arg)
            results.append(cost)
            if cost["status"] == "BLOCK":
                all_pass = False
        elif check_type != "all":
            print(json.dumps({"gate": "ERROR", "error": "cost校验需要标的代码: --check cost MUFG"}, indent=2, ensure_ascii=False))
            sys.exit(1)
    
    if check_type in ("execution", "all"):
        # 如果有额外参数作为待校验文本
        text_arg = " ".join(args[idx + 2:]) if idx + 2 < len(args) else None
        exec_result = check_execution_facts(text_arg if text_arg and text_arg != "all" else None)
        results.append(exec_result)
        if exec_result["status"] == "BLOCK":
            all_pass = False
    
    if check_type in ("realtime", "all"):
        ticker_arg = args[idx + 2] if idx + 2 < len(args) and not args[idx + 2].startswith("--") else None
        tickers = [ticker_arg] if ticker_arg and ticker_arg != "all" else None
        rt = check_realtime_data(tickers)
        results.append(rt)
        if rt["status"] == "BLOCK":
            all_pass = False
    
    if check_type in ("backtest", "all"):
        # 回测推断拦截 + 记忆污染自检
        bt = check_backtest_inference()
        results.append(bt)
        if bt["status"] == "BLOCK":
            all_pass = False
    
    if check_type == "all":
        # 记忆污染自检
        mc = check_memory_contamination()
        results.append(mc)
        if mc["status"] == "BLOCK":
            all_pass = False
    
    # ── 生成令牌 ──
    token = f"GATE-{now_iso().replace(' ', '-').replace(':', '')}-{'PASS' if all_pass else 'BLOCK'}"
    
    output = {
        "gate": "PASS" if all_pass else "BLOCK",
        "token": token,
        "timestamp": now_iso(),
        "check_type": check_type,
        "checks": results,
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r["status"] == "PASS"),
            "blocked": sum(1 for r in results if r["status"] == "BLOCK"),
            "all_pass": all_pass
        }
    }
    
    print(json.dumps(output, indent=2, ensure_ascii=False))
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
