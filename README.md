# Susan — Ceiling Lighting Performance Tool

A browser-based tool for designing and performing live ceiling lighting shows. Regions of a ceiling image can be grouped, sequenced with effects, and triggered via keyboard in real time.

## Setup

Start the local server:
```
python3 server.py
```
Serves on http://localhost:8080

Open `editor.html` to design scenes, `perform.html` to perform them. Both can run in separate browser tabs simultaneously.

## Editor (`editor.html`)

Design scenes by grouping ceiling regions, assigning effects, and setting up keyboard-triggered sequences.

### Mouse
| Action | Description |
|---|---|
| Click | Select region |
| Shift+Click | Toggle region in selection |
| Scroll | Zoom |
| Drag | Pan |
| Click group name | Select/deselect group |
| Double-click group name | Rename group |

### Keyboard
| Key | Description |
|---|---|
| C | Select children of selected regions |
| G | Quick-create group from selection |
| Escape | Clear selection |
| Space | Advance to next step (sequence test mode) |
| ? | Toggle help overlay |

### UI Controls
- **Scene selector** (1/2/3) — choose which scene file to edit
- **Save / Load** — save/load scene JSON via server
- **Save Current View** — save the current zoom/pan as a zoom preset

## Performer (`perform.html`)

Live performance engine. Loads scene JSON and responds to keyboard input in real time.

### Keyboard
| Key | Description |
|---|---|
| Space | Toggle raw image (full brightness, no effects) |
| Escape | Fade to black |
| Enter | Fade in from black |
| 1 / 2 / 3 | Switch scene (works anytime, including while black) |
| F | Toggle fullscreen |
| H | Toggle HUD (shows FPS, config values, active keys, hi-res status) |
| R | Reload config from `perform_config.json` |
| *Sequence keys* | Hold to activate group effect, release to fade out. Press again to advance to next step. |
| *Zoom keys* | Tween to zoom preset. Press again to cycle through presets on same key. |

### Performance workflow
1. Press **Space** to show the full image to the audience
2. Press **Escape** to fade to black
3. Use **1/2/3** to switch scenes while black
4. Press **Enter** to fade in (dimmed, ready for effects)
5. Hold sequence keys to light up groups
6. Use zoom keys to focus on areas of interest

## Configuration (`perform_config.json`)

| Setting | Default | Description |
|---|---|---|
| dimLevel | 0.15 | Background image opacity (unlit areas) |
| litLevel | 1.00 | Lit region target opacity |
| defaultFadeIn | 200 | Fade-in duration (ms) when key pressed |
| defaultFadeOut | 500 | Fade-out duration (ms) when key released |
| sparkleMinOn | 20 | Min time a region stays lit during sparkle (ms) |
| sparkleMaxOn | 80 | Max time a region stays lit during sparkle (ms) |
| sparkleMinOff | 20 | Min time a region stays dark during sparkle (ms) |
| sparkleMaxOff | 80 | Max time a region stays dark during sparkle (ms) |
| litSaturate | 1.8 | Color saturation boost for lit regions (1.0 = normal) |
| litContrast | 1.3 | Contrast boost for lit regions (1.0 = normal) |
| tweenDuration | 500 | Zoom tween duration (ms) |
| sceneFadeDuration | 1000 | Fade to/from black duration (ms) |
| sceneImages | {} | Per-scene image overrides (see below) |

### Scene images
Each scene can use a different background image. Configure in `sceneImages`:
```json
"sceneImages": {
  "1": { "image": "ceiling1a.png", "hiresImage": "ceiling1_upscayl_4x.png" },
  "2": { "image": "ceiling2.png", "hiresImage": "" },
  "3": { "image": "ceiling3.png", "hiresImage": "" }
}
```
If left empty, falls back to the image specified in the scene JSON.

## Generating Region Data

Each scene needs a set of region data files (id map, metadata, overlay, children). These are generated from an SVG outline file in two steps.

### Step 1: Render SVG to PNG

Use Inkscape to rasterize the SVG outline at the target image dimensions:
```bash
inkscape "ceiling1_outline no image.svg" \
  --export-type=png \
  --export-filename=outlines_render.png \
  --export-width=2731 --export-height=2048 \
  --export-background=white
```

The SVG should contain black filled shapes and/or black strokes on a white background. The result is a grayscale PNG where white areas become "white" regions and black areas become "black" regions.

### Step 2: Generate region files

```bash
python3 generate_regions.py outlines_render.png
```

This produces `region_id_map.png`, `region_meta.json`, `region_overlay.png`, and `region_children.json` in the current directory.

For additional scenes, use the `--prefix` flag:
```bash
python3 generate_regions.py outlines_render_scene2.png --prefix scene2_
```

### Requirements

- Python 3 with numpy, Pillow, scipy
- Inkscape (for SVG rendering)

## Files

| File | Description |
|---|---|
| editor.html | Scene editor |
| perform.html | Live performer |
| server.py | HTTP server with PUT support for saving |
| generate_regions.py | Region data file generator (from rendered SVG outline) |
| perform_config.json | Performance tuning parameters |
| scene1.json / scene2.json / scene3.json | Scene data (groups, sequences, zoom presets) |
| ceiling1a.png | Background image (2731x2048) |
| ceiling1_upscayl_4x_*.png | Hi-res background (8192x6144), loaded async |
| region_id_map.png | Pixel-to-region ID lookup map |
| region_meta.json | Region bounding boxes and centroids |
| region_overlay.png | Region boundary overlay for editor |
| region_children.json | Region parent-child relationships |
