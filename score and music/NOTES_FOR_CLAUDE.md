# Notes for Claude — Mvt II EP Generator Session

## Script
`generate_mvt2_ep.py` — reads the Movement II MusicXML, detects motives, writes
annotated score (`...John.musicxml`) and `movement2_motives.csv`.

Always run with `/usr/bin/python3 generate_mvt2_ep.py`.

---

## Critical Bug Fixed This Session
**MusicXML can have multiple `<notations>` elements on a single note.**
`child.find('notations')` only finds the first. The slur on P19 m14 was in a
*second* `<notations>` block and was being silently missed.
Fix: use `child.findall('notations')` and iterate all of them. Already implemented.

---

## Motive Rules Summary

### M1 (C3) — half notes
2+ consecutive half notes, no rest between. Slur-tied same-pitch notes across
barlines are skipped (not counted as separate halves).

### M2 (D3) — 16th pair pickup
Two consecutive 16th notes (different pitches) followed by a non-16th note.
If 3+ 16ths in a row, triggers on the **last pair** only.
- Suppressed during all solo sections (M7 m34-42, M8 m44-52, M9 m54-69)
- Suppressed if that instrument is already triggering another motive at that tick
- Per-part exclusions: P20 m16, P18 m95
- **Still imperfect** — user acknowledged and said to move on. Known issues:
  - m19 fires (expected m20), m71 fires (expected m72) — off by 1 measure
  - m90 extends to m100 (user expected m90-94) — from multiple instruments
  - m15 end shown as "m17 b0.0" in CSV = end of m16 (correct but confusing display)

### M3 (E4) — pizz chords
8th or 16th notes that have simultaneous chord notes from the same instrument.
Special rules:
- Violin I (P21) every note in m30–41 triggers M3
- Violin II (P22) every note in m52–69 triggers M3

### M4 (F4) — slurred 16th runs
5+ consecutive 16th notes with at least one slur marking. Hold to rest after run.
- P1/P2/P4/P5 (Fl.1, Fl.2, Cl.1, Cl.2) **excluded entirely** — their runs are M6
- Manual event: (1112, 1176) = Solo Vln m71–74 (slur not in XML for this section)
- `seq` filter keeps `tie_stop` notes that also have `slur_start` (slur can start
  on a tied note — otherwise the slur_start gets filtered out)

### M5 (G3) — slide gesture
Two cases:
- **Case A**: 8th note with slur_start, pitch changes, next note holds >2 ticks
- **Case B**: Step down 1–2 semitones after a rest, not 16th, next note holds >2 ticks
  (bass/inner voices P6/P23/P24/P25 excluded from Case B)

Both: measure ≥ 12. Per-part exclusions: P19 (SoloVln) never triggers M5;
P18 m88–92 excluded.

Manual events:
- (352, 448) = Bsn m23–29
- (1176, 1272) = Bsn m75–81

### M6 (A3) — repeated/alternating 16ths or tremolo
Tremolo notes always trigger M6. Slurred 16th runs trigger if they use:
- Exactly 1 pitch (≥2 notes), OR
- Exactly 2 pitches strictly alternating (≥3 notes, no consecutive same pitch)

This restriction prevents S.Sax/SoloVln melodic runs from false-triggering.

Manual event:
- (648, 808) = m42–51 (Fl/Cl arpeggio runs have 4–5 pitches, don't pass 2-pitch rule)

---

## Part IDs (key ones)
| PID | Instrument |
|-----|-----------|
| P1  | Flute 1 |
| P2  | Flute 2 |
| P4  | Clarinet 1 |
| P5  | Clarinet 2 |
| P6  | Bass (inner voice — exclude from M5 step-down) |
| P18 | Solo Soprano Saxophone |
| P19 | Solo Violin |
| P20 | Solo Violoncello |
| P21 | Violin I |
| P22 | Violin II |
| P23 | Viola (inner voice — exclude from M5 step-down) |
| P24 | Violoncello (inner voice — exclude from M5 step-down) |
| P25 | Double Bass (inner voice — exclude from M5 step-down) |
| P26 | Electric Piano (EP) — output part |

---

## Architecture Notes
- `COMMON_DIV = 4` ticks per quarter note
- 4/4 time throughout = 16 ticks per measure
- Measure ticks: m1=0, m10=144, m19=288, m26=400, m42=648, m52=808,
  m71=1112, m75=1176, m78=1224, m92=1448, m98=1536
- `deduplicate()` merges overlapping events of same motive
- Detectors return 4-tuples `(start, end, motive, pid)` — `None` pid for manual events
- M3/M4/M5/M6 run first; their raw events build `part_busy` dict used by M2
- CSV has columns: measure_start, beat_start, measure_end, beat_end, motive, instruments
- EP part uses 6 voices: M3(1), M4(2) on staff 1; M1(3), M2(4), M5(5), M6(6) on staff 2
- Stems: odd voices up, even voices down
- Beaming: consecutive 8th/16th notes within same beat grouped
