import tushare as ts
import pandas as pd
import numpy as np
import sys

pro = ts.pro_api()

symbols = {
    '513910.SH': ('港股通央企红利', 'MA40', 2.0),
    '588000.SH': ('科创50', 'MA40', 2.0),
    '510500.SH': ('中证500', 'MA40', 2.0),
    '512100.SH': ('中证1000', 'MA40', 2.0),
    '510880.SH': ('红利ETF', 'MA40', 2.0),
    '159530.SZ': ('机器人ETF', 'MA40', 2.0),
}

def calc_ma(close, n):
    return pd.Series(close).rolling(n).mean().values

def calc_atr(df, n=14):
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr1 = high - low
    tr2 = np.abs(high - prev_close)
    tr3 = np.abs(low - prev_close)
    tr = np.maximum(np.maximum(tr1, tr2), tr3)
    return pd.Series(tr).rolling(n).mean().values

k_values = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]

for code, (name, anchor, current_k) in symbols.items():
    header = f"{code} {name} | anchor={anchor} current_k={current_k}"
    print()
    print("=" * 70)
    print(f"  {header}")
    print("=" * 70)
    
    try:
        df = pro.fund_daily(ts_code=code, start_date='20180101', end_date='20260630')
        if df is None or len(df) < 100:
            print(f"  DATA INSUFFICIENT: {len(df) if df is not None else 0} rows")
            continue
        
        df = df.sort_values('trade_date').reset_index(drop=True)
        close = df['close'].values
        trade_dates = df['trade_date'].values
        
        ma40 = calc_ma(close, 40)
        atr14 = calc_atr(df, 14)
        
        start_idx = 60
        total_days = len(df) - start_idx
        
        print(f"  {'k':>5} {'buy_zone':>14} {'hits':>6} {'hit%':>7} {'avg60d':>8} {'win%':>7} {'PF':>6} {'sig/yr':>7}")
        print(f"  {'-'*5} {'-'*14} {'-'*6} {'-'*7} {'-'*8} {'-'*7} {'-'*6} {'-'*7}")
        
        for k in k_values:
            buy_zone = ma40 - k * atr14
            hits = 0
            hit_returns = []
            
            for i in range(start_idx, len(df)):
                if pd.isna(buy_zone[i]) or pd.isna(ma40[i]):
                    continue
                if close[i] <= buy_zone[i]:
                    hits += 1
                    end_idx = min(i + 60, len(df) - 1)
                    if end_idx > i + 20:
                        ret_60d = (close[end_idx] / close[i] - 1) * 100
                        hit_returns.append(ret_60d)
            
            hit_rate = hits / total_days * 100 if total_days > 0 else 0
            avg_ret = np.mean(hit_returns) if hit_returns else 0.0
            win_count = sum(1 for r in hit_returns if r > 0)
            win_rate = win_count / len(hit_returns) * 100 if hit_returns else 0.0
            
            if hit_returns:
                wins = [r for r in hit_returns if r > 0]
                losses = [abs(r) for r in hit_returns if r <= 0]
                avg_win = np.mean(wins) if wins else 0.0
                avg_loss = np.mean(losses) if losses else 0.0
                pf = avg_win / avg_loss if avg_loss > 0 else 99.0
            else:
                pf = 0.0
            
            years = total_days / 244.0
            annual_signals = len(hit_returns) / years if years > 0 else 0.0
            
            latest_ma40 = ma40[-1] if not pd.isna(ma40[-1]) else 0.0
            latest_atr = atr14[-1] if not pd.isna(atr14[-1]) else 0.0
            buy_price = latest_ma40 - k * latest_atr
            
            marker = " <--CURRENT" if abs(k - current_k) < 0.01 else ""
            print(f"  {k:>5.1f} {buy_price:>14.4f} {hits:>6} {hit_rate:>6.1f}% {avg_ret:>7.2f}% {win_rate:>6.1f}% {pf:>5.2f} {annual_signals:>6.1f}{marker}")
            
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
