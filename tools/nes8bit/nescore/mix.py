"""The mix: levels that add up, and the tricks NES composers leaned on.

The chip cannot balance itself. A pulse channel at volume 15, a triangle at volume
15 and a noise channel at volume 15 are *not* the same loudness, and a file whose
tracks were written at wildly different velocities arrives as wildly different
voices — 18 dB between the lead and a harmony line is the difference between a mix
and a pile.

So the stems are measured after they are rendered and each voice is nudged towards
the level its role should sit at. The nudge is bounded: it corrects a broken balance,
it does not re-write the arrangement.

On top of that sit the two things every NES soundtrack did and most conversions
forget:

* **a short echo** — composers had no reverb, so they spent the fourth channel (or
  a few frames) on a delayed copy of the lead. A 100 ms slap with a little feedback
  is what makes a square wave sound like it is in a room instead of a test bench;
* **a gentle compressor** — the APU's own mixer squashes peaks; doing it here keeps
  a busy chorus from clipping and a quiet verse from disappearing.
"""

import math
from typing import Dict, Iterable, List

# Where each kind of line sits in the mix, relative to the lead, in dB.
ROLE_TARGET = {
    "melody": 0.0,
    "counter": -3.5,
    "rhythm": -5.0,
    "harmony": -7.0,
    "bass": -5.0,
    "drum": -3.0,
}
DEFAULT_TARGET = -6.0
BASE_DB = -24.0            # where the lead sits before the final normalise
MAX_CORRECTION = 14.0      # never let the equaliser rewrite the arrangement
STRIDE = 8                 # loudness is measured on every 8th sample: fast, exact enough

ECHO_DELAY = 0.105         # seconds; roughly the "second pulse" trick
ECHO_FEEDBACK = 0.22
ECHO_MIX = 0.07             # quiet enough to be air; off entirely unless asked for


def _active_level(buffer: List[float]) -> float:
    """RMS of the parts that actually play, so a rare voice is not called quiet."""
    total = 0.0
    count = 0
    for index in range(0, len(buffer), STRIDE):
        value = buffer[index]
        if value > 1e-4 or value < -1e-4:
            total += value * value
            count += 1
    if not count:
        return 0.0
    return math.sqrt(total / count)


def channel_roles(grouped: Dict[str, Iterable]) -> Dict[str, str]:
    """The role a channel mainly plays, for the balance."""
    roles: Dict[str, str] = {}
    for channel, notes in grouped.items():
        counts: Dict[str, int] = {}
        for note in notes:
            counts[note.role] = counts.get(note.role, 0) + 1
        if counts:
            roles[channel] = max(counts, key=counts.get)
    return roles


def balance(stems: Dict[str, List[float]],
            roles: Dict[str, str]) -> Dict[str, float]:
    """A linear gain per channel that puts every voice near its role's level."""
    gains: Dict[str, float] = {}
    for channel, buffer in stems.items():
        level = _active_level(buffer)
        if level <= 0.0:
            gains[channel] = 1.0
            continue
        target = BASE_DB + ROLE_TARGET.get(roles.get(channel, ""), DEFAULT_TARGET)
        correction = target - 20.0 * math.log10(level)
        correction = max(-MAX_CORRECTION, min(MAX_CORRECTION, correction))
        gains[channel] = 10.0 ** (correction / 20.0)
    return gains


def role_levels(stems: Dict[str, List[float]],
                roles: Dict[str, str],
                gains: Dict[str, float]) -> Dict[str, float]:
    """The measured level of each *role* in the finished mix, in dB.

    Stems are rendered per channel; a listener hears roles. Three harmony channels
    add up, so they are summed (as the mix does) rather than averaged, and the
    result is the RMS of everything that voice-group actually contributes.
    """
    sums: Dict[str, List[float]] = {}
    for channel, buffer in stems.items():
        role = roles.get(channel, "")
        gain = gains.get(channel, 1.0)
        if role in sums:
            target = sums[role]
            for index, value in enumerate(buffer):
                target[index] += value * gain
        else:
            sums[role] = [value * gain for value in buffer]
    levels: Dict[str, float] = {}
    for role, buffer in sums.items():
        level = _active_level(buffer)
        levels[role] = 20.0 * math.log10(level) if level > 0 else -120.0
    return levels


def audibility(levels: Dict[str, float]) -> Dict[str, float]:
    """How far the melody sits above or below everything else, in dB.

    Levels are dB, so the rest of the mix is added as energy and turned back into
    dB: adding decibels together would be wrong the moment two parts play at once.
    """
    melody = levels.get("melody")
    rest = [value for role, value in levels.items() if role != "melody"]
    if melody is None or not rest:
        return {}
    total = sum(10.0 ** (value / 10.0) for value in rest)
    together = 10.0 * math.log10(total) if total > 0 else -120.0
    return {"melody": melody, "rest": together, "gap": melody - together}


def echo_delay(notes) -> float:
    """One or two rows of the song's own grid, so the echo lands on the beat.

    A fixed 100 ms slap sounds wrong on a tune whose sixteenths are 66 ms: the
    repeat falls between the notes. Composers set their echo to the row rate.
    """
    times = sorted({round(note.start, 3) for note in notes})
    steps = [b - a for a, b in zip(times, times[1:]) if 0.02 < b - a < 0.6]
    if not steps:
        return ECHO_DELAY
    steps.sort()
    step = steps[len(steps) // 2]
    return max(0.08, min(0.20, step * 2.0))


def echo(buffer: List[float], rate: int, delay: float = ECHO_DELAY,
         feedback: float = ECHO_FEEDBACK, mix: float = ECHO_MIX,
         taps: int = 2) -> List[float]:
    """A couple of delayed copies, quiet enough to be air rather than mud."""
    shift = int(rate * delay)
    if shift <= 0 or shift >= len(buffer):
        return buffer
    for tap in range(1, taps + 1):
        offset = shift * tap
        if offset >= len(buffer):
            break
        gain = mix * (feedback ** (tap - 1))
        tail = buffer[:-offset]
        buffer[offset:] = [a + gain * b for a, b in zip(buffer[offset:], tail)]
    return buffer


def compress(buffer: List[float], rate: int, threshold_db: float = -24.0,
             ratio: float = 1.8, attack: float = 0.010,
             release: float = 0.25) -> List[float]:
    """Block-based soft-knee compressor: keeps the quiet parts alive, tames peaks."""
    block = max(32, int(rate * 0.004))
    threshold = 10.0 ** (threshold_db / 20.0)
    attack_step = 1.0 - math.exp(-block / max(1.0, attack * rate))
    release_step = 1.0 - math.exp(-block / max(1.0, release * rate))
    gain = 1.0
    for start in range(0, len(buffer), block):
        end = min(len(buffer), start + block)
        chunk = buffer[start:end]
        if not chunk:
            break
        level = math.sqrt(sum(v * v for v in chunk) / len(chunk))
        if level > threshold:
            wanted = threshold * (level / threshold) ** (1.0 / ratio) / level
        else:
            wanted = 1.0
        step = attack_step if wanted < gain else release_step
        gain += (wanted - gain) * step
        if abs(gain - 1.0) > 1e-4:
            buffer[start:end] = [v * gain for v in chunk]
    return buffer


def choose_ceiling(buffer: List[float], rate: int, base: float = 0.72,
                   cap: float = 0.86) -> float:
    """How hard to limit: a sparse mix can take it, a wall of squares cannot.

    On a four-voice tune only a few percent of the samples poke above the base
    ceiling, so limiting there is free loudness. On twenty-two voices most of the
    mix is up there and clipping it would just add distortion — so the ceiling
    backs off automatically.
    """
    block = max(16, int(rate * 0.0015))
    total = 0
    loud = 0
    for start in range(0, len(buffer), block):
        chunk = buffer[start:start + block]
        if not chunk:
            break
        total += 1
        if max((abs(v) for v in chunk), default=0.0) > base:
            loud += 1
    fraction = loud / max(1, total)
    if fraction <= 0.06:
        return base
    return min(cap, base + (fraction - 0.06) * 1.3)


def limit(buffer: List[float], rate: int, ceiling: float = 0.96,
          release: float = 0.06) -> List[float]:
    """Catches the transients so the whole mix does not have to be turned down.

    Drums have 12 dB more crest factor than a square wave. Normalising on the
    loudest kick means the melody pays for it; a limiter takes the few samples that
    poke out and leaves the rest of the mix at its natural level.
    """
    block = max(16, int(rate * 0.0015))
    release_step = 1.0 - math.exp(-block / max(1.0, release * rate))
    gain = 1.0
    for start in range(0, len(buffer), block):
        end = min(len(buffer), start + block)
        chunk = buffer[start:end]
        if not chunk:
            break
        peak = max((abs(v) for v in chunk), default=0.0)
        wanted = ceiling / peak if peak > ceiling else 1.0
        if wanted < gain:
            gain = wanted                      # instant attack: never let a peak through
        else:
            gain += (wanted - gain) * release_step
        if gain < 0.999:
            buffer[start:end] = [v * gain for v in chunk]
    return buffer


def _hi_pass_level(buffer: List[float], rate: int, cutoff: float = 140.0) -> float:
    """Loudness with the rumble taken out, so a triangle drone is not over-weighted."""
    alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff / rate)
    low = 0.0
    total = 0.0
    count = 0
    for index in range(0, len(buffer), STRIDE):
        value = buffer[index]
        low += alpha * (value - low)
        high = value - low
        total += high * high
        count += 1
    if not count:
        return 0.0
    return math.sqrt(total / count)
