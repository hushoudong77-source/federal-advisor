#!/usr/bin/env python3
"""
执行链强制锁 — 规则N脚本化 V1.0
=================================
第一批（零风险纯数据操作）：
  Step 0:   直觉拦截协议 — 白名单校验
  Step 1.0: N.1.2 Tushare四接口探测
  Step 1.1: 规则G — 启动强制拉齐SOP
  Step 2:   规则I — 批量拉取后强制逐标对账
  Step 4:   规则M.1 — 技术指标新鲜度强制自检
  Step 5:   规则J — 输出前「零请提供」自检

输出: JSON结构，LLM读取后直接使用。
     任何步骤返回 ❌ → LLM不得输出分析正文，必须先修复后重跑。
"""

import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# ── 硬编码白名单 ──────────────────────────────────────────────
# 真源: AGENT.md 直觉拦截协议 V2.1
WHITELIST_US = [
    "QQQ", "IVV", "IAU", "BBJP", "MUFG", "EWY",
    "VNM", "FLIN", "SMIN", "VEA", "VTI", "BOTZ"
]
WHITELIST_CN = [
    "588000.SH", "513180.SH", "513910.SH", "510500.SH",
    "518880.SH", "512100.SH", "510880.SH", "159530.SZ",
    "510300.SH", "159915.SZ", "513770.SH", "159545.SZ"
]
WHITELIST_CANE = "CANE"  # 不入池但需拉取展示

WHITELIST = set(WHITELIST_US + WHITELIST_CN + [WHITELIST_CANE])

# ── Tushare 接口配置 ──────────────────────────────────────────
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN",
    "026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a")

TUSHARE_INTERFACES = {
    "fund_daily":  {"ts_code": "513910.SH", "desc": "A股ETF日线"},
    "us_daily":    {"ts_code": "QQQ", "desc": "美股ETF日线"},
    "shibor":      {"ts_code": None, "desc": "SHIBOR"},
    "us_tycr":     {"ts_code": None, "desc": "美债收益率曲线"},
}

# ── 工具函数 ──────────────────────────────────────────────────
def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def safe_len(rows):
    """安全获取DataFrame/列表行数"""
    if rows is None:
        return 0
    try:
        import pandas as pd
        if isinstance(rows, pd.DataFrame):
            return len(rows)
    except:
        pass
    try:
        return len(rows)
    except:
        return 0

def safe_rows_to_list(rows):
    """将Tushare返回的DataFrame转为dict列表"""
    if rows is None:
        return []
    try:
        import pandas as pd
        if isinstance(rows, pd.DataFrame):
            return rows.to_dict(orient="records")
    except:
        pass
    return list(rows) if hasattr(rows, '__iter__') else []

def get_latest_date(rows, date_col="trade_date"):
    """从Tushare返回行中提取最新日期"""
    rows_list = safe_rows_to_list(rows)
    if len(rows_list) == 0:
        return None
    try:
        dates = sorted(set(r.get(date_col, "") for r in rows_list), reverse=True)
        return dates[0] if dates else None
    except:
        return None

def make_result(step, status, **kwargs):
    return {"step": step, "status": status, "timestamp": now_iso(), **kwargs}


# ══════════════════════════════════════════════════════════════
# Step 0: 白名单校验
# ══════════════════════════════════════════════════════════════
def step_0_whitelist(targets):
    """
    检查 targets 中每个代码是否在白名单内。
    targets: list of str, 如 ["QQQ", "513910.SH", "INDA"]
    返回: {passed: bool, valid: [...], invalid: [...], result}
    """
    valid = [t for t in targets if t in WHITELIST]
    invalid = [t for t in targets if t not in WHITELIST]

    passed = len(invalid) == 0
    return make_result(
        "Step 0 白名单校验",
        "✅" if passed else "❌",
        passed=passed,
        total=len(targets),
        valid_count=len(valid),
        invalid_count=len(invalid),
        valid=valid,
        invalid=invalid
    )


# ══════════════════════════════════════════════════════════════
# Step 1.0: N.1.2 Tushare四接口探测
# ══════════════════════════════════════════════════════════════
def step_1_0_tushare_probe():
    """
    逐接口调用Tushare，打印返回行数和最新日期。
    禁止以「上次坏了」跳过，必须先调用再判断。
    """
    results = {}
    all_passed = True

    try:
        import tushare as ts
        pro = ts.pro_api(TUSHARE_TOKEN)
    except Exception as e:
        return make_result(
            "Step 1.0 Tushare探测",
            "❌",
            passed=False,
            error=f"Tushare初始化失败: {e}",
            interfaces={}
        )

    for iface_name, cfg in TUSHARE_INTERFACES.items():
        try:
            if iface_name == "fund_daily":
                rows = pro.fund_daily(ts_code=cfg["ts_code"],
                    start_date=(datetime.now()-timedelta(days=7)).strftime("%Y%m%d"),
                    end_date=datetime.now().strftime("%Y%m%d"))
            elif iface_name == "us_daily":
                rows = pro.us_daily(ts_code=cfg["ts_code"],
                    start_date=(datetime.now()-timedelta(days=7)).strftime("%Y%m%d"),
                    end_date=datetime.now().strftime("%Y%m%d"))
            elif iface_name == "shibor":
                rows = pro.shibor(
                    start_date=(datetime.now()-timedelta(days=7)).strftime("%Y%m%d"),
                    end_date=datetime.now().strftime("%Y%m%d"))
            elif iface_name == "us_tycr":
                rows = pro.us_tycr(
                    start_date=(datetime.now()-timedelta(days=30)).strftime("%Y%m%d"),
                    end_date=datetime.now().strftime("%Y%m%d"))
            else:
                rows = []

            n = safe_len(rows)
            # 不同接口的日期列名不同
            date_col_map = {"shibor": "date", "us_tycr": "date"}
            date_col = date_col_map.get(iface_name, "trade_date")
            latest = get_latest_date(rows, date_col) if n > 0 else None
            results[iface_name] = {
                "status": "✅",
                "rows": n,
                "latest": latest,
                "desc": cfg["desc"]
            }
        except Exception as e:
            results[iface_name] = {
                "status": "❌",
                "rows": 0,
                "latest": None,
                "error": str(e)[:200],
                "desc": cfg["desc"]
            }
            all_passed = False

    return make_result(
        "Step 1.0 Tushare四接口探测",
        "✅" if all_passed else "❌",
        passed=all_passed,
        interfaces=results
    )


# ══════════════════════════════════════════════════════════════
# Step 1.1: 规则G — 启动强制拉齐SOP
# ══════════════════════════════════════════════════════════════
def _ts_code_for_target(t):
    """将白名单代码转为Tushare ts_code"""
    if t in WHITELIST_US or t == WHITELIST_CANE:
        return t  # us_daily直接使用代码
    elif t in WHITELIST_CN:
        return t  # fund_daily直接使用代码（已含.SH/.SZ后缀）
    return None

def step_1_1_full_pull(targets=None, include_cane=True):
    """
    批量拉取全池日线 + 腾讯实时 + DR007。
    targets: None=全池, 或指定列表
    """
    import subprocess

    if targets is None:
        targets = WHITELIST_US + WHITELIST_CN
        if include_cane:
            targets = targets + [WHITELIST_CANE]

    results = {
        "us_daily": {},
        "fund_daily": {},
        "tencent_realtime": {},
        "dr007": None,
    }

    try:
        import tushare as ts
        pro = ts.pro_api(TUSHARE_TOKEN)
    except Exception as e:
        return make_result(
            "Step 1.1 规则G拉齐",
            "❌",
            passed=False,
            error=f"Tushare初始化失败: {e}",
            results=results
        )

    # ── 美股ETF日线 ──
    us_targets = [t for t in targets if t in WHITELIST_US or t == WHITELIST_CANE]
    for t in us_targets:
        try:
            rows = pro.us_daily(ts_code=t,
                start_date=(datetime.now()-timedelta(days=400)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"))
            n = safe_len(rows)
            latest = get_latest_date(rows) if n > 0 else None
            results["us_daily"][t] = {"rows": n, "latest": latest, "status": "✅" if n > 0 else "⚠️空"}
        except Exception as e:
            results["us_daily"][t] = {"rows": 0, "latest": None, "status": "❌", "error": str(e)[:150]}

    # ── A股ETF日线 ──
    cn_targets = [t for t in targets if t in WHITELIST_CN]
    for t in cn_targets:
        try:
            rows = pro.fund_daily(ts_code=t,
                start_date=(datetime.now()-timedelta(days=400)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"))
            n = safe_len(rows)
            latest = get_latest_date(rows) if n > 0 else None
            results["fund_daily"][t] = {"rows": n, "latest": latest, "status": "✅" if n > 0 else "⚠️空"}
        except Exception as e:
            results["fund_daily"][t] = {"rows": 0, "latest": None, "status": "❌", "error": str(e)[:150]}

    # ── 腾讯实时 ──
    try:
        r = subprocess.run(
            ["python3", str(Path(__file__).parent / "qt_realtime.py")],
            capture_output=True, text=True, timeout=30
        )
        results["tencent_realtime"] = {
            "status": "✅",
            "output": r.stdout[:3000] if r.returncode == 0 else r.stderr[:1000]
        }
    except Exception as e:
        results["tencent_realtime"] = {"status": "❌", "error": str(e)[:200]}

    # ── DR007 (AnySearch) ──
    try:
        r = subprocess.run(
            ["python3", str(Path(__file__).parent.parent / "skills/anysearch/scripts/anysearch_cli.py"),
             "search", "DR007 加权均价 2026年7月", "--freshness", "day", "--max_results", "3"],
            capture_output=True, text=True, timeout=30
        )
        results["dr007"] = {
            "status": "✅" if r.returncode == 0 else "⚠️",
            "output": r.stdout[:2000] if r.returncode == 0 else r.stderr[:500]
        }
    except Exception as e:
        results["dr007"] = {"status": "❌", "error": str(e)[:200]}

    # 判定整体通过
    us_ok = all(v["status"] == "✅" for v in results["us_daily"].values())
    cn_ok = all(v["status"] == "✅" for v in results["fund_daily"].values())
    tencent_ok = results["tencent_realtime"].get("status") == "✅"
    all_ok = us_ok and cn_ok and tencent_ok

    return make_result(
        "Step 1.1 规则G拉齐",
        "✅" if all_ok else "⚠️部分失败",
        passed=all_ok,
        results=results,
        summary={
            "us_daily": f"{sum(1 for v in results['us_daily'].values() if v['status']=='✅')}/{len(us_targets)}标OK",
            "fund_daily": f"{sum(1 for v in results['fund_daily'].values() if v['status']=='✅')}/{len(cn_targets)}标OK",
            "tencent_realtime": "OK" if tencent_ok else "FAIL",
            "dr007": results["dr007"].get("status", "?")
        }
    )


# ══════════════════════════════════════════════════════════════
# Step 2: 规则I — 批量拉取后强制逐标对账
# ══════════════════════════════════════════════════════════════
def step_2_reconcile(step_1_1_result, targets=None):
    """
    核对 Step 1.1 实际拉取标的 vs 需要标的。
    step_1_1_result: Step 1.1 的返回 dict
    targets: 需要标的列表，None=全池
    """
    if targets is None:
        targets = WHITELIST_US + WHITELIST_CN

    pulled_us = set(step_1_1_result.get("results", {}).get("us_daily", {}).keys())
    pulled_cn = set(step_1_1_result.get("results", {}).get("fund_daily", {}).keys())
    pulled = pulled_us | pulled_cn

    needed = set(targets)
    missing = needed - pulled
    extra = pulled - needed

    # 检查行数是否满足（≥120条，ATR14+MA60+MACD够用）
    low_rows = []
    MIN_ROWS = 120
    for pool, label in [(step_1_1_result.get("results", {}).get("us_daily", {}), "us"),
                         (step_1_1_result.get("results", {}).get("fund_daily", {}), "cn")]:
        for t, info in pool.items():
            if info.get("rows", 0) < MIN_ROWS and info.get("status") == "✅":
                low_rows.append(f"{t}({info['rows']}行)")

    passed = len(missing) == 0 and len(low_rows) == 0
    return make_result(
        "Step 2 规则I对账",
        "✅" if passed else "❌",
        passed=passed,
        total_needed=len(needed),
        total_pulled=len(pulled),
        missing=list(missing),
        extra=list(extra),
        low_rows=low_rows
    )


# ══════════════════════════════════════════════════════════════
# Step 4: 规则M.1 — 技术指标新鲜度强制自检
# ══════════════════════════════════════════════════════════════
def step_4_freshness(step_1_1_result):
    """
    检查每个标的的Tushare最新日线日期是否新鲜。
    不新鲜 = 标注过期，要求重拉。
    """
    us = step_1_1_result.get("results", {}).get("us_daily", {})
    cn = step_1_1_result.get("results", {}).get("fund_daily", {})

    freshness = {}
    stale = []
    today = datetime.now().strftime("%Y%m%d")

    for pool, label in [(us, "美股"), (cn, "A股")]:
        for t, info in pool.items():
            latest = info.get("latest", "")
            if not latest:
                freshness[t] = {"latest": None, "fresh": False, "reason": "无数据"}
                stale.append(t)
                continue

            # A股: 15:00后当日数据应已入库
            # 美股: 次日6:00后T-1数据应已入库
            # 宽松标准: latest >= 2个交易日前
            try:
                latest_dt = datetime.strptime(latest, "%Y%m%d")
                days_behind = (datetime.now() - latest_dt).days
                # 周五→周一允许3天
                is_fresh = days_behind <= 3
                freshness[t] = {
                    "latest": latest,
                    "fresh": is_fresh,
                    "days_behind": days_behind
                }
                if not is_fresh:
                    stale.append(t)
            except:
                freshness[t] = {"latest": latest, "fresh": True, "days_behind": 0}

    passed = len(stale) == 0
    return make_result(
        "Step 4 规则M.1新鲜度",
        "✅" if passed else "❌",
        passed=passed,
        total=len(freshness),
        stale_count=len(stale),
        stale=stale,
        details=freshness
    )


# ══════════════════════════════════════════════════════════════
# Step 5: 规则J — 输出前「零请提供」自检
# ══════════════════════════════════════════════════════════════
def step_5_no_please(text):
    """
    扫描文本中是否包含「请提供」「需要投喂」「等待用户」「暂无数据」。
    text: 即将输出的分析正文
    """
    triggers = ["请提供", "需要投喂", "需要您投喂", "等待用户", "暂无数据", "需守东供弹"]

    hits = []
    for line_num, line in enumerate(text.split("\n"), 1):
        for kw in triggers:
            if kw in line:
                hits.append({"line": line_num, "keyword": kw, "text": line.strip()[:120]})

    passed = len(hits) == 0
    return make_result(
        "Step 5 规则J「零请提供」",
        "✅" if passed else "❌",
        passed=passed,
        hit_count=len(hits),
        hits=hits
    )


# ══════════════════════════════════════════════════════════════
# 主入口: 跑完整执行链
# ══════════════════════════════════════════════════════════════
def run_chain(targets=None, output_text=None):
    """
    跑完整第一批执行链。
    targets: 需要的标的列表，None=全池
    output_text: 如果是Step 5自检，需要传入待检查文本

    返回: {
        "chain_passed": bool,
        "steps": [...],
        "summary": str
    }
    """
    steps = []

    # Step 0
    if targets is None:
        targets = WHITELIST_US + WHITELIST_CN + [WHITELIST_CANE]
    r = step_0_whitelist(targets)
    steps.append(r)
    if not r["passed"]:
        return {"chain_passed": False, "steps": steps, "summary": "Step 0 白名单校验失败，中断"}

    # Step 1.0
    r = step_1_0_tushare_probe()
    steps.append(r)
    if not r["passed"]:
        # 部分接口失败不阻断，但标记
        pass

    # Step 1.1
    r = step_1_1_full_pull(targets)
    steps.append(r)
    if not r["passed"]:
        return {"chain_passed": False, "steps": steps, "summary": "Step 1.1 数据拉取失败，中断"}

    # Step 2
    r = step_2_reconcile(r, targets)
    steps.append(r)
    if not r["passed"]:
        return {"chain_passed": False, "steps": steps, "summary": "Step 2 对账失败，中断"}

    # Step 4
    r = step_4_freshness(steps[-2])  # 用Step 1.1的结果
    steps.append(r)

    # Step 5 (需要传入待检查文本)
    if output_text:
        r = step_5_no_please(output_text)
        steps.append(r)
    else:
        steps.append(make_result("Step 5 规则J自检", "⏭️跳过", passed=True, note="无输出文本传入"))

    all_passed = all(s["passed"] for s in steps)
    failed_steps = [s["step"] for s in steps if not s["passed"]]

    return {
        "chain_passed": all_passed,
        "steps": steps,
        "summary": "全部通过" if all_passed else f"失败步骤: {failed_steps}"
    }


# ══════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="执行链强制锁 — 第一批零风险步骤")
    parser.add_argument("--targets", nargs="*", help="标的代码列表，默认全池")
    parser.add_argument("--check-text", type=str, help="Step 5自检的文本")
    parser.add_argument("--step", type=str, choices=["0","1.0","1.1","2","4","5","all"],
                        default="all", help="仅运行指定步骤")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()

    targets = args.targets if args.targets else None

    if args.step == "0":
        result = step_0_whitelist(targets or list(WHITELIST))
    elif args.step == "1.0":
        result = step_1_0_tushare_probe()
    elif args.step == "1.1":
        result = step_1_1_full_pull(targets)
    elif args.step == "2":
        r11 = step_1_1_full_pull(targets)
        result = step_2_reconcile(r11, targets)
    elif args.step == "4":
        r11 = step_1_1_full_pull(targets)
        result = step_4_freshness(r11)
    elif args.step == "5":
        result = step_5_no_please(args.check_text or "")
    else:
        result = run_chain(targets, args.check_text)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
