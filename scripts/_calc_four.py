import json
import pandas as pd

with open('scripts/.market_data_cache.json') as f:
    data = json.load(f)

def get_ticker_data(ticker):
    for item in data['market_data']:
        if item['ticker'] == ticker:
            return item
    return None

for tk in ['159915', '510300', '510500', '518880']:
    d = get_ticker_data(tk)
    if not d:
        print(f'{tk}: no data')
        continue
    
    tencent = d.get('tencent_price', 'N/A')
    klines = d.get('klines', [])
    if not klines:
        print(f'{tk}: no klines')
        continue
    
    closes = [k['close'] for k in klines]
    vols = [k['volume'] for k in klines]
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    
    price = float(tencent) if tencent != 'N/A' else closes[-1]
    
    # ATR14
    tr_list = []
    for i in range(1, min(20, len(closes))):
        h = highs[-i]
        l_ = lows[-i]
        c_prev = closes[-i-1]
        tr = max(h - l_, abs(h - c_prev), abs(l_ - c_prev))
        tr_list.append(tr)
    atr14 = sum(tr_list[:14]) / 14
    
    # MA40
    ma40 = sum(closes[-40:]) / 40
    
    # MA40 5日变化
    ma40_5d_ago = sum(closes[-45:-5]) / 40
    ma40_change_5d = abs(ma40 - ma40_5d_ago) / ma40_5d_ago * 100
    
    # MA40方向
    ma40_20d_ago = sum(closes[-60:-20]) / 40
    ma40_dir = 'up' if ma40 > ma40_20d_ago else 'down'
    
    # 50EMA
    ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1]
    
    # MA60
    ma60 = sum(closes[-60:]) / 60
    ma60_dir = 'up' if closes[-1] > closes[-60] else 'down'
    
    # MA5
    ma5 = sum(closes[-5:]) / 5
    
    # H20
    h20 = max(closes[-20:])
    
    # 量比
    vol_ma20 = sum(vols[-21:-1]) / 20
    vol_ratio = vols[-1] / vol_ma20
    
    # MACD
    ema12_s = pd.Series(closes).ewm(span=12, adjust=False).mean()
    ema26_s = pd.Series(closes).ewm(span=26, adjust=False).mean()
    diff_s = ema12_s - ema26_s
    dea_s = diff_s.ewm(span=9, adjust=False).mean()
    diff = diff_s.iloc[-1]
    dea_val = dea_s.iloc[-1]
    bar = 2 * (diff - dea_val)
    
    # RSI14
    gains = []
    losses = []
    for i in range(len(closes)-15, len(closes)):
        chg = closes[i] - closes[i-1]
        gains.append(max(chg, 0))
        losses.append(max(-chg, 0))
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    rsi14 = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss > 0 else 100
    
    # ADX14
    plus_dm = []
    minus_dm = []
    tr_adx = []
    for i in range(-29, 0):
        h = highs[i]
        l = lows[i]
        up = h - highs[i-1]
        down = lows[i-1] - l
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr_adx.append(max(h - l, abs(h - closes[i-1]), abs(l - closes[i-1])))
    
    tr14_adx = pd.Series(tr_adx).rolling(14).sum().iloc[-1]
    plus_dm14 = pd.Series(plus_dm).rolling(14).sum().iloc[-1]
    minus_dm14 = pd.Series(minus_dm).rolling(14).sum().iloc[-1]
    plus_di = 100 * plus_dm14 / tr14_adx if tr14_adx > 0 else 0
    minus_di = 100 * minus_dm14 / tr14_adx if tr14_adx > 0 else 0
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
    adx14 = dx
    
    # 底部序列
    panic_day = None
    stop_bleed_day = None
    for i in range(-20, 0):
        c = closes[i]
        v = vols[i]
        body = abs(c - closes[i-1])
        daily_chg_pct = (c - closes[i-1]) / closes[i-1] * 100
        atr_pct = atr14 / closes[i-1] * 100
        vol_ma20_i = sum(vols[max(0,i-20):i]) / 20
        if daily_chg_pct < -1.5 * atr_pct and v > 1.5 * vol_ma20_i:
            panic_day = i
        if body < 0.3 * atr14 and v < 0.8 * vol_ma20_i:
            if stop_bleed_day is None or i > stop_bleed_day:
                stop_bleed_day = i
    
    bottom_seq = 'YES' if (panic_day is not None and stop_bleed_day is not None and stop_bleed_day > panic_day) else 'NO'
    
    # R2
    k_map = {'159915': 2.0, '510300': 2.0, '510500': 2.5}
    k = k_map.get(tk)
    
    # 牛熊
    if ma60_dir == 'up' and price > ma60:
        bull_bear = 'BULL'
    elif ma60_dir == 'down' and price < ma60:
        bull_bear = 'BEAR'
    else:
        bull_bear = 'TRANS'
    
    print(f'=== {tk} ===')
    print(f'price={price:.3f}')
    print(f'MA40={ma40:.4f} dir={ma40_dir} 5d_chg={ma40_change_5d:.3f}%')
    print(f'50EMA={ema50:.4f}')
    print(f'MA60={ma60:.4f} dir={ma60_dir}')
    print(f'MA5={ma5:.4f}')
    print(f'ATR14={atr14:.4f}')
    print(f'H20={h20:.4f}')
    print(f'vol_ratio={vol_ratio:.2f}')
    print(f'MACD: DIFF={diff:.4f} DEA={dea_val:.4f} BAR={bar:.4f}')
    print(f'RSI14={rsi14:.1f}')
    print(f'ADX14={adx14:.1f}')
    if k:
        r2_upper = ma40 - k * atr14
        dist = (price - r2_upper) / r2_upper * 100
        print(f'R2(k={k}): upper={r2_upper:.4f} dist={dist:.1f}%')
    print(f'bottom_seq={bottom_seq} panic={panic_day} stop_bleed={stop_bleed_day}')
    print(f'R0.3: MA40_down={ma40_dir=="down"} price_below_50EMA={price < ema50}')
    print(f'bull_bear={bull_bear}')
    print()
