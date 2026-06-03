#!/usr/bin/env python3
"""
联邦投顾 — 实时行情取数标准工具 V1.0
数据源：腾讯财经（A股ETF）/ 新浪财经（美股ETF+个股）
输出：JSON 结构化，key=标的代码，value={price, change_pct, high, low, volume}
"""

import urllib.request
import json
import re
import sys

# ============================================================
# A股 ETF — 腾讯财经 qt.gtimg.cn
# ============================================================
A_ETF_CODES = [
    "sz518880", "sh510300", "sh510500", "sz159915",
    "sh588000", "sh513180", "sh513770", "sh513910",
    "sz159545", "sz159302"
]

def fetch_a_etf(codes=None):
    """拉取A股ETF实时行情"""
    codes = codes or A_ETF_CODES
    url = f"http://qt.gtimg.cn/q={','.join(codes)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    text = resp.read().decode("gbk")

    results = {}
    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        # 格式: v_sh510300="...~510300~现价~涨跌~涨跌幅~最高~最低~..."
        match = re.search(r'v_(\w+)="(.+)"', line)
        if not match:
            continue
        code_raw = match.group(1)
        fields = match.group(2).split("~")
        # 提取纯代码（去前缀）
        code = code_raw[2:] if len(code_raw) > 2 else code_raw
        try:
            results[code] = {
                "price": float(fields[3]),
                "change_pct": float(fields[32]) if len(fields) > 32 else None,
                "high": float(fields[33]) if len(fields) > 33 else None,
                "low": float(fields[34]) if len(fields) > 34 else None,
                "volume": int(fields[6]) if len(fields) > 6 and fields[6] else 0,
                "source": "tencent"
            }
        except (ValueError, IndexError):
            results[code] = {"error": "parse_failed", "raw": fields}
    return results


# ============================================================
# 美股 — 新浪财经 hq.sinajs.cn
# ============================================================
US_ETF_CODES = [
    "gb_qqq", "gb_spy", "gb_ivv", "gb_iau",
    "gb_ewy", "gb_vnm", "gb_bbjp", "gb_flin",
    "gb_mufg", "gb_sgov"
]

def fetch_us(code_raw):
    """拉取单只美股实时行情（新浪单次只支持一个）
    新浪格式: 名称,现价,涨跌幅%,时间,涨跌额,今开,最高,最低,52高,52低,成交量,...
              [0]  [1]   [2]     [3] [4]   [5] [6] [7] [8]  [9] [10]
    """
    url = f"http://hq.sinajs.cn/list={code_raw}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn"
    })
    resp = urllib.request.urlopen(req, timeout=10)
    text = resp.read().decode("gbk")
    match = re.search(r'="(.+)"', text)
    if not match:
        return {"error": "no_data"}
    fields = match.group(1).split(",")
    if not fields or not fields[0]:
        return {"error": "empty"}
    code = code_raw.replace("gb_", "").upper()
    try:
        return {
            code: {
                "price": float(fields[1]),
                "change_pct": float(fields[2]) if fields[2] else None,
                "high": float(fields[6]) if len(fields) > 6 and fields[6] else None,
                "low": float(fields[7]) if len(fields) > 7 and fields[7] else None,
                "volume": int(fields[10]) if len(fields) > 10 and fields[10] else 0,
                "source": "sina"
            }
        }
    except (ValueError, IndexError):
        return {code: {"error": "parse_failed"}}


def fetch_us_batch(codes=None):
    """批量拉取美股实时行情"""
    codes = codes or US_ETF_CODES
    results = {}
    for c in codes:
        results.update(fetch_us(c))
    return results


# ============================================================
# 宏观锚点 — 新浪财经（交易时段有效，非交易时段降级为 web_search）
# ============================================================
# 新浪非交易时段 DXY/XAU/US10Y/VIX/USDCNY 返回空，仅布伦特原油可用
# 宏观锚点改为从 web_search / 其他源获取，此处仅保留框架
MACRO_SINA_CODES = {
    "BRENT": "gb_sco",       # 布伦特原油（新浪可用）
}

def fetch_macro_sina():
    """拉取新浪可用的宏观锚点"""
    url = f"http://hq.sinajs.cn/list={','.join(MACRO_SINA_CODES.values())}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn"
    })
    resp = urllib.request.urlopen(req, timeout=10)
    text = resp.read().decode("gbk")

    results = {}
    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        match = re.search(r'var hq_str_(\w+)="(.+)"', line)
        if not match:
            match = re.search(r'="(.+)"', line)
            if not match:
                continue
        code_raw = match.group(1) if match.lastindex >= 2 else None
        values = match.group(2 if match.lastindex >= 2 else 1).split(",")
        if not values or not values[0]:
            continue
        name = [k for k, v in MACRO_SINA_CODES.items() if v == code_raw]
        name = name[0] if name else "UNKNOWN"
        try:
            results[name] = float(values[1])
        except (ValueError, IndexError):
            results[name] = "parse_failed"
    return results


def fetch_macro():
    """拉取宏观锚点（新浪可用部分 + 占位标记不可用部分）"""
    result = fetch_macro_sina()
    # 标注非交易时段不可用锚点（需通过 web_search 或统帅 P0 供弹）
    result["_note"] = "DXY/US10Y/VIX/XAU/USDCNY unavailable via Sina in non-trading hours. Use P0 feed or web_search."
    return result


# ============================================================
# 全量取数入口
# ============================================================
def fetch_all():
    """一键拉取全量：A股10只 + 美股10只 + 宏观锚点"""
    result = {
        "timestamp": "",
        "a_etf": fetch_a_etf(),
        "us_etf": fetch_us_batch(),
        "macro": fetch_macro(),
    }
    # 时间戳
    from datetime import datetime
    result["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        print(json.dumps(fetch_all(), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "--a":
        print(json.dumps(fetch_a_etf(), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "--us":
        print(json.dumps(fetch_us_batch(), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "--macro":
        print(json.dumps(fetch_macro(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(fetch_all(), ensure_ascii=False, indent=2))
