#!/usr/bin/env python3
"""
Stock Monitor V3.0 — 联邦投顾持仓监控
新增联邦专属预警层：止损触发/止盈触发/买入区间触发
盘后技术指标切Tushare（东财API被封）
"""

import requests
import json
import time
import os
import re
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# ============ Tushare 初始化 ============
import tushare as ts

TUSHARE_TOKEN = os.environ.get('TUSHARE_TOKEN', '026f0a2d89332cc6f7bfec218f55b9c65c36967f3c261a3a042dd35a')
ts.set_token(TUSHARE_TOKEN)
PRO = ts.pro_api()

# ============ 默认监控列表（会被 federal_loader 覆盖）============
WATCHLIST = []

# ============ 核心代码 ============

class StockAlert:
    def __init__(self):
        self.prev_data = {}
        self.alert_log = []
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self._tushare_cache = {}  # 缓存Tushare数据避免重复拉取
    
    # ========== 数据获取 ==========
    
    def fetch_sina_realtime(self, stocks):
        """获取A股实时行情"""
        results = {}
        if not stocks:
            return results
        
        codes = [f"{s['market']}{s['code']}" for s in stocks]
        url = f"https://hq.sinajs.cn/list={','.join(codes)}"
        try:
            resp = self.session.get(url, headers={'Referer': 'https://finance.sina.com.cn'}, timeout=10)
            resp.encoding = 'gb18030'
            for line in resp.text.strip().split(';'):
                if 'hq_str_' not in line or '=' not in line:
                    continue
                key = line.split('=')[0].split('_')[-1]
                if len(key) < 8:
                    continue
                data_str = line[line.index('"')+1 : line.rindex('"')]
                p = data_str.split(',')
                if len(p) > 30 and float(p[3]) > 0:
                    results[key[2:]] = {
                        'name': p[0],
                        'price': float(p[3]),
                        'prev_close': float(p[2]),
                        'open': float(p[1]),
                        'high': float(p[4]),
                        'low': float(p[5]),
                        'volume': int(p[8]),
                        'amount': float(p[9]),
                        'date': p[30],
                        'time': p[31],
                    }
        except Exception as e:
            print(f"新浪实时行情获取失败: {e}")
        
        return results
    
    def fetch_us_realtime(self, codes):
        """通过腾讯API获取美股实时行情"""
        results = {}
        if not codes:
            return results
        
        tencent_map = {code: f"us{code}" for code in codes}
        symbols = ",".join(tencent_map.values())
        url = f"http://qt.gtimg.cn/q={symbols}"
        
        try:
            resp = self.session.get(url, timeout=10)
            resp.encoding = 'gbk'
            for line in resp.text.strip().split('\n'):
                if 'v_' not in line or '=' not in line:
                    continue
                key = line.split('=')[0].strip()
                data_str = line[line.index('"')+1 : line.rindex('"')]
                if not data_str:
                    continue
                
                tencent_code = key.replace('v_', '')
                reverse_map = {v: k for k, v in tencent_map.items()}
                code = reverse_map.get(tencent_code)
                if not code:
                    continue
                
                p = data_str.split('~')
                if len(p) < 10:
                    continue
                
                try:
                    price = float(p[3]) if p[3] else 0
                    prev_close = float(p[4]) if len(p) > 4 and p[4] else price
                    
                    results[code] = {
                        'name': p[1] if p[1] else code,
                        'price': price,
                        'prev_close': prev_close,
                        'open': price,
                        'high': price,
                        'low': price,
                        'volume': 0,
                        'amount': 0,
                        'date': '',
                        'time': ''
                    }
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            print(f"美股实时行情获取失败: {e}")
        
        return results
    
    def fetch_realtime(self, stocks):
        """统一入口：分离A股/美股"""
        a_stocks = [s for s in stocks if s.get('market') != 'us']
        us_stocks = [s for s in stocks if s.get('market') == 'us']
        
        results = {}
        if a_stocks:
            results.update(self.fetch_sina_realtime(a_stocks))
        if us_stocks:
            us_codes = [s['code'] for s in us_stocks]
            results.update(self.fetch_us_realtime(us_codes))
        
        return results
    
    # ========== Tushare技术指标（盘后专用）==========
    
    def _get_tushare_daily(self, code, is_us=False):
        """获取Tushare日线数据（带缓存）"""
        cache_key = f"{code}_{'us' if is_us else 'cn'}"
        if cache_key in self._tushare_cache:
            return self._tushare_cache[cache_key]
        
        try:
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
            
            if is_us:
                df = PRO.us_daily(ts_code=code, start_date=start_date, end_date=end_date)
            else:
                # A股ETF
                if not code.endswith('.SH') and not code.endswith('.SZ'):
                    # 默认上海
                    code = f"{code}.SH"
                df = PRO.fund_daily(ts_code=code, start_date=start_date, end_date=end_date)
            
            if df is not None and len(df) > 0:
                df = df.sort_values('trade_date').reset_index(drop=True)
                self._tushare_cache[cache_key] = df
                return df
        except Exception as e:
            print(f"Tushare获取 {code} 日线失败: {e}")
        
        return None
    
    def calc_ma(self, closes, period):
        """计算简单移动平均"""
        if len(closes) < period:
            return None
        return float(np.mean(closes[-period:]))
    
    def calc_ema(self, closes, period):
        """计算EMA"""
        if len(closes) < period * 2:
            return None
        closes = np.array(closes, dtype=float)
        alpha = 2.0 / (period + 1)
        ema = closes[0]
        for i in range(1, len(closes)):
            ema = alpha * closes[i] + (1 - alpha) * ema
        return float(ema)
    
    def calc_atr(self, df, period=14):
        """计算ATR14"""
        if len(df) < period + 1:
            return None
        
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        
        tr_list = []
        for i in range(1, len(df)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            tr_list.append(tr)
        
        return float(np.mean(tr_list[-period:])) if len(tr_list) >= period else None
    
    def calc_rsi(self, closes, period=14):
        """计算RSI"""
        if len(closes) < period + 1:
            return None
        
        closes = np.array(closes, dtype=float)
        deltas = np.diff(closes[-period-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return float(100 - (100 / (1 + rs)))
    
    def calc_macd(self, closes):
        """计算MACD (12, 26, 9)"""
        if len(closes) < 35:
            return None
        
        closes = np.array(closes, dtype=float)
        ema12 = self._calc_ema_vector(closes, 12)
        ema26 = self._calc_ema_vector(closes, 26)
        
        diff = ema12 - ema26
        dea = self._calc_ema_vector(diff, 9)
        bar = 2 * (diff - dea)
        
        return {
            'DIFF': float(diff[-1]),
            'DEA': float(dea[-1]),
            'BAR': float(bar[-1]),
            'golden_cross': float(diff[-2]) <= float(dea[-2]) and float(diff[-1]) > float(dea[-1]),
            'death_cross': float(diff[-2]) >= float(dea[-2]) and float(diff[-1]) < float(dea[-1])
        }
    
    def _calc_ema_vector(self, data, period):
        """向量化EMA计算"""
        alpha = 2.0 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
        return ema
    
    def get_tech_indicators(self, code, is_us=False):
        """获取完整技术指标（Tushare盘后）"""
        df = self._get_tushare_daily(code, is_us)
        if df is None:
            return None
        
        closes = df['close'].values
        
        result = {
            'latest_date': str(df['trade_date'].iloc[-1]),
            'MA5': self.calc_ma(closes, 5),
            'MA10': self.calc_ma(closes, 10),
            'MA20': self.calc_ma(closes, 20),
            'MA40': self.calc_ma(closes, 40),
            'MA60': self.calc_ma(closes, 60),
            'ATR14': self.calc_atr(df, 14),
            'RSI14': self.calc_rsi(closes, 14),
            'MACD': self.calc_macd(closes),
            'H20': self.calc_ma(df['high'].values, 20) if len(df) >= 20 else None,
            'VOL_MA20': self.calc_ma(df['vol'].values.astype(float), 20) if len(df) >= 20 else None,
            'n_days': len(df)
        }
        
        return result
    
    # ========== 预警检查 ==========
    
    def check_federal_alerts(self, stock_config, data):
        """
        联邦专属预警层：
        - 止损价触发
        - 止盈价触发
        - 买入区间触发
        返回 (alerts, weights)
        """
        alerts = []
        weights = []
        code = stock_config['code']
        cost = stock_config.get('cost', 0)
        price = data['price']
        fed = stock_config.get('federal', {})
        
        if not fed or cost <= 0:
            return alerts, weights
        
        strategy = fed.get('strategy', '')
        
        # ─── 止损触发 ───
        stop_loss = fed.get('stop_loss', '')
        if stop_loss:
            # 解析止损位：如果是数字如"¥3.346"或百分比如"S6=−13%"
            sl_price = self._parse_price_trigger(stop_loss, cost, data)
            if sl_price and price <= sl_price:
                if not self._alerted_recently(code, 'federal_stop'):
                    alerts.append(('federal_stop', f"⛔ 联邦止损触发！现价≤止损 {sl_price:.2f}（{strategy}）"))
                    weights.append(5)  # 最高权重
        
        # ─── 止盈触发 ───
        take_profit = fed.get('take_profit', '')
        if take_profit:
            tp_price = self._parse_tp_trigger(take_profit, cost)
            if tp_price and price >= tp_price:
                if not self._alerted_recently(code, 'federal_tp'):
                    alerts.append(('federal_tp', f"🎯 联邦止盈触发！现价≥止盈 {tp_price:.2f}（{strategy}）"))
                    weights.append(5)
        
        # ─── 买入区间触发 ───
        entry_zone = fed.get('entry_zone', '')
        if entry_zone:
            entry_price = self._parse_entry_zone(entry_zone, cost)
            if entry_price and price <= entry_price:
                if not self._alerted_recently(code, 'federal_entry'):
                    alerts.append(('federal_entry', f"🟢 进入联邦买入区间！现价≤{entry_price:.2f}（{strategy}）"))
                    weights.append(4)
        
        # ─── ATR止损触发（仅盘后有ATR数据）───
        if 'ATR14' in data and data['ATR14']:
            atr = data['ATR14']
            stop_atr_mult = self._parse_atr_stop(stop_loss)
            if stop_atr_mult and atr > 0:
                sl_atr_price = cost - stop_atr_mult * atr
                if price <= sl_atr_price:
                    if not self._alerted_recently(code, 'federal_atr_stop'):
                        alerts.append(('federal_atr_stop', 
                            f"⛔ ATR止损触发！现价≤成本−{stop_atr_mult}×ATR14={sl_atr_price:.2f}"))
                        weights.append(5)
        
        return alerts, weights
    
    def _parse_price_trigger(self, text, cost, data):
        """解析止损/止盈价格"""
        if not text or cost <= 0:
            return None
        
        # 匹配显式价格: "¥3.346" / "$20.30" / "=$29.94" / "=$8.61"
        price_match = re.search(r'[=¥$]\s*(\d+(?:\.\d+)?)', text)
        if price_match:
            return float(price_match.group(1))
        
        # 匹配负百分比（止损专用）: "−13%" / "-15%" / "S6=−13%"
        neg_match = re.search(r'[−-](\d+(?:\.\d+)?)\s*%', text)
        if neg_match:
            pct = float(neg_match.group(1))
            return cost * (1 - pct / 100)
        
        # 如果文本不含负号百分比，说明可能是止盈文字（如"TP+10%"），
        # 不应该作为止损价格解析 → 返回None
        return None
    
    def _parse_tp_trigger(self, text, cost):
        """解析止盈价格：优先显式价格，其次正百分比"""
        if not text or cost <= 0:
            return None
        
        # 匹配显式价格: "=$29.94" / "¥3.346" / "$20.30"
        price_match = re.search(r'[=¥$]\s*(\d+(?:\.\d+)?)', text)
        if price_match:
            return float(price_match.group(1))
        
        # 匹配正百分比: "+10%" / "+50%" / "TP+10%"
        pos_match = re.search(r'\+(\d+(?:\.\d+)?)\s*%', text)
        if pos_match:
            pct = float(pos_match.group(1))
            return cost * (1 + pct / 100)
        
        return None
    
    def _parse_entry_zone(self, text, cost):
        """解析买入区间价格"""
        price_match = re.search(r'[¥$]\s*(\d+(?:\.\d+)?)', text)
        if price_match:
            return float(price_match.group(1))
        return None
    
    def _parse_atr_stop(self, text):
        """解析ATR止损倍数，如 '3.0×ATR14' → 3.0"""
        if not text:
            return None
        match = re.search(r'(\d+(?:\.\d+)?)\s*×\s*ATR', text)
        if match:
            return float(match.group(1))
        return None
    
    def check_alerts(self, stock_config, data):
        """检查所有预警条件"""
        alerts = []
        weights = []
        code = stock_config['code']
        cfg = stock_config.get('alerts', {})
        cost = stock_config.get('cost', 0)
        is_us = stock_config.get('market') == 'us'
        price = data['price']
        prev_close = data.get('prev_close', price)
        change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
        
        # ─── 1. 联邦专属预警（最高优先级）───
        fed_alerts, fed_weights = self.check_federal_alerts(stock_config, data)
        alerts.extend(fed_alerts)
        weights.extend(fed_weights)
        
        # ─── 2. 成本百分比 ───
        if cost > 0:
            cost_change_pct = (price - cost) / cost * 100
            if 'cost_pct_above' in cfg and cost_change_pct >= cfg['cost_pct_above']:
                if not self._alerted_recently(code, 'cost_above'):
                    alerts.append(('cost_above', f"🎯 盈利 {cfg['cost_pct_above']:.0f}% (现{price:.2f})"))
                    weights.append(3)
            if 'cost_pct_below' in cfg and cost_change_pct <= cfg['cost_pct_below']:
                if not self._alerted_recently(code, 'cost_below'):
                    alerts.append(('cost_below', f"🛑 亏损 {abs(cfg['cost_pct_below']):.0f}% (现{price:.2f})"))
                    weights.append(3)
        
        # ─── 3. 日内涨跌幅 ───
        if 'change_pct_above' in cfg and change_pct >= cfg['change_pct_above']:
            if not self._alerted_recently(code, 'pct_up'):
                alerts.append(('pct_up', f"📈 日内大涨 {change_pct:+.2f}%"))
                weights.append(2 if change_pct < 7 else 3)
        if 'change_pct_below' in cfg and change_pct <= cfg['change_pct_below']:
            if not self._alerted_recently(code, 'pct_down'):
                alerts.append(('pct_down', f"📉 日内大跌 {change_pct:+.2f}%"))
                weights.append(2 if change_pct > -7 else 3)
        
        # ─── 4. 均线金叉死叉（盘后有tech数据时）───
        macd = data.get('MACD')
        if macd:
            if macd.get('golden_cross') and not self._alerted_recently(code, 'ma_golden'):
                alerts.append(('ma_golden', f"🌟 MACD金叉 (DIFF={macd['DIFF']:.3f}上穿DEA={macd['DEA']:.3f})"))
                weights.append(3)
            if macd.get('death_cross') and not self._alerted_recently(code, 'ma_death'):
                alerts.append(('ma_death', f"⚠️ MACD死叉 (DIFF={macd['DIFF']:.3f}下穿DEA={macd['DEA']:.3f})"))
                weights.append(3)
        
        # ─── 5. RSI超买超卖 ───
        rsi = data.get('RSI14')
        if rsi:
            if rsi > 70 and not self._alerted_recently(code, 'rsi_high'):
                alerts.append(('rsi_high', f"🔥 RSI超买 ({rsi:.1f})，可能回调"))
                weights.append(2)
            elif rsi < 30 and not self._alerted_recently(code, 'rsi_low'):
                alerts.append(('rsi_low', f"❄️ RSI超卖 ({rsi:.1f})，可能反弹"))
                weights.append(2)
        
        # ─── 6. 跳空缺口（A股盘后）───
        if not is_us:
            open_price = data.get('open', price)
            prev_high = data.get('high', price)
            prev_low = data.get('low', price)
            
            if prev_high > 0 and open_price > prev_high * 1.01:
                gap_pct = (open_price - prev_high) / prev_high * 100
                if not self._alerted_recently(code, 'gap_up'):
                    alerts.append(('gap_up', f"⬆️ 向上跳空 {gap_pct:.1f}%"))
                    weights.append(2)
            elif prev_low > 0 and open_price < prev_low * 0.99:
                gap_pct = (prev_low - open_price) / prev_low * 100
                if not self._alerted_recently(code, 'gap_down'):
                    alerts.append(('gap_down', f"⬇️ 向下跳空 {gap_pct:.1f}%"))
                    weights.append(2)
        
        # ─── 7. 成交量异动（盘后有tech数据时）───
        vol_ma20 = data.get('VOL_MA20')
        current_vol = data.get('volume', 0)
        if vol_ma20 and current_vol > 0:
            vol_ratio = current_vol / vol_ma20
            if vol_ratio >= 2.0 and not self._alerted_recently(code, 'volume_surge'):
                alerts.append(('volume_surge', f"📊 放量 {vol_ratio:.1f}倍 (20日均量)"))
                weights.append(2)
            elif vol_ratio <= 0.5 and not self._alerted_recently(code, 'volume_shrink'):
                alerts.append(('volume_shrink', f"📉 缩量 {vol_ratio:.1f}倍 (20日均量)"))
                weights.append(1)
        
        # 计算预警级别
        level = self._calc_level(alerts, weights)
        
        return alerts, level
    
    def _calc_level(self, alerts, weights):
        """计算预警级别"""
        if not alerts:
            return None
        total_weight = sum(weights)
        n = len(alerts)
        
        if total_weight >= 5 or n >= 3:
            return "critical"
        if total_weight >= 3 or n >= 2:
            return "warning"
        return "info"
    
    def _alerted_recently(self, code, atype):
        """防重复：同一类型30分钟内不重复"""
        now = time.time()
        self.alert_log = [l for l in self.alert_log if now - l['t'] < 1800]
        for l in self.alert_log:
            if l['c'] == code and l['a'] == atype:
                return True
        return False
    
    def record_alert(self, code, atype):
        self.alert_log.append({'c': code, 'a': atype, 't': time.time()})
    
    def run_once(self, stocks_to_check=None, tech_scan=False):
        """
        执行一次监控
        stocks_to_check: 要监控的标的列表（None=全部）
        tech_scan: 是否扫描技术指标（盘后True/盘中False）
        """
        if stocks_to_check is None:
            stocks_to_check = WATCHLIST
        
        # 1. 获取实时价格
        data_map = self.fetch_realtime(stocks_to_check)
        
        # 2. 盘后补充Tushare技术指标
        if tech_scan:
            for stock in stocks_to_check:
                code = stock['code']
                is_us = stock.get('market') == 'us'
                
                tech = self.get_tech_indicators(code, is_us)
                if tech and code in data_map:
                    # 合并技术指标到data_map
                    for k, v in tech.items():
                        data_map[code][k] = v
                    # Tushare fund_daily vol单位是「手」（100股），转为「股」以匹配新浪
                    if not is_us and 'VOL_MA20' in tech and tech['VOL_MA20']:
                        data_map[code]['VOL_MA20'] = tech['VOL_MA20'] * 100
                    # 同时修正 data 里的 volume（如果新浪没拿到，用 Tushare 的）
                    if not is_us and 'TUSHARE_VOL' not in data_map[code]:
                        df = self._get_tushare_daily(code, is_us=False)
                        if df is not None and len(df) > 0:
                            data_map[code]['TUSHARE_VOL'] = float(df['vol'].values[-1]) * 100
        
        # 3. 检查预警
        triggered = []
        for stock in stocks_to_check:
            code = stock['code']
            if code not in data_map:
                continue
            
            data = data_map[code]
            if data['price'] <= 0:
                continue
            
            alerts, level = self.check_alerts(stock, data)
            
            if alerts:
                change_pct = 0
                if data.get('prev_close', 0) > 0:
                    change_pct = (data['price'] - data['prev_close']) / data['prev_close'] * 100
                
                color = "🔴" if change_pct > 0 else ("🟢" if change_pct < 0 else "⚪")
                level_icon = {"critical": "🚨", "warning": "⚠️", "info": "📢"}.get(level, "📢")
                level_text = {"critical": "【紧急】", "warning": "【警告】", "info": "【提醒】"}.get(level, "")
                
                msg = f"{level_icon} {level_text}{color} {stock['name']} ({code})\n"
                msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                msg += f"💰 现价: {data['price']:.2f} ({change_pct:+.2f}%)\n"
                
                cost = stock.get('cost', 0)
                if cost > 0:
                    cost_change = (data['price'] - cost) / cost * 100
                    msg += f"📊 成本: {cost:.2f} | 盈亏: {cost_change:+.2f}%\n"
                
                # 联邦参数
                fed = stock.get('federal', {})
                if fed:
                    msg += f"📐 策略: {fed.get('strategy', 'N/A')}\n"
                    if data.get('ATR14'):
                        msg += f"📏 ATR14: {data['ATR14']:.2f}\n"
                
                msg += f"\n🎯 触发预警 ({len(alerts)}项):\n"
                for aid, text in alerts:
                    msg += f"  • {text}\n"
                    self.record_alert(code, aid)
                
                triggered.append(msg)
        
        return triggered


if __name__ == '__main__':
    monitor = StockAlert()
    for alert in monitor.run_once():
        print(alert)
