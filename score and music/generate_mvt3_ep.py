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
    'M1':  [(1,99)],  # pattern detection
    'M2':  [(1,99)],  # pattern detection
    'M3':  [(1,99)],  # pattern detection
    'M4':  [(11,17),(22,30),(34,35),(66,68)],
    'M5':  [(12,14),(16,17),(20,23),(25,25),(31,35),(67,69),(71,74),(76,76)],
    'M6':  [(1,99)],  # pattern detection
    'M7':  [(1,99)],  # pattern detection
    'M8':  [(48,51),(56,59),(85,96)],
    'M9':  [(1,99)],  # pattern detection
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

# Solo parts excluded from M1-M9 retrigger when M10/M11/M12 are active.
SOLO_PARTS = {'P17', 'P18', 'P19', 'P20'}  # Solo Alto Sax, Solo Soprano Sax, Solo Violin, Solo Violoncello
SOLO_MUTE_MOTIVES = {'M10', 'M11', 'M12'}  # when these are active, exclude solo parts

# Pre-compute set of measures where any SOLO_MUTE_MOTIVE is active
SOLO_MUTE_MEASURES = set(
    mnum
    for motive in SOLO_MUTE_MOTIVES
    for start_m, end_m in BLOCKS[motive]
    for mnum in range(start_m, end_m + 1)
)

# Hybrid mode: set to a bar number to retrigger bars < N, sustain bars >= N.
# None = retrigger throughout all blocks.
RETRIGGER_END_BAR = None

# When True, retrigger motives scan every bar in the piece (not just BLOCKS).
# Sustained motives (M4, M5, M8) still respect their BLOCKS.
RETRIGGER_IGNORE_BLOCKS = False

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
    # Staff 2 (bass): 4 motives, one voice each — no sharing needed
    'M1':  ('1', '2'), 'M2':  ('2', '2'),
    'M5':  ('3', '2'), 'M6':  ('4', '2'),
    # Staff 1 (treble): 8 motives share 4 voices; pairs chosen to avoid overlap
    # M3+M4 share v1 (M3 ends bar 10/65, M4 starts bar 11/66 — no overlap)
    'M3':  ('1', '1'), 'M4':  ('1', '1'),
    # M7+M9 share v2 (M7 gap bars 26-43 covers M9 31-43 — no overlap)
    'M7':  ('2', '1'), 'M9':  ('2', '1'),
    # M8+M10 share v3 (conflict only bars 88-96)
    'M8':  ('3', '1'), 'M10': ('3', '1'),
    # M11+M12 share v4 (conflict only bars 88-96)
    'M11': ('4', '1'), 'M12': ('4', '1'),
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
                pitch_el = n.find('pitch')
                if pitch_el is not None:
                    pitch = pitch_el.findtext('step', '') + pitch_el.findtext('octave', '')
                else:
                    pitch = ''
                notes.append({
                    'offset':   offset / cur_div,
                    'dur':      dur_raw / cur_div,
                    'accent':   has_acc,
                    'rest':     is_rest,
                    'tie_cont': tie_cont,
                    'pitch':    pitch,
                })
                offset += dur_raw

        result[mnum] = notes
    return result


# M6 bar-range overrides: specific characteristic parts instead of pattern detection
M6_VIOLIN_BARS       = set(range(44, 48)) | set(range(52, 56)) | set(range(80, 84))
M6_FLUTE_BARS        = set(range(88, 97))
M6_SOPRANO_SAX_BARS  = {20, 21, 30}

# Percussion parts — M6 from percussion takes precedence over non-percussion
PERCUSSION_PARTS = {'P9', 'P10', 'P11', 'P12', 'P13', 'P14', 'P15', 'P16'}


def _m1_offsets(notes):
    """8 eighth notes through the entire bar, all the same pitch. Returns all onsets if matched."""
    onset = [n for n in notes if not n['rest'] and not n['tie_cont']]
    if len(onset) != 8:
        return set()
    if abs(onset[0]['offset'] - 0.0) > 0.01:
        return set()
    if not all(abs(n['dur'] - 0.5) < 0.01 for n in onset):
        return set()
    if len(set(n['pitch'] for n in onset)) != 1:
        return set()  # pitches differ — not M1
    return {n['offset'] for n in onset}


def _m2_detect_pattern(notes):
    """Returns True if the M2 figure starts at offset 0.0:
    16th, 16th, 8th, 16th, 16th, 8th, 16th, 16th, 16th, 16th — all non-rest, non-tie-cont.
    """
    expected = [0.25, 0.25, 0.5, 0.25, 0.25, 0.5, 0.25, 0.25, 0.25, 0.25]
    onset = [n for n in notes if not n['rest'] and not n['tie_cont']]
    if len(onset) < len(expected):
        return False
    if abs(onset[0]['offset'] - 0.0) > 0.01:
        return False
    return all(abs(onset[i]['dur'] - expected[i]) < 0.01 for i in range(len(expected)))


def _m3_offsets(notes):
    """16 sixteenth notes, all same note, NO accents. If any accents present, not M3."""
    onset = [n for n in notes if not n['rest'] and not n['tie_cont']]
    if len(onset) != 16:
        return set()
    if abs(onset[0]['offset'] - 0.0) > 0.01:
        return set()
    if not all(abs(n['dur'] - 0.25) < 0.01 for n in onset):
        return set()
    if any(n['accent'] for n in onset):
        return set()  # accents present → this is M6 P2, not M3
    return {n['offset'] for n in onset}


def _m7_offsets(notes):
    """Continual 8th notes through entire bar WITH pitch changes. Returns all onsets if matched."""
    onset = [n for n in notes if not n['rest'] and not n['tie_cont']]
    if not onset:
        return set()
    if abs(onset[0]['offset'] - 0.0) > 0.01:
        return set()
    if not all(abs(n['dur'] - 0.5) < 0.01 for n in onset):
        return set()
    if len(set(n['pitch'] for n in onset)) < 2:
        return set()  # all same pitch — that's M1, not M7
    return {n['offset'] for n in onset}


def _m9_offsets(notes):
    """4 quarter notes in a row. Returns all 4 onsets if matched."""
    onset = [n for n in notes if not n['rest'] and not n['tie_cont']]
    if len(onset) < 4:
        return set()
    if abs(onset[0]['offset'] - 0.0) > 0.01:
        return set()
    if not all(abs(onset[i]['dur'] - 1.0) < 0.01 for i in range(4)):
        return set()
    return {onset[i]['offset'] for i in range(4)}


def _m6_p1_offsets(notes):
    """Pattern 1: 8th→quarter→8th→8th…until rest. Returns offsets of every note in the figure."""
    offsets = set()
    i = 0
    while i <= len(notes) - 4:
        durs  = [notes[j]['dur']  for j in range(i, i + 4)]
        rests = [notes[j]['rest'] for j in range(i, i + 4)]
        if (not any(rests) and
                abs(durs[0] - 0.5) < 0.01 and abs(durs[1] - 1.0) < 0.01 and
                abs(durs[2] - 0.5) < 0.01 and abs(durs[3] - 0.5) < 0.01):
            j = i
            while j < len(notes) and not notes[j]['rest']:
                offsets.add(notes[j]['offset'])
                j += 1
            i = j
        else:
            i += 1
    return offsets


def _m6_p2_offsets(notes):
    """Pattern 2: accented 16th notes. Returns offsets of accented 16ths."""
    return {n['offset'] for n in notes
            if not n['rest'] and n['accent'] and abs(n['dur'] - 0.25) < 0.01}


def _m6_p3_offsets(notes):
    """Pattern 3: rest(8th)→note(8th)→note(8th)→rest(8th) OR note(8th)→rest(8th)→rest(8th)→note(8th)
    starting at offset 0.0.  When matched, trigger on ALL non-rest notes in the bar."""
    for i in range(len(notes) - 3):
        a, b, c, d = notes[i], notes[i+1], notes[i+2], notes[i+3]
        if abs(a['offset'] - 0.0) > 0.01: continue
        # variant 1: rest note note rest
        if (a['rest']      and abs(a['dur'] - 0.5) < 0.01 and
                not b['rest'] and abs(b['dur'] - 0.5) < 0.01 and
                not c['rest'] and abs(c['dur'] - 0.5) < 0.01 and
                d['rest']      and abs(d['dur'] - 0.5) < 0.01):
            return {n['offset'] for n in notes if not n['rest']}
        # variant 2: note rest rest note
        if (not a['rest'] and abs(a['dur'] - 0.5) < 0.01 and
                b['rest']      and abs(b['dur'] - 0.5) < 0.01 and
                c['rest']      and abs(c['dur'] - 0.5) < 0.01 and
                not d['rest'] and abs(d['dur'] - 0.5) < 0.01):
            return {n['offset'] for n in notes if not n['rest']}
    return set()


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


def collect_onsets_all_parts(motive, all_part_notes, mnum, part_names=None):
    """
    Collect unique note onset offsets (quarter-note) for one measure,
    scanning ALL parts.  Returns a sorted list of (act_off, deact_off, instruments) tuples.
    deact_off = act_off + 0.25 (one 16th note pulse per onset).
    instruments is a comma-separated string of part names (empty string if part_names not given).

    M6: if any part has accented 16th notes in this measure, only use
    accented-16th onsets from all parts; otherwise use all non-rest onsets.

    Solo parts (P18/P19/P20) are excluded when the measure falls within any
    M10/M11/M12 block.
    """
    exclude_solos = mnum in SOLO_MUTE_MEASURES

    # Gather all candidate notes from every part for this measure, keyed by pid
    notes_by_pid = {}
    for pid, part_notes in all_part_notes.items():
        if exclude_solos and pid in SOLO_PARTS:
            continue
        notes = [n for n in part_notes.get(mnum, []) if not n['rest'] and not n['tie_cont']]
        if notes:
            notes_by_pid[pid] = notes

    all_notes_flat = [n for notes in notes_by_pid.values() for n in notes]
    if not all_notes_flat:
        return []

    SIMPLE_PATTERN_FN = {
        'M1': _m1_offsets,
        'M3': _m3_offsets,
        'M7': _m7_offsets,
        'M9': _m9_offsets,
    }

    if motive in SIMPLE_PATTERN_FN:
        fn = SIMPLE_PATTERN_FN[motive]
        matching_pids = {}  # pid -> offsets from that part
        for pid, part_notes in all_part_notes.items():
            if exclude_solos and pid in SOLO_PARTS:
                continue
            offs = fn(part_notes.get(mnum, []))
            if offs:
                matching_pids[pid] = offs
        if not matching_pids:
            return []
        notes_by_pid = {pid: [n for n in notes_by_pid.get(pid, []) if n['offset'] in matching_pids[pid]]
                        for pid in matching_pids}
        notes_by_pid = {pid: n for pid, n in notes_by_pid.items() if n}

    if motive == 'M2':
        matching_pids = set()
        for pid, part_notes in all_part_notes.items():
            if exclude_solos and pid in SOLO_PARTS:
                continue
            cur_full  = part_notes.get(mnum, [])
            prev_full = part_notes.get(mnum - 1, [])
            if _m2_detect_pattern(cur_full) or _m2_detect_pattern(prev_full):
                matching_pids.add(pid)
        if not matching_pids:
            return []
        notes_by_pid = {pid: notes for pid, notes in notes_by_pid.items() if pid in matching_pids}
        notes_by_pid = {pid: n for pid, n in notes_by_pid.items() if n}
        if not notes_by_pid:
            return []

    if motive == 'M6':
        if mnum in M6_VIOLIN_BARS:
            # Trigger on every Violin I note
            notes_by_pid = {pid: n for pid, n in notes_by_pid.items() if pid == 'P21'}
        elif mnum in M6_FLUTE_BARS:
            # Trigger on every Flute note (Flute 1 + Flute 2)
            notes_by_pid = {pid: n for pid, n in notes_by_pid.items() if pid in ('P1', 'P2')}
        elif mnum in M6_SOPRANO_SAX_BARS:
            # Trigger on every Solo Soprano Sax note
            notes_by_pid = {pid: n for pid, n in notes_by_pid.items() if pid == 'P18'}
        else:
            # Pattern detection: percussion takes precedence; fallback to all parts.
            # Priority within each group: P3 > P2 > P1.
            full_by_pid = {}
            for pid, part_notes in all_part_notes.items():
                if exclude_solos and pid in SOLO_PARTS:
                    continue
                full = part_notes.get(mnum, [])
                if full:
                    full_by_pid[pid] = full

            perc_by_pid = {pid: notes for pid, notes in full_by_pid.items()
                           if pid in PERCUSSION_PARTS}

            def _pick_m6(candidate_pids):
                """Apply P3>P2>P1 priority over the given pid→notes dict."""
                p3 = {pid: _m6_p3_offsets(candidate_pids[pid]) for pid in candidate_pids}
                p2 = {pid: _m6_p2_offsets(candidate_pids[pid]) for pid in candidate_pids}
                p1 = {pid: _m6_p1_offsets(candidate_pids[pid]) for pid in candidate_pids}
                for by_pid in (p3, p2, p1):
                    offs = set().union(*by_pid.values()) if by_pid else set()
                    if offs:
                        return offs, {pid for pid, o in by_pid.items() if o}
                return set(), set()

            active_offs, matching_pids = _pick_m6(perc_by_pid)
            if not active_offs:
                active_offs, matching_pids = _pick_m6(full_by_pid)
            if not active_offs:
                return []

            notes_by_pid = {
                pid: [n for n in notes if n['offset'] in active_offs]
                for pid, notes in notes_by_pid.items()
                if pid in matching_pids
            }
            notes_by_pid = {pid: n for pid, n in notes_by_pid.items() if n}

    # Build {offset: [part_name, ...]} and {offset: max_dur} maps
    onset_parts = {}
    onset_dur   = {}
    for pid, notes in notes_by_pid.items():
        name = part_names.get(pid, pid) if part_names else ''
        for n in notes:
            off = n['offset']
            onset_parts.setdefault(off, []).append(name)
            if off not in onset_dur or n['dur'] > onset_dur[off]:
                onset_dur[off] = n['dur']

    unique_offsets = sorted(onset_parts)
    result = []
    for i, off in enumerate(unique_offsets):
        deact_off = off + onset_dur.get(off, 0.25)
        instruments = ', '.join(sorted(set(onset_parts[off]))) if part_names else ''
        result.append((off, deact_off, instruments))
    return result


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

        if retrigger and RETRIGGER_IGNORE_BLOCKS:
            for mnum in range(1, NUM_MEASURES + 1):
                onsets = collect_onsets_all_parts(motive, all_part_notes, mnum)
                beats_in_bar = bar_beats.get(mnum, 4)
                for act_off, deact_off, _ in onsets:
                    a_beat, a_subdiv = offset_to_beat_subdiv(act_off)
                    add(mnum, a_beat, a_subdiv, 'activate', key)
                    if deact_off >= beats_in_bar:
                        add(mnum + 1, 1, 0, 'deactivate', key)
                    else:
                        d_beat, d_subdiv = offset_to_beat_subdiv(deact_off)
                        add(mnum, d_beat, d_subdiv, 'deactivate', key)
            continue

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

                for act_off, deact_off, _ in onsets:
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

def build_csv_rows(all_part_notes, bar_beats, part_names):
    """
    One row per trigger/release event (matches movement2_motives.csv format).
    beat_start/beat_end are 1-indexed (beat 1 = 1.0, beat 1+16th = 1.25, etc.).
    Retrigger motives: one row per note onset.
    Sustained motives: one row per block.
    """
    rows = []
    for motive, blocks in BLOCKS.items():
        retrigger = motive in RETRIGGER_MOTIVES

        if retrigger and RETRIGGER_IGNORE_BLOCKS:
            for mnum in range(1, NUM_MEASURES + 1):
                onsets = collect_onsets_all_parts(motive, all_part_notes, mnum, part_names)
                beats_in_bar = bar_beats.get(mnum, 4)
                for act_off, deact_off, instruments in onsets:
                    if deact_off >= beats_in_bar:
                        r_bar, r_beat = mnum + 1, 1.0
                    else:
                        r_bar, r_beat = mnum, deact_off + 1.0
                    rows.append({
                        'measure_start': mnum,  'beat_start': act_off + 1.0,
                        'measure_end':   r_bar, 'beat_end':   r_beat,
                        'motive': motive, 'instruments': instruments,
                    })
            continue

        for start_m, end_m in blocks:
            at_last    = (end_m >= NUM_MEASURES)
            deact_bar  = end_m     if at_last else end_m + 1
            deact_beat = 4.0       if at_last else 1.0  # beat 4 or beat 1 of next bar

            if not retrigger:
                rows.append({
                    'measure_start': start_m,  'beat_start': 1.0,
                    'measure_end':   deact_bar, 'beat_end':   deact_beat,
                    'motive': motive, 'instruments': '',
                })
                continue

            retrig_last = end_m if RETRIGGER_END_BAR is None else min(end_m, RETRIGGER_END_BAR - 1)
            for mnum in range(start_m, retrig_last + 1):
                onsets = collect_onsets_all_parts(motive, all_part_notes, mnum, part_names)
                beats_in_bar = bar_beats.get(mnum, 4)
                for act_off, deact_off, instruments in onsets:
                    if deact_off >= beats_in_bar:
                        r_bar, r_beat = mnum + 1, 1.0
                    else:
                        r_bar, r_beat = mnum, deact_off + 1.0  # 1-indexed
                    rows.append({
                        'measure_start': mnum,  'beat_start': act_off + 1.0,
                        'measure_end':   r_bar, 'beat_end':   r_beat,
                        'motive': motive, 'instruments': instruments,
                    })

    rows.sort(key=lambda r: (r['measure_start'], r['beat_start'], r['motive']))
    return rows


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
    ET.SubElement(n, 'type').text = note_type
    ET.SubElement(n, 'staff').text = staff
    return n


def make_backup_xml(duration):
    b = ET.Element('backup')
    ET.SubElement(b, 'duration').text = str(duration)
    return b


def dur_to_note_type(dur_ticks, div):
    """Convert a tick duration to (note_type, dots)."""
    ratio = dur_ticks / div
    for r, t, d in [(4,'whole',0),(3,'half',1),(2,'half',0),(1.5,'quarter',1),
                    (1,'quarter',0),(0.75,'eighth',1),(0.5,'eighth',0),
                    (0.375,'16th',1),(0.25,'16th',0)]:
        if abs(ratio - r) < 0.01:
            return t, d
    return 'quarter', 0


def ticks_to_rests(ticks, div, voice, staff):
    """Fill a tick count with the fewest rest elements (greedy, largest first)."""
    rests = []
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
                rests.append(make_rest_xml(dur, ntype, voice, staff))
                remaining -= dur
                break
        else:
            break
    return rests


def build_note_sequence(step, octave, voice, staff, div, whole_dur, onsets):
    """
    Build note + rest elements for one retrigger voice in one measure.
    Note duration = time until next onset (or to end of bar for last note).
    Adds beaming for runs of 8th/16th notes in groups of 4.
    """
    if not onsets:
        return ticks_to_rests(whole_dur, div, voice, staff)

    # Convert to (act_tick, deact_tick) pairs using actual deact_off,
    # deduplicate by act_tick, clamp to bar end.
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

    # Build flat item list: (dur_ticks, note_type, dots, is_note)
    items = []
    current = 0
    for onset_tick, note_dur in note_ticks:
        gap = onset_tick - current
        if gap > 0:
            for rest_dur, rest_type in _greedy_split(gap, div):
                items.append((rest_dur, rest_type, 0, False))
                current += rest_dur
        ntype, ndots = dur_to_note_type(note_dur, div)
        items.append((note_dur, ntype, ndots, True))
        current = onset_tick + note_dur
    remaining = whole_dur - current
    if remaining > 0:
        for rest_dur, rest_type in _greedy_split(remaining, div):
            items.append((rest_dur, rest_type, 0, False))

    # Add beaming: scan runs of consecutive undotted notes of the same beamable type
    elements = []
    n = len(items)
    i = 0
    while i < n:
        dur, ntype, ndots, is_note = items[i]
        if not is_note or ntype not in ('eighth', '16th') or ndots:
            if is_note:
                elements.append(make_note_xml(step, octave, dur, voice, staff,
                                              note_type=ntype, dots=ndots))
            else:
                elements.append(make_rest_xml(dur, ntype, voice, staff))
            i += 1
            continue

        # Collect the full run of undotted notes of this type
        run_start = i
        while i < n and items[i][3] and items[i][1] == ntype and not items[i][2]:
            i += 1
        run = items[run_start:i]
        beam_levels = 2 if ntype == '16th' else 1
        group_size  = 4

        for g_start in range(0, len(run), group_size):
            group = run[g_start:g_start + group_size]
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


def _greedy_split(ticks, div):
    """Return list of (dur_ticks, note_type) filling ticks, largest first."""
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


def write_ep_part(ep_part, num_measures, all_part_notes, bar_beats):
    measure_active = {i: [] for i in range(1, num_measures + 1)}
    for motive, blocks in BLOCKS.items():
        if RETRIGGER_IGNORE_BLOCKS and motive in RETRIGGER_MOTIVES:
            for mn in range(1, num_measures + 1):
                measure_active[mn].append((motive, True, True))
            continue
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
        for tag in ('note', 'backup', 'forward'):
            for el in list(m.findall(tag)):
                m.remove(el)

        active = measure_active.get(mn, [])
        if not active and mn not in SCENE_NEXT_MEASURES:
            continue

        div          = div_by_measure.get(mn, 4)
        beats_in_bar = bar_beats.get(mn, 4)
        whole_dur    = div * beats_in_bar

        voice_blocks = []  # list of element lists, one per active motive

        for motive, is_first, is_last in active:
            step, octave = MOTIVE_PITCH[motive]
            voice, staff = MOTIVE_VOICE_STAFF[motive]

            if motive not in RETRIGGER_MOTIVES:
                # Sustained: whole note (tied across block)
                ntype, ndots = dur_to_note_type(whole_dur, div)
                elems = [make_note_xml(step, octave, whole_dur, voice, staff,
                                       note_type=ntype, dots=ndots,
                                       tie_start=not is_last, tie_stop=not is_first)]
            else:
                # Retrigger: actual note durations with beaming
                onsets = collect_onsets_all_parts(motive, all_part_notes, mn)
                if not onsets:
                    continue  # nothing to write for this motive in this bar
                elems = build_note_sequence(step, octave, voice, staff,
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


def main():
    tree = ET.parse(INPUT)
    root = tree.getroot()

    # Parse all parts once (shared by CSV and score.json)
    all_part_notes = {
        part.get('id'): parse_part_notes(root, part.get('id'))
        for part in root.findall('part')
        if part.get('id') != 'P26'
    }

    # Build part name lookup
    part_names = {
        sp.get('id'): sp.findtext('part-name') or sp.get('id')
        for sp in root.findall('.//score-part')
    }

    # Load bar_beats from score.json
    with open(SCORE_JSON) as f:
        score = json.load(f)
    mvt3 = next(m for m in score['movements'] if m['name'] == 'Movement III')
    bar_beats = {bar['bar']: bar['beats'] for bar in mvt3['bars']}

    rows = build_csv_rows(all_part_notes, bar_beats, part_names)
    with open(CSV_OUT, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['measure_start','beat_start',
                                          'measure_end','beat_end','motive','instruments'])
        w.writeheader()
        w.writerows(rows)
    print(f'Written {len(rows)} rows to {CSV_OUT}')

    ep_part = root.find('.//part[@id="P26"]')
    if ep_part is None:
        print('ERROR: EP part P26 not found')
        return
    write_ep_part(ep_part, NUM_MEASURES, all_part_notes, bar_beats)
    tree.write(OUTPUT, encoding='unicode', xml_declaration=True)
    print(f'Written annotated score to {OUTPUT}')

    write_score_json()


if __name__ == '__main__':
    main()
