# Malaqatin-Meetings — Live Image Performance Tool

A browser-based tool for designing and performing live projection shows. Regions of a photo are grouped, assigned effects, and triggered via keyboard in real time during a musical performance. The image is projected onto a screen.

## Setup

Start the local server:
```
python3 server.py
```
Serves on http://localhost:8080

Open `editor.html` to design scenes, `perform.html` to perform them. Both can run in separate browser tabs simultaneously.

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
| Click group name | Activate group (highlights its regions) |
| Shift+click group name | Multi-select groups |
| Double-click group name | Rename group |

### Keyboard

| Key | Description |
|---|---|
| C | Select children of selected regions (press again to restore previous selection) |
| G | Quick-create group from current selection |
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

Live performance engine. Loads `config.json` and responds to keyboard input in real time.

### Keyboard

| Key | Description |
|---|---|
| 1 / 2 / 3 | Load movement — fades to black, loads all scenes for that movement, plays audio cue when ready |
| Enter | Fade in from black |
| Escape | Fade to black |
| Left / Right arrow | Crossfade to previous / next scene within the current movement (no wrap) |
| Space | Toggle raw image (full brightness, effects suppressed) |
| F | Toggle fullscreen |
| H | Toggle HUD (FPS, config values, active sequences) |
| R | Reload config from `config.json` |
| *Sequence keys* | Hold to activate effect, release to fade out. Press again (after release) to advance to next step. |

### Performance workflow

1. Press **1**, **2**, or **3** to load a movement. The display fades to black while all scenes load.
2. A short audio tone plays when loading is complete (audible to operator, not audience).
3. Press **Enter** to fade in when ready.
4. Use **Left/Right** arrows to crossfade between scenes within the movement.
5. Hold sequence keys to activate effects on groups; release to fade out.
6. Press **Escape** to fade to black at any time (e.g. between movements).

---

## Configuration (`config.json`)

Single master config file. Edited by hand for structure; groups and sequences are written by the editor UI.

### Global settings

| Setting | Default | Description |
|---|---|---|
| dimLevel | 0.15 | Background image opacity when regions are unlit |
| litLevel | 1.00 | Opacity of lit regions |
| defaultFadeIn | 200 | Fade-in duration (ms) when a sequence key is pressed |
| defaultFadeOut | 500 | Fade-out duration (ms) when a sequence key is released |
| sparkleMinOn | 20 | Min time a region stays lit during sparkle (ms) |
| sparkleMaxOn | 80 | Max time a region stays lit during sparkle (ms) |
| sparkleMinOff | 20 | Min time a region stays dark during sparkle (ms) |
| sparkleMaxOff | 80 | Max time a region stays dark during sparkle (ms) |
| litSaturate | 1.8 | Color saturation multiplier for lit regions (1.0 = unchanged) |
| litContrast | 1.3 | Contrast multiplier for lit regions (1.0 = unchanged) |
| sceneFadeDuration | 1000 | Fade to/from black duration (ms) |
| crossfadeDuration | 1500 | Scene crossfade duration (ms) |

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

- **Edit by hand in JSON**: movement names, scene names, image and region file paths, adding/removing movements or scenes
- **Edit via editor UI**: groups and sequences within a scene

---

## Generating Region Data

Each scene needs region data generated from an outline image. The outline image must be a PNG with **white areas** as selectable regions and **black lines** as boundaries (not selectable).

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
| `perform.html` | Live performer |
| `server.py` | HTTP server with PUT support for saving `config.json` |
| `generate_regions.py` | Region data generator |
| `config.json` | Master config: global settings, movements, scenes, groups, sequences |
| `plan-20-Feb-2026.md` | Design plan for the movement/scene architecture |
| `ceiling1_closeup_21Feb0747.png` | Photo — Movement 1, Scene 1 |
| `ceiling_20Feb1811.png` | Photo — Movement 1, Scene 2 |
| `m1s1_region_id_map.png` | Region ID map — Movement 1, Scene 1 |
| `m1s1_region_meta.json` | Region metadata — Movement 1, Scene 1 |
| `m1s1_region_overlay.png` | Region overlay — Movement 1, Scene 1 |
| `m1s1_region_children.json` | Region children — Movement 1, Scene 1 |
| `m1s2_region_id_map.png` | Region ID map — Movement 1, Scene 2 |
| `m1s2_region_meta.json` | Region metadata — Movement 1, Scene 2 |
| `m1s2_region_overlay.png` | Region overlay — Movement 1, Scene 2 |
| `m1s2_region_children.json` | Region children — Movement 1, Scene 2 |
| `ceiling1_closeup_with_contours.svg` | Inkscape SVG — outline for M1S1 |
| `ceiling1_outline.svg` | Inkscape SVG — outline for M1S2 |
| `outlines_render_m1s1.png` | Rendered outline PNG used to generate M1S1 region data |
