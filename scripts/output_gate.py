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
  python3 output_gate.py --check fire-invoked # 🔴 脚本强制调用自证（/开火前，防跳脚本凭记忆输出）
  python3 output_gate.py --check routing /tmp/llm.json  # 路由/持仓文本一致性校验
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
import time
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
GATE_RULES_YAML = SCRIPTS_DIR / "gate_rules.yaml"

# ── 加载 gate 配置 ────────────────────────────────────────────
def _load_gate_rules():
    """加载 gate_rules.yaml，解析为 dict。无 YAML 依赖，手写简单解析器。"""
    rules = {}
    if not GATE_RULES_YAML.exists():
        return rules
    
    current_section = None
    current_key = None
    current_list = None
    
    with open(GATE_RULES_YAML) as f:
        for line in f:
            stripped = line.rstrip()
            if not stripped or stripped.startswith("#"):
                continue
            
            # 顶级 section
            if not stripped.startswith(" "):
                current_section = stripped.rstrip(":")
                rules[current_section] = {}
                current_key = None
                current_list = None
                continue
            
            # 缩进 2 空格 = section 下的 key
            if stripped.startswith("  ") and not stripped.startswith("    "):
                inner = stripped.strip()
                if inner.endswith(":"):
                    # 嵌套 key
                    current_key = inner.rstrip(":")
                    rules[current_section][current_key] = {}
                    current_list = None
                else:
                    # key: value
                    parts = inner.split(":", 1)
                    if len(parts) == 2:
                        key, val = parts
                        key = key.strip()
                        val = val.strip()
                        # 尝试类型转换
                        if val.replace(".", "").isdigit():
                            val = float(val) if "." in val else int(val)
                        elif val in ("true", "false"):
                            val = val == "true"
                        rules[current_section][key] = val
                continue
            
            # 缩进 4 空格 = 嵌套 key 下的 list item
            if stripped.startswith("    - "):
                item = stripped.strip()[2:]  # 去掉 "  - "
                if current_key and isinstance(rules[current_section].get(current_key), dict):
                    rules[current_section][current_key].setdefault("items", []).append(item)
                elif current_list is not None:
                    rules[current_section][current_list].append(item)
    
    return rules


# 加载配置（模块级）
GATE_RULES = _load_gate_rules()

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


def check_positions_integrity():
    """
    positions.json 防篡改完整性校验（硬锁零.九 代码化）
    
    检测 LLM 是否用 write/edit 工具绕过了 input_parser.py 的 /输入 闸门，
    直接修改了 positions.json。
    
    原理：positions.json 的 _meta.checksum 是上次通过 input_parser.py
    合法写入时计算的 SHA256。如果 LLM 用 write/edit 直接改了文件内容，
    checksum 会对不上。
    """
    result = {
        "check": "positions.json防篡改校验",
        "status": "PENDING",
        "stored_checksum": None,
        "computed_checksum": None,
        "tampered": False,
        "error": None
    }
    
    import hashlib
    
    if not POSITIONS_JSON.exists():
        result["status"] = "BLOCK"
        result["error"] = "positions.json 不存在"
        return result
    
    try:
        with open(POSITIONS_JSON) as f:
            raw = f.read()
        data = json.loads(raw)
    except Exception as e:
        result["status"] = "BLOCK"
        result["error"] = f"positions.json 解析失败: {e}"
        return result
    
    stored_checksum = data.get("_meta", {}).get("checksum")
    result["stored_checksum"] = stored_checksum
    
    if not stored_checksum:
        # 没有校验和——可能是旧版本文件，仅警告不阻断
        result["status"] = "PASS"
        result["note"] = "positions.json 无校验和（旧版本文件），无法验证完整性。建议通过 /输入 重新确权以添加校验和。"
        return result
    
    # 计算当前内容的校验和（排除 _meta.checksum 自身）
    meta = data.get("_meta", {})
    meta.pop("checksum", None)
    meta.pop("checksum_algo", None)
    meta.pop("checksum_updated", None)
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    computed = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    result["computed_checksum"] = computed
    
    if stored_checksum != computed:
        result["status"] = "BLOCK"
        result["tampered"] = True
        result["error"] = (
            f"🔴 positions.json 校验和不匹配！\n"
            f"   存储校验和: {stored_checksum}\n"
            f"   计算校验和: {computed}\n"
            f"   这意味着文件被 write/edit 工具直接修改，绕过了 /输入 闸门。\n"
            f"   唯一合法修改路径: python3 scripts/input_parser.py \"/输入 ...\"\n"
            f"   操作: ① 回滚到最近 git 版本 ② 守东通过 /输入 重新确权"
        )
    else:
        result["status"] = "PASS"
    
    return result


def check_memory_contamination():
    """
    记忆污染自检（硬锁零.七 + 防篡改）
    1. 检查 positions.json 完整性（防LLM绕过/输入闸门）
    2. 检查 MEMORY.md 持仓确权段 vs positions.json 是否一致
    """
    result = {
        "check": "记忆污染自检",
        "status": "PENDING",
        "integrity": None,
        "inconsistencies": [],
        "error": None
    }
    
    # ── 第一道：positions.json 完整性校验 ──
    integrity = check_positions_integrity()
    result["integrity"] = integrity
    if integrity["status"] == "BLOCK":
        result["status"] = "BLOCK"
        result["error"] = integrity["error"]
        return result
    
    # ── 第二道：MEMORY.md vs positions.json 对账 ──
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
            if not isinstance(h, dict):
                continue
            json_holdings[ticker] = {"shares": h.get("shares"), "account": acc}
    
    # 从 MEMORY.md 提取持仓
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


def check_routing_consistency(json_path):
    """
    文本字段校验：LLM输出中的路由标注 vs JSON数据源
    覆盖：路由判定（🟢进攻 / 🟡反击 / ⚪闲置 等）、持仓状态、操作建议
    
    输入格式同 check_consistency。
    校验规则：
    - 从 data_source JSON 中提取每个标的的路由/持仓/动作
    - 在 llm_text 中搜索对应标的，检查路由标注是否一致
    - 发现不一致 → BLOCK
    """
    result = {
        "check": "路由文本一致性校验",
        "status": "PENDING",
        "mismatches": [],
        "summary": ""
    }
    
    try:
        if json_path == "-":
            data = json.load(sys.stdin)
        else:
            data = read_json(json_path)
        
        llm_text = data.get("llm_text", "")
        data_source = data.get("data_source", {})
        
        if not llm_text:
            result["status"] = "PASS"
            result["summary"] = "无LLM文本待校验"
            return result
        
        if not data_source:
            result["status"] = "BLOCK"
            result["summary"] = "缺少 data_source 字段"
            return result
        
        mismatches = []
        
        # 路由标注映射
        ROUTE_PATTERNS = {
            "offense": ["🟢进攻", "进攻"],
            "cn_offense": ["🟢A股进攻", "A股进攻"],
            "counterpunch": ["🟡反击", "反击"],
            "idle": ["⚪闲置", "闲置"],
            "independent": ["⚪独立", "独立动量"],
            "shield": ["⚪金盾", "金盾豁免"],
            "fixed": ["⚪固定层", "固定层"],
            "deprived": ["⛔剥夺", "禁购"],
            "unclassified": ["⚪待分类", "待分类"],
            "cane": ["⚪独立", "厄尔尼诺"],
        }
        
        # 持仓状态映射
        POSITION_PATTERNS = {
            "holding": ["持有", "持仓"],
            "cleared": ["已清仓", "无持仓"],
            "never_held": ["从未持有", "无持仓"],
        }
        
        for ticker, d in data_source.items():
            if not isinstance(d, dict):
                continue
            
            # 检查路由标注
            route = d.get("route")
            if route and route in ROUTE_PATTERNS:
                # 在 LLM 文本中搜索该标的附近的路由标注
                ticker_pattern = re.escape(ticker)
                ticker_matches = list(re.finditer(ticker_pattern, llm_text))
                
                for match in ticker_matches:
                    # 取该标的出现位置附近 200 字符
                    start = max(0, match.start() - 50)
                    end = min(len(llm_text), match.end() + 150)
                    context = llm_text[start:end]
                    
                    expected_patterns = ROUTE_PATTERNS[route]
                    found_route = any(p in context for p in expected_patterns)
                    
                    if not found_route:
                        # 检查是否出现了错误的路由标注
                        all_route_labels = []
                        for r, patterns in ROUTE_PATTERNS.items():
                            for p in patterns:
                                if p in context:
                                    all_route_labels.append((r, p))
                        
                        if all_route_labels:
                            # LLM 标注了路由但与 JSON 不一致
                            mismatches.append({
                                "type": "route",
                                "ticker": ticker,
                                "expected": route,
                                "found": all_route_labels[0][0],
                                "context": context[:100] + "..."
                            })
            
            # 检查持仓状态
            position = d.get("position")
            if position and position in POSITION_PATTERNS:
                ticker_pattern = re.escape(ticker)
                ticker_matches = list(re.finditer(ticker_pattern, llm_text))
                
                for match in ticker_matches:
                    start = max(0, match.start() - 50)
                    end = min(len(llm_text), match.end() + 150)
                    context = llm_text[start:end]
                    
                    expected_patterns = POSITION_PATTERNS[position]
                    found_pos = any(p in context for p in expected_patterns)
                    
                    if not found_pos:
                        # 检查是否出现了错误的持仓标注
                        for pos, patterns in POSITION_PATTERNS.items():
                            if pos == position:
                                continue
                            for p in patterns:
                                if p in context:
                                    mismatches.append({
                                        "type": "position",
                                        "ticker": ticker,
                                        "expected": position,
                                        "found": pos,
                                        "context": context[:100] + "..."
                                    })
        
        if mismatches:
            result["status"] = "BLOCK"
            result["mismatches"] = mismatches[:20]
            result["summary"] = f"发现 {len(mismatches)} 处路由/持仓标注不一致"
        else:
            result["status"] = "PASS"
            result["summary"] = "所有路由和持仓标注与数据源一致"
    
    except Exception as e:
        result["status"] = "ERROR"
        result["summary"] = str(e)
    
    return result


def check_consistency(json_path):
    """
    数字一致性校验：LLM输出中的数字 vs JSON数据源
    
    输入: JSON文件路径，格式要求:
    {
        "llm_text": "LLM即将输出的文本",
        "data_source": "scan_data.json 或 fire_data.json 或 market_data.json"
    }
    或者直接用管道传入: echo '{"llm_text":"...", "data_source":"..."}' | python3 output_gate.py --check consistency -
    
    校验规则:
    - 从 data_source JSON 中提取所有数值字段
    - 在 llm_text 中搜索这些数值
    - 发现不一致 → BLOCK
    """
    result = {
        "check": "数字一致性校验",
        "status": "PENDING",
        "mismatches": [],
        "summary": ""
    }
    
    try:
        if json_path == "-":
            data = json.load(sys.stdin)
        else:
            data = read_json(json_path)
        
        llm_text = data.get("llm_text", "")
        data_source = data.get("data_source", {})
        
        if not llm_text:
            result["status"] = "PASS"
            result["summary"] = "无LLM文本待校验"
            return result
        
        if not data_source:
            result["status"] = "BLOCK"
            result["summary"] = "缺少 data_source 字段"
            return result
        
        # 从 data_source 中提取关键数值字段
        key_numeric_fields = [
            "price", "close", "open", "high", "low", "cost", "shares",
            "ma5", "ma20", "ma40", "ma60", "ma120", "ma250",
            "atr14", "rsi14", "adx14", "dev_ma60", "dev_ma40",
            "change_pct", "vol_ratio", "atr_pct",
            "c4", "buy_zone", "stop_loss", "take_profit",
            "gap_pct", "pnl_pct", "drawdown_20d",
        ]
        
        mismatches = []
        
        # 遍历 data_source 中的标的
        for ticker, d in data_source.items():
            if not isinstance(d, dict):
                continue
            
            for field in key_numeric_fields:
                val = d.get(field)
                if val is None:
                    continue
                
                # 格式化数值为显示字符串（与LLM输出中的常见格式匹配）
                if isinstance(val, float):
                    # 价格类: 保留2-3位小数
                    if field in ("price", "close", "open", "high", "low", "cost", "c4", "buy_zone", "stop_loss", "take_profit"):
                        formats = [f"{val:.2f}", f"{val:.3f}", f"${val:.2f}", f"¥{val:.2f}",
                                   f"${val:.3f}", f"¥{val:.3f}"]
                    elif field in ("shares",):
                        formats = [str(int(val)), f"{int(val):,}"]
                    elif field in ("change_pct", "dev_ma60", "dev_ma40", "pnl_pct", "gap_pct", "drawdown_20d", "atr_pct"):
                        formats = [f"{val:.1f}%", f"{val:.2f}%", f"{val:+.1f}%", f"{val:+.2f}%"]
                    else:
                        formats = [f"{val:.2f}", f"{val:.3f}", f"{val:.4f}"]
                elif isinstance(val, int):
                    formats = [str(val), f"{val:,}"]
                else:
                    continue
                
                # 特殊处理：股数可能以逗号分隔
                if field == "shares":
                    formats.append(f"{val:,}")
                
                # 检查是否有任何格式在LLM文本中出现
                found = any(fmt in llm_text for fmt in formats)
                
                if not found:
                    # 不是所有字段都必须出现——只在数值被引用了但值不对时才报
                    # 这里记录的是一致性检查中「数据源有但LLM文本中没有」的情况
                    # 如果LLM文本中出现了同类数字（如价格附近有不同数字），则标记
                    pass
                
                # 反向检查：在LLM文本中搜索同标的同字段可能被篡改的数字
                # 核心逻辑：如果LLM提到了这个标的，检查附近的价格/数量是否与JSON一致
        
        # 简化版：提取LLM中所有数值，与JSON中的关键数值对撞
        # 提取LLM中的货币数值
        money_pattern = re.findall(r'[¥$](\d{1,3}(?:,\d{3})*(?:\.\d+)?)', llm_text)
        pct_pattern = re.findall(r'([+-]?\d+\.?\d*)%', llm_text)
        share_pattern = re.findall(r'(\d{1,3}(?:,\d{3})*)\s*(?:股|shares)', llm_text)
        
        # 从JSON中收集所有"真值"
        truth_values = set()
        truth_pcts = set()
        truth_shares = set()
        
        for ticker, d in data_source.items():
            if not isinstance(d, dict):
                continue
            # 价格
            for f in ("price", "close", "cost", "c4", "buy_zone", "stop_loss", "take_profit"):
                v = d.get(f)
                if v and isinstance(v, (int, float)):
                    truth_values.add(round(v, 3))
            # 百分比
            for f in ("change_pct", "dev_ma60", "dev_ma40", "pnl_pct", "gap_pct", "drawdown_20d"):
                v = d.get(f)
                if v and isinstance(v, (int, float)):
                    truth_pcts.add(round(v, 2))
            # 股数
            v = d.get("shares")
            if v and isinstance(v, (int, float)):
                truth_shares.add(int(v))
        
        # 对撞
        tolerance = GATE_RULES.get("consistency", {}).get("tolerance_pct", 0.5) / 100
        for m in money_pattern:
            try:
                val = float(m.replace(",", ""))
                val_rounded = round(val, 3)
                # 检查是否接近任何真值（容差0.5%）
                near_truth = any(abs(val_rounded - t) / max(t, 0.01) < tolerance for t in truth_values if t > 0)
                if not near_truth and truth_values:
                    mismatches.append({
                        "type": "price",
                        "llm_value": val,
                        "nearest_truth": min(truth_values, key=lambda t: abs(val_rounded - t)),
                        "diff": round(val_rounded - min(truth_values, key=lambda t: abs(val_rounded - t)), 3)
                    })
            except:
                pass
        
        for m in share_pattern:
            try:
                val = int(m.replace(",", ""))
                if val not in truth_shares and truth_shares:
                    mismatches.append({
                        "type": "shares",
                        "llm_value": val,
                        "nearest_truth": min(truth_shares, key=lambda t: abs(val - t)),
                        "diff": val - min(truth_shares, key=lambda t: abs(val - t))
                    })
            except:
                pass
        
        if mismatches:
            result["status"] = "BLOCK"
            result["mismatches"] = mismatches[:20]  # 截断
            result["summary"] = f"发现 {len(mismatches)} 处数字不一致"
        else:
            result["status"] = "PASS"
            result["summary"] = "所有数值与数据源一致"
    
    except Exception as e:
        result["status"] = "ERROR"
        result["summary"] = str(e)
    
    return result


# ══════════════════════════════════════════════════════════════
# 🔴 fire-invoked 校验 — 脚本强制调用自证（2026-08-13 焊入）
# 根因：/开火 已代码化，但 LLM 可跳过脚本凭记忆硬编报告（518880 现价 ¥8.502 事故）。
#       代码化 = 能力存在；本校验 = 能力必须被真实调用。
# 逻辑：market_data.py 每次 fetch_all() 会落盘 .cache/market_data.json（含时间戳+pid）。
#       本校验读取该缓存，判定「脚本在本次会话内是否真实运行过且数据新鲜」。
#       返回调用指纹（invoked_at + epoch + pid），LLM 输出 /开火 报告时必须在开头引用。
# ══════════════════════════════════════════════════════════════
def check_fire_invoked(max_age_seconds=None):
    """
    校验「脚本是否真实运行过」——不校验数字对不对，只校验脚本跑没跑。

    判定标准：
    ├── 缓存文件不存在 → BLOCK（从未调用脚本，禁止输出 /开火 报告）
    ├── 缓存时间戳距今超过 max_age_seconds → BLOCK（数据过期，需重拉）
    └── 缓存新鲜 → PASS，返回调用指纹

    调用指纹格式（LLM 必须在报告开头逐字引用）：
    「🔒 脚本调用自证: market_data.py invoked_at=YYYY-MM-DD HH:MM:SS epoch=XXXXXXXXXX pid=NNNN」
    """
    age_limit = max_age_seconds or int(GATE_RULES.get("fire_invoked", {}).get("max_age_seconds", 1800))

    result = {
        "check": "脚本强制调用自证(fire-invoked)",
        "status": "PENDING",
        "fingerprint": None,
        "cache_age_seconds": None,
        "summary": ""
    }

    cache_path = SCRIPTS_DIR / ".cache" / "market_data.json"

    try:
        if not cache_path.exists():
            result["status"] = "BLOCK"
            result["summary"] = (
                "未检测到 market_data.py 运行痕迹（.cache/market_data.json 不存在）。"
                "禁止凭记忆输出 /开火 报告——先执行 python3 scripts/fire_report.py --json 或 market_data.py。"
            )
            return result

        payload = read_json(cache_path)
        invoked_at = payload.get("_invoked_at", "")
        invoked_epoch = payload.get("_invoked_epoch")
        pid = payload.get("_pid")

        if not invoked_epoch:
            result["status"] = "BLOCK"
            result["summary"] = "缓存文件存在但缺少 _invoked_epoch 字段，缓存损坏，需重拉脚本。"
            return result

        age = time.time() - float(invoked_epoch)
        result["cache_age_seconds"] = round(age, 1)

        if age > age_limit:
            result["status"] = "BLOCK"
            result["summary"] = (
                f"market_data.py 上次运行于 {invoked_at}（{round(age)} 秒前），"
                f"超过新鲜度上限 {age_limit} 秒。禁止复用旧数据，需重拉脚本。"
            )
            return result

        fingerprint = f"invoked_at={invoked_at} epoch={int(invoked_epoch)} pid={pid}"
        result["status"] = "PASS"
        result["fingerprint"] = fingerprint
        result["summary"] = (
            f"market_data.py 已真实运行（{invoked_at}，{round(age)} 秒前），"
            f"调用指纹: {fingerprint}。报告开头必须引用此指纹。"
        )

    except Exception as e:
        result["status"] = "ERROR"
        result["summary"] = str(e)

    return result


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def main():
    args = sys.argv[1:]
    
    if not args:
        print(json.dumps({
            "gate": "ERROR",
            "error": "缺少 --check 参数。用法: output_gate.py --check <vix|macro|position|cost|execution|realtime|consistency|routing|backtest|fire-invoked|all>",
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
    
    if check_type in ("consistency", "all"):
        # 数字一致性校验：LLM输出中的数字 vs JSON数据源
        json_arg = args[idx + 2] if idx + 2 < len(args) and not args[idx + 2].startswith("--") else None
        if json_arg:
            cons = check_consistency(json_arg)
            results.append(cons)
            if cons["status"] == "BLOCK":
                all_pass = False
        elif check_type != "all":
            print(json.dumps({"gate": "ERROR", "error": "consistency校验需要JSON文件路径: --check consistency /tmp/llm_output.json"}, indent=2, ensure_ascii=False))
            sys.exit(1)
    
    if check_type in ("routing", "all"):
        # 路由/持仓文本一致性校验
        json_arg = args[idx + 2] if idx + 2 < len(args) and not args[idx + 2].startswith("--") else None
        if json_arg:
            rout = check_routing_consistency(json_arg)
            results.append(rout)
            if rout["status"] == "BLOCK":
                all_pass = False
    
    if check_type in ("backtest", "all"):
        # 回测推断拦截 + 记忆污染自检
        bt = check_backtest_inference()
        results.append(bt)
        if bt["status"] == "BLOCK":
            all_pass = False

    if check_type in ("fire-invoked", "all"):
        # 🔴 脚本强制调用自证：/开火 等指令输出前，校验 market_data.py 是否真实运行过
        fi = check_fire_invoked()
        results.append(fi)
        if fi["status"] == "BLOCK":
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
