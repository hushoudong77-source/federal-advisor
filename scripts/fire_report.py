#!/usr/bin/env python3
"""
fire_report.py V1.0 — /开火 报告渲染器（2026-08-11 焊入）
联邦投顾开火流水线的最后一环：JSON → Markdown 模板

用法：
  python3 scripts/fire_report.py                         # 跑全流水线，输出完整 /开火 Markdown
  python3 scripts/fire_report.py --json                  # 输出 JSON（供 LLM 进一步处理）
  python3 scripts/fire_report.py --scope us              # 仅美股
  python3 scripts/fire_report.py --scope cn              # 仅A股
  python3 scripts/fire_report.py --mode offense          # 仅进攻（美股+A股+固定层+动量+CANE）
  python3 scripts/fire_report.py --mode counterpunch     # 仅反击（反击候选+恐慌抄底）

流水线：
  market_data.py → 格式桥接 → route_engine.py → fire_signal.py → macro_gate.py
      → opportunity_scorer.py → fire_report.py (渲染)
"""

import json
import sys
import os
import importlib
import importlib.util
import subprocess
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(SCRIPT_DIR, "..")

# ══════════════════════════════════════════════════════════════
# 模块内联加载（2026-08-13 焊入 — 消除 subprocess 冷启动，/开火 提速）
# 根因：原 fire_report.py 用 5+3=8 个 subprocess 串行调用各脚本，
#       每个都要冷启动 Python 解释器（~1-2秒 × N），导致 /开火 25秒延迟。
# 方案：用 importlib 动态加载同目录脚本，直接调用其函数，避免重复冷启动。
# ══════════════════════════════════════════════════════════════
def _load_module(name):
    """动态加载 scripts/ 下的同名 .py 模块，返回模块对象。失败返回 None。"""
    try:
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(SCRIPT_DIR, f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        return None


def _enforce_intraday_gate():
    """🔴 盘中现价新鲜度闸门（2026-08-17 焊入 — 512100 ¥2.864 事故根因修复）

    在 fetch_all() 之后立即调用，盘中时段校验腾讯实时数据新鲜度，
    防止拿 TickFlow 日线收盘价/旧缓存冒充现价。

    判定失败直接抛 RuntimeError 中断 pipeline——报告无法生成，
    LLM 无法绕过（不走脚本就没有报告，走了脚本必过闸）。
    """
    gate_mod = _load_module("output_gate")
    if gate_mod is None:
        # output_gate 不可用 → 不阻断（降级为无闸门，但不静默——打印告警）
        import sys as _sys
        print("[⚠️ intraday gate] output_gate 模块加载失败，盘中现价新鲜度闸门失效", file=_sys.stderr)
        return

    gate = gate_mod.check_intraday_price()
    if gate.get("status") == "BLOCK":
        raise RuntimeError(
            "🔴 盘中现价新鲜度闸门拦截: " + gate.get("summary", "现价数据疑似过期，禁止生成报告")
        )
    # PASS 时静默通过，不打断 pipeline 输出

# ══════════════════════════════════════════════════════════════
# 第零层：配置
# ══════════════════════════════════════════════════════════════

# 策略池分组（与 AGENT.md /开火 模板完全对齐）
STRATEGY_GROUPS = {
    "offense_us": {
        "title": "美股进攻候选",
        "tickers": ["QQQ", "IVV", "MUFG", "BOTZ"],
        "columns": ["排名", "标的", "现价", "C4", "距C4", "MACD BAR", "加仓过热", "机会得分", "开火"],
    },
    "offense_cn": {
        "title": "A股进攻候选（仅牛市）",
        "tickers": ["512100", "513180", "588000", "510500"],
        "columns": ["排名", "标的", "现价", "MA5", "距MA5", "牛市", "加仓过热", "机会得分", "开火"],
    },
    "fixed_layer": {
        "title": "固定层",
        "tickers": ["VTI", "VEA"],
        "columns": ["排名", "标的", "现价", "买入区间", "距区间", "加仓过热", "机会得分", "开火"],
    },
    "golden_shield": {
        "title": "黄金（金盾豁免）",
        "tickers": ["IAU", "518880"],
        "columns": ["标的", "现价", "MA40方向", "MACD", "RSI", "开火"],
    },
    "momentum": {
        "title": "独立动量",
        "tickers": ["FLIN", "SMIN", "EWY", "VNM"],
        "columns": ["排名", "标的", "现价", "MACD BAR", "距MA20", "加仓过热", "机会得分", "开火"],
    },
    "panic_dip": {
        "title": "SMIN 恐慌抄底（轨道二）",
        "tickers_sections": [
            {"title": "SMIN 恐慌抄底（轨道二）", "tickers": ["SMIN"]},
            {"title": "VNM 恐慌抄底（轨道二）", "tickers": ["VNM"]},
            {"title": "EWY 恐慌抄底（轨道二）", "tickers": ["EWY"]},
        ],
    },
    "cane": {
        "title": "独立标的（厄尔尼诺驱动）",
        "tickers": ["CANE"],
    },
}

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

# 持仓数据（从 positions.json 加载）
def load_positions():
    try:
        with open(os.path.join(WORKSPACE, "scripts", "positions.json")) as f:
            return json.load(f)
    except:
        return {}

# ══════════════════════════════════════════════════════════════
# 第一层：运行流水线
# ══════════════════════════════════════════════════════════════

def run_pipeline(scope="all"):
    """跑完整流水线，返回结构化数据。
    
    2026-08-13 重构：subprocess 串行调用 → import 内联调用，
    消除 5 次 Python 冷启动（/开火 提速核心）。
    """
    # 内联加载模块（避免 subprocess 冷启动）
    md_mod = _load_module("market_data")
    re_mod = _load_module("route_engine")
    fs_mod = _load_module("fire_signal")
    mg_mod = _load_module("macro_gate")
    gs_mod = _load_module("game_state")

    # Step 1: market_data.py — fetch_all()
    if md_mod:
        market_data = md_mod.fetch_all()
    else:
        md = subprocess.run(
            ["python3", os.path.join(SCRIPT_DIR, "market_data.py")],
            capture_output=True, text=True, timeout=120
        )
        market_data = _parse_json(md.stdout)

    # Step 1.5: 🔴 盘中现价新鲜度闸门（2026-08-17 焊入 — 512100 ¥2.864 事故根因修复）
    # 盘中时段若缓存过期/现价=日线收盘价，直接中断 pipeline，禁止生成报告。
    # 此闸门在 fetch_all() 之后立即触发，LLM 无法跳过——只要跑脚本就必过闸。
    _enforce_intraday_gate()

    # Step 2: 格式桥接 — 扁平→嵌套（fire_signal.py 期望的格式）
    bridged = bridge_format(market_data)

    # Step 3: route_engine.py — route_all()（用原始 market_data 扁平格式）
    if re_mod:
        routes = re_mod.route_all(market_data)
    else:
        re_result = subprocess.run(
            ["python3", os.path.join(SCRIPT_DIR, "route_engine.py")],
            input=json.dumps(market_data), capture_output=True, text=True, timeout=30
        )
        routes = _parse_json(re_result.stdout)

    # Step 3.5: 路由注入到 bridged（fire_signal.py 需要 route 字段）
    for ticker, route_info in routes.items():
        if ticker in bridged.get("indicators", {}):
            bridged["indicators"][ticker]["route"] = route_info.get("route", "")

    # Step 4: fire_signal.py — compute_all_signals()
    if fs_mod:
        fire_signals = fs_mod.compute_all_signals(bridged)
    else:
        fs_result = subprocess.run(
            ["python3", os.path.join(SCRIPT_DIR, "fire_signal.py"), "--stdin"],
            input=json.dumps(bridged), capture_output=True, text=True, timeout=30
        )
        fire_signals = _parse_json(fs_result.stdout)

    # Step 5: macro_gate.py — assess_all()
    if mg_mod:
        macro = mg_mod.assess_all()
    else:
        mg_result = subprocess.run(
            ["python3", os.path.join(SCRIPT_DIR, "macro_gate.py")],
            capture_output=True, text=True, timeout=30
        )
        macro = _parse_json(mg_result.stdout)

    # Step 5.5: game_state.py — compute_from_bridged()
    game_bridged = {
        "macro": macro,
        "indicators": bridged.get("indicators", {})
    }
    if gs_mod:
        game_state = gs_mod.compute_from_bridged(game_bridged)
    else:
        gs_result = subprocess.run(
            ["python3", os.path.join(SCRIPT_DIR, "game_state.py"), "--bridged", json.dumps(game_bridged), "--json"],
            capture_output=True, text=True, timeout=30
        )
        game_state = _parse_json(gs_result.stdout)

    # Step 6: opportunity_scorer.py（逐策略池 — 内联调用 score_pool）
    scores = run_opportunity_scorer(market_data, routes)

    return {
        "market_data": market_data,
        "routes": routes,
        "fire_signals": fire_signals,
        "macro": macro,
        "game_state": game_state,
        "scores": scores,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _normalize_dir(d):
    """方向值统一规范化为箭头：market_data 产英文 up/down/flat → fire_signal 期望 ↑/↓/→"""
    if d is None:
        return None
    if d in ("↑", "↓", "→"):
        return d
    return {"up": "↑", "down": "↓", "flat": "→"}.get(d, d)


def bridge_format(market_data):
    """
    将 market_data.py 的扁平输出转为 fire_signal.py 期望的嵌套格式。
    
    market_data 输出: {"QQQ": {"price": 722.20, "ma40": 720.0, "ma40_dir": "up", ...}}
    fire_signal 期望: {"indicators": {"QQQ": {"indicators": {"MA40": {"value": 720.0, "direction": "↑"}, ...}}}}
    """
    indicators = {}
    for ticker, data in market_data.items():
        if ticker.startswith("_"):
            continue
        
        ind = {}
        # 均线
        for ma in [5, 20, 40, 60, 120, 150, 250]:
            key = f"ma{ma}"
            if key in data and data[key] is not None:
                ind[f"MA{ma}"] = {"value": data[key]}
        # MA方向
        for ma in [5, 20, 40, 60, 120, 150, 250]:
            dir_key = f"ma{ma}_dir"
            if dir_key in data and data[dir_key] is not None:
                ma_key = f"MA{ma}"
                if ma_key in ind:
                    ind[ma_key]["direction"] = _normalize_dir(data[dir_key])
                else:
                    ind[ma_key] = {"value": data.get(f"ma{ma}"), "direction": _normalize_dir(data[dir_key])}
        # EMA
        for ema in [50, 150]:
            key = f"ema{ema}"
            if key in data and data[key] is not None:
                ind[f"EMA{ema}"] = {"value": data[key]}
        # ATR
        if "atr14" in data and data["atr14"] is not None:
            ind["ATR14"] = {"value": data["atr14"]}
        if "atr_pct" in data:
            ind["ATR_PCT"] = {"value": data["atr_pct"]}
        # H20
        if "h20" in data and data["h20"] is not None:
            ind["H20"] = {"value": data["h20"]}
        # RSI
        if "rsi14" in data and data["rsi14"] is not None:
            ind["RSI14"] = {"value": data["rsi14"]}
        # MACD
        if "macd" in data and data["macd"] is not None:
            ind["MACD"] = data["macd"]
        # 成交量
        if "vol_ratio" in data:
            ind["VOL_RATIO"] = {"value": data["vol_ratio"]}
        if "vol_ma20" in data:
            ind["VOL_MA20"] = {"value": data["vol_ma20"]}
        # ADX
        if "adx14" in data and data["adx14"] is not None:
            ind["ADX14"] = {"value": data["adx14"]}
        # 20日回撤
        if "drawdown_20d" in data and data["drawdown_20d"] is not None:
            ind["DRAWDOWN_20D"] = {"value": data["drawdown_20d"]}
        # 乖离率
        for ma in [20, 40, 60, 150]:
            dev_key = f"dev_ma{ma}"
            if dev_key in data and data[dev_key] is not None:
                ind[f"DEV_MA{ma}"] = {"value": data[dev_key]}
        # MA40 5日变化率（金盾V1.6走平过渡态判定）
        if "ma40_5d_chg" in data and data["ma40_5d_chg"] is not None:
            ind["MA40_5D_CHG"] = {"value": data["ma40_5d_chg"]}
        # MA40 5日连续上翘天数（连续符号确认，独立于死区判定）
        if "ma40_5d_up_streak" in data and data["ma40_5d_up_streak"] is not None:
            ind["MA40_5D_UP_STREAK"] = {"value": data["ma40_5d_up_streak"]}
        
        # 市场分类
        market = "us" if ticker not in ["588000","513180","513910","510500","518880","512100","510880","159530","510300","159915","513770","159545"] else "cn"
        if ticker in ["CANE"]:
            market = "us"
        
        indicators[ticker] = {
            "symbol": ticker,
            "market": market,
            "price_realtime": data.get("price"),
            "close_tushare": data.get("price"),
            "change_pct": data.get("change_pct"),
            "indicators": ind,
        }
    
    return {
        "meta": {"version": "V1.0", "scope": "all"},
        "indicators": indicators,
    }


def run_opportunity_scorer(market_data, routes):
    """逐策略池跑机会打分 — 直接从 market_data 扁平格式提取特征"""
    scores = {}
    
    # 从 market_data 扁平格式构建特征字典
    all_features = {}
    for ticker, data in market_data.items():
        if ticker.startswith("_"):
            continue
        
        price = data.get("price")
        ma40 = data.get("ma40")
        ma60 = data.get("ma60")
        ma20 = data.get("ma20")
        atr14 = data.get("atr14")
        
        # 距MA40乖离
        div_ma40 = None
        if price and ma40 and ma40 > 0:
            div_ma40 = (price / ma40 - 1) * 100
        # 距MA60乖离
        div_ma60 = None
        if price and ma60 and ma60 > 0:
            div_ma60 = (price / ma60 - 1) * 100
        # 距MA20
        price_vs_ma20 = None
        if price and ma20 and ma20 > 0:
            price_vs_ma20 = (price / ma20 - 1) * 100
        
        # MACD
        macd = data.get("macd", {})
        macd_bar = macd.get("bar") if isinstance(macd, dict) else None
        # MACD方向判定
        bar_prev = macd.get("bar_prev", 0) if isinstance(macd, dict) else 0
        if macd_bar is not None:
            if macd_bar > 0 and (bar_prev or 0) <= 0:
                macd_direction = "rising"
            elif macd_bar < 0:
                macd_direction = "falling"
            else:
                macd_direction = "flat"
        else:
            macd_direction = "flat"
        
        # ATR比
        atr_ratio = None
        if price and atr14 and price > 0:
            atr_ratio = atr14 / price
        
        # 买入区间 gap_pct：从 route_engine 的 counterpunch/offensive 字段取
        gap_pct = None
        rt = routes.get(ticker, {})
        # 反击标的：counterpunch.diff_pct
        cp = rt.get("counterpunch", {})
        if cp and "diff_pct" in cp:
            gap_pct = -cp["diff_pct"]  # diff_pct 是正数=距区间上沿距离，gap_pct 是负数=距区间距离
        # 美股进攻/固定层：从 route_engine 的买入区间字段取
        for section in ["offensive", "fixed_layer"]:
            sec = rt.get(section, {})
            if sec and "diff_pct" in sec:
                gap_pct = -sec["diff_pct"]
                break
        
        # 路由状态
        route = rt.get("route", "")
        blocked = rt.get("blocked", False)
        
        # 冷却期、Sharpe、MA60方向
        cooldown_remaining = data.get("cooldown_remaining", 0)
        sharpe = data.get("sharpe", 0)
        ma60_dir = data.get("ma60_dir", "flat")
        price_vs_ma60 = None
        if price and ma60 and ma60 > 0:
            price_vs_ma60 = (price / ma60 - 1) * 100
        
        all_features[ticker] = {
            "gap_pct": gap_pct,
            "divergence_ma40": div_ma40,
            "divergence_ma60": div_ma60,
            "price_vs_ma20": price_vs_ma20,
            "macd_bar": macd_bar,
            "macd_direction": macd_direction,
            "atr_ratio": atr_ratio,
            "cooldown_remaining": cooldown_remaining,
            "sharpe": sharpe,
            "ma60_direction": ma60_dir,
            "price_vs_ma60": price_vs_ma60,
            "blocked": blocked,
            "blocked_reason": rt.get("blocked_reason", ""),
        }
    
    # 逐策略池调用 — 内联调用 score_pool（避免 3 次 subprocess 冷启动）
    sc_mod = _load_module("opportunity_scorer")
    for pool_name in ["counterpunch", "attack", "momentum"]:
        try:
            # 过滤出该策略池的标的
            pool_features = {}
            pool_targets = _get_pool_targets(pool_name)
            for ticker, feat in all_features.items():
                if ticker in pool_targets:
                    pool_features[ticker] = feat

            if not pool_features:
                scores[pool_name] = {"rankings": [], "pool": pool_name}
                continue

            if sc_mod:
                # 内联调用 score_pool，返回 [(ticker, score, detail), ...]
                results = sc_mod.score_pool(pool_name, pool_features)
                rankings = []
                for i, (ticker, score, detail) in enumerate(results):
                    entry = {
                        "rank": i + 1,
                        "ticker": ticker,
                        "name": sc_mod.STRATEGY_POOLS[pool_name]["targets"].get(ticker, {}).get("name", ticker),
                        "score": score,
                        "status": detail.get("status", "") if isinstance(detail, dict) else "",
                    }
                    rankings.append(entry)
                scores[pool_name] = {"pool": pool_name, "rankings": rankings}
            else:
                result = subprocess.run(
                    ["python3", os.path.join(SCRIPT_DIR, "opportunity_scorer.py"),
                     "--mode", pool_name, "--features", json.dumps(pool_features)],
                    capture_output=True, text=True, timeout=30
                )
                scores[pool_name] = _parse_json(result.stdout)
        except Exception as e:
            scores[pool_name] = {"error": str(e)[:200]}

    return scores


def _get_pool_targets(pool_name):
    """获取策略池标的列表（硬编码，与 opportunity_scorer.py 对齐）"""
    pools = {
        "counterpunch": {"513910", "512100", "588000", "510500", "510880", "159530", "BBJP", "VNM", "510300", "159915"},
        "attack": {"QQQ", "IVV", "MUFG", "BOTZ", "VNM", "513180"},
        "momentum": {"FLIN", "SMIN", "EWY"},
    }
    return pools.get(pool_name, set())


def _parse_json(s):
    """安全解析JSON，处理可能的警告输出"""
    s = s.strip()
    # 找第一个 { 或 [
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

def render_markdown(data, mode="full"):
    """渲染 /开火 Markdown。mode: full=全部, offense=仅进攻, counterpunch=仅反击"""
    macro = data["macro"]
    signals = data["fire_signals"]["signals"]
    mkt = data["market_data"]
    
    lines = []
    
    # ── 头部：大势确定性二维评估 ──
    lines.extend(_render_two_dim(macro, data.get("game_state")))
    lines.append("")
    
    # ── 标题 ──
    if mode == "offense":
        lines.append(f"# ⚔️ 进攻 — {datetime.now().strftime('%Y-%m-%d')}")
    elif mode == "counterpunch":
        lines.append(f"# 🛡️ 反击 — {datetime.now().strftime('%Y-%m-%d')}")
    else:
        lines.append(f"# 🔥 开火 — {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")
    
    # ── C3.1 宏观事件静默 ──
    lines.extend(_render_c31(macro))
    lines.append("")
    
    if mode in ("full", "counterpunch"):
        # ── 反击候选 ──
        lines.extend(_render_counterpunch(data["routes"], mkt, macro, data["scores"]))
    
    if mode in ("full", "offense"):
        # ── 美股进攻候选 ──
        lines.extend(_render_offense_us(signals, mkt, macro, data["scores"]))
        
        # ── A股进攻候选 ──
        lines.extend(_render_offense_cn(signals, mkt, macro, data["scores"]))
        
        # ── 固定层 ──
        lines.extend(_render_fixed_layer(signals, mkt, macro))
        
        # ── 黄金 ──
        lines.extend(_render_golden_shield(signals, mkt, macro))
        
        # ── 独立动量 ──
        lines.extend(_render_momentum(signals, mkt, macro, data["scores"]))
        
        # ── 独立标的（CANE） ──
        lines.extend(_render_cane(signals, mkt))
    
    if mode in ("full", "counterpunch"):
        # ── 恐慌抄底 ──
        lines.extend(_render_panic_dip(signals, mkt))
    
    # ── 证伪审计结论 ──
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(_render_falsification(data))
    
    return "\n".join(lines)


def _format_game_state_line(gs):
    """格式化博弈态一句话输出"""
    if not gs or gs.get("effect") is None:
        return "[待判定]"
    label = gs.get("label", "?")
    effect = gs.get("effect", 0)
    cap = (gs.get("cap") or 0) * 100
    return f"{label}（效用{effect:+d}）| 仓位硬上限: {cap:.0f}%"


def _render_two_dim(macro, game_state=None):
    """二维评估 + 博弈态"""
    us10y = macro.get("us10y", {})
    vix = macro.get("vix", {})
    dxy = macro.get("dxy", {})
    verdict = macro.get("verdict", {})
    
    us10y_val = us10y.get("value")
    us10y_label = us10y.get("label", "⚪")
    vix_val = vix.get("value") or "—"
    vix_label = vix.get("label", "⚪")
    dxy_val = dxy.get("value")
    dxy_label = dxy.get("label", "⚪")
    
    dxy_display = f"{dxy_val}" if dxy_val else "—"
    
    lines = [
        "## 大势确定性二维评估（r33.29）",
        "",
        "| 维度 | 🟢阈值 | 🟡阈值 | 🔴阈值 | 当前值 | 判定 |",
        "|:---|:---|:---|:---|:---:|:---:|",
        f"| 恐慌烈度 | VIX>35 | VIX≤20 | VIX 20-35 | {vix_val} | {vix_label} |",
        f"| 美元方向 | DXY MA20↓ | 走平 | DXY MA20↑ | {dxy_display} | {dxy_label} |",
        "",
        f"├── US10Y: {us10y_val}% {us10y_label} | C3.1: {'🔴静默中' if macro.get('c31_events',{}).get('in_silence') else '✅正常'}",
        f"├── 博弈态: {_format_game_state_line(game_state)}",
        f"└── 交叉裁决: [LLM补充]",
    ]
    return lines


def _render_c31(macro):
    """C3.1 宏观事件静默"""
    c31 = macro.get("c31_events", {})
    layered = macro.get("c31_layered", {})
    
    if not c31.get("in_silence"):
        return ["├── C3.1: ✅ 无宏观事件静默"]
    
    events = c31.get("events", [])
    event_strs = [f"{e['event']} {e['date']}" for e in events]
    
    lines = [
        f"├── 🔴 C3.1 宏观静默: {' / '.join(event_strs)}",
    ]
    for key, desc in layered.items():
        lines.append(f"│   └── {key}: {desc}")
    return lines


def _fmt_price(val, ticker="", kind="us"):
    """格式化价格"""
    if val is None:
        return "—"
    if isinstance(val, (int, float)):
        if kind == "cn":
            return f"¥{val:.4f}" if val < 100 else f"¥{val:.3f}"
        else:
            return f"${val:.2f}"
    return str(val)


def _fmt_pct(val):
    """格式化百分比"""
    if val is None:
        return "—"
    if isinstance(val, (int, float)):
        return f"{val:+.2f}%"
    return str(val)


def _get_signal(ticker, signals, strategy):
    """安全获取某标的某策略信号"""
    s = signals.get(ticker, {})
    if "strategies" in s:
        return s["strategies"].get(strategy, {})
    return s if s.get("strategy") == strategy else {}


def _render_counterpunch(routes, mkt, macro, scores):
    """反击候选表 — 直接从 route_engine 的 counterpunch 字段渲染"""
    # 反击标的清单
    tickers = ["513910", "512100", "588000", "510500", "510880", "159530", "BBJP", "VNM", "510300", "159915"]
    
    # C3.1 对港股反击的降级检查
    c31_hk = macro.get("c31_layered", {}).get("hk_counterpunch", "")
    hk_downgraded = c31_hk.startswith("🟡")
    
    # 从 scores 中获取反击池排名和得分
    cp_scores = scores.get("counterpunch", {})
    score_map = {}
    for r in cp_scores.get("rankings", []):
        score_map[r.get("ticker", "")] = r.get("score", "—")
    
    lines = [
        "## 反击候选",
        "",
        "| 排名 | 标的 | 现价 | 买入区间 | 距区间 | MACD BAR | 底部序列 | 加仓过热 | 机会得分 | 开火 |",
        "|:---:|:---|:---:|:---|:---:|:---|:---|:---|:---:|:---:|",
    ]
    
    # 收集数据行
    rows = []
    for ticker in tickers:
        rt = routes.get(ticker, {})
        cp = rt.get("counterpunch", {})
        md = mkt.get(ticker, {}) or {}
        
        if not cp:
            # 非反击路由（如 159530/512100 路由为 idle）
            continue
            
        price = md.get("price")
        buy_zone_high = cp.get("buy_zone_high")
        diff_pct = cp.get("diff_pct")  # 正数=距区间上沿
        triggered = cp.get("triggered", False)
        # r33.96 — r05 为布尔值（True=放行），非豁免标的改用底部序列过滤。
        r05 = cp.get("r05", True)
        r05_exempt = cp.get("r05_exempt", False)
        r05_filter = cp.get("r05_filter", "ma40_dir")
        r05_blocked = (not r05) and (not r05_exempt)

        # 底部序列状态（仅非豁免标的展示）
        bottom_seq = md.get("bottom_seq")
        bottom_stop_days = md.get("bottom_stop_days")

        # MACD BAR
        macd = md.get("macd", {})
        macd_bar = macd.get("bar") if isinstance(macd, dict) else None

        # 港股标的 C3.1 降级
        hk_tickers = {"513910", "BBJP", "VNM"}
        is_hk = ticker in hk_tickers

        # 开火判定
        if triggered and not r05_blocked:
            if is_hk and hk_downgraded:
                fire = "🟡降级"
            else:
                fire = "🟢"
        elif triggered and r05_blocked:
            fire = "⛔MA40未向上" if r05_filter == "ma40_dir" else "⛔底部序列"
        else:
            fire = "—"

        gap_s = f"{diff_pct:+.2f}%" if isinstance(diff_pct, (int, float)) else "—"
        macd_s = f"{macd_bar:+.3f}" if isinstance(macd_bar, (int, float)) else "—"

        # 过滤状态列（跟随 R0.5 过滤逻辑动态展示）
        if r05_exempt:
            seq_s = "豁免"
        elif r05_filter == "ma40_dir":
            seq_s = f"{'🟢' if r05 else '⛔'}MA40{'↑' if r05 else '↓'}"
        elif bottom_seq:
            seq_s = f"✅({bottom_stop_days}d前)" if isinstance(bottom_stop_days, (int, float)) else "✅"
        else:
            seq_s = "⏳等止跌"

        score = score_map.get(ticker)
        score_s = f"{score:+.2f}" if isinstance(score, (int, float)) else "—"

        rows.append((ticker, price, buy_zone_high, diff_pct, macd_bar, seq_s, "✅正常", fire, score))
    
    # 排序：按机会得分降序，无分按距区间近的排
    rows.sort(key=lambda r: (
        -r[7] if isinstance(r[7], (int, float)) else -999,
        r[3] if r[3] is not None else 999
    ))
    
    for i, (ticker, price, buy_zone, diff, macd_bar, seq_s, overheat, fire, score) in enumerate(rows, 1):
        price_s = _fmt_price(price, ticker, "cn" if ticker.isdigit() else "us")
        buy_s = f"≤{_fmt_price(buy_zone, ticker, 'cn' if ticker.isdigit() else 'us')}" if buy_zone else "—"
        gap_s = f"-{diff:.2f}%" if isinstance(diff, (int, float)) else "—"
        macd_s = f"{macd_bar:+.3f}" if isinstance(macd_bar, (int, float)) else "—"
        score_s = f"{score:+.2f}" if isinstance(score, (int, float)) else "—"
        lines.append(f"| {i} | {ticker} | {price_s} | {buy_s} | {gap_s} | {macd_s} | {seq_s} | {overheat} | {score_s} | {fire} |")
    
    lines.append("")
    return lines


def _render_offense_us(signals, mkt, macro, scores):
    """美股进攻候选表"""
    tickers = ["QQQ", "IVV", "MUFG", "BOTZ"]
    c31_blocked = macro.get("c31_layered", {}).get("us_offensive", "").startswith("⛔")
    
    # 从 scores 中获取排名和得分
    attack_scores = scores.get("attack", {})
    score_map = {}
    for r in attack_scores.get("rankings", []):
        score_map[r.get("ticker", "")] = r.get("score", "—")
    
    lines = [
        "## 美股进攻候选" + ("（⛔ C3.1锁死）" if c31_blocked else ""),
        "",
        "| 排名 | 标的 | 现价 | C4 | 距C4 | MACD BAR | 加仓过热 | 机会得分 | 开火 |",
        "|:---:|:---|:---:|:---|:---:|:---|:---|:---:|:---:|",
    ]
    
    # 收集数据行
    rows = []
    for ticker in tickers:
        sig = _get_signal(ticker, signals, "offense_us")
        if "error" in sig:
            rows.append((ticker, None, None, None, None, None, "❌", "—", None))
            continue
        
        price = (mkt.get(ticker, {}) or {}).get("price")
        c4 = sig.get("c4")
        gap = sig.get("gap_pct")
        macd = sig.get("conditions", {}).get("C1_below_MA20", {}).get("detail", {})
        macd_bar = "—"
        ind = (mkt.get(ticker, {}) or {})
        if "macd" in ind and ind["macd"]:
            macd_bar = ind["macd"].get("bar", ind["macd"].get("BAR", "—"))
        
        triggered = sig.get("triggered", False)
        fire = "⛔CPI静默" if c31_blocked else ("🟢" if triggered else "—")
        
        score = score_map.get(ticker)
        score_s = f"{score:+.2f}" if isinstance(score, (int, float)) else "—"
        
        rows.append((ticker, price, c4, gap, macd_bar, "✅正常", fire, score))
    
    # 排序：按机会得分降序（有分的排前面），无分按距C4近的排
    rows.sort(key=lambda r: (-r[7] if isinstance(r[7], (int, float)) else -999, abs(r[3]) if r[3] is not None else 999))
    
    for i, (ticker, price, c4, gap, macd_bar, overheat, fire, score) in enumerate(rows, 1):
        price_s = _fmt_price(price, ticker, "us")
        c4_s = _fmt_price(c4, ticker, "us") if c4 else "—"
        gap_s = _fmt_pct(gap)
        macd_s = f"{macd_bar:+.2f}" if isinstance(macd_bar, (int, float)) else str(macd_bar)
        score_s = f"{score:+.2f}" if isinstance(score, (int, float)) else "—"
        lines.append(f"| {i} | {ticker} | {price_s} | ≤{c4_s} | {gap_s} | {macd_s} | {overheat} | {score_s} | {fire} |")
    
    lines.append("")
    return lines


def _render_offense_cn(signals, mkt, macro, scores):
    """A股进攻候选表"""
    tickers = ["512100", "513180", "588000", "510500"]
    c31_exempt = macro.get("c31_layered", {}).get("a_offensive", "").startswith("✅")
    
    # 从 scores 中获取得分（反击池有A股，但进攻池 scorer 还没覆盖A股）
    # A股进攻目前没有独立的 scorer，暂用距MA5距离作为排序
    attack_scores = scores.get("attack", {})
    score_map = {}
    for r in attack_scores.get("rankings", []):
        score_map[r.get("ticker", "")] = r.get("score", "—")
    
    lines = [
        "## A股进攻候选（仅牛市）",
        "",
        "| 排名 | 标的 | 现价 | MA5 | 距MA5 | 牛市 | 加仓过热 | 机会得分 | 开火 |",
        "|:---:|:---|:---:|:---|:---:|:---|:---|:---:|:---:|",
    ]
    
    rows = []
    for ticker in tickers:
        sig = _get_signal(ticker, signals, "offense_cn")
        if "tracks" in sig:
            sig = sig["tracks"].get("ma5", {})
        
        price = (mkt.get(ticker, {}) or {}).get("price")
        ma5 = (mkt.get(ticker, {}) or {}).get("ma5")
        gap = None
        is_bull = sig.get("is_bull", False)
        
        if price and ma5:
            gap = round((price - ma5) / ma5 * 100, 2)
        
        fire = "—"
        if is_bull and gap is not None and abs(gap) <= 2.0:
            fire = "🟢"
        
        score = score_map.get(ticker)
        
        rows.append((ticker, price, ma5, gap, is_bull, "✅正常", fire, score))
    
    rows.sort(key=lambda r: (-r[7] if isinstance(r[7], (int, float)) else -999, abs(r[3]) if r[3] is not None else 999))
    
    for i, (ticker, price, ma5, gap, is_bull, overheat, fire, score) in enumerate(rows, 1):
        price_s = _fmt_price(price, ticker, "cn")
        ma5_s = _fmt_price(ma5, ticker, "cn") if ma5 else "—"
        gap_s = _fmt_pct(gap)
        bull_s = "🟢" if is_bull else "🔴"
        score_s = f"{score:+.2f}" if isinstance(score, (int, float)) else "—"
        lines.append(f"| {i} | {ticker} | {price_s} | {ma5_s} | {gap_s} | {bull_s} | {overheat} | {score_s} | {fire} |")
    
    lines.append("")
    return lines


def _render_fixed_layer(signals, mkt, macro):
    """固定层"""
    tickers = ["VTI", "VEA"]
    
    lines = [
        "## 固定层",
        "",
        "| 排名 | 标的 | 现价 | 买入区间 | 距区间 | 加仓过热 | 开火 |",
        "|:---:|:---|:---:|:---|:---:|:---|:---:|",
    ]
    
    for i, ticker in enumerate(tickers, 1):
        sig = _get_signal(ticker, signals, "fixed_layer")
        price = (mkt.get(ticker, {}) or {}).get("price")
        zone = sig.get("buy_zone", {})
        lower = zone.get("lower")
        upper = zone.get("upper")
        in_zone = sig.get("in_zone", False)
        gap = sig.get("gap_pct")
        
        price_s = _fmt_price(price, ticker, "us")
        if lower and upper:
            zone_s = f"[${lower:.2f}, ${upper:.2f})"
        else:
            zone_s = "—"
        gap_s = _fmt_pct(gap)
        fire = "⛔高于区间" if gap is not None and gap > 0 else ("🟢" if in_zone else "⛔高于区间")
        
        lines.append(f"| {i} | {ticker} | {price_s} | {zone_s} | {gap_s} | ✅正常 | {fire} |")
    
    lines.append("")
    return lines


def _render_golden_shield(signals, mkt, macro):
    """黄金金盾"""
    tickers = ["IAU", "518880"]
    
    lines = [
        "## 黄金（金盾V1.6豁免C3.1）",
        "",
        "| 标的 | 现价 | MA40方向 | MACD | RSI | 开火 |",
        "|:---|:---:|:---|:---|:---:|:---:|",
    ]
    
    for ticker in tickers:
        sig = _get_signal(ticker, signals, "golden_shield")
        price = (mkt.get(ticker, {}) or {}).get("price")
        ma40_dir = "—"
        macd_str = "—"
        rsi = "—"
        
        ind = mkt.get(ticker, {})
        if ind:
            ma40_dir = ind.get("ma40_dir", "—")
            # 连续上翘天数（方案B：独立于死区判定）
            up_streak = sig.get("ma40_5d_up_streak")
            if up_streak is not None:
                streak_tag = "↑翘" if up_streak >= 3 else ("→" if up_streak > 0 else "↓跌")
                ma40_dir = f"{ma40_dir}/{streak_tag}{up_streak}日"
            if ind.get("macd"):
                bar_val = ind['macd'].get('bar', ind['macd'].get('BAR', 0))
                bar_str = f"{bar_val:+.2f}" if isinstance(bar_val, (int, float)) else str(bar_val)
                macd_str = f"BAR{bar_str}"
            rsi = ind.get("rsi14", "—")
        
        orthodox = sig.get("orthodox_triggered", False)
        transitional = sig.get("transitional_triggered", False)
        fire = "—"
        if orthodox:
            fire = "🟢满仓"
        elif transitional:
            fire = "🟡走平过渡⅓"
        else:
            # 检查C2（MA40方向）与C1（双顺风）
            c1 = sig.get("conditions", {}).get("C1_dual_tailwind", {})
            c2 = sig.get("conditions", {}).get("C2_MA40_up", {})
            if not c2.get("met", True):
                fire = "⛔ C2 MA40未翻多"
            elif not c1.get("met", True):
                fire = "⛔ C1双顺风未满足"
        
        kind = "us" if ticker == "IAU" else "cn"
        price_s = _fmt_price(price, ticker, kind)
        lines.append(f"| {ticker} | {price_s} | {ma40_dir} | {macd_str} | {rsi} | {fire} |")
    
    lines.append("")
    return lines


def _render_momentum(signals, mkt, macro, scores):
    """独立动量"""
    tickers = ["FLIN", "SMIN", "EWY", "VNM"]
    
    # 从 scores 中获取得分
    momentum_scores = scores.get("momentum", {})
    score_map = {}
    for r in momentum_scores.get("rankings", []):
        score_map[r.get("ticker", "")] = r.get("score", "—")
    
    lines = [
        "## 独立动量",
        "",
        "| 排名 | 标的 | 现价 | MACD BAR | 距MA20 | 加仓过热 | 机会得分 | 开火 |",
        "|:---:|:---|:---:|:---:|:---|:---|:---:|:---:|",
    ]
    
    rows = []
    for ticker in tickers:
        sig = _get_signal(ticker, signals, "momentum")
        price = (mkt.get(ticker, {}) or {}).get("price")
        macd_bar = "—"
        gap_ma20 = None
        
        ind = mkt.get(ticker, {})
        if ind:
            if ind.get("macd"):
                macd_bar = ind["macd"].get("bar", ind["macd"].get("BAR", "—"))
            ma20 = ind.get("ma20")
            if price and ma20:
                gap_ma20 = round((price - ma20) / ma20 * 100, 2)
        
        triggered = sig.get("triggered", False)
        fire = "🟢" if triggered else "⛔价>MA20" if gap_ma20 is not None and gap_ma20 > 0 else "—"
        
        score = score_map.get(ticker)
        
        rows.append((ticker, price, macd_bar, gap_ma20, "✅正常", fire, score))
    
    rows.sort(key=lambda r: (-r[6] if isinstance(r[6], (int, float)) else -999, abs(r[3]) if r[3] is not None else 999))
    
    for i, (ticker, price, macd_bar, gap_ma20, overheat, fire, score) in enumerate(rows, 1):
        price_s = _fmt_price(price, ticker, "us")
        macd_s = f"{macd_bar:+.2f}" if isinstance(macd_bar, (int, float)) else str(macd_bar)
        gap_s = _fmt_pct(gap_ma20)
        score_s = f"{score:+.2f}" if isinstance(score, (int, float)) else "—"
        lines.append(f"| {i} | {ticker} | {price_s} | {macd_s} | {gap_s} | {overheat} | {score_s} | {fire} |")
    
    lines.append("")
    return lines


def _render_panic_dip(signals, mkt):
    """恐慌抄底（轨道二）"""
    sections = [
        ("SMIN", "SMIN 恐慌抄底（轨道二）", -0.15),
        ("VNM", "VNM 恐慌抄底（轨道二）", -0.20),
        ("EWY", "EWY 恐慌抄底（轨道二）", -0.20),
    ]
    
    lines = []
    for ticker, title, threshold in sections:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| 标的 | 现价 | 20日回撤 | 买入阈值 | 加仓过热 | 开火 |")
        lines.append("|:---|:---:|:---:|:---|:---|:---:|")
        
        price = (mkt.get(ticker, {}) or {}).get("price")
        dd_pct = (mkt.get(ticker, {}) or {}).get("drawdown_20d")  # 已是百分比值（如 −2.51 表示 −2.51%）
        
        dd_str = _fmt_pct(dd_pct)
        threshold_pct = threshold * 100  # 转百分比（如 −0.20 → −20）
        threshold_str = f"<{threshold_pct:.0f}%"
        
        fire = "—"
        if dd_pct is not None and dd_pct <= threshold_pct:
            fire = "🟢"
        else:
            fire = "⛔远未触发"
        
        price_s = _fmt_price(price, ticker, "us")
        lines.append(f"| {ticker} | {price_s} | {dd_str} | {threshold_str} | ✅正常 | {fire} |")
        lines.append("")
    
    return lines


def _render_falsification(data):
    """生成证伪审计一句话结论"""
    macro = data.get("macro", {})
    signals = data.get("fire_signals", {}).get("signals", {})
    
    parts = []
    
    # 宏观环境
    vix = macro.get("vix", {}).get("value")
    us10y = macro.get("us10y", {}).get("value")
    c31 = macro.get("c31", {})
    c31_active = c31.get("active", False)
    c31_events = c31.get("events", [])
    
    # 统计各策略池开火状态
    counterpunch_fire = 0
    cp_tickers = {"513910", "512100", "588000", "510500", "510880", "159530", "BBJP", "VNM", "510300", "159915"}
    offense_us_tickers = {"QQQ", "IVV", "MUFG", "BOTZ"}
    offense_cn_tickers = {"512100", "513180", "588000", "510500"}
    momentum_tickers = {"FLIN", "SMIN", "EWY"}
    
    for ticker, sig_list in signals.items():
        if not sig_list or not isinstance(sig_list, list):
            continue
        if len(sig_list) == 0:
            continue
        sig = sig_list[0] if isinstance(sig_list[0], dict) else sig_list
        if ticker in cp_tickers:
            if isinstance(sig, dict) and sig.get("action") == "fire":
                counterpunch_fire += 1
    
    # 构建结论
    if c31_active and c31_events:
        events_str = "/".join(c31_events[:2])
        parts.append(f"CPI静默中（{events_str}），美股进攻/动量锁死，A股豁免")
    
    if counterpunch_fire > 0:
        parts.append(f"{counterpunch_fire}标反击开火")
    else:
        parts.append("无反击开火信号")
    
    if vix is not None and vix <= 20:
        parts.append(f"VIX={vix}自满风险")
    elif vix is not None and vix > 35:
        parts.append(f"VIX={vix}危机模式")
    
    if us10y is not None and us10y >= 4.5:
        parts.append(f"US10Y={us10y}%机会区间")
    
    conclusion = " | ".join(parts) if parts else "无特殊风险信号"
    return f"⚠️ 证伪审计: {conclusion}。"


def _render_cane(signals, mkt):
    """独立标的 CANE — 厄尔尼诺左侧分批框架"""
    ticker = "CANE"
    cane_mkt = mkt.get(ticker, {}) or {}
    price = cane_mkt.get("price")
    
    lines = [
        "## 独立标的（厄尔尼诺驱动）",
        "",
        "| 标的 | 现价 | 滚动峰值 | 回撤 | 距上批 | 批次 | 开火 |",
        "|:---|:---:|:---:|:---:|:---:|:---|:---:|",
    ]
    
    # 从 positions.json 读取持仓
    import subprocess as _sp
    pos_result = _sp.run(
        ["python3", os.path.join(SCRIPT_DIR, "read_positions.py"), "--ticker", "CANE"],
        capture_output=True, text=True, timeout=10
    )
    pos_data = json.loads(pos_result.stdout) if pos_result.stdout.strip() else {}
    shares = pos_data.get("shares", 0)
    cost = pos_data.get("cost", 0)
    
    # 从 MEMORY.md 提取 CANE 框架参数
    peak = None
    last_batch_date = None
    batch_num = None
    total_batches = 5
    
    memory_path = os.path.join(os.path.dirname(SCRIPT_DIR), "MEMORY.md")
    try:
        with open(memory_path) as f:
            memory_text = f.read()
        # 提取峰值
        import re
        peak_match = re.search(r'峰值\$?([\d.]+)\s*\(', memory_text)
        if peak_match:
            peak = float(peak_match.group(1))
        # 提取批次
        batch_match = re.search(r'第(\d)\+?(\d)?批', memory_text)
        if batch_match:
            batch_num = int(batch_match.group(1)) + (1 if batch_match.group(2) else 0)
        # 提取最近批次日期
        date_match = re.search(r'(\d+/\d+)\s*(?:共振|加仓|建仓)', memory_text)
        if date_match:
            last_batch_date = date_match.group(1)
    except:
        pass
    
    # 计算当前回撤
    peak_str = f"${peak:.2f}" if peak else "—"
    drawdown_str = "—"
    if peak and price:
        dd = (price / peak - 1) * 100
        drawdown_str = f"{dd:+.1f}%" if dd > 0 else f"{dd:.1f}%"
    
    # 距上批天数
    days_str = "—"
    if last_batch_date:
        try:
            from datetime import datetime
            batch_dt = datetime.strptime(f"2026/{last_batch_date}", "%Y/%m/%d")
            days_since = (datetime.now() - batch_dt).days
            days_str = f"{days_since}天"
        except:
            pass
    
    # 批次进度
    batch_str = f"第{batch_num}/{total_batches}批" if batch_num else "—"
    
    # 开火判定
    fire = "⚪等待"
    if peak and price and batch_num:
        threshold = peak * 0.95  # -5% 回撤触发
        if price <= threshold and batch_num < total_batches:
            fire = "🟢"
    
    price_s = f"${price:.2f}" if price else "—"
    lines.append(f"| {ticker} | {price_s} | {peak_str} | {drawdown_str} | {days_str} | {batch_str} | {fire} |")
    lines.append("")
    
    return lines


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="/开火 报告渲染器 V1.0")
    parser.add_argument("--json", action="store_true", help="输出JSON而非Markdown")
    parser.add_argument("--scope", choices=["us", "cn", "all"], default="all", help="标的范围")
    parser.add_argument("--mode", choices=["full", "offense", "counterpunch"], default="full",
                        help="报告模式: full=完整/开火, offense=仅进攻, counterpunch=仅反击")
    args = parser.parse_args()
    
    data = run_pipeline(args.scope)
    
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(render_markdown(data, mode=args.mode))


if __name__ == "__main__":
    main()
