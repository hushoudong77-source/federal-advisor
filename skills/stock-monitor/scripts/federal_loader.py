#!/usr/bin/env python3
"""
联邦投顾持仓监控 — 加载联邦参数配置 V2
从 federal_watchlist.json 加载监控列表，覆盖 monitor.py 的 WATCHLIST
"""

import json
import os
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "federal_watchlist.json"


def load_federal_watchlist():
    """加载联邦持仓监控配置"""
    if not CONFIG_PATH.exists():
        print(f"⚠️ 联邦配置文件不存在: {CONFIG_PATH}")
        return None
    
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
    
    stocks = config.get('stocks', [])
    print(f"📋 加载联邦监控配置: {len(stocks)} 标 | 更新: {config.get('updated', 'unknown')}")
    
    for s in stocks:
        fed = s.get('federal', {})
        strat = fed.get('strategy', 'N/A')
        print(f"  {s['code']} {s['name']} — {strat} | 成本: {s.get('cost', '?')}")
    
    return stocks


def load_and_monkeypatch():
    """
    加载联邦配置并替换 monitor.py 的 WATCHLIST。
    使用 monkey-patch 方式，不修改原始 monitor.py。
    """
    sys.path.insert(0, str(Path(__file__).parent))
    
    stocks = load_federal_watchlist()
    if not stocks:
        print("⚠️ 无法加载联邦配置，使用默认 WATCHLIST")
        return False
    
    import monitor
    monitor.WATCHLIST = stocks
    monitor.FEDERAL_MODE = True
    
    # 统计
    n_a = len([s for s in stocks if s.get('market') != 'us'])
    n_us = len([s for s in stocks if s.get('market') == 'us'])
    print(f"✅ 联邦监控配置已激活: {len(stocks)} 标 (A股{n_a} + 美股{n_us})")
    return True


if __name__ == '__main__':
    load_and_monkeypatch()
