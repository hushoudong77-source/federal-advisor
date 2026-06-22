#!/usr/bin/env python3
"""
联邦V1.2标准回测 — 三步漏斗最优指标搜索
标的: 512100 / 510500 / 588000
"""
import tushare as ts
import pandas as pd
import numpy as np
import json
from itertools import combinations

pro = ts.pro_api()  # 使用环境变量token

TS_CODES = {
    '512100': '512100.SH',
    '510500': '510500.SH',
    '588000': '588000.SH',
}
LABELS = {v: k for k, v in TS_CODES.items()}

def get_data(code):
    """拉取A股ETF日线"""
    df = pro.fund_daily(ts_code=code, start_date='20170101', end_date='20260622')
    if df is None or len(df) == 0:
        return None
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    for col in ['open','high','low','close','vol']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

def calc_indicators(df):
    """计算15个常用指标"""
    o,h,l,c,v = df['open'], df['high'], df['low'], df['close'], df['vol']
    
    # RSI(14)
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - 100/(1+rs)
    
    # KDJ
    low_n = l.rolling(9).min()
    high_n = h.rolling(9).max()
    rsv = (c - low_n) / (high_n - low_n) * 100
    df['k'] = rsv.ewm(com=2, adjust=False).mean()
    df['d'] = df['k'].ewm(com=2, adjust=False).mean()
    df['j'] = 3*df['k'] - 2*df['d']
    
    # MACD
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    df['macd_diff'] = ema12 - ema26
    df['macd_dea'] = df['macd_diff'].ewm(span=9).mean()
    df['macd_bar'] = 2 * (df['macd_diff'] - df['macd_dea'])
    
    # 布林带 (20,2)
    bb_ma = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df['bb_upper'] = bb_ma + 2*bb_std
    df['bb_lower'] = bb_ma - 2*bb_std
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / bb_ma
    
    # ATR(14)
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # MA
    for n in [5,10,20,40,60]:
        df[f'ma{n}'] = c.rolling(n).mean()
    
    # 成交量
    df['vol_ma5'] = v.rolling(5).mean()
    df['vol_ma20'] = v.rolling(20).mean()
    df['vol_ratio5'] = v / df['vol_ma5']
    df['vol_ratio20'] = v / df['vol_ma20']
    
    # OBV
    obv = (v * np.sign(c.diff())).cumsum()
    df['obv'] = obv
    df['obv_ma20'] = obv.rolling(20).mean()
    
    # CCI(14)
    tp = (h+l+c)/3
    df['cci'] = (tp - tp.rolling(14).mean()) / (0.015 * tp.rolling(14).std())
    
    # Williams %R(14)
    df['wr'] = (high_n - c) / (high_n - low_n) * -100
    
    # 乖离率
    df['bias20'] = (c - df['ma20']) / df['ma20'] * 100
    df['bias60'] = (c - df['ma60']) / df['ma60'] * 100
    
    return df

# 指标定义: {name: (condition_function, param_range)}
INDICATORS = {
    'RSI<N': ('rsi', lambda df, n: df['rsi'] < n, range(20, 45, 5)),
    'KDJ_J<N': ('j', lambda df, n: df['j'] < n, range(-10, 20, 5)),
    'KDJ_K<D': ('kd_cross', lambda df, n: df['k'] < df['d'], [0]),
    'MACD金叉': ('macd_cross', lambda df, n: (df['macd_bar'] > 0) & (df['macd_bar'].shift(1) <= 0), [0]),
    'BB<下轨': ('bb', lambda df, n: df['close'] < df['bb_lower'], [0]),
    'VOL>MA20×N': ('vol', lambda df, n: df['vol_ratio20'] > n, [1.0, 1.2, 1.5, 1.8, 2.0]),
    'VOL>MA5×N': ('vol5', lambda df, n: df['vol_ratio5'] > n, [1.0, 1.5, 2.0]),
    'OBV>MA20': ('obv', lambda df, n: df['obv'] > df['obv_ma20'], [0]),
    'CCI<N': ('cci', lambda df, n: df['cci'] < n, range(-200, -50, 50)),
    'WR<N': ('wr', lambda df, n: df['wr'] < n, range(-100, -60, 10)),
    'BIAS20<N': ('bias20', lambda df, n: df['bias20'] < n, [-2, -3, -5, -8, -10]),
    'BIAS60<N': ('bias60', lambda df, n: df['bias60'] < n, [-5, -8, -10, -15]),
    'MA5<MA20': ('ma520', lambda df, n: df['ma5'] < df['ma20'], [0]),
    'MA20<MA60': ('ma2060', lambda df, n: df['ma20'] < df['ma60'], [0]),
    'ATR>MA×N': ('atr', lambda df, n: df['atr'] > df['close']*n/100, [1, 2, 3]),
}

def compute_signals(df, combo, params):
    """计算指定指标组合的信号"""
    mask = pd.Series(True, index=df.index)
    for ind_name, param_value in zip(combo, params):
        ind_key = INDICATORS[ind_name][0]
        cond_fn = INDICATORS[ind_name][1]
        mask = mask & cond_fn(df, param_value)
    return mask

def federal_backtest(df, signals, label):
    """联邦V1.2标准回测 — 四状态仓位机"""
    trades = []
    
    # 找所有信号日
    signal_dates = df.index[signals & ~signals.shift(1).fillna(False)].tolist()
    
    for entry_idx in signal_dates:
        if entry_idx < 60:
            continue
        
        entry_close = df.loc[entry_idx, 'close']
        entry_date = df.loc[entry_idx, 'trade_date']
        atr = df.loc[entry_idx, 'atr']
        
        # 止损止盈
        stop_loss = entry_close - 2 * atr
        take_profit = entry_close + 3 * atr
        force_exit_idx = min(entry_idx + 60, len(df) - 1)
        
        # 正金字塔两层
        s1_entry = entry_close
        s2_trigger = entry_close - 1 * atr
        
        exit_idx = None
        exit_price = None
        exit_reason = None
        s2_entered = False
        s2_price = None
        
        for i in range(entry_idx + 1, force_exit_idx + 1):
            low = df.loc[i, 'low']
            high = df.loc[i, 'high']
            close = df.loc[i, 'close']
            
            # S2触发
            if not s2_entered and low <= s2_trigger:
                s2_entered = True
                s2_price = s2_trigger
            
            # 止损
            if low <= stop_loss:
                exit_idx = i
                exit_price = stop_loss
                exit_reason = '止损'
                break
            # 止盈
            if high >= take_profit:
                exit_idx = i
                exit_price = take_profit
                exit_reason = '止盈'
                break
        
        if exit_idx is None:
            exit_idx = force_exit_idx
            exit_price = df.loc[exit_idx, 'close']
            exit_reason = '60天退出'
        
        # 计算收益
        cost_rate = 0.007
        avg_entry = (s1_entry + (s2_price if s2_entered else s1_entry)) / 2
        gross_ret = (exit_price - avg_entry) / avg_entry
        net_ret = gross_ret - cost_rate
        
        trades.append({
            'entry_date': entry_date,
            'exit_date': df.loc[exit_idx, 'trade_date'],
            'entry_price': entry_close,
            'exit_price': exit_price,
            's2_entered': s2_entered,
            'avg_entry': avg_entry,
            'net_return': net_ret,
            'exit_reason': exit_reason,
            'days': exit_idx - entry_idx,
        })
    
    return trades

def simple_backtest(df, signals):
    """简单回测 — 固定20天平仓，用于漏斗二预筛选"""
    trades = []
    signal_dates = df.index[signals & ~signals.shift(1).fillna(False)].tolist()
    
    for entry_idx in signal_dates:
        if entry_idx < 60:
            continue
        entry_close = df.loc[entry_idx, 'close']
        exit_idx = min(entry_idx + 20, len(df) - 1)
        exit_close = df.loc[exit_idx, 'close']
        
        net_ret = (exit_close - entry_close) / entry_close - 0.007
        
        trades.append({
            'entry_date': df.loc[entry_idx, 'trade_date'],
            'net_return': net_ret,
            'days': exit_idx - entry_idx,
        })
    
    return trades

def calc_metrics(trades):
    """计算绩效指标"""
    if len(trades) < 3:
        return {'sharpe': -99, 'win_rate': 0, 'avg_return': 0, 'cum_return': 0, 'max_dd': 0, 'n_trades': len(trades)}
    
    returns = [t['net_return'] for t in trades]
    wins = sum(1 for r in returns if r > 0)
    
    cum = np.prod([1 + r for r in returns]) - 1
    
    # Sharpe (简化，假设无风险利率=0)
    avg_r = np.mean(returns)
    std_r = np.std(returns, ddof=1)
    sharpe = avg_r / std_r * np.sqrt(len(returns)) if std_r > 0 else -99
    
    # 最大回撤
    cumsum = np.cumprod([1 + r for r in returns])
    peak = np.maximum.accumulate(cumsum)
    dd = (cumsum - peak) / peak
    max_dd = dd.min()
    
    return {
        'sharpe': round(sharpe, 3),
        'win_rate': round(wins / len(returns) * 100, 1),
        'avg_return': round(avg_r * 100, 2),
        'cum_return': round(cum * 100, 1),
        'max_dd': round(max_dd * 100, 1),
        'n_trades': len(trades),
    }

def forward_window_validation(df, combo, params):
    """五窗口滚动前向验证"""
    df = df.copy()
    windows = [
        ('W1', '2018-01-01', '2019-12-31', '2020-01-01', '2020-12-31'),
        ('W2', '2019-01-01', '2020-12-31', '2021-01-01', '2021-12-31'),
        ('W3', '2020-01-01', '2021-12-31', '2022-01-01', '2022-12-31'),
        ('W4', '2021-01-01', '2022-12-31', '2023-01-01', '2023-12-31'),
        ('W5', '2022-01-01', '2023-12-31', '2024-01-01', '2025-06-22'),
    ]
    
    results = []
    for wname, train_start, train_end, test_start, test_end in windows:
        train_mask = (df['trade_date'] >= train_start) & (df['trade_date'] <= train_end)
        test_mask = (df['trade_date'] >= test_start) & (df['trade_date'] <= test_end)
        
        test_df = df[test_mask].reset_index(drop=True)
        signals = compute_signals(test_df, combo, params)
        trades = federal_backtest(test_df, signals, 'test')
        metrics = calc_metrics(trades)
        metrics['window'] = wname
        results.append(metrics)
    
    return results

# ====== MAIN ======
print("=" * 80)
print("🔬 联邦V1.2 — 三步漏斗最优指标搜索")
print("=" * 80)

all_data = {}
for label, code in TS_CODES.items():
    print(f"\n📊 拉取 {label}...")
    df = get_data(code)
    if df is None:
        print(f"  ❌ {label} 数据拉取失败")
        continue
    df = calc_indicators(df)
    df = df.dropna().reset_index(drop=True)
    all_data[label] = df
    print(f"  ✅ {label}: {len(df)}行, {df['trade_date'].min().date()} ~ {df['trade_date'].max().date()}")

print("\n" + "=" * 80)
print("🔽 漏斗一：指标相关性聚类 → 四类代表")
print("=" * 80)

# 四类代表指标组合
clusters = {
    '超卖': ['RSI<N'],
    '价格极端': ['BB<下轨'],
    '量能': ['VOL>MA20×N'],
    '动量': ['MACD金叉'],
}

# 生成单指标、两指标、三指标组合
single = [[c] for c in clusters.values()]
# flatten
single_flat = [[k] for k in clusters.values()]
double = list(combinations(list(clusters.values()), 2))
triple = list(combinations(list(clusters.values()), 3))

all_combos = single_flat + [list(c) for c in double] + [list(c) for c in triple]
print(f"组合总数: {len(all_combos)} (单指标4 + 两指标6 + 三指标4)")

print("\n" + "=" * 80)
print("🔽 漏斗二：简单回测预筛选（固定20天平仓）")
print("=" * 80)

# 参数网格
param_grids = {
    'RSI<N': [20, 25, 30, 35],
    'BB<下轨': [0],
    'VOL>MA20×N': [1.2, 1.5, 2.0],
    'MACD金叉': [0],
}

# 为每个标的跑所有组合
all_results = {}

for label, df in all_data.items():
    print(f"\n--- {label} ---")
    combo_results = []
    
    for combo in all_combos:
        # 生成参数组合
        param_lists = [param_grids[ind] for ind in combo]
        from itertools import product
        for params in product(*param_lists):
            signals = compute_signals(df, combo, list(params))
            trades = simple_backtest(df, signals)
            metrics = calc_metrics(trades)
            metrics['combo'] = ' + '.join(combo)
            metrics['params'] = str(params)
            metrics['n_signals'] = int(signals.sum())
            combo_results.append(metrics)
    
    # 按Sharpe排序
    combo_results.sort(key=lambda x: x['sharpe'], reverse=True)
    all_results[label] = combo_results
    
    # 展示Top 10
    print(f"  Top 10 (按简单Sharpe):")
    for i, r in enumerate(combo_results[:10]):
        print(f"    {i+1}. {r['combo']} | params={r['params']} | "
              f"Sharpe={r['sharpe']:.3f} | 胜率={r['win_rate']:.1f}% | "
              f"均收益={r['avg_return']:+.2f}% | 累计={r['cum_return']:+.1f}% | "
              f"N={r['n_trades']} | 信号={r['n_signals']}")

print("\n" + "=" * 80)
print("🔽 漏斗三：联邦V1.2标准回测 — 前5名组合 + 五窗口前向验证")
print("=" * 80)

# 三个标的的前5名组合取并集
top_combos = set()
for label in all_results:
    for r in all_results[label][:5]:
        top_combos.add((r['combo'], r['params']))

print(f"候选组合(去重后): {len(top_combos)}")

final_results = {}
for label, df in all_data.items():
    final_results[label] = []
    
    for combo_str, params_str in top_combos:
        combo = combo_str.split(' + ')
        params = eval(params_str)
        
        signals = compute_signals(df, combo, list(params))
        trades = federal_backtest(df, signals, label)
        metrics = calc_metrics(trades)
        
        # 五窗口前向验证
        fw = forward_window_validation(df, combo, list(params))
        fw_wins = sum(1 for w in fw if w['cum_return'] > 0)
        fw_avg_sharpe = np.mean([w['sharpe'] for w in fw if w['sharpe'] > -90])
        
        metrics['combo'] = combo_str
        metrics['params'] = params_str
        metrics['fw_wins'] = fw_wins
        metrics['fw_avg_sharpe'] = round(fw_avg_sharpe, 3)
        metrics['fw_details'] = fw
        
        final_results[label].append(metrics)

# 综合排名：三个标的的平均Sharpe
print("\n🏆 最终排名（三标联邦Sharpe均值）:")
combined_ranking = []
for combo_str, params_str in top_combos:
    combo = combo_str.split(' + ')
    params = eval(params_str)
    
    sharpes = []
    win_rates = []
    cum_returns = []
    n_trades_total = 0
    fw_wins_total = 0
    
    for label in all_data:
        matches = [r for r in final_results[label] if r['combo'] == combo_str and r['params'] == params_str]
        if matches:
            m = matches[0]
            if m['sharpe'] > -90:
                sharpes.append(m['sharpe'])
            win_rates.append(m['win_rate'])
            cum_returns.append(m['cum_return'])
            n_trades_total += m['n_trades']
            fw_wins_total += m['fw_wins']
    
    if sharpes:
        avg_sharpe = np.mean(sharpes)
        avg_win_rate = np.mean(win_rates)
        avg_cum = np.mean(cum_returns)
        combined_ranking.append({
            'combo': combo_str,
            'params': params_str,
            'avg_sharpe': round(avg_sharpe, 3),
            'avg_win_rate': round(avg_win_rate, 1),
            'avg_cum': round(avg_cum, 1),
            'total_trades': n_trades_total,
            'fw_wins': fw_wins_total,
            'per_symbol': {l: next((r for r in final_results[l] if r['combo']==combo_str and r['params']==params_str), None) for l in all_data}
        })

combined_ranking.sort(key=lambda x: x['avg_sharpe'], reverse=True)

for i, r in enumerate(combined_ranking[:10]):
    print(f"\n{'='*60}")
    print(f"🥇🥈🥉"[i] if i < 3 else f"  {i+1}.", end=" ")
    print(f"{r['combo']} | params={r['params']}")
    print(f"  三标均值: Sharpe={r['avg_sharpe']:.3f} | 胜率={r['avg_win_rate']:.1f}% | "
          f"累计={r['avg_cum']:+.1f}% | 总交易={r['total_trades']} | FW通过={r['fw_wins']}/15")
    
    for label in all_data:
        m = r['per_symbol'].get(label)
        if m:
            print(f"    {label}: Sharpe={m['sharpe']:.3f} | 胜率={m['win_rate']:.1f}% | "
                  f"累计={m['cum_return']:+.1f}% | N={m['n_trades']} | "
                  f"FW通过={m['fw_wins']}/5 | FW Sharpe={m['fw_avg_sharpe']:.3f}")

print("\n" + "=" * 80)
print("✅ 三步漏斗搜索完成")
print("=" * 80)
