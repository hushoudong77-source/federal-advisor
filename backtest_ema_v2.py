"""
均线组合买入区间回测 V2.0 — 邻近遍历 + 样本外校验

约束：
  1. 同结构邻近遍历：短10~15 / 中45~55 / 长80~95
  2. 样本外校验：前70%训练选最优参数 → 后30%验证
  3. 三层嵌套：短×中×长 全组合 × ATR乘数扫描

买入区间规则（不变）：
  - 锚线（中期均线）向上（较5日前）
  - 价格 ≤ 锚线（回踩）
  - 价格 ≥ 锚线 − m×ATR(14)
  - 短均线 > 长均线（多头排列）
"""

import tushare as ts
import os
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

pro = ts.pro_api(os.environ.get('TUSHARE_TOKEN'))

# ============================================================
# 参数空间
# ============================================================
# 步长缩小：短2步/中2步/长3步，控制总组合数
SHORT_RANGE = [10, 12, 14]          # 3档
MID_RANGE   = [45, 48, 51, 54]      # 4档
LONG_RANGE  = [80, 84, 88, 92]      # 4档
ATR_RANGE   = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

# 标的分组
CODES_A = {
    '518880': '518880.SH', '513910': '513910.SH', '513180': '513180.SH',
    '513770': '513770.SH', '510300': '510300.SH', '510500': '510500.SH',
    '588000': '588000.SH', '159915': '159915.SZ', '159545': '159545.SZ',
    '159302': '159302.SZ'
}
CODES_US = ['QQQ', 'IVV', 'IAU', 'BBJP', 'MUFG', 'EWY', 'FLIN', 'VNM']

# ============================================================
# 核心回测函数 — 单组参数 × 单段数据
# ============================================================
def run_segment(df, short_p, mid_p, long_p, atr_m, price_col='close'):
    """
    对一段数据运行买入区间规则，返回绩效指标。
    买入：信号日 → 次交易日开盘买入（简化：次日收盘）
    持有：固定20/40/60交易日
    """
    df = df.copy()
    
    # 计算EMA
    df['ema_s'] = df[price_col].ewm(span=short_p, adjust=False).mean()
    df['ema_m'] = df[price_col].ewm(span=mid_p, adjust=False).mean()
    df['ema_l'] = df[price_col].ewm(span=long_p, adjust=False).mean()
    
    # ATR(14)
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr14'] = df['tr'].rolling(14).mean()
    
    # 条件
    df['anchor_up'] = df['ema_m'] > df['ema_m'].shift(5)
    df['price_below'] = df[price_col] <= df['ema_m']
    df['buy_lower'] = df['ema_m'] - atr_m * df['atr14']
    df['price_above_lower'] = df[price_col] >= df['buy_lower']
    df['bull_align'] = df['ema_s'] > df['ema_l']
    
    df['buy_signal'] = (
        df['anchor_up'] & df['price_below'] &
        df['price_above_lower'] & df['bull_align']
    )
    
    # 需要最小预热
    min_pre = max(short_p, mid_p, long_p) + 14 + 10
    df_valid = df.iloc[min_pre:].reset_index(drop=True)
    
    if len(df_valid) < 50:
        return None
    
    # 收集买入信号触发后的持有收益
    returns_20, returns_40, returns_60 = [], [], []
    
    for i in range(len(df_valid)):
        if df_valid['buy_signal'].iloc[i]:
            entry = df_valid['close'].iloc[i]
            if i + 20 < len(df_valid):
                returns_20.append((df_valid['close'].iloc[i+20] / entry - 1) * 100)
            if i + 40 < len(df_valid):
                returns_40.append((df_valid['close'].iloc[i+40] / entry - 1) * 100)
            if i + 60 < len(df_valid):
                returns_60.append((df_valid['close'].iloc[i+60] / entry - 1) * 100)
    
    signal_count = int(df_valid['buy_signal'].sum())
    
    if signal_count == 0 or len(returns_40) < 3:
        return None
    
    result = {
        'signal_count': signal_count,
        'signal_pct': round(signal_count / len(df_valid) * 100, 2),
        'avg_20d': round(np.mean(returns_20), 2) if returns_20 else None,
        'avg_40d': round(np.mean(returns_40), 2) if returns_40 else None,
        'avg_60d': round(np.mean(returns_60), 2) if returns_60 else None,
        'wr_20d': round(sum(1 for r in returns_20 if r > 0) / len(returns_20) * 100, 1) if returns_20 else None,
        'wr_40d': round(sum(1 for r in returns_40 if r > 0) / len(returns_40) * 100, 1) if returns_40 else None,
        'wr_60d': round(sum(1 for r in returns_60 if r > 0) / len(returns_60) * 100, 1) if returns_60 else None,
        'n_20d': len(returns_20), 'n_40d': len(returns_40), 'n_60d': len(returns_60),
    }
    return result


# ============================================================
# 样本外校验主流程
# ============================================================
def backtest_with_oos(df, price_col='close'):
    """
    对一只标的执行完整回测：
      1. 前70%数据做训练集，遍历所有参数组合
      2. 选出训练集最优参数（按40日 avg_ret × win_rate 评分）
      3. 用该参数在后30%数据上运行，输出样本外绩效
    """
    n = len(df)
    split_idx = int(n * 0.70)
    df_train = df.iloc[:split_idx].copy()
    df_test = df.iloc[split_idx:].copy()
    
    # --- 训练集：全参数扫描 ---
    best_score = -999
    best_params = None
    best_train_result = None
    
    total_combos = len(SHORT_RANGE) * len(MID_RANGE) * len(LONG_RANGE) * len(ATR_RANGE)
    scanned = 0
    valid_combos = 0
    
    for s in SHORT_RANGE:
        for m in MID_RANGE:
            for l in LONG_RANGE:
                # 结构约束：短 < 中 < 长
                if not (s < m < l):
                    continue
                for a in ATR_RANGE:
                    scanned += 1
                    r = run_segment(df_train, s, m, l, a, price_col)
                    if r is None:
                        continue
                    valid_combos += 1
                    # 评分：40日平均收益 × 胜率
                    score = r['avg_40d'] * (r['wr_40d'] / 100)
                    if score > best_score:
                        best_score = score
                        best_params = (s, m, l, a)
                        best_train_result = r
    
    if best_params is None:
        return None
    
    # --- 样本外验证 ---
    s, m, l, a = best_params
    oos_result = run_segment(df_test, s, m, l, a, price_col)
    
    # --- 全周期回顾 ---
    full_result = run_segment(df, s, m, l, a, price_col)
    
    return {
        'params': best_params,
        'train': best_train_result,
        'oos': oos_result,
        'full': full_result,
        'train_days': len(df_train),
        'test_days': len(df_test),
        'valid_combos': valid_combos,
        'total_combos': scanned,
    }


# ============================================================
# 数据获取
# ============================================================
def get_a_data(code):
    df = pro.fund_daily(ts_code=code, start_date='20200101', end_date='20260509')
    if df is None or len(df) == 0:
        return None
    df = df.rename(columns={
        'trade_date': 'date', 'open': 'open', 'high': 'high',
        'low': 'low', 'close': 'close', 'vol': 'volume'
    })
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df[['open','high','low','close']] = df[['open','high','low','close']].astype(float)
    return df

def get_us_data(code):
    df = pro.us_daily(ts_code=code, start_date='20200101', end_date='20260509')
    if df is None or len(df) == 0:
        return None
    df = df.rename(columns={
        'trade_date': 'date', 'open': 'open', 'high': 'high',
        'low': 'low', 'close': 'close', 'vol': 'volume'
    })
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df[['open','high','low','close']] = df[['open','high','low','close']].astype(float)
    return df


# ============================================================
# 主循环
# ============================================================
print("=" * 130)
print("均线组合回测 V2.0 — 邻近遍历 + 70/30 样本外校验")
print(f"参数空间: 短{S_SHORT if (S_SHORT:=SHORT_RANGE) else SHORT_RANGE} × 中{MID_RANGE} × 长{LONG_RANGE} × ATR{ATR_RANGE}")
print(f"有效组合(短<中<长): {sum(1 for s in SHORT_RANGE for m in MID_RANGE for l in LONG_RANGE if s<m<l) * len(ATR_RANGE)}")
print("=" * 130)

all_results = []

# --- A股 ---
for name, code in CODES_A.items():
    df = get_a_data(code)
    if df is None:
        continue
    
    result = backtest_with_oos(df)
    if result is None:
        print(f"\n{name}: 无有效参数")
        continue
    
    s, m, l, a = result['params']
    tr = result['train']
    oos = result['oos']
    full = result['full']
    
    # 判断样本外是否稳健
    oos_ok = oos is not None and oos['avg_40d'] is not None
    if oos_ok:
        oos_score = oos['avg_40d'] * (oos['wr_40d'] / 100)
        train_score = tr['avg_40d'] * (tr['wr_40d'] / 100)
        degradation = (oos_score - train_score) / abs(train_score) * 100 if train_score != 0 else 0
        robust = "✅稳健" if oos_score > 0 and degradation > -50 else ("⚠️衰减" if oos_score > 0 else "🔴失效")
    else:
        oos_score = None
        degradation = None
        robust = "🔴无信号"
    
    print(f"\n{'─'*100}")
    print(f"  {name:8s}  |  最优参数: EMA{s}/{m}/{l}  ATR×{a:.1f}")
    print(f"  {'':8s}  |  训练集({result['train_days']}天): 信号{tr['signal_count']:3d}次  "
          f"40d={tr['avg_40d']:+.2f}% W{tr['wr_40d']:.0f}%  "
          f"60d={tr['avg_60d']:+.2f}% W{tr['wr_60d']:.0f}%")
    
    if oos_ok:
        print(f"  {'':8s}  |  样本外({result['test_days']}天): 信号{oos['signal_count']:3d}次  "
              f"40d={oos['avg_40d']:+.2f}% W{oos['wr_40d']:.0f}%  "
              f"60d={oos['avg_60d']:+.2f}% W{oos['wr_60d']:.0f}%  "
              f"→ {robust} (衰减{degradation:+.0f}%)")
    else:
        print(f"  {'':8s}  |  样本外({result['test_days']}天): 无有效信号 → {robust}")
    
    print(f"  {'':8s}  |  全周期: 信号{full['signal_count']:3d}次  "
          f"40d={full['avg_40d']:+.2f}% W{full['wr_40d']:.0f}%  "
          f"60d={full['avg_60d']:+.2f}% W{full['wr_60d']:.0f}%")
    
    all_results.append({
        'symbol': name, 'market': 'A',
        's': s, 'm': m, 'l': l, 'atr': a,
        'train_40d': tr['avg_40d'], 'train_wr40': tr['wr_40d'],
        'train_60d': tr['avg_60d'], 'train_wr60': tr['wr_60d'],
        'oos_40d': oos['avg_40d'] if oos_ok else None,
        'oos_wr40': oos['wr_40d'] if oos_ok else None,
        'oos_60d': oos['avg_60d'] if oos_ok else None,
        'oos_wr60': oos['wr_60d'] if oos_ok else None,
        'full_40d': full['avg_40d'], 'full_wr40': full['wr_40d'],
        'full_60d': full['avg_60d'], 'full_wr60': full['wr_60d'],
        'robust': robust,
        'degradation': degradation,
        'train_signals': tr['signal_count'],
        'oos_signals': oos['signal_count'] if oos_ok else 0,
        'full_signals': full['signal_count'],
    })

# --- 美股 ---
for code in CODES_US:
    df = get_us_data(code)
    if df is None:
        continue
    
    result = backtest_with_oos(df)
    if result is None:
        print(f"\n{code}: 无有效参数")
        continue
    
    s, m, l, a = result['params']
    tr = result['train']
    oos = result['oos']
    full = result['full']
    
    oos_ok = oos is not None and oos['avg_40d'] is not None
    if oos_ok:
        oos_score = oos['avg_40d'] * (oos['wr_40d'] / 100)
        train_score = tr['avg_40d'] * (tr['wr_40d'] / 100)
        degradation = (oos_score - train_score) / abs(train_score) * 100 if train_score != 0 else 0
        robust = "✅稳健" if oos_score > 0 and degradation > -50 else ("⚠️衰减" if oos_score > 0 else "🔴失效")
    else:
        oos_score = None
        degradation = None
        robust = "🔴无信号"
    
    print(f"\n{'─'*100}")
    print(f"  {code:8s}  |  最优参数: EMA{s}/{m}/{l}  ATR×{a:.1f}")
    print(f"  {'':8s}  |  训练集({result['train_days']}天): 信号{tr['signal_count']:3d}次  "
          f"40d={tr['avg_40d']:+.2f}% W{tr['wr_40d']:.0f}%  "
          f"60d={tr['avg_60d']:+.2f}% W{tr['wr_60d']:.0f}%")
    
    if oos_ok:
        print(f"  {'':8s}  |  样本外({result['test_days']}天): 信号{oos['signal_count']:3d}次  "
              f"40d={oos['avg_40d']:+.2f}% W{oos['wr_40d']:.0f}%  "
              f"60d={oos['avg_60d']:+.2f}% W{oos['wr_60d']:.0f}%  "
              f"→ {robust} (衰减{degradation:+.0f}%)")
    else:
        print(f"  {'':8s}  |  样本外({result['test_days']}天): 无有效信号 → {robust}")
    
    print(f"  {'':8s}  |  全周期: 信号{full['signal_count']:3d}次  "
          f"40d={full['avg_40d']:+.2f}% W{full['wr_40d']:.0f}%  "
          f"60d={full['avg_60d']:+.2f}% W{full['wr_60d']:.0f}%")
    
    all_results.append({
        'symbol': code, 'market': 'US',
        's': s, 'm': m, 'l': l, 'atr': a,
        'train_40d': tr['avg_40d'], 'train_wr40': tr['wr_40d'],
        'train_60d': tr['avg_60d'], 'train_wr60': tr['wr_60d'],
        'oos_40d': oos['avg_40d'] if oos_ok else None,
        'oos_wr40': oos['wr_40d'] if oos_ok else None,
        'oos_60d': oos['avg_60d'] if oos_ok else None,
        'oos_wr60': oos['wr_60d'] if oos_ok else None,
        'full_40d': full['avg_40d'], 'full_wr40': full['wr_40d'],
        'full_60d': full['avg_60d'], 'full_wr60': full['wr_60d'],
        'robust': robust,
        'degradation': degradation,
        'train_signals': tr['signal_count'],
        'oos_signals': oos['signal_count'] if oos_ok else 0,
        'full_signals': full['signal_count'],
    })


# ============================================================
# 汇总报告
# ============================================================
print("\n\n" + "=" * 130)
print("全量汇总 — 样本外校验结果")
print("=" * 130)

dfr = pd.DataFrame(all_results)

# 按稳健性分组
robust_list = dfr[dfr['robust'] == '✅稳健']
decay_list = dfr[dfr['robust'] == '⚠️衰减']
fail_list = dfr[dfr['robust'].isin(['🔴失效', '🔴无信号'])]

print(f"\n{'='*80}")
print(f"  ✅ 样本外稳健: {len(robust_list)} 只")
print(f"{'='*80}")
if len(robust_list) > 0:
    for _, row in robust_list.iterrows():
        print(f"  {row['symbol']:8s}  EMA{int(row['s'])}/{int(row['m'])}/{int(row['l'])} ATR×{row['atr']:.1f}  "
              f"训练40d={row['train_40d']:+.2f}% W{row['train_wr40']:.0f}%  "
              f"样本外40d={row['oos_40d']:+.2f}% W{row['oos_wr40']:.0f}%  "
              f"全周期={row['full_40d']:+.2f}% W{row['full_wr40']:.0f}%")

print(f"\n{'='*80}")
print(f"  ⚠️ 样本外衰减（但仍有正收益）: {len(decay_list)} 只")
print(f"{'='*80}")
if len(decay_list) > 0:
    for _, row in decay_list.iterrows():
        print(f"  {row['symbol']:8s}  EMA{int(row['s'])}/{int(row['m'])}/{int(row['l'])} ATR×{row['atr']:.1f}  "
              f"训练40d={row['train_40d']:+.2f}% W{row['train_wr40']:.0f}%  "
              f"样本外40d={row['oos_40d']:+.2f}% W{row['oos_wr40']:.0f}%  "
              f"衰减{row['degradation']:+.0f}%")

print(f"\n{'='*80}")
print(f"  🔴 样本外失效/无信号: {len(fail_list)} 只")
print(f"{'='*80}")
if len(fail_list) > 0:
    for _, row in fail_list.iterrows():
        oos_str = f"样本外40d={row['oos_40d']:+.2f}% W{row['oos_wr40']:.0f}%" if pd.notna(row['oos_40d']) else "样本外无信号"
        print(f"  {row['symbol']:8s}  EMA{int(row['s'])}/{int(row['m'])}/{int(row['l'])} ATR×{row['atr']:.1f}  "
              f"训练40d={row['train_40d']:+.2f}% W{row['train_wr40']:.0f}%  "
              f"{oos_str}")

# 参数分布
print(f"\n{'='*80}")
print(f"  参数分布统计")
print(f"{'='*80}")
print(f"  短周期: {dfr['s'].value_counts().sort_index().to_dict()}")
print(f"  中周期: {dfr['m'].value_counts().sort_index().to_dict()}")
print(f"  长周期: {dfr['l'].value_counts().sort_index().to_dict()}")
print(f"  ATR乘数: {dfr['atr'].value_counts().sort_index().to_dict()}")

print(f"\n✅ 回测完成 — {len(all_results)} 只标的")
