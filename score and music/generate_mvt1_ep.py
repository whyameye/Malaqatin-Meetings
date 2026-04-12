#!/usr/bin/env python3
"""
Movement I EP motive generator.

Reads conductor events directly from score.json (Movement I) instead of
pattern-detecting from MusicXML.  Each activate→deactivate pair in score.json
maps to a note (or series of tied notes) in the EP part.

Outputs:
  movement1_motives.csv
  Edited 1 Malaqatin Meetings - Full score - 01 Movement I Final - John.musicxml
    (EP part P26 replaced with freshly generated notes)
"""

import csv
import json
import pathlib
import xml.etree.ElementTree as ET

SCRIPT_DIR = pathlib.Path(__file__).parent
INPUT      = str(SCRIPT_DIR / 'Keyboard 1 - Full score - 01 Movement I Final.musicxml')
OUTPUT     = str(SCRIPT_DIR / 'Edited 1 Malaqatin Meetings - Full score - 01 Movement I Final - John.musicxml')
CSV_OUT    = str(SCRIPT_DIR / 'movement1_motives.csv')
SCORE_JSON = str(SCRIPT_DIR.parent / 'score.json')

# ── Motive config ─────────────────────────────────────────────────────────────

# Conductor key → motive name
KEY_MOTIVE = {
    'q': 'M1', 'w': 'M2', 'e': 'M3', 'r': 'M4',
    'a': 'M5', 's': 'M6', 'd': 'M7', 'f': 'M8',
}

# EP pitch (step, octave) for each key
KEY_PITCH = {
    'q': ('C', '3'),  # M1 — bass v1
    'w': ('D', '3'),  # M2 — bass v2
    'e': ('E', '4'),  # M3 — treble v1
    'r': ('F', '4'),  # M4 — treble v2
    'a': ('G', '3'),  # M5 — bass v3
    's': ('A', '3'),  # M6 — bass v4
    'd': ('B', '4'),  # M7 — treble v3
    'f': ('A', '4'),  # M8 — treble v4
}

# EP (voice, staff) for each key
# Voices 1-4 = treble (staff 1); voices 5-8 = bass (staff 2)
# This matches the original EP structure and prevents voice-duration conflicts.
KEY_VOICE_STAFF = {
    'e': ('1', '1'),  # M3 — treble staff, voice 1
    'r': ('2', '1'),  # M4 — treble staff, voice 2
    'd': ('3', '1'),  # M7 — treble staff, voice 3
    'f': ('4', '1'),  # M8 — treble staff, voice 4
    'q': ('5', '2'),  # M1 — bass staff, voice 5
    'w': ('6', '2'),  # M2 — bass staff, voice 6
    'a': ('7', '2'),  # M5 — bass staff, voice 7
    's': ('8', '2'),  # M6 — bass staff, voice 8
}

# Voice blocks in output order: treble first (v1-4), then bass (v5-8)
VOICE_ORDER = ['e', 'r', 'd', 'f', 'q', 'w', 'a', 's']

# Motives that should beam consecutive notes in groups of 4
BEAM_CONFIG = {
    'e': ('eighth', 1),   # M3: 8th notes, 1 beam level
    'r': ('16th',   2),   # M4: 16th notes, 2 beam levels
}


# ── Interval extraction from score.json ───────────────────────────────────────

def load_mvt1_bars():
    """Load Movement I bars from score.json."""
    with open(SCORE_JSON) as f:
        score = json.load(f)
    mvt1 = next(m for m in score['movements'] if m['name'] == 'Movement I')
    return mvt1['bars']


def extract_intervals(mvt_bars, key):
    """
    Walk the event stream for a key and emit (sb, sq, eb, eq) intervals where:
      sb = start bar, sq = start offset in qn
      eb = end bar,   eq = end offset in qn  (eq=0 means "start of bar eb")
    """
    # Collect all events in order
    events = []
    for bar in mvt_bars:
        for e in bar.get('events', []):
            if e.get('key') == key and e.get('action') in ('activate', 'deactivate'):
                offset = (e['beat'] - 1) + e['subdiv'] / 4.0
                events.append((bar['bar'], offset, e['action']))

    intervals = []
    cur_start = None
    for bar_num, offset, action in events:
        if action == 'activate':
            if cur_start is None:
                cur_start = (bar_num, offset)
        else:  # deactivate
            if cur_start is not None:
                intervals.append((*cur_start, bar_num, offset))
                cur_start = None
    return intervals


def bar_abs_start(mvt_bars, bar_num):
    """Return absolute quarter-note position of bar start."""
    pos = 0.0
    for bar in mvt_bars:
        if bar['bar'] == bar_num:
            return pos
        pos += bar['beats']
    return pos


# ── MusicXML helpers ──────────────────────────────────────────────────────────

def dur_to_note_type(dur_ticks, div):
    """Convert tick duration to (note_type, dots)."""
    ratio = dur_ticks / div
    for r, t, d in [
        (4, 'whole', 0), (3, 'half', 1), (2, 'half', 0),
        (1.5, 'quarter', 1), (1, 'quarter', 0),
        (0.75, 'eighth', 1), (0.5, 'eighth', 0),
        (0.375, '16th', 1), (0.25, '16th', 0),
    ]:
        if abs(ratio - r) < 0.01:
            return t, d
    return 'quarter', 0


def _greedy_split(ticks, div):
    """Return list of (dur_ticks, note_type) filling ticks, largest first."""
    result = []
    remaining = ticks
    candidates = sorted(
        [(round(r * div), t) for r, t in
         [(4, 'whole'), (2, 'half'), (1, 'quarter'), (0.5, 'eighth'), (0.25, '16th')]
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


def make_note_xml(step, octave, duration, voice, staff, note_type='quarter',
                  dots=0, tie_start=False, tie_stop=False):
    n = ET.Element('note')
    p = ET.SubElement(n, 'pitch')
    ET.SubElement(p, 'step').text   = step
    ET.SubElement(p, 'octave').text = octave
    ET.SubElement(n, 'duration').text = str(duration)
    if tie_stop:
        ET.SubElement(n, 'tie').set('type', 'stop')
    if tie_start:
        ET.SubElement(n, 'tie').set('type', 'start')
    ET.SubElement(n, 'voice').text = voice
    ET.SubElement(n, 'type').text  = note_type
    for _ in range(dots):
        ET.SubElement(n, 'dot')
    ET.SubElement(n, 'staff').text = staff
    notations = None
    if tie_stop or tie_start:
        notations = ET.SubElement(n, 'notations')
        if tie_stop:
            ET.SubElement(notations, 'tied').set('type', 'stop')
        if tie_start:
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


def ticks_to_rests(ticks, div, voice, staff):
    """Fill a tick gap with the fewest rests."""
    rests = []
    for dur, ntype in _greedy_split(ticks, div):
        rests.append(make_rest_xml(dur, ntype, voice, staff))
    return rests


# ── Per-bar note builder ───────────────────────────────────────────────────────

def build_voice_elements(key, intervals, bar_num, bar_abs, beats_in_bar, div):
    """
    Build MusicXML elements (notes + rests) for one voice in one measure.
    intervals: list of (sb, sq, eb, eq) for this key.
    Returns list of elements totalling exactly div*beats_in_bar ticks.
    """
    step, octave = KEY_PITCH[key]
    voice, staff  = KEY_VOICE_STAFF[key]
    whole_dur     = div * beats_in_bar
    bar_start_abs = bar_abs
    bar_end_abs   = bar_abs + beats_in_bar

    # Find intervals that overlap this bar (in absolute qn space)
    # Build abs_intervals: (abs_start, abs_end, sb, sq, eb, eq)
    # We need the bar abs_start map; pass it in via bar_abs
    active_in_bar = []
    for sb, sq, eb, eq in intervals:
        # We need abs positions — compute on the fly using bar_abs dicts passed from caller
        # Instead, pass pre-computed abs intervals
        pass

    # This function receives abs_intervals directly (see call site)
    return []  # placeholder — see build_voice_elements_abs below


def build_voice_elements_abs(key, abs_intervals, bar_abs_start, beats_in_bar, div,
                             xml_whole_dur=None):
    """
    Build MusicXML elements for one voice in one bar.
    abs_intervals: list of (abs_start_qn, abs_end_qn, orig_sb, orig_sq, orig_eb, orig_eq).
    xml_whole_dur: actual tick count for this bar from source (may differ from div*beats
                   if the source file has overlong notes, e.g. bar 26 in 2/4 uses 48 ticks).
    Returns element list totalling xml_whole_dur ticks.
    """
    step, octave = KEY_PITCH[key]
    voice, staff  = KEY_VOICE_STAFF[key]
    whole_dur     = xml_whole_dur if xml_whole_dur is not None else div * beats_in_bar
    # Scale factor: convert qn offsets to ticks
    # (normally div ticks/qn, but may differ for anomalous bars like bar 26)
    ticks_per_qn  = whole_dur / beats_in_bar if beats_in_bar else div
    bar_end_abs   = bar_abs_start + beats_in_bar

    # Filter to overlapping intervals
    overlapping = [
        (a, e, sb, sq, eb, eq)
        for (a, e, sb, sq, eb, eq) in abs_intervals
        if a < bar_end_abs and e > bar_abs_start
    ]
    if not overlapping:
        return ticks_to_rests(whole_dur, div, voice, staff)

    beam_type, beam_levels = BEAM_CONFIG.get(key, (None, 0))

    # Build list of note segments clipped to bar: (clip_start_qn, clip_end_qn, tie_stop, tie_start)
    segments = []
    for (a, e, sb, sq, eb, eq) in sorted(overlapping, key=lambda x: x[0]):
        clip_start = max(a, bar_abs_start) - bar_abs_start
        clip_end   = min(e, bar_end_abs)   - bar_abs_start
        tie_stop   = a < bar_abs_start       # interval started in a previous bar
        tie_start  = e > bar_end_abs         # interval continues into next bar
        segments.append((clip_start, clip_end, tie_stop, tie_start))

    # Build item list: (start_qn, end_qn, is_note, tie_stop, tie_start)
    items = []
    cursor = 0.0
    for clip_start, clip_end, tie_stop, tie_start in segments:
        if clip_start > cursor + 1e-9:
            items.append((cursor, clip_start, False, False, False))
        items.append((clip_start, clip_end, True, tie_stop, tie_start))
        cursor = clip_end
    if cursor < beats_in_bar - 1e-9:
        items.append((cursor, float(beats_in_bar), False, False, False))

    # Convert to XML elements with beaming.
    # Use ticks_per_qn (not raw div) so anomalous bars like bar 26 scale correctly.
    elements = []
    flat = []
    for start_qn, end_qn, is_note, tie_stop, tie_start in items:
        dur_ticks = round((end_qn - start_qn) * ticks_per_qn)
        if dur_ticks <= 0:
            continue
        if not is_note:
            for d, t in _greedy_split(dur_ticks, div):
                flat.append({'is_note': False, 'dur': d, 'type': t,
                              'dots': 0, 'tie_stop': False, 'tie_start': False})
        else:
            ntype, ndots = dur_to_note_type(dur_ticks, div)
            flat.append({'is_note': True, 'dur': dur_ticks, 'type': ntype,
                         'dots': ndots, 'tie_stop': tie_stop, 'tie_start': tie_start})

    # Apply beaming
    if beam_type and beam_levels:
        i = 0
        while i < len(flat):
            item = flat[i]
            if (item['is_note'] and item['type'] == beam_type
                    and item['dots'] == 0
                    and not item['tie_stop'] and not item['tie_start']):
                # Collect run
                run_start = i
                while (i < len(flat) and flat[i]['is_note']
                       and flat[i]['type'] == beam_type and flat[i]['dots'] == 0
                       and not flat[i]['tie_stop'] and not flat[i]['tie_start']):
                    i += 1
                run = flat[run_start:i]
                # Emit in groups of 4
                for g_start in range(0, len(run), 4):
                    group = run[g_start:g_start + 4]
                    for pos, it in enumerate(group):
                        note = make_note_xml(step, octave, it['dur'], voice, staff,
                                             note_type=it['type'], dots=it['dots'])
                        if len(group) > 1:
                            tag = ('begin' if pos == 0
                                   else ('end' if pos == len(group) - 1
                                         else 'continue'))
                            for lvl in range(1, beam_levels + 1):
                                b = ET.SubElement(note, 'beam')
                                b.set('number', str(lvl))
                                b.text = tag
                        elements.append(note)
            else:
                if item['is_note']:
                    elements.append(make_note_xml(
                        step, octave, item['dur'], voice, staff,
                        note_type=item['type'], dots=item['dots'],
                        tie_stop=item['tie_stop'], tie_start=item['tie_start'],
                    ))
                else:
                    elements.append(make_rest_xml(item['dur'], item['type'], voice, staff))
                i += 1
    else:
        for item in flat:
            if item['is_note']:
                elements.append(make_note_xml(
                    step, octave, item['dur'], voice, staff,
                    note_type=item['type'], dots=item['dots'],
                    tie_stop=item['tie_stop'], tie_start=item['tie_start'],
                ))
            else:
                elements.append(make_rest_xml(item['dur'], item['type'], voice, staff))

    return elements


# ── EP part writer ────────────────────────────────────────────────────────────

def _ep_xml_dur_by_bar(ep_part):
    """
    Compute actual tick count per measure from the EP part BEFORE notes are stripped.
    Uses the first voice found in each measure so anomalous bars (e.g. bar 26 in 2/4
    has 48-tick content) are preserved correctly.
    Returns {bar_num: tick_count}.
    """
    result = {}
    cur_div = 12
    for m in ep_part.findall('measure'):
        mn = int(m.get('number'))
        d  = m.findtext('.//divisions')
        if d:
            cur_div = int(d)
        # Find the first voice that has any notes and sum its durations
        voice_totals = {}
        for el in m:
            if el.tag == 'note' and el.find('chord') is None:
                v = el.findtext('voice') or '1'
                voice_totals[v] = voice_totals.get(v, 0) + int(el.findtext('duration') or 0)
        if voice_totals:
            # Use the max (most notes = most representative of bar capacity)
            result[mn] = max(voice_totals.values())
        else:
            result[mn] = cur_div * 4
    return result


def write_ep_part(ep_part, mvt_bars, abs_by_bar, source_root=None):
    """Replace EP part notes with generated content."""
    # Extract intervals for every key (absolute qn)
    abs_intervals_by_key = {}
    for key in VOICE_ORDER:
        raw = extract_intervals(mvt_bars, key)
        abs_ivals = []
        for sb, sq, eb, eq in raw:
            a = abs_by_bar[sb] + sq
            e = abs_by_bar[eb] + eq
            abs_ivals.append((a, e, sb, sq, eb, eq))
        abs_intervals_by_key[key] = abs_ivals

    # Build div_by_measure from EP part
    div_by_measure = {}
    cur_div = 12
    for m in ep_part.findall('measure'):
        mn = int(m.get('number'))
        d  = m.findtext('.//divisions')
        if d:
            cur_div = int(d)
        div_by_measure[mn] = cur_div

    beats_by_bar   = {bar['bar']: bar['beats'] for bar in mvt_bars}
    xml_dur_by_bar = _ep_xml_dur_by_bar(ep_part)  # actual ticks per bar (read before stripping)

    for m in ep_part.findall('measure'):
        mn = int(m.get('number'))
        # Strip notes, backups, forwards, and direction elements
        for tag in ('note', 'backup', 'forward', 'direction'):
            for el in list(m.findall(tag)):
                m.remove(el)

        div          = div_by_measure.get(mn, 12)
        beats_in_bar = beats_by_bar.get(mn, 4)
        xml_whole    = xml_dur_by_bar.get(mn, div * beats_in_bar)
        bar_abs      = abs_by_bar.get(mn, 0.0)

        voice_blocks = []
        for key in VOICE_ORDER:
            abs_ivals = abs_intervals_by_key[key]
            bar_end = bar_abs + beats_in_bar
            has_overlap = any(a < bar_end and e > bar_abs for (a, e, *_) in abs_ivals)
            if not has_overlap:
                voice_blocks.append(None)
                continue

            elems = build_voice_elements_abs(key, abs_ivals, bar_abs, beats_in_bar, div,
                                             xml_whole_dur=xml_whole)
            voice_blocks.append(elems)

        # Write to measure: each non-None block with backups between
        wrote_any = False
        prev_ticks = 0
        for elems in voice_blocks:
            if elems is None:
                continue
            if wrote_any:
                m.append(make_backup_xml(prev_ticks))
            prev_ticks = sum(
                int(el.findtext('duration') or 0)
                for el in elems
                if el.tag != 'beam' and el.findtext('duration') is not None
            )
            for el in elems:
                m.append(el)
            wrote_any = True


# ── CSV writer ────────────────────────────────────────────────────────────────

def build_csv_rows(mvt_bars):
    """One row per activate→deactivate interval."""
    rows = []
    for key in VOICE_ORDER:
        motive = KEY_MOTIVE[key]
        for sb, sq, eb, eq in extract_intervals(mvt_bars, key):
            # beat_start/beat_end are 1-indexed (beat 1 = 1.0)
            rows.append({
                'measure_start': sb,
                'beat_start':    sq + 1.0,
                'measure_end':   eb,
                'beat_end':      eq + 1.0,
                'motive':        motive,
                'instruments':   '',
            })
    rows.sort(key=lambda r: (r['measure_start'], r['beat_start'], r['motive']))
    return rows


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    mvt_bars = load_mvt1_bars()

    # Build absolute bar-start positions
    abs_by_bar = {}
    pos = 0.0
    for bar in mvt_bars:
        abs_by_bar[bar['bar']] = pos
        pos += bar['beats']
    # Add a sentinel for the first bar after the end
    abs_by_bar[mvt_bars[-1]['bar'] + 1] = pos

    # Write CSV
    rows = build_csv_rows(mvt_bars)
    with open(CSV_OUT, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'measure_start', 'beat_start', 'measure_end', 'beat_end',
            'motive', 'instruments',
        ])
        w.writeheader()
        w.writerows(rows)
    print(f'Written {len(rows)} rows to {CSV_OUT}')

    # Write MusicXML
    tree = ET.parse(INPUT)
    root = tree.getroot()
    ep_part = root.find('.//part[@id="P26"]')
    if ep_part is None:
        print('ERROR: EP part P26 not found in', INPUT)
        return

    write_ep_part(ep_part, mvt_bars, abs_by_bar, root)
    # Write with the DOCTYPE declaration that ET strips by default.
    xml_body = ET.tostring(root, encoding='unicode')
    with open(OUTPUT, 'w', encoding='utf-8') as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write('<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN"'
                 ' "http://www.musicxml.org/dtds/partwise.dtd">\n')
        fh.write(xml_body)
    print(f'Written annotated score to {OUTPUT}')

    # Summary
    for key in VOICE_ORDER:
        motive = KEY_MOTIVE[key]
        count  = len(extract_intervals(mvt_bars, key))
        print(f'  {motive} ({key}): {count} intervals')


if __name__ == '__main__':
    main()
