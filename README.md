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

Each scene needs a set of region data files generated from an outline image. The outline image is a PNG where **white areas** are selectable regions and **black areas** (thin lines or thick shapes) are boundaries — not selectable.

### Input file

The input to `generate_regions.py` is always a **grayscale PNG** — black outlines on a white background. Black pixels mark boundaries between regions; white pixels are the interiors of regions. The PNG must be the same dimensions as the background photo for that scene.

There are two common ways to produce this PNG:

**Option A — render from an SVG (using Inkscape):**
```bash
inkscape "ceiling1_outline no image.svg" \
  --export-type=png \
  --export-filename=outlines_render.png \
  --export-width=8192 --export-height=6144 \
  --export-background=white
```
Use `--export-background=white` so transparent areas become white (selectable), not black.

**Option B — convert a transparent PNG (e.g. an outline layer exported from Inkscape):**

If the outline layer was exported as a transparent PNG with black lines on a clear background, convert it to white-background first:
```bash
python3 -c "
from PIL import Image
import numpy as np
img = np.array(Image.open('ceiling1_outline_lines_up.png').convert('RGBA'))
# Where alpha is 0 (transparent) → white; where alpha > 0 → black
result = np.ones((img.shape[0], img.shape[1]), dtype=np.uint8) * 255
result[img[:,:,3] > 128] = 0
Image.fromarray(result, 'L').save('outlines_render.png')
"
```

### Running generate_regions.py

```bash
python3 generate_regions.py <input_outline.png> [options]
```

**Parameters:**

| Parameter | Description |
|---|---|
| `input_outline.png` | Path to the outline PNG (required) |
| `--prefix PREFIX` | Prefix for all output filenames, e.g. `hires_` produces `hires_region_id_map.png` etc. Default: none |
| `--outdir DIR` | Directory to write output files. Default: current directory |
| `--min-pixels N` | Minimum region size in pixels. Smaller regions are discarded. Default: 50. For hi-res images (~3x scale), try 150–450. |

**Examples:**
```bash
# Low-res, default output names
python3 generate_regions.py outlines_render.png

# Hi-res with prefix, higher min-pixels threshold
python3 generate_regions.py hires_outlines_render.png --prefix hires_ --min-pixels 150

# Scene 2 with custom prefix
python3 generate_regions.py scene2_outlines_render.png --prefix scene2_
```

### Output files

| File | Description |
|---|---|
| `region_id_map.png` | Lookup map: each pixel encodes the region ID it belongs to. R and G channels encode the ID (up to 65535 regions); B=255 means "region pixel", B=0 means "boundary — not selectable". Used at runtime for hit testing and highlight rendering. |
| `region_meta.json` | JSON object keyed by region ID. Each entry has: `bbox` [xmin, ymin, xmax, ymax], `cx`/`cy` (centroid), `size` (pixel count), `type` ("white" or "black"). Coordinates are in the id map's native pixel space. |
| `region_overlay.png` | Transparent PNG with each region filled in a random color at 50% opacity. Used in the editor to visualize region boundaries. Not used by the performer. |
| `region_children.json` | JSON object mapping parent region IDs to lists of child region IDs. A child is a region whose area is enclosed within a parent. Used by the editor's **C** key ("select children"). |

### Choosing --min-pixels

Too low: noise, thin line artifacts, and outline strokes may be detected as tiny regions.
Too high: small but meaningful regions (fine decorative details) get discarded.

- Low-res (2731×2048): `--min-pixels 50` (default)
- Hi-res (8192×6144, ~3× scale): `--min-pixels 150` to `--min-pixels 450`

Run time increases significantly at hi-res due to image size. Expect 20–40 minutes on a typical machine.

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
| ceiling1.png / ceiling1.jpg | Original low-res photo (2048×1536) |
| ceiling1_upscayl_4x_*.png | Hi-res background photo (8192×6144) |
| outlines_render.png | Rendered outline PNG used to generate low-res region data |
| hires_outlines_render.png | Rendered outline PNG used to generate hi-res region data |
| region_id_map.png | Pixel-to-region ID lookup map (low-res) |
| region_meta.json | Region bounding boxes and centroids (low-res) |
| region_overlay.png | Region color overlay for editor (low-res) |
| region_children.json | Region parent-child relationships (low-res) |
| hires_region_id_map.png | Pixel-to-region ID lookup map (hi-res) |
| hires_region_meta.json | Region bounding boxes and centroids (hi-res) |
| hires_region_overlay.png | Region color overlay for editor (hi-res) |
| hires_region_children.json | Region parent-child relationships (hi-res) |
