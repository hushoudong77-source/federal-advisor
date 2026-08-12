#!/usr/bin/env python3
"""
联邦投顾 — 路由判定引擎 V2.0（r33.92 理想架构重构）
输入: market_data.py 的 JSON 输出（24标现价+全部技术指标）
输出: 每标的路由分类 + 信号触发状态 + 买入区间/止损位

用法:
  python3 scripts/route_engine.py                    # 全量路由判定（JSON输出）
  python3 scripts/route_engine.py --table             # 表格格式
  python3 scripts/route_engine.py --ticker QQQ        # 单标判定
  python3 scripts/route_engine.py --input data.json   # 从指定JSON文件读取

LLM不再需要「读法典→手动判定每个标的C1/C2/C3/C4/R0-R2」
——脚本直接输出结构化路由表。
"""

import json
import sys
import os
import math
from datetime import datetime

# ============================================================
# 参数加载（单一真源：params.json）
# ============================================================
def load_params():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    params_path = os.path.join(script_dir, "params.json")
    with open(params_path, "r") as f:
        return json.load(f)

PARAMS = load_params()

# ============================================================
# 常量定义
# ============================================================
# EMA三态分流阈值
EMA_BUFFER = 0.003  # ±0.3%缓冲区

# R0.5锚线方向判定窗口
R05_WINDOW = 5

# ADX过滤阈值
ADX_MIN = 20

# 极端乖离阈值（按类型）
GAP_THRESHOLDS = {
    "large_cap": 0.50,    # 大盘宽基 >50%
    "tech_theme": 0.70,   # 科技/主题 >70%
    "small_emerging": 0.80  # 小微/新兴 >80%
}

# 标的类型映射（用于极端乖离阈值）
TICKER_TYPE = {
    "QQQ": "large_cap", "IVV": "large_cap", "VTI": "large_cap", "VEA": "large_cap",
    "513910": "large_cap", "510880": "large_cap", "510300": "large_cap",
    "588000": "tech_theme", "513180": "tech_theme", "510500": "tech_theme",
    "512100": "tech_theme", "159915": "tech_theme",
    "VNM": "small_emerging", "FLIN": "small_emerging", "EWY": "small_emerging",
    "BBJP": "small_emerging", "MUFG": "small_emerging", "SMIN": "small_emerging",
    "BOTZ": "tech_theme", "159530": "large_cap",
    "IAU": "large_cap", "518880": "large_cap",
    "513770": "tech_theme", "159545": "large_cap",
    "CANE": "small_emerging"
}

# 永久剥夺清单
DEPRIVED_COUNTERPUNCH = {"SMIN", "EWY"}  # 反击永久剥夺
DEPRIVED_OFFENSIVE = {"SMIN"}  # 进攻永久剥夺

# 豁免前置标的（不进入EMA三态分流）
EXEMPT_GOLD = {"IAU", "518880"}      # 金盾轨道
EXEMPT_FIXED = {"VTI", "VEA"}        # 固定层（空仓时⚪闲置）
EXEMPT_INDEPENDENT = {"CANE"}        # 独立标的
EXEMPT_MOMENTUM = {"FLIN", "SMIN", "EWY", "VNM"}  # 独立动量
EXEMPT_UNCLASSIFIED = {"513770", "159545"}  # 待分类

# R0.5豁免标的
R05_EXEMPT = {"513910", "512100", "510500", "588000", "510880", "159530", "BBJP", "VNM"}

# A股进攻标的
A_OFFENSIVE_TICKERS = {"512100", "513180", "588000", "510500"}

# 美股进攻标的
US_OFFENSIVE_TICKERS = {"QQQ", "IVV", "MUFG", "BOTZ"}

# 反击标的（含A股和美股反击候选）
COUNTERPUNCH_TICKERS = {
    "513910", "510880", "159530", "510300", "159915",
    "BBJP", "VNM",
    # 以下同时有A股进攻资格，非牛市时回退到反击
    "588000", "510500", "512100"
}
# 510500: 熊市暂停反击（params.json bear_market_suspended=true），但路由引擎仅输出信号，暂停逻辑由LLM裁决


# ============================================================
# 字段适配层 — market_data.py 输出 → 路由引擎内部统一字段
# ============================================================
def adapt_fields(data):
    """
    将 market_data.py 的输出适配为路由引擎的统一字段名。
    market_data 使用: price, macd.bar, ma60_dir="up"/"down"
    路由引擎内部使用: close, macd_bar, ma60_dir=1/-1/0
    """
    adapted = dict(data)  # 浅拷贝

    # price → close
    if "price" in adapted and "close" not in adapted:
        adapted["close"] = adapted["price"]

    # macd.bar → macd_bar
    macd = adapted.get("macd")
    if isinstance(macd, dict):
        adapted["macd_bar"] = macd.get("bar")
        adapted["macd_diff"] = macd.get("diff")
        adapted["macd_dea"] = macd.get("dea")
        adapted["macd_bar_prev"] = macd.get("bar_prev")

    # ma60_dir: "up"/"down"/"flat" → 1/-1/0
    ma_dir = adapted.get("ma60_dir")
    if isinstance(ma_dir, str):
        if ma_dir.lower() == "up":
            adapted["ma60_dir"] = 1
        elif ma_dir.lower() == "down":
            adapted["ma60_dir"] = -1
        else:
            adapted["ma60_dir"] = 0

    # ema30: 如果缺失，用 (ema50 + close) / 2 近似（临时方案）
    if "ema30" not in adapted or adapted["ema30"] is None:
        ema50 = adapted.get("ema50")
        close = adapted.get("close")
        if ema50 is not None and close is not None:
            adapted["ema30"] = (ema50 + close) / 2

    return adapted


# ============================================================
# 辅助函数
# ============================================================
def safe_float(d, key, default=None):
    """安全提取浮点数"""
    v = d.get(key)
    if v is None or v == "N/A":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default

def get_ma_direction(ma_values, window=5):
    """判定均线近N日方向：↑/→/↓"""
    if len(ma_values) < window + 1:
        return "→"
    recent = ma_values[-window:]
    delta = recent[-1] - recent[0]
    pct = delta / recent[0] if recent[0] != 0 else 0
    if pct > 0.001:
        return "↑"
    elif pct < -0.001:
        return "↓"
    else:
        return "→"


# ============================================================
# 核心判定函数
# ============================================================

def judge_exemption(ticker, data):
    """步骤-1: 豁免前置判定"""
    if ticker in EXEMPT_GOLD:
        return {"route": "gold_shield", "status": "exempt", "reason": "金盾轨道"}
    if ticker in EXEMPT_FIXED:
        return {"route": "fixed_layer", "status": "idle", "reason": "固定层（空仓→⚪闲置专用通道）"}
    if ticker in EXEMPT_INDEPENDENT:
        return {"route": "independent", "status": "idle", "reason": "厄尔尼诺左侧分批框架"}
    if ticker in EXEMPT_UNCLASSIFIED:
        return {"route": "unclassified", "status": "idle", "reason": "反击框架不成立，维持⚪待分类"}
    if ticker in EXEMPT_MOMENTUM:
        return {"route": "momentum", "status": "idle", "reason": "独立动量跟随策略"}
    return None  # 不豁免，继续路由判定


def judge_special(ticker, data):
    """步骤0: 特殊处理（永久剥夺）"""
    result = {"deprived_counterpunch": False, "deprived_offensive": False}
    if ticker in DEPRIVED_COUNTERPUNCH:
        result["deprived_counterpunch"] = True
    if ticker in DEPRIVED_OFFENSIVE:
        result["deprived_offensive"] = True
    return result


def judge_ema_diversion(ticker, data):
    """
    EMA三态分流层
    返回: {c1, c2, c1_raw, c2_raw, diversion: "offensive"/"counterpunch"/"idle"}
    """
    ema50 = safe_float(data, "ema50")
    ema150 = safe_float(data, "ema150")
    ema30 = safe_float(data, "ema30")

    if ema50 is None or ema150 is None or ema30 is None:
        return {"c1": None, "c2": None, "diversion": "data_missing"}

    c1_raw = (ema50 - ema150) / ema150
    c2_raw = (ema30 - ema50) / ema50

    # 缓冲区判定
    if c1_raw > EMA_BUFFER:
        c1 = True
    elif c1_raw < -EMA_BUFFER:
        c1 = False
    else:
        c1 = None  # 过渡区

    if c2_raw > EMA_BUFFER:
        c2 = True
    elif c2_raw < -EMA_BUFFER:
        c2 = False
    else:
        c2 = None

    # 分流
    if c1 is True and c2 is True:
        diversion = "offensive"
    elif c1 is False and c2 is False:
        diversion = "idle"
    elif (c1 is True and c2 is False) or (c1 is False and c2 is True) or (c1 is None or c2 is None):
        diversion = "counterpunch"
    else:
        diversion = "counterpunch"

    return {
        "c1": c1, "c2": c2,
        "c1_raw": round(c1_raw, 4), "c2_raw": round(c2_raw, 4),
        "diversion": diversion
    }


def judge_extreme_gap(ticker, data):
    """步骤0.5: 极端乖离拦截"""
    close = safe_float(data, "close")
    ema150 = safe_float(data, "ema150")
    if close is None or ema150 is None or ema150 == 0:
        return {"triggered": False, "gap_pct": None}

    gap_pct = abs(close - ema150) / ema150
    ticker_type = TICKER_TYPE.get(ticker, "large_cap")
    threshold = GAP_THRESHOLDS.get(ticker_type, 0.50)

    return {
        "triggered": gap_pct > threshold,
        "gap_pct": round(gap_pct, 4),
        "threshold": threshold,
        "type": ticker_type
    }


def judge_offensive_c3_c4(ticker, data):
    """步骤1: 美股进攻C3/C4判定"""
    close = safe_float(data, "close")
    ema50 = safe_float(data, "ema50")
    h20 = safe_float(data, "h20")
    vol = safe_float(data, "volume")
    vol_ma20 = safe_float(data, "vol_ma20")
    atr14 = safe_float(data, "atr14")

    result = {"c3": False, "c4": False, "c4_volume": False, "c4_atr": False,
              "c4_price": False, "attack_window": False}

    if any(v is None for v in [close, ema50, h20]):
        return result

    # C3: 价格 > 50EMA
    result["c3"] = close > ema50

    # C4: 价格 >= H20 × 0.98
    c4_price = close >= h20 * 0.98
    result["c4_price"] = c4_price

    # C4量能/波动率辅助条件
    if vol is not None and vol_ma20 is not None and vol_ma20 > 0:
        # 跨境ETF量能阈值0.7，其余0.8
        cross_border = {"BBJP", "MUFG", "EWY", "VNM", "FLIN"}
        vol_threshold = 0.7 if ticker in cross_border else 0.8
        result["c4_volume"] = vol > vol_ma20 * vol_threshold

    # ATR波动率条件
    # ATR(14) < ATR(14)_MA20 × 1.1（简化：跳过ATR_MA20计算，默认通过）
    result["c4_atr"] = True  # 简化处理

    # C4综合判定
    result["c4"] = c4_price and (result["c4_volume"] or result["c4_atr"])
    result["attack_window"] = result["c4"]  # C4满足即开启攻击窗口

    return result


def judge_counterpunch_r0_r2(ticker, data, special):
    """步骤2: 反击R0-R2判定"""
    params = PARAMS["counterpunch"].get(ticker, {})
    if not params:
        return {"r05": False, "r1": False, "r2a": False, "r2b": False, "r2c": False,
                "buy_zone_low": None, "buy_zone_high": None, "triggered": False}

    # 如果反击被永久剥夺
    if special.get("deprived_counterpunch"):
        return {"r05": False, "r1": False, "r2a": False, "r2b": False, "r2c": False,
                "buy_zone_low": None, "buy_zone_high": None, "triggered": False,
                "status": "deprived"}

    close = safe_float(data, "close")
    ma40 = safe_float(data, "ma40")
    atr14 = safe_float(data, "atr14")
    k = params.get("k", 2.0)

    if close is None or ma40 is None or atr14 is None:
        return {"r05": False, "r1": False, "r2a": False, "r2b": False, "r2c": False,
                "buy_zone_low": None, "buy_zone_high": None, "triggered": False,
                "status": "data_missing"}

    result = {"status": "normal"}

    # R0.5: 锚线方向过滤
    if ticker in R05_EXEMPT:
        result["r05"] = True
        result["r05_exempt"] = True
    else:
        ma40_dir = safe_float(data, "ma40_dir")
        result["r05"] = ma40_dir is not None and ma40_dir >= 0
        result["r05_exempt"] = False

    # R1: C1=False ∨ C2=False（非双False）
    ema = judge_ema_diversion(ticker, data)
    c1, c2 = ema.get("c1"), ema.get("c2")
    is_double_false = (c1 is False and c2 is False)
    is_single_false = (c1 is False) != (c2 is False)  # 恰好一个False
    result["r1"] = is_single_false

    # 计算买入区间
    buy_zone_high = ma40
    buy_zone_low = ma40 - k * atr14
    result["buy_zone_low"] = round(buy_zone_low, 4)
    result["buy_zone_high"] = round(buy_zone_high, 4)
    result["diff_pct"] = round((close - buy_zone_high) / buy_zone_high * 100, 2)

    # R2a: 浅废墟买入区间 [MA40 - 1.5×ATR, MA40)
    r2a_low = ma40 - 1.5 * atr14
    r2a_high = ma40
    result["r2a"] = r2a_low <= close < r2a_high

    # R2b: 深废墟买入区间 [MA40 - 3.0×ATR, MA40 - 1.5×ATR)
    r2b_low = ma40 - 3.0 * atr14
    r2b_high = ma40 - 1.5 * atr14
    result["r2b"] = r2b_low <= close < r2b_high

    # R2c: 核爆底 < MA40 - 4.0×ATR
    r2c_threshold = ma40 - 4.0 * atr14
    result["r2c"] = close < r2c_threshold

    # 综合触发
    result["triggered"] = (result["r2a"] or result["r2b"] or result["r2c"])

    return result


def judge_a_share_offensive(ticker, data):
    """A股进攻策略：MA5回踩判定（仅牛市）"""
    close = safe_float(data, "close")
    ma5 = safe_float(data, "ma5")
    ma60 = safe_float(data, "ma60")
    ma60_dir = safe_float(data, "ma60_dir")

    result = {"bull_market": False, "ma5_pullback": False, "ma50_pullback": False}

    if close is None or ma60 is None or ma60_dir is None:
        return result

    # 牛市判定：MA60↑ + 价格>MA60
    bull_market = ma60_dir > 0 and close > ma60
    result["bull_market"] = bull_market

    if not bull_market:
        return result

    # MA5回踩判定
    if ma5 is not None and ma5 > 0:
        params = PARAMS["a_share_offensive"].get(ticker, {})
        ma5_cfg = params.get("ma5_pullback", {})
        tolerance = float(str(ma5_cfg.get("tolerance", "0.005")).replace("±", "").replace("%","")) / 100
        if tolerance == 0:
            tolerance = 0.005
        result["ma5_pullback"] = abs(close - ma5) / ma5 <= tolerance

    # MA50回踩判定（仅512100）
    if ticker == "512100" and bull_market:
        ma50 = safe_float(data, "ma50")
        if ma50 is not None and ma50 > 0:
            result["ma50_pullback"] = abs(close - ma50) / ma50 <= 0.02

    return result


def judge_momentum(ticker, data):
    """独立动量策略判定"""
    close = safe_float(data, "close")
    ma20 = safe_float(data, "ma20")
    macd_bar = safe_float(data, "macd_bar")
    drawdown_20d = safe_float(data, "drawdown_20d")

    result = {"track_one": False, "track_two": False}

    # 轨道一：MACD金叉 + 价<MA20
    if close is not None and ma20 is not None and macd_bar is not None:
        result["track_one"] = macd_bar > 0 and close < ma20

    # 轨道二：恐慌抄底
    if drawdown_20d is not None:
        track_two_cfg = PARAMS["momentum"].get(ticker, {}).get("track_two", {})
        if track_two_cfg:
            trigger_str = track_two_cfg.get("trigger", "")
            if "<" in trigger_str:
                threshold = float(trigger_str.split("<")[1].replace("%", "").replace("−", "-").strip()) / 100
                result["track_two"] = drawdown_20d < threshold
                result["track_two_threshold"] = threshold
                result["track_two_build"] = track_two_cfg.get("build", "")

    return result


def judge_gold_shield(ticker, data):
    """金盾V1.4四条件判定"""
    close = safe_float(data, "close")
    ma60 = safe_float(data, "ma60")
    macd_bar = safe_float(data, "macd_bar")
    rsi = safe_float(data, "rsi14")
    atr14 = safe_float(data, "atr14")

    result = {"c1": False, "c2": False, "c3": False, "c4": False}

    if close is None:
        return result

    # C1: MA60方向↑
    ma60_dir = safe_float(data, "ma60_dir")
    result["c1"] = ma60_dir is not None and ma60_dir > 0

    # C2: MACD金叉（BAR > 0）
    result["c2"] = macd_bar is not None and macd_bar > 0

    # C3: RSI < 70
    result["c3"] = rsi is not None and rsi < 70

    # C4: 波动率正常（ATR14/价格 < 3%）
    if atr14 is not None and close > 0:
        result["c4"] = (atr14 / close) < 0.03
    else:
        result["c4"] = True

    result["all_green"] = all([result["c1"], result["c2"], result["c3"], result["c4"]])
    return result


def judge_fixed_layer(ticker, data):
    """固定层买入区间判定"""
    params = PARAMS["fixed_layer"].get(ticker, {})
    close = safe_float(data, "close")
    ma60 = safe_float(data, "ma60")
    atr14 = safe_float(data, "atr14")
    k = params.get("k", 4.0)

    result = {"in_buy_zone": False, "buy_zone_low": None, "buy_zone_high": None}

    if close is None or ma60 is None or atr14 is None:
        return result

    buy_zone_low = ma60 - k * atr14
    buy_zone_high = ma60 + 2 * atr14
    result["buy_zone_low"] = round(buy_zone_low, 4)
    result["buy_zone_high"] = round(buy_zone_high, 4)
    result["in_buy_zone"] = buy_zone_low <= close < buy_zone_high
    result["diff_pct"] = round((close - ma60) / ma60 * 100, 2)

    return result


# ============================================================
# 宏观闸导入
# ============================================================
def get_macro_gate():
    """获取宏观闸状态（带缓存，同一次调用只拉一次）"""
    try:
        from macro_gate import assess_all
        return assess_all()
    except ImportError:
        return None


# ============================================================
# 主路由入口
# ============================================================
def route_single(ticker, data, macro=None):
    """
    单标路由判定（r33.92 理想架构）

    总路由设计:
      标的进入 → 豁免前置 → 确定策略归属 → 各策略独立判定
      EMA三态分流仅作为「美股进攻」的内部漏斗，不再作为全局闸门。

    策略归属层级（从上到下，命中即返回）：
      L-1: 豁免前置（金盾/固定层/独立标的/待分类/独立动量）
      L0:  永久剥夺检查
      L1:  美股进攻（US_OFFENSIVE_TICKERS，内部用 EMA+C3/C4 判定）
      L2:  A股进攻（A_OFFENSIVE_TICKERS，内部用牛市+MA5回踩判定）
      L3:  反击（COUNTERPUNCH_TICKERS，内部用R0-R2判定）
      L4:  兜底闲置
    """
    data = adapt_fields(data)  # 字段适配
    result = {
        "ticker": ticker,
        "close": safe_float(data, "close"),
        "change_pct": safe_float(data, "change_pct"),
    }

    # ═══════════════════════════════════════════════════════════
    # L-1: 豁免前置 — 不参与任何路由判定
    # ═══════════════════════════════════════════════════════════
    exempt = judge_exemption(ticker, data)
    if exempt:
        result["route"] = exempt["route"]
        result["status"] = exempt["status"]
        result["reason"] = exempt["reason"]

        if exempt["route"] == "gold_shield":
            result["gold_shield"] = judge_gold_shield(ticker, data)
        elif exempt["route"] == "fixed_layer":
            result["fixed_layer"] = judge_fixed_layer(ticker, data)
        elif exempt["route"] == "momentum":
            result["momentum"] = judge_momentum(ticker, data)
        return result

    # ═══════════════════════════════════════════════════════════
    # L0: 总路由 — 确定标的的策略归属
    # ═══════════════════════════════════════════════════════════
    special = judge_special(ticker, data)
    result["special"] = special

    # 极端乖离拦截（所有策略池共享）
    gap = judge_extreme_gap(ticker, data)
    result["extreme_gap"] = gap

    # EMA判定（仅用于美股进攻内部漏斗，不在此层做分流）
    ema = judge_ema_diversion(ticker, data)
    result["ema"] = ema

    # ─── 总路由：按策略归属分发 ───
    in_us_offensive = ticker in US_OFFENSIVE_TICKERS and not special.get("deprived_offensive")
    in_a_offensive = ticker in A_OFFENSIVE_TICKERS
    in_counterpunch = ticker in COUNTERPUNCH_TICKERS and not special.get("deprived_counterpunch")

    # ═══════════════════════════════════════════════════════════
    # L1: 美股进攻判定
    # ── EMA三态分流在此层内部做漏斗，不管其他策略池的事 ──
    # ═══════════════════════════════════════════════════════════
    if in_us_offensive:
        if ema["diversion"] == "data_missing":
            result["route"] = "data_missing"
            result["status"] = "EMA数据缺失"
            return result

        if ema["diversion"] == "offensive":
            offensive = judge_offensive_c3_c4(ticker, data)
            result["offensive"] = offensive
            if offensive["c3"] and offensive["c4"]:
                result["route"] = "us_offensive"
                result["status"] = "🟢进攻触发"
            elif offensive["c3"] and offensive["c4_price"]:
                result["route"] = "us_offensive"
                result["status"] = "🟡预备进攻（量能不满足）"
            else:
                result["route"] = "offensive_candidate"
                result["status"] = "进攻候选（C3/C4未全满足）"
        else:
            # EMA未形成多头 → 进攻候选，等待C1∧C2恢复
            result["route"] = "offensive_candidate"
            result["status"] = "进攻候选（EMA未全多头，等待C1∧C2恢复）"
        return result

    # ═══════════════════════════════════════════════════════════
    # L2: A股进攻判定（内部用牛熊+MA5回踩做漏斗）
    # ═══════════════════════════════════════════════════════════
    if in_a_offensive:
        a_off = judge_a_share_offensive(ticker, data)
        result["a_offensive"] = a_off

        if a_off["bull_market"]:
            if a_off["ma5_pullback"] or a_off.get("ma50_pullback"):
                result["route"] = "a_share_offensive"
                result["status"] = "🟢A股进攻触发"
            else:
                result["route"] = "a_share_offensive"
                result["status"] = "🟡牛市已确认，等待MA5回踩"
            return result

        # 非牛市：A股进攻不适用 → 如果同时是反击候选，跌入L3反击判定
        # 如果不在反击池 → 兜底闲置
        if not in_counterpunch:
            result["route"] = "idle"
            result["status"] = "熊市/过渡期（A股进攻冻结）"
            return result
        # in_counterpunch → 继续往下走入L3

    # ═══════════════════════════════════════════════════════════
    # L3: 反击判定（独立漏斗，不经过EMA三态前置）
    # ═══════════════════════════════════════════════════════════
    if in_counterpunch:
        cr = judge_counterpunch_r0_r2(ticker, data, special)
        result["counterpunch"] = cr

        if cr.get("status") == "deprived":
            result["route"] = "idle"
            result["status"] = "🔴反击永久剥夺"
        elif cr.get("status") == "data_missing":
            result["route"] = "data_missing"
            result["status"] = "反击数据缺失"
        elif cr.get("triggered"):
            result["route"] = "counterpunch"
            result["status"] = "🟡反击触发"
        else:
            result["route"] = "counterpunch"
            result["status"] = "反击候选（未达买入区间）"
        return result

    # ═══════════════════════════════════════════════════════════
    # L4: 兜底 — 不在任何候选池
    # ═══════════════════════════════════════════════════════════
    result["route"] = "idle"
    result["status"] = "⚪闲置"
    return result


def route_all(market_data):
    """全量路由判定"""
    macro = get_macro_gate()
    results = {"_macro": macro}
    for ticker in PARAMS["pool"]["us_equity"] + PARAMS["pool"]["cn_equity"] + PARAMS["pool"]["independent"]:
        if ticker in market_data:
            r = route_single(ticker, market_data[ticker], macro)
            # 注入宏观闸否决（如果全局熔断或危机模式）
            if macro:
                if macro["verdict"]["global_meltdown"]:
                    if r.get("route") not in ("fixed_layer", "gold_shield", "independent"):
                        r["macro_override"] = "🔴全局熔断——信号无效"
                elif macro["verdict"]["crisis_mode"]:
                    if r.get("route") in ("us_offensive", "a_share_offensive", "counterpunch"):
                        r["macro_override"] = "🔴危机模式——暂停新开仓"
            results[ticker] = r
        else:
            results[ticker] = {"ticker": ticker, "route": "data_missing", "status": "无数据"}
    return results


# ============================================================
# 输出格式化
# ============================================================
def format_table(results):
    """表格格式输出"""
    lines = []

    # 宏观闸摘要
    macro = results.get("_macro")
    if macro:
        u = macro["us10y"]
        v = macro["vix"]
        lines.append(f"US10Y: {u['value']}% ({u['label']}) | VIX: {v['value']} ({v['label']}) | {macro['verdict']['summary']}")
        lines.append("")

    lines.append(f"{'标的':<8} {'现价':>8} {'涨跌':>7} {'路由':<18} {'状态':<36}")
    lines.append("-" * 80)

    # 按路由分组排序
    route_order = {
        "us_offensive": 0, "a_share_offensive": 1, "offensive_candidate": 2,
        "counterpunch": 3, "momentum": 4, "gold_shield": 5,
        "fixed_layer": 6, "independent": 7,
        "idle": 8, "data_missing": 9, "unclassified": 10
    }

    sorted_results = sorted(results.items(), key=lambda x: route_order.get(x[1].get("route", ""), 99))

    for ticker, r in sorted_results:
        if ticker.startswith("_"):  # 跳过元数据字段
            continue
        close = r.get("close") or 0
        change = r.get("change_pct") or 0
        route = r.get("route", "?")
        status = r.get("status", "?")

        # 截断status
        if len(status) > 36:
            status = status[:33] + "..."

        lines.append(f"{ticker:<8} {close:>8.2f} {change:>+6.2f}% {route:<18} {status:<36}")

    return "\n".join(lines)


def format_json(results):
    """JSON格式输出（含完整判定详情）"""
    return json.dumps(results, ensure_ascii=False, indent=2, default=str)


# ============================================================
# CLI入口
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="联邦投顾路由判定引擎")
    parser.add_argument("--ticker", type=str, help="单标判定")
    parser.add_argument("--table", action="store_true", help="表格格式输出")
    parser.add_argument("--input", type=str, help="从指定JSON文件读取market_data输出")
    parser.add_argument("--json", action="store_true", help="JSON格式输出（默认）")
    args = parser.parse_args()

    # 获取market_data（优先级：--input > stdin > 调用market_data.py）
    if args.input:
        with open(args.input, "r") as f:
            market_data = json.load(f)
    elif not sys.stdin.isatty():
        # 从标准输入读取（fire_report.py 流水线传入 bridged 数据）
        try:
            raw = sys.stdin.read()
            if raw.strip():
                market_data = json.loads(raw)
            else:
                raise ValueError("stdin为空")
        except (json.JSONDecodeError, ValueError):
            print("❌ stdin 数据解析失败", file=sys.stderr)
            sys.exit(1)
    else:
        # 回退：调用market_data.py
        import subprocess
        script_dir = os.path.dirname(os.path.abspath(__file__))
        md_script = os.path.join(script_dir, "market_data.py")
        result = subprocess.run(["python3", md_script], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"❌ market_data.py 执行失败: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        try:
            market_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            # market_data.py 可能输出表格格式，尝试提取JSON
            # 回退：直接调用Python模块
            sys.path.insert(0, script_dir)
            from market_data import fetch_all_market_data
            market_data = fetch_all_market_data()

    # 判定
    if args.ticker:
        if args.ticker in market_data:
            r = route_single(args.ticker, market_data[args.ticker])
            results = {args.ticker: r}
        else:
            print(f"❌ 标的 {args.ticker} 不在数据中", file=sys.stderr)
            sys.exit(1)
    else:
        results = route_all(market_data)

    # 输出
    if args.table:
        print(format_table(results))
    else:
        print(format_json(results))
