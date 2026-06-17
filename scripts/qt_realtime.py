#!/usr/bin/env python3
"""全池19标腾讯实时行情拉取 — 修正版V3"""
import urllib.request
import re
import sys
from datetime import datetime

# 腾讯行情代码映射 — 键值就是腾讯返回的键名
SYMBOLS = {
    # A股ETF（上交所）
    "513910": "sh513910",
    "588000": "sh588000",
    "512100": "sh512100",
    "510880": "sh510880",
    "510500": "sh510500",
    "513180": "sh513180",
    "518880": "sh518880",
    "511880": "sh511880",
    # A股ETF（深交所）
    "159302": "sz159302",
    "159545": "sz159545",
    # 指数
    "000001": "sh000001",
    "399006": "sz399006",
    "HSI": "hkHSI",
    # 美股 — 腾讯返回的键名去掉后缀(.OQ/.N/.AM等)，直接用usXXX
    "BBJP":  "usBBJP",
    "CANE":  "usCANE",
    "EWY":   "usEWY",
    "FLIN":  "usFLIN",
    "IAU":   "usIAU",
    "IVV":   "usIVV",
    "MUFG":  "usMUFG",   # 腾讯返回 v_usMUFG (非 usMUFG.N)
    "QQQ":   "usQQQ",    # 腾讯返回 v_usQQQ  (非 usQQQ.OQ)
    "SMIN":  "usSMIN",
    "VEA":   "usVEA",
    "VNM":   "usVNM",
    "VTI":   "usVTI",
}

NAMES = {
    "000001": "上证指数",
    "159302": "港股高股息ETF银华",
    "159545": "恒生红利低波ETF易方达",
    "399006": "创业板指",
    "510500": "中证500ETF南方",
    "511880": "银华日利ETF",
    "512100": "中证1000ETF南方",
    "510880": "红利ETF易方达",
    "513180": "恒生科技ETF华夏",
    "513910": "港股通央企红利ETF华夏",
    "518880": "黄金ETF华安",
    "588000": "科创50ETF华夏",
    "HSI": "恒生指数",
    "BBJP": "Jp Morgan Etf Trust Betabuilders Japan Usd",
    "CANE": "Teucrium Commodity Trust Sugar Fund",
    "EWY": "韩国ETF-iShares MSCI",
    "FLIN": "Franklin Templeton Etf Tr Franklin Ftse India Etf",
    "IAU": "黄金信托ETF-iShares",
    "IVV": "标普500指数ETF-iShares",
    "MUFG": "三菱日联金融",
    "QQQ": "纳指100ETF",
    "SMIN": "iShares安硕MSCI印度小盘股ETF",
    "VEA": "新华富时发达市场ETF",
    "VNM": "VanEck Vectors越南ETF",
    "VTI": "美国全股市ETF-Vanguard",
}

def parse_price(raw):
    if raw is None:
        return None
    raw = str(raw).strip()
    if raw == '' or raw == '""':
        return None
    raw = raw.strip('"').strip("'").lstrip('~')
    try:
        return float(raw)
    except ValueError:
        return None

def fetch_all():
    """一次性拉取所有标的"""
    codes = list(set(SYMBOLS.values()))
    url = f"http://qt.gtimg.cn/q={','.join(codes)}"
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'http://finance.qq.com'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('gbk', errors='replace')
    except Exception as e:
        print(f"// ERROR: 腾讯API请求失败: {e}", file=sys.stderr)
        return {}
    
    # 构建反向映射: qt_code -> symbol
    qt_to_symbol = {v: k for k, v in SYMBOLS.items()}
    
    result = {}
    lines = raw.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or '=' not in line:
            continue
        
        match = re.match(r'v_(\S+)="(.*)"', line)
        if not match:
            continue
        
        qt_code = match.group(1)
        fields = match.group(2).split('~')
        
        if len(fields) < 5:
            continue
        
        symbol = qt_to_symbol.get(qt_code)
        if symbol is None:
            continue
        
        price = parse_price(fields[3])
        prev_close = parse_price(fields[4])
        pct = fields[32] if len(fields) > 32 else ''
        
        result[symbol] = {
            'name': fields[1] if len(fields) > 1 else NAMES.get(symbol, symbol),
            'price': price,
            'prev_close': prev_close,
            'pct': pct,
        }
    
    return result

def main():
    now = datetime.now()
    print(f"// 腾讯实时行情 | {now.strftime('%Y-%m-%d %H:%M:%S')} CST")
    print()
    
    data = fetch_all()
    
    order = ["000001", "399006", "HSI",
             "513910", "588000", "512100", "510880", "510500", "513180", "518880", "511880",
             "159302", "159545",
             "QQQ", "IVV", "IAU", "BBJP", "MUFG", "EWY", "VNM", "FLIN", "SMIN", "VEA", "VTI", "CANE"]
    
    all_ok = True
    for s in order:
        d = data.get(s)
        if d is None or d.get('price') is None:
            print(f"  {s:<8} {'—':40s} {'N/A':>10s}")
            all_ok = False
            continue
        
        name = NAMES.get(s, d.get('name', s))
        price = d['price']
        pct = d.get('pct', '')
        
        # 格式化价格
        if s in ("000001", "399006", "HSI"):
            pf = f"{price:>12.2f}"
        elif s.startswith(("51", "15", "58")) or s == "511880":
            pf = f"{price:>11.3f}"
        else:
            pf = f"{price:>8.2f}"
        
        # 涨跌幅
        pct_str = pct.replace('%', '') if pct else ''
        try:
            pct_f = float(pct_str)
            pct_display = f"{pct_f:+.2f}%"
        except (ValueError, TypeError):
            pct_display = pct if pct else "N/A"
        
        print(f"  {s:<8} {name:<40} {pf}  {pct_display}")
    
    # 统计
    total = len(order)
    ok = sum(1 for s in order if data.get(s, {}).get('price') is not None)
    print(f"\n// ✅ {ok}/{total} 成功")

if __name__ == '__main__':
    main()
