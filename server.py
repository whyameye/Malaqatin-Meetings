#!/usr/bin/env python3
"""
Combined server:
  HTTP on port 8080 — serves files, handles PUT saves
  WebSocket on port 8765 — relays events between performer and display
"""
import asyncio
import http.server
import os
import socket
import threading
import websockets

HTTP_PORT = 8080
WS_PORT   = 8765
ALLOWED_FILES = {'scene1.json', 'scene2.json', 'scene3.json', 'perform_config.json', 'config.json'}
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

# ── HTTP ─────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_PUT(self):
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
    hostname = socket.gethostname()
    try:
        lan_ip = socket.gethostbyname(hostname)
    except Exception:
        lan_ip = '?.?.?.?'

    print(f'HTTP  http://localhost:{HTTP_PORT}     (this machine)')
    print(f'      http://{lan_ip}:{HTTP_PORT}  (LAN)')
    print(f'WS    ws://localhost:{WS_PORT}')
    print(f'      ws://{lan_ip}:{WS_PORT}  (LAN)')
    print(f'Directory: {DIRECTORY}')

    # HTTP in a background thread
    http_server = http.server.HTTPServer(('', HTTP_PORT), Handler)
    t = threading.Thread(target=http_server.serve_forever, daemon=True)
    t.start()

    # WebSocket in the asyncio loop
    async with websockets.serve(ws_handler, '0.0.0.0', WS_PORT):
        await asyncio.Future()

asyncio.run(main())
