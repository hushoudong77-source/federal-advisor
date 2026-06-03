#!/usr/bin/env python3
"""
全池21标硬编码白名单 — 唯一真源 (Single Source of Truth)
任何扫描/分析/路由操作必须引用此文件，严禁凭记忆/惯性添加标的。

V5.8.2r15 | 2026-05-18焊入 | 直觉拦截协议V2.0硬化
"""

# ============================================================
# 全池21标精确清单（固定层空仓时VEA/VTI临时进入路由，建仓后回归19标）
# ============================================================

POOL_WHITELIST = {
    # ── 美股ETF（9标）─────────────────────────────────────
    "QQQ": {
        "name": "Invesco QQQ Trust",
        "tushare_code": "QQQ",
        "market": "us",
        "type": "etf",
        "strategy": "spearhead_only",  # 仅进攻
    },
    "IVV": {
        "name": "iShares Core S&P 500 ETF",
        "tushare_code": "IVV",
        "market": "us",
        "type": "etf",
        "strategy": "spearhead_only",
    },
    "IAU": {
        "name": "iShares Gold Trust",
        "tushare_code": "IAU",
        "market": "us",
        "type": "etf",
        "strategy": "gold_shield",  # 金盾总纲V1.2独立驱动
        "exempt": True,
    },
    "BBJP": {
        "name": "JPMorgan BetaBuilders Japan ETF",
        "tushare_code": "BBJP",
        "market": "us",
        "type": "etf",
        "strategy": "counterpunch",  # 仅反击（进攻已移除）
    },
    "MUFG": {
        "name": "Mitsubishi UFJ Financial Group ADR",
        "tushare_code": "MUFG",
        "market": "us",
        "type": "stock",
        "strategy": "counterpunch",
    },
    "EWY": {
        "name": "iShares MSCI South Korea ETF",
        "tushare_code": "EWY",
        "market": "us",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "VNM": {
        "name": "VanEck Vietnam ETF",
        "tushare_code": "VNM",
        "market": "us",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "FLIN": {
        "name": "Franklin FTSE India ETF",
        "tushare_code": "FLIN",
        "market": "us",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "SMIN": {
        "name": "iShares MSCI India ETF",
        "tushare_code": "SMIN",
        "market": "us",
        "type": "etf",
        "strategy": "observation",  # 观察期，2%上限
        "observation_cap": 0.02,
    },

    # ── A股ETF（10标）────────────────────────────────────
    "510300": {
        "name": "华泰柏瑞沪深300ETF",
        "tushare_code": "510300.SH",
        "market": "a",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "510500": {
        "name": "南方中证500ETF",
        "tushare_code": "510500.SH",
        "market": "a",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "159915": {
        "name": "易方达创业板ETF",
        "tushare_code": "159915.SZ",
        "market": "a",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "588000": {
        "name": "华夏科创50ETF",
        "tushare_code": "588000.SH",
        "market": "a",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "513180": {
        "name": "易方达恒生科技ETF",
        "tushare_code": "513180.SH",
        "market": "a",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "513770": {
        "name": "博时恒生医疗ETF",
        "tushare_code": "513770.SH",
        "market": "a",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "513910": {
        "name": "华泰柏瑞红利低波ETF",
        "tushare_code": "513910.SH",
        "market": "a",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "159545": {
        "name": "广发中证红利ETF",
        "tushare_code": "159545.SZ",
        "market": "a",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "159302": {
        "name": "易方达中证红利ETF",
        "tushare_code": "159302.SZ",
        "market": "a",
        "type": "etf",
        "strategy": "counterpunch",
    },
    "518880": {
        "name": "华安黄金ETF",
        "tushare_code": "518880.SH",
        "market": "a",
        "type": "etf",
        "strategy": "gold_shield",
        "exempt": True,
    },

    # ── 固定层（2标）────────────────────────────────────
    "VEA": {
        "name": "Vanguard FTSE Developed Markets ETF",
        "tushare_code": "VEA",
        "market": "us",
        "type": "etf",
        "strategy": "fixed_layer",  # 宪法§0管辖，永不离场
        "fixed_weight": 0.20,
        "exempt": True,
    },
    "VTI": {
        "name": "Vanguard Total Stock Market ETF",
        "tushare_code": "VTI",
        "market": "us",
        "type": "etf",
        "strategy": "fixed_layer",
        "fixed_weight": 0.10,
        "exempt": True,
    },
}


# ============================================================
# 黑名单 — 永久禁入，任何情况下不得出现在扫描/分析/路由中
# ============================================================

BLACKLIST_PERMANENT = {
    "INDA",   # iShares MSCI India ETF — 不在全池
    "EEM",    # iShares MSCI Emerging Markets — 不在全池
    "XLF",    # Financial Select Sector SPDR — 不在全池
    "EWG",    # iShares MSCI Germany ETF — 不在全池
    "KBA",    # KraneShares Bosera MSCI China A — 不在全池
    "DXJ",    # WisdomTree Japan Hedged Equity — 不在全池
    "VNQ",    # Vanguard Real Estate ETF — 不在全池
}


# ============================================================
# 工具函数
# ============================================================

def validate_symbol(symbol: str) -> bool:
    """验证标的代码是否在全池白名单内。返回True=在池内，False=不在。"""
    return symbol in POOL_WHITELIST


def validate_symbols(symbols: list) -> tuple[list, list]:
    """批量验证，返回 (valid_list, invalid_list)"""
    valid = []
    invalid = []
    for s in symbols:
        if s in POOL_WHITELIST:
            valid.append(s)
        else:
            invalid.append(s)
    return valid, invalid


def get_tushare_code(symbol: str) -> str:
    """获取Tushare代码"""
    entry = POOL_WHITELIST.get(symbol)
    if entry:
        return entry["tushare_code"]
    raise KeyError(f"'{symbol}' 不在全池21标白名单内")


def get_market(symbol: str) -> str:
    """获取市场类型: 'us' | 'a'"""
    entry = POOL_WHITELIST.get(symbol)
    if entry:
        return entry["market"]
    raise KeyError(f"'{symbol}' 不在全池21标白名单内")


def get_us_symbols() -> list:
    """获取所有美股标的代码"""
    return [s for s, e in POOL_WHITELIST.items() if e["market"] == "us"]


def get_a_symbols() -> list:
    """获取所有A股标的代码"""
    return [s for s, e in POOL_WHITELIST.items() if e["market"] == "a"]


def get_all_symbols() -> list:
    """获取全池21标代码列表"""
    return list(POOL_WHITELIST.keys())


def get_core_symbols() -> list:
    """获取核心19标（不含固定层）"""
    return [s for s, e in POOL_WHITELIST.items() if e.get("strategy") != "fixed_layer"]


def get_routing_symbols() -> list:
    """
    获取需进入路由判定的标的（固定层空仓时=全池21标，建仓后=核心19标）
    当前状态：VEA/VTI空仓 → 返回全池21标
    """
    # VEA/VTI空仓时临时进入路由
    return get_all_symbols()


# ============================================================
# 自检 — 模块导入时自动执行
# ============================================================

def _self_check():
    """导入时自检：确保白名单完整性和一致性"""
    symbols = list(POOL_WHITELIST.keys())
    expected_count = 21
    assert len(symbols) == expected_count, \
        f"白名单标的数={len(symbols)}，预期={expected_count}。缺失或多余！"

    # 检查Tushare代码唯一性
    codes = [e["tushare_code"] for e in POOL_WHITELIST.values()]
    duplicates = [c for c in codes if codes.count(c) > 1]
    if duplicates:
        raise AssertionError(f"Tushare代码重复: {set(duplicates)}")

    # 检查黑名单与白名单无交集
    overlap = set(POOL_WHITELIST.keys()) & BLACKLIST_PERMANENT
    if overlap:
        raise AssertionError(f"黑名单标的出现在白名单中: {overlap}")


_self_check()

if __name__ == "__main__":
    print(f"✅ 全池白名单自检通过：{len(POOL_WHITELIST)}标")
    print(f"   美股: {get_us_symbols()}")
    print(f"   A股:  {get_a_symbols()}")
    print(f"   黑名单: {sorted(BLACKLIST_PERMANENT)}")
