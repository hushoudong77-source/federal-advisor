#!/usr/bin/env python3
"""
🎯 策略池内机会打分引擎 — scikit-learn Z-score 标准化 + 加权排序
签发：守东（资产规划部首席审计官）
生效日期：2026-07-04

集成到 /开火 指令输出流程中，对同策略池内的候选标的按多维度特征打分，
输出降序排列的优先级列表。策略池之间不交叉比较（进攻 vs 反击逻辑不同）。

使用方式：
    python3 scripts/opportunity_scorer.py --mode counterpunch --prices '{"513910":1.567,"588000":1.234,...}'
    python3 scripts/opportunity_scorer.py --mode attack --prices '{"QQQ":520.5,...}'
    python3 scripts/opportunity_scorer.py --mode momentum --prices '{"FLIN":26.5,...}'
"""

import json
import sys
import argparse
import numpy as np
from sklearn.preprocessing import StandardScaler


# ============================================================
# §1 策略池标的定义（从 AGENT.md /开火模板 同步）
# ============================================================

STRATEGY_POOLS = {
    "counterpunch": {
        "name": "反击策略池",
        "targets": {
            "513910": {
                "name": "港股通央企红利ETF",
                "anchor": "MA40",
                "k": 2.7,
                "stop_mult": 2.8,
                "cooldown_days": 16,
                "route": "反击",
                "note": "L1红利层"
            },
            "512100": {
                "name": "中证1000ETF",
                "anchor": "MA40",
                "k": 2.0,
                "stop_mult": 1.5,
                "cooldown_days": 15,
                "route": "反击",
                "note": "C3独立参数"
            },
            "588000": {
                "name": "科创50ETF",
                "anchor": "MA40",
                "k": 4.7,
                "stop_mult": 3.5,
                "cooldown_days": 15,
                "route": "反击",
                "note": "L2成长层"
            },
            "510500": {
                "name": "中证500ETF",
                "anchor": "MA40",
                "k": 4.9,
                "stop_mult": 2.8,
                "cooldown_days": 60,
                "route": "反击",
                "note": "L3宽基层"
            },
            "510880": {
                "name": "红利ETF易方达",
                "anchor": "MA40",
                "k": 2.0,
                "stop_mult": 2.0,
                "cooldown_days": 30,
                "route": "反击",
                "note": "豁免R0.5"
            },
            "159530": {
                "name": "人形机器人ETF",
                "anchor": "MA40",
                "k": 1.5,
                "stop_mult": 2.0,
                "cooldown_days": 30,
                "route": "反击",
                "note": "高波动"
            },
            "BBJP": {
                "name": "日股ETF",
                "anchor": "MA40",
                "k": 5.0,
                "stop_mult": 3.5,
                "cooldown_days": 14,
                "route": "反击",
                "note": "L2发达层"
            },
            "VNM": {
                "name": "越南ETF",
                "anchor": "MA40",
                "k": 2.0,
                "stop_mult": 3.5,
                "cooldown_days": 9,
                "route": "反击",
                "note": "L2新兴层"
            }
        },
        "weights": {
            "gap_pct": 0.30,          # 距买入区间距离%（越近越好）
            "divergence_z": 0.20,     # 乖离MA40标准化（反向：越负越高分）
            "macd_score": 0.15,       # MACD动能分
            "cooldown_remaining": 0.15, # 距冷却期到期天数（越近越好）
            "volatility_score": 0.10,  # 波动率适中分
            "sharpe_score": 0.10       # 历史回测Sharpe分
        }
    },
    "attack": {
        "name": "进攻策略池",
        "targets": {
            "QQQ": {
                "name": "纳指100ETF",
                "anchor": "C4=H20×0.98",
                "cooldown_days": 30,
                "route": "进攻"
            },
            "IVV": {
                "name": "标普500ETF",
                "anchor": "C4=H20×0.98",
                "cooldown_days": 30,
                "route": "进攻"
            },
            "MUFG": {
                "name": "三菱日联金融",
                "anchor": "C4=H20×0.98",
                "cooldown_days": 30,
                "route": "进攻"
            },
            "VNM": {
                "name": "越南ETF",
                "anchor": "C4=H20×0.98",
                "cooldown_days": 30,
                "route": "进攻",
                "note": "同时是反击候选"
            },
            "513180": {
                "name": "恒生科技ETF",
                "anchor": "C4=H20×0.98",
                "cooldown_days": 30,
                "route": "进攻"
            }
        },
        "weights": {
            "gap_pct": 0.35,          # 距C4距离%
            "divergence_z": 0.15,     # 乖离MA40/MA60标准化
            "macd_score": 0.15,       # MACD动能
            "cooldown_remaining": 0.15, # 冷却期
            "trend_strength": 0.10,    # MA60趋势强度
            "volatility_score": 0.10   # ATR环境
        }
    },
    "momentum": {
        "name": "独立动量跟随池",
        "targets": {
            "FLIN": {
                "name": "印度ETF",
                "cooldown_days": 30,
                "route": "动量跟随"
            },
            "SMIN": {
                "name": "印度小盘ETF",
                "cooldown_days": 30,
                "route": "动量跟随"
            },
            "EWY": {
                "name": "韩国ETF",
                "cooldown_days": 30,
                "route": "动量跟随"
            },
            "588000": {
                "name": "科创50ETF",
                "cooldown_days": 30,
                "route": "动量跟随",
                "note": "与反击策略并行"
            }
        },
        "weights": {
            "macd_bar_strength": 0.30,  # MACD BAR强度（金叉确认度）
            "ma20_gap": 0.25,           # 距MA20距离（负=在MA20下方=可入场）
            "atr_ratio": 0.15,          # ATR/价格比（适中最好）
            "cooldown_remaining": 0.15,  # 冷却期
            "sharpe_score": 0.15        # 历史回测Sharpe
        }
    }
}


# ============================================================
# §2 特征计算函数
# ============================================================

def compute_macd_score(macd_bar, macd_direction):
    """
    MACD 动能分: -1.0(死叉加深) ~ +1.0(金叉强化)
    
    macd_bar: MACD BAR 值
    macd_direction: "rising"/"falling"/"flat"
    """
    if macd_bar is None:
        return 0.0
    
    # BAR符号分
    bar_sign = 1.0 if macd_bar > 0 else -0.5
    
    # 方向分
    if macd_direction == "rising":
        direction_bonus = 0.3
    elif macd_direction == "falling":
        direction_bonus = -0.3
    else:
        direction_bonus = 0.0
    
    return np.clip(bar_sign + direction_bonus, -1.0, 1.0)


def compute_volatility_score(atr_ratio):
    """
    波动率适中分: ATR/价格比在 0.8%~2.5% 最佳
    太高(>4%)=扣分、太低(<0.5%)=微扣
    """
    if atr_ratio is None:
        return 0.0
    
    # 黄金区间 [0.008, 0.025]
    if 0.008 <= atr_ratio <= 0.025:
        return 1.0
    elif atr_ratio > 0.04:
        return max(0.0, 1.0 - (atr_ratio - 0.04) * 30)
    elif atr_ratio < 0.005:
        return max(0.0, 1.0 - (0.005 - atr_ratio) * 200)
    elif atr_ratio > 0.025:
        return max(0.0, 1.0 - (atr_ratio - 0.025) * 20)
    else:
        return max(0.0, 1.0 - (0.008 - atr_ratio) * 100)


def compute_trend_strength(ma60_direction, price_vs_ma60):
    """
    MA60 趋势强度分: -1.0(强烈下行) ~ +1.0(强势上行)
    仅用于进攻策略池
    """
    score = 0.0
    
    if ma60_direction == "up":
        score += 0.5
    elif ma60_direction == "down":
        score -= 0.5
    
    if price_vs_ma60 is not None:
        if price_vs_ma60 > 0:
            score += 0.3
        else:
            score -= 0.3
    
    return np.clip(score, -1.0, 1.0)


def compute_cooldown_score(cooldown_days, remaining_days):
    """
    冷却期得分: 已经从冷却期出来了→高分, 还在冷却中→按剩余天数递减
    remaining_days: 距冷却期到期还有多少天 (0=已到期, 负数=已过期N天)
    """
    if remaining_days is None or cooldown_days is None:
        return 0.5  # 未知状态给中性分
    
    if remaining_days <= 0:
        # 已到期或已过期
        return 1.0
    else:
        # 按剩余比例递减
        return max(0.0, 1.0 - remaining_days / cooldown_days)


# ============================================================
# §3 核心打分引擎
# ============================================================

def score_pool(pool_name, features_dict):
    """
    对策略池内标的进行 Z-score 标准化 + 加权打分
    
    features_dict: {
        "TICKER": {
            "gap_pct": float,           # 距买入区间距离%（现价-买入价)/现价, 负=没到区间
            "divergence_ma40": float,   # 乖离MA40（%）
            "divergence_ma60": float,   # 乖离MA60（%）
            "macd_bar": float,          # MACD BAR
            "macd_direction": str,      # "rising"/"falling"/"flat"
            "atr_ratio": float,         # ATR14/现价
            "cooldown_remaining": int,  # 距冷却期到期天数 (0=已到期)
            "sharpe": float,            # 历史回测Sharpe
            "ma60_direction": str,      # "up"/"down"/"flat"
            "price_vs_ma60": float,     # 现价/MA60 - 1
            "blocked": bool,            # 是否被熔断/锁死
            "blocked_reason": str       # 熔断原因
        },
        ...
    }
    
    Returns: [(ticker, score, detail_dict), ...] 降序排列
    """
    pool = STRATEGY_POOLS.get(pool_name)
    if not pool:
        raise ValueError(f"未知策略池: {pool_name}。可选: {list(STRATEGY_POOLS.keys())}")
    
    targets = pool["targets"]
    weights = pool["weights"]
    
    # 分离已熔断和正常标的
    blocked_targets = {}
    active_targets = {}
    
    for ticker, feat in features_dict.items():
        if ticker not in targets:
            continue
        if feat.get("blocked", False):
            blocked_targets[ticker] = feat
        else:
            active_targets[ticker] = feat
    
    # 如果没有活跃标的，全部返回（熔断的排最后）
    if not active_targets:
        result = []
        for ticker, feat in blocked_targets.items():
            result.append((ticker, -999.0, {
                "status": "🔴熔断",
                "reason": feat.get("blocked_reason", "未知"),
                "gap_pct": feat.get("gap_pct"),
                "details": feat
            }))
        return result
    
    # 构建特征矩阵
    tickers = list(active_targets.keys())
    n = len(tickers)
    
    # 提取原始特征
    raw_features = {}
    for dim in weights.keys():
        raw_features[dim] = np.zeros(n)
    
    for i, ticker in enumerate(tickers):
        feat = active_targets[ticker]
        for dim in weights.keys():
            raw_features[dim][i] = _extract_raw_feature(dim, feat, pool_name)
    
    # Z-score 标准化 (至少需要2个标的)
    scaler = StandardScaler()
    z_features = {}
    
    for dim in weights.keys():
        vals = raw_features[dim].reshape(-1, 1)
        if n >= 2 and np.std(vals) > 1e-10:
            z_features[dim] = scaler.fit_transform(vals).flatten()
        else:
            z_features[dim] = np.zeros(n)
    
    # 方向修正：某些特征需要反向（值越小越好→标准化后取负）
    direction_flip = {
        "gap_pct": True,              # 距区间越近（gap越小）→分越高
        "divergence_z": True,          # 乖离越负→分越高（反击池）
        "cooldown_remaining": True,    # 剩余天数越少→分越高
    }
    
    # 加权合成
    composite = np.zeros(n)
    for dim, w in weights.items():
        z = z_features[dim]
        if direction_flip.get(dim, False):
            z = -z
        composite += w * z
    
    # 排序
    ranked_indices = np.argsort(-composite)
    
    result = []
    for idx in ranked_indices:
        ticker = tickers[idx]
        feat = active_targets[ticker]
        detail = {
            "status": "🟢可评估",
            "composite_score": round(float(composite[idx]), 3),
            "z_scores": {dim: round(float(z_features[dim][idx]), 3) for dim in weights.keys()},
            "raw_values": {dim: round(float(raw_features[dim][idx]), 4) for dim in weights.keys()},
            "gap_pct": feat.get("gap_pct"),
            "divergence_ma40": feat.get("divergence_ma40"),
            "divergence_ma60": feat.get("divergence_ma60"),
            "macd_bar": feat.get("macd_bar"),
            "atr_ratio": feat.get("atr_ratio"),
            "cooldown_remaining": feat.get("cooldown_remaining"),
            "sharpe": feat.get("sharpe"),
        }
        result.append((ticker, float(composite[idx]), detail))
    
    # 追加熔断标的到末尾
    for ticker, feat in blocked_targets.items():
        result.append((ticker, -999.0, {
            "status": "🔴熔断",
            "reason": feat.get("blocked_reason", "未知"),
            "composite_score": -999.0,
            "gap_pct": feat.get("gap_pct")
        }))
    
    return result


def _extract_raw_feature(dim, feat, pool_name):
    """提取原始特征值"""
    default = 0.0
    
    if dim == "gap_pct":
        return feat.get("gap_pct", default)
    
    elif dim == "divergence_z":
        # 用MA40乖离（反击池）/ MA60乖离（进攻池）
        if pool_name == "attack":
            return feat.get("divergence_ma60", default)
        else:
            return feat.get("divergence_ma40", default)
    
    elif dim == "macd_score":
        return compute_macd_score(
            feat.get("macd_bar"),
            feat.get("macd_direction", "flat")
        )
    
    elif dim == "macd_bar_strength":
        macd_bar = feat.get("macd_bar", 0.0)
        # 正值且上升=最好
        if macd_bar > 0:
            return min(1.0, macd_bar * 5)  # BAR=0.2→1.0
        else:
            return max(-1.0, macd_bar * 5)
    
    elif dim == "ma20_gap":
        # 现价/MA20 - 1, 负值=在MA20下方=可入场
        return feat.get("price_vs_ma20", default)
    
    elif dim == "atr_ratio":
        return feat.get("atr_ratio", default)
    
    elif dim == "cooldown_remaining":
        cd = feat.get("cooldown_remaining", None)
        if cd is None:
            return 0.0  # 未知状态→中性
        return float(cd)
    
    elif dim == "sharpe_score":
        return feat.get("sharpe", default)
    
    elif dim == "volatility_score":
        return compute_volatility_score(feat.get("atr_ratio"))
    
    elif dim == "trend_strength":
        return compute_trend_strength(
            feat.get("ma60_direction", "flat"),
            feat.get("price_vs_ma60")
        )
    
    return default


# ============================================================
# §4 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="策略池内机会打分")
    parser.add_argument("--mode", required=True, 
                        choices=["counterpunch", "attack", "momentum"],
                        help="策略池名称")
    parser.add_argument("--features", required=True,
                        help="JSON格式的特征数据")
    parser.add_argument("--compact", action="store_true",
                        help="紧凑输出（仅排名）")
    
    args = parser.parse_args()
    
    try:
        features = json.loads(args.features)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"JSON解析失败: {e}"}, ensure_ascii=False))
        sys.exit(1)
    
    try:
        results = score_pool(args.mode, features)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    
    if args.compact:
        # 紧凑输出：仅排名
        output = []
        for i, (ticker, score, detail) in enumerate(results):
            output.append({
                "rank": i + 1,
                "ticker": ticker,
                "name": STRATEGY_POOLS[args.mode]["targets"].get(ticker, {}).get("name", ""),
                "score": score,
                "status": detail.get("status", "")
            })
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        # 完整输出
        pool = STRATEGY_POOLS[args.mode]
        output = {
            "pool": pool["name"],
            "weights": pool["weights"],
            "rankings": []
        }
        for i, (ticker, score, detail) in enumerate(results):
            entry = {
                "rank": i + 1,
                "ticker": ticker,
                "name": pool["targets"].get(ticker, {}).get("name", ticker),
                "score": score,
                "status": detail.get("status", ""),
            }
            if detail.get("status") != "🔴熔断":
                entry["detail"] = detail
            else:
                entry["reason"] = detail.get("reason", "")
            output["rankings"].append(entry)
        
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
