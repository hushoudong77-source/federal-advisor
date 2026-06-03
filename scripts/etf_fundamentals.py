#!/usr/bin/env python3
"""
ETF基本面数据自动抓取模块
从iShares官网提取PE/PB等估值数据（Vanguard/Invesco需browser渲染）

用法：
  python3 scripts/etf_fundamentals.py --ticker EFA
  python3 scripts/etf_fundamentals.py --all
  python3 scripts/etf_fundamentals.py --list
"""

import requests
import re
import sys
import time
from datetime import datetime

ETF_MAP = {
    "EFA":  ("ishares", "https://www.ishares.com/us/products/239623/ishares-core-msci-eafe-etf"),
    "ITOT": ("ishares", "https://www.ishares.com/us/products/239724/ishares-core-sp-total-us-stock-market-etf"),
    "IVV":  ("ishares", "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf"),
    "IEF":  ("ishares", "https://www.ishares.com/us/products/239454/ishares-7-10-year-treasury-bond-etf"),
    "TLT":  ("ishares", "https://www.ishares.com/us/products/239456/ishares-20-year-treasury-bond-etf"),
    "SGOV": ("ishares", "https://www.ishares.com/us/products/314116/ishares-0-3-month-treasury-bond-etf"),
    "IAU":  ("ishares", "https://www.ishares.com/us/products/239561/ishares-gold-trust"),
    "EWJ":  ("ishares", "https://www.ishares.com/us/products/239730/ishares-msci-japan-etf"),
    "EWY":  ("ishares", "https://www.ishares.com/us/products/239686/ishares-msci-south-korea-etf"),
    "EWU":  ("ishares", "https://www.ishares.com/us/products/239692/ishares-msci-united-kingdom-etf"),
    "SMIN": ("ishares", "https://www.ishares.com/us/products/239674/ishares-msci-india-small-cap-etf"),
    "VNM":  ("ishares", "https://www.ishares.com/us/products/239636/ishares-msci-vietnam-etf"),
    "VEA":  ("vanguard", "https://investor.vanguard.com/investment-products/etfs/profile/vea"),
    "VTI":  ("vanguard", "https://investor.vanguard.com/investment-products/etfs/profile/vti"),
    "QQQ":  ("invesco", "https://www.invesco.com/us/financial-products/etfs/product-detail?ticker=QQQ"),
}

BOND_ETFS = {"IEF", "TLT", "SGOV"}
GOLD_ETFS = {"IAU"}


def parse_ishares(html):
    """从iShares HTML提取PE/PB等"""
    d = {}
    for pat, key in [
        (r'P/E Ratio[^<]*</[^>]*>\s*<[^>]*>\s*([\d.]+)', "PE"),
        (r'P/B Ratio[^<]*</[^>]*>\s*<[^>]*>\s*([\d.]+)', "PB"),
        (r'Expense Ratio[:\s]*([\d.]+)%', "expense_ratio"),
        (r'12m Trailing Yield.*?(\d+\.?\d*)%', "yield_12m"),
        (r'30 Day SEC Yield.*?(\d+\.?\d*)%', "sec_yield_30d"),
        (r'Number of Holdings[^<]*</[^>]*>\s*<[^>]*>\s*([\d,]+)', "num_holdings"),
        (r'Standard Deviation[^\(]*\(3y\)[^<]*</[^>]*>\s*<[^>]*>\s*([\d.]+)%', "std_dev_3y"),
        (r'Equity Beta[^\(]*\(3y\)[^<]*</[^>]*>\s*<[^>]*>\s*([\d.]+)', "beta"),
    ]:
        m = re.search(pat, html, re.DOTALL)
        if m:
            try:
                v = m.group(1).replace(",", "")
                d[key] = float(v) if "." in v or key != "num_holdings" else int(v)
            except: pass
    
    dm = re.search(r'as of\s+(May|Apr|Mar|Feb|Jan|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})', html)
    if dm: d["data_date"] = f"{dm.group(1)} {dm.group(2)}, {dm.group(3)}"
    return d


def fetch(url):
    try:
        r = requests.get(url, headers={"User-Agent": "ETFScanner/1.0"}, timeout=30)
        return parse_ishares(r.text) if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"error": str(e)}


def show(ticker, data, issuer):
    if "error" in data:
        return f"[{ticker}] ERROR: {data['error']}"
    lines = [f"\n{'='*50}", f"  {ticker} | {issuer} | {data.get('data_date','?')}", f"{'='*50}"]
    if ticker not in BOND_ETFS and ticker not in GOLD_ETFS:
        for k, label in [("PE","PE"), ("PB","PB")]:
            if k in data: lines.append(f"  {label}: {data[k]:.2f}x")
    for k, label, fmt in [
        ("expense_ratio","费用率","{:.2f}%"), ("yield_12m","12月收益","{:.2f}%"),
        ("sec_yield_30d","SEC收益","{:.2f}%"), ("std_dev_3y","3y波动","{:.2f}%"),
        ("beta","Beta","{:.2f}"), ("num_holdings","持股数","{}"),
    ]:
        if k in data and data[k] is not None: lines.append(f"  {label}: {fmt.format(data[k])}")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("用法: --ticker EFA | --all | --list")
        return
    arg = sys.argv[1]
    if arg == "--list":
        for t, (iss, url) in ETF_MAP.items(): print(f"{t:<8} {iss:<10} {url}")
        return
    tickers = list(ETF_MAP.keys()) if arg == "--all" else ([sys.argv[2].upper()] if arg == "--ticker" and len(sys.argv)>2 else [arg.upper()])
    n_ishares = n_other = 0
    for t in tickers:
        if t not in ETF_MAP: 
            print(f"[{t}] 未配置"); continue
        issuer, url = ETF_MAP[t]
        if issuer == "ishares":
            print(f"Fetching {t}...", end=" ", flush=True)
            print(show(t, fetch(url), issuer))
            n_ishares += 1; time.sleep(1.5)
        else:
            print(f"[{t}] {issuer} — 需browser渲染: {url}")
            n_other += 1
    print(f"\nDone: iShares={n_ishares}, browser_needed={n_other}")

if __name__ == "__main__":
    main()
