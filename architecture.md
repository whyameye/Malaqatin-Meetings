# Susan — Performance System Architecture

## Overview

A browser-based live projection system for musical performance. Regions of a ceiling photograph are lit, sparkled, and animated in sync with live music, triggered by a MIDI controller.

The system runs entirely in Chrome browser — no native installs required on any performance machine beyond Chrome itself.

---

## Machines

### 1. Performer Linux Laptop
- Runs Chrome with `perform.html?role=performer`
- Connected to Oxygen 8 USB MIDI controller
- Runs `server.py` — serves all assets (HTML, images, JSON) to both machines
- Runs `relay.py` — WebSocket relay, broadcasts events to display machine
- HUD displayed by default — shows connection status, MIDI status, active sequences, FPS
- Performer (keyboardist) watches this screen during performance

### 2. Display Laptop (brought to venue)
- Runs Chrome with `perform.html?role=display`
- Connects to performer laptop via WiFi router for assets and WebSocket events
- Renders the projection — identical visual logic, driven by incoming WebSocket events
- No HUD, no keyboard input, no MIDI — purely reactive
- Projector connects to this machine

---

## Networking

### Primary — Private WiFi Router
```
WiFi Router (brought to venue, power only)
├── Performer laptop: serves assets + relay, opens http://localhost
└── Display laptop: opens http://[performer-laptop-ip]
                    WebSocket: ws://[performer-laptop-ip]:8765
```
- Bring any standard WiFi router to the venue — needs only a power outlet
- Both machines connect wirelessly to it; all traffic stays on private LAN
- No internet required — completely self-contained
- Performer opens `http://localhost` (secure context → Web MIDI works)
- Display opens `http://[performer-laptop-ip]` (no MIDI needed)
- Low latency (~2–5ms), immune to venue network issues

### Fallback — Internet Relay
```
Both machines → venue WiFi or phone tether → internet → relay server
WebSocket: wss://yourserver.com/relay
```
- If private router isn't available or fails
- Both machines independently connect to any available internet
- WebSocket events routed through internet relay (~50–100ms latency)
- Assets still served from performer laptop (requires both on same network)
  or from a cloud server (no shared network needed)
- Switch by changing the `ws=` URL parameter — no code changes

### Development (no WebSocket)
```
perform.html (no ws= parameter)
```
- Runs fully standalone — no WebSocket connection attempted
- Full keyboard and MIDI input, all rendering works normally
- Use for building and configuring without needing two machines

---

## Single HTML File

`perform.html` handles both roles via URL parameters:

```
# Performer (primary)
perform.html?role=performer&ws=ws://192.168.x.x:8765

# Display
perform.html?role=display&ws=ws://192.168.x.x:8765

# Standalone development (no WebSocket)
perform.html
```

- `role=performer`: MIDI input, keyboard input, sends events via WebSocket if connected, HUD shown by default
- `role=display`: receives WebSocket events only, renders visuals, no HUD, no input
- `ws=`: WebSocket relay URL — if omitted, runs standalone with no WebSocket
- WebSocket connection is optional — performer works fully without it
- Both roles run identical rendering code — same visual output

---

## HUD (Performer Only)

Shown by default on `role=performer`, never on `role=display`. Toggle with H key.

Displays:
- WebSocket status: `WS: connected` / `WS: disconnected` / `WS: off`
- MIDI status: `MIDI: Oxygen 8` / `MIDI: not found`
- Current movement and scene
- Active sequences with effect, step, and opacity
- FPS

---

## MIDI

- **Controller**: M-Audio Oxygen 8 — 25 mini keys (2 octaves), 8 assignable knobs, pitch wheel (springs to center), mod wheel
- **Browser API**: Web MIDI API (Chrome only, requires HTTPS or localhost)
- **Linux firmware**: Oxygen 8 requires firmware upload on connect — install `midisport-firmware` package (`sudo apt install midisport-firmware`), then replug device
- **MIDI is additive**: all existing computer keyboard bindings continue to work alongside MIDI

### Piano Keys → Sequences
- Note On → `activateSequence()` (equivalent to key down)
- Note Off → `deactivateSequence()` (equivalent to key up)
- Mapping defined in `config.json` as `midiNoteMap`: keyboard key → MIDI note number
  ```json
  "midiNoteMap": { "q": 60, "w": 62, "e": 64 }
  ```
- Incoming MIDI note looked up in map → matching sequence activated/deactivated

### Pitch Wheel → Scene Changes
- Pitch wheel value range: 0–127 (center = 64, springs back to center when released)
- Value > 96 (above 75%) → next scene (triggers once per gesture, resets when wheel returns to center)
- Value < 32 (below 25%) → previous scene
- Middle zone (32–96) = no action / resets trigger ready for next gesture

### Knobs → Movement Selection
- 8 knobs send CC messages, values 0–127 (halfway = 64)
- Knob 1 past halfway (value ≥ 64) → start performer (same as Enter key)
- Knobs 2–8 past halfway → select movement 2–8 respectively
- Highest-numbered knob past halfway takes precedence (e.g. knobs 2 and 3 both up → movement 3)
- No knobs past halfway → movement 1
- Knob state evaluated on every CC message received (not edge-triggered)
- Visual params (dimLevel, litLevel, etc.) are set in config and do not change during performance — knobs not used for these

### Secure Context for Web MIDI
Web MIDI API requires a secure context (HTTPS or localhost). Performer opens `http://localhost` which satisfies this. Display machine does not use MIDI so no secure context required there.

---

## Event Protocol (WebSocket)

Performer sends minimal JSON events to relay; relay broadcasts to all display clients:

```json
{ "type": "activate",   "key": "q" }
{ "type": "deactivate", "key": "q" }
{ "type": "scene",      "sceneIdx": 1 }
{ "type": "movement",   "movementIdx": 0 }
{ "type": "fade",       "action": "in" | "out" }
```

Relay (`relay.py`) is a simple broadcast server — no state, no logic. Any message received is forwarded to all connected clients.

---

## Asset Loading

All assets use relative URLs and load from wherever `perform.html` is served:

```
Performer laptop (server.py)
├── perform.html
├── config.json
├── ceiling1_closeup_21Feb0747.png
├── m1s1_region_id_map.png
├── m1s1_region_meta.json
└── ...etc
```

All scenes within the current movement are loaded when the movement is selected. Switching movements requires network access to performer laptop. Assets are held in memory once loaded.

---

## Editor

`editor.html` — scene editor, runs in browser, saves via HTTP PUT to `server.py`. Used on development machine (currently desktop). Not part of the live performance stack.

---

## Pre-Performance Checklist

1. `git pull` on performer laptop to sync latest code and assets
2. Plug in WiFi router, connect both laptops to it
3. Plug in Oxygen 8 — verify `midisport-firmware` is installed
4. On performer laptop: start `server.py` and `relay.py`
5. Performer opens Chrome: `http://localhost/perform.html?role=performer&ws=ws://localhost:8765`
6. Display opens Chrome: `http://[performer-ip]/perform.html?role=display&ws=ws://[performer-ip]:8765`
7. Verify HUD shows `WS: connected` and `MIDI: Oxygen 8`
8. Test: press Oxygen 8 key → verify regions light on display
9. Disable display laptop screensaver/sleep
10. Set display Chrome to fullscreen (F11), connect projector

---

## Software Stack

| Component | Technology |
|-----------|------------|
| Asset server | Python (`server.py`) |
| WebSocket relay | Python (`relay.py`, `websockets` library) |
| Performer/Display UI | Vanilla HTML/JS/Canvas (`perform.html`) |
| MIDI | Web MIDI API (Chrome, localhost) |
| Region processing | Python (`generate_regions.py`) |
| Scene editing | `editor.html` (browser) |
