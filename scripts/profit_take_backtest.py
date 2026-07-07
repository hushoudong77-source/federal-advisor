#!/usr/bin/env python3
"""
美股进攻策略止盈方案全量回测
模拟C4=H20×0.98入场 → 对比多种止盈方案的绩效
"""

import pandas as pd
import numpy as np

# ============================================================
# 参数配置
# ============================================================
STOP_MULT = {
    'QQQ': 8.0,
    'IVV': 2.0,
    'MUFG': 7.0,
}

COOLDOWN = 30

# ============================================================
# 数据加载
# ============================================================
def load_data(symbol):
    df = pd.read_csv(f'/tmp/{symbol}_daily.csv')
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr14'] = df['tr'].rolling(14).mean().shift(1)
    df['h20'] = df['close'].rolling(20).max().shift(1)
    df['c4'] = df['h20'] * 0.98
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma50'] = df['close'].rolling(50).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    return df

def find_entries(df):
    entries = []
    last_entry_idx = -COOLDOWN - 1
    for i in range(60, len(df)):
        if i - last_entry_idx <= COOLDOWN:
            continue
        if pd.isna(df['c4'].iloc[i]):
            continue
        if df['close'].iloc[i] <= df['c4'].iloc[i]:
            entries.append(i)
            last_entry_idx = i
    return entries

def simulate_trade(df, entry_idx, stop_mult, tp_config):
    entry_price = df['close'].iloc[entry_idx]
    entry_date = df['trade_date'].iloc[entry_idx]
    atr_entry = df['atr14'].iloc[entry_idx]
    if pd.isna(atr_entry) or atr_entry <= 0:
        return None
    
    stop_price = entry_price - stop_mult * atr_entry
    highest_close = entry_price
    tp_type = tp_config['type']
    max_hold = min(120, len(df) - entry_idx - 1)
    
    for j in range(entry_idx + 1, entry_idx + max_hold + 1):
        close = df['close'].iloc[j]
        exit_date = df['trade_date'].iloc[j]
        if close > highest_close:
            highest_close = close
        
        exit_reason = None
        exit_price = close
        
        # 止损
        if close <= stop_price:
            exit_reason = 'stop_loss'
            exit_price = stop_price
        
        # 固定%止盈
        elif tp_type == 'fixed_pct':
            if (close - entry_price) / entry_price >= tp_config['pct'] / 100:
                exit_reason = f'tp_{tp_config["pct"]}pct'
        
        # 阶梯止盈（简化：最后一档触发时全仓离场）
        elif tp_type == 'ladder':
            pnl_pct = (close - entry_price) / entry_price
            tiers = tp_config['tiers']
            for tier_pct, action in tiers:
                if pnl_pct >= tier_pct / 100:
                    if action == 'trail':
                        if (highest_close - close) / highest_close >= 0.20:
                            exit_reason = f'ladder_trail_dd20'
        
        # 动态回撤止盈
        elif tp_type == 'trailing':
            pnl_pct = (close - entry_price) / entry_price
            if pnl_pct >= tp_config['activation_pct'] / 100:
                trail_stop = highest_close - tp_config['trail_atr'] * atr_entry
                if close <= trail_stop:
                    exit_reason = f'trail_{tp_config["activation_pct"]}_{tp_config["trail_atr"]}x'
        
        # MA止盈
        elif tp_type == 'ma':
            ma_val = df[tp_config['ma_col']].iloc[j]
            if not pd.isna(ma_val) and close >= ma_val:
                exit_reason = f'ma_{tp_config["ma_col"]}'
        
        if exit_reason:
            hold_days = j - entry_idx
            pnl_pct = (exit_price - entry_price) / entry_price
            return {
                'entry_date': entry_date, 'exit_date': exit_date,
                'entry_price': entry_price, 'exit_price': exit_price,
                'pnl_pct': pnl_pct, 'hold_days': hold_days,
                'exit_reason': exit_reason, 'highest_close': highest_close,
                'max_pnl_pct': (highest_close - entry_price) / entry_price,
            }
    
    # 120天强制离场
    if entry_idx + max_hold < len(df):
        j = entry_idx + max_hold
        exit_price = df['close'].iloc[j]
        exit_date = df['trade_date'].iloc[j]
        return {
            'entry_date': entry_date, 'exit_date': exit_date,
            'entry_price': entry_price, 'exit_price': exit_price,
            'pnl_pct': (exit_price - entry_price) / entry_price,
            'hold_days': max_hold, 'exit_reason': 'force_120d',
            'highest_close': highest_close,
            'max_pnl_pct': (highest_close - entry_price) / entry_price,
        }
    return None

def run_backtest(df, stop_mult, tp_config):
    entries = find_entries(df)
    trades = []
    for e in entries:
        r = simulate_trade(df, e, stop_mult, tp_config)
        if r:
            trades.append(r)
    if not trades:
        return None
    pnls = [t['pnl_pct'] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    total = len(pnls)
    pos = [p for p in pnls if p > 0]
    neg = [p for p in pnls if p < 0]
    return {
        'total_trades': total, 'wins': wins,
        'win_rate': wins / total * 100,
        'avg_return': np.mean(pnls) * 100,
        'total_return': sum(pnls) * 100,
        'max_win': max(pnls) * 100,
        'max_loss': min(pnls) * 100,
        'avg_hold': np.mean([t['hold_days'] for t in trades]),
        'sharpe': np.mean(pnls) / np.std(pnls) if np.std(pnls) > 0 else 0,
        'pf': abs(sum(pos) / sum(neg)) if neg and sum(neg) != 0 else float('inf'),
        'reasons': dict(pd.Series([t['exit_reason'] for t in trades]).value_counts()),
    }

# ============================================================
# 方案定义
# ============================================================
configs = [
    {'type': 'none', 'name': '基线(仅止损)'},
]

for pct in [5, 8, 10, 12, 15, 20, 25, 30, 40, 50]:
    configs.append({'type': 'fixed_pct', 'pct': pct, 'name': f'固定+{pct}%止盈'})

configs.append({'type': 'ladder', 'tiers': [(10,'breakeven'),(20,'sell_half'),(30,'sell_remaining_half'),(50,'trail')],
                'name': '阶梯(当前:+10保本→+20砍半→+30再砍半→+50跟踪)'})

for t1,t2,t3 in [(10,20,30),(10,25,40),(15,25,40),(10,20,50),(10,30,50),(15,30,50)]:
    configs.append({'type': 'ladder', 'tiers': [(t1,'breakeven'),(t2,'sell_half'),(t3,'sell_remaining_half'),(50,'trail')],
                    'name': f'阶梯(+{t1}保本→+{t2}砍半→+{t3}再砍半→+50跟踪)'})

for act in [10, 15, 20]:
    for tr in [1.5, 2.0, 2.5, 3.0]:
        configs.append({'type': 'trailing', 'activation_pct': act, 'trail_atr': tr,
                        'name': f'动态回撤(激活+{act}%/回撤{tr}×ATR)'})

for ma in ['ma20', 'ma50', 'ma60']:
    configs.append({'type': 'ma', 'ma_col': ma, 'name': f'{ma.upper()}止盈'})

# ============================================================
# 运行
# ============================================================
print("=" * 120)
print("美股进攻策略止盈方案全量回测 (Tushare 2018-2026)")
print("=" * 120)

for symbol in ['QQQ', 'IVV', 'MUFG']:
    print(f"\n{'='*80}")
    print(f"  {symbol}  (止损={STOP_MULT[symbol]}×ATR, 冷却{COOLDOWN}天)")
    print(f"{'='*80}")
    df = load_data(symbol)
    
    results = []
    for cfg in configs:
        r = run_backtest(df, STOP_MULT[symbol], cfg)
        if r:
            results.append((cfg['name'], r))
    
    results.sort(key=lambda x: x[1]['total_return'], reverse=True)
    
    print(f"\n{'止盈方案':<55} {'笔数':>4} {'胜率':>6} {'累计':>8} {'均收益':>7} {'最大盈':>7} {'最大亏':>7} {'PF':>6} {'SR':>6} {'均持':>5}")
    print("-" * 115)
    
    for name, r in results[:25]:
        print(f"{name:<55} {r['total_trades']:>4} {r['win_rate']:>5.1f}% {r['total_return']:>7.1f}% {r['avg_return']:>6.2f}% {r['max_win']:>6.1f}% {r['max_loss']:>6.1f}% {r['pf']:>5.2f} {r['sharpe']:>5.3f} {r['avg_hold']:>4.0f}")
    
    baseline = next(r for n, r in results if n == '基线(仅止损)')
    current = next((r for n, r in results if '当前' in n), None)
    
    print(f"\n基线: {baseline['total_trades']}笔 累计{baseline['total_return']:.1f}% 胜率{baseline['win_rate']:.1f}%")
    if current:
        diff = current['total_return'] - baseline['total_return']
        print(f"当前阶梯: {current['total_trades']}笔 累计{current['total_return']:.1f}% vs基线 {diff:+.1f}pp")

print("\nDone.")
