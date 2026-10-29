"""Standard MIDI File importer (formats 0, 1 and 2, plus RIFF-wrapped RMID).

Tempo changes are honoured, the sustain pedal stretches notes, and pitch bend plus
CC1 vibrato are carried through so the arranger can imitate them.
"""

import struct
from typing import Dict, List, Tuple

from ..model import Note, Song
from . import register

EXTENSIONS = (".mid", ".midi", ".rmi", ".kar")
LABEL = "MIDI (Standard MIDI File)"


def _vlq(data: bytes, pos: int) -> Tuple[int, int]:
    value = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos
    return value, pos


def _chunks(data: bytes):
    pos = 0
    while pos + 8 <= len(data):
        kind = data[pos:pos + 4]
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + length]
        yield kind, body
        pos += 8 + length


def _rmid_to_smf(data: bytes) -> bytes:
    """Unwrap RIFF/RMID containers down to the embedded SMF."""
    pos = 12
    while pos + 8 <= len(data):
        kind = data[pos:pos + 4]
        length = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if kind == b"data":
            return data[pos + 8:pos + 8 + length]
        pos += 8 + length + (length & 1)
    return data


def _parse_track(body: bytes):
    """Returns [(absolute_tick, status_byte, payload_list)]."""
    pos = 0
    tick = 0
    running = 0
    events = []
    while pos < len(body):
        delta, pos = _vlq(body, pos)
        tick += delta
        if pos >= len(body):
            break
        status = body[pos]
        if status & 0x80:
            pos += 1
        else:
            status = running

        if status == 0xFF:
            if pos >= len(body):
                break
            meta_type = body[pos]
            pos += 1
            length, pos = _vlq(body, pos)
            payload = body[pos:pos + length]
            pos += length
            events.append((tick, 0xFF, [meta_type] + list(payload)))
            if meta_type == 0x2F:
                break
            continue

        if status in (0xF0, 0xF7):
            length, pos = _vlq(body, pos)
            pos += length
            events.append((tick, status, []))
            continue

        running = status
        kind = status & 0xF0
        count = 1 if kind in (0xC0, 0xD0) else 2
        payload = list(body[pos:pos + count])
        pos += count
        events.append((tick, status, payload))
    return events


_MAJOR = ["C", "G", "D", "A", "E", "B", "F#", "C#"]
_MINOR = ["A", "E", "B", "F#", "C#", "G#", "D#", "A#"]


def _key_name(sharps: int, minor: bool) -> str:
    names = _MINOR if minor else _MAJOR
    if -7 <= sharps <= 7:
        index = sharps if sharps >= 0 else sharps + 7
        table = names if sharps >= 0 else ["F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"]
        try:
            return "%s %s" % (table[index], "minor" if minor else "major")
        except IndexError:
            pass
    return ""


def _track_meta(events):
    """Name, patch and the first tempo/meter information in one track."""
    name = ""
    for _tick, status, payload in events:
        if status == 0xFF and payload:
            kind = payload[0]
            if kind == 0x03 and not name:                       # track name
                try:
                    name = bytes(payload[1:]).decode("latin-1").strip("\x00 ").strip()
                except Exception:
                    name = ""
    return name


def _tempo_map(tracks):
    changes = [(0, 500000)]
    for events in tracks:
        for tick, status, payload in events:
            if status == 0xFF and payload and payload[0] == 0x51 and len(payload) >= 4:
                tempo = (payload[1] << 16) | (payload[2] << 8) | payload[3]
                if tempo > 0:
                    changes.append((tick, tempo))
    changes.sort(key=lambda item: item[0])
    return changes


def _tick_converter(changes, division: int):
    if division & 0x8000:            # SMPTE timing
        fps = 256 - (division >> 8)
        ticks_per_frame = max(1, division & 0xFF)
        scale = 1.0 / (fps * ticks_per_frame)
        return lambda tick: tick * scale

    ticks_per_quarter = max(1, division)

    def convert(tick: int) -> float:
        seconds = 0.0
        last_tick = 0
        tempo = 500000
        for change_tick, change_tempo in changes:
            if change_tick <= last_tick:
                tempo = change_tempo
                continue
            if change_tick >= tick:
                break
            seconds += (change_tick - last_tick) / ticks_per_quarter * (tempo / 1e6)
            last_tick = change_tick
            tempo = change_tempo
        seconds += (tick - last_tick) / ticks_per_quarter * (tempo / 1e6)
        return seconds

    return convert


def read(path: str) -> Song:
    with open(path, "rb") as handle:
        data = handle.read()

    if data[:4] == b"RIFF":
        data = _rmid_to_smf(data)

    division = 480
    tracks: List[list] = []
    for kind, body in _chunks(data):
        if kind == b"MThd" and len(body) >= 6:
            _fmt, _ntrks, division = struct.unpack(">HHH", body[:6])
        elif kind == b"MTrk":
            tracks.append(_parse_track(body))

    song = Song(source_format="midi", source_path=path)
    if not tracks:
        song.add_warning("no MTrk chunks found; is this really a MIDI file?")
        return song

    # tempo, meter and track names: the things a musician reads off the page
    for events in tracks:
        name = _track_meta(events)
        song.track_names.append(name or "Track %d" % (len(song.track_names) + 1))
        for _tick, status, payload in events:
            if status != 0xFF or not payload:
                continue
            if payload[0] == 0x59 and len(payload) >= 3 and not song.key:
                sharps = payload[1] - 256 if payload[1] > 127 else payload[1]
                song.key = _key_name(sharps, payload[2] == 1)
            if payload[0] == 0x58 and len(payload) >= 3 and not song.meter:
                numerator, denominator = payload[1], 2 ** payload[2]
                song.meter = "%d/%d" % (numerator, denominator)
            if payload[0] == 0x51 and len(payload) >= 4 and not song.tempo:
                micros = (payload[1] << 16) | (payload[2] << 8) | payload[3]
                if micros:
                    song.tempo = 60_000_000.0 / micros

    changes = _tempo_map(tracks)
    to_seconds = _tick_converter(changes, division)

    for track_index, events in enumerate(tracks):
        programs: Dict[int, int] = {}
        bends: Dict[int, float] = {}
        vibrato: Dict[int, float] = {}
        volume: Dict[int, float] = {channel: 1.0 for channel in range(16)}
        expression: Dict[int, float] = {channel: 1.0 for channel in range(16)}
        bend_range: Dict[int, float] = {channel: 2.0 for channel in range(16)}
        rpn: Dict[int, tuple] = {}
        sounding: Dict[Tuple[int, int], dict] = {}
        finished: List[dict] = []

        def close(key, at_seconds):
            info = sounding.pop(key, None)
            if info is None:
                return
            info["end"] = max(info["start"] + 0.02, at_seconds)
            finished.append(info)

        for tick, status, payload in events:
            if status == 0xFF:
                continue
            seconds = to_seconds(tick)
            kind = status & 0xF0
            channel = status & 0x0F

            if kind == 0xC0 and payload:
                programs[channel] = payload[0]
            elif kind == 0xB0 and len(payload) >= 2:
                controller, value = payload[0], payload[1]
                if controller == 64 and value < 64:
                    for key in [k for k in sounding if k[0] == channel]:
                        close(key, seconds)
                elif controller == 1:
                    vibrato[channel] = (value / 127.0) * 0.5
                    for key, info in sounding.items():
                        if key[0] == channel:
                            info["vibrato"] = vibrato[channel]
                elif controller == 7:
                    volume[channel] = value / 127.0
                elif controller == 11:
                    expression[channel] = value / 127.0
                elif controller in (100, 101):                      # RPN select
                    rpn[channel] = (rpn.get(channel, (0, 0))[0], value) \
                        if controller == 100 else (value, rpn.get(channel, (0, 0))[1])
                elif controller == 6 and rpn.get(channel) == (0, 0):
                    bend_range[channel] = float(value or 2)         # semitones
            elif kind == 0xE0 and len(payload) >= 2:
                raw = (payload[1] << 7) | payload[0]
                bends[channel] = ((raw - 8192) / 8192.0) * bend_range.get(channel, 2.0)
                for key, info in sounding.items():
                    if key[0] == channel and abs(bends[channel]) > abs(info["bend"]):
                        info["bend"] = bends[channel]      # the peak, not the last value
            elif kind == 0x90 and len(payload) >= 2:
                number, velocity = payload[0], payload[1]
                key = (channel, number)
                if velocity == 0:
                    close(key, seconds)
                else:
                    if key in sounding:
                        close(key, seconds)        # retrigger
                    sounding[key] = {
                        "start": seconds,
                        "pitch": number,
                        "velocity": velocity,
                        "program": programs.get(channel, 0),
                        "bend": bends.get(channel, 0.0),
                        "vibrato": vibrato.get(channel, 0.0),
                        "drum": channel == 9,
                        "expression": volume.get(channel, 1.0)
                                      * expression.get(channel, 1.0),
                    }
            elif kind == 0x80 and len(payload) >= 2:
                close((channel, payload[0]), seconds)

        end_seconds = to_seconds(events[-1][0]) if events else 0.0
        for key in list(sounding):
            close(key, end_seconds)

        for info in finished:
            song.notes.append(Note(
                start=info["start"],
                dur=max(0.02, info["end"] - info["start"]),
                pitch=info["pitch"],
                velocity=info["velocity"],
                part=track_index,
                role="drum" if info["drum"] else "melody",
                program=info["program"],
                vibrato=info["vibrato"],
                bend=info["bend"],
                expression=max(0.0, min(1.0, info.get("expression", 1.0))),
                track_name=(song.track_names[track_index]
                            if track_index < len(song.track_names) else ""),
            ))

    song.refresh_duration()
    if not song.notes:
        song.add_warning("the file parsed but contained no notes")
    return song


register("midi", LABEL)(read)
