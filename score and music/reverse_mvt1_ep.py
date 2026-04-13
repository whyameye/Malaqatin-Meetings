#!/usr/bin/env python3
"""
Reverse Movement I EP generator.

Reads the annotated MusicXML (EP part P26) and reconstructs the
activate/deactivate events that would live in score.json.

Tests fidelity by comparing reconstructed events against the current
score.json — a perfect match confirms that the MusicXML and score.json
are exact mirrors and that either could be used to reconstruct the other.
"""

import json
import pathlib
import xml.etree.ElementTree as ET

SCRIPT_DIR = pathlib.Path(__file__).parent
INPUT_XML  = str(SCRIPT_DIR / 'Edited 1 Malaqatin Meetings - Full score - 01 Movement I Final - John.musicxml')
SCORE_JSON = str(SCRIPT_DIR.parent / 'score.json')

# (step, octave) → conductor key  (inverse of KEY_PITCH in generate_mvt1_ep.py)
PITCH_KEY = {
    ('C', '3'): 'q',  # M1
    ('D', '3'): 'w',  # M2
    ('E', '4'): 'e',  # M3
    ('F', '4'): 'r',  # M4
    ('G', '3'): 'a',  # M5
    ('A', '3'): 's',  # M6
    ('B', '4'): 'd',  # M7
    ('A', '4'): 'f',  # M8
}


def load_mvt1_bars():
    with open(SCORE_JSON) as f:
        score = json.load(f)
    mvt1 = next(m for m in score['movements'] if m['name'] == 'Movement I')
    return mvt1['bars']


def build_abs_by_bar(mvt_bars):
    abs_by_bar = {}
    pos = 0.0
    for bar in mvt_bars:
        abs_by_bar[bar['bar']] = pos
        pos += bar['beats']
    abs_by_bar[mvt_bars[-1]['bar'] + 1] = pos
    return abs_by_bar


def abs_to_bar_beat_subdiv(abs_qn, mvt_bars, abs_by_bar):
    """Convert absolute quarter-note position to (bar_num, beat, subdiv)."""
    for bar in mvt_bars:
        bar_start = abs_by_bar[bar['bar']]
        bar_end   = bar_start + bar['beats']
        if abs_qn < bar_end - 1e-9:
            offset = abs_qn - bar_start
            beat   = int(offset) + 1
            subdiv = round((offset - int(offset)) * 4)
            if subdiv == 4:
                beat  += 1
                subdiv = 0
            return bar['bar'], beat, subdiv
    # At or past end — assign to last bar
    last      = mvt_bars[-1]
    bar_start = abs_by_bar[last['bar']]
    offset    = abs_qn - bar_start
    beat      = int(offset) + 1
    subdiv    = round((offset - int(offset)) * 4)
    return last['bar'], beat, subdiv


def parse_ep_events(ep_part, mvt_bars, abs_by_bar):
    """
    Walk EP part P26 measure by measure and extract activate/deactivate events.

    Returns list of (bar_num, beat, subdiv, action, key) tuples.
    """
    events         = []
    open_intervals = {}   # key → abs_start_qn of the currently open interval
    cur_div        = 4

    for m in ep_part.findall('measure'):
        mn  = int(m.get('number'))
        d   = m.findtext('.//divisions')
        if d:
            cur_div = int(d)

        bar_abs  = abs_by_bar.get(mn, 0.0)
        cursor   = 0    # ticks from bar start (single global cursor, updated by notes/backup/forward)
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

            # Chord notes share the start position of the previous note
            note_pos = (cursor - last_dur) if is_chord else cursor

            if not is_rest:
                step   = el.findtext('pitch/step')
                octave = el.findtext('pitch/octave')
                key    = PITCH_KEY.get((step, octave))

                if key:
                    ties          = {t.get('type') for t in el.findall('tie')}
                    has_tie_stop  = 'stop'  in ties
                    has_tie_start = 'start' in ties

                    abs_start = bar_abs + note_pos / cur_div
                    abs_end   = bar_abs + (note_pos + dur) / cur_div

                    if not has_tie_stop:
                        open_intervals[key] = abs_start
                        b, beat, subdiv = abs_to_bar_beat_subdiv(abs_start, mvt_bars, abs_by_bar)
                        events.append((b, beat, subdiv, 'activate', key))

                    if not has_tie_start:
                        if key in open_intervals:
                            b, beat, subdiv = abs_to_bar_beat_subdiv(abs_end, mvt_bars, abs_by_bar)
                            events.append((b, beat, subdiv, 'deactivate', key))
                            del open_intervals[key]

            if not is_chord:
                last_dur = dur
                cursor  += dur

    return events


def get_original_events(mvt_bars):
    """Extract all activate/deactivate events from score.json as a set of tuples."""
    orig = set()
    for bar in mvt_bars:
        for e in bar.get('events', []):
            if e.get('action') in ('activate', 'deactivate'):
                orig.add((bar['bar'], e['beat'], e.get('subdiv', 0), e['action'], e['key']))
    return orig


def main():
    mvt_bars   = load_mvt1_bars()
    abs_by_bar = build_abs_by_bar(mvt_bars)

    tree    = ET.parse(INPUT_XML)
    root    = tree.getroot()
    ep_part = root.find('.//part[@id="P26"]')
    if ep_part is None:
        print('ERROR: EP part P26 not found in', INPUT_XML)
        return

    reconstructed = parse_ep_events(ep_part, mvt_bars, abs_by_bar)
    recon_set     = set(reconstructed)

    orig_set      = get_original_events(mvt_bars)

    print(f'score.json events : {len(orig_set)}')
    print(f'Reconstructed     : {len(recon_set)}')

    missing = orig_set  - recon_set   # in original but not reconstructed
    extra   = recon_set - orig_set    # in reconstructed but not original

    if not missing and not extra:
        print('\nPERFECT MATCH — MusicXML and score.json are exact mirrors.')
    else:
        if missing:
            print(f'\n{len(missing)} events in score.json but MISSING from reconstruction:')
            for e in sorted(missing):
                print(f'  bar={e[0]:3d}  beat={e[1]}  subdiv={e[2]}  {e[3]:12s}  {e[4]}')
        if extra:
            print(f'\n{len(extra)} events EXTRA in reconstruction (not in score.json):')
            for e in sorted(extra):
                print(f'  bar={e[0]:3d}  beat={e[1]}  subdiv={e[2]}  {e[3]:12s}  {e[4]}')


if __name__ == '__main__':
    main()
