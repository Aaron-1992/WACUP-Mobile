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

    changes = _tempo_map(tracks)
    to_seconds = _tick_converter(changes, division)

    for track_index, events in enumerate(tracks):
        programs: Dict[int, int] = {}
        bends: Dict[int, float] = {}
        vibrato: Dict[int, float] = {}
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
            elif kind == 0xE0 and len(payload) >= 2:
                raw = (payload[1] << 7) | payload[0]
                bends[channel] = ((raw - 8192) / 8192.0) * 2.0     # +/- 2 semitones
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
            ))

    song.refresh_duration()
    if not song.notes:
        song.add_warning("the file parsed but contained no notes")
    return song


register("midi", LABEL)(read)
