#!/usr/bin/env python3
"""
Movement III EP motive generator.
Reads the Movement III MusicXML, writes motive blocks to CSV,
annotated EP part to output MusicXML, and conductor events to score.json.

Retrigger motives: one activate/deactivate pair per unique note onset, collected
from ALL parts in the MusicXML (any instrument playing contributes to retrigger
timing).  M6 uses accent-only triggering when any part has accented 16th notes
in that measure; all non-rest notes otherwise.

Sustained motives: one activate at block start, one deactivate at block end.

RETRIGGER_END_BAR: set to a bar number for hybrid mode — retrigger for bars
before that number, sustained from that bar onward.  None = retrigger throughout.
"""

import csv
import json
import pathlib
import xml.etree.ElementTree as ET

SCRIPT_DIR = pathlib.Path(__file__).parent
INPUT      = str(SCRIPT_DIR / 'Edited 3 Malaqatin Meetings - Full score - 01 Movement III Final.musicxml')
OUTPUT     = str(SCRIPT_DIR / 'Edited 3 Malaqatin Meetings - Full score - 01 Movement III Final - John.musicxml')
CSV_OUT    = str(SCRIPT_DIR / 'movement3_motives.csv')
SCORE_JSON = str(SCRIPT_DIR.parent / 'score.json')

# ── Motive blocks (measure ranges, inclusive) ─────────────────────────────────
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
# Motives that retrigger per note from MusicXML.
# M4, M5, M8 stay sustained.
RETRIGGER_MOTIVES = {'M1', 'M2', 'M3', 'M6', 'M7', 'M9'}

# Hybrid mode: set to a bar number to retrigger bars < N, sustain bars >= N.
# None = retrigger throughout all blocks.
RETRIGGER_END_BAR = None

# EP pitch for each motive (step, octave)
MOTIVE_PITCH = {
    'M1':  ('C', '3'), 'M2':  ('D', '3'),
    'M3':  ('E', '4'), 'M4':  ('F', '4'),
    'M5':  ('G', '3'), 'M6':  ('A', '3'),
    'M7':  ('G', '4'), 'M8':  ('A', '4'),
    'M9':  ('B', '4'), 'M10': ('C', '4'),
    'M11': ('D', '4'), 'M12': ('E', '5'),
}

MOTIVE_VOICE_STAFF = {
    'M1':  ('3', '2'), 'M2':  ('4', '2'),
    'M3':  ('1', '1'), 'M4':  ('2', '1'),
    'M5':  ('5', '2'), 'M6':  ('6', '2'),
    'M7':  ('7', '2'), 'M8':  ('1', '1'),
    'M9':  ('2', '1'), 'M10': ('3', '1'),
    'M11': ('4', '1'), 'M12': ('5', '1'),
}

NUM_MEASURES   = 99
SCENE_NEXT_MEASURES = {15, 48, 80}


# ── Note parsing ──────────────────────────────────────────────────────────────

def parse_part_notes(root, part_id):
    """
    Parse all notes from a part.
    Returns {mnum: [{'offset': qn, 'dur': qn, 'accent': bool, 'rest': bool, 'tie_cont': bool}]}
    offset/dur are in quarter notes.  tie_cont=True means this note continues a previous tie
    (not a new onset).
    """
    part = root.find(f'.//part[@id="{part_id}"]')
    if part is None:
        return {}

    result = {}
    cur_div = 4
    for m in part.findall('measure'):
        mnum = int(m.get('number'))
        for attr in m.findall('attributes'):
            d = attr.findtext('divisions')
            if d:
                cur_div = int(d)

        notes = []
        offset = 0  # ticks from bar start
        for n in m.findall('note'):
            dur_raw  = int(n.findtext('duration') or 0)
            is_chord = n.find('chord') is not None
            is_rest  = n.find('rest')  is not None
            tie_cont = any(t.get('type') == 'stop' for t in n.findall('tie'))
            has_acc  = n.find('.//accent') is not None

            if not is_chord:
                notes.append({
                    'offset':   offset / cur_div,
                    'dur':      dur_raw / cur_div,
                    'accent':   has_acc,
                    'rest':     is_rest,
                    'tie_cont': tie_cont,
                })
                offset += dur_raw

        result[mnum] = notes
    return result


def offset_to_beat_subdiv(offset_qn):
    """
    Quarter-note offset within a bar → (beat 1-indexed, subdiv 0-3).
    subdiv is in 16th-note units: 0=on beat, 1=one 16th after, 2=half beat, 3=three 16ths after.
    """
    beat   = int(offset_qn) + 1
    subdiv = round((offset_qn % 1.0) * 4)
    if subdiv >= 4:
        beat  += 1
        subdiv = 0
    return beat, subdiv


def collect_onsets_all_parts(motive, all_part_notes, mnum):
    """
    Collect unique note onset offsets (quarter-note) for one measure,
    scanning ALL parts.  Returns a sorted list of (act_off, deact_off) pairs.
    deact_off = act_off + 0.25 (one 16th note pulse per onset).

    M6: if any part has accented 16th notes in this measure, only use
    accented-16th onsets from all parts; otherwise use all non-rest onsets.
    """
    # Gather all candidate notes from every part for this measure
    all_notes = []
    for part_notes in all_part_notes.values():
        for n in part_notes.get(mnum, []):
            if not n['rest'] and not n['tie_cont']:
                all_notes.append(n)

    if not all_notes:
        return []

    if motive == 'M6':
        has_accented_16ths = any(
            n['accent'] and abs(n['dur'] - 0.25) < 0.01
            for n in all_notes
        )
        if has_accented_16ths:
            all_notes = [n for n in all_notes if n['accent'] and abs(n['dur'] - 0.25) < 0.01]

    # Deduplicate by onset offset, then build pairs
    unique_offsets = sorted(set(n['offset'] for n in all_notes))
    return [(off, off + 0.25) for off in unique_offsets]


# ── Score event building ──────────────────────────────────────────────────────

def build_score_events(root, bar_beats):
    """
    Build all conductor events.
    bar_beats: {bar_num: beat_count} from score.json — used to detect cross-bar deactivates.
    Returns {bar_num: [event_dict]}.
    """
    events = {}

    def add(bar, beat, subdiv, action, key):
        events.setdefault(bar, []).append(
            {'beat': beat, 'subdiv': subdiv, 'action': action, 'key': key}
        )

    # Pre-parse ALL parts (except EP part P26) for retrigger motives
    all_part_notes = {}
    if RETRIGGER_MOTIVES:
        for part in root.findall('part'):
            pid = part.get('id')
            if pid != 'P26':
                all_part_notes[pid] = parse_part_notes(root, pid)

    for motive, blocks in BLOCKS.items():
        key       = MOTIVE_KEY[motive]
        retrigger = motive in RETRIGGER_MOTIVES
        split     = RETRIGGER_END_BAR  # None or bar number

        for start_m, end_m in blocks:
            at_last    = (end_m >= NUM_MEASURES)
            deact_bar  = end_m     if at_last else end_m + 1
            deact_beat = 4         if at_last else 1

            if not retrigger:
                # Fully sustained
                add(start_m, 1, 0, 'activate', key)
                add(deact_bar, deact_beat, 0, 'deactivate', key)
                continue

            # Retrigger portion: bars start_m .. retrig_last
            retrig_last = end_m if split is None else min(end_m, split - 1)

            for mnum in range(start_m, retrig_last + 1):
                onsets = collect_onsets_all_parts(motive, all_part_notes, mnum)
                beats_in_bar = bar_beats.get(mnum, 4)

                for act_off, deact_off in onsets:
                    a_beat, a_subdiv = offset_to_beat_subdiv(act_off)
                    add(mnum, a_beat, a_subdiv, 'activate', key)

                    if deact_off >= beats_in_bar:
                        # Deactivate falls in next bar
                        add(mnum + 1, 1, 0, 'deactivate', key)
                    else:
                        d_beat, d_subdiv = offset_to_beat_subdiv(deact_off)
                        add(mnum, d_beat, d_subdiv, 'deactivate', key)

            # Sustained tail when RETRIGGER_END_BAR splits a block
            if split is not None and split <= end_m:
                sust_start = max(start_m, split)
                add(sust_start, 1, 0, 'activate', key)
                add(deact_bar, deact_beat, 0, 'deactivate', key)

    return events


def write_score_json():
    with open(SCORE_JSON) as f:
        score = json.load(f)

    mvt3 = next(m for m in score['movements'] if m['name'] == 'Movement III')
    all_keys  = set(MOTIVE_KEY.values())

    # Build bar_beats lookup from score.json
    bar_beats = {bar['bar']: bar['beats'] for bar in mvt3['bars']}

    # Parse MusicXML
    tree = ET.parse(INPUT)
    root = tree.getroot()

    new_events = build_score_events(root, bar_beats)

    for bar in mvt3['bars']:
        bn = bar['bar']
        # Remove existing motive events
        bar['events'] = [
            e for e in bar.get('events', [])
            if not (e.get('action') in ('activate', 'deactivate')
                    and e.get('key') in all_keys)
        ]
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

    # Summary per motive
    for motive, key in sorted(MOTIVE_KEY.items()):
        act = sum(1 for evs in new_events.values()
                  for e in evs if e.get('key') == key and e.get('action') == 'activate')
        print(f'  {motive} ({key}): {act} activates')


# ── CSV and MusicXML output (unchanged logic) ─────────────────────────────────

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
                'measure_start': start_m, 'beat_start': 0.0,
                'measure_end':   end_m_csv, 'beat_end':  beat_end,
                'motive': motive, 'instruments': '',
            })
    rows.sort(key=lambda r: (r['motive'], r['measure_start']))
    return rows


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
                measure_active[mn].append((motive, mn == start_m, mn == end_m))

    div_by_measure = {}
    current_div = 4
    for m in ep_part.findall('measure'):
        mn = int(m.get('number'))
        d  = m.findtext('.//divisions')
        if d: current_div = int(d)
        div_by_measure[mn] = current_div

    for m in ep_part.findall('measure'):
        mn = int(m.get('number'))
        for n in m.findall('note'):
            m.remove(n)
        active = measure_active.get(mn, [])
        if not active:
            continue
        div      = div_by_measure.get(mn, 4)
        whole_dur = div * 4
        for motive, is_first, is_last in active:
            step, octave = MOTIVE_PITCH[motive]
            voice, staff = MOTIVE_VOICE_STAFF[motive]
            m.append(make_note_xml(step, octave, whole_dur, voice, staff,
                                   tie_start=not is_last, tie_stop=not is_first))
        if mn in SCENE_NEXT_MEASURES:
            m.append(make_note_xml('C', '5', whole_dur, '8', '1'))


def main():
    rows = build_csv_rows()
    with open(CSV_OUT, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['measure_start','beat_start',
                                          'measure_end','beat_end','motive','instruments'])
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
