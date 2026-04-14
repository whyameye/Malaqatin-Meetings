#!/usr/bin/env python3
"""
Reverse Movement III EP generator.

Reads the composer-edited annotated MusicXML (EP part P26 in
'Edited 3 ... - John.musicxml') and reconstructs conductor events
in score.json plus a new movement3_motives.csv.

Use this when the composer has manually edited the EP motive indicators
and you want those edits reflected in score.json.

Retrigger motives (M1, M2, M3, M6, M7, M9): each note → one activate/deactivate pair.
Sustained motives (M4, M5, M8, M10, M11, M12): tied whole-note blocks → one activate at
block start, one deactivate at block end.
"""

import csv
import json
import pathlib
import xml.etree.ElementTree as ET

SCRIPT_DIR = pathlib.Path(__file__).parent
INPUT_XML  = str(SCRIPT_DIR / 'Edited 3 Malaqatin Meetings - Full score - 01 Movement III Final - John.musicxml')
CSV_OUT    = str(SCRIPT_DIR / 'movement3_motives.csv')
SCORE_JSON = str(SCRIPT_DIR.parent / 'score.json')

# (step, octave) → motive  (inverse of MOTIVE_PITCH in generate_mvt3_ep.py)
PITCH_MOTIVE = {
    ('C', '3'): 'M1',  ('D', '3'): 'M2',
    ('E', '4'): 'M3',  ('F', '4'): 'M4',
    ('G', '3'): 'M5',  ('A', '3'): 'M6',
    ('G', '4'): 'M7',  ('A', '4'): 'M8',
    ('B', '4'): 'M9',  ('C', '4'): 'M10',
    ('D', '4'): 'M11', ('E', '5'): 'M12',
}

MOTIVE_KEY = {
    'M1': 'q', 'M2': 'w', 'M3': 'e', 'M4': 'r',
    'M5': 'a', 'M6': 's', 'M7': 'd', 'M8': 'f',
    'M9': 'g', 'M10': 'y', 'M11': 'u', 'M12': 'i',
}

RETRIGGER_MOTIVES = {'M1', 'M2', 'M3', 'M6', 'M7', 'M9'}
SUSTAINED_MOTIVES = {'M4', 'M5', 'M8', 'M10', 'M11', 'M12'}


def load_score():
    with open(SCORE_JSON) as f:
        return json.load(f)


def offset_to_beat_subdiv(offset_qn):
    """Quarter-note offset within a bar → (beat 1-indexed, subdiv 0-3)."""
    beat   = int(offset_qn) + 1
    subdiv = round((offset_qn % 1.0) * 4)
    if subdiv >= 4:
        beat  += 1
        subdiv = 0
    return beat, subdiv


def parse_ep_events(ep_part, bar_beats):
    """
    Walk EP part P26 and extract activate/deactivate events.

    Returns:
        events_by_bar: {bar_num: [event_dict, ...]}
        csv_rows: list of dicts ready for CSV output
    """
    events_by_bar = {}
    csv_rows      = []

    # Sustained motives: track open blocks — motive → (start_bar, start_off_qn)
    open_blocks = {}

    def add_event(bar_num, beat, subdiv, action, key):
        events_by_bar.setdefault(bar_num, []).append(
            {'beat': beat, 'subdiv': subdiv, 'action': action, 'key': key}
        )

    cur_div = 4

    for m in ep_part.findall('measure'):
        mn  = int(m.get('number'))
        d   = m.findtext('.//divisions')
        if d:
            cur_div = int(d)

        beats_in_bar = bar_beats.get(mn, 4)
        cursor   = 0    # ticks from bar start (single global cursor)
        last_dur = 0

        for el in m:
            if el.tag == 'backup':
                cursor -= int(el.findtext('duration') or 0)
                continue
            if el.tag == 'forward':
                cursor += int(el.findtext('duration') or 0)
                continue
            if el.tag != 'note':
                continue

            is_rest  = el.find('rest')  is not None
            is_chord = el.find('chord') is not None
            dur      = int(el.findtext('duration') or 0)

            note_pos = (cursor - last_dur) if is_chord else cursor

            if not is_rest:
                step   = el.findtext('pitch/step')
                octave = el.findtext('pitch/octave')
                motive = PITCH_MOTIVE.get((step, octave))

                if motive:
                    key  = MOTIVE_KEY[motive]
                    ties = {t.get('type') for t in el.findall('tie')}
                    has_tie_stop  = 'stop'  in ties
                    has_tie_start = 'start' in ties

                    act_off_qn   = note_pos / cur_div
                    deact_off_qn = (note_pos + dur) / cur_div

                    # Skip notes that start at or beyond the bar end (generator overflow artifact)
                    if act_off_qn >= beats_in_bar - 1e-9:
                        if not is_chord:
                            last_dur = dur
                            cursor  += dur
                        continue

                    if motive in RETRIGGER_MOTIVES:
                        # Each note is one activate/deactivate pair
                        a_beat, a_subdiv = offset_to_beat_subdiv(act_off_qn)
                        add_event(mn, a_beat, a_subdiv, 'activate', key)

                        if deact_off_qn >= beats_in_bar - 1e-9:
                            # Deactivate falls in next bar
                            add_event(mn + 1, 1, 0, 'deactivate', key)
                            csv_rows.append({
                                'measure_start': mn,    'beat_start': act_off_qn + 1.0,
                                'measure_end':   mn+1,  'beat_end':   1.0,
                                'motive': motive, 'instruments': '',
                            })
                        else:
                            d_beat, d_subdiv = offset_to_beat_subdiv(deact_off_qn)
                            add_event(mn, d_beat, d_subdiv, 'deactivate', key)
                            csv_rows.append({
                                'measure_start': mn,  'beat_start': act_off_qn + 1.0,
                                'measure_end':   mn,  'beat_end':   deact_off_qn + 1.0,
                                'motive': motive, 'instruments': '',
                            })

                    else:  # sustained
                        if not has_tie_stop:
                            # Start of a new block
                            open_blocks[motive] = (mn, act_off_qn)
                            a_beat, a_subdiv = offset_to_beat_subdiv(act_off_qn)
                            add_event(mn, a_beat, a_subdiv, 'activate', key)

                        if not has_tie_start:
                            # End of block
                            if motive in open_blocks:
                                start_bar, start_off = open_blocks.pop(motive)
                                if deact_off_qn >= beats_in_bar - 1e-9:
                                    add_event(mn + 1, 1, 0, 'deactivate', key)
                                    csv_rows.append({
                                        'measure_start': start_bar, 'beat_start': start_off + 1.0,
                                        'measure_end':   mn + 1,    'beat_end':   1.0,
                                        'motive': motive, 'instruments': '',
                                    })
                                else:
                                    d_beat, d_subdiv = offset_to_beat_subdiv(deact_off_qn)
                                    add_event(mn, d_beat, d_subdiv, 'deactivate', key)
                                    csv_rows.append({
                                        'measure_start': start_bar, 'beat_start': start_off + 1.0,
                                        'measure_end':   mn,        'beat_end':   deact_off_qn + 1.0,
                                        'motive': motive, 'instruments': '',
                                    })

            if not is_chord:
                last_dur = dur
                cursor  += dur

    return events_by_bar, csv_rows


def main():
    score = load_score()
    mvt3  = next(m for m in score['movements'] if m['name'] == 'Movement III')
    bar_beats = {bar['bar']: bar['beats'] for bar in mvt3['bars']}
    all_keys  = set(MOTIVE_KEY.values())

    tree    = ET.parse(INPUT_XML)
    root    = tree.getroot()
    ep_part = root.find('.//part[@id="P26"]')
    if ep_part is None:
        print('ERROR: EP part P26 not found in', INPUT_XML)
        return

    events_by_bar, csv_rows = parse_ep_events(ep_part, bar_beats)

    # Update score.json — replace all motive activate/deactivate events
    for bar in mvt3['bars']:
        bn = bar['bar']
        bar['events'] = [
            e for e in bar.get('events', [])
            if not (e.get('action') in ('activate', 'deactivate')
                    and e.get('key') in all_keys)
        ]
        bar['events'].extend(events_by_bar.get(bn, []))
        bar['events'].sort(key=lambda e: (
            e.get('beat', 1),
            e.get('subdiv', 0),
            0 if e.get('action') == 'deactivate' else 1,
        ))

    with open(SCORE_JSON, 'w') as f:
        json.dump(score, f, indent=2)

    total = sum(len(v) for v in events_by_bar.values())
    print(f'Written {total} events to {SCORE_JSON}')

    # Write CSV
    csv_rows.sort(key=lambda r: (r['measure_start'], r['beat_start'], r['motive']))
    with open(CSV_OUT, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'measure_start', 'beat_start', 'measure_end', 'beat_end', 'motive', 'instruments'
        ])
        w.writeheader()
        w.writerows(csv_rows)
    print(f'Written {len(csv_rows)} rows to {CSV_OUT}')

    # Summary per motive
    for motive in sorted(MOTIVE_KEY):
        key = MOTIVE_KEY[motive]
        act = sum(1 for evs in events_by_bar.values()
                  for e in evs if e.get('key') == key and e.get('action') == 'activate')
        print(f'  {motive} ({key}): {act} activates')


if __name__ == '__main__':
    main()
