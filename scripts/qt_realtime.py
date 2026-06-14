"""
腾讯股票实时行情接口封装
http://qt.gtimg.cn/
P4层补充数据源 — 用于盘中实时行情自动获取

代码前缀规则：
  A股: sz000001 sh600519
  港股: hk00700 hk09988
  美股: usAAPL usQQQ (返回 OTC 后缀)
  指数: sh000001 sz399006 (A股) / r_hkHSI (恒生) / s_usIXIC (纳斯达克)
"""

import requests
from typing import Dict, List, Optional, Any

API_URL = "http://qt.gtimg.cn/q={}"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
TIMEOUT = 10

# 全池A股ETF代码映射
A_CODES = {
    '159302.SZ': 'sz159302',    # 港股高股息ETF银华
    '159545.SZ': 'sz159545',    # 恒生红利低波ETF易方达
    '513910.SH': 'sh513910',    # 港股通央企红利ETF华夏
    '513180.SH': 'sh513180',    # 恒生科技ETF华夏
    '588000.SH': 'sh588000',    # 科创50ETF华夏
    '510500.SH': 'sh510500',    # 中证500ETF南方
    '518880.SH': 'sh518880',    # 黄金ETF华安
    '511880.SH': 'sh511880',    # 银华日利ETF
}

# 全池美股代码映射
US_CODES = {
    'QQQ': 'usQQQ',
    'IVV': 'usIVV',
    'IAU': 'usIAU',
    'VTI': 'usVTI',
    'VEA': 'usVEA',
    'BBJP': 'usBBJP',
    'MUFG': 'usMUFG',
    'EWY': 'usEWY',
    'VNM': 'usVNM',
    'FLIN': 'usFLIN',
    'SMIN': 'usSMIN',
    'CANE': 'usCANE',
}

# 港股 + 指数映射
HK_CODES = {
    '00700': 'hk00700',   # 腾讯（参照）
    '09988': 'hk09988',   # 阿里（参照）
}

INDEX_CODES = {
    '000001': 'sh000001', # 上证
    '399006': 'sz399006', # 创业板
    'HSI': 'r_hkHSI',     # 恒生
}


def get_realtime(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    批量获取实时行情
    
    Args:
        codes: 腾讯格式代码列表，如 ['sz159302', 'sh513910', 'usQQQ']
        
    Returns:
        dict[code] = {name, price, change_pct, high, low, ...}
    """
    if not codes:
        return {}
    
    url = API_URL.format(','.join(codes))
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.encoding = 'gbk'
    except Exception as e:
        return {'_error': f'请求失败: {e}'}
    
    results = {}
    for line in r.text.strip().split(';'):
        if not line.strip():
            continue
        start = line.find('"')
        end = line.rfind('"')
        if start == -1 or end == -1 or start == end:
            continue
        fields = line[start+1:end].split('~')
        if len(fields) < 10:
            continue
        
        code = fields[2] if fields[2] else line.split('=')[0].strip()
        
        d = {
            'name': fields[1],
            'price': _safe_float(fields[3]),
            'last_close': _safe_float(fields[4]),
            'open': _safe_float(fields[5]),
            'volume_hand': _safe_int(fields[6]),  # 成交量(手)
            'volume_amount': _safe_float(fields[37]),  # 成交额(万元)
            'high': _safe_float(fields[33]),
            'low': _safe_float(fields[34]),
            'change': _safe_float(fields[31]),
            'change_pct': _safe_float(fields[32]),
            'turnover_rate': _safe_float(fields[38]),
            'pe': _safe_float(fields[39]),
            'market_cap': _safe_float(fields[45]),
            'circ_market_cap': _safe_float(fields[44]),
            'high_limit': _safe_float(fields[47]),
            'low_limit': _safe_float(fields[48]),
            'time': fields[30] if len(fields) > 30 else None,
        }
        results[code] = d
    
    return results


def get_pool_realtime():
    """获取全池17标 + 参照的实时行情"""
    codes = list(A_CODES.values()) + list(US_CODES.values()) + list(INDEX_CODES.values())
    return get_realtime(codes)


def _safe_float(v):
    try:
        return float(v) if v else None
    except (ValueError, TypeError):
        return None

def _safe_int(v):
    try:
        return int(v) if v else None
    except (ValueError, TypeError):
        return None


if __name__ == '__main__':
    # 测试
    data = get_pool_realtime()
    for code, d in sorted(data.items()):
        if code == '_error':
            print(f'ERROR: {d}')
            continue
        pct = f'{d["change_pct"]:+6.2f}%' if d['change_pct'] is not None else '  N/A  '
        price = f'{d["price"]:>8.3f}' if d['price'] else '  N/A  '
        print(f'{code:>12s} {d["name"]:12s} {price} {pct}')
