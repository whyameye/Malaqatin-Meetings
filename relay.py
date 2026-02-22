#!/usr/bin/env python3
"""
Simple WebSocket relay — broadcasts any message from any client to all others.
Usage: python3 relay.py [port]   (default port: 8765)
"""
import asyncio
import sys
import websockets

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
clients = set()

async def handler(ws):
    clients.add(ws)
    addr = ws.remote_address
    print(f"[+] {addr}  ({len(clients)} connected)")
    try:
        async for message in ws:
            others = clients - {ws}
            if others:
                await asyncio.gather(*[c.send(message) for c in others])
    except websockets.ConnectionClosed:
        pass
    finally:
        clients.discard(ws)
        print(f"[-] {addr}  ({len(clients)} connected)")

async def main():
    print(f"Relay listening on ws://0.0.0.0:{PORT}")
    async with websockets.serve(handler, "0.0.0.0", PORT):
        await asyncio.Future()

asyncio.run(main())
