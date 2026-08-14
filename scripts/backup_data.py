#!/usr/bin/env python3
"""
联邦投顾 — 行情数据双源备份系统 V1.0
================================================
目标：摆脱 TickFlow 单点依赖，建立独立于付费 API 的历史数据库。

三件套：
  ① 源A（主库）：TickFlow 全量日线 OHLCV → data_backup/{us,cn}/*.csv
  ② 源B（第二源）：腾讯实时现价每日落盘 → data_backup/tencent/*.csv
  ③ 异地副本：data_backup 纳入 GitHub 全量备份（backup_to_github.sh 已含 git add -A）

设计要点：
  - 复权模式锁死 adjust="none"（不复权），与主库均线体系同一价格坐标系
  - manifest.json 记录每标「最新日期+行数+抓取时间」，断源一眼可见
  - CSV 通用格式（date,open,high,low,close,volume,amount），任何工具可读

用法：
  python3 scripts/backup_data.py --full       # 一次性全量抓取（初始化底库）
  python3 scripts/backup_data.py --daily      # 每日增量追加（断源前每日跑）
  python3 scripts/backup_data.py --tencent    # 腾讯现价单独落盘
  python3 scripts/backup_data.py --status     # 查看备份库状态
"""

import os
import sys
import json
import time
import csv
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data_backup")
BACKUP_DIR = os.path.abspath(BACKUP_DIR)
US_DIR = os.path.join(BACKUP_DIR, "us")
CN_DIR = os.path.join(BACKUP_DIR, "cn")
TC_DIR = os.path.join(BACKUP_DIR, "tencent")
MANIFEST = os.path.join(BACKUP_DIR, "manifest.json")

# 复用 market_data.py 的全池定义（25标：美股13+含CANE，A股12）
from market_data import FULL_POOL, TICKFLOW_API_KEY, fetch_tencent_realtime

COUNT_FULL = 10000  # 全量历史（TickFlow max 10000）
CSV_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]


def _ensure_dirs():
    for d in (BACKUP_DIR, US_DIR, CN_DIR, TC_DIR):
        os.makedirs(d, exist_ok=True)


def _csv_path(fed, info):
    """返回标的对应的 CSV 路径。美股→us/，A股→cn/"""
    sub = US_DIR if info["type"] == "us" else CN_DIR
    return os.path.join(sub, f"{fed}.csv")


def _load_manifest():
    if os.path.exists(MANIFEST):
        try:
            with open(MANIFEST, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_manifest(m):
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def _write_csv(path, rows):
    """rows: list of dict，按 CSV_COLUMNS 顺序写出"""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _read_csv(path):
    """读取 CSV，返回 list of dict（无 header 转换，保留原始）"""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _df_to_rows(df):
    """TickFlow DataFrame → CSV rows"""
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "date": str(r["trade_date"]),
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "volume": r["volume"],
            "amount": r.get("amount", 0.0),
        })
    return rows


def _get_tickflow():
    """获取 TickFlow 客户端（带依赖自愈）"""
    try:
        from self_heal import ensure_tickflow
        ensure_tickflow()
    except Exception:
        pass
    from tickflow import TickFlow
    return TickFlow(TICKFLOW_API_KEY)


def run_full():
    """一次性全量抓取：25标全部历史日线落盘"""
    _ensure_dirs()
    print("=" * 60)
    print(" 行情数据全量备份 — TickFlow 全量历史")
    print(f" 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    tf = _get_tickflow()
    manifest = _load_manifest()
    ok, fail = 0, 0

    for fed, info in FULL_POOL.items():
        sym = info["tickflow"]
        path = _csv_path(fed, info)
        try:
            df = tf.klines.get(sym, period="1d", count=COUNT_FULL,
                               adjust="none", as_dataframe=True)
            if df is None or len(df) == 0:
                print(f"  ❌ {fed:8s} 返回空")
                fail += 1
                continue
            rows = _df_to_rows(df)
            _write_csv(path, rows)
            earliest = str(df["trade_date"].iloc[0])
            latest = str(df["trade_date"].iloc[-1])
            manifest[fed] = {
                "type": info["type"],
                "tickflow": sym,
                "rows": len(rows),
                "earliest": earliest,
                "latest": latest,
                "source": "tickflow",
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            print(f"  ✅ {fed:8s} {len(rows):5d}行  {earliest} ~ {latest}")
            ok += 1
        except Exception as e:
            print(f"  ❌ {fed:8s} 抓取失败: {type(e).__name__}: {e}")
            fail += 1

    _save_manifest(manifest)
    print("-" * 60)
    print(f" 结果: 成功 {ok} / 失败 {fail}")
    print(f" 存储目录: {BACKUP_DIR}")
    return ok, fail


def run_daily():
    """每日增量：把当天新增的一根日线追加到 CSV（断源前每日跑）"""
    _ensure_dirs()
    print("=" * 60)
    print(" 行情数据每日增量备份")
    print(f" 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    tf = _get_tickflow()
    manifest = _load_manifest()
    added, skipped, fail = 0, 0, 0

    for fed, info in FULL_POOL.items():
        sym = info["tickflow"]
        path = _csv_path(fed, info)
        existing = _read_csv(path)
        last_date = existing[-1]["date"] if existing else None

        try:
            # 增量只需拉最近 30 条，比对后追加新行
            df = tf.klines.get(sym, period="1d", count=60,
                               adjust="none", as_dataframe=True)
            if df is None or len(df) == 0:
                print(f"  ❌ {fed:8s} 返回空")
                fail += 1
                continue

            new_rows = []
            for _, r in df.iterrows():
                d = str(r["trade_date"])
                if last_date and d <= last_date:
                    continue
                new_rows.append({
                    "date": d,
                    "open": r["open"],
                    "high": r["high"],
                    "low": r["low"],
                    "close": r["close"],
                    "volume": r["volume"],
                    "amount": r.get("amount", 0.0),
                })

            if new_rows:
                # 追加新行
                with open(path, "a", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                    for r in new_rows:
                        w.writerow(r)
                latest = new_rows[-1]["date"]
                manifest[fed] = {
                    "type": info["type"],
                    "tickflow": sym,
                    "rows": len(existing) + len(new_rows),
                    "earliest": existing[0]["date"] if existing else latest,
                    "latest": latest,
                    "source": "tickflow",
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                print(f"  ✅ {fed:8s} +{len(new_rows)}行 → 最新 {latest}")
                added += len(new_rows)
            else:
                print(f"  ⏭️  {fed:8s} 无新数据（最新 {last_date}）")
                skipped += 1
        except Exception as e:
            print(f"  ❌ {fed:8s} 增量失败: {type(e).__name__}: {e}")
            fail += 1

    _save_manifest(manifest)
    print("-" * 60)
    print(f" 结果: 新增 {added} 行 / 无更新 {skipped} / 失败 {fail}")
    return added, skipped, fail


def run_tencent():
    """腾讯现价单独落盘：第二独立源，每日积累自己的历史"""
    _ensure_dirs()
    print("=" * 60)
    print(" 腾讯现价落盘 — 独立第二源")
    print(f" 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    data = fetch_tencent_realtime()
    if "_error" in data:
        print(f"  ❌ 腾讯不可用: {data['_error']}")
        return 0, 1

    today = datetime.now().strftime("%Y-%m-%d")
    ok, fail = 0, 0

    for fed, info in FULL_POOL.items():
        if fed not in data:
            fail += 1
            continue
        d = data[fed]
        path = os.path.join(TC_DIR, f"{fed}.csv")
        row = {
            "date": today,
            "open": d.get("prev_close"),
            "high": d.get("high"),
            "low": d.get("low"),
            "close": d.get("price"),
            "volume": d.get("volume", 0),
            "amount": 0.0,
        }
        # 追加（腾讯同一个交易日可能多次调用，避免重复日期）
        existing = _read_csv(path)
        if existing and existing[-1]["date"] == today:
            # 覆盖当日最新快照
            existing[-1] = row
            _write_csv(path, existing)
        else:
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                w.writerow(row)
        ok += 1

    print(f" 结果: 成功 {ok} / 失败 {fail}，日期 {today}")
    return ok, fail


def run_status():
    """查看备份库状态"""
    _ensure_dirs()
    manifest = _load_manifest()
    print("=" * 60)
    print(" 行情数据备份库状态")
    print("=" * 60)
    if not manifest:
        print("  ⚠️ 备份库为空，请先执行 --full")
        return

    print(f"\n {'标的':10s} {'类型':5s} {'行数':>7s} {'最早':>12s} {'最新':>12s} {'更新时间':>19s}")
    print("-" * 70)
    for fed, m in sorted(manifest.items()):
        print(f" {fed:10s} {m.get('type','?'):5s} {m.get('rows',0):>7d} "
              f"{m.get('earliest','?'):>12s} {m.get('latest','?'):>12s} "
              f"{m.get('updated_at','?'):>19s}")
    print("-" * 70)
    print(f" 共 {len(manifest)} 标 | 存储目录: {BACKUP_DIR}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--full" in args:
        run_full()
    elif "--daily" in args:
        run_daily()
    elif "--tencent" in args:
        run_tencent()
    elif "--status" in args:
        run_status()
    else:
        print(__doc__)
