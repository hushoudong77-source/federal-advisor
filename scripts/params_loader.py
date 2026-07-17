#!/usr/bin/env python3
"""
params_loader.py — 统一参数加载器
所有脚本和LLM通过此模块读取 params.json，禁止在其他文件中硬编码参数。

用法:
    from params_loader import get_params, get_ticker_param, get_all_counterpunch, ...
"""

import json
import os

_PARAMS = None
_PARAMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'params.json')


def _load():
    global _PARAMS
    if _PARAMS is None:
        with open(_PARAMS_PATH, 'r') as f:
            _PARAMS = json.load(f)
    return _PARAMS


def get_params():
    """返回完整参数字典"""
    return _load()


def get_meta():
    """返回 _meta 信息（版本号等）"""
    return _load()['_meta']


def get_pool():
    """返回全池标的列表"""
    return _load()['pool']


def get_tushare_code(ticker):
    """返回标的的Tushare代码和类型"""
    codes = _load()['pool']['tushare_codes']
    if ticker in codes:
        return codes[ticker]
    raise KeyError(f"标的 {ticker} 不在全池中")


def get_routing(ticker):
    """返回标的路由分类"""
    routing = _load()['routing']
    if ticker in routing:
        return routing[ticker]
    raise KeyError(f"标的 {ticker} 无路由配置")


def get_counterpunch(ticker=None):
    """返回反击策略参数。不传ticker返回全部"""
    cp = _load()['counterpunch']
    if ticker is None:
        return cp
    if ticker in cp:
        return cp[ticker]
    raise KeyError(f"标的 {ticker} 不在反击策略池中")


def get_us_offensive(ticker=None):
    """返回美股进攻策略参数"""
    uo = _load()['us_offensive']
    if ticker is None:
        return uo
    if ticker in uo:
        return uo[ticker]
    raise KeyError(f"标的 {ticker} 不在美股进攻池中")


def get_a_share_offensive(ticker=None):
    """返回A股进攻策略参数"""
    ao = _load()['a_share_offensive']
    if ticker is None:
        return ao
    if ticker in ao:
        return ao[ticker]
    raise KeyError(f"标的 {ticker} 不在A股进攻池中")


def get_momentum(ticker=None):
    """返回动量跟随策略参数"""
    mm = _load()['momentum']
    if ticker is None:
        return mm
    if ticker in mm:
        return mm[ticker]
    raise KeyError(f"标的 {ticker} 不在动量跟随池中")


def get_fixed_layer(ticker=None):
    """返回固定层参数"""
    fl = _load()['fixed_layer']
    if ticker is None:
        return fl
    if ticker in fl:
        return fl[ticker]
    raise KeyError(f"标的 {ticker} 不在固定层中")


def get_gold_shield(ticker=None):
    """返回金盾参数"""
    gs = _load()['gold_shield']
    if ticker is None:
        return gs
    if ticker in gs:
        return gs[ticker]
    raise KeyError(f"标的 {ticker} 不在金盾体系中")


def get_cane():
    """返回CANE独立标的参数"""
    return _load()['independent_cane']


def get_macro_thresholds():
    """返回宏观阈值"""
    return _load()['macro_thresholds']


def get_risk_controls():
    """返回风控参数"""
    return _load()['risk_controls']


def get_ticker_param(ticker):
    """智能路由：根据标的自动返回对应策略的参数"""
    routing = _load()['routing'].get(ticker, {}).get('route', None)
    
    route_map = {
        'counterpunch': get_counterpunch,
        'us_offensive': get_us_offensive,
        'a_share_offensive': get_a_share_offensive,
        'momentum': get_momentum,
        'fixed_layer': get_fixed_layer,
        'gold_shield': get_gold_shield,
        'independent': get_cane,
    }
    
    if routing in route_map:
        try:
            return route_map[routing](ticker)
        except KeyError:
            pass
    
    return {'route': routing, 'warning': f'{ticker} 路由={routing}，无逐标参数可返回'}


# ============================================================
# CLI: python3 params_loader.py <ticker>  快速查询
# ============================================================
if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
        try:
            param = get_ticker_param(ticker)
            print(json.dumps(param, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"❌ {e}")
    else:
        print(f"📋 params.json V{get_meta()['version']}")
        print(f"   标的池: {len(get_pool()['us_equity'])}美股 + {len(get_pool()['cn_equity'])}A股 + {len(get_pool()['independent'])}独立")
        print(f"   使用: python3 params_loader.py <ticker>")
