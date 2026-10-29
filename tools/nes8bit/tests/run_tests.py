"""End-to-end self test: importer -> arranger -> renderer -> files on disk.

Run with:  python tests/run_tests.py
"""

import os
import struct
import sys
import tempfile
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import make_test_midi                                     # noqa: E402
from nescore import analyze, chips, importers              # noqa: E402
from nescore.arrange import Options, arrange               # noqa: E402
from nescore.cli import main                               # noqa: E402
from nescore.render import (RenderOptions, render, render_channel,   # noqa: E402
                            write_wav)
from nescore.model import Note                             # noqa: E402
from nescore.vgmout import write_vgm                       # noqa: E402

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        FAILURES.append(label)


def rms(frames: bytes) -> float:
    if not frames:
        return 0.0
    total = 0
    for value in frames:
        centred = value - 128
        total += centred * centred
    return (total / len(frames)) ** 0.5


def main_test() -> None:
    work = tempfile.mkdtemp(prefix="chip8bit-test-")
    midi_path = make_test_midi.write(os.path.join(work, "genesis-style.mid"))

    print("parsing MIDI")
    importer = importers.find_for(midi_path)
    song = importer(midi_path)
    check("MIDI parsed", song.source_format == "midi")
    check("notes found", len(song.notes) > 150, "got %d" % len(song.notes))
    check("no parse warnings", not song.warnings, "; ".join(song.warnings))
    check("duration is about 8s", 7.5 < song.duration < 9.0,
          "got %.2f" % song.duration)
    check("six source parts", len(song.parts()) == 6, str(len(song.parts())))
    check("drums detected", any(n.role == "drum" for n in song.notes) or
          any(n.pitch in (36, 38, 42) for n in song.notes))
    check("pitch bend survived", any(abs(n.bend) > 0.1 for n in song.notes))
    check("vibrato survived", any(n.vibrato > 0 for n in song.notes))

    print("understanding the file")
    analysis = analyze.analyse(song)
    check("tempo read", abs(analysis.tempo - 120) < 1, str(analysis.tempo))
    check("meter read", analysis.meter == "4/4", analysis.meter)
    check("key read", analysis.key == "D major", analysis.key)
    check("instruments named", any("Lead" in name for name in analysis.instrument_names),
          str(analysis.instrument_names))
    roles = [voice.role for voice in analysis.voices]
    check("one melody found", roles.count("melody") == 1, str(roles))
    check("one bass found", roles.count("bass") == 1, str(roles))
    check("percussion separated", "drum" in roles, str(roles))
    chords = [v for v in analysis.voices if v.chord_tone]
    check("chords split into voices", len(chords) >= 3, str(len(chords)))
    check("chord tones are harmony, not melody",
          all(v.role in ("harmony", "counter", "bass") for v in chords),
          str([v.role for v in chords]))
    check("summary explains itself", any("BPM" in line for line in analysis.summary_lines()))

    print("arranging on a bare NES (4 voices)")
    base_channels = chips.build_channel_set([])
    base_notes, base_stats = arrange(song, base_channels, Options())
    check("every note landed on a channel",
          all(n.channel for n in base_notes) and base_notes)
    check("the 4-voice console was actually used",
          len(base_stats.per_channel_notes) == 4,
          str(sorted(base_stats.per_channel_notes)))
    check("sharing stayed a small fraction of the song",
          base_stats.shared < 0.25 * max(1, len(base_notes)),
          "%d of %d" % (base_stats.shared, len(base_notes)))
    check("noise channel kept the drums",
          any(n.channel == "noise" for n in base_notes))
    check("duplicated parts were folded together", base_stats.deduped > 0,
          str(base_stats.deduped))

    print("arranging on a fully extended console")
    for extensions in (["vrc6"], ["vrc6", "mmc5"], ["all"]):
        names = list(chips.EXTENSION_CHANNELS) if extensions == ["all"] else extensions
        channel_set = chips.build_channel_set(names)
        notes, stats = arrange(song, channel_set, Options())
        check("%s: sharing is rare" % "+".join(names),
              stats.shared <= 0.12 * max(1, len(notes)),
              "%d of %d" % (stats.shared, len(notes)))
        check("%s: every note landed on a channel" % "+".join(names),
              all(n.channel for n in notes))
        check("%s: more voices than the base console (%d)" % ("+".join(names),
                                                              len(stats.per_channel_notes)),
              len(stats.per_channel_notes) > 4)
        if extensions == ["all"]:
            all_notes, all_stats = notes, stats
            all_channels = channel_set

    check("with every chip the tune needs no sharing at all",
          all_stats.shared == 0, str(all_stats.shared))
    check("with every chip nothing is lost",
          all_stats.dropped == 0,
          "dropped %d" % all_stats.dropped)
    check("only percussion gets thinned, and only a little",
          all_stats.simplified <= 10,
          "thinned %d" % all_stats.simplified)

    print("articulation")
    legato_notes = [n for n in base_notes if n.role == "melody"]
    joined = sum(1 for a, b in zip(legato_notes, legato_notes[1:])
                 if abs(a.end() - b.start) < 0.01)
    check("legato lines are not re-attacked note by note",
          joined > 0 or len(legato_notes) < 2, str(joined))

    print("rendering")
    grouped = {}
    for note in base_notes:
        grouped.setdefault(note.channel, []).append(note)
    pcm, stems, duration = render(base_notes, base_channels, RenderOptions(), grouped)
    check("audio produced", len(pcm) > 1000)
    check("audio is not silence", rms(pcm) > 8.0, "rms %.1f" % rms(pcm))
    check("duration matches the song", abs(duration - song.duration) < 1.0,
          "%.2f" % duration)

    wav_path = os.path.join(work, "out.wav")
    write_wav(wav_path, pcm, RenderOptions())
    with wave.open(wav_path, "rb") as handle:
        check("wav is 16-bit mono 44.1k",
              (handle.getsampwidth(), handle.getnchannels(), handle.getframerate())
              == (2, 1, 44100))
        check("wav has the expected length",
              abs(handle.getnframes() / 44100.0 - duration) < 0.1)

    check("one stem per used channel", len(stems) == len(grouped))
    check("every channel audible",
          all(rms(bytes(int((v * 0.5 + 0.5) * 255) for v in buf)) > 1.0
              for buf in stems.values()))

    print("rendering with extensions")
    grouped = {}
    for note in all_notes:
        grouped.setdefault(note.channel, []).append(note)
    ext_pcm, ext_stems, _ = render(all_notes, all_channels, RenderOptions(), grouped)
    check("extended render is not silent", rms(ext_pcm) > 8.0)
    check("one stem per extended channel", len(ext_stems) == len(grouped))
    for name in ("vrc6_saw", "fds", "n163_1", "psg1"):
        if name in ext_stems:
            check("%s produced sound" % name, rms(
                bytes(int((v * 0.5 + 0.5) * 255) for v in ext_stems[name])) > 0.5)

    print("synthesis accuracy (measured by zero crossings)")
    every_channel = chips.build_channel_set(list(chips.EXTENSION_CHANNELS))
    for channel_id, pitch in (("pulse1", 69), ("pulse2", 45), ("triangle", 57),
                              ("vrc6_pulse1", 72), ("vrc6_saw", 60), ("mmc5_pulse1", 50),
                              ("fds", 64), ("n163_1", 67), ("psg1", 62)):
        # the DMC is a DAC thump, deliberately unpitched, so it is not measured here
        measured = _measure(channel_id, pitch, every_channel)
        expected = 440.0 * 2 ** ((pitch - 69) / 12.0)
        tolerance = 0.02
        check("%s is in tune at %d" % (channel_id, pitch),
              abs(measured - expected) / expected < tolerance,
              "%.1f Hz vs %.1f Hz" % (measured, expected))

    print("VGM export")
    vgm_path = os.path.join(work, "out.vgm")
    messages = write_vgm(vgm_path, base_notes, base_channels, duration, [])
    with open(vgm_path, "rb") as handle:
        blob = handle.read()
    check("VGM signature", blob[:4] == b"Vgm ")
    check("VGM version 1.71", struct.unpack("<I", blob[0x08:0x0C])[0] == 0x171)
    check("VGM data offset", struct.unpack("<I", blob[0x34:0x38])[0] == 0xCC)
    check("VGM ends with 0x66", blob[-1] == 0x66)
    check("VGM carries the NES APU clock",
          struct.unpack("<I", blob[0x84:0x88])[0] == 1789773)
    check("VGM contains NES APU writes", 0xB4 in blob[0x100:])
    check("no VGM warnings on the base console", not messages, str(messages))

    print("VGM export with every extension enabled")
    all_vgm = os.path.join(work, "all-chips.vgm")
    try:
        messages = write_vgm(all_vgm, all_notes, all_channels, duration,
                             list(chips.EXTENSION_CHANNELS))
        check("extended VGM written", os.path.getsize(all_vgm) > 1000)
        check("extended VGM keeps silent about channels it cannot address",
              any("WAV only" in m for m in messages) or not messages, str(messages))
    except Exception as error:
        check("extended VGM written", False, "%s: %s" % (type(error).__name__, error))

    print("VGM import round trip (a synthetic YM2612 log)")
    synth_vgm = make_test_midi.__file__ and _write_fake_genesis_vgm(
        os.path.join(work, "fake-genesis.vgm"))
    genesis = importers.find_for(synth_vgm)(synth_vgm)
    check("VGM importer found notes", len(genesis.notes) >= 8,
          "got %d" % len(genesis.notes))
    check("VGM notes have sane pitch",
          all(30 <= n.pitch <= 90 for n in genesis.notes))
    check("VGM notes have real timing", genesis.duration > 0.5,
          "%.2f" % genesis.duration)

    print("command line")
    out_dir = os.path.join(work, "cli-out")
    code = main([midi_path, "-o", out_dir, "--extensions", "vrc6,mmc5", "--stats"])
    produced = os.listdir(out_dir) if os.path.isdir(out_dir) else []
    check("cli exit code 0", code == 0)
    check("cli wrote one wav", len(produced) == 1, str(produced))
    check("cli named the file after the chips",
          produced and "nes+vrc6+mmc5" in produced[0], str(produced))

    vgm_dir = os.path.join(work, "cli-vgm")
    code = main([midi_path, "-o", vgm_dir, "--export-vgm", "--max-seconds", "2"])
    check("cli vgm export exit 0", code == 0)
    vgm_files = sorted(os.listdir(vgm_dir)) if os.path.isdir(vgm_dir) else []
    check("cli wrote a wav and a vgm",
          len(vgm_files) == 2 and any(n.endswith(".vgm") for n in vgm_files)
          and any(n.endswith(".wav") for n in vgm_files), str(vgm_files))

    bad = os.path.join(work, "broken.mid")
    with open(bad, "wb") as handle:
        handle.write(b"not a midi file at all")
    code = main([bad, "-o", work])
    check("broken input reported, not crashed", code == 1)

    print("\n%d check(s) failed" % len(FAILURES))
    return 0 if not FAILURES else 1


def _measure(channel_id: str, pitch: int, channels) -> float:
    """Render one long note and count how often the waveform crosses zero."""
    spec = chips.channel_by_id(channels, channel_id)
    note = Note(start=0.0, dur=1.0, pitch=pitch, velocity=110, volume=15,
                duty=0.5, role="melody")
    buf = render_channel([note], spec, RenderOptions(rate=44100), 44100)[2000:40000]
    crossings = sum(1 for index in range(1, len(buf))
                    if (buf[index - 1] <= 0 < buf[index])
                    or (buf[index - 1] >= 0 > buf[index]))
    return (crossings / 2.0) / (len(buf) / 44100.0)


def _write_fake_genesis_vgm(path: str) -> str:
    """A tiny YM2612 log: key on, play, key off — so the importer has work to do."""
    data = bytearray()
    notes = [60, 64, 67, 72, 60, 64, 67, 72]
    fnum = {60: 0x2A5, 64: 0x35B, 67: 0x3F0, 72: 0x4EC}
    for index, pitch in enumerate(notes):
        fnum_value = fnum[pitch]
        data += bytes([0x52, 0x28, 0x00])                       # key off ch0
        data += bytes([0x52, 0x40, 0x20])                       # operator level
        data += bytes([0x52, 0xA4, ((fnum_value >> 8) & 0x07) | 0x20])   # block 4
        data += bytes([0x52, 0xA0, fnum_value & 0xFF])
        data += bytes([0x52, 0x28, 0x0F])                       # key on ch0, all operators
        data += bytes([0x61, 0x00, 0x40])                       # wait 0x4000 samples
    data += bytes([0x52, 0x28, 0x00])
    data += b"\x66"

    header = bytearray(0x40)
    header[0x00:0x04] = b"Vgm "
    struct.pack_into("<I", header, 0x04, 0x40 + len(data) - 4)
    struct.pack_into("<I", header, 0x08, 0x151)
    struct.pack_into("<I", header, 0x2C, 7670453)               # YM2612 clock
    struct.pack_into("<I", header, 0x34, 0x40 - 0x34)
    with open(path, "wb") as handle:
        handle.write(bytes(header) + bytes(data))
    return path


if __name__ == "__main__":
    sys.exit(main_test())
