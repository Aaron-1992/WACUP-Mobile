# chip8bit — NES / 8-bit chiptune transcoder

Takes **MIDI files** (and **game music logs**: VGM, VGZ, GYM, or a `.zip` of them) and
re-composes them for the NES sound chip, then renders the result as 8-bit WAV.

* every hardware voice is used, and **extension chips can be switched on**;
* when a part has nowhere to go it is **moved to any other channel that is free**
  at that moment, and only when the console is genuinely full do the clashing
  notes take turns as a fast arpeggio — the way NES soundtracks fake chords;
* the synthesis is hardware-accurate, not "square wave synth": 4-bit volume,
  the 32-step triangle with no volume control, 15-bit LFSR noise, VRC6 sawtooth,
  FDS/Namco wavetable, SN76489 attenuation steps, and the APU's non-linear mixer
  curve on the output.

No dependencies. Pure Python 3 standard library, so the Windows build is one `.exe`.

## Two ways to use it

### The window (what you probably want)

Double-click **`chip8bit.exe`** — no install, no Python. A window opens in your browser:

1. **Add music** — drag files onto the drop zone (or click it). MIDI, VGM/VGZ,
   GYM, and `.zip` of any of those.
2. **Pick chips** — click the extension chips you want. The counter in the corner
   shows how many voices you have (4 → 22). Your choices are remembered.
3. **Convert** — press the big button. Each result plays right there, shows how
   every note was placed (placed / on spare channels / shared / dropped), and has a
   Download button. "Load the demo tune" gives you something to hear immediately.

You can also **drop a file straight onto `chip8bit.exe`** — the window opens with
that file already queued.

Everything runs on your machine; nothing is uploaded. Files are written where you
click Download, and the page can be closed any time. To stop the app, use *Quit
chip8bit* at the bottom of the page.

### The command line

```
chip8bit-cli.exe song.mid --extensions vrc6,mmc5,fds --stats
chip8bit-cli.exe games\*.vgz --extensions all -o converted
chip8bit-cli.exe --list-extensions
```

`chip8bit-cli.exe song.mid` writes `song [nes].wav` next to the input;
`--extensions all` writes `song [nes+vrc6+mmc5+fds+n163+psg+dmc].wav`.

## The chips you can switch on

| flag | adds | channels |
| --- | --- | --- |
| `nes` (always on) | 2A03 APU | `pulse1`, `pulse2`, `triangle`, `noise` |
| `vrc6` | Konami VRC6 | 2 extra pulses + a sawtooth (`vrc6_saw`) |
| `mmc5` | Nintendo MMC5 | 2 extra pulses |
| `fds` | Famicom Disk System | 1 wavetable channel |
| `n163` | Namco 163 | 8 wavetable channels |
| `psg` | SN76489 (Master System / Genesis) | 3 square channels |
| `dmc` | APU delta channel | 1 percussion voice |

That is 4 voices bare and 22 with everything enabled.

## Command line options

| option | what it does |
| --- | --- |
| `--stats` | report where every note went: placed, re-homed, shared, dropped |
| `--stems FOLDER` | one WAV per console channel, to hear the arrangement |
| `--export-vgm` | also write a `.vgm` register log |
| `--no-sharing` | never split a held note into an arpeggio |
| `--arp-frames N` | frames per arpeggio note (default 2, the classic NES feel) |
| `--bits 16`, `--rate 48000` | cleaner output for editing |
| `--transpose N`, `--max-seconds N`, `--gain 0.8`, `--linear` | the usual knobs |

## How a conversion works

1. **Import** — the source is turned into plain notes with real pitch, timing,
   velocity, pitch bend and vibrato. Tempo changes, sustain pedal, running status,
   formats 0/1/2 and RIFF-wrapped MIDI are all handled. VGM/GYM input is decoded
   from the FM register writes (fnum/block → Hz), so Genesis music keeps its
   actual tuning instead of being guessed.
2. **Arrange** — each part is classified (melody / harmony / bass / drums), then:
   melody leans on the pulses, bass takes the triangle, drums take noise (and the
   DMC if enabled), harmony fills whichever channel is free. Overflow notes go to
   any free melodic channel; only then does a channel borrow and arpeggiate.
3. **Quantise** to the NES's 60.0988 fps frame grid, so every event is a frame
   the console could actually hit.
4. **Render** — each channel is synthesised like the real chip, mixed through the
   APU curve, dithered and written as 8-bit PCM.

## Honest limits

* VGM can only address the NES APU and the SN76489, so `--export-vgm` leaves the
  VRC6/MMC5/FDS/N163 notes out of the log. The WAV always has all of them.
* The DMC channel has no sample ROM here, so it is driven as a direct DAC thump
  (unpitched percussion) rather than a sampled drum kit.
* Supported input: MIDI (`.mid .midi .rmi .kar`), VGM/VGZ, GYM, `.zip`. NSF, SPC,
  PSF and friends are different formats — the tool says so rather than guessing.
* Sources with more simultaneous voices than the console plus every extension
  (say, a dense orchestral MIDI) will still need arpeggios or lose a few inner
  voices. `--stats` (and the window's result card) tells you exactly how many.
* The window is served from `127.0.0.1` on your own machine and opened in your
  default browser — that keeps the tool dependency-free and gives real drag-and-drop
  and an audio player for free. It is not a native window, but it is the only
  process running and it never talks to the network.

## Development

```
python tests/make_test_midi.py tests/genesis-style.mid   # synthetic Genesis-style tune
python tests/run_tests.py                                # pipeline self test (50+ checks)
python chip8bit.py --selftest                            # GUI self test (starts the window)
python chip8bit.py                                       # open the window
python chip8bit.py --serve --port 8734                   # serve it without a browser
python chip8bit.py tests/genesis-style.mid --extensions all --stats
```
