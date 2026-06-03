"""
data_pipeline.py — V1.2 冻结执行版 数据管道
============================================
功能:
  1. 加载 19 只标的原始 CSV → 统一 OHLCV DataFrame
  2. Train/Val/Test 时间切割 (4年/12月/10月)
  3. 低频标的过滤 (<30次交易/年 踢除)
  4. regime 标记注入 (crisis/tightening/normal)
  5. 输出标准化 HDF5 供下游引擎消费

硬规格 (V1.2冻结):
  - Train: 2019-01-01 ~ 2023-12-31 (柔性前延至数据起始)
  - Val:   2024-01-01 ~ 2024-12-31
  - Test:  2025-01-01 ~ 2026-05-08 (数据截止)
  - 低频线: <30次年化交易 → 踢除
  - regime标记: crisis/tightening/normal 三态

用法:
  python data_pipeline.py --data-dir ./data --output ./output/data_bundle.h5
"""

import pandas as pd
import numpy as np
import os
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

# ============================================================
# 硬编码配置 (V1.2冻结)
# ============================================================

# 时间切割边界
TRAIN_END = "2023-12-31"
VAL_START = "2024-01-01"
VAL_END = "2024-12-31"
TEST_START = "2025-01-01"

# 低频剔除线: 年化交易次数 < 30 → 踢除
MIN_ANNUAL_TRADES = 30

# regime标记 (基于VIX/US10Y等宏观数据, 暂时用简化版)
REGIME_RULES = {
    "crisis": [
        # 2020-02-19 ~ 2020-04-07 新冠崩盘
        ("2020-02-19", "2020-04-07"),
        # 2022-01-03 ~ 2022-10-12 加息熊市
        ("2022-01-03", "2022-10-12"),
    ],
    "tightening": [
        # 2021-11-22 ~ 2022-01-02 Taper→加息过渡
        ("2021-11-22", "2022-01-02"),
        # 2022-10-13 ~ 2023-07-31 加息末期高压
        ("2022-10-13", "2023-07-31"),
    ],
}
# normal = 不在以上区间即为normal

# 标的元数据
SYMBOL_META = {
    # A股 ETF (市场=境内, 跨境=0)
    "510300": {"name": "沪深300ETF", "market": "CN", "cross_border": False, "type": "equity"},
    "510500": {"name": "中证500ETF", "market": "CN", "cross_border": False, "type": "equity"},
    "159915": {"name": "创业板ETF", "market": "CN", "cross_border": False, "type": "equity"},
    "588000": {"name": "科创50ETF", "market": "CN", "cross_border": False, "type": "equity"},
    "513180": {"name": "恒生科技ETF", "market": "CN", "cross_border": True, "type": "equity"},
    "513770": {"name": "港股通科技ETF", "market": "CN", "cross_border": True, "type": "equity"},
    "513910": {"name": "港股红利ETF", "market": "CN", "cross_border": True, "type": "equity"},
    "159545": {"name": "恒生红利ETF", "market": "CN", "cross_border": True, "type": "equity"},
    "159302": {"name": "港股高股息ETF", "market": "CN", "cross_border": True, "type": "equity"},
    "518880": {"name": "黄金ETF", "market": "CN", "cross_border": False, "type": "commodity"},
    # 美股 ETF
    "QQQ": {"name": "纳指100ETF", "market": "US", "cross_border": False, "type": "equity"},
    "IVV": {"name": "标普500ETF", "market": "US", "cross_border": False, "type": "equity"},
    "IAU": {"name": "黄金ETF(USD)", "market": "US", "cross_border": False, "type": "commodity"},
    "BBJP": {"name": "日本ETF", "market": "US", "cross_border": True, "type": "equity"},
    "MUFG": {"name": "三菱日联", "market": "US", "cross_border": True, "type": "equity"},
    "EWY": {"name": "韩国ETF", "market": "US", "cross_border": True, "type": "equity"},
    "VNM": {"name": "越南ETF", "market": "US", "cross_border": True, "type": "equity"},
    "FLIN": {"name": "印度ETF", "market": "US", "cross_border": True, "type": "equity"},
    "SMIN": {"name": "印度中小盘ETF", "market": "US", "cross_border": True, "type": "equity"},
}


@dataclass
class PipelineResult:
    """管道输出"""
    train: Dict[str, pd.DataFrame]   # symbol → train df
    val: Dict[str, pd.DataFrame]     # symbol → val df
    test: Dict[str, pd.DataFrame]    # symbol → test df
    kicked: List[str]                # 被踢除的标的
    meta: pd.DataFrame               # 标的元数据


def load_csv_unified(filepath: str) -> pd.DataFrame:
    """统一加载 V1.2 格式 CSV (ts_code, date, open, high, low, close, volume, ...)"""
    df = pd.read_csv(filepath)
    # 自动检测日期格式
    try:
        df["date"] = pd.to_datetime(df["date"])  # 自动识别格式 (YYYY-MM-DD 或 YYYYMMDD)
    except (ValueError, KeyError):
        df["date"] = pd.to_datetime(df["date"])
    # 确保有 volume 列，部分标的数据缺失
    if "volume" not in df.columns:
        df["volume"] = np.nan
    # 保留标准列
    cols = ["date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def load_all(data_dir: str) -> Dict[str, pd.DataFrame]:
    """加载所有标的 CSV → {symbol: DataFrame}"""
    raw = {}
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".csv") or fname.startswith("_"):
            continue
        symbol = fname.replace("_daily.csv", "").replace(".csv", "")
        filepath = os.path.join(data_dir, fname)
        try:
            df = load_csv_unified(filepath)
            if len(df) > 0:
                raw[symbol] = df
                print(f"  [{symbol}] {len(df)} rows, {df['date'].min().date()} → {df['date'].max().date()}")
        except Exception as e:
            print(f"  [⚠ {symbol}] 加载失败: {e}")
    return raw


def filter_low_frequency(
    raw: Dict[str, pd.DataFrame],
    min_annual: int = MIN_ANNUAL_TRADES,
) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    """踢除年化交易次数 < min_annual 的标的"""
    kept = {}
    kicked = []

    for symbol, df in raw.items():
        days = (df["date"].max() - df["date"].min()).days
        years = max(days / 365.25, 0.5)  # 最少算半年
        annual_trades = len(df) / years

        if annual_trades < min_annual:
            kicked.append(symbol)
            print(f"  [踢除] {symbol}: 年化交易 {annual_trades:.1f} < {min_annual}")
        else:
            kept[symbol] = df

    return kept, kicked


def assign_regime(df: pd.DataFrame) -> pd.DataFrame:
    """注入 regime 标记列 (crisis/tightening/normal)"""
    df = df.copy()
    df["regime"] = "normal"

    for regime_name, intervals in REGIME_RULES.items():
        for start, end in intervals:
            mask = (df["date"] >= start) & (df["date"] <= end)
            df.loc[mask, "regime"] = regime_name

    return df


def split_time(
    df: pd.DataFrame,
    train_end: str = TRAIN_END,
    val_start: str = VAL_START,
    val_end: str = VAL_END,
    test_start: str = TEST_START,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Train/Val/Test 时间切割"""
    train = df[df["date"] <= train_end].copy()
    val = df[(df["date"] >= val_start) & (df["date"] <= val_end)].copy()
    test = df[df["date"] >= test_start].copy()
    return train, val, test


def build_meta(kept: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """构建标的元数据表"""
    rows = []
    for symbol in sorted(kept.keys()):
        meta = SYMBOL_META.get(symbol, {})
        rows.append({
            "symbol": symbol,
            "name": meta.get("name", symbol),
            "market": meta.get("market", "??"),
            "cross_border": meta.get("cross_border", False),
            "type": meta.get("type", "equity"),
        })
    return pd.DataFrame(rows)


def run(data_dir: str, output_path: str) -> PipelineResult:
    """主流程"""
    print("=" * 60)
    print("  Data Pipeline V1.2 — 冻结执行版")
    print("=" * 60)

    # Step 1: 加载
    print("\n[1/5] 加载原始 CSV...")
    raw = load_all(data_dir)
    print(f"  总计 {len(raw)} 只标的")

    # Step 2: 低频过滤
    print(f"\n[2/5] 低频过滤 (阈值: {MIN_ANNUAL_TRADES}次/年)...")
    kept, kicked = filter_low_frequency(raw)

    # Step 3: regime 标记
    print("\n[3/5] 注入 regime 标记...")
    for symbol in kept:
        kept[symbol] = assign_regime(kept[symbol])
        regime_counts = kept[symbol]["regime"].value_counts().to_dict()
        print(f"  [{symbol}] regime: {regime_counts}")

    # Step 4: Train/Val/Test 切割
    print(f"\n[4/5] 时间切割 (Train≤{TRAIN_END}, Val={VAL_START}~{VAL_END}, Test≥{TEST_START})...")
    train, val, test = {}, {}, {}
    for symbol, df in kept.items():
        t, v, te = split_time(df)
        train[symbol] = t
        val[symbol] = v
        test[symbol] = te
        print(f"  [{symbol}] Train:{len(t)} Val:{len(v)} Test:{len(te)}")

    # Step 5: 输出 Feather 格式 (按 split/symbol 分目录)
    print(f"\n[5/5] 输出 Feather 格式 → {output_path}")
    out_base = output_path.replace(".h5", "")  # 去掉扩展名，作为目录
    os.makedirs(out_base, exist_ok=True)

    for split_name, split_data in [("train", train), ("val", val), ("test", test)]:
        split_dir = os.path.join(out_base, split_name)
        os.makedirs(split_dir, exist_ok=True)
        for symbol, df in split_data.items():
            df.reset_index(drop=True).to_feather(os.path.join(split_dir, f"{symbol}.feather"))

    # 元数据
    meta = build_meta(kept)
    meta.to_feather(os.path.join(out_base, "meta.feather"))

    # 踢除清单
    if kicked:
        pd.DataFrame({"symbol": kicked}).to_feather(os.path.join(out_base, "kicked.feather"))

    # 摘要
    print("\n" + "=" * 60)
    print(f"  管道完成")
    print(f"  通过: {len(kept)} 只  |  踢除: {len(kicked)} 只")
    train_total = sum(len(df) for df in train.values())
    val_total = sum(len(df) for df in val.values())
    test_total = sum(len(df) for df in test.values())
    print(f"  总行数 — Train:{train_total}  Val:{val_total}  Test:{test_total}")
    print(f"  输出: {out_base}/")
    print("=" * 60)

    return PipelineResult(
        train=train, val=val, test=test,
        kicked=kicked, meta=meta,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Data Pipeline V1.2")
    parser.add_argument("--data-dir", default="./data", help="原始CSV目录")
    parser.add_argument("--output", default="./output/data_bundle.h5", help="输出HDF5路径")
    args = parser.parse_args()

    run(args.data_dir, args.output)
