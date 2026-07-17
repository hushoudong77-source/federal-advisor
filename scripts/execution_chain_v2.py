#!/usr/bin/env python3
"""
执行链强制锁 — 第二批 LLM辅助裁决脚本 V2.0
=============================================
第一批（零风险纯数据，已在 execution_chain.py）：
  Step 0:   白名单校验
  Step 1.0: Tushare四接口探测
  Step 1.1: 规则G拉齐
  Step 2:   规则I对账
  Step 4:   规则M.1新鲜度
  Step 5:   规则J零请提供

第二批（LLM辅助裁决，新增于本脚本）：
  Step 0.5: 规则O — 持仓事实强制校验
  Step 3:   规则K — P0/P1覆写检查
  Step 3.5: 规则K.6 — 持仓成本强制来源校验
  Step 6.5: 敏感词事实断言扫描

设计原则：
- 脚本做「数据准备 + 规则检查 + 交叉比对」，输出结构化 JSON
- LLM 读取 JSON，对脚本无法自动裁决的部分做最终判定
- 脚本不做「最终裁决」——那是 LLM 的活
- 但脚本把「明显的事实矛盾」标记为 🔴，LLM 必须处理

输出：
  JSON 结构 → LLM 读取后：
    ① 确认或修正脚本标记的 🔴 项
    ② 对 🟡 待确权项做最终裁决
    ③ 生成 Step 0.5/3/3.5/6.5 的最终判定
"""

import json
import sys
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.parent
MEMORY_MD = WORKSPACE / "MEMORY.md"
MEMORY_DIR = WORKSPACE / "memory"
PARAMS_JSON = WORKSPACE / "scripts" / "params.json"
DECISION_LOG_DIR = WORKSPACE / "knowledge" / "analysis" / "decision-log"

# ── 工具函数 ──────────────────────────────────────────────────
def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def today_file():
    return MEMORY_DIR / f"{today_str()}.md"

def make_result(step, status, **kwargs):
    return {"step": step, "status": status, "timestamp": now_iso(), **kwargs}

def read_file(path):
    """读取文件，不存在返回空字符串"""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")

def load_params():
    """加载 params.json"""
    try:
        with open(PARAMS_JSON) as f:
            return json.load(f)
    except:
        return {}

# ══════════════════════════════════════════════════════════════
# Step 0.5: 规则O — 持仓事实强制校验
# ══════════════════════════════════════════════════════════════

def parse_memory_positions(memory_text):
    """
    从 MEMORY.md 文本中提取「持仓确权」段的所有持仓。
    返回: {ticker: {"shares": int, "cost": float, "source_line": str}, ...}
    """
    positions = {}

    # 模式1: 「A账户持仓确权（日期）」段
    # 例: 518880 7,000股(¥8.646) + 512100 300股(¥3.204)
    a_pattern = re.findall(
        r'(\d{6}\.\w{2}|\d{6})\s+([\d,]+)股\s*\(\s*[¥$]?([\d.]+)\s*\)',
        memory_text
    )
    for ticker, shares_str, cost_str in a_pattern:
        ticker_clean = ticker.replace(".SH", "").replace(".SZ", "").replace(".HK", "")
        try:
            shares = int(shares_str.replace(",", ""))
            cost = float(cost_str)
            positions[ticker_clean] = {"shares": shares, "cost": cost, "source": "A账户确权段"}
        except:
            pass

    # 模式2: 「B账户持仓确权（日期）」段
    # 例: VEA 2,244股(成本$72.17)/VTI 282股(成本$327.69)
    b_pattern = re.findall(
        r'([A-Z]{2,5})\s+([\d,]+)股\s*\(\s*成本\s*[¥$]?([\d.]+)\s*\)',
        memory_text
    )
    for ticker, shares_str, cost_str in b_pattern:
        try:
            shares = int(shares_str.replace(",", ""))
            cost = float(cost_str)
            if ticker not in positions:
                positions[ticker] = {"shares": shares, "cost": cost, "source": "B账户确权段"}
        except:
            pass

    # 模式3: 散落格式 — 如「MUFG 1,644股(成本$19.961)」或「CANE 3,452股(均价≈$9.90)」
    scattered = re.findall(
        r'([A-Z]{2,5})\s+([\d,]+)股\s*\(\s*(?:成本|均价)\s*[≈=]?\s*[¥$]?([\d.]+)\s*\)',
        memory_text
    )
    for ticker, shares_str, cost_str in scattered:
        if ticker not in positions:
            try:
                shares = int(shares_str.replace(",", ""))
                cost = float(cost_str)
                positions[ticker] = {"shares": shares, "cost": cost, "source": "散落格式"}
            except:
                pass

    # 模式4: 「已清仓」标注 — 如「513910(7/15,浮盈+4.1%)」
    cleared = re.findall(
        r'(\d{6}\.\w{2}|\d{6}|[A-Z]{2,5})\s*\(\s*[\d/]+.*?(?:清仓|止盈|已清仓|已卖出)',
        memory_text
    )
    cleared_tickers = set()
    for t in cleared:
        cleared_tickers.add(t.replace(".SH", "").replace(".SZ", ""))

    # 模式5: 独立清仓段 — 「已清仓归档：159302/BBJP/SGOV/IVV/...」
    archive_match = re.search(
        r'已清仓归档[：:]\s*(.+?)(?:\n|$)',
        memory_text
    )
    if archive_match:
        archive_text = archive_match.group(1)
        # 按/分割，但只提取有效的标的代码（2-6位字母数字）
        for part in archive_text.split("/"):
            ticker_candidate = part.strip().replace(".SH", "").replace(".SZ", "")
            # 只保留有效的标的代码格式
            if re.match(r'^[A-Z]{2,5}$|^\d{6}$', ticker_candidate):
                cleared_tickers.add(ticker_candidate)

    return positions, cleared_tickers


def parse_decision_log_clears():
    """
    从决策日志中提取守东确认的清仓记录。
    返回: {ticker: {"date": str, "reason": str}, ...}
    """
    clears = {}
    if not DECISION_LOG_DIR.exists():
        return clears

    # 读取最近3个月的决策日志
    for month_file in sorted(DECISION_LOG_DIR.glob("*.md"), reverse=True)[:3]:
        text = read_file(month_file)
        # 搜索清仓/止盈记录
        # 格式: 「MM/DD 清仓XXX」或 「XXX 已清仓」
        entries = re.findall(
            r'(\d{1,2}/\d{1,2}).*?([A-Z]{2,5}|\d{6}).*?(?:清仓|止盈|已清仓|已卖出)',
            text
        )
        for date, ticker in entries:
            if ticker not in clears:
                clears[ticker] = {"date": date, "source": month_file.name}

    return clears


def step_0_5_position_verify():
    """
    Step 0.5: 规则O — 持仓事实强制校验

    做三件事:
    1. 解析 MEMORY.md 中的持仓确权段 → 提取所有持仓
    2. 解析已清仓归档 → 提取所有已清仓标的
    3. 交叉比对决策日志 → 检查是否有 MEMORY 持有但决策日志已清仓的矛盾

    输出:
    - 已确权持仓清单
    - 已清仓清单
    - 矛盾清单（🔴 LLM必须裁决）
    - 待确权清单（🟡 LLM需确认）
    """
    memory_text = read_file(MEMORY_MD)
    today_text = read_file(today_file()) if today_file().exists() else ""

    positions, cleared_tickers = parse_memory_positions(memory_text)
    decision_clears = parse_decision_log_clears()

    # 交叉比对: MEMORY 持仓 vs 决策日志清仓
    conflicts = []
    for ticker in positions:
        if ticker in decision_clears:
            conflicts.append({
                "ticker": ticker,
                "memory_says": f"持有{positions[ticker]['shares']}股",
                "decision_log_says": f"已清仓({decision_clears[ticker]['date']})",
                "severity": "🔴",
                "llm_action": "裁决：以MEMORY.md为准还是决策日志为准？需守东确权"
            })

    # 检查 MEMORY 持仓 vs 已清仓归档的矛盾
    for ticker in positions:
        if ticker in cleared_tickers:
            conflicts.append({
                "ticker": ticker,
                "memory_says": f"持有{positions[ticker]['shares']}股",
                "cleared_archive_says": "已清仓归档",
                "severity": "🔴",
                "llm_action": "MEMORY内部矛盾：持仓确权段说持有，已清仓归档说已清仓"
            })

    # 检查当日memory中是否有更新的持仓信息
    today_positions_hints = []
    if today_text:
        # 搜索守东投喂的持仓相关表述
        hints = re.findall(
            r'(?:持仓|持有|建仓|买入|清仓|卖出)\s*[：:]\s*(.+)',
            today_text
        )
        today_positions_hints = hints

    # 构建持仓摘要
    holdings_summary = {}
    for ticker, info in positions.items():
        if ticker not in cleared_tickers:
            holdings_summary[ticker] = {
                "shares": info["shares"],
                "cost": info["cost"],
                "source": info["source"]
            }

    # 检查 BOTZ 等已知从未买入的标的
    known_never_bought = ["BOTZ"]  # MEMORY 明确标注从未买入
    false_positives = []
    for ticker in known_never_bought:
        if ticker in holdings_summary:
            false_positives.append({
                "ticker": ticker,
                "memory_shows": holdings_summary[ticker],
                "known_fact": "从未被守东买入",
                "severity": "🔴",
                "llm_action": "硬锁零.八违规——BOTZ不应出现在持仓确权段"
            })

    passed = len(conflicts) == 0 and len(false_positives) == 0

    return make_result(
        "Step 0.5 规则O持仓校验",
        "✅" if passed else "⚠️有冲突需LLM裁决",
        passed=passed,
        holdings=holdings_summary,
        holdings_count=len(holdings_summary),
        cleared=list(cleared_tickers),
        cleared_count=len(cleared_tickers),
        conflicts=conflicts,
        false_positives=false_positives,
        today_hints=today_positions_hints,
        llm_required=not passed,
        llm_instructions=[
            "1. 检查 conflicts 列表——如有🔴项，需裁决持仓状态",
            "2. 检查 false_positives——如有BOTZ等从未买入标的出现，立即隔离",
            "3. 检查 holdings 是否与守东最近确权一致",
            "4. 确认后更新 holdings_summary 为最终持仓清单"
        ] if not passed else []
    )


# ══════════════════════════════════════════════════════════════
# Step 3: 规则K — P0/P1覆写检查
# ══════════════════════════════════════════════════════════════

def extract_p0_prices(memory_text):
    """
    从当日和前日memory中提取守东投喂的标的现价。
    返回: {ticker: {"price": float, "date": str, "source": str}, ...}
    """
    prices = {}

    # 模式1: 「标的 ¥X.XXX」或「标的 $X.XX」— 必须有货币符号
    # 例: 513910 ¥1.478 / QQQ $696.30
    pattern1 = re.findall(
        r'(\d{6}\.\w{2}|\d{6}|[A-Z]{2,5})\s+([¥$])(\d+\.?\d*)',
        memory_text
    )
    for ticker, currency, price_str in pattern1:
        try:
            p = float(price_str)
            # 过滤不合理价格：A股ETF至少¥0.1，美股至少$1
            min_price = 0.1 if currency == "¥" else 1.0
            max_price = 10000
            if min_price <= p <= max_price:
                ticker_clean = ticker.replace(".SH", "").replace(".SZ", "")
                # 过滤持仓股数误匹配：A股价格通常>¥1，美股>=$10
                if currency == "¥" and p < 1.0:
                    continue  # 可能是股数
                if currency == "$" and p < 5.0:
                    continue  # 可能是股数或持仓数量
                if ticker_clean not in prices:
                    prices[ticker_clean] = {"price": p, "source": "memory投喂"}
        except:
            pass

    # 模式2: 「标的=现价」格式 — 同样必须有货币符号
    pattern2 = re.findall(
        r'(\d{6}\.\w{2}|\d{6}|[A-Z]{2,5})\s*[=＝]\s*([¥$])(\d+\.?\d*)',
        memory_text
    )
    for ticker, currency, price_str in pattern2:
        try:
            p = float(price_str)
            min_price = 0.1 if currency == "¥" else 5.0
            if min_price <= p <= 10000:
                ticker_clean = ticker.replace(".SH", "").replace(".SZ", "")
                if ticker_clean not in prices:
                    prices[ticker_clean] = {"price": p, "source": "memory投喂(=格式)"}
        except:
            pass

    # 模式3: 腾讯实时格式 — 无货币符号但有明确价格上下文
    # 例: 「现价: QQQ $696.30」或 「QQQ 现价 696.30」
    pattern3 = re.findall(
        r'(?:现价|最新价|收盘价|当前)[：:\s]*(\d{6}\.\w{2}|\d{6}|[A-Z]{2,5})\s*[¥$]?(\d+\.?\d+)',
        memory_text
    )
    for ticker, price_str in pattern3:
        try:
            p = float(price_str)
            ticker_clean = ticker.replace(".SH", "").replace(".SZ", "")
            if 1.0 <= p <= 10000 and ticker_clean not in prices:
                prices[ticker_clean] = {"price": p, "source": "memory投喂(现价上下文)"}
        except:
            pass

    return prices


def step_3_p0_overlay():
    """
    Step 3: 规则K — P0/P1覆写检查

    扫描当日memory + 前日memory → 提取守东投喂的所有标的现价
    → 标记哪些标的可用P0覆写

    注意：腾讯实时API的现价在 Step 1.1 中已获取，此处只处理 P0 投喂覆写。
    脚本不判断「应该用P0还是Tushare」——那是LLM的活。
    """
    today_text = read_file(today_file()) if today_file().exists() else ""

    # 前日memory
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_file = MEMORY_DIR / f"{yesterday}.md"
    yesterday_text = read_file(yesterday_file) if yesterday_file.exists() else ""

    p0_today = extract_p0_prices(today_text)
    p0_yesterday = extract_p0_prices(yesterday_text)

    # 合并，当日优先
    p0_merged = {}
    for ticker, info in p0_yesterday.items():
        p0_merged[ticker] = {**info, "staleness": "前日"}
    for ticker, info in p0_today.items():
        p0_merged[ticker] = {**info, "staleness": "当日"}

    # 检查是否有H20/C4相关的P0投喂
    h20_hints = []
    h20_pattern = re.findall(
        r'(\d{6}\.\w{2}|\d{6}|[A-Z]{2,5})\s*H20\s*[=＝]\s*[¥$]?(\d+\.?\d*)',
        today_text + yesterday_text
    )
    for ticker, h20_str in h20_pattern:
        try:
            h20_hints.append({
                "ticker": ticker.replace(".SH", "").replace(".SZ", ""),
                "h20": float(h20_str),
                "note": "Step K4.1: P0 H20可用，C4基值=P0 H20"
            })
        except:
            pass

    return make_result(
        "Step 3 规则K P0覆写",
        "✅",
        passed=True,
        p0_prices=p0_merged,
        p0_count=len(p0_merged),
        h20_hints=h20_hints,
        h20_count=len(h20_hints),
        llm_instructions=[
            "1. 逐标比对 P0投喂日期 vs Tushare最新日期",
            "2. P0更更新 → 用P0覆写现价栏，标注「P0(MM/DD投喂)」",
            "3. Tushare更更新 → 用Tushare，标注「Tushare(MM/DD)」",
            "4. 技术指标(EMA/ATR/MACD)继续用Tushare计算值",
            "5. 如有H20 hints → C4基值=P0 H20（Step K4.1强制）",
            "6. 输出K5覆写摘要作为正文首段"
        ]
    )


# ══════════════════════════════════════════════════════════════
# Step 3.5: 规则K.6 — 持仓成本强制来源校验
# ══════════════════════════════════════════════════════════════

def step_3_5_cost_verify(holdings_from_step_0_5):
    """
    Step 3.5: 规则K.6 — 持仓成本强制来源校验

    输入: Step 0.5 输出的 holdings_summary（已确权持仓）
    动作:
    1. 从 MEMORY.md 提取每笔持仓的成本
    2. 从当日memory提取更新的成本信息
    3. 交叉比对 → 标记不一致项
    4. 输出每个持仓标的的成本来源 + 确权日期

    注意: 成本校验的前提是持仓已确权（Step 0.5通过）
    """
    memory_text = read_file(MEMORY_MD)
    today_text = read_file(today_file()) if today_file().exists() else ""

    # 从 MEMORY.md 提取成本信息（已在 parse_memory_positions 中做了）
    mem_positions, _ = parse_memory_positions(memory_text)

    # 从当日memory提取成本相关投喂
    today_cost_updates = {}
    cost_pattern = re.findall(
        r'(\d{6}\.\w{2}|\d{6}|[A-Z]{2,5})\s*(?:成本|均价|建仓价).*?[¥$]?(\d+\.?\d*)',
        today_text
    )
    for ticker, cost_str in cost_pattern:
        try:
            ticker_clean = ticker.replace(".SH", "").replace(".SZ", "")
            today_cost_updates[ticker_clean] = float(cost_str)
        except:
            pass

    # 逐标校验
    cost_verification = {}
    warnings = []

    for ticker, holding in (holdings_from_step_0_5 or {}).items():
        mem_cost = None
        if ticker in mem_positions:
            mem_cost = mem_positions[ticker].get("cost")

        today_cost = today_cost_updates.get(ticker)

        # 裁决优先级: 当日memory > MEMORY.md
        if today_cost is not None:
            effective_cost = today_cost
            source = f"当日memory({today_str()})"
            if mem_cost is not None and abs(today_cost - mem_cost) / mem_cost > 0.01:
                warnings.append({
                    "ticker": ticker,
                    "mem_cost": mem_cost,
                    "today_cost": today_cost,
                    "delta_pct": f"{(today_cost - mem_cost) / mem_cost * 100:+.1f}%",
                    "action": "以当日memory为准"
                })
        elif mem_cost is not None:
            effective_cost = mem_cost
            source = f"MEMORY.md确权段"
        else:
            effective_cost = None
            source = "⚠️未确权"
            warnings.append({
                "ticker": ticker,
                "issue": "成本未确权——MEMORY.md和当日memory均无成本记录",
                "action": "⛔禁止输出止损/止盈/浮盈亏计算，需守东供弹"
            })

        cost_verification[ticker] = {
            "cost": effective_cost,
            "source": source,
            "status": "✅" if effective_cost is not None else "⛔"
        }

    all_ok = all(v["status"] == "✅" for v in cost_verification.values())

    return make_result(
        "Step 3.5 规则K.6成本校验",
        "✅" if all_ok else "⚠️有未确权成本",
        passed=all_ok,
        cost_verification=cost_verification,
        warnings=warnings,
        llm_instructions=[
            "1. 任何止损/止盈/浮盈亏输出前，必须先确认成本来源",
            "2. cost_verification中status=⛔的标的 → 禁止输出止损/止盈/浮盈亏",
            "3. 有warnings的标的 → 在输出中标注成本来源",
            "4. 格式: 「成本: $X.XX（来源: MEMORY.md YYYY-MM-DD确权）」"
        ]
    )


# ══════════════════════════════════════════════════════════════
# Step 6.5: 敏感词事实断言扫描
# ══════════════════════════════════════════════════════════════

SENSITIVE_WORDS = {
    "execution_fact": {
        "keywords": ["已清仓", "已卖出", "已买入", "已加仓", "已建仓", "已执行", "已止损", "已止盈"],
        "trigger_rule": "规则P.1 — 执行事实确认",
        "check": "来源是否为守东确权？非守东确认→自动替换为「⚠️信号触发，待执行」"
    },
    "cost": {
        "keywords": ["成本=$", "成本=¥", "成本约$", "成本约¥", "建仓成本"],
        "trigger_rule": "规则K.6 — 成本来源校验",
        "check": "是否已标注来源+确权日期？未标注→补充"
    },
    "stop_loss": {
        "keywords": ["止损$", "止损¥", "止损线", "止损位"],
        "trigger_rule": "规则K.6 — 成本是止损底座",
        "check": "成本是否已确权？未确权→禁止输出止损计算"
    },
    "pnl": {
        "keywords": ["浮盈", "浮亏", "盈亏", "盈利", "亏损"],
        "trigger_rule": "规则K.6 — 盈亏依赖成本",
        "check": "成本是否已确权？未确权→禁止输出盈亏计算"
    },
    "tushare_status": {
        "keywords": ["Tushare不可用", "Tushare停更", "token失效", "Tushare数据停在", "Tushare token"],
        "trigger_rule": "规则G.1+N.1 — Tushare状态验证",
        "check": "本会话是否已显式调用验证？未验证→禁止输出此论断"
    },
    "technical_indicator": {
        "keywords": ["ATR14=", "MA40=", "MA60=", "MA120=", "MA250=", "乖离率=", "EMA50=", "EMA150=", "MACD=", "RSI14=", "ADX14="],
        "trigger_rule": "规则M.3 — 伪计算审计",
        "check": "该数值能否追溯到「Tushare日线→pandas计算→结果」链？不能→拦截强制重算"
    },
    "cooling_period": {
        "keywords": ["冷却至", "冷却期至", "冷却到", "冷却X天"],
        "trigger_rule": "r33.68 — 冷却期已废除",
        "check": "开仓冷却期已废除（r33.68），仅保留加仓过热约束。如出现→标记为过期规则残留"
    }
}


def step_6_5_sensitive_scan(output_text):
    """
    Step 6.5: 敏感词事实断言扫描

    扫描即将输出的文本，命中敏感词时触发对应校验。
    脚本不拦截输出——只标记命中位置和需要检查的规则，
    LLM读取后自行判断是否需要修正。
    """
    if not output_text:
        return make_result(
            "Step 6.5 敏感词扫描",
            "⏭️跳过",
            passed=True,
            hits={},
            note="无输出文本传入"
        )

    hits = {}

    for category, config in SENSITIVE_WORDS.items():
        category_hits = []
        for kw in config["keywords"]:
            for match in re.finditer(re.escape(kw), output_text):
                # 获取上下文（前后20字符）
                start = max(0, match.start() - 20)
                end = min(len(output_text), match.end() + 20)
                context = output_text[start:end].replace("\n", " ").strip()

                category_hits.append({
                    "keyword": kw,
                    "position": match.start(),
                    "context": f"...{context}...",
                    "rule": config["trigger_rule"],
                    "check": config["check"]
                })

        if category_hits:
            hits[category] = category_hits

    # 特别检查：冷却期残留
    cooling_hits = []
    cooling_patterns = [
        r'冷却至\s*\d{1,2}/\d{1,2}',
        r'冷却期至\s*\d{1,2}/\d{1,2}',
        r'冷却\s*\d+\s*天',
        r'冷却到\s*\d{1,2}/\d{1,2}',
    ]
    for pattern in cooling_patterns:
        for match in re.finditer(pattern, output_text):
            context = output_text[max(0, match.start()-20):match.end()+20].replace("\n", " ")
            cooling_hits.append({
                "pattern": match.group(),
                "context": f"...{context}...",
                "rule": "r33.68 — 冷却期已废除",
                "check": "开仓冷却期已全部废除，应替换为「等待（MACD金叉+入买入区间）」或「等待（条件满足）」"
            })

    if cooling_hits:
        hits["cooling_abolished_r3368"] = cooling_hits

    # C3.1 宏观静默检查（特殊扫描）
    c31_hits = _scan_c31_violations(output_text)

    if c31_hits:
        hits["c31_macro_silence"] = c31_hits

    total_hits = sum(len(v) for v in hits.values())
    passed = total_hits == 0

    return make_result(
        "Step 6.5 敏感词扫描",
        "✅" if passed else f"⚠️{total_hits}处命中需检查",
        passed=passed,
        total_hits=total_hits,
        hits=hits,
        llm_instructions=[
            "1. 逐类检查 hits 中的命中项",
            "2. execution_fact 命中 → 回溯来源，非守东确认→替换为「⚠️信号触发，待执行」",
            "3. cost/stop_loss/pnl 命中 → 确认成本已标注来源+日期",
            "4. tushare_status 命中 → 确认本会话已调用验证",
            "5. technical_indicator 命中 → 确认可追溯到Tushare日线计算",
            "6. cooling_abolished 命中 → r33.68已废除开仓冷却期，替换为正确表述",
            "7. c31_macro_silence 命中 → 检查是否应在霍尔木兹危机期间暂停"
        ] if not passed else []
    )


def _detect_macro_silence_events():
    """
    从对话记忆中动态检测当前活跃的宏观静默事件。
    读取今天和昨天的memory文件，搜索关键词，返回活跃事件列表。
    
    搜索关键词: 霍尔木兹, 地缘, C3.1, 宏观静默, 海峡, 断流, 危机
    """
    events = []
    mem_files = []

    # 读取今天和前一天的memory
    for days_back in [0, 1]:
        d = (datetime.now() - timedelta(days=days_back)).date()
        f = Path(f"memory/{d.isoformat()}.md")
        if f.exists():
            mem_files.append((d.isoformat(), read_file(f)))

    # 搜索关键词
    silence_keywords = [
        "霍尔木兹", "地缘冲突", "地缘事件", "地缘风险",
        "C3.1", "宏观静默", "海峡断流", "海峡关闭",
        r"P0级.*事件", r"静默.*暂停",
    ]

    for date_str, text in mem_files:
        for kw in silence_keywords:
            if kw.replace("\\", "") in text:
                # 提取事件描述（关键词前后50字符）
                for match in re.finditer(re.escape(kw), text, re.IGNORECASE):
                    start = max(0, match.start() - 50)
                    end = min(len(text), match.end() + 50)
                    snippet = text[start:end].replace("\n", " ").strip()
                    events.append({
                        "keyword": kw,
                        "date": date_str,
                        "snippet": snippet,
                    })

    # 去重（同一天同一关键词只保留一次）
    seen = set()
    unique = []
    for e in events:
        key = (e["date"], e["keyword"])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return unique


def _scan_c31_violations(output_text):
    """
    C3.1 宏观事件静默期检查。

    ⭐ V2: 从对话记忆动态检测活跃的宏观静默事件（不再硬编码霍尔木兹）。
    检测到活跃事件 → 检查输出中是否有美股进攻/独立动量的开仓建议
    但未标注C3.1暂停。

    应暂停: 美股进攻(QQQ/IVV/MUFG/BOTZ) + 独立动量(FLIN/SMIN/EWY/VNM)
    豁免: A股进攻+反击 / 金盾+固定层
    """
    # 先检测是否有活跃的宏观静默事件
    active_events = _detect_macro_silence_events()

    if not active_events:
        return []  # 无活跃事件，跳过C3.1检查

    hits = []
    c31_sensitive_tickers = ["QQQ", "IVV", "MUFG", "BOTZ", "FLIN", "SMIN", "EWY", "VNM"]

    # 提取事件名用于提示
    event_names = list(set(
        e["keyword"] for e in active_events
        if e["keyword"] not in ["C3.1", "宏观静默"]
    ))[:3]
    event_label = "/".join(event_names) if event_names else "活跃地缘事件"

    for ticker in c31_sensitive_tickers:
        pattern = re.compile(
            rf'{ticker}.*?(?:可执行|买入|开火|加仓|建仓|轨道.*?触发)',
            re.DOTALL
        )
        for match in pattern.finditer(output_text):
            context = match.group()[:200].replace("\n", " ")
            # 检查是否已标注暂停
            if "C3.1" not in context and "暂停" not in context and "推迟" not in context:
                hits.append({
                    "ticker": ticker,
                    "context": context,
                    "rule": f"C3.1 — {event_label}",
                    "check": f"{ticker}属于美股进攻/独立动量，{event_label}期间应⛔暂停新开仓",
                    "active_events": [e["snippet"][:100] for e in active_events[:3]]
                })

    return hits


# ══════════════════════════════════════════════════════════════
# 主入口: 跑第二批全部步骤
# ══════════════════════════════════════════════════════════════

def run_v2_chain(output_text=None, holdings_override=None):
    """
    跑第二批全部步骤。

    output_text: LLM即将输出的分析正文（用于Step 6.5扫描）
    holdings_override: 手动指定的持仓（用于跳过Step 0.5自动解析）

    返回: {
        "chain_passed": bool,
        "steps": [...],
        "llm_checklist": [...],  # LLM必须处理的事项
        "summary": str
    }
    """
    steps = []
    llm_checklist = []

    # Step 0.5: 持仓校验
    r = step_0_5_position_verify()
    steps.append(r)
    if r.get("llm_required"):
        llm_checklist.append({
            "step": "Step 0.5",
            "action": "持仓冲突裁决",
            "details": r.get("conflicts", []) + r.get("false_positives", [])
        })

    # 获取确权持仓（用于后续步骤）
    holdings = holdings_override or r.get("holdings", {})

    # Step 3: P0覆写
    r = step_3_p0_overlay()
    steps.append(r)

    # Step 3.5: 成本校验
    r = step_3_5_cost_verify(holdings)
    steps.append(r)
    if r.get("warnings"):
        llm_checklist.append({
            "step": "Step 3.5",
            "action": "成本未确权处理",
            "details": r["warnings"]
        })

    # Step 6.5: 敏感词扫描
    r = step_6_5_sensitive_scan(output_text or "")
    steps.append(r)
    if not r["passed"]:
        llm_checklist.append({
            "step": "Step 6.5",
            "action": "敏感词修正",
            "details": {k: len(v) for k, v in r.get("hits", {}).items()}
        })

    all_passed = all(s["passed"] for s in steps)

    return {
        "chain_passed": all_passed,
        "steps": steps,
        "llm_checklist": llm_checklist,
        "summary": "全部通过" if all_passed else f"需LLM处理{len(llm_checklist)}项"
    }


# ══════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="执行链第二批 — LLM辅助裁决步骤")
    parser.add_argument("--step", type=str, choices=["0.5","3","3.5","6.5","all"],
                        default="all", help="仅运行指定步骤")
    parser.add_argument("--check-text", type=str, help="Step 6.5自检的文本（可传入文件路径或直接文本）")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()

    # 处理 --check-text（可能是文件路径）
    check_text = args.check_text
    if check_text and os.path.exists(check_text):
        check_text = read_file(Path(check_text))

    if args.step == "0.5":
        result = step_0_5_position_verify()
    elif args.step == "3":
        result = step_3_p0_overlay()
    elif args.step == "3.5":
        r05 = step_0_5_position_verify()
        result = step_3_5_cost_verify(r05.get("holdings", {}))
    elif args.step == "6.5":
        result = step_6_5_sensitive_scan(check_text or "")
    else:
        result = run_v2_chain(check_text)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
