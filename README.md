# Malaqatin-Meetings — Live Image Performance Tool

A browser-based tool for designing and performing live projection shows. Regions of a photo are grouped, assigned effects, and triggered via keyboard or MIDI in real time during a musical performance. The image is projected onto a screen.

## Setup

Start the local server:
```
python3 server.py
```
Prints HTTP and WebSocket URLs on startup (both localhost and LAN IP).

Open `editor.html` to design scenes, `perform.html` to perform them. Both can run in separate browser tabs simultaneously.

---

## Two-Machine Performance Setup

The performer and display run as separate roles of the same `perform.html` file, connected via WebSocket.

### Primary — Private WiFi Router

Both machines connect to a WiFi router (brought to venue, needs only a power outlet). Performer laptop runs `server.py` which serves assets and the WebSocket relay.

**Performer laptop** (static IP `192.168.1.10`, opens in Chrome):
```
http://localhost:8082/perform.html?role=performer
```

**Display laptop** (opens in Chrome, projector connected):
```
http://192.168.1.10:8082/perform.html?role=display
```

### Fallback — Cloud Server

If the private router isn't available, both machines connect to a cloud server independently via venue WiFi. The server runs `server.py` behind nginx with HTTPS/WSS and a secret token for access control.

**Server setup** (Ubuntu, nginx, certbot):

1. Install dependencies:
   ```bash
   sudo apt install nginx certbot python3-certbot-nginx
   sudo pip3 install websockets
   ```

2. Create a systemd service at `/etc/systemd/system/malaqatin-meetings.service`:
   ```ini
   [Unit]
   Description=Malaqatin Meetings Server
   After=network.target

   [Service]
   Type=simple
   User=youruser
   WorkingDirectory=/path/to/Malaqatin-Meetings
   ExecStart=/usr/bin/python3 server.py
   Restart=always
   RestartSec=5
   Environment=HTTP_HOST=127.0.0.1
   Environment=WS_HOST=127.0.0.1
   Environment=HTTP_PORT=8082
   Environment=WS_PORT=8765
   Environment=SECRET_TOKEN=your-secret-token-here

   [Install]
   WantedBy=multi-user.target
   ```

3. Create an nginx site at `/etc/nginx/sites-available/your-subdomain`:
   ```nginx
   server {
       server_name your-subdomain.example.com;

       location /ws {
           proxy_pass http://127.0.0.1:8765;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
           proxy_read_timeout 86400;
       }

       location / {
           limit_except GET HEAD OPTIONS {
               deny all;
           }
           proxy_pass http://127.0.0.1:8082;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }

       listen 80;
   }
   ```

4. Enable the site, get an SSL cert, and start the service:
   ```bash
   sudo ln -s /etc/nginx/sites-available/your-subdomain /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d your-subdomain.example.com
   sudo systemctl daemon-reload
   sudo systemctl enable malaqatin-meetings
   sudo systemctl start malaqatin-meetings
   ```

**Performer laptop:**
```
https://your-subdomain.example.com/perform.html?role=performer&token=your-secret-token-here
```

**Display laptop:**
```
https://your-subdomain.example.com/perform.html?role=display&token=your-secret-token-here
```

- All requests without the correct `?token=` are rejected with 403
- PUT requests (editor saves) are blocked from the public internet — manage config files via SSH
- HTTP redirects to HTTPS automatically

### Development (no display machine)

Run with no display — WebSocket connects but nothing is listening on the other end, which is fine:
```
http://localhost:8082/perform.html
```

### Notes
- `server.py` prints the performer laptop's LAN IP on startup — use that IP in the display URL
- The display machine never needs a known/static IP — only the performer's IP matters
- WebSocket URL is derived automatically from the page URL (`ws=` can override if needed)
- HUD is shown by default on `role=performer`, never on `role=display`
- The performer broadcasts full state (active sequences + scene + movement) every 500ms — the display self-corrects any missed messages within that window

### Reducing latency on WiFi

Two settings significantly reduce latency between performer and display:

**1. Disable WiFi power saving on both machines** (resets on reboot):
```bash
sudo iwconfig wlp3s0 power off   # replace wlp3s0 with your interface (check with: ip link)
```
Verify: `iwconfig wlp3s0 | grep Power` should show `Power Management:off`

To make permanent, create `/etc/NetworkManager/conf.d/wifi-powersave-off.conf`:
```ini
[connection]
wifi.powersave = 2
```

**2. Wired connection for the performer laptop** — plugging the performer into the router with ethernet eliminates one WiFi hop.

---

## Editor (`editor.html`)

Design scenes by grouping image regions and assigning keyboard-triggered effect sequences.

### Mouse

| Action | Description |
|---|---|
| Click | Select region |
| Shift+Click | Toggle region in selection |
| Scroll | Zoom |
| Drag | Pan |
| Click group name | Activate group (highlights its regions) and adds it to the multi-selection |
| Shift+click group name | Toggle group in multi-selection |
| Double-click group name | Rename group |

### Keyboard

| Key | Description |
|---|---|
| C | Select children of selected regions (press again to restore previous selection) |
| G | Quick-create group from current selection |
| S | Add active group as next step to active sequence (flashes group name briefly to confirm) |
| Escape | Clear selection |
| Space | Advance to next step (in sequence test mode) |
| ? | Toggle help overlay |

### Workflow

1. Select **Movement** and **Scene** from the dropdowns in the bottom bar
2. Click regions on the canvas to select them
3. Create a **Group** from the selection (name it, then click Create, or press G)
4. Select a group and create a **Sequence** — assign a keyboard key and add steps (group + effect per step)
5. Click **Save** — writes groups and sequences for the current scene to `config.json`

### Groups and Sequences

- A **group** is a named set of regions with a display color
- A **sequence** maps a keyboard key to an ordered list of steps; each step specifies a group and an effect
- During performance, holding a key activates the current step; releasing fades it out; pressing again advances to the next step
- Effects: **solid** (all regions on), **sparkle** (regions randomly flicker on/off), **fade** (same as solid)

---

## Performer (`perform.html`)

Live performance engine. Loads `config.json` and responds to keyboard and MIDI input in real time.

### Keyboard

| Key | Description |
|---|---|
| 1 / 2 / 3 | Load movement — crossfades to new movement, plays audio cue when ready |
| Enter | Fade in from black |
| Escape | Fade to black |
| Left / Right arrow | Crossfade to previous / next scene within the current movement (no wrap) |
| J | Toggle raw image (full brightness, effects suppressed) |
| K | Toggle fullscreen |
| H | Toggle HUD (shown by default on performer; hidden on display) |
| L | Reload config from `config.json` |
| Space | Conductor tap — one tap per quarter-note beat (see Conductor Mode) |
| Backspace | Reset conductor to bar 1 |
| 4 / 5 | Move display image left / right (10px; Shift = 1px) |
| 6 / 7 | Shrink / enlarge display image (10px; Shift = 1px) — scales from top-left |
| 8 | Reset display image to full screen |
| [ | Conductor: back 1 beat (also switches scene if crossing a scene boundary) |
| ] | Conductor: open jump-to-bar dialog (type measure number, Enter to jump, Escape to cancel) |
| *Sequence keys* | Hold to activate effect, release to fade out. Press again (after release) to advance to next step. |

### MIDI (Oxygen 8)

**Linux firmware requirement**: The Oxygen 8 needs firmware uploaded on connect:
```bash
sudo apt install midisport-firmware
```
Then unplug and replug the device. Verify with `midi_test.html`.

| Control | Action |
|---|---|
| Piano keys | Activate/deactivate sequences (mapped via `midiNoteMap` in config) |
| Pitch wheel >75% | Next scene |
| Pitch wheel <25% | Previous scene |
| Knob 8 above halfway | Fade in |
| Knob 8 below halfway | Fade out |
| Knobs 2–7 past halfway | Load movement 2–7 (highest past halfway wins; none past halfway = movement 1) |
| Knob 1 past halfway | Fade in (same as Enter, for initial startup only) |

MIDI is additive — all keyboard bindings still work alongside MIDI.

### Startup knob check

On first load, if MIDI is connected and knobs are configured, the performer is prompted to set all movement knobs (2–7) below halfway and fade knob (8) above halfway before proceeding. The count of unconfirmed knobs is shown. Once all are confirmed the audio ready tone plays and the performer can begin. This check only happens once — subsequent movement switches skip it.

### Held keys across scene changes

If a key (keyboard or MIDI) is held down during a scene crossfade, it is automatically re-activated in the new scene. The performer does not need to re-press it.

### HUD

Shown by default on `role=performer`, never on `role=display`. Toggle with H key. Displays:
- FPS, WebSocket status, MIDI device name, screen wake lock status
- Current movement and scene
- Active sequences with effect, step, and opacity
- Config values (dimLevel, litLevel, etc.)

### Performance workflow

1. Press **1**, **2**, or **3** (or turn knob 2/3) to load a movement. Crossfades from current scene while loading in background.
2. A short audio tone plays when loading is complete (audible to operator, not audience).
3. On first load: set knobs to correct positions when prompted, then press **Enter** or any piano key to fade in.
4. Use **Left/Right** arrows or pitch wheel to crossfade between scenes.
5. Use **Knob 8** to fade in/out between movements.
6. Hold sequence keys or MIDI keys to activate effects; release to fade out.

---

## Conductor Mode

Instead of a pianist triggering regions manually, a tapper taps quarter-note beats on the Space bar. The system reads `score.json` (converted from MusicXML) and fires visual events — region activations, deactivations, and scene changes — at the correct beat positions.

### Setup

1. Run `parse_score.py` to generate `score.json` from the MusicXML EP part:
   ```bash
   python3 parse_score.py
   ```
   Re-run whenever the score changes. The script reads `score and music/Keyboard_1_Modified_v17 16-March-2026 John edits.musicxml` and writes `score.json` to the project root.

2. Load `perform.html` as normal and press **Enter** to fade in.

3. Start tapping **Space** on every quarter-note beat, beginning from bar 1 beat 1.

### How it works

- Each Space tap = one quarter-note beat
- **On the tap**: events at beat position subdiv 0 fire immediately (deactivates) or after ~1 tick (~62ms at 80 BPM, activates) to create a visible retrigger gap
- **Within the beat**: 16th-note subdivision events (subdiv 1–3) are scheduled via `setTimeout` relative to the tap timestamp and cancelled if the next tap arrives early
- **BPM**: estimated from the average of the last 2–3 tap intervals; used only for intra-beat subdivision timing
- **Scene changes**: `scene_next` events in the score trigger automatic crossfades
- **Deactivation**: if the tapper stops, regions deactivate automatically ~1 tick before the next beat would have arrived

### Navigation during rehearsal

| Key | Action |
|---|---|
| Space | Tap (advance one beat) |
| Backspace | Reset to bar 1 |
| [ | Back 1 beat (corrects scene if crossing a scene boundary) |
| ] | Jump to measure — type number, press Enter |

### Pitch-to-key mapping (Movement I, EP part P26)

| Note | Key | Motive |
|---|---|---|
| C3 | q | M1 — tied whole notes |
| D3 | w | M2 — repeating quarters |
| E4 | e | M3 — repeating 8ths |
| F4 | r | M4 — repeating 16ths |
| G4 | e + r | M3 + M4 together (treated as E4 + F4 chord) |
| G3 | a | M5 — slides |
| A3 | s | M6 — rhythmic pattern |
| B4 | d | M7 — tremolo |
| A4 | f | M8/M9 — cello/violin solos |
| C5 | — | scene_next (scene change marker) |

### HUD

In conductor mode the HUD shows an extra line:
```
Conductor: Bar 12 | Beat 3/4 | BPM 81
```
Before the first tap it shows `ready (Space=tap)`. After the last bar it stops.

---

## Configuration (`config.json`)

Single master config file. Edited by hand for structure; groups and sequences are written by the editor UI.

### Global settings

| Setting | Default | Description |
|---|---|---|
| dimLevel | 0.15 | Background image opacity when regions are unlit (0–1) |
| litLevel | 1.00 | Opacity of lit regions (0–1; cannot exceed 1) |
| litBrightness | 1.0 | CSS brightness() multiplier for lit regions (1.0 = unchanged) |
| litSaturate | 1.8 | CSS saturate() multiplier for lit regions (1.0 = unchanged) |
| litContrast | 1.3 | CSS contrast() multiplier for lit regions (1.0 = unchanged) |
| fadeIn | 200 | Default fade-in duration (ms) when a sequence key is pressed |
| fadeOut | 500 | Default fade-out duration (ms) when a sequence key is released |
| sparkleSpeed | 100 | Default sparkle interval (ms) |
| sparkleMinOn | 20 | Min time a region stays lit during sparkle (ms) |
| sparkleMaxOn | 80 | Max time a region stays lit during sparkle (ms) |
| sparkleMinOff | 20 | Min time a region stays dark during sparkle (ms) |
| sparkleMaxOff | 80 | Max time a region stays dark during sparkle (ms) |
| sceneFadeDuration | 1000 | Fade to/from black duration (ms) |
| crossfadeDuration | 1500 | Scene crossfade duration (ms) |
| spotlightDim | 1.0 | Background dim multiplier when any sequence is active (1.0 = no effect, 0.0 = black) |
| spotlightInDelay | 0 | Delay before spotlight starts dimming after first key press (ms) |
| spotlightFadeIn | 300 | Duration of spotlight dim fade-in (ms) |
| spotlightFadeOut | 800 | Duration of spotlight fade back to normal (ms) |
| spotlightDelay | 500 | Delay after all keys released before spotlight fades back (ms) |
| midiNoteMap | {} | Maps keyboard key → MIDI note number (see below) |
| midiKnobCCs | [] | CC numbers for knobs 1–7 in order (find with `midi_test.html`) |
| midiFadeKnobCC | 83 | CC number for fade knob (knob 8 on Oxygen 8) |

### Per-sequence overrides

Any sequence can override these global values. Leave unset (null) to use the global value:

`dimLevel`, `litLevel`, `litBrightness`, `litSaturate`, `litContrast`, `fadeIn`, `fadeOut`, `sparkleSpeed`

Set in the editor UI or directly in `config.json` under a sequence object.

### MIDI note map

Maps keyboard sequence keys and special actions to MIDI note numbers:

```json
"midiNoteMap": {
  "q": 48,
  "w": 50,
  "scene_next": 60,
  "scene_prev": 59
}
```

Special action values: `scene_next`, `scene_prev` — trigger scene crossfade on Note On.

Use `midi_test.html` to find the note numbers for each key on your MIDI controller.

### Structure

```json
{
  "config": { ... },
  "movements": [
    {
      "name": "Movement 1",
      "config": { "dimLevel": 0.10 },
      "scenes": [
        {
          "name": "Scene 1",
          "image": "scene_photo.png",
          "regionIdMap": "m1s1_region_id_map.png",
          "regionMeta": "m1s1_region_meta.json",
          "regionChildren": "m1s1_region_children.json",
          "regionOverlay": "m1s1_region_overlay.png",
          "groups": { },
          "sequences": { }
        }
      ]
    }
  ]
}
```

### Config merging

A movement's `config` block overrides the global `config` where specified. Global values fill everything else. Config is per-movement — there is no per-scene config.

### Division of responsibility

- **Edit by hand in JSON**: movement names, scene names, image and region file paths, MIDI mappings, adding/removing movements or scenes
- **Edit via editor UI**: groups and sequences within a scene

---

## Generating Region Data

Each scene needs region data generated from an outline image. The outline image must be a PNG with **white areas** as selectable regions and **black lines** as boundaries (not selectable).

### Tuning parameters first

Use `segmentation_tuner.html` to interactively preview segmentation parameters before running `generate_regions.py`. Load an outline PNG, adjust parameters, and see the region count and overlay in real time.

### Producing the input PNG

**From an SVG (via Inkscape):**
```bash
inkscape outline.svg \
  --export-filename outlines_render.png \
  --export-width 2007 --export-height 1134 \
  --export-background '#ffffff' --export-background-opacity 1.0
```
The `--export-background` flag ensures transparent areas become white (selectable), not black.

**From a transparent PNG (e.g. an outline layer exported from Inkscape):**
```python
from PIL import Image
img = Image.open('outline_transparent.png').convert('RGBA')
bg = Image.new('RGB', img.size, (255, 255, 255))
bg.paste(img, mask=img.split()[3])
bg.save('outlines_render.png')
```

### Running generate_regions.py

```bash
python3 generate_regions.py <input_outline.png> [options]
```

| Parameter | Description |
|---|---|
| `input_outline.png` | Path to the outline PNG (required) |
| `--prefix PREFIX` | Prefix for all output filenames, e.g. `m1s1_` produces `m1s1_region_id_map.png` etc. Default: none |
| `--outdir DIR` | Directory to write output files. Default: current directory |
| `--min-pixels N` | Minimum region size in pixels. Regions smaller than this are discarded. Default: 50 |

**Example:**
```bash
python3 generate_regions.py outlines_render_m1s1.png --prefix m1s1_ --min-pixels 50
```

Choosing `--min-pixels`: too low causes thin line artifacts and noise to appear as regions; too high discards small but meaningful decorative details. For a ~2000×1100 image, 50 is a reasonable starting point.

### Output files

Four files are produced (with the given prefix applied to each name):

**`region_id_map.png`**

A PNG the same dimensions as the input. Each pixel encodes which region it belongs to:
- R channel = low byte of region ID
- G channel = high byte of region ID
- B channel = 255 for region pixels, 0 for boundary pixels (boundaries are pure black: 0,0,0)

Region IDs are 0-indexed integers. White regions are assigned IDs 0…N-1; black regions follow with IDs N…N+M-1. Up to 65535 regions are supported. Used at runtime for hit testing (which region did the user click?) and highlight rendering.

**`region_meta.json`**

JSON object keyed by region ID (as a string). Each entry contains:
- `bbox`: [xmin, ymin, xmax, ymax] — bounding box in id map pixel coordinates
- `cx`, `cy`: centroid in id map pixel coordinates
- `size`: pixel count
- `type`: `"white"` or `"black"`
- `idx`: integer ID (same as the key parsed as int)

Coordinates are in the id map's native pixel space. The editor and performer scale them to logical image coordinates at load time using the ratio of image dimensions to id map dimensions.

**`region_overlay.png`**

Transparent RGBA PNG with each region filled in a distinct color at 50% opacity (alpha=128). Colors are deterministic — the same input always produces the same colors (RNG seeded with 42). Used in the editor to visualize region boundaries. Not used by the performer.

**`region_children.json`**

JSON object mapping parent region IDs (strings) to lists of child region IDs (integers). A region is only considered a potential parent if it is ≥ 5000 pixels. Children are detected using two methods combined:
1. **Flood-fill containment**: treat parent pixels as walls; any region whose centroid is enclosed is a child
2. **Bounding-box containment**: child bbox fully inside parent bbox (with 10px margin) and child is less than half the parent's size

Used by the editor's **C** key to select all children of a selected region.

### Requirements

- Python 3 with `numpy`, `Pillow`, `scipy`
- Inkscape (for SVG rendering only)

---

## Files

| File | Description |
|---|---|
| `editor.html` | Scene editor |
| `perform.html` | Live performer (supports `role=performer\|display` and `token=` URL params; WebSocket URL derived automatically from page host) |
| `server.py` | Combined HTTP server (port 8082) and WebSocket relay (port 8765). Ports and bind address configurable via env vars; supports `SECRET_TOKEN` for token-gated access. |
| `segmentation_tuner.html` | Interactive UI for tuning region segmentation parameters |
| `midi_test.html` | MIDI monitor — shows all input from connected MIDI devices |
| `architecture.md` | System architecture and networking plan |
| `motives and key mappings.md` | Human-readable table of motives, keyboard keys, MIDI keys, and patterns |
| `generate_regions.py` | Region data generator |
| `config.json` | Master config: global settings, movements, scenes, groups, sequences |
| `parse_score.py` | Converts MusicXML EP part to `score.json` for conductor mode. Run after any score change. |
| `score.json` | Generated score data consumed by conductor mode. Do not edit by hand — re-run `parse_score.py`. |
| `ceiling1_closeup_21Feb0747.png` | Photo — Movement 1, Scene 1 |
| `ceiling1_medium_up.png` | Photo — Movement 1, Scene 2 |
| `ceiling_zoomOut.png` | Photo — Movement 1, Scene 3 |
| `ceiling_9by16.png` | Photo — Movement 1, Scene 4 |
| `m1s1_region_id_map.png` | Region ID map — M1 Scene 1 |
| `m1s1_region_meta.json` | Region metadata — M1 Scene 1 |
| `m1s1_region_overlay.png` | Region overlay — M1 Scene 1 |
| `m1s1_region_children.json` | Region children — M1 Scene 1 |
| `m1s2_region_id_map.png` | Region ID map — M1 Scene 2 |
| `m1s2_region_meta.json` | Region metadata — M1 Scene 2 |
| `m1s2_region_overlay.png` | Region overlay — M1 Scene 2 |
| `m1s2_region_children.json` | Region children — M1 Scene 2 |
| `m1s3_region_id_map.png` | Region ID map — M1 Scene 3 |
| `m1s3_region_meta.json` | Region metadata — M1 Scene 3 |
| `m1s3_region_overlay.png` | Region overlay — M1 Scene 3 |
| `m1s3_region_children.json` | Region children — M1 Scene 3 |
| `m1s4_region_id_map.png` | Region ID map — M1 Scene 4 |
| `m1s4_region_meta.json` | Region metadata — M1 Scene 4 |
| `m1s4_region_overlay.png` | Region overlay — M1 Scene 4 |
| `m1s4_region_children.json` | Region children — M1 Scene 4 |
| `ceiling1_closeup_with_contours.svg` | Inkscape SVG — outline for M1S1 |
| `ceiling1_outline.svg` | Inkscape SVG — outline for M1S2 |
| `outlines_render_m1s1.png` | Rendered outline PNG used to generate M1S1 region data |
