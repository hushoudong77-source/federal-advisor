"""
均线组合买入区间回测 V1.0
测试四组均线体系，统一买入区间逻辑：
  价格必须在买入区间内（贴近中长期锚线），且多头排列
对比基准：当前法典 MA20 体系

四组测试：
  G1: EMA5+EMA12+EMA20  (短线起爆)
  G2: EMA12+EMA50+EMA89 (波段主力)
  G3: SMA60+SMA120+EMA50 (中线趋势)
  G4: EMA12+EMA50 (极简双均线，基准对照)
  
买入区间规则（各组统一逻辑）：
  - 趋势前置：中长期均线必须向上（较5日前值上升）
  - 价格必须 ≤ 最近的中长期锚线（即"回踩到锚线附近"）
  - 价格必须 ≥ 锚线 - N×ATR（防止追入深跌）
  - 短期均线 > 长期均线（多头排列）
  
逐标独立回测，不统一参数。
"""

import tushare as ts
import os
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

pro = ts.pro_api(os.environ.get('TUSHARE_TOKEN'))

# ============================================================
# 标的分组
# ============================================================
CODES_A = {
    '518880': '518880.SH', '513910': '513910.SH', '513180': '513180.SH',
    '513770': '513770.SH', '510300': '510300.SH', '510500': '510500.SH',
    '588000': '588000.SH', '159915': '159915.SZ', '159545': '159545.SZ',
    '159302': '159302.SZ'
}
CODES_US = ['QQQ', 'IVV', 'IAU', 'BBJP', 'MUFG', 'EWY', 'FLIN', 'VNM']

# ATR乘数扫描范围 — 每组的"价格在多远范围内算买入区间"
ATR_RANGE = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

# ============================================================
# 均线计算
# ============================================================
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_sma(series, period):
    return series.rolling(period).mean()

# ============================================================
# 买入区间模拟（单组均线体系）
# ============================================================
def backtest_ma_system(df, ma_func, params, atr_m, name, price_col='close'):
    """
    df: 含OHLCV的DataFrame，index为日期（升序）
    ma_func: 'EMA' 或 'SMA'
    params: [(周期, 角色), ...]  角色: 'short'=短期攻击线, 'mid'=中期锚线, 'long'=长期趋势墙
    atr_m: ATR乘数
    name: 体系名称
    
    买入区间规则:
      1. 中长期锚线必须向上（较5日前）
      2. 价格 <= 锚线（回踩到锚线或更低）
      3. 价格 >= 锚线 - atr_m * ATR
      4. 短期均线 > 长期均线（多头排列）
      
    买入: 当天收盘触发买入区间 → 次日开盘买入
    卖出: 无卖出规则（纯测买入区间命中后的持有收益），持有至数据结束
    """
    df = df.copy()
    
    # 计算各均线
    for period, role in params:
        col = f'{ma_func}{period}'
        if ma_func == 'EMA':
            df[col] = calc_ema(df[price_col], period)
        else:
            df[col] = calc_sma(df[price_col], period)
    
    # ATR(14)
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr14'] = df['tr'].rolling(14).mean()
    
    # 识别锚线（中期均线 = 价格回踩目标）
    mid_params = [p for p in params if p[1] == 'mid']
    if not mid_params:
        # 如果没有明确标记mid，取中间那条
        mid_params = [params[len(params)//2]]
    
    mid_period = mid_params[0][0]
    mid_col = f'{ma_func}{mid_period}'
    
    # 长期均线（趋势墙）
    long_params = [p for p in params if p[1] == 'long']
    long_col = f'{ma_func}{long_params[0][0]}' if long_params else None
    
    # 短期均线
    short_params = [p for p in params if p[1] == 'short']
    short_col = f'{ma_func}{short_params[0][0]}' if short_params else None
    
    # --- 条件判断 ---
    # 1. 锚线向上（较5日前）
    df['anchor_up'] = df[mid_col] > df[mid_col].shift(5)
    
    # 2. 价格 <= 锚线（回踩）
    df['price_below_anchor'] = df[price_col] <= df[mid_col]
    
    # 3. 价格 >= 锚线 - m*ATR
    df['buy_lower'] = df[mid_col] - atr_m * df['atr14']
    df['price_above_lower'] = df[price_col] >= df['buy_lower']
    
    # 4. 多头排列：short > long（如果有的话）
    if short_col and long_col:
        df['bull_alignment'] = df[short_col] > df[long_col]
    elif short_col:
        # 只有short+mid的情况：short > mid
        df['bull_alignment'] = df[short_col] > df[mid_col]
    else:
        df['bull_alignment'] = True
    
    # 综合买入信号
    df['buy_signal'] = (
        df['anchor_up'] &
        df['price_below_anchor'] &
        df['price_above_lower'] &
        df['bull_alignment']
    )
    
    # 需要足够的历史数据
    min_period = max(p[0] for p in params) + 14 + 10  # 最大均线周期 + ATR + 缓冲
    df_valid = df.iloc[min_period:].copy()
    
    if len(df_valid) < 50:
        return None
    
    # --- 模拟买入 ---
    # 买入信号日 → 次日开盘买入（简化：次日收盘价）
    trades = []
    in_position = False
    entry_idx = None
    entry_price = None
    
    for i in range(len(df_valid) - 1):
        if not in_position and df_valid['buy_signal'].iloc[i]:
            # 次日买入
            entry_idx = i + 1
            entry_price = df_valid['close'].iloc[i + 1]
            in_position = True
        # 不设卖出，持有到底
    
    # 计算绩效
    total_days = len(df_valid)
    signal_days = df_valid['buy_signal'].sum()
    signal_pct = signal_days / total_days * 100
    
    # 模拟：每次买入信号触发后持有20个交易日
    returns_20d = []
    returns_40d = []
    returns_60d = []
    
    for i in range(len(df_valid)):
        if df_valid['buy_signal'].iloc[i]:
            entry = df_valid['close'].iloc[i]
            # 20日
            if i + 20 < len(df_valid):
                ret_20 = (df_valid['close'].iloc[i + 20] / entry - 1) * 100
                returns_20d.append(ret_20)
            # 40日
            if i + 40 < len(df_valid):
                ret_40 = (df_valid['close'].iloc[i + 40] / entry - 1) * 100
                returns_40d.append(ret_40)
            # 60日
            if i + 60 < len(df_valid):
                ret_60 = (df_valid['close'].iloc[i + 60] / entry - 1) * 100
                returns_60d.append(ret_60)
    
    result = {
        'total_days': total_days,
        'signal_count': int(signal_days),
        'signal_pct': round(signal_pct, 2),
        'avg_ret_20d': round(np.mean(returns_20d), 2) if returns_20d else None,
        'avg_ret_40d': round(np.mean(returns_40d), 2) if returns_40d else None,
        'avg_ret_60d': round(np.mean(returns_60d), 2) if returns_60d else None,
        'win_rate_20d': round(sum(1 for r in returns_20d if r > 0) / len(returns_20d) * 100, 1) if returns_20d else None,
        'win_rate_40d': round(sum(1 for r in returns_40d if r > 0) / len(returns_40d) * 100, 1) if returns_40d else None,
        'win_rate_60d': round(sum(1 for r in returns_60d if r > 0) / len(returns_60d) * 100, 1) if returns_60d else None,
        'n_trades_20d': len(returns_20d),
        'n_trades_40d': len(returns_40d),
        'n_trades_60d': len(returns_60d),
    }
    return result


# ============================================================
# 四组均线体系定义
# ============================================================
SYSTEMS = {
    'G1_EMA5_12_20': {
        'ma_func': 'EMA',
        'params': [(5, 'short'), (12, 'mid'), (20, 'long')],
        'desc': '短线起爆 EMA5+EMA12+EMA20'
    },
    'G2_EMA12_50_89': {
        'ma_func': 'EMA',
        'params': [(12, 'short'), (50, 'mid'), (89, 'long')],
        'desc': '波段主力 EMA12+EMA50+EMA89'
    },
    'G3_SMA60_120_EMA50': {
        'ma_func': 'SMA',
        'params': [(60, 'mid'), (120, 'long')],
        'desc': '中线趋势 SMA60+SMA120+EMA50'
    },
    'G4_EMA12_50': {
        'ma_func': 'EMA',
        'params': [(12, 'short'), (50, 'mid')],
        'desc': '极简双均线 EMA12+EMA50'
    },
}

# G3 特殊处理：SMA60/SMA120 用SMA算，EMA50 用EMA，锚线=SMA60
# 这里简化：G3只用SMA60和SMA120，锚线=SMA60，多头=SMA60>SMA120
SYSTEMS['G3_SMA60_120_EMA50'] = {
    'ma_func': 'SMA',
    'params': [(60, 'mid'), (120, 'long')],
    'desc': '中线趋势 SMA60+SMA120 (锚线SMA60)'
}


# ============================================================
# 数据获取
# ============================================================
def get_a_data(code):
    """获取A股ETF数据"""
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
    """获取美股ETF数据"""
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
# 主回测循环
# ============================================================
print("=" * 120)
print("均线组合买入区间回测 V1.0")
print("测试范围: 18只核心池标的 × 4组均线体系 × 7档ATR乘数(1.0~4.0)")
print("=" * 120)

all_results = []

# A股
for name, code in CODES_A.items():
    df = get_a_data(code)
    if df is None:
        print(f"\n{name}: 无数据，跳过")
        continue
    
    print(f"\n{'='*80}")
    print(f"  {name} ({code}) — {len(df)} 个交易日")
    print(f"{'='*80}")
    
    for sys_name, sys_cfg in SYSTEMS.items():
        best_atr = None
        best_ret = -999
        best_result = None
        
        for atr_m in ATR_RANGE:
            result = backtest_ma_system(
                df, sys_cfg['ma_func'], sys_cfg['params'],
                atr_m, sys_name
            )
            if result is None:
                continue
            
            # 综合评分：40日平均收益 × 胜率权重
            if result['avg_ret_40d'] is not None and result['n_trades_40d'] >= 3:
                score = result['avg_ret_40d'] * (result['win_rate_40d'] / 100)
                if score > best_ret:
                    best_ret = score
                    best_atr = atr_m
                    best_result = result
        
        if best_result:
            r = best_result
            print(f"  {sys_name:25s}  ATR×{best_atr:.1f}  | 信号{r['signal_count']:4d}次({r['signal_pct']:5.1f}%)  | "
                  f"20d avg={r['avg_ret_20d']:+.2f}% W{r['win_rate_20d']:.0f}%  | "
                  f"40d avg={r['avg_ret_40d']:+.2f}% W{r['win_rate_40d']:.0f}%  | "
                  f"60d avg={r['avg_ret_60d']:+.2f}% W{r['win_rate_60d']:.0f}%")
            
            all_results.append({
                'symbol': name,
                'market': 'A',
                'system': sys_name,
                'desc': sys_cfg['desc'],
                'best_atr': best_atr,
                **best_result
            })
        else:
            print(f"  {sys_name:25s}  无有效信号")

# 美股
for code in CODES_US:
    df = get_us_data(code)
    if df is None:
        print(f"\n{code}: 无数据，跳过")
        continue
    
    print(f"\n{'='*80}")
    print(f"  {code} — {len(df)} 个交易日")
    print(f"{'='*80}")
    
    for sys_name, sys_cfg in SYSTEMS.items():
        best_atr = None
        best_ret = -999
        best_result = None
        
        for atr_m in ATR_RANGE:
            result = backtest_ma_system(
                df, sys_cfg['ma_func'], sys_cfg['params'],
                atr_m, sys_name
            )
            if result is None:
                continue
            
            if result['avg_ret_40d'] is not None and result['n_trades_40d'] >= 3:
                score = result['avg_ret_40d'] * (result['win_rate_40d'] / 100)
                if score > best_ret:
                    best_ret = score
                    best_atr = atr_m
                    best_result = result
        
        if best_result:
            r = best_result
            print(f"  {sys_name:25s}  ATR×{best_atr:.1f}  | 信号{r['signal_count']:4d}次({r['signal_pct']:5.1f}%)  | "
                  f"20d avg={r['avg_ret_20d']:+.2f}% W{r['win_rate_20d']:.0f}%  | "
                  f"40d avg={r['avg_ret_40d']:+.2f}% W{r['win_rate_40d']:.0f}%  | "
                  f"60d avg={r['avg_ret_60d']:+.2f}% W{r['win_rate_60d']:.0f}%")
            
            all_results.append({
                'symbol': code,
                'market': 'US',
                'system': sys_name,
                'desc': sys_cfg['desc'],
                'best_atr': best_atr,
                **best_result
            })
        else:
            print(f"  {sys_name:25s}  无有效信号")

# ============================================================
# 汇总
# ============================================================
print("\n\n" + "=" * 120)
print("全量汇总 — 按均线体系分组")
print("=" * 120)

dfr = pd.DataFrame(all_results)
if len(dfr) > 0:
    for sys_name in ['G1_EMA5_12_20', 'G2_EMA12_50_89', 'G3_SMA60_120_EMA50', 'G4_EMA12_50']:
        subset = dfr[dfr['system'] == sys_name]
        if len(subset) == 0:
            continue
        desc = subset['desc'].iloc[0]
        print(f"\n{'─'*80}")
        print(f"  {sys_name}: {desc}")
        print(f"  覆盖 {len(subset)} 只标的")
        print(f"  40日平均收益: {subset['avg_ret_40d'].mean():+.2f}%  |  40日平均胜率: {subset['win_rate_40d'].mean():.0f}%")
        print(f"  60日平均收益: {subset['avg_ret_60d'].mean():+.2f}%  |  60日平均胜率: {subset['win_rate_60d'].mean():.0f}%")
        print(f"  平均信号次数: {subset['signal_count'].mean():.0f}次  |  平均信号占比: {subset['signal_pct'].mean():.1f}%")
        
        # 逐标明细
        for _, row in subset.iterrows():
            print(f"    {row['symbol']:8s}  ATR×{row['best_atr']:.1f}  "
                  f"信号{int(row['signal_count']):4d}次  "
                  f"40d={row['avg_ret_40d']:+.2f}% W{row['win_rate_40d']:.0f}%  "
                  f"60d={row['avg_ret_60d']:+.2f}% W{row['win_rate_60d']:.0f}%")

print("\n\n✅ 回测完成")
