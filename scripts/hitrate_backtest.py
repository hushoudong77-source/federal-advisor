#!/usr/bin/env python3
"""
📜 命中率回测引擎 — TickFlow 版 V3.0
V3.0: Tushare → TickFlow (不复权)
"""
import pandas as pd, numpy as np, sys, os, json
from datetime import datetime, timedelta
from tickflow import TickFlow

TICKER_CONFIG = {
    '513910': {'name':'港股通央企红利ETF','anchor':40,'k':2.7,'hold_days':20,'tf_code':'513910.SH','stop_mult':3.5,'cooldown':16,'tier':'L1红利'},
    '512100': {'name':'中证1000ETF','anchor':40,'k':2.0,'hold_days':20,'tf_code':'512100.SH','stop_mult':3.0,'cooldown':15,'tier':'L2成长'},
    '510500': {'name':'中证500ETF','anchor':40,'k':4.9,'hold_days':15,'tf_code':'510500.SH','stop_mult':2.5,'cooldown':60,'tier':'L3宽基'},
    '588000': {'name':'科创50ETF','anchor':40,'k':4.7,'hold_days':15,'tf_code':'588000.SH','stop_mult':3.0,'cooldown':15,'tier':'L2成长'},
    '510880': {'name':'红利ETF','anchor':40,'k':2.0,'hold_days':20,'tf_code':'510880.SH','stop_mult':3.0,'cooldown':30,'tier':'L1红利'},
    '159530': {'name':'机器人ETF','anchor':40,'k':1.5,'hold_days':10,'tf_code':'159530.SZ','stop_mult':4.0,'cooldown':30,'tier':'L2成长'},
    '510300': {'name':'沪深300ETF','anchor':40,'k':2.0,'hold_days':20,'tf_code':'510300.SH','stop_mult':4.0,'cooldown':45,'tier':'L3宽基'},
    '159915': {'name':'创业板ETF','anchor':40,'k':2.0,'hold_days':20,'tf_code':'159915.SZ','stop_mult':4.0,'cooldown':10,'tier':'L3宽基'},
}

def fetch_data_tf(cfg, count=10000):
    tf = TickFlow(api_key=os.environ.get('TICKFLOW_API_KEY'))
    r = tf.klines.get(cfg['tf_code'], period='1d', count=count, adjust='none')
    if not r or len(r.get('close',[]))==0: return None
    df = pd.DataFrame({'Date':pd.to_datetime(r['timestamp'],unit='ms'),'Open':r['open'],'High':r['high'],'Low':r['low'],'Close':r['close'],'Volume':r['volume']})
    return df.sort_values('Date').reset_index(drop=True)

def calc_indicators(df, anchor):
    df = df.copy()
    df['MA'] = df['Close'].rolling(anchor).mean()
    df['MA30'] = df['Close'].rolling(30).mean()
    df['DevMA30'] = (df['Close']-df['MA30'])/df['MA30']*100
    df['prev_c'] = df['Close'].shift(1)
    df['TR'] = df.apply(lambda r: max(r['High']-r['Low'],abs(r['High']-r['prev_c']) if pd.notna(r['prev_c']) else 0,abs(r['Low']-r['prev_c']) if pd.notna(r['prev_c']) else 0),axis=1)
    atr=[None]
    for i in range(1,len(df)):
        tr=df.loc[df.index[i],'TR']
        if pd.isna(tr): atr.append(None); continue
        if len(atr)<=14:
            v=[x for x in atr if x is not None]+[tr]; atr.append(np.mean(v))
        else: atr.append((atr[-1]*13+tr)/14)
    df['ATR14']=atr
    delta=df['Close'].diff()
    gain=delta.where(delta>0,0); loss=(-delta).where(delta<0,0)
    df['RSI14']=100-(100/(1+gain.rolling(14).mean()/loss.rolling(14).mean().replace(0,np.nan))); df['RSI14']=df['RSI14'].fillna(50)
    df['VolMA20']=df['Volume'].rolling(20).mean()
    return df

def identify(df, anchor, k, hold_days, cooldown=10, stop_mult=2.0):
    signals=[]; n=len(df); in_zone=False; cool_end=-1
    for i in range(n):
        if i<anchor+14: continue
        ma=df.loc[df.index[i],'MA']; atr=df.loc[df.index[i],'ATR14']; p=df.loc[df.index[i],'Close']
        if pd.isna(ma) or pd.isna(atr) or atr<=0: continue
        lo=ma-k*atr; hi=ma
        iz=(lo<=p<=hi)
        if cool_end>0 and i<=cool_end: iz=False
        if iz and not in_zone:
            signals.append({'idx':i,'date':df.loc[df.index[i],'Date'],'entry':p,'lo':lo,'hi':hi,'atr':atr,'stop':lo-stop_mult*atr,'hold':hold_days})
            cool_end=i+cooldown; in_zone=True
        elif not iz: in_zone=False
    return signals

def calc_results(sigs, df):
    for s in sigs:
        i=s['idx']; pe=s['entry']; ps=s['stop']; h=s['hold']
        for d in range(1,h+1):
            ci=i+d
            if ci>=len(df): s['res']='N/A'; s['exit_p']=df.iloc[-1]['Close']; s['exit_d']=df.iloc[-1]['Date']; s['exit_r']='DATA_END'; break
            lo=df.loc[df.index[ci],'Low']; cl=df.loc[df.index[ci],'Close']; dt=df.loc[df.index[ci],'Date']
            if lo<=ps: s['res']='STOP'; s['exit_p']=ps; s['exit_d']=dt; s['exit_r']='STOP_LOSS'; break
            if d==h: s['res']='WIN' if cl>pe else 'LOSS'; s['exit_p']=cl; s['exit_d']=dt; s['exit_r']='TIME_EXIT'
        if s.get('exit_p'): s['ret']=(s['exit_p']-pe)/pe*100
    return sigs

def metrics(sigs, df, anchor, k):
    v=[s for s in sigs if s.get('res') in ('WIN','LOSS','STOP')]
    t=len(v); w=len([s for s in v if s['res']=='WIN']); l=len([s for s in v if s['res'] in ('LOSS','STOP')])
    st=len([s for s in v if s['res']=='STOP']); na=len([s for s in sigs if s.get('res')=='N/A'])
    hr=w/t if t else 0
    tw=sum(s['ret'] for s in v if s['res']=='WIN'); tl=abs(sum(s['ret'] for s in v if s['res'] in ('LOSS','STOP')))
    pf=tw/tl if tl>0 else (float('inf') if tw>0 else 0)
    aw=np.mean([s['ret'] for s in v if s['res']=='WIN']) if w else 0
    al=np.mean([s['ret'] for s in v if s['res'] in ('LOSS','STOP')]) if l else 0
    mc=cc=0
    for s in v:
        if s['res'] in ('LOSS','STOP'): cc+=1; mc=max(mc,cc)
        else: cc=0
    exp=(hr*aw)-((1-hr)*abs(al))
    n=len(df); zd=0
    for i in range(anchor+14,n):
        ma=df.loc[df.index[i],'MA']; atr=df.loc[df.index[i],'ATR14']
        if pd.isna(ma) or pd.isna(atr): continue
        lo=ma-k*atr
        if lo<=df.loc[df.index[i],'Close']<=ma: zd+=1
    cr=zd/(n-anchor-14) if (n-anchor-14)>0 else 0
    lm=df.iloc[-1]['MA']; la=df.iloc[-1]['ATR14']; lp=df.iloc[-1]['Close']
    if pd.notna(lm) and pd.notna(la):
        ll=lm-k*la
        cs='🔴超跌' if lp<=ll else ('🟡上方' if lp>=lm else '🟢区间内')
    else: cs='⚪N/A'
    return {'total':t,'win':w,'loss':l,'stop':st,'na':na,'hr':hr,'pf':pf,'aw':aw,'al':al,'exp':exp,'mc':mc,'cr':cr,'cs':cs}

def run_one(ticker, cfg, count=10000, verbose=True):
    if verbose:
        print(f"\n{'='*60}\n  {ticker} {cfg['name']}\n  {cfg['tier']} | MA{cfg['anchor']}×{cfg['k']} | H={cfg['hold_days']}d\n{'='*60}")
    df=fetch_data_tf(cfg,count)
    if df is None or len(df)<200: return print("  ❌ 数据不足") if verbose else None
    df=calc_indicators(df,cfg['anchor']); df=df.dropna(subset=['MA','ATR14']).reset_index(drop=True)
    if len(df)<50: return print("  ❌ 指标后不足") if verbose else None
    sigs=identify(df,cfg['anchor'],cfg['k'],cfg['hold_days'],cfg.get('cooldown',10),cfg.get('stop_mult',2.0))
    sigs=calc_results(sigs,df); m=metrics(sigs,df,cfg['anchor'],cfg['k'])
    if verbose:
        print(f"  📊 {df.iloc[0]['Date'].strftime('%Y-%m-%d')}~{df.iloc[-1]['Date'].strftime('%Y-%m-%d')} | {len(df)}日")
        print(f"  📈 信号{m['total']} | WIN={m['win']} LOSS={m['loss']} STOP={m['stop']} N/A={m['na']}")
        print(f"  🎯 HR:{m['hr']*100:.1f}% CR:{m['cr']*100:.1f}% PF:{m['pf']:.2f} | 均盈亏:{m['aw']:+.2f}%/{m['al']:.2f}%")
        print(f"     期望值:{m['exp']:+.2f}% 最大连亏:{m['mc']}笔 | 当前:{m['cs']}")
        recent=[s for s in sigs if s.get('res') in ('WIN','LOSS','STOP')][-5:]
        if recent:
            print(f"  📋 最近5笔:")
            for s in recent:
                e='🟢' if s['res']=='WIN' else ('🔴' if s['res']=='STOP' else '⚫')
                print(f"     {e} {s['date'].strftime('%Y-%m-%d')} {s['entry']:.3f}→{s['exit_p']:.3f} ({s['ret']:+.2f}%) [{s['exit_r']}]")
    return {'ticker':ticker,'name':cfg['name'],'tier':cfg['tier'],'config':f"MA{cfg['anchor']}×{cfg['k']}",'hold':cfg['hold_days'],'period':f"{df.iloc[0]['Date'].strftime('%Y-%m-%d')}~{df.iloc[-1]['Date'].strftime('%Y-%m-%d')}",'days':len(df),**m}

def run_all(count=10000, verbose=True):
    results=[]
    for t,c in TICKER_CONFIG.items():
        r=run_one(t,c,count,verbose)
        if r: results.append(r)
    if results:
        print(f"\n\n{'='*100}\n  📊 全池反击命中率回测 — TickFlow 不复权\n{'='*100}")
        print(f"{'标的':<8} {'名称':<16} {'层级':<10} {'参数':<12} {'H':>3} {'信号':>5} {'HR':>8} {'CR':>8} {'PF':>6} {'期望值':>8} {'连亏':>4} {'状态':<10}")
        print("-"*100)
        for r in results:
            print(f"{r['ticker']:<8} {r['name']:<16} {r['tier']:<10} {r['config']:<12} {r['hold']:>3} {r['total']:>5} {r['hr']*100:>7.1f}% {r['cr']*100:>7.1f}% {r['pf']:>6.2f} {r['exp']:>+7.2f}% {r['mc']:>4}笔 {r['cs']:<10}")
        print(f"\n{'='*100}")
        print(f"  总标:{len(results)} | 总信号:{sum(r['total'] for r in results)}")
        print(f"  平均HR:{np.mean([r['hr'] for r in results])*100:.1f}% | 平均CR:{np.mean([r['cr'] for r in results])*100:.1f}%")
        print(f"{'='*100}")
    return results

if __name__=='__main__':
    ticker_arg=None
    for i,a in enumerate(sys.argv[1:]):
        if a in ('--ticker','-t') and i+1<len(sys.argv)-1: ticker_arg=sys.argv[i+2].upper()
    if ticker_arg and ticker_arg in TICKER_CONFIG:
        run_one(ticker_arg, TICKER_CONFIG[ticker_arg], count=10000)
    elif ticker_arg:
        print(f"❌ 不在池内: {ticker_arg}"); sys.exit(1)
    else:
        run_all(count=10000, verbose=True)
