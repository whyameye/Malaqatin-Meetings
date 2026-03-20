#!/usr/bin/python3
"""parse_score.py — Convert MusicXML EP part to score.json for conductor mode.

Usage:
  python3 parse_score.py

Reads the Electric Piano part (P26) from the Movement I MusicXML and writes
score.json to the project root. Re-run whenever the score changes.

Pitch-to-key mapping (EP part, P26):
  C3 = q (M1 — tied whole notes)
  D3 = w (M2 — repeating quarters)
  E4 = e (M3 — repeating 8ths)
  F4 = r (M4 — repeating 16ths)
  G3 = a (M5 — slides)
  A3 = s (M6 — rhythmic pattern)
  B4 = d (M7 — tremolo)
  P↑ direction text = scene_next
"""

import xml.etree.ElementTree as ET
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCORE_DIR  = os.path.join(SCRIPT_DIR, 'score and music')

MOVEMENTS = [
    {
        'name':        'Movement I',
        'file':        'Keyboard_1_Modified_v17 16-March-2026 John edits.musicxml',
        'defaultBPM':  80,
        'ep_part_id':  'P26',
    },
]

# Only these pitches trigger visual events; all others are ignored
PITCH_TO_KEY = {
    ('C', '3'): 'q',  # M1
    ('D', '3'): 'w',  # M2
    ('E', '4'): 'e',  # M3
    ('F', '4'): 'r',        # M4
    ('G', '4'): ['e', 'r'], # chord: G4 treated as E4+F4 (M3+M4 together)
    ('G', '3'): 'a',        # M5
    ('A', '3'): 's',        # M6
    ('B', '4'): 'd',        # M7
    ('A', '4'): 'f',        # M8/M9 (cello/violin solos)
    ('C', '5'): 'scene_next',  # scene change marker
}


def parse_movement(mvmt_cfg):
    path = os.path.join(SCORE_DIR, mvmt_cfg['file'])
    if not os.path.exists(path):
        print(f'  ERROR: file not found: {mvmt_cfg["file"]}')
        return None

    tree = ET.parse(path)
    root = tree.getroot()

    ep = next((p for p in root.findall('part')
               if p.get('id') == mvmt_cfg['ep_part_id']), None)
    if ep is None:
        print(f'  ERROR: part {mvmt_cfg["ep_part_id"]} not found')
        return None

    tpq           = 4   # ticks per quarter note — updated from <divisions>
    beats_per_bar = 4   # updated from <time>
    abs_tick      = 0   # absolute tick from start of piece

    # bar_info[mnum] = (abs_tick_start, beats_per_bar, tpq)
    bar_info = {}

    # Collect all events as (abs_tick, action, key_or_None)
    raw_events = []

    for m in ep.findall('measure'):
        mnum = int(m.get('number'))

        # Update divisions and time signature
        attr = m.find('attributes')
        if attr is not None:
            d = attr.find('divisions')
            if d is not None:
                tpq = int(d.text)
            t = attr.find('time')
            if t is not None:
                b = t.find('beats')
                if b is not None:
                    beats_per_bar = int(b.text)

        bar_info[mnum] = (abs_tick, beats_per_bar, tpq)

        pos         = 0   # tick position within measure
        chord_start = 0   # tick of current chord group start

        for child in m:
            tag = child.tag

            if tag == 'backup':
                pos         -= int(child.find('duration').text)
                chord_start  = pos
                continue

            if tag == 'forward':
                pos         += int(child.find('duration').text)
                chord_start  = pos
                continue

            if tag == 'direction':
                continue  # scene_next now comes from C5 notes, not P↑ text

            if tag != 'note':
                continue

            dur_el = child.find('duration')
            dur    = int(dur_el.text) if dur_el is not None else 0

            is_chord = child.find('chord') is not None
            if is_chord:
                onset = chord_start
            else:
                chord_start = pos
                onset       = pos
                pos        += dur

            if child.find('rest') is not None:
                continue

            pitch = child.find('pitch')
            if pitch is None:
                continue

            step   = pitch.findtext('step',   '')
            octave = pitch.findtext('octave', '')
            key    = PITCH_TO_KEY.get((step, octave))
            if key is None:
                continue

            # Tie handling: skip activate for tie-stop, skip deactivate for tie-start
            is_tie_stop  = any(t.get('type') == 'stop'  for t in child.findall('tie'))
            is_tie_start = any(t.get('type') == 'start' for t in child.findall('tie'))

            keys = key if isinstance(key, list) else [key]
            for k in keys:
                if k == 'scene_next':
                    if not is_tie_stop:
                        raw_events.append((abs_tick + onset, 'scene_next', None))
                else:
                    if not is_tie_stop:
                        raw_events.append((abs_tick + onset,       'activate',   k))
                    if not is_tie_start:
                        raw_events.append((abs_tick + onset + dur, 'deactivate', k))

        abs_tick += beats_per_bar * tpq

    # Build sorted list of bar numbers
    bar_numbers = sorted(bar_info.keys())

    def abs_to_bar_beat_subdiv(tick):
        """Convert absolute tick to (bar, beat 1-indexed, subdiv 0-indexed 16th)."""
        # Find the bar this tick belongs to
        bar = bar_numbers[0]
        for bn in bar_numbers:
            start, _, _ = bar_info[bn]
            if tick >= start:
                bar = bn
            else:
                break
        start, _, tpq_b = bar_info[bar]
        within  = tick - start
        beat    = within // tpq_b + 1
        subdiv  = (within % tpq_b) // (tpq_b // 4)
        return bar, int(beat), int(subdiv)

    # Group events by bar
    events_by_bar = {}
    _priority = {'deactivate': 0, 'scene_next': 1, 'activate': 2}
    for tick, action, key in sorted(raw_events, key=lambda e: (e[0], _priority.get(e[1], 99))):
        bar, beat, subdiv = abs_to_bar_beat_subdiv(tick)
        ev = {'beat': beat, 'subdiv': subdiv, 'action': action}
        if key is not None:
            ev['key'] = key
        events_by_bar.setdefault(bar, []).append(ev)

    # Build bars list
    bars = []
    for bn in bar_numbers:
        _, bpb, _ = bar_info[bn]
        entry = {'bar': bn, 'beats': bpb}
        if bn in events_by_bar:
            entry['events'] = events_by_bar[bn]
        bars.append(entry)

    return {
        'name':       mvmt_cfg['name'],
        'defaultBPM': mvmt_cfg['defaultBPM'],
        'bars':       bars,
    }


def main():
    score = {'movements': []}

    for mvmt_cfg in MOVEMENTS:
        print(f'Parsing {mvmt_cfg["name"]}...')
        result = parse_movement(mvmt_cfg)
        if result:
            total     = len(result['bars'])
            with_evts = sum(1 for b in result['bars'] if b.get('events'))
            scene_nxt = sum(1 for b in result['bars']
                            for e in b.get('events', []) if e['action'] == 'scene_next')
            print(f'  {total} bars, {with_evts} bars with events, {scene_nxt} scene_next events')
            score['movements'].append(result)
        else:
            print('  Skipped.')

    out = os.path.join(SCRIPT_DIR, 'score.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(score, f, indent=2, ensure_ascii=False)
    print(f'\nWritten to {out}')


if __name__ == '__main__':
    main()
