#!/usr/bin/env python3
"""
Movement III EP motive generator.
Reads the Movement III MusicXML, writes motive blocks to CSV and
annotated EP part to output MusicXML.

Each motive block = one activate at start, one deactivate at end.
Boundaries derived from score label positions and consecutive note activity.
"""

import csv
import xml.etree.ElementTree as ET

INPUT   = 'Edited 3 Malaqatin Meetings - Full score - 01 Movement III Final.musicxml'
OUTPUT  = 'Edited 3 Malaqatin Meetings - Full score - 01 Movement III Final - John.musicxml'
CSV_OUT = 'movement3_motives.csv'

# ── Motive blocks (measure ranges, inclusive, score-derived) ─────────────────
# M7 kept separate from M1 (distinct visual sequence)
# M8 m84-95 included (same vibraphone tremolo pattern, no label but clear continuation)
# M12 = Solo Violin solo m80-96 (new motive)

BLOCKS = {
    'M1':  [(1,17),(24,25),(64,74),(92,96)],
    'M2':  [(5,17),(56,57),(64,69),(92,96)],
    'M3':  [(7,10),(58,59),(64,65),(92,96)],
    'M4':  [(11,17),(22,30),(34,35),(66,68)],
    'M5':  [(12,14),(16,17),(20,23),(25,25),(31,35),(67,69),(71,74),(76,76)],
    'M6':  [(15,17),(20,21),(24,24),(26,35),(44,47),(52,55),(70,73),(75,75),(80,83),(88,96)],
    'M7':  [(18,25),(44,99)],
    'M8':  [(48,51),(56,59),(84,95)],
    'M9':  [(31,43)],
    'M10': [(36,44),(88,96)],
    'M11': [(44,60),(88,96)],
    'M12': [(80,96)],
}

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
# Staff 1 (treble): M3, M4, M8, M9, M10, M11, M12
# Staff 2 (bass):   M1, M2, M5, M6, M7
MOTIVE_VOICE_STAFF = {
    'M1':  ('3', '2'), 'M2':  ('4', '2'),
    'M3':  ('1', '1'), 'M4':  ('2', '1'),
    'M5':  ('5', '2'), 'M6':  ('6', '2'),
    'M7':  ('7', '2'), 'M8':  ('1', '1'),
    'M9':  ('2', '1'), 'M10': ('3', '1'),
    'M11': ('4', '1'), 'M12': ('5', '1'),
}

NUM_MEASURES = 99


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
    # Build per-measure active motive list
    measure_active = {i: [] for i in range(1, num_measures + 1)}
    for motive, blocks in BLOCKS.items():
        for start_m, end_m in blocks:
            for mn in range(start_m, min(end_m + 1, num_measures + 1)):
                is_first = (mn == start_m)
                is_last  = (mn == end_m)
                measure_active[mn].append((motive, is_first, is_last))

    # Get divisions per measure (may vary across parts — use EP part's own divisions)
    div_by_measure = {}
    current_div = 4
    for m in ep_part.findall('measure'):
        mn = int(m.get('number'))
        d = m.findtext('.//divisions')
        if d:
            current_div = int(d)
        div_by_measure[mn] = current_div

    # Rewrite EP notes
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


if __name__ == '__main__':
    main()
