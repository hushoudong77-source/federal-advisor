#!/usr/bin/env python3
"""A股12标快速扫描 - TickFlow日线自算"""
from tickflow import TickFlow
import os, statistics, json, math

tf = TickFlow(os.environ.get('TICKFLOW_API_KEY'))

SYMBOLS = {
    '588000': '588000.SH', '513180': '513180.SH', '513910': '513910.SH',
    '510500': '510500.SH', '518880': '518880.SH', '512100': '512100.SH',
    '510880': '510880.SH', '159530': '159530.SZ', '510300': '510300.SH',
    '159915': '159915.SZ', '513770': '513770.SH', '159545': '159545.SZ'
}

results = {}
for name, sym in SYMBOLS.items():
    df = tf.klines.get(sym, period='1d', count=300, as_dataframe=True)
    closes = df['close'].tolist()
    highs = df['high'].tolist()
    lows = df['low'].tolist()
    volumes = df['volume'].tolist()
    
    n = len(closes)
    c = closes[-1]
    
    # MA40
    ma40 = statistics.fmean(closes[-40:]) if n >= 40 else float('nan')
    dev_ma40 = (c - ma40) / ma40 * 100
    
    # MA60 direction
    if n >= 80:
        ma60_now = statistics.fmean(closes[-60:])
        ma60_20d_ago = statistics.fmean(closes[-80:-20])
        ma60_dir = 'up' if ma60_now > ma60_20d_ago else 'down'
    else:
        ma60_dir = 'N/A'
    
    ma60 = statistics.fmean(closes[-60:]) if n >= 60 else float('nan')
    
    # MA5
    ma5 = statistics.fmean(closes[-5:]) if n >= 5 else float('nan')
    
    # ATR14
    if n >= 15:
        trs = []
        for i in range(-14, 0):
            trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
        atr14 = statistics.fmean(trs)
    else:
        atr14 = float('nan')
    
    # MACD (EMA12/26)
    if n >= 35:
        k12 = 2/13
        k26 = 2/27
        ema12 = closes[n-35]
        ema26 = closes[n-35]
        for i in range(n-34, n):
            ema12 = closes[i]*k12 + ema12*(1-k12)
            ema26 = closes[i]*k26 + ema26*(1-k26)
        diff = ema12 - ema26
        
        dea_start = diff
        for i in range(n-26, n):
            dea_start = diff*(2/10) + dea_start*(8/10)
        dea = dea_start
        bar = 2 * (diff - dea)
        
        # 前一日BAR
        ema12_prev = closes[n-36]
        ema26_prev = closes[n-36]
        for i in range(n-35, n-1):
            ema12_prev = closes[i]*k12 + ema12_prev*(1-k12)
            ema26_prev = closes[i]*k26 + ema26_prev*(1-k26)
        diff_prev = ema12_prev - ema26_prev
        bar_prev = 2 * (diff_prev - dea_start)
    else:
        bar = float('nan')
        bar_prev = float('nan')
    
    # H20
    h20 = max(highs[-20:]) if n >= 20 else float('nan')
    
    # 20日回撤
    dd20 = (c - closes[-20]) / closes[-20] * 100 if n >= 20 else float('nan')
    
    # VOL ratio
    vol_ma20 = statistics.fmean(volumes[-20:]) if n >= 20 else float('nan')
    vol_ratio = volumes[-1] / vol_ma20 if vol_ma20 > 0 else float('nan')
    
    # ADX14 简化
    if n >= 30:
        trs = []
        plus_dm = []
        minus_dm = []
        for i in range(-28, 0):
            tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
            trs.append(tr)
            up = highs[i] - highs[i-1] if highs[i] > highs[i-1] else 0
            down = lows[i-1] - lows[i] if lows[i] < lows[i-1] else 0
            plus_dm.append(up if up > down and up > 0 else 0)
            minus_dm.append(down if down > up and down > 0 else 0)
        
        atr14_adx = statistics.fmean(trs[-14:])
        plus_di = statistics.fmean(plus_dm[-14:]) / atr14_adx * 100
        minus_di = statistics.fmean(minus_dm[-14:]) / atr14_adx * 100
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
        adx14 = dx  # 简化为单日DX
    else:
        adx14 = float('nan')
    
    results[name] = {
        'price': round(c, 3),
        'ma5': round(ma5, 4),
        'ma40': round(ma40, 4),
        'ma60': round(ma60, 4),
        'dev_ma40': round(dev_ma40, 2),
        'ma60_dir': ma60_dir,
        'atr14': round(atr14, 4),
        'atr_pct': round(atr14/c*100, 1),
        'bar': round(bar, 5) if not math.isnan(bar) else 'N/A',
        'bar_prev': round(bar_prev, 5) if not math.isnan(bar_prev) else 'N/A',
        'h20': round(h20, 4),
        'dd20': round(dd20, 2),
        'vol_ratio': round(vol_ratio, 2),
        'adx14': round(adx14, 1),
    }
    print(f'{name} ¥{c:.3f}  devMA40={dev_ma40:+.2f}%  MA60_dir={ma60_dir}  ATR14=¥{atr14:.4f}({atr14/c*100:.1f}%)  BAR={bar:.5f}  H20=¥{h20:.4f}  DD20d={dd20:+.2f}%  VOLR={vol_ratio:.2f}  ADX={adx14:.1f}')

print('\n--- JSON ---')
print(json.dumps(results, indent=2, ensure_ascii=False))
