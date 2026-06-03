#!/usr/bin/env python3
"""
P5: 动态止盈 ATR 衰减系数逐标标定
P6: 仓位分档规则验证
基于 P3 已找到的逐标最优 MA×ATR 买入参数
"""
import json, sys, math
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np

# ============================================================
# 数据加载
# ============================================================
try:
    with open('/home/agent/cow/backtest_data/all_ohlcv.json','r') as f:
        data = json.load(f)
    print(f"✅ 数据加载成功: {len(data)} 只标的")
except:
    print("❌ 数据文件不存在，请先运行 P3 回测")
    sys.exit(1)

# ============================================================
# P3 最优参数
# ============================================================
P3_OPTIMAL = {
    # 美股 (MA锚线, buy_ATR_k, stop_ATR_k)
    'QQQ':    ('MA40', 1.0, 2.0),
    'IVV':    ('MA20', 2.0, 1.5),
    'IAU':    ('MA120', 2.5, 2.0),
    'BBJP':   ('MA20', 1.5, 2.0),
    'MUFG':   ('MA60', 4.0, 2.0),
    'EWY':    ('MA120', 2.5, 2.0),
    'FLIN':   ('MA40', 2.0, 2.0),
    'VNM':    ('MA20', 1.0, 2.0),
    # A股
    '518880': ('MA80', 5.0, 2.0),
    '510300': ('MA120', 3.0, 2.0),
    '510500': ('MA20', 3.0, 2.0),
    '159915': ('MA20', 3.0, 2.5),
    '588000': ('MA60', 5.0, 1.5),
    '513180': ('MA40', 1.0, 2.0),
    '513770': ('MA80', 1.5, 1.0),
    '513910': ('MA40', 5.0, 2.0),
    '159545': ('MA40', 4.5, 2.0),
    '159302': ('MA80', 3.0, 3.0),
}

# 动态止盈 ATR 乘数扫描范围
TRAIL_K_RANGE = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]

# 绝对止损
ABS_STOP = {
    'IAU': -0.07, '518880': -0.07,
    'default': -0.05
}

def get_abs_stop(sym):
    return ABS_STOP.get(sym, ABS_STOP['default'])

# 仓位分档——深跌概率判定所需的参数
def calc_deep_prob(sym, closes, ma_line, atr):
    """简化版深跌概率估算：当前价低于MA的ATR倍数"""
    if len(closes) < 5 or atr <= 0:
        return 0.5
    current = closes[-1]
    deviation = (ma_line - current) / atr if atr > 0 else 0
    # 乖离率越大，深跌概率越低（因为已经跌了很多）
    if deviation > 3: return 0.15  # 已深跌
    elif deviation > 1.5: return 0.30
    elif deviation > 0: return 0.50
    else: return 0.70  # 在MA上方，买入后下跌概率更高

# ============================================================
# P5: 动态止盈 ATR 衰减系数扫描
# ============================================================
print("\n" + "="*90)
print("P5: 动态止盈 ATR 衰减系数逐标标定")
print("="*90)

p5_results = {}

for sym, (ma_label, buy_k, stop_k) in P3_OPTIMAL.items():
    if sym not in data:
        continue
    ohlcv = data[sym]
    closes = np.array([b['close'] for b in ohlcv])
    highs = np.array([b['high'] for b in ohlcv])
    lows = np.array([b['low'] for b in ohlcv])
    
    if len(closes) < 50:
        continue
    
    ma_period = int(ma_label.replace('MA',''))
    
    # 计算MA和ATR
    ma = np.array([np.nan]*len(closes))
    atr_arr = np.array([np.nan]*len(closes))
    tr_arr = np.array([np.nan]*len(closes))
    
    for i in range(len(closes)):
        if i >= ma_period - 1:
            ma[i] = np.mean(closes[i-ma_period+1:i+1])
        if i >= 1:
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i-1])
            tr3 = abs(lows[i] - closes[i-1])
            tr_arr[i] = max(tr1, tr2, tr3)
        if i >= 14:
            atr_arr[i] = np.mean(tr_arr[i-13:i+1])
    
    # 对每个 trail_k 做回测
    best_trail = None
    best_cagr = -999
    
    for trail_k in TRAIL_K_RANGE:
        total_return = 1.0
        in_position = False
        entry_price = 0
        highest_since_entry = 0
        trail_stop = 0
        trade_count = 0
        wins = 0
        max_dd = 0
        peak_value = 1.0
        
        for i in range(ma_period + 14, len(closes)):
            if np.isnan(ma[i]) or np.isnan(atr_arr[i]) or atr_arr[i] <= 0:
                continue
            
            if not in_position:
                # 买入条件：收盘价在买入区间 [MA-buy_k*ATR, MA]
                buy_low = ma[i] - buy_k * atr_arr[i]
                buy_high = ma[i]
                if buy_low <= closes[i] <= buy_high:
                    in_position = True
                    entry_price = closes[i]
                    highest_since_entry = closes[i]
                    trail_stop = closes[i] - trail_k * atr_arr[i]
                    trade_count += 1
            else:
                # 更新最高价和跟踪止盈
                if closes[i] > highest_since_entry:
                    highest_since_entry = closes[i]
                    trail_stop = highest_since_entry - trail_k * atr_arr[i]
                
                # 动态止盈击穿
                if closes[i] <= trail_stop:
                    ret = (closes[i] - entry_price) / entry_price
                    if ret > 0:
                        wins += 1
                    total_return *= (1 + ret)
                    in_position = False
                    if total_return > peak_value:
                        peak_value = total_return
                    dd = (peak_value - total_return) / peak_value
                    if dd > max_dd:
                        max_dd = dd
                    continue
                
                # 止损
                stop_price = entry_price - stop_k * atr_arr[i]
                abs_stop_price = entry_price * (1 - get_abs_stop(sym))
                effective_stop = max(stop_price, abs_stop_price)
                
                if closes[i] <= effective_stop:
                    ret = (closes[i] - entry_price) / entry_price
                    total_return *= (1 + ret)
                    in_position = False
                    if total_return > peak_value:
                        peak_value = total_return
                    dd = (peak_value - total_return) / peak_value
                    if dd > max_dd:
                        max_dd = dd
        
        # 计算 CAGR
        years = len(closes) / 252
        cagr = (total_return ** (1/years) - 1) * 100 if years > 0 and total_return > 0 else -999
        
        if cagr > best_cagr:
            best_cagr = cagr
            best_trail = {
                'trail_k': trail_k,
                'cagr': cagr,
                'total_return': total_return,
                'trades': trade_count,
                'win_rate': wins/trade_count*100 if trade_count > 0 else 0,
                'max_dd': max_dd * 100,
            }
    
    p5_results[sym] = best_trail
    if best_trail:
        print(f"  {sym:8s} 最优 trail_k={best_trail['trail_k']:.1f}  "
              f"CAGR={best_trail['cagr']:+.2f}%  "
              f"胜率={best_trail['win_rate']:.1f}%  "
              f"回撤={best_trail['max_dd']:.1f}%  "
              f"交易={best_trail['trades']}笔")

# ============================================================
# P6: 仓位分档规则验证
# ============================================================
print("\n" + "="*90)
print("P6: 仓位分档规则验证")
print("="*90)

# 分档策略对比
LOT_STRATEGIES = {
    '低概率(50%+50%)': [0.5, 0.5, 0],
    '中概率(50%+30%+20%)': [0.5, 0.3, 0.2],
    '高概率(33%+33%+34%)': [0.333, 0.333, 0.334],
}

# 对每只标的，模拟不同分档策略的绩效
p6_results = {}

for sym, (ma_label, buy_k, stop_k) in P3_OPTIMAL.items():
    if sym not in data:
        continue
    ohlcv = data[sym]
    closes = np.array([b['close'] for b in ohlcv])
    highs = np.array([b['high'] for b in ohlcv])
    lows = np.array([b['low'] for b in ohlcv])
    
    if len(closes) < 50:
        continue
    
    ma_period = int(ma_label.replace('MA',''))
    
    # 计算MA和ATR
    ma = np.array([np.nan]*len(closes))
    atr_arr = np.array([np.nan]*len(closes))
    tr_arr = np.array([np.nan]*len(closes))
    
    for i in range(len(closes)):
        if i >= ma_period - 1:
            ma[i] = np.mean(closes[i-ma_period+1:i+1])
        if i >= 1:
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i-1])
            tr3 = abs(lows[i] - closes[i-1])
            tr_arr[i] = max(tr1, tr2, tr3)
        if i >= 14:
            atr_arr[i] = np.mean(tr_arr[i-13:i+1])
    
    # 用最优 trail_k
    best_trail_k = p5_results[sym]['trail_k'] if sym in p5_results and p5_results[sym] else 2.5
    
    strat_comparison = {}
    
    for strat_name, ratios in LOT_STRATEGIES.items():
        total_return = 1.0
        in_position = False
        entry_prices = []
        highest_since_entry = 0
        trail_stop = 0
        position_size = 0  # 已投入仓位比例
        trade_count = 0
        wins = 0
        max_dd = 0
        peak_value = 1.0
        lot_index = 0  # 当前批次
        
        for i in range(ma_period + 14, len(closes)):
            if np.isnan(ma[i]) or np.isnan(atr_arr[i]) or atr_arr[i] <= 0:
                continue
            
            if not in_position:
                buy_low = ma[i] - buy_k * atr_arr[i]
                buy_high = ma[i]
                if buy_low <= closes[i] <= buy_high:
                    in_position = True
                    # 分批建仓
                    entry_prices = [closes[i]]
                    position_size = ratios[0]
                    highest_since_entry = closes[i]
                    trail_stop = closes[i] - best_trail_k * atr_arr[i]
                    lot_index = 0
                    trade_count += 1
            else:
                # 检查是否继续加仓（回踩更深）
                if lot_index < len(ratios) - 1 and ratios[lot_index+1] > 0:
                    # 第二/三批买入：价格比第一批更低
                    if closes[i] < entry_prices[0] * 0.98:  # 跌超2%触发加仓
                        entry_prices.append(closes[i])
                        position_size += ratios[lot_index + 1]
                        lot_index += 1
                        # 更新最高跟踪
                        if closes[i] > highest_since_entry:
                            highest_since_entry = closes[i]
                            trail_stop = highest_since_entry - best_trail_k * atr_arr[i]
                
                if closes[i] > highest_since_entry:
                    highest_since_entry = closes[i]
                    trail_stop = highest_since_entry - best_trail_k * atr_arr[i]
                
                # 动态止盈
                if closes[i] <= trail_stop:
                    avg_entry = np.mean(entry_prices)
                    ret = (closes[i] - avg_entry) / avg_entry
                    if ret > 0:
                        wins += 1
                    total_return *= (1 + ret * position_size)
                    in_position = False
                    if total_return > peak_value:
                        peak_value = total_return
                    dd = (peak_value - total_return) / peak_value
                    if dd > max_dd:
                        max_dd = dd
                    continue
                
                # 止损
                avg_entry = np.mean(entry_prices)
                stop_price = avg_entry - stop_k * atr_arr[i]
                abs_stop_price = avg_entry * (1 - get_abs_stop(sym))
                effective_stop = max(stop_price, abs_stop_price)
                
                if closes[i] <= effective_stop:
                    ret = (closes[i] - avg_entry) / avg_entry
                    total_return *= (1 + ret * position_size)
                    in_position = False
                    if total_return > peak_value:
                        peak_value = total_return
                    dd = (peak_value - total_return) / peak_value
                    if dd > max_dd:
                        max_dd = dd
        
        years = len(closes) / 252
        cagr = (total_return ** (1/years) - 1) * 100 if years > 0 and total_return > 0 else -999
        
        strat_comparison[strat_name] = {
            'cagr': cagr,
            'trades': trade_count,
            'win_rate': wins/trade_count*100 if trade_count > 0 else 0,
            'max_dd': max_dd * 100,
            'total_return': total_return,
        }
    
    p6_results[sym] = strat_comparison

# 汇总输出
print("\n逐标最优分档策略:")
print(f"{'标的':<8s} {'最优分档':<20s} {'CAGR':>8s} {'vs均分':>8s} {'胜率':>7s} {'回撤':>7s}")
print("-"*65)

for sym in p6_results:
    best_strat = None
    best_cagr = -999
    for strat_name, stats in p6_results[sym].items():
        if stats['cagr'] > best_cagr:
            best_cagr = stats['cagr']
            best_strat = strat_name
            best_stats = stats
    
    # 均分基准 (50%+50%)
    base_cagr = p6_results[sym].get('低概率(50%+50%)', {}).get('cagr', 0)
    delta = best_cagr - base_cagr
    
    print(f"  {sym:<8s} {best_strat:<20s} {best_cagr:+.2f}%  {delta:+.2f}pp  "
          f"{best_stats['win_rate']:.1f}%  {best_stats['max_dd']:.1f}%")

# 保存结果
output = {
    'p5_trail_k': p5_results,
    'p6_lot_strategies': {s: {k: v for k,v in ss.items()} for s, ss in p6_results.items()}
}
with open('/home/agent/cow/backtest_data/p5_p6_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print("\n✅ P5+P6 结果已保存至 backtest_data/p5_p6_results.json")
