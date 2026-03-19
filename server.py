#!/usr/bin/python3
"""
Combined server:
  HTTP on port 8082 — serves files, handles PUT saves
  WebSocket on port 8765 — relays events between performer and display

Environment variables:
  HTTP_PORT     HTTP port (default 8082)
  HTTP_HOST     HTTP bind address (default '' = all interfaces)
  WS_HOST       WebSocket bind address (default '0.0.0.0')
  WS_PORT       WebSocket port (default 8765)
  SECRET_TOKEN  If set, all HTTP requests and WebSocket connections must
                include ?token=<value> or the request is rejected (403/close).
                If unset, no token check is performed (local use).
"""
import asyncio
import http.server
import os
import socket
import threading
from urllib.parse import urlparse, parse_qs
import websockets

HTTP_PORT = int(os.environ.get('HTTP_PORT', 8082))
HTTP_HOST = os.environ.get('HTTP_HOST', '')
WS_PORT   = int(os.environ.get('WS_PORT', 8765))
WS_HOST   = os.environ.get('WS_HOST', '0.0.0.0')
SECRET_TOKEN = os.environ.get('SECRET_TOKEN', '')  # empty = no auth

ALLOWED_FILES = {'scene1.json', 'scene2.json', 'scene3.json', 'perform_config.json', 'config.json'}
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

def _token_ok(path):
    """Return True if token auth is disabled or the request token matches."""
    if not SECRET_TOKEN:
        return True
    qs = parse_qs(urlparse(path).query)
    return qs.get('token', [None])[0] == SECRET_TOKEN

# ── HTTP ─────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def _check_token(self):
        if not _token_ok(self.path):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'Forbidden')
            return False
        return True

    def do_GET(self):
        if not self._check_token():
            return
        super().do_GET()

    def do_HEAD(self):
        if not self._check_token():
            return
        super().do_HEAD()

    def do_PUT(self):
        if not self._check_token():
            return
        filename = os.path.basename(self.path.split('?')[0].lstrip('/'))
        if filename not in ALLOWED_FILES:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'Not allowed')
            return
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        filepath = os.path.join(DIRECTORY, filename)
        with open(filepath, 'wb') as f:
            f.write(body)
        print(f'Saved {filename} ({len(body)} bytes)')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b'OK')

    def do_OPTIONS(self):
        if not self._check_token():
            return
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress per-request logging

# ── WebSocket relay ───────────────────────────────────────────
ws_clients = set()

async def ws_handler(ws):
    # websockets <13 exposes path directly; >=13 moved it to ws.request.path
    ws_path = getattr(ws, 'path', None) or getattr(ws.request, 'path', '/')
    if not _token_ok(ws_path):
        await ws.close(1008, 'Forbidden')
        return
    ws_clients.add(ws)
    addr = ws.remote_address
    print(f'[WS] +{addr}  ({len(ws_clients)} connected)')
    try:
        async for message in ws:
            others = ws_clients - {ws}
            if others:
                await asyncio.gather(*[c.send(message) for c in others])
    except websockets.ConnectionClosed:
        pass
    finally:
        ws_clients.discard(ws)
        print(f'[WS] -{addr}  ({len(ws_clients)} connected)')

async def main():
    lan_ip = '?.?.?.?'
    # Try each common gateway to find the active LAN interface
    for target in ('8.8.8.8', '192.168.1.1', '192.168.0.1', '10.0.0.1'):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 80))
                ip = s.getsockname()[0]
                if not ip.startswith('127.'):
                    lan_ip = ip
                    break
        except Exception:
            continue

    auth = f' (token auth {"ON" if SECRET_TOKEN else "OFF"})'
    print(f'HTTP  http://localhost:{HTTP_PORT}     (this machine){auth}')
    print(f'      http://{lan_ip}:{HTTP_PORT}  (LAN)')
    print(f'WS    ws://localhost:{WS_PORT}')
    print(f'      ws://{lan_ip}:{WS_PORT}  (LAN)')
    print(f'Directory: {DIRECTORY}')

    # HTTP in a background thread
    http_server = http.server.HTTPServer((HTTP_HOST, HTTP_PORT), Handler)
    t = threading.Thread(target=http_server.serve_forever, daemon=True)
    t.start()

    # WebSocket in the asyncio loop
    async with websockets.serve(ws_handler, WS_HOST, WS_PORT):
        await asyncio.Future()

asyncio.run(main())
