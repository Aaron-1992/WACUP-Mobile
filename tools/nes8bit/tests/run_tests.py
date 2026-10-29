"""End-to-end self test: importer -> arranger -> renderer -> files on disk.

Run with:  python tests/run_tests.py
"""

import math
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
from nescore import mix as mix_module                     # noqa: E402
from nescore import samples as samples_module              # noqa: E402
from nescore import arrange as arrange_module             # noqa: E402
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

    print("a fast tune (226 BPM, 33 ms notes)")
    fast_path = make_test_midi.write_fast(os.path.join(work, "fast-tune.mid"))
    fast_song = importers.find_for(fast_path)(fast_path)
    fast_analysis = analyze.analyse(fast_song)
    check("fast tune parsed", len(fast_song.notes) > 300, str(len(fast_song.notes)))
    check("fast tempo read", abs(fast_analysis.tempo - 226) < 2,
          str(fast_analysis.tempo))
    short_notes = [n for n in fast_song.notes if n.dur < 0.04]
    check("the file really is full of tiny notes", len(short_notes) > 40,
          str(len(short_notes)))

    fast_notes, fast_stats = arrange(fast_song, base_channels, Options(),
                                     analysis=fast_analysis)
    fast_melody = [n for n in fast_notes if n.role == "melody"]
    wanted = [n for n in fast_song.notes if n.role == "melody"]
    check("a fast tune keeps its melody on a bare NES",
          len(fast_melody) >= 0.95 * len(wanted),
          "%d of %d" % (len(fast_melody), len(wanted)))
    check("tiny notes are lengthened, not thrown away", fast_stats.dropped == 0,
          "dropped %d" % fast_stats.dropped)
    check("the melody never lands on another line's channel",
          len({n.channel for n in fast_melody}) == 1,
          str(sorted({n.channel for n in fast_melody})))
    fast_drums = [n for n in fast_notes if n.role == "drum"]
    check("20 ms drum hits survive", len(fast_drums) >= 0.8 * sum(
        1 for n in fast_song.notes if n.role == "drum"), str(len(fast_drums)))

    wide_notes, wide_stats = arrange(
        fast_song, chips.build_channel_set(list(chips.EXTENSION_CHANNELS)),
        Options(), analysis=fast_analysis)
    check("the chips are used, not just the first pulse wave",
          len(wide_stats.per_channel_notes) >= 8,
          str(sorted(wide_stats.per_channel_notes)))
    check("extra chips lose no more notes", wide_stats.dropped == 0)
    check("a chord really sounds at once", _simultaneity(wide_notes) >= 2.0,
          "%.2f notes at a time" % _simultaneity(wide_notes))

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

    print("voice budgeting (a few lines, not every part at once)")
    crowd = []
    for voice_index in range(6):                 # six harmony lines at once
        for step in range(8):
            crowd.append(Note(start=step * 0.25, dur=0.24,
                              pitch=55 + voice_index,
                              velocity=90 - voice_index * 6,
                              part=voice_index + 1, role="harmony",
                              voice=voice_index))
    budget = arrange_module._voice_budget(22)
    crowd_stats = arrange_module.Stats()
    kept_crowd = arrange_module._thin_voices(crowd, budget, crowd_stats)
    check("too many lines get thinned, and it is reported",
          crowd_stats.voices_thinned > 0, str(crowd_stats.voices_thinned))
    check("only the budget's worth of lines is kept",
          len({n.voice for n in kept_crowd}) == budget["harmony"],
          "%d of 6 lines" % len({n.voice for n in kept_crowd}))
    check("the quietest line is the one dropped",
          60 not in {n.pitch for n in kept_crowd},
          str(sorted({n.pitch for n in kept_crowd})))
    check("thinning is explained in the stats text",
          any("thinned" in line for line in crowd_stats.as_lines()))
    check("a big console still gets an arrangement-sized budget",
          2 <= budget["harmony"] <= 8 and budget["melody"] == 1, str(budget))
    check("a bare NES is left alone (contention already picks the best line)",
          arrange_module._voice_budget(4) is None)
    budget_notes, _ = arrange(
        fast_song, chips.build_channel_set(list(chips.EXTENSION_CHANNELS)),
        Options(), analysis=fast_analysis)
    check("exactly one melody line is used",
          len({n.channel for n in budget_notes if n.role == "melody"}) <= 1)
    check("the tune survives the thinning",
          sum(1 for n in budget_notes if n.role == "melody") >= 0.95 * sum(
              1 for n in fast_song.notes if n.role == "melody"),
          str(sum(1 for n in budget_notes if n.role == "melody")))

    print("the mix (measured from the pre-master stems)")
    role_energy = {}
    roles_by_channel = {}
    for note in all_notes:
        roles_by_channel.setdefault(note.channel, set()).add(note.role)
    for channel_id, buf in ext_stems.items():
        energy = sum((v - 0.0) ** 2 for v in buf) / max(1, len(buf))
        for role in roles_by_channel.get(channel_id, ()):
            role_energy[role] = role_energy.get(role, 0.0) + energy
    level = {role: value ** 0.5 for role, value in role_energy.items()}
    check("the melody is in the mix", level.get("melody", 0.0) > 0,
          str(sorted(level.items())))
    check("the melody is not buried under the chord bed",
          level.get("melody", 0.0) >= level.get("harmony", 0.0),
          "melody %.3f harmony %.3f" % (level.get("melody", 0),
                                        level.get("harmony", 0)))
    check("the melody is not buried under the bass",
          level.get("melody", 0.0) >= 0.85 * level.get("bass", 0.0),
          "melody %.3f bass %.3f" % (level.get("melody", 0),
                                     level.get("bass", 0)))
    check("the drums are audible", level.get("drum", 0.0) > 0.25 * level.get("melody", 0),
          "drum %.3f melody %.3f" % (level.get("drum", 0), level.get("melody", 0)))

    print("balancing the voices (the loudness the listener actually hears)")
    roles = mix_module.channel_roles(
        {channel: [n for n in all_notes if n.channel == channel]
         for channel in ext_stems})
    stem_levels = {channel: 20.0 * __import__("math").log10(
        max(1e-6, mix_module._active_level(buf)))
        for channel, buf in ext_stems.items()}
    gains = mix_module.balance(ext_stems, roles)
    after = {channel: level + 20.0 * __import__("math").log10(max(1e-6, gains[channel]))
             for channel, level in stem_levels.items()}
    before_spread = max(stem_levels.values()) - min(stem_levels.values())
    after_spread = max(after.values()) - min(after.values())
    check("every voice is measured", len(stem_levels) == len(ext_stems),
          "%d of %d" % (len(stem_levels), len(ext_stems)))
    check("the balance closes the gap between voices",
          after_spread < before_spread - 2.0,
          "%.1f dB -> %.1f dB" % (before_spread, after_spread))
    check("no voice is more than 20 dB under the lead",
          min(after.values()) > max(after.values()) - 20.0,
          "%.1f .. %.1f dB" % (min(after.values()), max(after.values())))
    check("the equaliser never rewrites the arrangement",
          all(0.05 < gain < 20.0 for gain in gains.values()),
          str(sorted(round(g, 2) for g in gains.values())))

    print("instruments have their own envelopes")
    pulse_spec = chips.channel_by_id(all_channels, "pulse1")

    def curve(program: int, role: str = "melody"):
        note = Note(start=0.0, dur=1.0, pitch=64, velocity=110, volume=15,
                    duty=0.5, role=role, program=program)
        buf = render_channel([note], pulse_spec, RenderOptions(rate=44100), 44100)

        def level(at):
            chunk = buf[int(at * 44100):int(at * 44100) + 2205]
            return (sum(v * v for v in chunk) / max(1, len(chunk))) ** 0.5
        return level(0.05), level(0.45), level(0.95)

    piano = curve(0)
    organ = curve(16)
    strings = curve(48)
    check("a piano dies away under the finger",
          piano[2] < piano[0] * 0.25,
          "%.3f -> %.3f" % (piano[0], piano[2]))
    check("an organ holds its level",
          organ[2] > organ[0] * 0.75, "%.3f -> %.3f" % (organ[0], organ[2]))
    check("strings swell in instead of clicking on",
          strings[1] > strings[0] * 1.05 or strings[0] > 0.8 * strings[1],
          "%.3f -> %.3f" % (strings[0], strings[1]))
    def drop_db(levels):
        return 20.0 * math.log10(max(1e-9, levels[0]) / max(1e-9, levels[2]))
    check("a struck note is not flat, a held one is",
          drop_db(piano) > drop_db(organ) + 8.0,
          "piano -%.1f dB, organ -%.1f dB" % (drop_db(piano), drop_db(organ)))

    print("the drum kit is balanced like a kit")
    def piece_rms(name):
        buf = samples_module.get(name)
        return (sum(v * v for v in buf) / max(1, len(buf))) ** 0.5
    kick = piece_rms("kick")
    snare = piece_rms("snare")
    hat = piece_rms("hat")
    check("the snare sits with the kick",
          0.4 < snare / kick < 1.2, "%.2f" % (snare / kick))
    check("the hats sit under the drums",
          hat / kick < 0.45, "%.2f" % (hat / kick))
    check("every piece has room for its transient",
          all(max((abs(v) for v in samples_module.get(name))) > 0.3
              for name in ("kick", "snare", "hat", "crash", "tom_low")))

    print("the echo is a tail, not a wash")
    plain = [math.sin(0.05 * i) if i < 2000 else 0.0 for i in range(44100)]
    echoed = mix_module.echo(list(plain), 44100)
    tail_plain = sum(abs(v) for v in plain[6000:12000])
    tail_echo = sum(abs(v) for v in echoed[6000:12000])
    body_plain = sum(abs(v) for v in plain[0:2000])
    body_echo = sum(abs(v) for v in echoed[0:2000])
    check("the echo puts sound where there was none", tail_echo > tail_plain)
    check("the echo leaves the original hit intact",
          abs(body_echo - body_plain) < 0.02 * max(1e-9, body_plain) + 1.0)

    print("the master stays clean")
    demo_pcm = render(all_notes, all_channels, RenderOptions(rate=44100), {})[0]
    peak = max(abs(v - 128) for v in demo_pcm) if demo_pcm else 0
    check("nothing clips", peak <= 128, str(peak))
    check("there is signal", peak > 20, str(peak))
    check("no echo unless it is asked for", demo_pcm == render(
        all_notes, all_channels, RenderOptions(rate=44100), {})[0])
    with_echo = render(all_notes, all_channels,
                       RenderOptions(rate=44100, echo=True), {})[0]
    check("the echo can be asked for", with_echo != demo_pcm)
    again = render(all_notes, all_channels, RenderOptions(rate=44100), {})[0]
    check("the same input renders the same bytes", again == demo_pcm)

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


def _simultaneity(notes) -> float:
    """Average number of notes sounding at the same time."""
    if not notes:
        return 0.0
    events = []
    for note in notes:
        events.append((note.start, 1))
        events.append((note.end(), -1))
    events.sort(key=lambda item: (item[0], -item[1]))
    area = 0.0
    last = events[0][0] if events else 0.0
    current = 0
    for moment, delta in events:
        area += current * (moment - last)
        last = moment
        current += delta
    span = max(n.end() for n in notes) - min(n.start for n in notes)
    return area / span if span > 0 else 0.0


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
