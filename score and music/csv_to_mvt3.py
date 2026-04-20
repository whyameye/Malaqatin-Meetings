#!/usr/bin/env python3
"""
csv_to_mvt3.py — Generate Movement III EP MusicXML and score.json from movement3_motives.csv.

By default writes a PREVIEW MusicXML file and prints what would change in score.json
without modifying either original file.

Run with --apply to overwrite the actual output files:
    python3 csv_to_mvt3.py --apply
"""

import argparse
import csv
import json
import pathlib
import xml.etree.ElementTree as ET

SCRIPT_DIR  = pathlib.Path(__file__).parent
BASE_XML    = str(SCRIPT_DIR / 'Edited 3 Malaqatin Meetings - Full score - 01 Movement III Final.musicxml')
OUTPUT_XML  = str(SCRIPT_DIR / 'Edited 3 Malaqatin Meetings - Full score - 01 Movement III Final - John.musicxml')
PREVIEW_XML = str(SCRIPT_DIR / 'Edited 3 Malaqatin Meetings - Full score - 01 Movement III Final - John - preview.musicxml')
CSV_IN      = str(SCRIPT_DIR / 'movement3_motives.csv')
SCORE_JSON  = str(SCRIPT_DIR.parent / 'score.json')

MOTIVE_KEY = {
    'M1': 'q', 'M2': 'w', 'M3': 'e', 'M4':  'r',
    'M5': 'a', 'M6': 's', 'M7': 'd', 'M8':  'f',
    'M9': 'g', 'M10': 'y', 'M11': 'u', 'M12': 'i',
}

MOTIVE_PITCH = {
    'M1':  ('C', '3'), 'M2':  ('D', '3'),
    'M3':  ('E', '4'), 'M4':  ('F', '4'),
    'M5':  ('G', '3'), 'M6':  ('A', '3'),
    'M7':  ('G', '4'), 'M8':  ('A', '4'),
    'M9':  ('B', '4'), 'M10': ('C', '4'),
    'M11': ('D', '4'), 'M12': ('E', '5'),
}

MOTIVE_VOICE_STAFF = {
    'M1':  ('1', '2'), 'M2': ('2', '2'),
    'M5':  ('3', '2'), 'M6': ('4', '2'),
    'M3':  ('1', '1'), 'M4': ('1', '1'),
    'M7':  ('2', '1'), 'M9': ('2', '1'),
    'M8':  ('3', '1'), 'M10': ('3', '1'),
    'M11': ('4', '1'), 'M12': ('4', '1'),
}

RETRIGGER_MOTIVES  = {'M1', 'M2', 'M3', 'M6', 'M7', 'M9'}
SUSTAINED_MOTIVES  = {'M4', 'M5', 'M8', 'M10', 'M11', 'M12'}
SCENE_NEXT_MEASURES = {15, 48, 80}
NUM_MEASURES       = 99

# Output order for voice blocks within each measure
VOICE_ORDER = ['M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8', 'M9', 'M10', 'M11', 'M12']


# ── CSV reading ───────────────────────────────────────────────────────────────

def read_csv(path):
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            rows.append({
                'measure_start': int(row['measure_start']),
                'beat_start':    float(row['beat_start']),
                'measure_end':   int(row['measure_end']),
                'beat_end':      float(row['beat_end']),
                'motive':        row['motive'].strip(),
                'instruments':   row.get('instruments', '').strip(),
            })
    return rows


# ── Validation ────────────────────────────────────────────────────────────────

def validate_rows(rows, bar_beats):
    """
    Print warnings for suspicious CSV rows. Never aborts.
    Checks:
      - Unknown motive name
      - measure_end before measure_start
      - beat_end before beat_start (when same measure)
      - beat_start / beat_end out of range for the bar's time signature
      - Overlapping intervals for the same motive
    """
    warnings = []

    def warn(row_idx, motive, msg):
        warnings.append(f'  Row {row_idx+2} ({motive}): {msg}')  # +2: skip header row to match spreadsheet

    # Track open intervals per motive for overlap detection
    # motive → (row_idx, measure_start, beat_start, measure_end, beat_end)
    open_intervals = {}

    for i, row in enumerate(rows):
        motive        = row['motive']
        measure_start = row['measure_start']
        beat_start    = row['beat_start']
        measure_end   = row['measure_end']
        beat_end      = row['beat_end']

        if motive not in MOTIVE_KEY:
            warn(i, motive, f'unknown motive "{motive}" — skipped')
            continue

        # measure order
        if measure_end < measure_start:
            warn(i, motive, f'measure_end ({measure_end}) < measure_start ({measure_start})')

        # beat order within same measure
        if measure_end == measure_start and beat_end <= beat_start:
            warn(i, motive, f'beat_end ({beat_end}) <= beat_start ({beat_start}) in same measure')

        # beat_start in range
        beats_start_bar = bar_beats.get(measure_start)
        if beats_start_bar is not None:
            if beat_start < 1.0 - 1e-9:
                warn(i, motive, f'beat_start ({beat_start}) < 1 in bar {measure_start}')
            elif beat_start > beats_start_bar + 1.0 - 1e-9:
                warn(i, motive, f'beat_start ({beat_start}) exceeds bar {measure_start} length ({beats_start_bar} beats)')

        # beat_end in range
        beats_end_bar = bar_beats.get(measure_end)
        if beats_end_bar is not None:
            if beat_end < 1.0 - 1e-9:
                warn(i, motive, f'beat_end ({beat_end}) < 1 in bar {measure_end}')
            elif beat_end > beats_end_bar + 1.0 - 1e-9:
                warn(i, motive, f'beat_end ({beat_end}) exceeds bar {measure_end} length ({beats_end_bar} beats)')

        # duplicate / overlap detection
        def interval_lt(ma, ba, mb, bb):
            """True if (ma, ba) < (mb, bb)."""
            return ma < mb or (ma == mb and ba < bb)

        if motive in open_intervals:
            prev_i, prev_ms, prev_bs, prev_me, prev_be = open_intervals[motive]
            is_duplicate = (measure_start == prev_ms and beat_start == prev_bs and
                            measure_end   == prev_me and beat_end   == prev_be)
            if is_duplicate:
                warn(i, motive,
                     f'duplicate of row {prev_i+2} '
                     f'(bar {prev_ms} beat {prev_bs} – bar {prev_me} beat {prev_be})')
            elif interval_lt(measure_start, beat_start, prev_me, prev_be):
                warn(i, motive,
                     f'overlaps with row {prev_i+2} '
                     f'(bar {prev_ms} beat {prev_bs} – bar {prev_me} beat {prev_be})')

        open_intervals[motive] = (i, measure_start, beat_start, measure_end, beat_end)

    if warnings:
        print(f'\nWARNINGS ({len(warnings)}):')
        for w in warnings:
            print(w)
    else:
        print('\nValidation: OK')


# ── Beat conversion ───────────────────────────────────────────────────────────

def beat_float_to_beat_subdiv(beat_float):
    """1-indexed beat float (e.g. 1.5) → (beat 1-indexed, subdiv 0-3)."""
    beat   = int(beat_float)
    subdiv = round((beat_float - beat) * 4)
    if subdiv >= 4:
        beat  += 1
        subdiv = 0
    return beat, subdiv


# ── Score.json events ─────────────────────────────────────────────────────────

def csv_to_score_events(rows):
    """Convert CSV rows to {bar_num: [event_dict]}."""
    events_by_bar = {}

    def add(bar, beat, subdiv, action, key):
        events_by_bar.setdefault(bar, []).append(
            {'beat': beat, 'subdiv': subdiv, 'action': action, 'key': key}
        )

    for row in rows:
        key = MOTIVE_KEY.get(row['motive'])
        if not key:
            continue
        a_beat, a_subdiv = beat_float_to_beat_subdiv(row['beat_start'])
        d_beat, d_subdiv = beat_float_to_beat_subdiv(row['beat_end'])
        add(row['measure_start'], a_beat, a_subdiv, 'activate',   key)
        add(row['measure_end'],   d_beat, d_subdiv, 'deactivate', key)

    # Sort order matches generate_mvt3_ep.py: beat, subdiv, deact-before-act, then motive order
    _key_order = {k: i for i, k in enumerate(['q','w','e','r','a','s','d','f','g','y','u','i'])}
    for bar_num in events_by_bar:
        events_by_bar[bar_num].sort(key=lambda e: (
            e['beat'], e['subdiv'],
            0 if e['action'] == 'deactivate' else 1,
            _key_order.get(e['key'], 99),
        ))

    return events_by_bar


# ── EP data structures ────────────────────────────────────────────────────────

def build_ep_data(rows, bar_beats):
    """
    Returns:
        retrigger_by_bar: {bar_num: {motive: [(act_off_qn, deact_off_qn, instruments)]}}
        sustained_by_bar: {bar_num: {motive: (is_first, is_last)}}
    """
    retrigger_by_bar = {}
    sustained_by_bar = {}

    for row in rows:
        motive        = row['motive']
        measure_start = row['measure_start']
        beat_start    = row['beat_start']
        measure_end   = row['measure_end']
        beat_end      = row['beat_end']
        instruments   = row['instruments']

        act_off = beat_start - 1.0   # 0-indexed qn offset within measure_start

        if motive in RETRIGGER_MOTIVES:
            beats_in_bar = bar_beats.get(measure_start, 4)
            if measure_end == measure_start:
                deact_off = beat_end - 1.0
            else:
                deact_off = float(beats_in_bar)   # clip to bar end

            retrigger_by_bar.setdefault(measure_start, {}).setdefault(motive, [])
            retrigger_by_bar[measure_start][motive].append((act_off, deact_off, instruments))

        else:  # sustained
            # Determine bar range: first_bar..last_bar inclusive
            last_bar = (measure_end - 1) if beat_end <= 1.0 + 1e-9 else measure_end
            first_bar = measure_start
            for bar_num in range(first_bar, last_bar + 1):
                sustained_by_bar.setdefault(bar_num, {})[motive] = (
                    bar_num == first_bar,
                    bar_num == last_bar,
                )

    return retrigger_by_bar, sustained_by_bar


# ── MusicXML helpers (mirror of generate_mvt3_ep.py) ─────────────────────────

def make_note_xml(step, octave, duration, voice, staff, note_type='whole',
                  dots=0, tie_start=False, tie_stop=False):
    n = ET.Element('note')
    p = ET.SubElement(n, 'pitch')
    ET.SubElement(p, 'step').text   = step
    ET.SubElement(p, 'octave').text = octave
    ET.SubElement(n, 'duration').text = str(duration)
    ET.SubElement(n, 'voice').text  = voice
    ET.SubElement(n, 'type').text   = note_type
    for _ in range(dots):
        ET.SubElement(n, 'dot')
    ET.SubElement(n, 'staff').text  = staff
    notations = ET.SubElement(n, 'notations')
    if tie_stop:
        ET.SubElement(n, 'tie').set('type', 'stop')
        ET.SubElement(notations, 'tied').set('type', 'stop')
    if tie_start:
        ET.SubElement(n, 'tie').set('type', 'start')
        ET.SubElement(notations, 'tied').set('type', 'start')
    return n


def make_rest_xml(duration, note_type, voice, staff):
    n = ET.Element('note')
    ET.SubElement(n, 'rest')
    ET.SubElement(n, 'duration').text = str(duration)
    ET.SubElement(n, 'voice').text = voice
    ET.SubElement(n, 'type').text  = note_type
    ET.SubElement(n, 'staff').text = staff
    return n


def make_backup_xml(duration):
    b = ET.Element('backup')
    ET.SubElement(b, 'duration').text = str(duration)
    return b


def dur_to_note_type(dur_ticks, div):
    ratio = dur_ticks / div
    for r, t, d in [(4,'whole',0),(3,'half',1),(2,'half',0),(1.5,'quarter',1),
                    (1,'quarter',0),(0.75,'eighth',1),(0.5,'eighth',0),
                    (0.375,'16th',1),(0.25,'16th',0)]:
        if abs(ratio - r) < 0.01:
            return t, d
    return 'quarter', 0


def _greedy_split(ticks, div):
    result = []
    remaining = ticks
    candidates = sorted(
        [(round(r * div), t) for r, t in
         [(4,'whole'),(2,'half'),(1,'quarter'),(0.5,'eighth'),(0.25,'16th')]
         if round(r * div) > 0],
        reverse=True,
    )
    while remaining > 0:
        for dur, ntype in candidates:
            if dur <= remaining:
                result.append((dur, ntype))
                remaining -= dur
                break
        else:
            break
    return result


def ticks_to_rests(ticks, div, voice, staff):
    return [make_rest_xml(d, t, voice, staff) for d, t in _greedy_split(ticks, div)]


def build_note_sequence(step, octave, voice, staff, div, whole_dur, onsets):
    """Build retrigger note+rest elements for one voice in one measure."""
    if not onsets:
        return ticks_to_rests(whole_dur, div, voice, staff)

    seen_act = set()
    tick_pairs = []
    for act_off, deact_off, _ in onsets:
        act_tick   = round(act_off   * div)
        deact_tick = min(round(deact_off * div), whole_dur)
        if act_tick not in seen_act and act_tick < whole_dur:
            seen_act.add(act_tick)
            tick_pairs.append((act_tick, max(act_tick + 1, deact_tick)))
    tick_pairs.sort()
    if not tick_pairs:
        return ticks_to_rests(whole_dur, div, voice, staff)

    note_ticks = [(act, deact - act) for act, deact in tick_pairs]
    items = []
    current = 0
    for onset_tick, note_dur in note_ticks:
        gap = onset_tick - current
        if gap > 0:
            for d, t in _greedy_split(gap, div):
                items.append((d, t, 0, False))
                current += d
        ntype, ndots = dur_to_note_type(note_dur, div)
        items.append((note_dur, ntype, ndots, True))
        current = onset_tick + note_dur
    remaining = whole_dur - current
    if remaining > 0:
        for d, t in _greedy_split(remaining, div):
            items.append((d, t, 0, False))

    elements = []
    n_items = len(items)
    i = 0
    while i < n_items:
        dur, ntype, ndots, is_note = items[i]
        if not is_note or ntype not in ('eighth', '16th') or ndots:
            if is_note:
                elements.append(make_note_xml(step, octave, dur, voice, staff,
                                              note_type=ntype, dots=ndots))
            else:
                elements.append(make_rest_xml(dur, ntype, voice, staff))
            i += 1
            continue
        run_start = i
        while i < n_items and items[i][3] and items[i][1] == ntype and not items[i][2]:
            i += 1
        run = items[run_start:i]
        beam_levels = 2 if ntype == '16th' else 1
        for g_start in range(0, len(run), 4):
            group = run[g_start:g_start + 4]
            for pos, (d, t, dots, _) in enumerate(group):
                note = make_note_xml(step, octave, d, voice, staff, note_type=t, dots=dots)
                if len(group) > 1:
                    tag = 'begin' if pos == 0 else ('end' if pos == len(group) - 1 else 'continue')
                    for lvl in range(1, beam_levels + 1):
                        b = ET.SubElement(note, 'beam')
                        b.set('number', str(lvl))
                        b.text = tag
                elements.append(note)
    return elements


# ── EP part writer ────────────────────────────────────────────────────────────

def write_ep_part(ep_part, bar_beats, retrigger_by_bar, sustained_by_bar):
    div_by_measure = {}
    cur_div = 4
    for m in ep_part.findall('measure'):
        mn = int(m.get('number'))
        d  = m.findtext('.//divisions')
        if d: cur_div = int(d)
        div_by_measure[mn] = cur_div

    for m in ep_part.findall('measure'):
        mn = int(m.get('number'))
        for tag in ('note', 'backup', 'forward'):
            for el in list(m.findall(tag)):
                m.remove(el)

        div          = div_by_measure.get(mn, 4)
        beats_in_bar = bar_beats.get(mn, 4)
        whole_dur    = div * beats_in_bar

        retrigger_motives_here = retrigger_by_bar.get(mn, {})
        sustained_motives_here = sustained_by_bar.get(mn, {})

        if not retrigger_motives_here and not sustained_motives_here \
                and mn not in SCENE_NEXT_MEASURES:
            continue

        voice_blocks = []

        for motive in VOICE_ORDER:
            step, octave = MOTIVE_PITCH[motive]
            voice, staff = MOTIVE_VOICE_STAFF[motive]

            if motive in SUSTAINED_MOTIVES and motive in sustained_motives_here:
                is_first, is_last = sustained_motives_here[motive]
                ntype, ndots = dur_to_note_type(whole_dur, div)
                elems = [make_note_xml(step, octave, whole_dur, voice, staff,
                                       note_type=ntype, dots=ndots,
                                       tie_start=not is_last, tie_stop=not is_first)]
                voice_blocks.append(elems)

            elif motive in RETRIGGER_MOTIVES and motive in retrigger_motives_here:
                onsets = retrigger_motives_here[motive]
                elems  = build_note_sequence(step, octave, voice, staff,
                                             div, whole_dur, onsets)
                voice_blocks.append(elems)

        prev_ticks = 0
        for i, elems in enumerate(voice_blocks):
            if i > 0:
                m.append(make_backup_xml(prev_ticks))
            prev_ticks = sum(
                int(el.findtext('duration') or 0)
                for el in elems
                if el.find('chord') is None and el.findtext('duration') is not None
            )
            for el in elems:
                m.append(el)

        if mn in SCENE_NEXT_MEASURES:
            if voice_blocks:
                m.append(make_backup_xml(whole_dur))
            m.append(make_note_xml('C', '5', whole_dur, '8', '1'))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true',
                        help='Overwrite actual output files (default: preview only)')
    args = parser.parse_args()

    # Load CSV
    rows = read_csv(CSV_IN)
    print(f'Read {len(rows)} rows from {CSV_IN}')

    # Load score.json for bar structure
    with open(SCORE_JSON) as f:
        score = json.load(f)
    mvt3      = next(m for m in score['movements'] if m['name'] == 'Movement III')
    bar_beats = {bar['bar']: bar['beats'] for bar in mvt3['bars']}
    all_keys  = set(MOTIVE_KEY.values())

    # Validate CSV
    validate_rows(rows, bar_beats)

    # Build events and EP data
    events_by_bar                 = csv_to_score_events(rows)
    retrigger_by_bar, sustained_by_bar = build_ep_data(rows, bar_beats)

    # ── Score.json comparison / update ───────────────────────────────────────
    old_events = {}
    for bar in mvt3['bars']:
        bn = bar['bar']
        evts = [e for e in bar.get('events', [])
                if e.get('action') in ('activate','deactivate') and e.get('key') in all_keys]
        if evts:
            old_events[bn] = {(e['beat'], e.get('subdiv',0), e['action'], e['key']) for e in evts}

    new_events_set = {
        bn: {(e['beat'], e.get('subdiv',0), e['action'], e['key']) for e in evts}
        for bn, evts in events_by_bar.items()
    }

    key_motive = {v: k for k, v in MOTIVE_KEY.items()}  # e.g. 's' → 'M6'

    all_bars = sorted(set(old_events) | set(new_events_set))
    diff_bars = 0
    for bn in all_bars:
        old = old_events.get(bn, set())
        new = new_events_set.get(bn, set())
        missing = old - new
        extra   = new - old
        if missing or extra:
            if diff_bars == 0:
                print('\nScore.json changes (Movement III):')
            diff_bars += 1
            print(f'  Bar {bn}:')
            for e in sorted(missing):
                m = key_motive.get(e[3], e[3])
                print(f'    REMOVE: beat={e[0]} subdiv={e[1]} {e[2]:12s} {m} ({e[3]})')
            for e in sorted(extra):
                m = key_motive.get(e[3], e[3])
                print(f'    ADD:    beat={e[0]} subdiv={e[1]} {e[2]:12s} {m} ({e[3]})')
    if diff_bars == 0:
        print('\nScore.json: no changes to Movement III events.')
    else:
        print(f'\n{diff_bars} bars changed.')

    # ── MusicXML ─────────────────────────────────────────────────────────────
    tree    = ET.parse(BASE_XML)
    root    = tree.getroot()
    ep_part = root.find('.//part[@id="P26"]')
    if ep_part is None:
        print('ERROR: P26 not found in base MusicXML')
        return

    write_ep_part(ep_part, bar_beats, retrigger_by_bar, sustained_by_bar)

    if args.apply:
        # Update score.json Movement III
        for bar in mvt3['bars']:
            bn = bar['bar']
            bar['events'] = [
                e for e in bar.get('events', [])
                if not (e.get('action') in ('activate','deactivate') and e.get('key') in all_keys)
            ]
            bar['events'].extend(events_by_bar.get(bn, []))
            bar['events'].sort(key=lambda e: (
                e.get('beat',1), e.get('subdiv',0),
                0 if e.get('action') == 'deactivate' else 1,
            ))
        with open(SCORE_JSON, 'w') as f:
            json.dump(score, f, indent=2)
        print(f'\nWritten score.json')

        tree.write(OUTPUT_XML, encoding='unicode', xml_declaration=True)
        print(f'Written {OUTPUT_XML}')
    else:
        tree.write(PREVIEW_XML, encoding='unicode', xml_declaration=True)
        print(f'\nPreview written to: ...Final - John - preview.musicxml')
        print('Run with --apply to overwrite actual files.')

    # Summary
    print()
    for motive in sorted(MOTIVE_KEY):
        key = MOTIVE_KEY[motive]
        act = sum(1 for evts in events_by_bar.values()
                  for e in evts if e.get('key') == key and e.get('action') == 'activate')
        if act:
            print(f'  {motive} ({key}): {act} activates')


if __name__ == '__main__':
    main()
