#!/usr/bin/env python3
"""
scan_report.py V1.0 — /扫描 报告渲染器（2026-08-12 焊入）
联邦投顾扫描流水线的最后一环：market_data + route_engine + positions → Markdown 四段式模板

用法：
  python3 scripts/scan_report.py                    # /扫描（全池24标）
  python3 scripts/scan_report.py --scope us          # /扫描美股（12标）
  python3 scripts/scan_report.py --scope cn          # /扫描A股（12标）
  python3 scripts/scan_report.py --json             # 输出JSON（供LLM进一步处理）

流水线：
  market_data.py → route_engine.py → positions.json → scan_report.py (渲染)
"""

import json
import sys
import os
import subprocess
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(SCRIPT_DIR, "..")

# ══════════════════════════════════════════════════════════════
# 第零层：配置
# ══════════════════════════════════════════════════════════════

# 标的名称映射
TICKER_NAMES = {
    "QQQ": "纳指100ETF", "IVV": "标普500ETF", "IAU": "黄金ETF",
    "BBJP": "日本大盘ETF", "MUFG": "三菱日联金融", "EWY": "韩国ETF",
    "VNM": "越南ETF", "FLIN": "印度大盘ETF", "SMIN": "印度小盘ETF",
    "VEA": "发达市场ETF", "VTI": "全美市场ETF", "BOTZ": "机器人AI ETF",
    "588000": "科创50ETF", "513180": "恒生科技ETF", "513910": "港股央企红利",
    "510500": "中证500ETF", "518880": "黄金ETF", "512100": "中证1000ETF",
    "510880": "红利ETF", "159530": "机器人ETF", "510300": "沪深300ETF",
    "159915": "创业板ETF", "513770": "恒生医疗ETF", "159545": "中证红利ETF",
    "CANE": "白糖ETN",
}

# 路由emoji映射
ROUTE_EMOJI = {
    "us_offensive": "🟢进攻",
    "a_share_offensive": "🟢A股进攻",
    "offensive_candidate": "🟡进攻候选",
    "counterpunch": "🟡反击",
    "momentum": "⚪动量",
    "gold_shield": "⚪金盾",
    "fixed_layer": "⚪固定",
    "independent": "⚪独立",
    "idle": "⚪闲置",
    "unclassified": "⚪待分类",
    "data_missing": "⚠️无数据",
}

# 全池标的分组
US_TICKERS = ["QQQ", "IVV", "IAU", "BBJP", "MUFG", "EWY", "VNM", "FLIN", "SMIN", "VEA", "VTI", "BOTZ", "CANE"]
CN_TICKERS = ["588000", "513180", "513910", "510500", "518880", "512100", "510880", "159530", "510300", "159915", "513770", "159545"]

# 标的市场类型
def ticker_market(ticker):
    if ticker in CN_TICKERS:
        return "cn"
    return "us"


# ══════════════════════════════════════════════════════════════
# 第一层：运行流水线
# ══════════════════════════════════════════════════════════════

def _enforce_intraday_gate():
    """🔴 盘中现价新鲜度闸门（2026-08-17 焊入 — 512100 ¥2.864 事故根因修复）

    在 market_data.py 拉取之后立即调用，盘中时段校验腾讯实时数据新鲜度，
    防止拿 TickFlow 日线收盘价/旧缓存冒充现价。
    失败抛 RuntimeError 中断 pipeline——报告无法生成，LLM 无法绕过。
    """
    try:
        proc = subprocess.run(
            ["python3", os.path.join(SCRIPT_DIR, "output_gate.py"), "--check", "intraday"],
            capture_output=True, text=True, timeout=15
        )
        out = proc.stdout.strip()
        try:
            gate = json.loads(out)
        except Exception:
            # output_gate 返回非 JSON → 不阻断（降级，但打印告警）
            print(f"[⚠️ intraday gate] output_gate 返回非JSON: {out[:200]}", file=sys.stderr)
            return
        if gate.get("gate") == "BLOCK":
            summary = ""
            for c in gate.get("checks", []):
                if c.get("status") == "BLOCK":
                    summary = c.get("summary", "")
                    break
            raise RuntimeError("🔴 盘中现价新鲜度闸门拦截: " + (summary or "现价数据疑似过期"))
    except RuntimeError:
        raise
    except Exception as e:
        print(f"[⚠️ intraday gate] 闸门执行异常（降级放行）: {e}", file=sys.stderr)


def run_pipeline(scope="all"):
    """跑扫描流水线，返回结构化数据"""
    
    # Step 1: market_data.py
    md = subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "market_data.py")],
        capture_output=True, text=True, timeout=120
    )
    market_data = _parse_json(md.stdout)

    # Step 1.5: 🔴 盘中现价新鲜度闸门（2026-08-17 焊入 — 512100 ¥2.864 事故根因修复）
    _enforce_intraday_gate()
    
    # Step 2: route_engine.py
    re_result = subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "route_engine.py")],
        input=json.dumps(market_data), capture_output=True, text=True, timeout=30
    )
    routes = _parse_json(re_result.stdout)
    
    # Step 3: macro_gate.py (宏观锚点 + 博弈态)
    mg_result = subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "macro_gate.py")],
        capture_output=True, text=True, timeout=30
    )
    macro = _parse_json(mg_result.stdout)
    
    # Step 3.5: game_state.py
    game_bridged = {
        "macro": macro,
        "indicators": _build_indicators_for_game_state(market_data)
    }
    gs_result = subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "game_state.py"), 
         "--bridged", json.dumps(game_bridged), "--json"],
        capture_output=True, text=True, timeout=30
    )
    game_state = _parse_json(gs_result.stdout)
    
    # Step 4: positions.json
    positions = load_positions()
    
    return {
        "market_data": market_data,
        "routes": routes,
        "macro": macro,
        "game_state": game_state,
        "positions": positions,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _build_indicators_for_game_state(market_data):
    """构建 game_state.py 期望的 indicators 格式"""
    indicators = {}
    for ticker, data in market_data.items():
        if ticker.startswith("_"):
            continue
        indicators[ticker] = {
            "symbol": ticker,
            "indicators": {
                "ADX14": {"value": data.get("adx14")},
                "VOL_RATIO": {"value": data.get("vol_ratio")},
            }
        }
    return indicators


def load_positions():
    """读取持仓"""
    try:
        with open(os.path.join(WORKSPACE, "scripts", "positions.json")) as f:
            pos_data = json.load(f)
        result = {}
        for acct in ["A", "B"]:
            for item in pos_data.get(acct, {}).get("holdings", []):
                ticker = item["ticker"]
                if ticker not in result:
                    result[ticker] = {}
                result[ticker][acct] = {
                    "shares": item.get("shares", 0),
                    "cost": item.get("cost", 0),
                }
        # 现金
        result["_cash"] = {
            "A": pos_data.get("A", {}).get("cash", 0),
            "B": pos_data.get("B", {}).get("cash", 0),
        }
        return result
    except:
        return {"_cash": {"A": 0, "B": 0}}


def _parse_json(s):
    """安全解析JSON"""
    s = s.strip()
    for i, c in enumerate(s):
        if c in ('{', '['):
            try:
                return json.loads(s[i:])
            except:
                return {"error": "JSON解析失败", "raw": s[:500]}
    return {"error": "无有效JSON", "raw": s[:500]}


# ══════════════════════════════════════════════════════════════
# 第二层：Markdown 渲染
# ══════════════════════════════════════════════════════════════

def render_markdown(data, scope="all"):
    """渲染 /扫描 四段式 Markdown"""
    macro = data["macro"]
    game_state = data.get("game_state", {})
    routes = data["routes"]
    mkt = data["market_data"]
    positions = data["positions"]
    
    lines = []
    
    # ── 段一：宏观重力场 + 博弈态 ──
    lines.extend(_render_macro_section(macro, game_state, scope))
    lines.append("")
    
    # ── 段二：全池路由判定表 ──
    lines.extend(_render_route_table(routes, mkt, positions, scope))
    lines.append("")
    
    # ── 段三：仓位与现金总览 ──
    lines.extend(_render_position_summary(mkt, positions))
    lines.append("")
    
    # ── 段四：操作建议汇总 ──
    lines.extend(_render_action_suggestions(routes, mkt, positions, macro))
    
    return "\n".join(lines)


# ─── 段一：宏观重力场 ───

def _render_macro_section(macro, game_state, scope="all"):
    """段一：宏观重力场 + 博弈态"""
    us10y = macro.get("us10y", {})
    vix = macro.get("vix", {})
    dxy = macro.get("dxy", {})
    es = macro.get("es", {})
    dr007 = macro.get("dr007", {})
    cny = macro.get("usdcny", {})
    
    us10y_val = us10y.get("value", "—")
    us10y_chg = us10y.get("change", "—")
    vix_val = vix.get("value", "—")
    vix_chg = vix.get("change", "—")
    dxy_val = dxy.get("value", "—")
    dxy_chg = dxy.get("change", "—")
    es_val = es.get("value", "—")
    es_chg = es.get("change", "—")
    dr007_val = dr007.get("value", "—")
    dr007_chg = dr007.get("change", "—")
    cny_val = cny.get("value", "—")
    cny_chg = cny.get("change", "—")
    
    # 信号灯简化
    def _label(val, label):
        return label if label else "⚪"
    
    lines = [
        "# 🔭 全量扫描" + ("" if scope == "all" else f" — {scope.upper()}") + f" — {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "## 一、宏观重力场 + 博弈态",
        "",
        "| 锚点 | 现值 | 变动 | 信号灯 |",
        "|:---|---:|:---:|:---:|",
        f"| DXY | {dxy_val} | {dxy_chg} | {_label(dxy_val, dxy.get('label'))} |",
        f"| US10Y | {us10y_val}% | {us10y_chg}bp | {_label(us10y_val, us10y.get('label'))} |",
        f"| VIX | {vix_val} | {vix_chg} | {_label(vix_val, vix.get('label'))} |",
        f"| ES/NQ | {es_val} | {es_chg} | {_label(es_val, es.get('label'))} |",
        f"| DR007 | {dr007_val}% | {dr007_chg}bp | {_label(dr007_val, dr007.get('label'))} |",
        f"| USDCNY | {cny_val} | {cny_chg}bp | {_label(cny_val, cny.get('label'))} |",
        "",
    ]
    
    # 宏观定性
    verdict = macro.get("verdict", {})
    summary = verdict.get("summary", "—")
    
    # 博弈态
    gs_label = game_state.get("label", "—")
    gs_cap = (game_state.get("cap") or 0) * 100
    
    # 二维评估
    two_dim = _infer_two_dim(macro)
    
    lines.append(f"├── 宏观定性: {summary}")
    lines.append(f"├── 博弈态: {gs_label} | 仓位上限: {gs_cap:.0f}% | 二维评估: {two_dim}")
    lines.append(f"└── 操作基调: [待LLM判定]")
    
    return lines


def _infer_two_dim(macro):
    """从macro数据推断二维评估结论"""
    vix = macro.get("vix", {})
    dxy = macro.get("dxy", {})
    
    vix_val = vix.get("value")
    dxy_dir = dxy.get("direction", "")
    
    vix_verdict = "⚪"
    if vix_val is not None:
        try:
            v = float(vix_val)
            if v > 35:
                vix_verdict = "🟢"
            elif v <= 20:
                vix_verdict = "🟡"
            else:
                vix_verdict = "🔴"
        except:
            pass
    
    dxy_verdict = "⚪"
    if dxy_dir:
        if "down" in dxy_dir.lower():
            dxy_verdict = "🟢"
        elif "up" in dxy_dir.lower():
            dxy_verdict = "🔴"
        else:
            dxy_verdict = "🟡"
    
    return f"VIX{vix_verdict}×DXY{dxy_verdict}"


# ─── 段二：全池路由判定表 ───

def _render_route_table(routes, mkt, positions, scope="all"):
    """段二：全池路由判定表"""
    
    # 确定要展示的标的
    if scope == "us":
        display_tickers = US_TICKERS
    elif scope == "cn":
        display_tickers = CN_TICKERS
    else:
        display_tickers = US_TICKERS + CN_TICKERS
    
    lines = [
        "## 二、全池路由判定",
        "",
        "| 标的 | 现价 | 涨跌 | 路由 | 持仓 | 动作 |",
        "|:---|:---:|:---:|:---|:---:|:---|",
    ]
    
    # 按路由分组排序
    route_order = {
        "us_offensive": 0, "a_share_offensive": 1, "offensive_candidate": 2,
        "counterpunch": 3, "momentum": 4, "gold_shield": 5,
        "fixed_layer": 6, "independent": 7,
        "idle": 8, "unclassified": 9, "data_missing": 10
    }
    
    sorted_tickers = sorted(
        [t for t in display_tickers if t in routes],
        key=lambda t: route_order.get(routes[t].get("route", ""), 99)
    )
    
    for ticker in sorted_tickers:
        rt = routes.get(ticker, {})
        md = mkt.get(ticker, {}) or {}
        
        price = md.get("price")
        change_pct = md.get("change_pct")
        route = rt.get("route", "?")
        status = rt.get("status", "?")
        
        # 价格格式化
        if ticker_market(ticker) == "cn":
            price_s = f"¥{price:.4f}" if isinstance(price, (int, float)) and price < 100 else f"¥{price:.3f}" if isinstance(price, (int, float)) else str(price)
        else:
            price_s = f"${price:.2f}" if isinstance(price, (int, float)) else str(price)
        
        chg_s = f"{change_pct:+.2f}%" if isinstance(change_pct, (int, float)) else str(change_pct)
        route_s = ROUTE_EMOJI.get(route, f"⚪{route}")
        
        # 持仓
        pos = _get_position_str(ticker, positions)
        
        # 动作
        action = _infer_action(ticker, rt, md)
        
        lines.append(f"| {ticker} | {price_s} | {chg_s} | {route_s} | {pos} | {action} |")
    
    lines.append("")
    lines.append("**路由图例**：🟢进攻=美股开火候选 | 🟢A股进攻=MA5回踩(仅牛市) | 🟡反击=等待买入区间 | ⚪闲置=不操作 | ⚪动量=独立动量策略 | ⛔剥夺=禁购 | ⚪金盾=黄金专属 | ⚪固定=固定层 | ⚪独立=独立标的")
    
    return lines


def _get_position_str(ticker, positions):
    """获取持仓字符串"""
    if ticker not in positions:
        return "—"
    
    parts = []
    for acct in ["A", "B"]:
        if acct in positions[ticker]:
            shares = positions[ticker][acct]["shares"]
            if shares > 0:
                parts.append(f"{acct}:{shares}股")
    
    return "/".join(parts) if parts else "—"


def _infer_action(ticker, rt, md):
    """从路由状态推断动作建议"""
    route = rt.get("route", "")
    status = rt.get("status", "")
    
    if route == "us_offensive":
        if "触发" in status:
            return "🟢开火候选"
        return "待C3/C4"
    elif route == "a_share_offensive":
        if "触发" in status:
            return "🟢开火候选"
        return "待MA5回踩"
    elif route == "offensive_candidate":
        return "等待恢复"
    elif route == "counterpunch":
        cp = rt.get("counterpunch", {})
        r05_filter = cp.get("r05_filter", "ma40_dir")
        # r33.96/33.97 — 非豁免标的用底部序列(159915)或MA40方向(510300)过滤
        if cp.get("r05_exempt"):
            # 豁免标的：不看过滤，直接按触发状态
            if "触发" in status:
                return "🟢开火候选"
            return "等待买入区间"
        # 非豁免标的：按各自过滤逻辑
        if cp.get("r05"):
            if "触发" in status:
                if r05_filter == "ma40_dir":
                    return "🟢反击触发(MA40↑)"
                return "🟢反击触发(底部序列✅)"
            if r05_filter == "ma40_dir":
                return "待MA40转向上(价格到位)"
            return "待底部序列(价格到位)"
        if r05_filter == "ma40_dir":
            return "🔒MA40未向上"
        return "🔒底部序列未确认(等止跌日)"
    elif route == "momentum":
        momentum = rt.get("momentum", {})
        if momentum.get("track_one"):
            return "🟢轨道一触发"
        if momentum.get("track_two"):
            return "🟢轨道二触发"
        return "待信号"
    elif route == "gold_shield":
        gs = rt.get("gold_shield", {})
        if gs.get("all_green"):
            return "🟢四条件全绿"
        return "等待"
    elif route == "fixed_layer":
        fl = rt.get("fixed_layer", {})
        if fl.get("in_buy_zone"):
            return "🟢在买入区间"
        return "等待"
    elif route == "independent":
        return "持有(厄尔尼诺)"
    elif route == "idle":
        return "不操作"
    else:
        return "—"


# ─── 段三：仓位与现金总览 ───

def _render_position_summary(mkt, positions):
    """段三：仓位与现金总览"""
    cash = positions.get("_cash", {"A": 0, "B": 0})
    
    # 计算持仓市值（A股用CNY，B股用USD）
    a_total_market = 0
    b_total_market = 0
    
    for ticker, pos_data in positions.items():
        if ticker.startswith("_"):
            continue
        md = mkt.get(ticker, {}) or {}
        price = md.get("price")
        if price is None:
            continue
        
        for acct in ["A", "B"]:
            if acct in pos_data:
                shares = pos_data[acct]["shares"]
                if ticker_market(ticker) == "cn" and acct == "A":
                    a_total_market += shares * price
                elif acct == "B":
                    b_total_market += shares * price
    
    a_total = a_total_market + cash.get("A", 0)
    b_total = b_total_market + cash.get("B", 0)
    
    a_equity_pct = (a_total_market / a_total * 100) if a_total > 0 else 0
    b_equity_pct = (b_total_market / b_total * 100) if b_total > 0 else 0
    
    lines = [
        "## 三、仓位与现金总览",
        "",
        "| 维度 | 数值 |",
        "|:---|---:|",
        f"| A账户总资产 | ¥{a_total:,.0f} | 权益仓位 | {a_equity_pct:.0f}% | 可用现金 | ¥{cash.get('A', 0):,.0f} |",
        f"| B账户总资产 | ${b_total:,.0f} | 权益仓位 | {b_equity_pct:.0f}% | 可用现金 | ${cash.get('B', 0):,.0f} |",
        f"| 合并总资产(USDCNY —) | ¥— | 总权益仓位 | — | 总现金 | — |",
    ]
    return lines


# ─── 段四：操作建议汇总 ───

def _render_action_suggestions(routes, mkt, positions, macro):
    """段四：操作建议汇总"""
    
    suggestions = _collect_suggestions(routes, mkt, positions, macro)
    
    if not suggestions:
        return [
            "## 四、操作建议汇总",
            "",
            "无待执行操作，所有标的处于等待/持有状态。",
        ]
    
    lines = [
        "## 四、操作建议汇总",
        "",
        "| # | 优先级 | 标的 | 操作 | 数量 | 价格条件 | 备注 |",
        "|:---:|:---:|:---|:---|:---:|:---|:---|",
    ]
    
    for i, s in enumerate(suggestions, 1):
        lines.append(
            f"| {i} | {s['priority']} | {s['ticker']} | {s['action']} | {s['qty']} | {s['condition']} | {s['note']} |"
        )
    
    # 一句话总结
    if suggestions:
        top = suggestions[0]
        lines.append("")
        lines.append(f"**一句话总结**：{top['ticker']} {top['action']}，{top['note']}")
    
    lines.append("")
    lines.append("**优先级**：🟢可执行(可直接下单) | 🟡观察(接近触发) | 🔴禁止(冷却/冻结) | ⚪持有 | ⚪等待")
    
    return lines


def _fmt_price(val, ticker):
    """格式化价格（放在 _collect_suggestions 之前，避免引用错误）"""
    if val is None:
        return "—"
    if isinstance(val, (int, float)):
        if ticker_market(ticker) == "cn":
            return f"¥{val:.3f}"
        return f"${val:.2f}"
    return str(val)


def _collect_suggestions(routes, mkt, positions, macro):
    """从路由数据中收集操作建议"""
    suggestions = []
    
    for ticker, rt in routes.items():
        if ticker.startswith("_"):
            continue
        
        route = rt.get("route", "")
        status = rt.get("status", "")
        md = mkt.get(ticker, {}) or {}
        price = md.get("price")
        
        # 美股进攻触发
        if route == "us_offensive" and "触发" in status:
            c31_blocked = macro.get("c31_layered", {}).get("us_offensive", "").startswith("⛔")
            if c31_blocked:
                suggestions.append({
                    "priority": "🔴禁止", "ticker": ticker,
                    "action": "暂停", "qty": "—",
                    "condition": "—",
                    "note": "C3.1宏观静默"
                })
            else:
                c4_price = md.get("h20", 0) * 0.98 if md.get("h20") else None
                suggestions.append({
                    "priority": "🟢可执行", "ticker": ticker,
                    "action": "买入", "qty": "按5%仓位",
                    "condition": f"≤${c4_price:.2f}" if c4_price else "—",
                    "note": "C3/C4全满足"
                })
        
        # A股进攻触发
        elif route == "a_share_offensive" and "触发" in status:
            suggestions.append({
                "priority": "🟢可执行", "ticker": ticker,
                "action": "买入", "qty": "按5%仓位",
                "condition": f"≤{_fmt_price(price, ticker)}",
                "note": "MA5回踩触发"
            })
        
        # 反击触发
        elif route == "counterpunch" and "触发" in status:
            cp = rt.get("counterpunch", {})
            buy_zone_high = cp.get("buy_zone_high")
            # r33.96/33.97 — r05 为布尔值（True=放行），非豁免标的按各自过滤
            r05 = cp.get("r05", True)
            r05_exempt = cp.get("r05_exempt", False)
            r05_filter = cp.get("r05_filter", "ma40_dir")
            r05_blocked = (not r05) and (not r05_exempt)
            if r05_blocked:
                suggestions.append({
                    "priority": "🔴禁止", "ticker": ticker,
                    "action": "暂停", "qty": "—",
                    "condition": "—",
                    "note": "MA40未向上" if r05_filter == "ma40_dir" else "底部序列未确认"
                })
            else:
                suggestions.append({
                    "priority": "🟢可执行", "ticker": ticker,
                    "action": "买入", "qty": "正金字塔两层",
                    "condition": f"≤{_fmt_price(buy_zone_high, ticker)}" if buy_zone_high else "—",
                    "note": "反击触发，区间内"
                })
        
        # 动量触发
        elif route == "momentum":
            momentum = rt.get("momentum", {})
            if momentum.get("track_one"):
                suggestions.append({
                    "priority": "🟢可执行", "ticker": ticker,
                    "action": "买入", "qty": "单笔5%",
                    "condition": f"≤{_fmt_price(price, ticker)}" if price else "—",
                    "note": "MACD金叉+价<MA20"
                })
            if momentum.get("track_two"):
                suggestions.append({
                    "priority": "🟢可执行", "ticker": ticker,
                    "action": "买入", "qty": momentum.get("track_two_build", "正金字塔(3/7)"),
                    "condition": f"≤{_fmt_price(price, ticker)}" if price else "—",
                    "note": "恐慌抄底触发"
                })
        
        # 固定层触发
        elif route == "fixed_layer":
            fl = rt.get("fixed_layer", {})
            if fl.get("in_buy_zone"):
                suggestions.append({
                    "priority": "🟢可执行", "ticker": ticker,
                    "action": "买入", "qty": "按固定层仓位",
                    "condition": f"≤{_fmt_price(price, ticker)}" if price else "—",
                    "note": "在买入区间内"
                })
    
    # 排序：可执行 > 观察 > 禁止
    priority_order = {"🟢可执行": 0, "🟡观察": 1, "🔴禁止": 2, "⚪持有": 3, "⚪等待": 4}
    suggestions.sort(key=lambda s: priority_order.get(s["priority"], 99))
    
    return suggestions
    """格式化价格"""
    if val is None:
        return "—"
    if isinstance(val, (int, float)):
        if ticker_market(ticker) == "cn":
            return f"¥{val:.3f}"
        return f"${val:.2f}"
    return str(val)


# ══════════════════════════════════════════════════════════════
# CLI入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="联邦投顾扫描报告渲染器")
    parser.add_argument("--scope", type=str, default="all", choices=["all", "us", "cn"],
                       help="扫描范围：all=全池, us=美股, cn=A股")
    parser.add_argument("--json", action="store_true", help="输出JSON（供LLM进一步处理）")
    args = parser.parse_args()
    
    data = run_pipeline(args.scope)
    
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_markdown(data, args.scope))
