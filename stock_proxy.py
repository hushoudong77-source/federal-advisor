#!/usr/bin/env python3
"""美股+A股+宏观行情代理 (8898端口) — Sina股市 + Yahoo宏观"""
import http.server, json, urllib.request, time, socketserver, re, ssl, concurrent.futures

_ctx = ssl._create_unverified_context()
PORT = 8898

US_TICKERS = [
    ("QQQ","Invesco QQQ"), ("IVV","iShares S&P 500"),
    ("VTI","Vanguard Total Stock"), ("VEA","FTSE Developed"),
    ("IAU","iShares Gold Trust"), ("BBJP","JPMorgan Japan"),
    ("MUFG","Mitsubishi UFJ"), ("EWY","MSCI South Korea"),
    ("VNM","VanEck Vietnam"), ("FLIN","Franklin FTSE India"),
    ("SMIN","iShares MSCI India"),
    ("CANE","Teucrium Sugar Fund"),
]

CN_TICKERS = [
    ("sh510300","华泰柏瑞沪深300"),("sh510500","南方中证500"),
    ("sz159915","易方达创业板"),("sh588000","华夏科创50"),
    ("sh513180","易方达恒生科技"),
    ("sh513910","华泰柏瑞红利低波"),("sz159545","广发中证红利"),
    ("sz159302","易方达中证红利"),("sh518880","华安黄金ETF"),
]

# 宏观指标 — Yahoo Finance
_YAHOO_MACRO = [
    ("^TYX","美国20Y国债"), ("^TNX","美国10Y国债"), ("IEF","7-10Y国债ETF"),
    ("BZ=F","布伦特原油"), ("DX-Y.NYB","美元指数"),
    ("DBC","CRB商品"), ("^VIX","VIX恐慌"),
]

def fetch_sina_quotes(tickers, prefix="gb_"):
    if not tickers: return []
    codes = [prefix + t[0].lower() for t in tickers]
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent":"Mozilla/5.0","Referer":"https://finance.sina.com.cn"})
        with urllib.request.urlopen(req, timeout=8, context=_ctx) as r:
            try: text = r.read().decode("gbk")
            except: text = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return [{"code":t[0],"name":t[1],"error":str(e)[:40]} for t in tickers]
    results = []
    for t in tickers:
        code = t[0]
        var_name = f"hq_str_{prefix}{code.lower()}"
        m = re.search(re.escape(var_name)+r'="([^"]*)"', text)
        if not m:
            results.append({"code":code,"name":t[1],"error":"no data"})
            continue
        f = m.group(1).split(",")
        p = float(f[1]) if len(f)>1 and f[1] else None
        c = float(f[2]) if len(f)>2 and f[2] else None
        results.append({"code":code,"name":t[1],"price":p,"change_pct":c})
    return results

def fetch_cn_forex():
    """获取美元兑人民币在岸汇率"""
    try:
        url = "https://hq.sinajs.cn/list=fx_susdcny"
        req = urllib.request.Request(url, headers={
            "User-Agent":"Mozilla/5.0","Referer":"https://finance.sina.com.cn"})
        with urllib.request.urlopen(req, timeout=8, context=_ctx) as r:
            text = r.read().decode("gbk")
        f = text.split(",")
        if len(f) > 3:
            price = float(f[1]) if f[1] else None
            prev = float(f[3]) if f[3] else None
            chg = round((price-prev)/prev*100,2) if price and prev else None
            return {"code":"USDCNY","name":"美元/人民币","price":price,"change_pct":chg}
        return {"code":"USDCNY","name":"美元/人民币","error":"parse fail"}
    except Exception as e:
        return {"code":"USDCNY","name":"美元/人民币","error":str(e)[:40]}

def fetch_cn_quotes():
    results = []
    for code, name in CN_TICKERS:
        try:
            url = f"https://hq.sinajs.cn/list={code}"
            req = urllib.request.Request(url, headers={
                "User-Agent":"Mozilla/5.0","Referer":"https://finance.sina.com.cn"})
            with urllib.request.urlopen(req, timeout=8, context=_ctx) as r:
                try: text = r.read().decode("gbk")
                except: text = r.read().decode("utf-8", errors="replace")
            m = re.search(r'"([^"]*)"', text)
            if m:
                f = m.group(1).split(",")
                price = float(f[3]) if len(f)>3 and f[3] else None
                prev = float(f[2]) if len(f)>2 and f[2] else None
                chg = round((price-prev)/prev*100,2) if price and prev else None
                results.append({"code":code,"name":name,"price":price,"change_pct":chg})
            else:
                results.append({"code":code,"name":name,"error":"parse fail"})
        except Exception as e:
            results.append({"code":code,"name":name,"error":str(e)[:40]})
        time.sleep(0.15)
    return results

def _fetch_one_macro(item):
    code, name = item
    proxy_h = urllib.request.ProxyHandler({'https': 'http://127.0.0.1:7890'})
    proxy_opener = urllib.request.build_opener(proxy_h)
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with proxy_opener.open(req, timeout=2) as r:
            meta = json.loads(r.read())["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("previousClose") or meta.get("chartPreviousClose")
        chg = round((price-prev)/prev*100,2) if price and prev else None
        return {"code":code,"name":name,"price":price,"change_pct":chg}
    except urllib.error.HTTPError as e:
        return {"code":code,"name":name,"error":f"HTTP {e.code}"}
    except Exception as e:
        return {"code":code,"name":name,"error":str(e)[:40]}

def fetch_macro():
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        return list(pool.map(_fetch_one_macro, _YAHOO_MACRO))

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/yahoo":
            self.send_json(fetch_sina_quotes(US_TICKERS,"gb_") + fetch_macro())
            return
        if self.path == "/api/yahoo/cn":
            result = fetch_tencent_quotes()
            if not any(s.get("price") for s in result):
                result = fetch_cn_quotes()
            result.append(fetch_cn_forex())
            self.send_json(result)
            return
        self.send_response(404); self.end_headers()

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Cache-Control","no-cache")
        self.end_headers()
        count = len([r for r in data if r.get("price")])
        self.wfile.write(json.dumps({
            "updated":time.strftime("%H:%M:%S"),"count":count,"stocks":data
        }, ensure_ascii=False).encode())
    def log_message(self,f,*a): pass

class S(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    print(f"🦐 行情代理 → http://localhost:{PORT}/api/yahoo")


def fetch_tencent_quotes():
    """腾讯行情API (备用，支持A股)"""
    codes = "sh510300,sh510500,sz159915,sh588000,sh513180,sh513910,sz159302,sh518880"
    url = f"https://qt.gtimg.cn/q={codes}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent","Mozilla/5.0")
    try:
        resp = urllib.request.urlopen(req, timeout=8, context=_ctx)
        raw = resp.read()
        # GBK解码
        try:
            text = raw.decode("gbk")
        except:
            text = raw.decode("utf-8","ignore")
        results = []
        for m in re.finditer(r'v_\w+="([^"]+)"', text):
            if not m: continue
            parts = m.group(1).split("~")
            if len(parts) < 35: continue
            name = parts[1]
            code_raw = parts[2]
            price = float(parts[3]) if parts[3] else 0
            chg_pct = float(parts[32]) if parts[32] else 0
            chg_amt = float(parts[31]) if parts[31] else 0
            high = float(parts[33]) if parts[33] else 0
            low = float(parts[34]) if parts[34] else 0
            open_ = float(parts[5]) if parts[5] else 0
            prev_close = float(parts[4]) if parts[4] else 0
            volume = float(parts[6]) if parts[6] else 0
            amount = volume * price
            results.append({
                "code": code_raw, "name": name,
                "price": price, "change_pct": chg_pct,
                "change_amt": chg_amt, "high": high,
                "low": low, "open": open_,
                "prev_close": prev_close, "volume": volume,
            })
        return results
    except Exception as e:
        return [{"code":"ERROR","name":str(e),"price":0,"change_pct":0}]


if __name__ == "__main__":
    S(("0.0.0.0", PORT), H).serve_forever()
