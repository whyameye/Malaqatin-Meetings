#!/usr/bin/env python3
"""
Generate Electric Piano (P26) motive notes for Movement II.

Scans all non-EP parts and writes motive indicator notes into P26:
  M1 = C3  : 2+ consecutive half notes (no rest between)
  M2 = D3  : exactly 2 16th notes followed by a longer note; hold to rest
  M3 = E4  : pizz notes; match each note's duration; stop at arco
  M4 = F4  : 5+ slurred 16th notes; hold to rest
  M5 = G3  : 8th note slurred to longer note; hold to rest
  M6 = A3  : repeated/alternating (1-2 pitches) 16ths or tremolo; hold to run end

Also writes a CSV: measure_start, beat_start, measure_end, beat_end, motive
"""

import xml.etree.ElementTree as ET
import csv
from collections import defaultdict

INPUT  = 'Edited 2 Malaqatin Meetings - Full score - 01 Movement II Final.musicxml'
OUTPUT = 'Edited 2 Malaqatin Meetings - Full score - 01 Movement II Final - John.musicxml'
CSV_OUT = 'movement2_motives.csv'

EP_PART = 'P26'
COMMON_DIV = 4   # internal ticks per quarter note (normalize everything to this)

# Measures to IGNORE for each solo part (M7/M8/M9 solo sections)
SOLO_IGNORE = {
    'P20': set(range(34, 43)),   # M7: measures 34-42
    'P18': set(range(44, 53)),   # M8: measures 44-52
    'P19': set(range(54, 70)),   # M9: measures 54-69
}

# M5-specific exclusions (per-part measure ranges where M5 should not fire)
M5_PART_IGNORE = {
    'P19': set(range(1, 200)),   # SoloVln never triggers M5
    'P18': set(range(88, 93)),   # S.Sax: no M5 in m88-92
}
# Bass/inner voices excluded from M5 step-down rule
M5_STEPDOWN_EXCLUDE = {'P6', 'P23', 'P24', 'P25'}

# M4: Fl/Cl excluded entirely — their 32-note runs are M6, not M4
M4_EXCLUDE_PARTS = {'P1', 'P2', 'P4', 'P5'}

# Semitone map for pitch comparison in M5 step-down rule
_STEP_SEMI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

def _pitch_semi(n):
    return _STEP_SEMI.get(n['step'], 0) + n['octave'] * 12 + int(n.get('alter', 0) or 0)

MOTIVE_PITCH = {
    'M1': ('C', 3), 'M2': ('D', 3),
    'M3': ('E', 4), 'M4': ('F', 4),
    'M5': ('G', 3), 'M6': ('A', 3),
    'M7': ('B', 4), 'M8': ('A', 4), 'M9': ('G', 4),
}
# Voice and staff for each motive in P26
MOTIVE_VOICE_STAFF = {
    'M3': ('1', '1'), 'M4': ('2', '1'),
    'M7': ('3', '1'), 'M8': ('4', '1'), 'M9': ('5', '1'),
    'M1': ('6', '2'), 'M2': ('7', '2'),
    'M5': ('8', '2'), 'M6': ('9', '2'),
}
# Order for writing voices in each measure
VOICE_ORDER = ['M3', 'M4', 'M7', 'M8', 'M9', 'M1', 'M2', 'M5', 'M6']

# Note values in COMMON_DIV ticks (greedy decomposition, largest first)
NOTE_VALUES = [
    (16, 'whole',   False),
    (12, 'half',    True),
    ( 8, 'half',    False),
    ( 6, 'quarter', True),
    ( 4, 'quarter', False),
    ( 3, 'eighth',  True),
    ( 2, 'eighth',  False),
    ( 1, '16th',    False),
]

# ─── Measure info ────────────────────────────────────────────────────────────

def get_measure_info(root):
    """Build measure timeline from first part. Returns dict[mnum → info]."""
    first_part = root.find('part')
    cur_div = 4
    beats = 4
    beat_type = 4
    info = {}
    tick = 0
    for m in first_part.findall('measure'):
        mnum = int(m.get('number'))
        attrs = m.find('attributes')
        if attrs is not None:
            de = attrs.find('divisions')
            if de is not None:
                cur_div = int(de.text)
            te = attrs.find('time')
            if te is not None:
                beats = int(te.find('beats').text)
                beat_type = int(te.find('beat-type').text)
        # Measure duration in COMMON_DIV ticks (independent of part divisions)
        dur = beats * COMMON_DIV * 4 // beat_type
        info[mnum] = {'start': tick, 'dur': dur, 'beats': beats, 'beat_type': beat_type}
        tick += dur
    return info

# ─── Note extraction ──────────────────────────────────────────────────────────

def extract_notes(part_el, measure_info):
    """
    Extract all note events from a part, normalized to COMMON_DIV ticks.
    Each note dict has: abs_tick, measure, offset, duration, step, octave, alter,
    note_type, is_rest, is_chord, slur_start, slur_stop, tie_start, tie_stop,
    tremolo, pizz.
    """
    notes = []
    cur_div = 4
    running_pizz = False  # persists across measures

    for m_el in part_el.findall('measure'):
        mnum = int(m_el.get('number'))
        if mnum not in measure_info:
            continue
        mstart = measure_info[mnum]['start']

        # ── Pre-scan: collect pizz/arco direction positions in this measure ──
        pizz_changes = []  # [(norm_pos_in_measure, is_pizz)]
        pre_pos = 0
        pre_div = cur_div
        for child in m_el:
            tag = child.tag
            if tag == 'attributes':
                de = child.find('divisions')
                if de is not None:
                    pre_div = int(de.text)
            elif tag == 'note':
                is_chord = child.find('chord') is not None
                if not is_chord:
                    raw = int(child.findtext('duration', '0'))
                    pre_pos += round(raw / pre_div * COMMON_DIV)
            elif tag == 'backup':
                raw = int(child.findtext('duration', '0'))
                pre_pos -= round(raw / pre_div * COMMON_DIV)
                pre_pos = max(0, pre_pos)
            elif tag == 'forward':
                raw = int(child.findtext('duration', '0'))
                pre_pos += round(raw / pre_div * COMMON_DIV)
            elif tag == 'direction':
                for dt in child.findall('direction-type'):
                    for w in dt.findall('words'):
                        if w.text:
                            txt = w.text.lower().strip()
                            if 'pizz' in txt:
                                pizz_changes.append((pre_pos, True))
                            elif 'arco' in txt:
                                pizz_changes.append((pre_pos, False))

        pizz_changes.sort()

        # ── Main scan ────────────────────────────────────────────────────────
        pos = 0
        last_onset_pos = 0

        for child in m_el:
            tag = child.tag
            if tag == 'attributes':
                de = child.find('divisions')
                if de is not None:
                    cur_div = int(de.text)
            elif tag == 'note':
                raw = int(child.findtext('duration', '0'))
                dur = round(raw / cur_div * COMMON_DIV)
                is_chord = child.find('chord') is not None
                is_rest = child.find('rest') is not None

                if not is_chord:
                    note_pos = pos
                    last_onset_pos = pos
                else:
                    note_pos = last_onset_pos

                # Determine pizz state at this note position
                note_pizz = running_pizz
                for chg_pos, chg_state in pizz_changes:
                    if chg_pos <= note_pos:
                        note_pizz = chg_state

                # Pitch
                step = octave = None
                alter = 0
                pitch_el = child.find('pitch')
                if pitch_el is not None:
                    step = pitch_el.findtext('step')
                    octave = int(pitch_el.findtext('octave'))
                    a = pitch_el.findtext('alter')
                    alter = int(float(a)) if a else 0

                note_type = child.findtext('type', '')

                # Slur / tremolo — a note may have multiple <notations> elements
                slur_start = slur_stop = tremolo = False
                for notations in child.findall('notations'):
                    for slur in notations.findall('slur'):
                        t = slur.get('type', '')
                        if t == 'start':
                            slur_start = True
                        elif t == 'stop':
                            slur_stop = True
                    if notations.find('.//tremolo') is not None:
                        tremolo = True

                tie_start = any(t.get('type') == 'start' for t in child.findall('tie'))
                tie_stop  = any(t.get('type') == 'stop'  for t in child.findall('tie'))

                notes.append({
                    'abs_tick':  mstart + note_pos,
                    'measure':   mnum,
                    'offset':    note_pos,
                    'duration':  dur,
                    'step':      step,
                    'octave':    octave,
                    'alter':     alter,
                    'note_type': note_type,
                    'is_rest':   is_rest,
                    'is_chord':  is_chord,
                    'slur_start': slur_start,
                    'slur_stop':  slur_stop,
                    'tie_start':  tie_start,
                    'tie_stop':   tie_stop,
                    'tremolo':    tremolo,
                    'pizz':       note_pizz,
                })

                if not is_chord:
                    pos += dur

            elif tag == 'backup':
                raw = int(child.findtext('duration', '0'))
                pos -= round(raw / cur_div * COMMON_DIV)
            elif tag == 'forward':
                raw = int(child.findtext('duration', '0'))
                pos += round(raw / cur_div * COMMON_DIV)

        # Update running pizz state for next measure
        for _, chg_state in pizz_changes:
            running_pizz = chg_state

    return notes

# ─── Helpers ─────────────────────────────────────────────────────────────────

def should_ignore(part_id, mnum):
    return mnum in SOLO_IGNORE.get(part_id, set())

def onset_seq(notes, mnum=None):
    """Return note-onset sequence (exclude chord and tie-stop notes).
    Optionally filter to a specific measure."""
    return [n for n in notes
            if not n['is_chord'] and not n['tie_stop']
            and (mnum is None or n['measure'] == mnum)]

def follow_tie_end(notes_full, note):
    """Follow a tie chain through the full notes list, return end tick of last tied note."""
    by_tick = {}
    for n in notes_full:
        by_tick.setdefault(n['abs_tick'], []).append(n)
    current = note
    while current.get('tie_start'):
        end_tick = current['abs_tick'] + current['duration']
        found = None
        for c in by_tick.get(end_tick, []):
            if (c.get('tie_stop') and not c.get('is_chord')
                    and c['step'] == current['step'] and c['octave'] == current['octave']):
                found = c
                break
        if not found:
            break
        current = found
    return current['abs_tick'] + current['duration']

def find_hold_end(notes_full, seq, from_idx):
    """Return end tick of the held note after from_idx: end of tie chain of last note before rest."""
    last_note = None
    for i in range(from_idx, len(seq)):
        if seq[i]['is_rest']:
            break
        last_note = seq[i]
    if last_note is None:
        return seq[from_idx]['abs_tick'] if from_idx < len(seq) else 0
    return follow_tie_end(notes_full, last_note)

# ─── Motive detectors ─────────────────────────────────────────────────────────

def detect_m7(measure_info):
    """B4 treble: solo cello section, m30 start to end of m42."""
    start = measure_info[30]['start']
    end   = measure_info[42]['start'] + measure_info[42]['dur']
    return [(start, end, 'M7', 'P20')]  # Solo Violoncello

def detect_m8(measure_info):
    """A4 treble: solo sax section, beat 4.5 of m43 to beginning of beat 3 of m52."""
    start = measure_info[43]['start'] + int(3.5 * COMMON_DIV)
    end   = measure_info[52]['start'] + 2 * COMMON_DIV
    return [(start, end, 'M8', 'P18')]  # Solo Soprano Saxophone

def detect_m9(measure_info):
    """G4 treble: solo violin section, beat 0.5 of m54 to end of m69."""
    start = measure_info[54]['start'] + int(0.5 * COMMON_DIV)
    end   = measure_info[69]['start'] + measure_info[69]['dur']
    return [(start, end, 'M9', 'P19')]  # Solo Violin

def detect_m1(notes_by_part):
    """C3: 2+ consecutive half notes with no rest between."""
    events = []
    for pid, notes in notes_by_part.items():
        seq = [n for n in notes if not n['is_chord'] and not n['tie_stop']
               and not should_ignore(pid, n['measure'])]
        run = []
        prev = None
        for n in seq:
            # slur-stop on same pitch = tied note across barline, skip it
            is_slur_tie = (n['slur_stop'] and prev is not None and not prev['is_rest']
                           and n['step'] == prev['step'] and n['octave'] == prev['octave'])
            if is_slur_tie:
                prev = n
                continue
            if not n['is_rest'] and n['note_type'] == 'half':
                run.append(n)
            else:
                if len(run) >= 2:
                    for rn in run:
                        events.append((rn['abs_tick'], rn['abs_tick'] + rn['duration'], 'M1', pid))
                run = [] if n['is_rest'] else []
                if not n['is_rest'] and n['note_type'] == 'half':
                    run.append(n)
            prev = n
        if len(run) >= 2:
            for rn in run:
                events.append((rn['abs_tick'], rn['abs_tick'] + rn['duration'], 'M1', pid))
    return events

def detect_m2(notes_by_part, part_busy=None):
    """D3: exactly 2 16th notes (different pitches) followed by longer note; hold to rest.
    Suppressed during all solo sections (M7/M8/M9).
    Suppressed for any part already triggering another motive at that tick."""
    solo_measures = set().union(*SOLO_IGNORE.values())
    # Additional per-part measure exclusions for M2
    M2_PART_IGNORE = {
        'P19': {19},             # m19 false-start; replaced by manual event at m18b3.25
        'P20': {16},             # SoloVc. m16: false positive, extends event into m17
        'P18': {90, 91, 95},    # m90/91 moved to m95 last 16th; m95 handled by manual event
    }
    part_busy = part_busy or {}
    # Manual events with corrected start times
    events = [
        (285, 352, 'M2', 'P19'),    # m18 beat4 2nd 16th -> m23 (was m19b0)
        (1503, 1568, 'M2', None),   # m95 last 16th -> m100 (was m90b0)
    ]
    for pid, notes in notes_by_part.items():
        busy = part_busy.get(pid, [])
        m2_ignore = M2_PART_IGNORE.get(pid, set())
        seq = [n for n in notes if not n['is_chord'] and not n['tie_stop']
               and not should_ignore(pid, n['measure'])
               and n['measure'] not in solo_measures
               and n['measure'] not in m2_ignore]
        for i in range(len(seq) - 2):
            n0, n1, n2 = seq[i], seq[i+1], seq[i+2]
            if n0['is_rest'] or n1['is_rest'] or n2['is_rest']:
                continue
            if n0['note_type'] != '16th' or n1['note_type'] != '16th':
                continue
            if n2['note_type'] == '16th':
                continue
            # Require different pitches
            if (n0['step'], n0['octave']) == (n1['step'], n1['octave']):
                continue
            # Skip if this part is already doing another motive at this tick
            tick = n0['abs_tick']
            if any(bs <= tick < be for bs, be in busy):
                continue
            end = find_hold_end(notes, seq, i + 2)
            events.append((n0['abs_tick'], end, 'M2', pid))
    return events

def detect_m3(notes_by_part):
    """E4: 8th or 16th note chords (2+ simultaneous notes from one instrument).
    Also includes all Violin I (P21) notes in measures 30-41."""
    events = []
    for pid, notes in notes_by_part.items():
        # Find all abs_ticks that have at least one <chord> note
        ticks_with_chord = {n['abs_tick'] for n in notes if n['is_chord']}
        for n in notes:
            if n['is_chord'] or n['tie_stop'] or n['is_rest']:
                continue
            if should_ignore(pid, n['measure']):
                continue
            # Violin I m30-41, Violin II m52-69: every note triggers M3
            if ((pid == 'P21' and 30 <= n['measure'] <= 41)
                    or (pid == 'P22' and 52 <= n['measure'] <= 69)):
                events.append((n['abs_tick'], n['abs_tick'] + n['duration'], 'M3', pid))
            # String section pizz backup m95-98: every note triggers M3
            elif (pid in {'P21', 'P22', 'P23', 'P24', 'P25'} and 95 <= n['measure'] <= 98):
                events.append((n['abs_tick'], n['abs_tick'] + n['duration'], 'M3', pid))
            elif (n['note_type'] in ('eighth', '16th')
                    and n['abs_tick'] in ticks_with_chord):
                events.append((n['abs_tick'], n['abs_tick'] + n['duration'], 'M3', pid))
    return events

def detect_m4(notes_by_part):
    """F4: 5+ slurred 16th notes; hold to rest after slur ends.
    Manual event for Solo Violin m71-74."""
    events = [
        (242, 264, 'M4', 'P20'),   # SoloVc. m16 beat1& (and of beat 1) -> m17b2
        (1112, 1176, 'M4', 'P19'), # SoloVln m71 beat 0 -> m75 beat 0
    ]
    for pid, notes in notes_by_part.items():
        # Keep tie_stop notes that also have slur_start — these start a new slur on a tied note
        seq = [n for n in notes if not n['is_chord']
               and (not n['tie_stop'] or n['slur_start'])
               and not should_ignore(pid, n['measure'])]
        i = 0
        while i < len(seq):
            n = seq[i]
            # Fl/Cl excluded from M4 — their 32-note runs are M6
            if pid in M4_EXCLUDE_PARTS:
                i += 1
                continue
            # Start of a slur on a 16th note
            if n['note_type'] == '16th' and not n['is_rest']:
                # Collect consecutive 16th notes
                slur_notes = [n]
                j = i + 1
                while j < len(seq):
                    nj = seq[j]
                    if nj['is_rest'] or nj['note_type'] != '16th':
                        break
                    slur_notes.append(nj)
                    if nj['slur_stop']:
                        j += 1
                        break
                    j += 1
                # Valid if >=5 notes AND at least one has a slur marking
                has_slur = any(sn['slur_start'] or sn['slur_stop'] for sn in slur_notes)
                if len(slur_notes) >= 5 and has_slur:
                    end = find_hold_end(notes, seq, j)
                    events.append((slur_notes[0]['abs_tick'], end, 'M4', pid))
                i = j
            else:
                i += 1
    return events

def detect_m5(notes_by_part):
    """G3: slide gesture. Two cases:
    A) 8th note with slur_start, pitch changes, n1 effective duration > 2 ticks.
    B) Step down 1-2 semitones after a rest, n0 not 16th, n1 effective duration > 2 ticks
       (melody instruments only — bass/inner voices excluded via M5_STEPDOWN_EXCLUDE).
    Both: measure >= 12. Per-part measure exclusions via M5_PART_IGNORE.
    Also includes manual Bsn events for m23-25 and m75-77.
    """
    # Manual Bsn events (bassoon enters after rest with step-down, not caught by rule)
    events = [
        (352, 448, 'M5', None),    # Bsn m23 beat 0 -> m29 beat 0
        (1176, 1272, 'M5', None),  # Bsn m75 beat 0 -> m81 beat 0
    ]
    for pid, notes in notes_by_part.items():
        m5_ignore = M5_PART_IGNORE.get(pid, set())
        seq = [n for n in notes if not n['is_chord'] and not n['tie_stop']
               and not should_ignore(pid, n['measure'])]
        for i in range(len(seq) - 1):
            n0, n1 = seq[i], seq[i+1]
            if n0['is_rest'] or n1['is_rest']:
                continue
            if n0['measure'] < 12 or n0['measure'] in m5_ignore:
                continue
            diff = _pitch_semi(n1) - _pitch_semi(n0)
            n1_eff = follow_tie_end(notes, n1) - n1['abs_tick']
            prev_is_rest = (i == 0 or seq[i - 1]['is_rest'])
            # Case A: slur-based slide (pitch must change, n1 must hold)
            case_a = (n0['note_type'] == 'eighth' and n0['slur_start']
                      and diff != 0 and n1_eff > 2)
            # Case B: step-down entry after rest (melody instruments only)
            case_b = (pid not in M5_STEPDOWN_EXCLUDE
                      and diff in (-1, -2) and n0['note_type'] != '16th'
                      and n1_eff > 2 and prev_is_rest)
            if case_a or case_b:
                end = find_hold_end(notes, seq, i + 1)
                events.append((n0['abs_tick'], end, 'M5', pid))
    return events

def detect_m6(notes_by_part):
    """A3: slurred 16th notes repeating 1 pitch (>=2 notes) or strictly alternating 2 pitches
    (>=3 notes, A-B-A minimum). Excludes pizz chord leaders (already M3). Includes tremolo.
    Manual events for m42-51 (Fl/Cl arpeggios not caught by 2-pitch rule)."""
    events = [
        (648, 808, 'M6', None),   # m42 beat 0 -> m52 beat 0 (Fl/Cl arpeggio runs)
    ]
    for pid, notes in notes_by_part.items():
        ticks_with_chord = {n['abs_tick'] for n in notes if n['is_chord']}
        seq = [n for n in notes if not n['is_chord'] and not n['tie_stop']
               and not should_ignore(pid, n['measure'])]

        # Tremolo notes (no chord exclusion — tremolo chords are valid M6)
        for n in seq:
            if n['tremolo'] and not n['is_rest']:
                events.append((n['abs_tick'], n['abs_tick'] + n['duration'], 'M6', pid))

        # Slurred repeated/alternating 16th note runs (exclude pizz chord leaders).
        # Run must use exactly 1 pitch (any length) or exactly 2 pitches alternating
        # (each consecutive pair differs — no same pitch twice in a row).
        sixteenths = [n for n in seq if not n['is_rest'] and n['note_type'] == '16th'
                      and n['abs_tick'] not in ticks_with_chord]
        i = 0
        while i < len(sixteenths):
            n = sixteenths[i]
            # Collect a slur group: start at slur_start, end at slur_stop
            if not n['slur_start']:
                i += 1
                continue
            run = [n]
            j = i + 1
            while j < len(sixteenths):
                run.append(sixteenths[j])
                if sixteenths[j]['slur_stop']:
                    j += 1
                    break
                j += 1
            # Check pitch restriction: 1 unique pitch, or 2 pitches strictly alternating
            pitches = [(r['step'], r['octave']) for r in run]
            unique = set(pitches)
            if len(unique) == 1:
                valid = len(run) >= 2
            elif len(unique) == 2:
                # Must alternate: no two consecutive notes have the same pitch
                valid = len(run) >= 3 and all(pitches[k] != pitches[k+1] for k in range(len(pitches)-1))
            else:
                valid = False
            if valid:
                events.append((run[0]['abs_tick'], run[-1]['abs_tick'] + run[-1]['duration'], 'M6', pid))
            i = j
    return events

# ─── Deduplication ────────────────────────────────────────────────────────────

def deduplicate(events):
    """Merge overlapping events of the same motive; keep one per unique start.
    Accepts 3-tuples (start, end, motive) or 4-tuples (start, end, motive, pid)."""
    by_motive = defaultdict(list)
    for ev in events:
        by_motive[ev[2]].append(ev)

    result = []
    for motive, mevs in by_motive.items():
        mevs.sort()
        merged = []
        for ev in mevs:
            start, end, m = ev[0], ev[1], ev[2]
            if merged and start < merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end), m)
            else:
                merged.append([start, end, m])
        result.extend(tuple(e) for e in merged)

    return result


def build_part_busy(events_4tuple):
    """Build {pid: [(start, end)]} from 4-tuple events for M2 conflict exclusion."""
    part_busy = defaultdict(list)
    for ev in events_4tuple:
        if len(ev) == 4 and ev[3] is not None:
            part_busy[ev[3]].append((ev[0], ev[1]))
    return dict(part_busy)

# ─── XML note generation ──────────────────────────────────────────────────────

def ticks_to_notes(ticks):
    """Decompose tick duration into list of (type_str, ticks, is_dotted)."""
    result = []
    remaining = ticks
    for dur, ntype, dotted in NOTE_VALUES:
        while remaining >= dur:
            result.append((ntype, dur, dotted))
            remaining -= dur
    return result

def make_note_el(step, octave, ntype, dur, voice, staff, is_dotted=False,
                 tie_start=False, tie_stop=False):
    note = ET.Element('note')
    pitch = ET.SubElement(note, 'pitch')
    ET.SubElement(pitch, 'step').text = step
    ET.SubElement(pitch, 'octave').text = str(octave)
    ET.SubElement(note, 'duration').text = str(dur)
    if tie_stop:
        ts = ET.SubElement(note, 'tie')
        ts.set('type', 'stop')
    if tie_start:
        ts = ET.SubElement(note, 'tie')
        ts.set('type', 'start')
    ET.SubElement(note, 'voice').text = str(voice)
    ET.SubElement(note, 'type').text = ntype
    if is_dotted:
        ET.SubElement(note, 'dot')
    # Stem direction: odd voice = up, even voice = down; whole notes have no stem
    if ntype != 'whole':
        stem = ET.SubElement(note, 'stem')
        stem.text = 'up' if int(voice) % 2 == 1 else 'down'
    ET.SubElement(note, 'staff').text = str(staff)
    if tie_stop or tie_start:
        notations = ET.SubElement(note, 'notations')
        if tie_stop:
            el = ET.SubElement(notations, 'tied')
            el.set('type', 'stop')
        if tie_start:
            el = ET.SubElement(notations, 'tied')
            el.set('type', 'start')
    return note


def add_beams(elements):
    """Add beam elements to consecutive beamable notes within the same beat."""
    # Collect non-chord notes with their measure positions
    items = []
    pos = 0
    for el in elements:
        if el.tag == 'note':
            is_chord = el.find('chord') is not None
            dur = int(el.findtext('duration', '0'))
            if not is_chord:
                is_rest = el.find('rest') is not None
                nt = el.findtext('type', '')
                items.append((el, pos, dur, nt, is_rest))
                pos += dur
        elif el.tag == 'backup':
            pos -= int(el.findtext('duration', '0'))
        elif el.tag == 'forward':
            pos += int(el.findtext('duration', '0'))

    BEAMABLE = {'eighth', '16th'}
    i = 0
    while i < len(items):
        el, p, d, nt, is_rest = items[i]
        if is_rest or nt not in BEAMABLE:
            i += 1
            continue
        beat = p // COMMON_DIV
        group = [(el, p, d, nt)]
        j = i + 1
        while j < len(items):
            el2, p2, d2, nt2, is_rest2 = items[j]
            if is_rest2 or nt2 not in BEAMABLE: break
            if p2 != group[-1][1] + group[-1][2]: break  # gap
            if p2 // COMMON_DIV != beat: break            # different beat
            group.append((el2, p2, d2, nt2))
            j += 1
        if len(group) >= 2:
            for k, (gel, gp, gd, gnt) in enumerate(group):
                b = ET.SubElement(gel, 'beam')
                b.set('number', '1')
                b.text = 'begin' if k == 0 else ('end' if k == len(group)-1 else 'continue')
                # Secondary beam for 16ths
                if gnt == '16th':
                    prev_16 = k > 0 and group[k-1][3] == '16th'
                    next_16 = k < len(group)-1 and group[k+1][3] == '16th'
                    if prev_16 or next_16:
                        b2 = ET.SubElement(gel, 'beam')
                        b2.set('number', '2')
                        b2.text = 'begin' if not prev_16 else ('end' if not next_16 else 'continue')
        i = j if len(group) >= 2 else i + 1

def make_rest_el(ntype, dur, voice, staff, is_dotted=False, full_measure=False):
    note = ET.Element('note')
    rest = ET.SubElement(note, 'rest')
    if full_measure:
        rest.set('measure', 'yes')
    ET.SubElement(note, 'duration').text = str(dur)
    ET.SubElement(note, 'voice').text = str(voice)
    if not full_measure:
        ET.SubElement(note, 'type').text = ntype
        if is_dotted:
            ET.SubElement(note, 'dot')
    ET.SubElement(note, 'staff').text = str(staff)
    return note

def make_backup_el(dur):
    b = ET.Element('backup')
    ET.SubElement(b, 'duration').text = str(dur)
    return b

def generate_voice_content(mstart, mdur, motive, events, voice, staff, step, octave):
    """
    Generate XML elements for one voice in one measure.
    events: all EP events for this motive (unclipped).
    Returns list of ET.Element.
    """
    m_end = mstart + mdur

    # Clip events to this measure and annotate is_first/is_last
    segments = []
    for ev_start, ev_end, _ in events:
        seg_start = max(ev_start, mstart) - mstart   # offset in measure
        seg_end   = min(ev_end,   m_end)  - mstart
        if seg_start >= seg_end:
            continue
        is_first = ev_start >= mstart   # event starts in this measure
        is_last  = ev_end   <= m_end    # event ends in this measure
        segments.append((seg_start, seg_end, is_first, is_last))

    segments.sort()

    elements = []
    pos = 0

    if not segments:
        # Whole-measure rest
        elements.append(make_rest_el('whole', mdur, voice, staff, full_measure=True))
        return elements

    for seg_start, seg_end, is_first, is_last in segments:
        # Rest before segment
        if seg_start > pos:
            for ntype, dur, dotted in ticks_to_notes(seg_start - pos):
                elements.append(make_rest_el(ntype, dur, voice, staff, dotted))
        # Note(s) for this segment
        parts = ticks_to_notes(seg_end - seg_start)
        for i, (ntype, dur, dotted) in enumerate(parts):
            is_fp = (i == 0)
            is_lp = (i == len(parts) - 1)
            t_stop  = (not is_first) if is_fp else True
            t_start = (not is_last)  if is_lp else True
            elements.append(make_note_el(step, octave, ntype, dur, voice, staff,
                                         dotted, t_start, t_stop))
        pos = seg_end

    # Rest after last segment
    if pos < mdur:
        for ntype, dur, dotted in ticks_to_notes(mdur - pos):
            elements.append(make_rest_el(ntype, dur, voice, staff, dotted))

    add_beams(elements)
    return elements

# ─── XML modification ─────────────────────────────────────────────────────────

def apply_to_xml(root, measure_info, events_by_motive):
    """Replace P26 measure content with generated EP notes."""
    ep_part = next(p for p in root.findall('part') if p.get('id') == EP_PART)

    for m_el in ep_part.findall('measure'):
        mnum = int(m_el.get('number'))
        if mnum not in measure_info:
            continue
        minfo = measure_info[mnum]
        mstart = minfo['start']
        mdur   = minfo['dur']

        # Remove existing note/backup/forward elements
        for child in [c for c in m_el if c.tag in ('note', 'backup', 'forward')]:
            m_el.remove(child)

        # Generate content for each voice
        first_voice = True
        for motive in VOICE_ORDER:
            voice, staff = MOTIVE_VOICE_STAFF[motive]
            step, octave = MOTIVE_PITCH[motive]
            evs = [(ev[0], ev[1], ev[2]) for ev in events_by_motive.get(motive, [])
                   if ev[0] < mstart + mdur and ev[1] > mstart]

            if not first_voice:
                m_el.append(make_backup_el(mdur))
            first_voice = False

            for el in generate_voice_content(mstart, mdur, motive, evs, voice, staff, step, octave):
                m_el.append(el)

# ─── CSV ──────────────────────────────────────────────────────────────────────

def tick_to_measure_beat(tick, measure_info):
    for mnum in sorted(measure_info):
        mi = measure_info[mnum]
        if mi['start'] <= tick < mi['start'] + mi['dur']:
            offset = tick - mi['start']
            beat = offset / COMMON_DIV
            return mnum, round(beat, 3)
    # At or past end of last measure
    last = max(measure_info)
    mi = measure_info[last]
    beat = (tick - mi['start']) / COMMON_DIV
    return last, round(beat, 3)

def shorten_name(name):
    """Abbreviate part names for CSV."""
    import re
    name = re.sub(r'(\s*\([^)]+\))+', '', name).strip()
    table = [
        ('Solo Soprano Saxophone', 'Sop Sax'),
        ('Solo Violin',            'Solo Vln'),
        ('Solo Violoncello',       'Solo Vc.'),
        ('Violin II',              'Vln II'),
        ('Violin I',               'Vln I'),
        ('Viola',                  'Vla.'),
        ('Violoncello',            'Vc.'),
        ('Contrabass',             'Cb.'),
        ('Double Bass',            'Cb.'),
        ('Flute 1',                'Fl. 1'),
        ('Flute 2',                'Fl. 2'),
        ('Oboe',                   'Ob.'),
        ('Bassoon',                'Bsn.'),
        ('Clarinet 1',             'Cl. 1'),
        ('Clarinet 2',             'Cl. 2'),
        ('Trumpet 1',              'Tpt. 1'),
        ('Trumpet 2',              'Tpt. 2'),
        ('Horn',                   'Hn.'),
        ('Trombone',               'Tbn.'),
        ('Vibraphone',             'Vib.'),
        ('Electric Piano',         'EP'),
    ]
    for full, short in table:
        if full in name:
            return short
    return name


def write_csv(events, measure_info, part_names=None, raw_events=None):
    part_names = part_names or {}
    raw4 = [ev for ev in (raw_events or events) if len(ev) == 4 and ev[3] is not None]

    rows = []
    for ev in sorted(events):
        start, end, motive = ev[0], ev[1], ev[2]
        ms, bs = tick_to_measure_beat(start, measure_info)
        me, be = tick_to_measure_beat(end, measure_info)
        pids = sorted({r[3] for r in raw4
                       if r[2] == motive and r[0] < end and r[1] > start})
        instruments = ', '.join(shorten_name(part_names.get(p, p)) for p in pids) if pids else ''
        rows.append((ms, bs, me, be, motive, instruments))
    rows.sort()
    with open(CSV_OUT, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['measure_start', 'beat_start', 'measure_end', 'beat_end', 'motive', 'instruments'])
        for row in rows:
            w.writerow(row)
    print(f'  CSV: {len(rows)} rows → {CSV_OUT}')

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print(f'Parsing {INPUT} ...')
    tree = ET.parse(INPUT)
    root = tree.getroot()

    measure_info = get_measure_info(root)
    print(f'  {len(measure_info)} measures')

    # Build part name map
    part_names = {}
    for sp in root.findall('.//score-part'):
        part_names[sp.get('id')] = sp.findtext('part-name', sp.get('id'))

    # Extract notes for all non-EP parts
    notes_by_part = {}
    for part_el in root.findall('part'):
        pid = part_el.get('id')
        if pid == EP_PART:
            continue
        notes_by_part[pid] = extract_notes(part_el, measure_info)
    print(f'  {len(notes_by_part)} non-EP parts parsed')

    # Detect motives — run M3/M4/M5/M6 first to build part_busy for M2 exclusion
    print('Detecting motives...')
    all_events = []
    raw_non_m2 = []
    for detect, label in [
        (detect_m1, 'M1'), (detect_m3, 'M3'),
        (detect_m4, 'M4'), (detect_m5, 'M5'), (detect_m6, 'M6'),
    ]:
        evs = detect(notes_by_part)
        raw_non_m2.extend(evs)
        evs = deduplicate(evs)
        print(f'  {label}: {len(evs)} events')
        all_events.extend(evs)

    part_busy = build_part_busy(raw_non_m2)
    raw_m2 = detect_m2(notes_by_part, part_busy)
    m2_evs = deduplicate(raw_m2)
    print(f'  M2: {len(m2_evs)} events')
    raw_non_m2.extend(raw_m2)
    all_events.extend(m2_evs)

    # Solo-section motives — independent, do not affect part_busy or any other motive
    for detect, label in [
        (detect_m7, 'M7'), (detect_m8, 'M8'), (detect_m9, 'M9'),
    ]:
        evs = detect(measure_info)
        print(f'  {label}: {len(evs)} events')
        all_events.extend(evs)

    # Group by motive for XML generation
    events_by_motive = defaultdict(list)
    for ev in all_events:
        events_by_motive[ev[2]].append(ev)

    # Apply to XML
    print('Writing EP part...')
    apply_to_xml(root, measure_info, events_by_motive)

    # Write CSV — deduplicated events for rows, raw events for instrument lookup
    write_csv(all_events, measure_info, part_names, raw_events=all_events)

    # Write output XML (preserve declaration)
    tree.write(OUTPUT, encoding='unicode', xml_declaration=False)
    # Prepend the standard MusicXML declaration
    with open(OUTPUT, 'r') as f:
        content = f.read()
    with open(OUTPUT, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(content)

    print(f'Done → {OUTPUT}')

if __name__ == '__main__':
    main()
