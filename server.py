#!/usr/bin/env python3
"""Simple HTTP server that also handles PUT requests to save JSON files."""
import http.server
import os

ALLOWED_FILES = {'scene1.json', 'scene2.json', 'scene3.json', 'perform_config.json', 'config.json'}
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

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

if __name__ == '__main__':
    import socket
    port = 8080
    hostname = socket.gethostname()
    try:
        lan_ip = socket.gethostbyname(hostname)
    except Exception:
        lan_ip = '?.?.?.?'
    print(f'Serving on http://localhost:{port}  (this machine)')
    print(f'         on http://{lan_ip}:{port}  (other machines on LAN)')
    print(f'Directory: {DIRECTORY}')
    print(f'Allowed saves: {ALLOWED_FILES}')
    server = http.server.HTTPServer(('', port), Handler)
    server.serve_forever()
