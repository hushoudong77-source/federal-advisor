#!/usr/bin/env python3
""" /回测 L2 — 月度逐标最优参数重标定 """
import tushare as ts
import pandas as pd
import numpy as np

ts.set_token('d4a1352a19c1e52c5f1d0df8b7ef8f67ed9d27806c4aec64297ce426f7c5')
pro = ts.pro_api()

k_range = np.arange(1.0, 5.1, 0.5)
LOOKFORWARD = 60
MA_WINDOW = 40

def calc_metrics(df, k):
    df = df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date').reset_index(drop=True)
    
    df['MA40'] = df['close'].rolling(MA_WINDOW).mean()
    df['TR'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['ATR14'] = df['TR'].rolling(14).mean()
    df['buy_upper'] = df['MA40'] - k * df['ATR14']
    df['in_zone'] = df['close'] <= df['buy_upper']
    
    hits = []
    was_in = False
    for i in range(len(df) - LOOKFORWARD):
        if df.loc[i, 'in_zone'] and pd.notna(df.loc[i, 'MA40']):
            if was_in:
                was_in = df.loc[i, 'in_zone']
                continue
            was_in = True
            entry = df.loc[i, 'close']
            future_ret = (df.loc[i + LOOKFORWARD, 'close'] - entry) / entry
            fwd_prices = df.loc[i:i + LOOKFORWARD, 'close'].values
            peak = np.maximum.accumulate(fwd_prices)
            dd = np.min((fwd_prices - peak) / peak)
            hits.append({
                'date': df.loc[i, 'trade_date'],
                'entry': entry,
                'ret_60d': future_ret,
                'max_dd': dd,
                'win': future_ret > 0
            })
        else:
            was_in = False
    
    if len(hits) == 0:
        return {'hit_rate': 0, 'avg_ret': 0, 'win_rate': 0, 'max_dd': 0, 'score': 0, 'n_hits': 0}
    
    hr = pd.DataFrame(hits)
    total_days = len(df) - LOOKFORWARD
    hit_rate = len(hr) / total_days
    
    return {
        'hit_rate': round(hit_rate * 100, 2),
        'avg_ret': round(hr['ret_60d'].mean() * 100, 2),
        'win_rate': round(hr['win'].mean() * 100, 1),
        'max_dd': round(hr['max_dd'].min() * 100, 2),
        'score': round(hr['win'].mean() * hr['ret_60d'].mean() * 100 - abs(hr['max_dd'].min()) * 50, 2),
        'n_hits': len(hr)
    }


targets = [
    ('513910.SH', '513910 港股通央企红利', 'fund_daily'),
    ('588000.SH', '588000 科创50', 'fund_daily'),
    ('510500.SH', '510500 中证500', 'fund_daily'),
    ('512100.SH', '512100 中证1000', 'fund_daily'),
    ('510880.SH', '510880 红利ETF', 'fund_daily'),
    ('BBJP', 'BBJP 日股ETF', 'us_daily'),
    ('VNM', 'VNM 越南ETF', 'us_daily'),
    ('VTI', 'VTI 全美市场', 'us_daily'),
    ('VEA', 'VEA 非美发达', 'us_daily'),
]

current_k = {
    '513910.SH': 2.0, '588000.SH': 2.0, '510500.SH': 2.0,
    '512100.SH': 2.0, '510880.SH': 2.0, 'BBJP': 2.0,
    'VNM': 2.0, 'VTI': 4.0, 'VEA': 4.0
}

for code, name, source in targets:
    if source == 'fund_daily':
        df = pro.fund_daily(ts_code=code, start_date='20180101', end_date='20260628')
    else:
        df = pro.us_daily(ts_code=code, start_date='20180101', end_date='20260628')
    
    df = df.sort_values('trade_date').reset_index(drop=True)
    
    latest_date = pd.to_datetime(df['trade_date'].max())
    cutoff_24m = latest_date - pd.DateOffset(months=24)
    df_24m = df[pd.to_datetime(df['trade_date']) >= cutoff_24m].copy().reset_index(drop=True)
    df_full = df.copy().reset_index(drop=True)
    
    cur_k = current_k.get(code, 2.0)
    
    d0_24 = df_24m['trade_date'].iloc[0]
    dn_24 = df_24m['trade_date'].iloc[-1]
    d0_f = df_full['trade_date'].iloc[0]
    dn_f = df_full['trade_date'].iloc[-1]
    
    print(f'\n{"="*60}')
    print(f'### {name} (当前k={cur_k})')
    print(f'24月窗口: {dn_24} ~ {d0_24}, {len(df_24m)}交易日')
    print(f'全量窗口: {dn_f} ~ {d0_f}, {len(df_full)}交易日')
    print(f'{"k":>6} | {"命中率%":>7} | {"均收益%":>7} | {"胜率%":>6} | {"最大回撤%":>8} | {"得分":>6} | {"命中数":>6} | {"窗口":>4}')
    print(f'{"-"*70}')
    
    best_24m = {'k': 0, 'score': -999}
    best_full = {'k': 0, 'score': -999}
    cur_score_24m = None
    
    for k in k_range:
        r24 = calc_metrics(df_24m, k)
        rfull = calc_metrics(df_full, k)
        
        tag_24 = '24M'
        tag_full = 'FULL'
        
        if abs(k - cur_k) < 0.01:
            cur_score_24m = r24['score']
            tag_24 += ' <--当前'
        
        if r24['score'] > best_24m['score']:
            best_24m = {'k': k, 'score': r24['score'], 'metrics': r24}
        if rfull['score'] > best_full['score']:
            best_full = {'k': k, 'score': rfull['score'], 'metrics': rfull}
        
        print(f'{k:>5.1f} | {r24["hit_rate"]:>6.1f}% | {r24["avg_ret"]:>+7.2f}% | {r24["win_rate"]:>5.1f}% | {r24["max_dd"]:>+8.2f}% | {r24["score"]:>+6.2f} | {r24["n_hits"]:>5} | {tag_24}')
        print(f'{"":>5}  | {rfull["hit_rate"]:>6.1f}% | {rfull["avg_ret"]:>+7.2f}% | {rfull["win_rate"]:>5.1f}% | {rfull["max_dd"]:>+8.2f}% | {rfull["score"]:>+6.2f} | {rfull["n_hits"]:>5} | {tag_full}')
    
    score_ratio = cur_score_24m / best_24m['score'] if best_24m['score'] != 0 and cur_score_24m is not None else 0
    diff = abs(best_24m['score'] - best_full['score'])
    
    print(f'\n├── 24月最优: k={best_24m["k"]:.1f} (得分 {best_24m["score"]:.2f})')
    print(f'├── 全量最优: k={best_full["k"]:.1f} (得分 {best_full["score"]:.2f})')
    if diff >= 0.05:
        print(f'├── 窗口差异: |{diff:.2f}| -> ⚠️ 市场结构漂移')
    else:
        print(f'├── 窗口差异: |{diff:.2f}| -> ✅ 参数稳定')
    print(f'├── 当前参数 vs 24月最优: 得分比 = {score_ratio:.1%}')
    if score_ratio >= 0.95:
        verdict = '✅ 维持当前参数'
    elif score_ratio >= 0.85:
        verdict = '🟡 标记观察'
    else:
        verdict = f'🔴 建议修正至 k={best_24m["k"]:.1f}'
    print(f'└── 裁决: {verdict}')

print('\n\n✅ /回测 L2 完成')
