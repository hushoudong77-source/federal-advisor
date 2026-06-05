#!/usr/bin/env python3
"""local dev server: static files + CORS proxy + session-routed chat"""
import http.server
import certifi
import json
import os
import re
import ssl
import sys
import time
import urllib.request
import urllib.parse

# SSL context: trust certifi bundle (macOS Python 3.14 needs this)
_ssl_ctx = ssl.create_default_context(cafile=certifi.where())
_https_handler = urllib.request.HTTPSHandler(context=_ssl_ctx)
_opener = urllib.request.build_opener(_https_handler)
urllib.request.install_opener(_opener)

PORT = 8899
DIR = os.path.dirname(os.path.abspath(__file__))

PROXY_BACKEND = 'http://127.0.0.1:8898'
GATEWAY_BASE = 'http://127.0.0.1:18789'

# Cache for the active session key (refreshed on error or every N calls)

def _get_gateway_token():
    try:
        with open(os.path.expanduser('~/.openclaw/openclaw.json')) as f:
            return json.load(f)['gateway']['auth']['token']
    except Exception:
        return ''

def _proxy_to(url, path, self):
    """Generic GET proxy: forward request to backend."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'OpenClaw/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, max-age=15')
        self.end_headers()
        self.wfile.write(body)
    except Exception as e:
        body = json.dumps({'ok': False, 'error': str(e)}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

def _call_tool(tool, args, timeout=30):
    """Call /tools/invoke on the gateway. Returns (ok, result_or_error)."""
    token = _get_gateway_token()
    payload = json.dumps({'tool': tool, 'args': args}).encode()
    req = urllib.request.Request(
        f'{GATEWAY_BASE}/tools/invoke', data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            if data.get('ok') and data.get('result'):
                return True, data['result']
            return False, data.get('error', 'unknown error')
    except urllib.error.HTTPError as e:
        return False, f'HTTP {e.code}: {e.read().decode()[:200]}'
    except Exception as e:
        return False, str(e)


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'authorization, content-type, x-openclaw-model')
        self.send_header('Access-Control-Max-Age', '86400')
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/api/fa-chat':
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len) if content_len > 0 else b'{}\n'
            data = json.loads(body)
            msgs = data.get('messages', [])
            context_prompt = data.get('context', '')

            # 加载联邦投顾系统定义
            fa_dir = os.path.join(DIR, 'federal-advisor')
            sys_path = os.path.join(fa_dir, 'SYSTEM.md')
            try:
                with open(sys_path, 'r', encoding='utf-8') as f:
                    system_prompt = f.read()
            except Exception as e:
                system_prompt = f'你是联邦投顾，冷酷的资产审计官。\n指令：用简洁、数据驱动、结论先行的风格。回答要冷酷、直接、专业，不加感情修饰。用户是操作员，按指令执行。'
                print(f'[FA] 加载SYSTEM.md失败: {e}')

            openai_msgs = [{'role': 'system', 'content': system_prompt}]
            for m in msgs:
                openai_msgs.append({
                    'role': 'user' if m.get('role') == 'user' else 'assistant',
                    'content': m.get('content', '')
                })

            if context_prompt:
                openai_msgs.append({'role': 'system', 'content': f'额外上下文：{context_prompt}'})

            # 调用网关 OpenAI 兼容 API
            token = _get_gateway_token()
            payload = json.dumps({
                'model': 'openclaw',
                'messages': openai_msgs,
                'max_tokens': 8192,
            }).encode()

            try:
                req = urllib.request.Request(
                    f'{GATEWAY_BASE}/v1/chat/completions',
                    data=payload,
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {token}',
                    })
                with urllib.request.urlopen(req, timeout=300) as resp:
                    result = json.loads(resp.read())
                    reply = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                    self._send_json(200, {'ok': True, 'result': reply})
            except urllib.error.HTTPError as e:
                err = e.read().decode()[:500]
                self._send_json(e.code, {'ok': False, 'error': err})
            except Exception as e:
                self._send_json(502, {'ok': False, 'error': str(e)})
            return

        if path == '/chat/completions' or path.startswith('/api/chat'):
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len) if content_len > 0 else b'{}'
            
            # 全部走 LinkAI
            linkai_url = 'https://api.link-ai.tech/v1/chat/memory/completions'
            auth = self.headers.get('Authorization', '')
            try:
                req = urllib.request.Request(linkai_url, data=body,
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': auth,
                        'User-Agent': 'OpenClaw/1.0',
                    })
                with urllib.request.urlopen(req, timeout=180) as resp:
                    self.send_response(resp.status)
                    ct = resp.headers.get('Content-Type', 'application/json')
                    self.send_header('Content-Type', ct)
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(e.read())
            except Exception as e:
                self.send_response(502)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            return

        self.send_response(405)
        self.end_headers()
        self.wfile.write(b'POST not supported at this path')

    def _send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _proxy_post(self, body, url):
        """Direct POST proxy to arbitrary URL (fallback)."""
        token = _get_gateway_token()
        try:
            req = urllib.request.Request(url, data=body,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {token}',
                    'User-Agent': 'OpenClaw/1.0',
                })
            with urllib.request.urlopen(req, timeout=120) as resp:
                rbody = resp.read()
                self.send_response(resp.status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(rbody)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(rbody)
        except urllib.error.HTTPError as e:
            rbody = e.read()
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(rbody)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(rbody)
        except Exception as e:
            err = json.dumps({'error': str(e)}).encode()
            self.send_response(502)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(err)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(err)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = parsed.query

        if path == '/api/news':
            # 跑马灯快讯：华尔街见闻 live 流
            try:
                api_url = 'https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=20'
                req = urllib.request.Request(api_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    'Referer': 'https://wallstreetcn.com/live/global',
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                raw_items = data.get('data', {}).get('items', [])
                items = []
                for item in raw_items:
                    if not item.get('content_text') and not item.get('title'):
                        continue
                    title = (item.get('title') or '').strip()
                    content = (item.get('content_text') or item.get('content') or '').strip()
                    # 去掉 HTML 标签
                    content = re.sub(r'<[^>]+>', '', content)[:200]
                    if not title and not content:
                        continue
                    items.append({
                        'time': item.get('display_time', 0),
                        'title': title,
                        'content': content,
                        'score': item.get('score', 0),
                    })
                body = json.dumps({'items': items}, ensure_ascii=False).encode()
            except Exception as e:
                body = json.dumps({'items': [], 'error': str(e)}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'max-age=30')
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith('/api/'):
            backend_url = f'{PROXY_BACKEND}{path}'
            if query:
                backend_url += '?' + query
            _proxy_to(backend_url, path, self)
            return

        if path.startswith('/wscn/'):
            # 华尔街见闻代理: /wscn/xxx → https://api-one.wallstcn.com/apiv1/xxx
            api_path = path[len('/wscn/'):]
            api_url = f'https://api-one.wallstcn.com/apiv1/{api_path}'
            if query:
                api_url += '?' + query
            try:
                req = urllib.request.Request(api_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    'Referer': 'https://wallstreetcn.com/',
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = resp.read()
            except Exception as e:
                body = json.dumps({'ok': False, 'error': str(e)}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'max-age=30')
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith('/proxy/cls'):
            try:
                req = urllib.request.Request(
                    'https://www.cls.cn/telegraph',
                    headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    html = resp.read().decode('utf-8', errors='ignore')
                m = re.search(r'__NEXT_DATA__[^>]*>([\s\S]*?)</script', html)
                if m:
                    data = json.loads(m.group(1))
                    items = data['props']['pageProps']['initialState']['telegraph']['telegraphList']
                    result = []
                    for item in items[:5]:
                        title = item.get('title', '') or ''
                        content = item.get('content', '') or ''
                        if not title:
                            tm = re.search(r'【([^】]+)】', content)
                            if tm:
                                title = tm.group(1)
                                content = content.replace('【' + title + '】', '').strip()
                        result.append({
                            'title': title,
                            'content': content,
                            'reading': item.get('reading_num', 0),
                            'ctime': item.get('ctime', 0)
                        })
                    body = json.dumps({'ok': True, 'items': result}, ensure_ascii=False).encode()
                else:
                    body = json.dumps({'ok': False, 'error': 'no data'}).encode()
            except Exception as e:
                body = json.dumps({'ok': False, 'error': str(e)}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'max-age=30')
            self.end_headers()
            self.wfile.write(body)
            return

        super().do_GET()

    def log_message(self, fmt, *args):
        if '/proxy/cls' not in args[0]:
            super().log_message(fmt, *args)

if __name__ == '__main__':
    print(f'🦐 投资决策专家服务端  http://localhost:{PORT}/linkai-chat.html')

    os.chdir(DIR)
    srv = http.server.ThreadingHTTPServer(('0.0.0.0', PORT), ProxyHandler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
