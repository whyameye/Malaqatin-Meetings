# Susan — Performance System Architecture

## Overview

A browser-based live projection system for musical performance. Regions of a ceiling photograph are lit, sparkled, and animated in sync with live music, triggered by a MIDI controller.

The system runs entirely in Chrome browser — no native installs required on any performance machine beyond Chrome itself.

---

## Machines

### 1. Cloud Linux Box (asset server)
- Serves all static assets (HTML, images, JSON) over HTTPS
- Runs `server.py` (Python HTTP server with PUT support for the editor)
- Optionally runs a WebSocket relay endpoint (see Networking below)
- Accessible from anywhere with internet

### 2. Performer Linux Laptop
- Runs Chrome with `perform.html?role=performer`
- Connected to Oxygen 8 USB MIDI controller
- Receives MIDI Note On/Off events → triggers sequences
- Sends sequence events to display machine via WebSocket
- Renders the performance view locally (performer can watch their own screen)
- Hosts the WebSocket relay (preferred) or connects to cloud relay (fallback)

### 3. Display Machine (venue/school property)
- Any machine running Chrome browser — no installation required
- Runs `perform.html?role=display`
- Connects to WebSocket relay, receives sequence events from performer
- Renders the projection — identical logic to performer, driven by incoming events
- No MIDI, no keyboard input — purely reactive

---

## Networking

The WebSocket URL is a single configurable value. Three options in order of preference:

### Option 1 — Performer Laptop Hotspot (preferred)
```
Venue WiFi → Performer Laptop (internet) → shares hotspot
                                          ↘
                              Display Machine connects to hotspot
                              WebSocket: ws://192.168.x.x:8765
```
- Performer laptop connects to venue WiFi for internet (asset loading)
- Simultaneously shares its connection as a WiFi hotspot
- Display machine connects to that hotspot
- WebSocket relay runs on performer laptop (`localhost:8765` from its perspective)
- Fully self-contained LAN — immune to venue firewall/client isolation
- On Linux: `nmcli device wifi hotspot ifname wlan0 ssid SusanPerf password yourpass`

### Option 2 — Phone Hotspot (fallback)
```
Phone hotspot LAN
├── Performer laptop (WebSocket relay + performer view)
└── Display machine (display view)
```
- Both machines connect to phone's hotspot
- Phone has no client isolation — peer-to-peer works
- WebSocket relay runs on performer laptop
- Use if performer laptop can't simultaneously connect to venue WiFi + share hotspot

### Option 3 — Cloud Relay (fallback)
```
Both machines → venue WiFi → internet → cloud Linux box (WebSocket relay)
WebSocket: wss://yourserver.com/relay
```
- Works on any internet connection regardless of client isolation
- Latency: ~50–150ms (imperceptible for visual art)
- Use if no hotspot is available

---

## Single HTML File

`perform.html` handles both roles via URL parameter:

```
perform.html?role=performer&ws=ws://192.168.x.x:8765
perform.html?role=display&ws=ws://192.168.x.x:8765
```

- `role=performer`: enables MIDI input, keyboard fallback, sends events to relay
- `role=display`: connects to relay, receives events, renders projection
- `ws=` : WebSocket relay URL (defaults to `ws://localhost:8765` if omitted)
- Both roles run identical rendering code — same visual output

---

## MIDI

- **Controller**: M-Audio Oxygen 8 (USB)
- **Browser API**: Web MIDI API (Chrome only, requires HTTPS or localhost)
- **Mapping**:
  - Note On → `activateSequence(key)` (equivalent to key down)
  - Note Off → `deactivateSequence(key)` (equivalent to key up)
  - MIDI note numbers mapped to sequence keys in config
  - Knobs (CCs) → config parameters (dimLevel, litLevel, etc.) — future
- **HTTPS requirement**: Web MIDI API requires a secure context. Assets served from cloud over HTTPS satisfies this. Hotspot relay uses `ws://` (not `wss://`) which is allowed from an HTTPS page when the relay is on a local/private IP.

---

## Event Protocol (WebSocket)

Performer sends minimal JSON events to relay; relay broadcasts to all display clients:

```json
{ "type": "activate",   "seqId": "s0" }
{ "type": "deactivate", "seqId": "s0" }
{ "type": "scene",      "sceneIdx": 1 }
```

Relay is a simple broadcast server — no state, no logic. Any message received from performer is forwarded to all connected display clients.

---

## Asset Loading

All assets (images, region maps, JSON) are loaded by both performer and display machines directly from the cloud server over HTTPS. The WebSocket relay carries only lightweight event messages — not image data.

```
Cloud server (HTTPS)
├── perform.html
├── config.json
├── ceiling1_closeup_21Feb0747.png
├── m1s1_region_id_map.png
├── m1s1_region_meta.json
└── ...etc
```

---

## Editor

`editor.html` — scene editor, runs in browser, saves via HTTP PUT to `server.py`. Used on any machine with access to the cloud server. Not part of the live performance stack.

---

## Pre-Performance Checklist

1. Cloud server running (`server.py`)
2. Performer laptop: connect to venue WiFi, start hotspot, plug in Oxygen 8
3. Display machine: connect to performer hotspot, open Chrome, navigate to display URL
4. Performer: open Chrome, navigate to performer URL, confirm MIDI device detected
5. Test: press MIDI key on Oxygen 8 → verify regions light on display
6. Disable display machine screensaver/sleep
7. Set Chrome to fullscreen (F11) on display machine

---

## Software Stack

| Component | Technology |
|-----------|------------|
| Asset server | Python (`server.py`) |
| WebSocket relay | Python (`websockets` library) |
| Performer/Display UI | Vanilla HTML/JS/Canvas (single file) |
| MIDI | Web MIDI API (Chrome) |
| Region processing | Python (`generate_regions.py`) |
| Scene editing | `editor.html` (browser) |
