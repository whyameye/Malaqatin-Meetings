# Susan — Redesign Plan (20 Feb 2026)

## Overview

Redesign the scene/movement structure of the Susan ceiling lighting performance tool to match the musical structure of the work being performed.

---

## Musical / Structural Concept

The performance corresponds to a musical work with **3 movements**. Each movement contains up to **5 scenes**. This maps directly to the software structure:

- **Movement** (previously called "parent scene") — corresponds to a musical movement
  - Selected with keys **1 / 2 / 3**
  - Transition between movements: **fade to black**
  - Always starts on scene 1 of the new movement
- **Scene** (previously called "child scene") — a specific view/photo/region setup within a movement
  - Navigate with **Left / Right arrow keys**
  - Transition between scenes: **crossfade**
  - Does not wrap — stops at first/last scene
  - Each scene has its own: image, region data, groups, sequences

Scenes are independent of each other. Groups and sequences do not carry across scene or movement boundaries. Transitions happen when things are musically quiet.

---

## Navigation (Performer)

| Key | Action |
|---|---|
| 1 / 2 / 3 | Switch movement → fade to black → load all scenes for that movement → audio cue when ready → Enter to fade in |
| Right arrow | Crossfade to next scene in movement (stop at last) |
| Left arrow | Crossfade to previous scene in movement (stop at first) |
| Escape | Fade to black (manual, any time) |
| Enter | Fade in from black |
| Space | Toggle raw image (full brightness) |
| F | Toggle fullscreen |
| H | Toggle HUD |
| R | Reload config |
| *Sequence keys* | Hold to activate effect, release to fade out |

**Zoom presets are removed.**

---

## Loading Strategy

- When a movement is selected (1/2/3): fade to black, then load ALL scenes for that movement simultaneously
- Play a **short audio tone** when loading is complete (feedback for operator, inaudible to audience over music)
- Operator presses **Enter** to fade in when ready
- When switching movements: dump current movement's data, load new movement's data
- This ensures all crossfades within a movement are lag-free once loaded
- Loading at 1920×1080 should complete in well under 5 seconds

---

## Config File

Single master config file: **`config.json`**

Replaces: `perform_config.json`, `scene1.json`, `scene2.json`, `scene3.json`

### Structure

```json
{
  "config": {
    "dimLevel": 0.15,
    "litLevel": 1.00,
    "defaultFadeIn": 200,
    "defaultFadeOut": 500,
    "sparkleMinOn": 20,
    "sparkleMaxOn": 80,
    "sparkleMinOff": 20,
    "sparkleMaxOff": 80,
    "litSaturate": 1.8,
    "litContrast": 1.3,
    "sceneFadeDuration": 1000,
    "crossfadeDuration": 1500
  },
  "movements": [
    {
      "name": "Movement 1",
      "config": {
        "dimLevel": 0.10,
        "litSaturate": 2.0
      },
      "scenes": [
        {
          "name": "Opening",
          "image": "m1_scene1.png",
          "regionIdMap": "m1_scene1_region_id_map.png",
          "regionMeta": "m1_scene1_region_meta.json",
          "regionChildren": "m1_scene1_region_children.json",
          "groups": { },
          "sequences": { }
        }
      ]
    },
    {
      "name": "Movement 2",
      "config": { },
      "scenes": [ ]
    },
    {
      "name": "Movement 3",
      "config": { },
      "scenes": [ ]
    }
  ]
}
```

### Config merging

Movement `config` overrides global `config` where specified. Global fills the rest. Config is NOT per-scene — per-movement is the finest granularity.

### What is NOT in the config file (edited by hand in JSON)

- Movement names
- Scene names
- Image and region file paths
- Adding/removing movements or scenes

### What IS edited via the editor UI

- Groups (which regions belong together)
- Sequences (key bindings and effects for groups)

---

## Editor Changes

### UI Changes

- Replace current **1 / 2 / 3 scene selector** buttons with:
  - **Movement dropdown** — selects the movement
  - **Scene dropdown** — populated from scenes in the selected movement
- Loading a scene loads the correct image and region data from config
- **Remove zoom preset UI**

### Save Behaviour

- Save reads the current `config.json`
- Updates only the `groups` and `sequences` for the currently selected movement/scene
- Writes the full file back

### Division of Responsibility

- **JSON editing**: structure (movements, scenes, file paths, adding/removing scenes)
- **Editor UI**: groups and sequences within an existing scene

---

## Performer Changes

- Load `config.json` instead of `perform_config.json` + scene JSON files
- Implement movement loading (all scenes for a movement loaded at once)
- Implement crossfade between scenes (Left/Right arrows)
- Implement audio cue on load complete (Web Audio API, short tone)
- Merge movement config over global config at runtime
- Remove zoom preset system entirely
- 1/2/3 keys select movements, not scenes

---

## Image Resolution

- Target image resolution: **1920×1080** (sufficient for projected ceiling performance)
- Maximum: **3840×2160** if more detail needed
- Previous hi-res work used 8192×6144 — this is larger than needed and slow to process

---

## Region Data (per scene)

Each scene references its own set of region files:
- `region_id_map.png` — pixel-to-region lookup
- `region_meta.json` — bounding boxes, centroids, sizes
- `region_children.json` — parent-child relationships

Generated using `generate_regions.py` from a white-background outline PNG. See README for full documentation.

**Black lines/boundaries are NOT selectable regions.** Only white areas between outlines are selectable.

---

## Outstanding / Deferred Issues

- **Alignment between photo and outlines**: the SVG-derived outlines don't perfectly align with the photo at hi-res. Deferred — not blocking current work.
- **New outlines**: user has `ceiling1_outline_lines_up` (black lines on transparent, 2731×2048, from Inkscape vectors) which aligns correctly with the photo. When ready, export from Inkscape at target resolution, convert to white-background PNG, run through `generate_regions.py`.
- **Scene image filenames**: not yet determined for movements 2 and 3.
