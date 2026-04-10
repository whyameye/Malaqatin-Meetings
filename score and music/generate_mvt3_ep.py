#!/usr/bin/env python3
"""
Movement III EP motive generator.
Reads the Movement III MusicXML, writes motive blocks to CSV,
annotated EP part to output MusicXML, and conductor events to score.json.

Each motive block is either:
  sustained  – one activate at block start, one deactivate at block end
  retrigger  – short pulse (activate beat 1, deactivate beat 1+) on every bar in block

RETRIGGER_MOTIVES controls which motives retrigger.
RETRIGGER_END_BAR controls a per-bar hybrid: bars before RETRIGGER_END_BAR retrigger,
bars from RETRIGGER_END_BAR onward sustain.  Set to None for all-retrigger.
"""

import csv
import json
import pathlib
import xml.etree.ElementTree as ET

SCRIPT_DIR = pathlib.Path(__file__).parent
INPUT   = str(SCRIPT_DIR / 'Edited 3 Malaqatin Meetings - Full score - 01 Movement III Final.musicxml')
OUTPUT  = str(SCRIPT_DIR / 'Edited 3 Malaqatin Meetings - Full score - 01 Movement III Final - John.musicxml')
CSV_OUT = str(SCRIPT_DIR / 'movement3_motives.csv')
SCORE_JSON = str(SCRIPT_DIR.parent / 'score.json')

# ── Motive blocks (measure ranges, inclusive, score-derived) ─────────────────
BLOCKS = {
    'M1':  [(1,17),(24,25),(64,74),(92,96)],
    'M2':  [(5,17),(56,57),(64,69),(92,96)],
    'M3':  [(7,10),(58,59),(64,65),(92,96)],
    'M4':  [(11,17),(22,30),(34,35),(66,68)],
    'M5':  [(12,14),(16,17),(20,23),(25,25),(31,35),(67,69),(71,74),(76,76)],
    'M6':  [(15,17),(20,21),(24,24),(26,35),(44,47),(52,55),(70,73),(75,75),(80,83),(88,96)],
    'M7':  [(18,25),(44,99)],
    'M8':  [(48,51),(56,59),(85,96)],
    'M9':  [(31,43)],
    'M10': [(36,44),(88,96)],
    'M11': [(44,60),(88,96)],
    'M12': [(80,96)],
}

# Conductor key for each motive
MOTIVE_KEY = {
    'M1': 'q', 'M2': 'w', 'M3': 'e', 'M4': 'r',
    'M5': 'a', 'M6': 's', 'M7': 'd', 'M8': 'f',
    'M9': 'g', 'M10': 'y', 'M11': 'u', 'M12': 'i',
}

# ── Retrigger config ──────────────────────────────────────────────────────────
# Motives in this set pulse once per bar (activate beat 1, deactivate beat 1+)
# instead of sustaining for the full block duration.
RETRIGGER_MOTIVES = {'M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8', 'M9'}

# Set to a bar number to use hybrid mode: retrigger for bars < RETRIGGER_END_BAR,
# sustained from RETRIGGER_END_BAR onward.  None = retrigger throughout.
RETRIGGER_END_BAR = None   # e.g. 11 → retrigger bars 1-10, sustained bar 11+

# EP pitch for each motive (step, octave)
MOTIVE_PITCH = {
    'M1':  ('C', '3'),
    'M2':  ('D', '3'),
    'M3':  ('E', '4'),
    'M4':  ('F', '4'),
    'M5':  ('G', '3'),
    'M6':  ('A', '3'),
    'M7':  ('G', '4'),
    'M8':  ('A', '4'),
    'M9':  ('B', '4'),
    'M10': ('C', '4'),
    'M11': ('D', '4'),
    'M12': ('E', '5'),
}

# Voice and staff for each motive in EP part
MOTIVE_VOICE_STAFF = {
    'M1':  ('3', '2'), 'M2':  ('4', '2'),
    'M3':  ('1', '1'), 'M4':  ('2', '1'),
    'M5':  ('5', '2'), 'M6':  ('6', '2'),
    'M7':  ('7', '2'), 'M8':  ('1', '1'),
    'M9':  ('2', '1'), 'M10': ('3', '1'),
    'M11': ('4', '1'), 'M12': ('5', '1'),
}

NUM_MEASURES = 99

# Measures where a scene_next note should appear (kept for MusicXML annotation
# even though score.json no longer uses scene_next events)
SCENE_NEXT_MEASURES = {15, 48, 80}


def build_csv_rows():
    rows = []
    for motive, blocks in BLOCKS.items():
        for start_m, end_m in blocks:
            end_m_csv = end_m + 1
            beat_end  = 0.0
            if end_m >= NUM_MEASURES:
                end_m_csv = NUM_MEASURES
                beat_end  = 4.0
            rows.append({
                'measure_start': start_m,
                'beat_start':    0.0,
                'measure_end':   end_m_csv,
                'beat_end':      beat_end,
                'motive':        motive,
                'instruments':   '',
            })
    rows.sort(key=lambda r: (r['motive'], r['measure_start']))
    return rows


def build_score_events():
    """
    Return {bar_num: [event_dict, ...]} for all motive conductor events.

    Sustained block (start_m, end_m inclusive):
      activate  at bar start_m, beat 1, subdiv 0
      deactivate at bar end_m+1, beat 1, subdiv 0
      (special: last bar of movement deactivates at bar end_m, beat 4, subdiv 0)

    Retrigger block: one pulse per bar in the retrigger range —
      activate  at bar m, beat 1, subdiv 0
      deactivate at bar m, beat 1, subdiv 2   (beat "1+", half beat later)

    Hybrid (RETRIGGER_END_BAR = N):
      bars start_m .. N-1  → retrigger
      bars N .. end_m      → one sustained activate at N, deactivate at end
    """
    events = {}

    def add(bar, beat, subdiv, action, key):
        events.setdefault(bar, []).append(
            {'beat': beat, 'subdiv': subdiv, 'action': action, 'key': key}
        )

    for motive, blocks in BLOCKS.items():
        key = MOTIVE_KEY[motive]
        retrigger = motive in RETRIGGER_MOTIVES

        for start_m, end_m in blocks:
            at_last = (end_m >= NUM_MEASURES)
            deact_bar  = end_m     if at_last else end_m + 1
            deact_beat = 4         if at_last else 1

            if not retrigger:
                add(start_m, 1, 0, 'activate', key)
                add(deact_bar, deact_beat, 0, 'deactivate', key)
                continue

            # Retrigger (possibly hybrid)
            split = RETRIGGER_END_BAR  # None or bar number where sustained begins

            retrig_last = end_m if split is None else min(end_m, split - 1)
            for m in range(start_m, retrig_last + 1):
                add(m, 1, 0, 'activate', key)
                add(m, 1, 2, 'deactivate', key)

            # Sustained tail (only when RETRIGGER_END_BAR is set and falls within block)
            if split is not None and split <= end_m:
                sust_start = max(start_m, split)
                add(sust_start, 1, 0, 'activate', key)
                add(deact_bar, deact_beat, 0, 'deactivate', key)

    return events


def write_score_json():
    with open(SCORE_JSON) as f:
        score = json.load(f)

    mvt3 = next(m for m in score['movements'] if m['name'] == 'Movement III')
    all_keys = set(MOTIVE_KEY.values())
    new_events = build_score_events()

    for bar in mvt3['bars']:
        bn = bar['bar']
        # Remove old motive events
        bar['events'] = [
            e for e in bar.get('events', [])
            if not (e.get('action') in ('activate', 'deactivate')
                    and e.get('key') in all_keys)
        ]
        # Insert new events
        bar['events'].extend(new_events.get(bn, []))
        # Sort: beat asc, subdiv asc, deactivate before activate at same position
        bar['events'].sort(key=lambda e: (
            e.get('beat', 1),
            e.get('subdiv', 0),
            0 if e.get('action') == 'deactivate' else 1,
        ))

    with open(SCORE_JSON, 'w') as f:
        json.dump(score, f, indent=2)

    total = sum(len(v) for v in new_events.values())
    print(f'Written {total} conductor events to {SCORE_JSON}')


def make_note_xml(step, octave, duration, voice, staff,
                  tie_start=False, tie_stop=False):
    n = ET.Element('note')
    p = ET.SubElement(n, 'pitch')
    ET.SubElement(p, 'step').text   = step
    ET.SubElement(p, 'octave').text = octave
    ET.SubElement(n, 'duration').text = str(duration)
    ET.SubElement(n, 'voice').text  = voice
    ET.SubElement(n, 'type').text   = 'whole'
    ET.SubElement(n, 'staff').text  = staff
    notations = ET.SubElement(n, 'notations')
    if tie_stop:
        ET.SubElement(n, 'tie').set('type', 'stop')
        ET.SubElement(notations, 'tied').set('type', 'stop')
    if tie_start:
        ET.SubElement(n, 'tie').set('type', 'start')
        ET.SubElement(notations, 'tied').set('type', 'start')
    return n


def write_ep_part(ep_part, num_measures):
    measure_active = {i: [] for i in range(1, num_measures + 1)}
    for motive, blocks in BLOCKS.items():
        for start_m, end_m in blocks:
            for mn in range(start_m, min(end_m + 1, num_measures + 1)):
                is_first = (mn == start_m)
                is_last  = (mn == end_m)
                measure_active[mn].append((motive, is_first, is_last))

    div_by_measure = {}
    current_div = 4
    for m in ep_part.findall('measure'):
        mn = int(m.get('number'))
        d = m.findtext('.//divisions')
        if d:
            current_div = int(d)
        div_by_measure[mn] = current_div

    for m in ep_part.findall('measure'):
        mn = int(m.get('number'))
        for n in m.findall('note'):
            m.remove(n)

        active = measure_active.get(mn, [])
        if not active:
            continue

        div = div_by_measure.get(mn, 4)
        whole_dur = div * 4

        for motive, is_first, is_last in active:
            step, octave = MOTIVE_PITCH[motive]
            voice, staff = MOTIVE_VOICE_STAFF[motive]
            note = make_note_xml(
                step, octave, whole_dur, voice, staff,
                tie_start=not is_last,
                tie_stop=not is_first,
            )
            m.append(note)

        if mn in SCENE_NEXT_MEASURES:
            scene_note = make_note_xml('C', '5', whole_dur, '8', '1')
            m.append(scene_note)


def main():
    rows = build_csv_rows()
    with open(CSV_OUT, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['measure_start','beat_start','measure_end','beat_end','motive','instruments'])
        w.writeheader()
        w.writerows(rows)
    print(f'Written {len(rows)} rows to {CSV_OUT}')

    tree = ET.parse(INPUT)
    root = tree.getroot()
    ep_part = root.find('.//part[@id="P26"]')
    if ep_part is None:
        print('ERROR: EP part P26 not found')
        return

    write_ep_part(ep_part, NUM_MEASURES)
    tree.write(OUTPUT, encoding='unicode', xml_declaration=True)
    print(f'Written annotated score to {OUTPUT}')

    write_score_json()


if __name__ == '__main__':
    main()
