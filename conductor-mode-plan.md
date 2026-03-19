# Conductor Mode — Implementation Plan

## Overview

Instead of a pianist playing the composed electric piano part live, a "tapper" taps quarter note beats on a single key. A script pre-loaded with the composed score fires the correct visual events (motive activations, scene changes) at the right subdivisions, using the tap stream to track tempo and phase in real time.

The tapper replaces the pianist entirely. Their only job is to tap steady quarter note beats.

---

## How It Works

### Tap Input
- A single designated key (keyboard or MIDI note) is the tap input
- Each tap = one quarter note beat
- The tapper taps throughout the entire performance

### Tempo Tracking
- Default BPM at startup: **80** (or whatever the movement's opening tempo is)
- On each tap, recalculate BPM using the average of the **last 2–3 tap intervals**:
  ```
  BPM = 60000 / average(last 2 or 3 intervals in ms)
  ```
- 2–3 intervals balances responsiveness against single-tap jitter
- No sanity checks — the tapper may intentionally vary tempo

### Phase Correction
- Each tap is treated as the ground truth for **where the beat is right now**
- On every tap, all pending future events are **rescheduled** relative to that tap
- This makes phase drift structurally impossible — the tapper's timing is always the anchor
- Events already fired are left alone
- Events scheduled within the next ~20ms are left alone to avoid jitter

### Subdivision Placement
- The script uses the current BPM estimate to place subdivisions between taps
- At 80 BPM: quarter = 750ms, eighth = 375ms, 16th = 187.5ms
- Subdivision events are fired via `setTimeout` relative to the last tap
- On the next tap they are rescheduled if needed

---

## Score Data Format

A one-time Python script (`parse_score.py`) converts the MusicXML files to a clean JSON timeline that the browser consumes directly. The browser never touches MusicXML.

### `score.json` structure

```json
{
  "movements": [
    {
      "name": "Movement I",
      "defaultBPM": 80,
      "bars": [
        {
          "bar": 1,
          "beats": 4,
          "events": []
        },
        {
          "bar": 4,
          "beats": 4,
          "events": [
            { "beat": 1, "subdiv": 0, "action": "scene_next" },
            { "beat": 1, "subdiv": 0, "action": "activate", "key": "w" }
          ]
        }
      ]
    }
  ]
}
```

- `beat`: 1-indexed quarter note beat within the bar (1–4 for 4/4, 1–2 for 2/4)
- `subdiv`: 0-indexed 16th note offset within the beat (0=on the beat, 1=e, 2=and, 3=a)
- `action`: `activate`, `deactivate`, `scene_next`, `scene_prev`
- `key`: which visual sequence key to trigger (q, w, e, r, a, s...)
- 2/4 bars have `"beats": 2` — the script skips waiting for beats 3 and 4

### Motive-to-key mapping
The MusicXML score already has motive labels (M1–M7) as text directions on every bar. The conversion script uses a mapping table (defined by the composer) to translate motive labels to visual keys:

```python
MOTIVE_MAP = {
    "M1": "q",
    "M2": "w",
    "M3": "e",
    "M4": "r",
    "M5": "a",
    "M6": "s",
    # M7 = scene change marker, not a visual key
}
```

`P↑` markers in the score become `scene_next` events.

---

## Score Parsing Script (`parse_score.py`)

One-time offline conversion. Handles:
- Reading MusicXML electric piano part
- Extracting `P↑` markers as `scene_next` events
- Extracting motive text directions (M1–M7) and mapping to visual keys
- Converting note positions to bar/beat/subdiv
- Handling 2/4 bars
- Outputting `score.json`

The script is run once when the score is finalised (or re-run if the score changes). The output `score.json` is committed to the repo.

---

## Conductor Mode in `perform.html`

Activated via URL param: `?mode=conductor`

### State variables needed
```js
let tapTimes = [];           // timestamps of last 3 taps
let currentBPM = 80;         // current tempo estimate
let lastTapTime = null;      // timestamp of most recent tap
let currentBar = 0;          // which bar we are in
let currentBeat = 0;         // which beat within the bar
let pendingTimeouts = [];    // scheduled future events (cancellable)
let scoreData = null;        // loaded from score.json
let conductorActive = false; // true once first tap received
```

### On each tap
1. Record tap timestamp
2. Update `tapTimes` array (keep last 3)
3. Recalculate BPM from average of last 2–3 intervals
4. Advance beat counter (beat → beat+1, wrapping at bar boundary)
5. Cancel all pending timeouts
6. Reschedule future events in current bar + next bar relative to this tap
7. Update HUD

### Beat counting
- The tapper taps every quarter note
- The script tracks which beat of which bar each tap corresponds to
- The tapper must start tapping on beat 1 of bar 1
- If the tapper misses a beat or double-taps, beat counting will drift — see Recovery below

### Event firing
```
for each event in current and upcoming bars:
    offset_ms = (beat - currentBeat) * (60000 / BPM)
              + (subdiv / 4) * (60000 / BPM)
    setTimeout(() => fireEvent(event), offset_ms)
```

### Recovery from beat counting errors
- A dedicated **reset key** lets the tapper signal "I am on beat 1 of bar N"
- Or: the tapper taps a different key to manually set the current bar number
- The HUD shows current bar and beat prominently so the tapper can spot drift

---

## HUD in Conductor Mode

Large, clear display showing:
- Current bar number and beat (e.g. **Bar 12 | Beat 3**)
- Current BPM estimate
- Next event coming up (e.g. "→ activate W in 0.3s")
- A visual pulse on every beat (flashes on tap)

The HUD is the tapper's primary feedback — they need to confirm the script is tracking their position correctly.

---

## Score Structure per Movement

### Movement I (86 bars)
- 4/4 throughout except bar 26 (2/4)
- Tempo: 80 BPM, slight rallentando near end (bar 85: ~71 BPM)
- Scene changes (P↑): bars 4, 10, 11
- 4 scenes, 3 scene_next events
- Motives active: M1–M7

### Movement II (103 bars)
- 4/4 with 2/4 at bars 29 and 93
- Tempo: 80 BPM, slows to 60 at bars 79–80, back to 80 at bar 81, slows again at end
- Score not yet written for electric piano

### Movement III (99 bars)
- Pure 4/4, no time signature changes
- Tempo: 100 BPM throughout (fastest movement)
- Score not yet written for electric piano

---

## Timing Sensitivity

Some events are more sensitive to drift than others:

**Low sensitivity** — dense 16th-note trill sections (M3/M4, Pattern A). Audience perceives these as texture, not individual hits. Small drift is imperceptible.

**High sensitivity** — sparse syncopated hits (Pattern D, bars 46–53 / 65–72). Isolated F4 16th notes land at off-beat positions (beat 1.5, 4.75, etc.). A miss here is noticeable. These are the moments the tapper needs to be most steady.

**Scene changes** — bars 4, 10, 11. These are structural and visible. Ideally happen at the right bar even if slightly off the beat.

---

## What Still Needs to Be Done

1. **Compose electric piano parts for Movements II and III** — the MusicXML is structural only, no keyboard part yet
2. **Define motive-to-key mapping** for Movements II and III (may differ from Movement I)
3. **Write `parse_score.py`** — MusicXML → `score.json` converter
4. **Implement conductor mode in `perform.html`** — tap input, tempo tracker, event scheduler, HUD
5. **Add `score.json`** to the repo once scores are finalised
6. **Test with a real tapper** — verify phase correction and BPM smoothing feel right in practice

---

## Open Questions

- Should the tapper tap every quarter note, or every half note? (Quarter is more precise but more work; half note is easier but halves subdivision resolution)
- Should conductor mode be a separate HTML file or a mode within `perform.html`?
- Does the tapper need a metronome click in their earpiece, or is tapping to the live ensemble enough?
- For the rallentando sections (Mvt I bar 85, Mvt II bars 79–80) — does the tapper follow the live ensemble naturally, or does the script need to know about these tempo changes in advance?
