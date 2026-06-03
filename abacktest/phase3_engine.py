#!/usr/bin/env python3
"""
Phase 3 全量绩效回测 — V5.8.2r11 完整规则引擎
范围: 核心12标, 2018-01-02 ~ 2026-05-15
"""
import pandas as pd
import numpy as np
import os, sys, warnings
warnings.filterwarnings('ignore')

DATA_DIR = '/home/agent/cow/data/v12_backtest'
US10Y_PATH = '/home/agent/cow/data/us10y_2018_2026.csv'

# ============================================================
# CONFIG: V5.8.2r11 全池参数矩阵
# ============================================================

# 进攻策略参数 (仅进攻候选标的)
SPEARHEAD_PARAMS = {
    'QQQ':  {'atr_mul': 2.5, 'vol_group': 'high', 'max_pct': 7.5},
    'IVV':  {'atr_mul': 2.5, 'vol_group': 'high', 'max_pct': 7.5},
    'BBJP': {'atr_mul': 1.5, 'vol_group': 'low',  'max_pct': 5.0},  # BBJP特殊上限5%
    'MUFG': {'atr_mul': 2.0, 'vol_group': 'mid',  'max_pct': 7.5},
    'EWY':  {'atr_mul': 2.5, 'vol_group': 'high', 'max_pct': 7.5, 'windfall': 15.0},
    'VNM':  {'atr_mul': 2.0, 'vol_group': 'mid',  'max_pct': 7.5},
    'FLIN': {'atr_mul': 2.5, 'vol_group': 'high', 'max_pct': 7.5},
}

# 反击策略参数 (全池19标除IAU/518880豁免)
COUNTERPUNCH_PARAMS = {
    'QQQ':  {'anchor': 20, 'buy_k': 2.0, 'tier': 'T2', 'max_pct': 10.0},
    'IVV':  {'anchor': 20, 'buy_k': 4.0, 'tier': 'T2', 'max_pct': 10.0},
    'BBJP': {'anchor': 40, 'buy_k': 2.5, 'tier': 'T2', 'max_pct': 5.0},
    'MUFG': {'anchor': 40, 'buy_k': 0.5, 'tier': 'T1', 'max_pct': 10.0},
    'EWY':  {'anchor': 40, 'buy_k': 3.0, 'tier': 'T2', 'max_pct': 10.0},
    'VNM':  {'anchor': 20, 'buy_k': 0.5, 'tier': 'T1', 'max_pct': 10.0},
    'FLIN': {'anchor': 20, 'buy_k': 1.0, 'tier': 'T1', 'max_pct': 10.0},
    'SMIN': {'anchor': 20, 'buy_k': 4.0, 'tier': 'T2', 'max_pct': 2.0},
    '510300': {'anchor': 60, 'buy_k': 5.0, 'tier': 'T2', 'max_pct': 10.0},
    '510500': {'anchor': 60, 'buy_k': 5.0, 'tier': 'T2', 'max_pct': 10.0},
    '159915': {'anchor': 10, 'buy_k': 1.5, 'tier': 'T2', 'max_pct': 10.0},
    '588000': {'anchor': 60, 'buy_k': 5.0, 'tier': 'T2', 'max_pct': 10.0},
    '513770': {'anchor': 60, 'buy_k': 2.5, 'tier': 'T2', 'max_pct': 10.0},
    '513180': {'anchor': 20, 'buy_k': 0.5, 'tier': 'T1', 'max_pct': 10.0},
    '513910': {'anchor': 60, 'buy_k': 4.5, 'tier': 'T2', 'max_pct': 10.0},
    '159545': {'anchor': 40, 'buy_k': 4.5, 'tier': 'T2', 'max_pct': 10.0},
    '159302': {'anchor': 60, 'buy_k': 4.0, 'tier': 'T2', 'max_pct': 10.0},
}

# 止盈参数
TIER_PROFIT = {
    'T1': {'trigger': 3.0, 'fallback': 1.0},
    'T2': {'trigger': 5.0, 'fallback': 2.0},
}

# 乖离阈值
DEVIATION_THRESHOLDS = {
    'QQQ': 50, 'IVV': 50, '510300': 50, '510500': 50, '513910': 50, '159545': 50, '159302': 50,
    '159915': 70, '588000': 70, '513180': 70, '513770': 70,
    'VNM': 80, 'FLIN': 80, 'EWY': 80, 'BBJP': 80, 'MUFG': 80,
}

# 速率预警禁开列表
VIX_SURGE_BAN = {'159915', '588000'}
US10Y_SURGE_BAN = {'EWY', 'BBJP', 'IAU', '513180', '513770'}

# 固定层
FIXED_PCT = 0.30
CASH_SOVEREIGNTY = 0.05

# 全局初始资金
INITIAL_CAPITAL = 1_000_000

print("Engine config loaded.")

def load_data(symbol, exclude_years=None):
    """加载标的日线数据，可选排除指定年份"""
    path = os.path.join(DATA_DIR, f'{symbol}_daily.csv')
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    
    # 排除指定年份
    if exclude_years:
        df = df[~df['date'].dt.year.isin(exclude_years)].reset_index(drop=True)
    
    # 标准化列名
    col_map = {'ts_code': 'symbol', 'pct_change': 'pct_chg'}
    df = df.rename(columns=col_map)
    if 'close' not in df.columns and 'Close' in df.columns:
        df = df.rename(columns={'Close': 'close', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Volume': 'volume'})
    
    df = df[df['close'].notna()].reset_index(drop=True)
    return df

def compute_indicators(df):
    """计算所有技术指标"""
    df = df.copy()
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values if 'volume' in df.columns else np.ones(len(df))
    
    n = len(df)
    
    # EMA
    df['ema30'] = pd.Series(close).ewm(span=30, adjust=False).mean().values
    df['ema50'] = pd.Series(close).ewm(span=50, adjust=False).mean().values
    df['ema150'] = pd.Series(close).ewm(span=150, adjust=False).mean().values
    
    # ATR(14) Wilder
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = np.zeros(n)
    atr[14] = tr[1:15].mean()
    for i in range(15, n):
        atr[i] = (atr[i-1] * 13 + tr[i]) / 14
    df['atr14'] = atr
    
    # H20 (不含当日)
    h20 = np.zeros(n)
    for i in range(20, n):
        h20[i] = close[max(0,i-20):i].max()
    df['h20'] = h20
    
    # 20日均量
    vma20 = np.zeros(n)
    for i in range(20, n):
        vma20[i] = volume[max(0,i-20):i].mean()
    df['vma20'] = vma20
    
    # MA锚线
    for period in [10, 20, 40, 60]:
        df[f'ma{period}'] = df['close'].rolling(period).mean()
    
    # 乖离率
    df['deviation'] = np.where(df['ema150'] > 0, (close - df['ema150'].values) / df['ema150'].values * 100, 0)
    
    # EMA代理
    df['c1_proxy'] = (df['ema50'] > df['ema150']).astype(int)
    df['c2_proxy'] = (df['ema30'] > df['ema50']).astype(int)
    
    # 昨收
    df['prev_close'] = df['close'].shift(1)
    df['prev_close'].iloc[0] = df['open'].iloc[0]
    
    return df

print("Indicator functions loaded.")

def load_us10y():
    """加载US10Y数据并计算跳升"""
    df = pd.read_csv(US10Y_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df['us10y'] = df['y10'].astype(float)
    df['us10y_surge'] = df['us10y'].diff() * 100  # bp
    return df

def check_macro_gate(date, us10y_df, vix_df=None):
    """
    宏观闸检查
    返回: {'global': bool, 'banned_set': set}
    global=True -> 全池关闭
    banned_set -> 禁开标的集合
    """
    row = us10y_df[us10y_df['date'] == date]
    if len(row) == 0:
        return {'global': False, 'banned_set': set()}
    
    us10y_val = row['us10y'].values[0]
    us10y_surge = row['us10y_surge'].values[0]
    
    # 0-A: 全局终极熔断
    global_melt = us10y_val >= 5.00
    
    # 0-B: 速率预警
    banned = set()
    if not np.isnan(us10y_surge) and us10y_surge > 8:
        banned |= US10Y_SURGE_BAN
    
    # VIX (暂缺，跳过)
    
    return {'global': global_melt, 'banned_set': banned}

def check_deviation_block(symbol, deviation):
    """极端乖离拦截"""
    threshold = DEVIATION_THRESHOLDS.get(symbol, 50)
    return abs(deviation) > threshold

def compute_buy_zone(symbol, df, idx):
    """计算买入区间 [anchor - buy_k*ATR, anchor]"""
    params = COUNTERPUNCH_PARAMS.get(symbol)
    if not params:
        return None, None
    
    anchor_period = params['anchor']
    buy_k = params['buy_k']
    anchor_val = df[f'ma{anchor_period}'].iloc[idx]
    atr_val = df['atr14'].iloc[idx]
    
    if pd.isna(anchor_val) or pd.isna(atr_val) or atr_val == 0:
        return None, None
    
    lower = anchor_val - buy_k * atr_val
    upper = anchor_val
    return lower, upper

print("Macro gate functions loaded.")

def run_spearhead_backtest(symbol, df, us10y_df, capital=INITIAL_CAPITAL):
    """进攻策略回测"""
    params = SPEARHEAD_PARAMS.get(symbol)
    if not params:
        return []
    
    atr_mul = params['atr_mul']
    max_pct = params['max_pct']
    windfall = params.get('windfall', None)
    
    trades = []
    in_position = False
    entry_price = 0
    entry_idx = 0
    highest_since = 0
    trailing_stop = 0
    batch_num = 0  # 0=未建仓, 1,2,3
    position_pct = 0
    attack_locked = False
    
    n = len(df)
    for i in range(150, n):  # 至少150条EMA稳定
        date = df['date'].iloc[i]
        close = df['close'].iloc[i]
        prev_close = df['prev_close'].iloc[i]
        atr = df['atr14'].iloc[i]
        h20 = df['h20'].iloc[i]
        vma20 = df['vma20'].iloc[i]
        vol = df['volume'].iloc[i] if 'volume' in df.columns else 1e9
        dev = df['deviation'].iloc[i]
        
        c1 = df['c1_proxy'].iloc[i] == 1
        c2 = df['c2_proxy'].iloc[i] == 1
        c3 = close > df['ema50'].iloc[i]
        c4_close = close >= h20 * 0.995
        c4_vol = vol > vma20
        c4_up = close > prev_close
        c4 = c4_close and c4_vol and c4_up
        
        # 宏观闸
        gate = check_macro_gate(date, us10y_df)
        global_melt = gate['global']
        
        if not in_position:
            # 入场检查
            if global_melt:
                continue
            if check_deviation_block(symbol, dev):
                continue
            if symbol in gate['banned_set']:
                continue
            
            if c1 and c2 and c3 and c4:
                # 反等价鞅建仓
                if batch_num == 0:
                    batch_pct = 0.03
                elif batch_num == 1:
                    batch_pct = 0.02
                else:
                    batch_pct = 0.01
                
                # 检查上限
                total_after = position_pct + batch_pct
                if total_after > max_pct / 100:
                    continue  # 超出上限不建仓
                
                # 1%风险公式计算股数
                risk_amount = capital * 0.01
                stop_distance = atr_mul * atr
                if stop_distance <= 0:
                    continue
                shares = risk_amount / stop_distance
                cost = shares * close
                
                # 检查资金
                position_pct += batch_pct
                position_cost_pct = cost / capital
                
                entry_price = close
                entry_idx = i
                highest_since = close
                trailing_stop = close - atr_mul * atr
                in_position = True
                attack_locked = True
                batch_num += 1
                
                trades.append({
                    'symbol': symbol, 'type': 'ENTRY', 'date': date,
                    'price': close, 'shares': shares, 'batch': batch_num,
                    'batch_pct': batch_pct, 'position_pct': position_pct,
                    'trailing_stop': trailing_stop
                })
        else:
            # 持仓管理
            highest_since = max(highest_since, close)
            
            # EWY暴利锁定
            if symbol == 'EWY' and windfall:
                pnl_pct = (close - entry_price) / entry_price * 100
                if pnl_pct > windfall:
                    effective_atr_mul = 1.5
                else:
                    effective_atr_mul = atr_mul
            else:
                effective_atr_mul = atr_mul
            
            trailing_stop = max(trailing_stop, highest_since - effective_atr_mul * atr)
            
            # SRC检查 — 按编号升序: SRC-1 > SRC-2 > SRC-3 > SRC-4 > SRC-5 > SRC-6
            exit_reason = None
            pnl_pct_now = (close - entry_price) / entry_price * 100
            
            # SRC-4: 跳空缺口 (简化: 收盘<昨收×0.95 且 无回补)
            gap_down = close < prev_close * 0.95 if prev_close > 0 else False
            
            # SRC-1: 追踪止损 (编号最小，优先级最高)
            if close <= trailing_stop:
                exit_reason = 'SRC-1_TRAILING_STOP'
            # SRC-2: 8%硬止损
            elif pnl_pct_now <= -8:
                exit_reason = 'SRC-2_HARD_STOP'
            # SRC-3: C1/C2代理反转
            elif not c1 or not c2:
                exit_reason = 'SRC-3_EMA_REVERSAL'
            # SRC-4: 跳空缺口
            elif gap_down:
                exit_reason = 'SRC-4_GAP_DOWN'
            # SRC-5: 宏观熔断
            elif global_melt:
                exit_reason = 'SRC-5_MACRO_MELT'
            # SRC-6: 15%绝对底线
            elif pnl_pct_now <= -15:
                exit_reason = 'SRC-6_ABSOLUTE'
            
            if exit_reason:
                pnl_pct = (close - entry_price) / entry_price * 100
                trades.append({
                    'symbol': symbol, 'type': 'EXIT', 'date': date,
                    'price': close, 'entry_price': entry_price,
                    'pnl_pct': pnl_pct, 'reason': exit_reason,
                    'hold_days': i - entry_idx, 'position_pct': position_pct
                })
                in_position = False
                entry_price = 0
                entry_idx = 0
                highest_since = 0
                trailing_stop = 0
                batch_num = 0
                position_pct = 0
                attack_locked = False
    
    # 未平仓处理
    if in_position:
        close = df['close'].iloc[-1]
        pnl_pct = (close - entry_price) / entry_price * 100
        trades.append({
            'symbol': symbol, 'type': 'EXIT', 'date': df['date'].iloc[-1],
            'price': close, 'entry_price': entry_price,
            'pnl_pct': pnl_pct, 'reason': 'END_OF_DATA',
            'hold_days': n - 1 - entry_idx, 'position_pct': position_pct
        })
    
    return trades

print("Spearhead backtest loaded.")

def run_counterpunch_backtest(symbol, df, us10y_df, capital=INITIAL_CAPITAL):
    """反击策略回测"""
    params = COUNTERPUNCH_PARAMS.get(symbol)
    if not params:
        return []
    
    anchor_period = params['anchor']
    buy_k = params['buy_k']
    tier = params['tier']
    max_pct = params['max_pct']
    tier_params = TIER_PROFIT[tier]
    
    trades = []
    in_position = False
    entry_prices = []
    entry_dates = []
    total_shares = 0
    total_cost = 0
    position_pct = 0
    batch_executed = 0  # 0,1,2,3
    highest_since = 0
    trailing_stop = 0
    entry_idx = 0
    paused = False
    
    n = len(df)
    for i in range(150, n):
        date = df['date'].iloc[i]
        close = df['close'].iloc[i]
        atr = df['atr14'].iloc[i]
        dev = df['deviation'].iloc[i]
        c1 = df['c1_proxy'].iloc[i] == 1
        c2 = df['c2_proxy'].iloc[i] == 1
        
        # 宏观闸
        gate = check_macro_gate(date, us10y_df)
        global_melt = gate['global']
        
        buy_lower, buy_upper = compute_buy_zone(symbol, df, i)
        if buy_lower is None:
            continue
        
        in_zone = buy_lower <= close <= buy_upper
        
        if not in_position:
            if global_melt:
                continue
            if check_deviation_block(symbol, dev):
                continue
            if symbol in gate['banned_set']:
                continue
            
            # R1: 结构非多头
            r1 = (not c1) or (not c2)
            if not r1:
                continue
            
            # R2: 落入买入区间
            if not in_zone:
                continue
            
            # 三分批建仓: 首批
            batch_pct = max_pct / 100 / 3
            risk_budget = capital * batch_pct
            shares = risk_budget / close if close > 0 else 0
            cost = shares * close
            
            entry_prices = [close]
            entry_dates = [date]
            total_shares = shares
            total_cost = cost
            position_pct = batch_pct
            batch_executed = 1
            highest_since = close
            trailing_stop = close - 2.0 * atr
            in_position = True
            entry_idx = i
            paused = False
            
            trades.append({
                'symbol': symbol, 'type': 'ENTRY', 'date': date,
                'price': close, 'shares': shares, 'batch': 1,
                'batch_pct': batch_pct * 100, 'position_pct': position_pct * 100,
                'trailing_stop': trailing_stop, 'strategy': 'COUNTERPUNCH'
            })
        else:
            # 持仓管理 - 离场检查
            highest_since = max(highest_since, close)
            trailing_stop = max(trailing_stop, highest_since - 2.0 * atr)
            
            avg_entry = total_cost / total_shares if total_shares > 0 else entry_prices[0]
            pnl_pct = (close - avg_entry) / avg_entry * 100
            
            exit_reason = None
            
            # SRC按编号升序: SRC-1 > SRC-2 > SRC-3 > SRC-4 > SRC-5 > SRC-6
            anchor_val = df[f'ma{anchor_period}'].iloc[i]
            
            # SRC-1: 追踪止损 (编号最小，优先级最高)
            if close <= trailing_stop:
                exit_reason = 'SRC-1_TRAILING_STOP'
            # SRC-2: 锚线跌破
            elif not pd.isna(anchor_val) and close < anchor_val - 2 * atr:
                exit_reason = 'SRC-2_ANCHOR_BREAK'
            # SRC-3: 盈利回吐止盈
            elif pnl_pct >= tier_params['trigger']:
                exit_reason = f'SRC-3_PROFIT_{tier_params["trigger"]}%'
            # SRC-4: EMA双死叉
            elif (not c1) and (not c2):
                exit_reason = 'SRC-4_DEATH_CROSS'
            # SRC-5: 宏观熔断
            elif global_melt:
                exit_reason = 'SRC-5_MACRO_MELT'
            # SRC-6: 15%绝对底线
            elif pnl_pct <= -15:
                exit_reason = 'SRC-6_ABSOLUTE'
            
            if exit_reason:
                trades.append({
                    'symbol': symbol, 'type': 'EXIT', 'date': date,
                    'price': close, 'avg_entry': avg_entry,
                    'pnl_pct': pnl_pct, 'reason': exit_reason,
                    'hold_days': i - entry_idx, 'position_pct': position_pct * 100,
                    'batches': batch_executed
                })
                in_position = False
                entry_prices = []
                total_shares = 0
                total_cost = 0
                position_pct = 0
                batch_executed = 0
                paused = False
                continue
            
            # 加仓逻辑
            if not paused and batch_executed < 3:
                if in_zone:
                    if batch_executed == 1:
                        # 第二批: 再跌1×ATR或持仓≥3日
                        drop_trigger = close <= entry_prices[0] - atr
                        time_trigger = (i - entry_idx) >= 3
                        if drop_trigger or time_trigger:
                            batch_pct = max_pct / 100 / 3
                            risk_budget = capital * batch_pct
                            shares = risk_budget / close if close > 0 else 0
                            entry_prices.append(close)
                            total_shares += shares
                            total_cost += shares * close
                            position_pct += batch_pct
                            batch_executed = 2
                            trades.append({
                                'symbol': symbol, 'type': 'ENTRY', 'date': date,
                                'price': close, 'shares': shares, 'batch': 2,
                                'position_pct': position_pct * 100
                            })
                    elif batch_executed == 2:
                        # 第三批: 再跌1.5×ATR或持仓≥5日
                        drop_trigger = close <= entry_prices[1] - 1.5 * atr
                        time_trigger = (i - entry_idx) >= 5
                        if drop_trigger or time_trigger:
                            batch_pct = max_pct / 100 / 3
                            risk_budget = capital * batch_pct
                            shares = risk_budget / close if close > 0 else 0
                            entry_prices.append(close)
                            total_shares += shares
                            total_cost += shares * close
                            position_pct += batch_pct
                            batch_executed = 3
                            trades.append({
                                'symbol': symbol, 'type': 'ENTRY', 'date': date,
                                'price': close, 'shares': shares, 'batch': 3,
                                'position_pct': position_pct * 100
                            })
                else:
                    # 价格反弹出买入区间 → 暂停后续批次
                    if batch_executed < 3:
                        paused = True
    
    # 未平仓
    if in_position:
        close = df['close'].iloc[-1]
        avg_entry = total_cost / total_shares if total_shares > 0 else entry_prices[0]
        pnl_pct = (close - avg_entry) / avg_entry * 100
        trades.append({
            'symbol': symbol, 'type': 'EXIT', 'date': df['date'].iloc[-1],
            'price': close, 'avg_entry': avg_entry,
            'pnl_pct': pnl_pct, 'reason': 'END_OF_DATA',
            'hold_days': n - 1 - entry_idx, 'position_pct': position_pct * 100,
            'batches': batch_executed
        })
    
    return trades

print("Counterpunch backtest loaded.")
