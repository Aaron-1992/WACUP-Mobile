"""The chip8bit window: a tracker desk, dark.

One native window, one look. It is laid out like a tracker — a strip of live
numbers, a toolbar, the pattern page as the biggest thing on the desk, the chips
and the files down the right — and it is painted dark: near-black panels, single
hairline borders, one mint accent, monospaced text everywhere. There is no skin
switch and there are no bevels; that Windows 95 face is gone for good.

The big pattern page is built from the arrangement that really went to the chips:
one column per console voice, note / instrument / volume in hex, row numbers down
the side of every group of four channels, and a play cursor that follows the music.
The strip above it shows what the converter understood about the file.
"""

import bisect
import gc
import json
import os
import queue
import sys
import tempfile
import threading
import time
from dataclasses import replace
from typing import Dict, List, Optional

import pygame

from . import chips, convert, dialogs, demo, gm, importers, theme, waves as waves_module

WIDTH, HEIGHT = 1200, 830
MIN_WIDTH, MIN_HEIGHT = 1000, 740
FPS = 60

RATES = (22050, 32000, 44100, 48000, 96000)   # what the RATE spinner walks
GROUP_SIZE = 4             # channels per row-number group, as in FastTracker II
PATTERN_ROWS = 64          # one tracker pattern
PATTERN_SPEED = 6          # ticks per row: 2.5/BPM * 6 seconds

_FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/TTF",
    "/usr/local/share/fonts",
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
]

_CHANNEL_NAMES = {
    "pulse1": "PU1", "pulse2": "PU2", "triangle": "TRI", "noise": "NOI",
    "dmc": "DMC", "fds": "FDS", "vrc6_saw": "V6S",
    "vrc6_pulse1": "V6-1", "vrc6_pulse2": "V6-2",
    "mmc5_pulse1": "M5-1", "mmc5_pulse2": "M5-2",
    # the second NES APU, and the PC Engine's six
    "nes2_pulse1": "2PU1", "nes2_pulse2": "2PU2", "nes2_triangle": "2TRI",
    "nes2_noise": "2NOI",
    "pce1": "PC1", "pce2": "PC2", "pce3": "PC3", "pce4": "PC4",
    "pce5": "PC5", "pce6": "PC6",
}


def _font_path(names, bold=False):
    """Find a usable TrueType file: fontconfig first, then the usual folders.

    The sandbox (and many CI images) have no fc-list, so match_font finds nothing
    and everything falls back to pygame's tiny bitmap face.
    """
    for name in names:
        try:
            path = pygame.font.match_font(name, bold=bold)
        except Exception:
            path = None
        if path:
            return path
    wanted = []
    for name in names:
        flat = name.replace(" ", "")
        wanted.append((flat + ("-Bold" if bold else "") + ".ttf").lower())
        wanted.append((flat + ".ttf").lower())
    for folder in _FONT_DIRS:
        if not os.path.isdir(folder):
            continue
        for entry in sorted(os.listdir(folder)):
            if entry.lower() in wanted:
                return os.path.join(folder, entry)
    return None


def _font(theme_obj: theme.Theme, size: int, bold: bool = False):
    return pygame.font.Font(_font_path(theme_obj.fonts(), bold=bold), size)


def _font_mono(size: int, bold: bool = False):
    """A monospaced font, so tracker columns line up like they should."""
    return pygame.font.Font(
        _font_path(("DejaVu Sans Mono", "Liberation Mono", "Consolas",
                    "Courier New", "Courier"), bold=bold), size)


def _channel_short(channel: str) -> str:
    if channel in _CHANNEL_NAMES:
        return _CHANNEL_NAMES[channel]
    if channel.startswith("n163_"):
        return "N" + channel[5:]
    if channel.startswith("psg"):
        return "PSG" + channel[3:]
    return channel[:4].upper()


def _fit(font, text: str, width: int) -> str:
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "…")[0] > width:
        text = text[:-1]
    return (text + "…") if text else ""


DS_EXTENSIONS = (".nds", ".sdat", ".sseq")


class QueueItem:
    """One file waiting to be converted, plus what happened to it."""

    def __init__(self, path: str, name: str, size: int = 0,
                 sequence: str = "", bank: str = ""):
        self.path = path
        self.name = name
        self.size = size
        self.status = "waiting"      # waiting | working | failed  (done leaves)
        self.fraction = 0.0
        self.stage = ""
        self.error = ""
        # a DS ROM holds many songs: which one this row converts
        self.sequence = sequence
        self.bank = bank
        self.catalogue: Optional[dict] = None     # songs, banks, waves, name
        self.catalogue_note = ""                  # why it could not be read
        self.catalogue_reading = False

    def is_archive(self) -> bool:
        return os.path.splitext(self.path)[1].lower() in DS_EXTENSIONS

    def song(self) -> str:
        """The song this row converts: what was picked, or the archive's own."""
        if self.sequence:
            return self.sequence
        if self.catalogue:
            return self.catalogue.get("chosen", "")
        return ""

    def song_count(self) -> int:
        return len(self.catalogue["songs"]) if self.catalogue else 0

    def song_number(self) -> int:
        """1-based position of the chosen song, for "12 of 37"."""
        if not self.catalogue:
            return 0
        wanted = self.song().lower()
        for position, (_index, _bank, name) in enumerate(self.catalogue["songs"], 1):
            if name.lower() == wanted:
                return position
        return 1 if self.catalogue["songs"] else 0

    def settings_for(self, settings):
        """This row's conversion settings: a copy with its own song and bank."""
        if not (self.sequence or self.bank):
            return settings
        return replace(settings, sequence=self.sequence, bank=self.bank)


READABLE = (".mid", ".midi", ".rmi", ".kar", ".vgm", ".vgz", ".gym",
            ".nds", ".sdat", ".sseq", ".zip")


class App:
    def __init__(self, files: Optional[List[str]] = None,
                 settings_path: Optional[str] = None):
        pygame.init()
        pygame.display.set_caption("chip8bit — NES / 8-bit transcoder")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()

        self.settings_path = settings_path or self._default_settings_path()
        self.settings = self._load_settings()
        self.theme = theme.get()

        self.fonts: Dict[str, pygame.font.Font] = {}
        self._build_fonts()

        self.items: List[QueueItem] = []
        self.results: List[convert.Result] = []
        self.batch: List[QueueItem] = []
        self.output_dir = dialogs.default_output_dir()
        self.convert_started = 0.0
        self.messages: queue.Queue = queue.Queue()
        self.busy = False
        self.progress = 0.0
        self.progress_label = ""
        self.status = "Drop MIDI / VGM / GYM files on the window, or press ADD MUSIC"
        self.status_error = False

        self.hits: List[tuple] = []
        self.mouse = (0, 0)
        self.scroll_queue = 0
        self.scroll_results = 0
        self.playing: Optional[int] = None
        self.mixer_ready = self._init_mixer()
        self.running = True

        # widget handles the self test (and the mouse) use
        self.chip_rects: List[tuple] = []
        self.toolbar_rects: List[pygame.Rect] = []
        self.convert_rect = pygame.Rect(0, 0, 0, 0)
        self.play_rect = pygame.Rect(0, 0, 0, 0)
        self.pattern_row = 0
        self.pattern_column = 0
        self.pattern_columns = 1
        self.pattern_height = 0
        self.selected_result = 0
        self.mouse_in_pattern = False
        self.mouse_in_queue = False
        self.mouse_in_results = False
        # the song browser (only DS archives open one)
        self.song_window: Optional[dict] = None
        self.song_rows: List[tuple] = []
        self.songs_buttons: List[tuple] = []      # (queue index, rect) per row
        self.song_list_view = pygame.Rect(0, 0, 0, 0)
        self._song_click = (-1, 0.0)
        self._song_typed = ""
        self._song_typed_at = 0.0
        self._catalogues_reading: set = set()
        self.queue_view = pygame.Rect(0, 0, 0, 0)
        self.results_view = pygame.Rect(0, 0, 0, 0)

        # caches: what is on screen changes far less often than the window is
        # asked to repaint, so the expensive answers are kept (see _pattern_data,
        # _paint_rows, _paint_mixer and _surface).
        self._text_cache: Dict[tuple, pygame.Surface] = {}
        self._pattern_key = None
        self._pattern_cache = (None, [], 0.0, 0, {})
        self._note_counts: Dict[str, int] = {}
        self._note_spans: Dict[str, List[tuple]] = {}
        self._note_starts: Dict[str, List[float]] = {}
        self._mixer_key = None
        self._mixer_surface: Optional[pygame.Surface] = None
        self._mixer_cells: List[tuple] = []
        self._body_key = None
        self._body_surface: Optional[pygame.Surface] = None
        self._dirty = True
        self._last_draw = 0.0

        # A window that holds a whole song in memory makes every full garbage
        # collection expensive, and one landing inside a repaint is a stutter you
        # can see. Collect less often, and freeze what was alive at startup (the
        # fonts, the theme, the widget tables) out of the scans: this is the usual
        # advice for pygame programs, and it is measurable here — a full pass over
        # a converted three-minute tune was taking 100 ms or more.
        gc.set_threshold(20000, 50, 50)
        gc.freeze()

        for path in files or []:
            self.add_path(path)

    # ------------------------------------------------------------------ setup

    def _build_fonts(self) -> None:
        t = self.theme
        self.fonts = {
            "logo": _font(t, 44, bold=True),
            "title": _font(t, 17, bold=True),
            "body": _font(t, 15),
            "small": _font(t, 15),
            "tiny": _font(t, 13, bold=True),
            "button": _font(t, 14, bold=True),
            "pattern": _font_mono(19),
            "head": _font_mono(14, bold=True),
        }

    @staticmethod
    def _default_settings_path() -> str:
        base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base, "chip8bit-settings.json")

    def _load_settings(self):
        """The saved settings, with the old look key simply ignored.

        A settings file written by an older build still holds "look": "win95" or
        "amiga". There is one look now, so the key is skipped rather than
        switched to: an upgrade must not put the Windows 95 desk back on screen.
        """
        settings = convert.Settings()
        try:
            with open(self.settings_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, ValueError):
            return settings
        settings.extensions = [name for name in saved.get("extensions", [])
                               if name in chips.EXTENSION_CHANNELS]
        settings.base = bool(saved.get("base", True))
        settings.bits = 16 if saved.get("bits", 16) != 8 else 8
        settings.export_vgm = bool(saved.get("export_vgm", False))
        settings.sharing = False        # never resurrect arpeggio cramming
        settings.sampled_drums = bool(saved.get("sampled_drums", True))
        return settings

    def _save_settings(self) -> None:
        try:
            with open(self.settings_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "extensions": list(self.settings.extensions),
                    "base": self.settings.base,
                    "bits": self.settings.bits,
                    "export_vgm": self.settings.export_vgm,
                    "sharing": self.settings.sharing,
                    "sampled_drums": self.settings.sampled_drums,
                }, handle, indent=2)
        except OSError:
            pass

    def _init_mixer(self) -> bool:
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=1024)
            pygame.mixer.music.set_volume(0.9)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------- files

    def add_path(self, path: str, sequence: str = "", bank: str = "") -> None:
        if not os.path.isfile(path):
            self.status = "Not a file: %s" % path
            self.status_error = True
            return
        if any(item.path == path and item.sequence == sequence
               for item in self.items):
            self.status = "%s is already in the list" % os.path.basename(path)
            self.status_error = False
            return
        if os.path.splitext(path)[1].lower() not in READABLE:
            self.status = ("Can't read %s — MIDI, VGM, GYM, a DS ROM or a .zip "
                           "of those" % os.path.basename(path))
            self.status_error = True
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        item = QueueItem(path, os.path.basename(path), size,
                         sequence=sequence, bank=bank)
        self.items.append(item)
        self.status = "%d file%s queued — press CONVERT" % (
            len(self.items), "" if len(self.items) == 1 else "s")
        self.status_error = False
        if item.is_archive():
            self.read_catalogue(item)

    # ------------------------------------------------------------ song browser

    def read_catalogue(self, item: QueueItem) -> None:
        """List the songs inside a DS file, off the drawing thread."""
        if item.catalogue is not None or item.catalogue_reading:
            return
        item.catalogue_reading = True
        item.catalogue_note = ""
        if item.path not in self._catalogues_reading:
            self._catalogues_reading.add(item.path)
            threading.Thread(target=self._read_catalogue, args=(item.path,),
                             daemon=True).start()

    def _read_catalogue(self, path: str) -> None:
        catalogue = None
        note = ""
        try:
            catalogue = importers.catalogue(path)
            if catalogue is None:
                note = "this file holds no songs to list"
        except Exception as error:                 # a bad file must not crash
            note = str(error)
        self.messages.put(("catalogue", path, catalogue, note))

    def _catalogue_arrived(self, path: str, catalogue, note: str) -> None:
        self._catalogues_reading.discard(path)
        for item in self.items:
            if item.path != path:
                continue
            item.catalogue_reading = False
            item.catalogue = catalogue
            item.catalogue_note = note
        window = self.song_window
        if window and window["item"].path == path:
            self._fill_song_window(window["item"])

    def open_songs(self, index: int) -> None:
        """Open the song browser for one queued file."""
        if not (0 <= index < len(self.items)):
            return
        item = self.items[index]
        if not item.is_archive():
            self.status = "%s is not a DS archive — it has no songs to choose" % item.name
            self.status_error = True
            return
        self.song_window = {"item": item, "selected": 0, "scroll": 0,
                            "bank": item.bank, "row_h": 22}
        self._fill_song_window(item)
        self.read_catalogue(item)
        if item.catalogue:
            self.status = "%d song%s in %s — Enter uses one, ESC closes" % (
                item.song_count(), "" if item.song_count() == 1 else "s", item.name)
        else:
            self.status = "Reading the songs in %s…" % item.name
        self.status_error = False

    def _fill_song_window(self, item: QueueItem) -> None:
        window = self.song_window
        if not window or window["item"] is not item:
            return
        window["selected"] = 0
        window["scroll"] = 0
        if item.catalogue:
            wanted = item.song()
            for position, (_index, _bank, name) in enumerate(item.catalogue["songs"]):
                if wanted and name.lower() == wanted.lower():
                    window["selected"] = position
                    break
            window["bank"] = item.bank or ""

    def close_songs(self) -> None:
        if self.song_window:
            self.song_window = None
            self.status = "Song list closed — the file still converts as it is"
            self.status_error = False

    def _window_songs(self) -> List[tuple]:
        window = self.song_window
        if not window or not window["item"].catalogue:
            return []
        return window["item"].catalogue["songs"]

    def move_song(self, step: int) -> None:
        songs = self._window_songs()
        if not songs or not self.song_window:
            return
        window = self.song_window
        window["selected"] = max(0, min(len(songs) - 1,
                                        window["selected"] + step))
        self._scroll_song_into_view()

    def _scroll_song_into_view(self) -> None:
        window = self.song_window
        if not window or not self.song_list_view.height:
            return
        visible = max(1, (self.song_list_view.height - 4) // window["row_h"])
        selected = window["selected"]
        if selected < window["scroll"]:
            window["scroll"] = selected
        elif selected >= window["scroll"] + visible:
            window["scroll"] = selected - visible + 1
        window["scroll"] = max(0, min(window["scroll"],
                                      max(0, len(self._window_songs()) - visible)))

    def pick_song_row(self, position: int) -> None:
        songs = self._window_songs()
        if not songs or not self.song_window:
            return
        position = max(0, min(len(songs) - 1, position))
        now = time.time()
        last, when = self._song_click
        self._song_click = (position, now)
        self.song_window["selected"] = position
        if last == position and now - when < 0.45:
            self.use_song()            # a double click takes the song

    def change_bank(self, step: int) -> None:
        """Step the bank number in the browser (empty = the song's own bank)."""
        window = self.song_window
        if not window:
            return
        item = window["item"]
        banks = (item.catalogue or {}).get("banks", 0) or 1
        current = window["bank"]
        if current == "":
            songs = self._window_songs()
            selected = window["selected"]
            own = songs[selected][1] if songs else 0
            value = own + step
        else:
            value = int(current) + step
        value = max(0, min(max(0, banks - 1), value))
        window["bank"] = str(value)

    def use_song(self) -> None:
        """Take the highlighted song for this queue row, and close the browser."""
        window = self.song_window
        songs = self._window_songs()
        if not window or not songs:
            return
        item = window["item"]
        _index, own_bank, name = songs[window["selected"]]
        bank = window["bank"]
        valid_banks = (item.catalogue or {}).get("banks", 0)
        if bank != "" and valid_banks and int(bank) >= valid_banks:
            bank = ""
        if bank == str(own_bank):
            bank = ""                      # the song's own bank: say nothing
        item.sequence = name
        item.bank = bank
        self.song_window = None
        self.status = "%s → %s%s — press CONVERT" % (
            item.name, name, "" if not bank else " (bank %s)" % bank)
        self.status_error = False

    def add_all_songs(self) -> None:
        """Queue every song in the archive as its own row."""
        window = self.song_window
        if not window or not window["item"].catalogue:
            return
        item = window["item"]
        songs = item.catalogue["songs"]
        existing = {(entry.path, entry.sequence) for entry in self.items}
        added = 0
        for _index, _bank, name in songs[:200]:
            if (item.path, name) in existing:
                continue
            self.items.append(QueueItem(item.path, item.name, item.size,
                                        sequence=name))
            existing.add((item.path, name))
            added += 1
        self.song_window = None
        if not item.sequence:              # the row that stood for "all of it"
            self.items = [entry for entry in self.items if entry is not item]
        if added:
            self.status = "Queued %d song%s from %s — press CONVERT" % (
                added, "" if added == 1 else "s", item.name)
        else:
            self.status = "Every song in %s is already in the list" % item.name
        self.status_error = False

    def add_demo(self) -> None:
        directory = os.path.join(tempfile.gettempdir(), "chip8bit-demo")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "chip8bit demo tune.mid")
        if not os.path.isfile(path):
            with open(path, "wb") as handle:
                handle.write(demo.build())
        self.add_path(path)

    def remove_item(self, index: int) -> None:
        if not (0 <= index < len(self.items)):
            return
        gone = self.items.pop(index)
        if self.song_window and self.song_window["item"] is gone:
            self.song_window = None        # its songs went with it

    def clear_queue(self) -> None:
        if self.busy:
            self.status = "Still converting — wait, or press STOP"
            self.status_error = True
            return
        self.items = []
        self.scroll_queue = 0
        self.song_window = None
        self.status = "List cleared — results are still in CONVERTED"
        self.status_error = False

    def pick_files(self) -> None:
        paths = dialogs.open_files()
        if paths:
            for path in paths:
                self.add_path(path)
        else:
            self.status = "If no picker opens, just drop files onto this window"
        self.status_error = False

    # ----------------------------------------------------------------- convert

    def start_convert(self) -> None:
        if self.busy:
            return
        pending = [item for item in self.items if item.status != "done"]
        if not pending:
            self.status = "Nothing to convert — press ADD MUSIC or drop a file here"
            self.status_error = False
            return
        for item in pending:
            item.status = "waiting"
            item.fraction = 0.0
            item.stage = ""
            item.error = ""
        self.batch = pending
        self.busy = True
        self.progress = 0.0
        self.progress_label = "Starting…"
        self.convert_started = time.time()
        self.status_error = False
        self.status = "Converting %d file%s…" % (len(pending),
                                                 "" if len(pending) == 1 else "s")
        files = list(pending)
        threading.Thread(target=self._work, args=(files, self.settings),
                         daemon=True).start()

    def output_line(self) -> str:
        return os.path.join(self.output_dir, "")

    def open_output_dir(self) -> None:
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError:
            pass
        dialogs.reveal(self.output_line())
        self.status = "Converted files go to %s" % self.output_dir
        self.status_error = False

    def _work(self, files, settings) -> None:
        output_dir = self.output_dir
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError:
            pass
        try:
            for index, item in enumerate(files):
                path, name = item.path, item.name
                self.messages.put(("begin", index))

                def progress(stage, fraction, index=index):
                    self.messages.put(("progress", index, stage,
                                       max(0.0, min(1.0, fraction))))

                try:
                    result = convert.convert_file(path, item.settings_for(settings),
                                                  output_dir=output_dir,
                                                  progress=progress)
                except Exception as error:      # one bad file must not stop the rest
                    result = convert.Result(ok=False, name=name,
                                            error="%s: %s" % (type(error).__name__,
                                                              error))
                self.messages.put(("result", index, result, path))
        finally:
            self.messages.put(("done",))

    def _drain(self) -> None:
        """Take whatever the worker threads have finished, without blocking."""
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                return
            # a finished conversion or a read song list changes the picture, and
            # no event will be coming to say so: paint the next frame
            self._dirty = True
            if message[0] == "catalogue":
                _tag, path, catalogue, note = message
                self._catalogue_arrived(path, catalogue, note)
                continue
            if message[0] == "begin":
                _, index = message
                if 0 <= index < len(self.batch):
                    item = self.batch[index]
                    item.status = "working"
                    item.fraction = 0.0
                    self.progress_label = item.name
            elif message[0] == "progress":
                _, index, stage, fraction = message
                total = max(1, len(self.batch))
                if 0 <= index < len(self.batch):
                    item = self.batch[index]
                    item.fraction = fraction
                    item.stage = stage
                    self.progress_label = "%s — %s" % (item.name, stage)
                self.progress = (index + fraction) / total
            elif message[0] == "result":
                _, index, result, path = message
                if 0 <= index < len(self.batch):
                    item = self.batch[index]
                    item.fraction = 1.0
                    if result.ok:
                        item.status = "done"
                    else:
                        item.status = "failed"
                        item.error = result.error
                self.results.insert(0, result)
                self.selected_result = 0
                if not result.ok:
                    for position, other in enumerate(self.results):
                        if other.ok:
                            self.selected_result = position
                            break
                self.pattern_row = 0
                self.pattern_column = 0
                if result.ok:
                    self.status = "Saved %s" % os.path.basename(result.wav_path)
                    if getattr(result, "assets", None):
                        extras = sorted({os.path.splitext(name)[1].upper()
                                         for name in result.assets})
                        self.status += " + " + " and ".join(extras)
                    self.status_error = False
                else:
                    self.status = "%s: %s" % (os.path.basename(path), result.error)
                    self.status_error = True
            elif message[0] == "done":
                self.busy = False
                self.progress = 0.0
                self.progress_label = ""
                self._finish_batch()

    def _finish_batch(self) -> None:
        """Move the converted files out of the queue and say how it went."""
        batch, self.batch = self.batch, []
        if not batch:
            return
        ok = [item for item in batch if item.status == "done"]
        failed = [item for item in batch if item.status == "failed"]
        self.items = [item for item in self.items if item.status != "done"]
        for item in self.items:
            if item.status != "failed":     # keep the failure visible until retried
                item.status = "waiting"
            item.fraction = 0.0
        took = max(0.0, time.time() - self.convert_started)
        if failed and not ok:
            self.status = ("%d file%s could not be converted — %s"
                           % (len(failed), "" if len(failed) == 1 else "s",
                              failed[0].error))
            self.status_error = True
        elif failed:
            self.status = ("Converted %d file%s in %.1fs, %d failed — left in the "
                           "list, press CONVERT to retry"
                           % (len(ok), "" if len(ok) == 1 else "s", took,
                              len(failed)))
            self.status_error = True
        else:
            self.status = ("Converted %d file%s in %.1fs to %s"
                           % (len(ok), "" if len(ok) == 1 else "s", took,
                              self.output_dir))
            extras = self._written_extras()
            if extras:
                self.status += " — plus %s beside it" % " and ".join(extras)
            self.status_error = False

    def _written_extras(self) -> List[str]:
        """The .MID / .SF2 a DS ROM left next to the output, if any."""
        newest = self.results[0] if self.results else None
        names = getattr(newest, "assets", None) or []
        return sorted({os.path.splitext(name)[1].upper() for name in names})

    # ---------------------------------------------------------------- playback

    def play(self, index: int, start: float = 0.0) -> None:
        if not (0 <= index < len(self.results)):
            return
        result = self.results[index]
        if not result.ok or not self.mixer_ready:
            return
        try:
            pygame.mixer.music.load(result.wav_path)
            if start > 0.01:
                pygame.mixer.music.play(start=start)
            else:
                pygame.mixer.music.play()
            self.playing = index
        except Exception as error:
            self.status = "Could not play: %s" % error
            self.status_error = True

    def stop(self) -> None:
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self.playing = None

    def save_result(self, index: int) -> None:
        if not (0 <= index < len(self.results)):
            return
        result = self.results[index]
        destination = dialogs.save_as(os.path.basename(result.wav_path) or "song.wav")
        if not destination:
            self.status = "Already saved to %s" % result.wav_path
            return
        try:
            with open(result.wav_path, "rb") as source, \
                    open(destination, "wb") as out:
                out.write(source.read())
            self.status = "Copied to %s" % destination
            self.status_error = False
        except OSError as error:
            self.status = "Could not save: %s" % error
            self.status_error = True

    def open_folder(self, index: int) -> None:
        if 0 <= index < len(self.results):
            dialogs.reveal(self.results[index].wav_path)

    # ------------------------------------------------------------------ events

    def handle_event(self, event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.VIDEORESIZE:
            self.screen = pygame.display.set_mode(
                (max(MIN_WIDTH, event.w), max(MIN_HEIGHT, event.h)), pygame.RESIZABLE)
        elif event.type == pygame.DROPFILE:
            for path in (getattr(event, "files", None) or [event.file]):
                self.add_path(path)
        elif event.type == pygame.MOUSEWHEEL:
            if self.song_window:
                self.move_song(-event.y * 3)
                return
            rows = max(1, self.pattern_height // 10)
            if self.mouse_in_pattern:
                if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                    self.pattern_column = max(0, self.pattern_column - event.y)
                else:
                    self.pattern_row = max(0, self.pattern_row - event.y * rows)
            elif self.mouse_in_queue:
                self.scroll_queue = max(0, self.scroll_queue - event.y)
            elif self.mouse_in_results:
                self.scroll_results = max(0, self.scroll_results - event.y)
        elif event.type == pygame.KEYDOWN:
            if self.song_window:
                self._song_window_key(event)
                return
            page = max(1, self.pattern_height // self._row_height())
            if event.key == pygame.K_UP:
                self.pattern_row = max(0, self.pattern_row - 1)
            elif event.key == pygame.K_DOWN:
                self.pattern_row += 1
            elif event.key == pygame.K_PAGEUP:
                self.pattern_row = max(0, self.pattern_row - page)
            elif event.key == pygame.K_PAGEDOWN:
                self.pattern_row += page
            elif event.key == pygame.K_LEFT:
                self.pattern_column = max(0, self.pattern_column - 1)
            elif event.key == pygame.K_RIGHT:
                self.pattern_column += 1
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.start_convert()
            elif event.key == pygame.K_SPACE:
                self.stop() if self.playing is not None else self.play(0)
            elif event.key == pygame.K_o and event.mod & pygame.KMOD_CTRL:
                self.pick_files()
            elif event.key == pygame.K_ESCAPE:
                if self.playing is not None:
                    self.stop()
                else:
                    self.running = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.mouse = event.pos
            # The click goes to the *smallest* control under the pointer, so a
            # button always beats the panel it sits on, whatever order they
            # happened to be drawn in. That was a real bug once: a panel-wide
            # "click empty space" rectangle drew last and ate every button in it.
            under = [hit for hit in self.hits if hit[0].collidepoint(event.pos)]
            if under:
                rect, action = min(under, key=lambda hit: hit[0].width *
                                   hit[0].height)
                action()

    def _song_window_key(self, event) -> None:
        """Keys while the song browser is open: pick, use, or leave."""
        row_h = self.song_window["row_h"] if self.song_window else 22
        visible = max(1, (self.song_list_view.height - 4) // row_h) \
            if self.song_list_view.height else 8
        if event.key == pygame.K_ESCAPE:
            self.close_songs()
        elif event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
            self.use_song()
        elif event.key == pygame.K_UP:
            self.move_song(-1)
        elif event.key == pygame.K_DOWN:
            self.move_song(1)
        elif event.key == pygame.K_PAGEUP:
            self.move_song(-visible)
        elif event.key == pygame.K_PAGEDOWN:
            self.move_song(visible)
        elif event.key == pygame.K_HOME:
            self.move_song(-len(self._window_songs()))
        elif event.key == pygame.K_END:
            self.move_song(len(self._window_songs()))
        elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_RIGHT):
            self.change_bank(1)
        elif event.key in (pygame.K_MINUS, pygame.K_LEFT):
            self.change_bank(-1)
        elif getattr(event, "unicode", "") and event.unicode.isprintable() \
                and event.unicode.strip():
            self.jump_to_song(event.unicode)
        self._scroll_song_into_view()

    def jump_to_song(self, typed: str) -> None:
        """Type a few letters to jump to the song that starts with them."""
        window = self.song_window
        songs = self._window_songs()
        if not window or not songs:
            return
        now = time.time()
        if now - self._song_typed_at > 1.2:
            self._song_typed = ""
        self._song_typed_at = now
        self._song_typed += typed.lower()
        # "bgm15", "bgm_15" and "BGM 15" are the same name to a person typing
        wanted = "".join(ch for ch in self._song_typed if ch.isalnum())
        names = ["".join(ch for ch in name.lower() if ch.isalnum())
                 for _index, _bank, name in songs]
        start = window["selected"]
        for matcher in (str.startswith, None):
            for offset in range(1, len(songs) + 1):
                position = (start + offset) % len(songs)
                hit = (names[position].startswith(wanted) if matcher
                       else wanted in names[position])
                if hit and wanted:
                    window["selected"] = position
                    self._scroll_song_into_view()
                    self.status = "Jumped to %s" % songs[position][2]
                    return

    # ----------------------------------------------------------------- switches


    def toggle_chip(self, name: str) -> None:
        """Switch one chip on or off.

        "nes" is the first NES APU, which is a chip like any other: a PC Engine
        arrangement is six PC Engine voices, not a NES with six extras bolted on.
        The one rule is that a console has to be left: an empty desk cannot
        convert anything.
        """
        if name == "nes":
            if self.settings.base:
                if not any(other in self.settings.extensions
                           for other in chips.CONSOLES):
                    self.status = ("That is the only console on — switch on "
                                   "PC ENGINE (or 2x NES) first")
                    self.status_error = True
                    return
                self.settings.base = False
            else:
                self.settings.base = True
            self._save_settings()
            self.status = "Playing on %s" % self.console_label()
            self.status_error = False
            return
        if name in self.settings.extensions:
            if name in chips.CONSOLES and len(self.settings.extensions) == 1 \
                    and not self.settings.base:
                self.status = ("That is the only console on — switch on NES or "
                               "another console first")
                self.status_error = True
                return
            self.settings.extensions.remove(name)
        else:
            self.settings.extensions.append(name)
        self._save_settings()
        self.status = "Playing on %s" % self.console_label()
        self.status_error = False

    def console_label(self) -> str:
        """What the console currently is, for the status line and the header."""
        names = ["THE NES"] if self.settings.base else []
        names += [chips.CHIP_LABELS.get(name, name.upper())
                  for name in self.settings.extensions
                  if name in chips.CONSOLES]
        extra = [name for name in self.settings.extensions
                 if name not in chips.CONSOLES]
        if extra:
            names.append("%d CARTRIDGE CHIP%s" % (len(extra),
                                                  "" if len(extra) == 1 else "S"))
        return " + ".join(names) or "nothing at all"

    def all_chips(self) -> None:
        """Everything on: both consoles and every cartridge chip."""
        if len(self.settings.extensions) == len(chips.EXTENSION_CHANNELS) \
                and self.settings.base:
            self.settings.extensions = []
        else:
            self.settings.base = True
            self.settings.extensions = chips.ordered_extensions()
        self._save_settings()

    def no_chips(self) -> None:
        """Nothing but one NES — the plain four-voice console."""
        self.settings.base = True
        self.settings.extensions = []
        self._save_settings()

    def toggle_bits(self) -> None:
        self.settings.bits = 8 if self.settings.bits > 8 else 16
        self._save_settings()

    def set_bits(self, bits: int) -> None:
        if self.settings.bits != bits:
            self.settings.bits = bits
            self._save_settings()

    def step_rate(self, step: int) -> None:
        """Walk the sample rates the mix can be rendered at."""
        rates = list(RATES)
        current = self.settings.rate
        if current in rates:
            position = rates.index(current)
        else:
            position = min(range(len(rates)),
                           key=lambda i: abs(rates[i] - current))
        position = max(0, min(len(rates) - 1, position + step))
        if rates[position] != current:
            self.settings.rate = rates[position]
            self._save_settings()

    def step_chips(self, step: int) -> None:
        """One extension chip on or off, in the CHIPS panel's own order."""
        names = chips.ordered_extensions()
        if not names:
            return
        if step > 0:
            for name in names:
                if name not in self.settings.extensions:
                    self.settings.extensions.append(name)
                    self._save_settings()
                    return
        else:
            for name in reversed(names):
                if name in self.settings.extensions:
                    self.settings.extensions.remove(name)
                    self._save_settings()
                    return

    def toggle_vgm(self) -> None:
        self.settings.export_vgm = not self.settings.export_vgm
        self._save_settings()

    def toggle_drums(self) -> None:
        self.settings.sampled_drums = not self.settings.sampled_drums
        self._save_settings()

    def chip_count(self) -> int:
        """How many chips are on, counting the NES APU when it is one of them."""
        return (1 if self.settings.base else 0) + len(self.settings.extensions)

    def voice_count(self) -> int:
        return (4 if self.settings.base else 0) + sum(
            len(chips.EXTENSION_CHANNELS[name])
            for name in self.settings.extensions
            if name in chips.EXTENSION_CHANNELS)

    # ---------------------------------------------------------------- geometry

    def _row_height(self) -> int:
        return self.fonts["pattern"].get_height() + 6

    def _layout(self):
        """Every panel in the window, recomputed from the current size.

        The shape is FamiTracker's: a strip of live numbers at the top, a toolbar
        under it, the pattern page as the biggest thing on the desk, and the
        chips / files / converted panels down the right-hand side. Nothing is
        beveled and nothing overlaps, so every panel is one flat rectangle with a
        hairline around it.
        """
        width, height = self.screen.get_size()
        outer = pygame.Rect(0, 0, width, height)
        content = outer.inflate(-8, -8)

        top_h = 46            # the live number boxes
        toolbar_h = 40        # ADD / CONVERT / PLAY …
        status_h = 26
        info_h = 64           # three lines of "what I found"
        mixer_h = 62          # the channel meters
        right_w = max(272, min(322, int(content.width * 0.25)))

        top = pygame.Rect(content.x, content.y, content.width, top_h)
        toolbar = pygame.Rect(content.x, top.bottom + 4, content.width, toolbar_h)
        status = pygame.Rect(content.x, content.bottom - status_h, content.width,
                             status_h)

        # the analysis strip and the channel meters run the whole width, the way
        # a tracker keeps its song info and its scopes across the top; only the
        # pattern page and the side panels share the height below them
        info = pygame.Rect(content.x, toolbar.bottom + 4, content.width, info_h)
        mixer = pygame.Rect(content.x, info.bottom + 4, content.width, mixer_h)
        body_top = mixer.bottom + 4
        body_bottom = status.y - 4
        side = pygame.Rect(content.right - right_w, body_top, right_w,
                           body_bottom - body_top)
        pattern = pygame.Rect(content.x, body_top, side.x - content.x - 6,
                              body_bottom - body_top)
        return outer, content, top, toolbar, info, mixer, pattern, side, status

    def _pattern_rect(self) -> pygame.Rect:
        """The panel the pattern page sits in."""
        return self._layout()[6]

    def _pattern_page(self) -> pygame.Rect:
        """The pattern page itself: the dark well inside that panel."""
        rect = self._pattern_rect()
        return pygame.Rect(rect.x + 4, rect.y + 4, rect.width - 8, rect.height - 8)

    # ----------------------------------------------------------------- drawing

    def _needs_redraw(self) -> bool:
        """Whether this frame has anything new to show.

        A still window — nothing playing, no batch running, no event — has
        nothing to redraw, and painting a 1200x830 desk sixty times a second only
        to produce the identical picture is where a lot of the old stutter came
        from. Anything that plays or works redraws every frame, because the play
        cursor and the progress bars move; otherwise the window redraws when
        something happened, with a slow refresh as a safety net.
        """
        if self._dirty:
            self._dirty = False
            return True
        if self.busy or self.playing is not None:
            return True
        return time.time() - self._last_draw > 0.5

    def draw(self) -> None:
        self.hits = []
        self.songs_buttons = []
        self.song_rows = []
        self.toolbar_rects = []
        self.mouse = pygame.mouse.get_pos()
        t = self.theme
        self.screen.fill(t.desktop)

        (outer, _content, top, toolbar, info, mixer,
         pattern, side, status) = self._layout()
        theme.frame(self.screen, outer, t)

        self._draw_top(top)
        self._draw_toolbar(toolbar)
        self._draw_info(info)
        self._draw_mixer(mixer)
        self._draw_pattern(pattern)
        self._draw_side(side)
        self._draw_status(status)
        if self.song_window:
            # The browser is modal: nothing behind it can be clicked while it is
            # open, so a stray click cannot start a conversion or move the queue.
            self.hits = []
            self._draw_song_window(outer)
        self._last_draw = time.time()

    def _surface(self, font: str, text: str, colour) -> pygame.Surface:
        """A rendered line, kept between frames.

        The pattern page, the channel meters and the chip rows draw the same few
        hundred strings over and over. Re-rendering antialiased text every frame
        was the single biggest cost in the window; this keeps them. The cache is
        bounded, so a thousand file names cannot grow it without limit.
        """
        key = (font, text, colour)
        cache = self._text_cache
        found = cache.get(key)
        if found is None:
            if len(cache) > 1500:
                cache.clear()
            found = self.fonts[font].render(text, self.theme.smooth, colour)
            cache[key] = found
        return found

    def _text(self, x, y, text, font="body", color=None):
        t = self.theme
        surface = self._surface(font, text, color or t.text)
        self.screen.blit(surface, (x, y))
        return surface

    def _title_bar(self, rect: pygame.Rect) -> pygame.Rect:
        font = self.fonts["tiny"]
        height = max(16, font.get_height() + 3)
        return pygame.Rect(rect.x + 3, rect.y + 3, rect.width - 6, height)

    def _tiny_buttons(self, panel_rect: pygame.Rect, entries) -> None:
        """Small switches living in a panel's title line (ALL / NONE / ADD…)."""
        bar = self._title_bar(panel_rect)
        x = bar.right - 3
        for label, action, width in reversed(entries):
            box = pygame.Rect(x - width, bar.y + 1, width, bar.height - 2)
            theme.button(self.screen, box, self.theme, label,
                         self.fonts["tiny"])
            self.hits.append((box.copy(), action))
            x = box.x - 4

    def _button(self, rect, label, action, pressed=False, enabled=True,
                primary=False, font="button"):
        theme.button(self.screen, rect, self.theme, label, self.fonts[font],
                     pressed=pressed, enabled=enabled, primary=primary)
        if enabled:
            self.hits.append((rect.copy(), action))

    # ------------------------------------------------------------------ header

    # ------------------------------------------------------------------- top

    def _draw_top(self, rect: pygame.Rect) -> None:
        """The strip along the top: the name, and four live number boxes."""
        t = self.theme
        self.screen.fill(t.panel, rect)
        pygame.draw.rect(self.screen, t.dark, rect, 1)
        self._draw_mark(pygame.Rect(rect.x + 16, rect.y, 330, rect.height))

        more_chips = lambda: self.step_chips(1)          # noqa: E731
        fewer_chips = lambda: self.step_chips(-1)        # noqa: E731
        groups = [
            ("VOICES", "%02d" % self.voice_count(), more_chips, fewer_chips),
            ("CHIPS", "%02d" % self.chip_count(), more_chips, fewer_chips),
            ("BITS", "%02d" % self.settings.bits,
             lambda: self.set_bits(16), lambda: self.set_bits(8)),
            ("RATE", "%dk" % (self.settings.rate // 1000),
             lambda: self.step_rate(1), lambda: self.step_rate(-1)),
        ]

        arrow_w, box_w = 23, 44
        label_font = self.fonts["tiny"]
        x = rect.right - 14
        for label, value, up_action, down_action in reversed(groups):
            label_w = label_font.size(label)[0]
            x -= label_w + 8 + box_w + 3 + arrow_w
            self.screen.blit(self._surface("tiny", label, t.dim),
                             (x, rect.centery - label_font.get_height() // 2))
            box = pygame.Rect(x + label_w + 8, rect.centery - 13, box_w, 26)
            theme.numeric(self.screen, box, t, value, self.fonts["small"])
            up = pygame.Rect(box.right + 3, box.y, arrow_w, 12)
            down = pygame.Rect(box.right + 3, box.y + 14, arrow_w, 12)
            for arrow_rect, direction, action in ((up, "up", up_action),
                                                  (down, "down", down_action)):
                theme.arrow(self.screen, arrow_rect, t, direction)
                if action:
                    self.hits.append((arrow_rect.copy(), action))
            x -= 20

    def _draw_mark(self, rect: pygame.Rect) -> None:
        """The name, and what the program is, on one line."""
        t = self.theme
        font = self.fonts["title"]
        parts = (("chip", t.text), ("8", t.accent), ("bit", t.text))
        x = rect.x
        y = rect.centery - font.get_height() // 2
        for text, colour in parts:
            surface = self._surface("title", text, colour)
            self.screen.blit(surface, (x, y))
            x += surface.get_width()
        caption = self._surface("small", "NES / 8-bit transcoder", t.dim)
        self.screen.blit(caption, (x + 12, rect.centery - caption.get_height() // 2))

    def _draw_info(self, rect: pygame.Rect) -> None:
        """What the converter found in the file, and what it is unsure about.

        This used to be a titled panel with a sunken well around it, which cost a
        third of the top of the window and read like a 1995 message box. It is a
        strip now: the analysis on two lines, the kept/left-out totals on the
        right of the first, and — if the conversion has something to confess — a
        warning line under them instead of leaving the listener to wonder.
        """
        t = self.theme
        self.screen.fill(t.panel, rect)
        pygame.draw.rect(self.screen, t.dark, rect, 1)
        self.screen.fill(t.accent, (rect.x + 1, rect.y + 1, 3, rect.height - 2))

        # the kept / left-out totals get their own accent line on the right, so
        # the strip does not say the same number twice
        lines = [line for line in self._found_lines()
                 if "notes kept" not in line]
        keys = ("body", "small", "small")
        colours = (t.field_text, t.pattern_inst, t.pattern_vol)
        analysis_lines = lines[:2]

        advice = self._advice_line()
        summary = "" if advice else self._result_summary()
        totals = self._surface("tiny", summary, t.accent) if summary else None

        x = rect.x + 14
        y = rect.y + 7
        for position, text in enumerate(analysis_lines):
            if not text:
                continue
            key = keys[min(position, 2)]
            font = self.fonts[key]
            room = rect.right - x - 14
            if position == 0 and totals is not None:
                # the totals sit at the right of the first row, so the song name
                # stops before them instead of running underneath
                room -= totals.get_width() + 16
            surface = self._surface(key, _fit(font, text, room),
                                    colours[min(position, 2)])
            self.screen.blit(surface, (x, y))
            y += font.get_height() + 3

        if totals is not None:
            self.screen.blit(totals, (rect.right - totals.get_width() - 14,
                                      rect.y + 9))
        if advice:
            surface = self._surface("tiny", _fit(self.fonts["tiny"], "! " + advice,
                                                 rect.width - 28), t.warn)
            self.screen.blit(surface, (x, y))

    def _advice_line(self) -> str:
        """The one thing worth knowing about the selected conversion, if any."""
        if not self.results:
            return ""
        chosen = self.results[min(self.selected_result, len(self.results) - 1)]
        advice = getattr(chosen, "advice", None)
        return advice[0] if advice else ""

    def _result_summary(self) -> str:
        """The one-line totals for the selected conversion, or nothing."""
        if not self.results:
            return ""
        result = self.results[min(self.selected_result, len(self.results) - 1)]
        if not result.ok:
            return "CONVERSION FAILED"
        text = "%d KEPT" % result.kept
        if getattr(result, "left_out", 0):
            text += " · %d OUT" % result.left_out
        if getattr(result, "thinned", 0):
            text += " · %d THINNED" % result.thinned
        return text

    def _draw_toolbar(self, rect: pygame.Rect) -> None:
        """The toolbar: one flat row of buttons, the way a tracker has one."""
        t = self.theme
        self.screen.fill(t.panel, rect)
        pygame.draw.rect(self.screen, t.dark, rect, 1)

        has_results = bool(self.results)
        buttons = [
            ("ADD MUSIC", self.pick_files, True, False),
            ("DEMO", self.add_demo, True, False),
            (None, None, False, False),
            ("CONVERT %d" % len(self.items) if self.items else "CONVERT",
             self.start_convert, bool(self.items) and not self.busy, True),
            ("STOP", self.stop, self.playing is not None or self.busy, False),
            (None, None, False, False),
            ("PLAY", self.play_selected, has_results, False),
            ("SAVE AS", self.save_selected, has_results, False),
            ("FOLDER", self.open_folder_selected, has_results, False),
        ]
        height = 30
        x = rect.x + 8
        y = rect.y + (rect.height - height) // 2
        font = self.fonts["button"]
        for label, action, enabled, primary in buttons:
            if label is None:
                self.screen.fill(t.dark, (x + 4, y + 5, 1, height - 10))
                x += 16
                continue
            width = max(80, font.size(label)[0] + 26)
            box = pygame.Rect(x, y, width, height)
            hover = enabled and box.collidepoint(self.mouse)
            theme.button(self.screen, box, t, label, font,
                         pressed=(primary and self.busy), enabled=enabled,
                         primary=primary, hover=hover)
            self.toolbar_rects.append(box.copy())
            if enabled:
                self.hits.append((box.copy(), action))
            if action == self.start_convert:
                self.convert_rect = box.copy()
            elif action == self.play_selected:
                self.play_rect = box.copy()
            x += width + 6

        # the rest of the strip says what the queue is doing, which is the one
        # thing you look at before pressing CONVERT
        if self.busy:
            hint, colour = (self.progress_label or "working", t.warn)
        elif self.items:
            hint = "%d FILE%s READY" % (len(self.items),
                                        "" if len(self.items) == 1 else "S")
            colour = t.pattern_inst
        else:
            hint, colour = "DROP MUSIC ANYWHERE ON THIS WINDOW", t.pattern_empty
        surface = self._surface("tiny", _fit(self.fonts["tiny"], hint,
                                             rect.right - x - 24), colour)
        self.screen.blit(surface, (rect.right - surface.get_width() - 12,
                                   rect.centery - surface.get_height() // 2))

    def _found_lines(self):
        if not self.results:
            return ["No file analysed yet — add music, then press CONVERT",
                    "drop .mid .vgm .vgz .gym .nds .sdat .zip anywhere on this window",
                    "", ""]
        result = self.results[min(self.selected_result, len(self.results) - 1)]
        if not result.ok:
            return ["Could not convert %s" % (result.name or "that file"),
                    (result.error or "unknown problem"),
                    "the file is still in the list — try another format",
                    ""]
        lines = list(getattr(result, "analysis_lines", []) or [])
        if not lines:
            lines = ["Converted %s" % os.path.basename(result.wav_path)]
        out = []
        if result.song and result.song_count > 1:
            out.append("%s · song %d of %d · %s" % (
                result.name or "that file", result.song_index,
                result.song_count, result.song))
        for line in lines:
            if line.startswith("Instruments: "):
                out.append("Instr: " + line[len("Instruments: "):])
            elif line.startswith("Found "):
                out.append(line)
        if len(out) < 2:
            out = out + lines[:1]
        if result.ok:
            kept = "%d notes kept" % result.kept
            if getattr(result, "left_out", 0):
                kept += " · %d left out" % result.left_out
            if getattr(result, "thinned", 0):
                kept += " · %d lines thinned" % result.thinned
            out.append(kept)
            waves = getattr(result, "waves", None)
            if waves:
                # what the PC Engine was told to load into its wave RAM
                shown = sorted(waves.items(), key=lambda item: -item[1])[:4]
                out.append("PC Engine wave RAM: " + ", ".join(
                    "%s x%d" % (waves_module.describe(name), count)
                    for name, count in shown))
        while len(out) < 4:
            out.append("")
        return out[:4]

    def request_quit(self) -> None:
        self.running = False

    # ------------------------------------------------------------------- scope

    # ----------------------------------------------------------------- meters

    def _draw_mixer(self, rect: pygame.Rect) -> None:
        """The row of channel meters: one cell per voice the console can have.

        Two rows of sixteen holds every voice there is (4 APU + the cartridge
        chips + a second NES + a PC Engine = 32), and each cell shows the voice's
        name and how much of the song it plays. While music plays, the voices
        sounding under the playhead light up.

        The cells are painted once into a surface and kept: this used to walk
        every note of the song once per cell, thirty-two times a frame, which was
        5.8 ms of the frame for a picture that hardly changes.
        """
        t = self.theme
        self.screen.fill(t.panel, rect)
        pygame.draw.rect(self.screen, t.dark, rect, 1)
        area = pygame.Rect(rect.x + 4, rect.y + 4, rect.width - 8, rect.height - 8)

        self._pattern_data()            # cached, and the meters read its counts
        active = tuple(spec.id for spec in self.settings.channels())
        every = tuple(spec.id for spec in
                      chips.build_channel_set(chips.ordered_extensions()))
        key = (every, active, area.size, self._pattern_key)
        if key != self._mixer_key or self._mixer_surface is None:
            self._mixer_surface, self._mixer_cells = self._paint_mixer(
                area.size, every, active)
            self._mixer_key = key
        self.screen.blit(self._mixer_surface, area.topleft)

        if self.playing is None:
            return
        position = pygame.mixer.music.get_pos() if pygame.mixer.get_init() else -1
        if position < 0:
            return
        live = self._sounding(position / 1000.0)
        if not live:
            return
        for channel, cell, bar in self._mixer_cells:
            if channel not in live:
                continue
            box = cell.move(area.topleft)
            pygame.draw.rect(self.screen, t.accent, box, 1)
            self.screen.fill(t.accent, bar.move(area.topleft))

    def _paint_mixer(self, size, every, active):
        """Paint the static meter cells; returns the surface and their geometry."""
        t = self.theme
        surface = pygame.Surface(size)
        surface.fill(t.panel)
        per_row, rows, gap = 16, 2, 3
        cell_w = (size[0] - (per_row - 1) * gap) // per_row
        cell_h = (size[1] - (rows - 1) * gap) // rows
        counts = self._note_counts
        busiest = max(counts.values()) if counts else 0
        cells = []
        for index, channel in enumerate(every[:per_row * rows]):
            cell = pygame.Rect((index % per_row) * (cell_w + gap),
                               (index // per_row) * (cell_h + gap), cell_w, cell_h)
            on = channel in active
            surface.fill(t.field if on else t.stripe, cell)
            pygame.draw.rect(surface, t.dark, cell, 1)
            number = self._surface("tiny", "%02d" % (index + 1),
                                   t.pattern_vol if on else t.pattern_empty)
            surface.blit(number, (cell.x + 4, cell.y + 2))
            name_colour = t.field_text if on else t.pattern_empty
            name = self._surface("tiny", _channel_short(channel), name_colour)
            name_x = cell.x + 4 + number.get_width() + 5
            if name_x + name.get_width() <= cell.right - 3:
                # a narrow window shows the number alone rather than half a name
                surface.blit(name, (name_x, cell.y + 2))
            bar = pygame.Rect(cell.x + 4, cell.bottom - 6, cell.width - 8, 3)
            surface.fill(t.pattern_empty, bar)
            count = counts.get(channel, 0)
            if on and count and busiest:
                width = max(2, int(bar.width * count / float(busiest)))
                surface.fill(t.pattern_inst, (bar.x, bar.y, width, bar.height))
            cells.append((channel, cell, bar))
        return surface, cells

    def _sounding(self, at: float):
        """Which voices have a note under the playhead, right now."""
        live = set()
        for channel, starts in self._note_starts.items():
            spans = self._note_spans[channel]
            index = bisect.bisect_right(starts, at) - 1
            for probe in range(max(0, index - 3), index + 1):
                if spans[probe][1] > at:
                    live.add(channel)
                    break
        return live

    def _draw_scope_trace(self, box: pygame.Rect, channel: str, result,
                          duration: float) -> None:
        """A little waveform for one voice, like FT2's channel scopes.

        Each note is a burst of up/down strokes whose height follows its volume,
        sitting on the baseline of the box: it reads as "this voice is playing
        here", which is what the scopes in the screenshot tell you at a glance.
        """
        t = self.theme
        inner = pygame.Rect(box.x + 2, box.y + 13, box.width - 4, box.height - 15)
        if inner.width <= 4 or inner.height <= 6:
            return
        mid = inner.centery
        notes = []
        if result is not None and getattr(result, "notes", None):
            notes = [n for n in result.notes if n.channel == channel]
        baseline = t.pattern_empty
        if not notes:
            self.screen.fill(baseline, (inner.x, mid, inner.width, 1))
            tag = self.fonts["head"].render("- - -", t.smooth, baseline)
            self.screen.blit(tag, (inner.x + 4, mid - tag.get_height() // 2))
            return

        self.screen.fill(baseline, (inner.x, mid, inner.width, 1))
        colour = t.field_text
        for note in notes:
            start = int((note.start / duration) * inner.width)
            end = int((note.end() / duration) * inner.width)
            width = max(2, min(10, end - start))
            level = max(0.2, min(1.0, note.volume / 15.0))
            amplitude = max(1, int(level * (inner.height // 2 - 1)))
            step = 2
            for offset in range(0, width, step):
                x = inner.x + start + offset
                if x >= inner.right:
                    break
                top = mid - amplitude if offset % 4 == 0 else mid - amplitude // 3
                bottom = mid + amplitude if offset % 4 == 0 else mid + amplitude // 3
                self.screen.fill(colour, (x, top, 1, max(1, bottom - top)))

    # ----------------------------------------------------------- pattern data

    # ----------------------------------------------------------- pattern data

    def _pattern_data(self):
        """Rows of channel cells for the last conversion, in tracker form.

        The row length is chosen from the music, not fixed: a 226 BPM tune needs
        shorter rows than a 90 BPM one, otherwise two notes land in the same cell
        and the page silently hides half the song.

        The answer is cached. The window used to ask for this three times every
        frame — the meters, the page and a click — and each answer walked every
        note of the song five times over to pick that row length, which was tens
        of milliseconds a frame on a long tune and the reason scrolling stuttered.
        """
        result = self.results[self.selected_result] if self.results else None
        channels = tuple(spec.id for spec in self.settings.channels())
        key = (id(result), self.selected_result, len(self.results), channels)
        if key == self._pattern_key:
            return self._pattern_cache
        data = self._build_pattern(result, channels)
        self._pattern_key = key
        self._pattern_cache = data
        return data

    def _build_pattern(self, result, channel_ids):
        """The uncached half of `_pattern_data`, plus what the meters need."""
        self._note_counts: Dict[str, int] = {}
        self._note_spans: Dict[str, List[tuple]] = {}
        self._note_starts: Dict[str, List[float]] = {}
        if result is None or not getattr(result, "notes", None):
            return None, [], 0.0, 0, {}

        for note in result.notes:
            if note.channel:
                self._note_counts[note.channel] = \
                    self._note_counts.get(note.channel, 0) + 1
                self._note_spans.setdefault(note.channel, []).append(
                    (note.start, note.end()))
        for channel, spans in self._note_spans.items():
            spans.sort()
            self._note_starts[channel] = [span[0] for span in spans]

        tempo = float(getattr(result, "tempo", 0.0) or 120.0)
        channels = list(channel_ids)
        for note in result.notes:
            if note.channel and note.channel not in channels:
                channels.append(note.channel)
        index_of = {name: index for index, name in enumerate(channels)}

        # Pick the row length from the music: the longest rows that still leave
        # almost every note in its own cell. A fast tune gets short rows instead of
        # a page that hides half of it.
        #
        # The search counts collisions in a set and only builds the note cells
        # once, for the speed that wins. Building five grids of lists for a
        # three-minute tune allocated tens of thousands of objects, and those
        # allocations are what kept waking the garbage collector mid-repaint.
        tolerance = max(2, int(len(result.notes) * 0.01))
        row_seconds = None
        fewest = tolerance + 1
        for speed in (PATTERN_SPEED, 4, 3, 2, 1):
            candidate = 2.5 * speed / max(30.0, tempo)
            seen = set()
            collisions = 0
            for note in result.notes:
                if note.channel in index_of:
                    key = (int(note.start / candidate), index_of[note.channel])
                    if key in seen:
                        collisions += 1
                    else:
                        seen.add(key)
            if collisions <= tolerance:
                row_seconds = candidate        # coarsest page that still works
                break
            if collisions < fewest:
                row_seconds, fewest = candidate, collisions
        if row_seconds is None:
            row_seconds = 2.5 * PATTERN_SPEED / max(30.0, tempo)
        grid: Dict[tuple, List] = {}
        for note in result.notes:
            if note.channel in index_of:
                grid.setdefault((int(note.start / row_seconds),
                                 index_of[note.channel]), []).append(note)

        rows = int(max(n.end() for n in result.notes) / row_seconds) + 2
        return result, channels, row_seconds, rows, grid

    def _draw_pattern(self, rect: pygame.Rect) -> None:
        t = self.theme
        self.screen.fill(t.panel, rect)
        pygame.draw.rect(self.screen, t.dark, rect, 1)
        page = self._pattern_page()
        theme.field(self.screen, page, t, t.field)
        self.mouse_in_pattern = page.collidepoint(self.mouse)

        data = self._pattern_data()
        if data[0] is None:
            self._empty_pattern(page)
            self.pattern_height = 0
            self.hits.append((page, self._pattern_click))
            return
        result, channels, row_seconds, rows, grid = data

        info_h = self.fonts["head"].get_height() + 8
        head_h = self._pattern_head_height()
        row_h = self._row_height()
        font = self.fonts["pattern"]
        gutter = 34
        cell = font.size("D#6 3 ---")[0] + 12
        jump_w = 46
        pages = (rows + PATTERN_ROWS - 1) // PATTERN_ROWS
        usable = page.width - (jump_w + 20 if pages > 1 else 14) - 10
        columns = max(1, min(len(channels), usable // (cell + gutter // 2)))
        while columns > 1 and (columns * cell + _groups(columns) * gutter) > usable:
            columns -= 1
        spare = usable - columns * cell - _groups(columns) * gutter
        if columns and spare > 0:
            cell += min(26, spare // columns)
        self.pattern_columns = columns
        self.pattern_column = max(0, min(self.pattern_column,
                                         max(0, len(channels) - columns)))
        first = self.pattern_column

        reserve = 14 if len(channels) > columns else 0
        visible = max(1, (page.height - head_h - 8 - reserve) // row_h)
        self.pattern_height = visible * row_h
        max_rows = max(visible, rows)
        self.pattern_row = max(0, min(self.pattern_row, max_rows - visible))

        playing_row = None
        if self.playing is not None and pygame.mixer.get_init():
            position = pygame.mixer.music.get_pos()
            if position >= 0:
                playing_row = int(position / 1000.0 / row_seconds)
                self.pattern_row = max(
                    0, min(playing_row - visible // 2, max_rows - visible))

        cursor_row = self.pattern_row
        if self.mouse_in_pattern:
            offset = self.mouse[1] - (page.y + head_h)
            if offset >= 0:
                cursor_row = self.pattern_row + offset // row_h

        positions = []
        x = 4
        for slot in range(columns):
            if slot % GROUP_SIZE == 0:
                x += gutter
            positions.append(x)
            x += cell

        self._draw_pattern_info(pygame.Rect(page.x + 4, page.y + 4,
                                            page.width - 8, info_h),
                                channels, cursor_row, row_seconds, rows, result,
                                grid)
        self._draw_channel_head(page, info_h, head_h,
                                [page.x + 2 + value for value in positions],
                                cell, channels, first)

        # The rows are painted into one surface and kept between frames: while
        # the music plays, a frame is then one blit plus the cursor, instead of
        # redrawing several hundred note cells sixty times a second.
        body_key = (id(result), first, self.pattern_row, visible, columns, cell,
                    row_h, playing_row if playing_row is not None and
                    self.pattern_row <= playing_row < self.pattern_row + visible
                    else None, cursor_row, page.width, page.height)
        if body_key != self._body_key or self._body_surface is None:
            self._body_key = body_key
            self._body_surface = self._paint_rows(
                (page.width - 4, visible * row_h), channels, grid, first, columns,
                visible, positions, cell, gutter, row_h, playing_row, cursor_row)
        self.screen.blit(self._body_surface, (page.x + 2, page.y + head_h))

        if pages > 1:
            self._draw_jump_strip(
                pygame.Rect(page.right - jump_w - 18, page.y + head_h, jump_w,
                            page.height - head_h - 6), rows, visible, row_seconds)

        if rows > visible:
            bar = pygame.Rect(page.right - 12, page.y + head_h, 10,
                              page.height - head_h - 8)
            theme.scrollbar(self.screen, bar, t,
                            self.pattern_row / max(1, rows - visible),
                            visible / max(1, rows))
        if len(channels) > columns:
            bar = pygame.Rect(page.x + 4, page.bottom - 10, page.width - 24, 8)
            theme.scrollbar(self.screen, bar, t,
                            first / max(1, len(channels) - columns),
                            columns / max(1, len(channels)))

        self.hits.append((page, self._pattern_click))

    def _paint_rows(self, size, channels, grid, first, columns, visible, positions,
                    cell, gutter, row_h, playing_row, cursor_row):
        """Paint the pattern rows (numbers, gaps, notes) into their own surface."""
        t = self.theme
        surface = pygame.Surface(size)
        surface.fill(t.field)
        head = self.fonts["head"]
        empty = self._surface("pattern", "--- · ---", t.pattern_empty)
        for slot in range(visible):
            row_index = self.pattern_row + slot
            y = slot * row_h
            row_rect = pygame.Rect(0, y, size[0], row_h)
            highlight = playing_row is not None and row_index == playing_row
            if highlight:
                surface.fill(t.playing, row_rect)
            elif row_index % 4 == 0:
                surface.fill(t.stripe, row_rect)

            pattern_row = row_index % PATTERN_ROWS
            number_colour = (t.pattern_row_beat if pattern_row % 16 == 0
                             else t.pattern_row)
            if highlight:
                number_colour = t.playing_text
            for slot_index in range(0, columns, GROUP_SIZE):
                number = self._surface("head", "%02X" % pattern_row, number_colour)
                surface.blit(number, (positions[slot_index] - gutter + 2, y + 3))

            # a gap between each group of four channels, so a column can be
            # followed from the top of the page to the bottom
            for slot_index in range(GROUP_SIZE, columns, GROUP_SIZE):
                line_x = positions[slot_index] - 3
                surface.fill(t.pattern_group, (line_x, row_rect.y, 3, row_h))
            if row_index == cursor_row:
                pygame.draw.rect(surface, t.cursor, row_rect, 1)
            elif row_index == self.pattern_row and not highlight:
                pygame.draw.rect(surface, t.accent_dark, row_rect, 1)

            for column in range(columns):
                index = first + column
                if index >= len(channels):
                    break
                x = positions[column]
                notes_here = grid.get((row_index, index))
                note = notes_here[0] if notes_here else None
                if note is None:
                    surface.blit(empty, (x + 4, y + 3))
                    continue
                pitch = gm.pitch_name(note.pitch)
                letter, octave = pitch[:-1], pitch[-1]
                name = "%s%s%s" % (letter, "" if len(letter) > 1 else "-", octave)
                colour = t.playing_text if highlight else t.pattern_note
                inst_colour = t.playing_text if highlight else t.pattern_inst
                vol_colour = t.playing_text if highlight else t.pattern_vol
                note_surface = self._surface("pattern", name, colour)
                surface.blit(note_surface, (x + 4, y + 3))
                instrument = self._surface(
                    "pattern", "%X" % (note.program % 16), inst_colour)
                surface.blit(instrument, (x + 4 + note_surface.get_width() + 10,
                                          y + 3))
                volume = "%02X" % int(round(max(0, min(15, note.volume)) * 0x40 / 15.0))
                surface.blit(self._surface("pattern", volume, vol_colour),
                             (x + 4 + note_surface.get_width() + 10 +
                              head.size("0")[0] + 12, y + 3))
        return surface

    def _pattern_head_height(self) -> int:
        """From the top of the page to the first row: info line + column names."""
        head = self.fonts["head"].get_height()
        return (head + 8) + head + 10

    def _draw_pattern_info(self, rect, channels, cursor_row, row_seconds, rows,
                           result, grid) -> None:
        """The info line FT2 puts above the pattern: position, time, tempo."""
        t = self.theme
        self.screen.fill(t.pattern_head, rect)
        theme.raised(self.screen, rect, t, 1)
        hidden = sum(len(z) - 1 for z in grid.values())
        text = "PAT %02X:%02X   TIME %05.1fs / %05.1fs   BPM %3d   %d VOICES" % (
            cursor_row // PATTERN_ROWS, cursor_row % PATTERN_ROWS,
            cursor_row * row_seconds, rows * row_seconds,
            int(round(getattr(result, "tempo", 0.0) or 120.0)), len(channels))
        if hidden:
            text += "   +%d SHARED" % hidden
        surface = self.fonts["head"].render(text, t.smooth, t.text)
        self.screen.blit(surface, (rect.x + 8,
                                   rect.centery - surface.get_height() // 2))

    def _draw_channel_head(self, page, info_h, head_h, positions, cell, channels,
                           first) -> None:
        t = self.theme
        strip = pygame.Rect(page.x + 2, page.y + 2 + info_h, page.width - 4,
                            head_h - info_h - 2)
        self.screen.fill(t.pattern_head, strip)
        theme.raised(self.screen, strip, t, 1)
        for slot, x in enumerate(positions):
            index = first + slot
            if index >= len(channels):
                break
            box = pygame.Rect(x - 2, strip.y + 2, cell - 4, strip.height - 4)
            self.screen.fill(t.field, box)
            theme.sunken(self.screen, box, t, 1)
            number = self.fonts["head"].render("%02d" % (index + 1), t.smooth,
                                               t.field_text)
            name = self.fonts["head"].render(_channel_short(channels[index]),
                                             t.smooth, t.pattern_inst)
            self.screen.blit(number, (box.x + 5, box.centery - number.get_height() // 2))
            self.screen.blit(name, (box.right - name.get_width() - 5,
                                    box.centery - name.get_height() // 2))

    def _draw_jump_strip(self, rect, rows, visible, row_seconds) -> None:
        """The pattern-number boxes FT2 has down the right edge of the pattern."""
        t = self.theme
        current = self.pattern_row // PATTERN_ROWS
        pages = max(1, (rows + PATTERN_ROWS - 1) // PATTERN_ROWS)
        box_h = 22
        per = max(1, (rect.height - 40) // box_h)
        start = max(0, min(current - per // 2, max(0, pages - per)))
        y = rect.y
        up = pygame.Rect(rect.x, y, rect.width - 4, 16)
        theme.arrow(self.screen, up, t, "up", enabled=current > 0)
        self.hits.append((up.copy(), lambda: self._jump_page(-1)))
        y += 18
        for page_number in range(start, min(pages, start + per)):
            box = pygame.Rect(rect.x, y, rect.width - 4, box_h - 2)
            theme.numeric(self.screen, box, t,
                          "%02d" % (page_number + 1),
                          self.fonts["small"],
                          t.field_text if page_number == current else t.pattern_vol)
            self.hits.append((box.copy(),
                              (lambda p=page_number: self._jump_page(p))))
            y += box_h
        down = pygame.Rect(rect.x, min(y, rect.bottom - 16), rect.width - 4, 16)
        theme.arrow(self.screen, down, t, "down", enabled=current < pages - 1)
        self.hits.append((down.copy(), lambda: self._jump_page(1)))

    def _jump_page(self, target) -> None:
        if target in (-1, 1):
            self.pattern_row = max(0, self.pattern_row + target * PATTERN_ROWS)
        else:
            self.pattern_row = target * PATTERN_ROWS

    def _pattern_click(self) -> None:
        """Clicking a row starts playback there, like clicking in a tracker."""
        data = self._pattern_data()
        if data[0] is None or not self.results:
            return
        row_seconds = data[2]
        offset = self.mouse[1] - (self._pattern_page().y +
                                  self._pattern_head_height())
        row = self.pattern_row + max(0, offset // self._row_height())
        if self.playing is not None:
            self.stop()
        self.play(self.selected_result, start=max(0.0, row * row_seconds))

    def _empty_pattern(self, page: pygame.Rect) -> None:
        t = self.theme
        lines = [
            ("NO SONG LOADED", "title", t.field_text),
            ("", "small", t.pattern_inst),
            ("drop a .mid / .vgm / .vgz / .gym / .zip on this window,", "body",
             t.pattern_inst),
            ("or press ADD MUSIC, then CONVERT", "body", t.pattern_inst),
            ("", "small", t.pattern_inst),
            ("The pattern page then shows what actually went to the chips:", "body",
             t.pattern_vol),
            ("one column per voice, note / instrument / volume in hex,", "body",
             t.pattern_vol),
            ("row numbers every four channels, and a cursor that follows", "body",
             t.pattern_vol),
            ("the music while it plays.  Click a row to play from there.", "body",
             t.pattern_vol),
        ]
        y = page.y + 24
        for text, font, colour in lines:
            if text:
                self._text(page.x + 28, y, text, font, colour)
            y += self.fonts[font].get_height() + 6

    # -------------------------------------------------------------- side panel

    def _draw_side(self, rect: pygame.Rect) -> None:
        t = self.theme
        self.screen.fill(t.desk, rect)

        # --- chips: two columns, one row per chip, like FT2's button blocks
        # The consoles get a line of their own — the NES APU itself, a second
        # NES and a PC Engine — and the cartridge add-ons share the two columns
        # underneath. Every row is a switch, the NES included: a PC Engine with
        # the NES off is six PC Engine voices. Full-width rows also give names
        # like "PC ENGINE" room to be read instead of truncated.
        entries = [("nes", "NES", 4, True),
                   ("dual", chips.CHIP_LABELS["dual"],
                    len(chips.EXTENSION_CHANNELS["dual"]), True),
                   ("pce", chips.CHIP_LABELS["pce"],
                    len(chips.EXTENSION_CHANNELS["pce"]), True)]
        entries += [(name, chips.CHIP_LABELS.get(name, name.upper()),
                     len(chips.EXTENSION_CHANNELS[name]), False)
                    for name in chips.ordered_extensions()
                    if name not in ("dual", "pce")]
        rows_needed = 3 + (len(entries) - 3 + 1) // 2
        row_h = 24
        chips_h = rows_needed * row_h + 36
        chips_box = pygame.Rect(rect.x, rect.y, rect.width, chips_h)
        inner = theme.panel(self.screen, chips_box, t, "CHIPS", self.fonts["tiny"])
        self._tiny_buttons(chips_box, (("ALL", self.all_chips, 44),
                                       ("NONE", self.no_chips, 52)))
        theme.field(self.screen, inner, t, t.field)
        self.chip_rects = []
        col_w = inner.width // 2
        column, line = 0, 0
        for index, (name, label, count, wide) in enumerate(entries):
            if wide:
                if column:
                    column, line = 0, line + 1
                row = pygame.Rect(inner.x, inner.y + 1 + line * row_h,
                                  inner.width - 2, row_h - 2)
                column, line = 0, line + 1
            else:
                row = pygame.Rect(inner.x + column * col_w,
                                  inner.y + 1 + line * row_h,
                                  col_w - 2, row_h - 2)
                column += 1
                if column >= 2:
                    column, line = 0, line + 1
            on = (self.settings.base if name == "nes"
                  else name in self.settings.extensions)
            if row.collidepoint(self.mouse):
                self.screen.fill(t.playing, row)
            self._text(row.x + 4, row.y + (row_h - 16) // 2, "%02d" % (index + 1),
                       "head", t.pattern_vol if on else t.pattern_empty)
            tag = "+%d %s" % (count, "ON" if on else "OFF")
            tag_surface = self.fonts["tiny"].render(
                tag, t.smooth, t.ok if on else t.pattern_empty)
            self.screen.blit(tag_surface,
                             (row.right - tag_surface.get_width() - 4,
                              row.y + (row_h - 16) // 2))
            room = row.right - tag_surface.get_width() - 8 - (row.x + 32)
            self._text(row.x + 32,
                       row.y + (row_h - self.fonts["small"].get_height()) // 2,
                       _fit(self.fonts["small"], label, room), "small",
                       t.field_text if on else t.pattern_empty)
            self.chip_rects.append((name, row.copy()))
            self.hits.append((row.copy(), (lambda n=name: self.toggle_chip(n))))

        # --- queue: one row per file with its own status, so a batch is visible
        rest = rect.bottom - chips_box.bottom - 6
        queue_h = max(112, min(168, int(rest * 0.46)))
        queue_box = pygame.Rect(rect.x, chips_box.bottom + 6, rect.width, queue_h)
        inner = theme.panel(self.screen, queue_box, t,
                            "FILES TO CONVERT  %d" % len(self.items),
                            self.fonts["tiny"])
        # Clicking the empty panel adds files — but only while it *is* empty, so
        # a click on a queued row can never fall through to the file dialog.
        # Registered first, so every button and row on top wins the click: the
        # dispatch walks the hit list backwards.
        if not self.items:
            self.hits.append((queue_box.copy(), self.pick_files))
        self._tiny_buttons(queue_box, (("ADD", self.pick_files, 46),
                                       ("CLEAR", self.clear_queue, 62)))
        footer_h = 22
        footer = pygame.Rect(inner.x, inner.bottom - footer_h, inner.width,
                             footer_h)
        self.screen.fill(t.face, footer)
        self.screen.fill(t.groove, (footer.x, footer.y, footer.width, 1))
        view = pygame.Rect(inner.x, inner.y, inner.width,
                           inner.height - footer_h - 3)
        theme.field(self.screen, view, t, t.field)
        self.queue_view = view
        self.mouse_in_queue = view.collidepoint(self.mouse)
        row_h = 26
        visible = max(1, view.height // row_h)
        self.scroll_queue = max(0, min(self.scroll_queue,
                                       max(0, len(self.items) - visible)))
        if not self.items:
            self._text(view.x + 6, view.y + 6, "drop music here, or ADD",
                       "small", t.pattern_empty)
            self._text(view.x + 6, view.y + 26,
                       "MIDI · VGM · GYM · NDS · ZIP", "tiny", t.pattern_empty)
        for slot in range(min(visible, len(self.items) - self.scroll_queue)):
            index = slot + self.scroll_queue
            item = self.items[index]
            row = pygame.Rect(view.x + 2, view.y + 2 + slot * row_h,
                              view.width - 4, row_h - 2)
            working = item.status == "working"
            failed = item.status == "failed"
            if working:
                self.screen.fill(t.accent_dark, row)
            elif row.collidepoint(self.mouse):
                self.screen.fill(t.stripe, row)
            archive = item.is_archive()
            self._text(row.x + 3, row.y + 3, "%02d" % (index + 1), "head",
                       t.bad if failed else t.pattern_vol)
            name_colour = t.bad if failed else (t.playing_text if working
                                                else t.field_text)
            name_width = row.width - (196 if archive else 106)
            self._text(row.x + 30, row.y + 3,
                       _fit(self.fonts["small"], item.name, name_width),
                       "small", name_colour)
            close_x = row.right - 24
            if archive:
                # a DS archive holds many songs: say which one, and offer the list
                songs_width = max(52, self.fonts["tiny"].size("SONGS")[0] + 12)
                songs_button = pygame.Rect(row.right - 24 - songs_width - 4,
                                           row.y + 3, songs_width, row_h - 8)
                theme.button(self.screen, songs_button, t, "SONGS",
                             self.fonts["tiny"])
                self.songs_buttons.append((index, songs_button.copy()))
                if item.catalogue_note:
                    tag, colour = "no songs", t.bad
                elif item.catalogue is None:
                    tag, colour = "reading…", t.pattern_empty
                else:
                    tag = "%d/%d  %s" % (item.song_number(), item.song_count(),
                                         item.song())
                    colour = t.playing_text if working else t.pattern_inst
                tag_surface = self.fonts["tiny"].render(
                    _fit(self.fonts["tiny"], tag, 116), t.smooth, colour)
                self.screen.blit(tag_surface,
                                 (songs_button.x - tag_surface.get_width() - 6,
                                  row.y + 4))
                self.hits.append((row.copy(), (lambda i=index: self.open_songs(i))))
                self.hits.append((songs_button.copy(),
                                  (lambda i=index: self.open_songs(i))))
            else:
                if failed:
                    tag, colour = "FAIL", t.bad
                elif working:
                    tag, colour = "%d%%" % int(item.fraction * 100), t.playing_text
                else:
                    tag, colour = "WAIT", t.pattern_empty
                tag_surface = self.fonts["tiny"].render(tag, t.smooth, colour)
                self.screen.blit(tag_surface,
                                 (close_x - tag_surface.get_width() - 6,
                                  row.y + 4))
            close = pygame.Rect(close_x, row.y + 3, 22, row_h - 8)
            theme.button(self.screen, close, t, "x", self.fonts["tiny"])
            self.hits.append((close.copy(), (lambda i=index: self.remove_item(i))))
            if working:
                filled = int((row.width - 8) * max(0.0, min(1.0, item.fraction)))
                self.screen.fill(t.pattern_empty,
                                 (row.x + 4, row.bottom - 5, row.width - 8, 3))
                self.screen.fill(t.accent,
                                 (row.x + 4, row.bottom - 5, filled, 3))
            elif failed and item.error:
                self._text(row.x + 30, row.y + 13,
                           _fit(self.fonts["tiny"], item.error, row.width - 40),
                           "tiny", t.bad)

        # footer: where the files land, or how far the batch has got
        if self.busy:
            finished = sum(1 for item in self.batch if item.status in ("done",
                                                                      "failed"))
            label = "%d/%d  %s" % (min(finished + 1, len(self.batch)),
                                   len(self.batch), self.progress_label or "")
            self._text(footer.x, footer.y + 3,
                       _fit(self.fonts["tiny"], label, footer.width - 52),
                       "tiny", t.text)
            percent = self.fonts["tiny"].render(
                "%d%%" % int(self.progress * 100), t.smooth, t.text)
            self.screen.blit(percent, (footer.right - percent.get_width(),
                                       footer.y + 3))
            filled = int(footer.width * max(0.0, min(1.0, self.progress)))
            self.screen.fill(t.pattern_empty,
                             (footer.x, footer.bottom - 3, footer.width, 3))
            self.screen.fill(t.accent,
                             (footer.x, footer.bottom - 3, filled, 3))
        else:
            label = self.fonts["tiny"].render("SAVE TO", t.smooth, t.dim)
            self.screen.blit(label, (footer.x, footer.y + 3))
            self._text(footer.x + label.get_width() + 8, footer.y + 3,
                       _fit(self.fonts["tiny"], self.output_dir,
                            footer.width - label.get_width() - 12),
                       "tiny", t.text)
            self.hits.append((footer.copy(), self.open_output_dir))

        results_box = pygame.Rect(rect.x, queue_box.bottom + 6, rect.width,
                                  rect.bottom - queue_box.bottom - 6)
        inner = theme.panel(self.screen, results_box, t,
                            "CONVERTED  %d" % len(self.results), self.fonts["tiny"])
        self._tiny_buttons(results_box, (("OPEN", self.open_output_dir, 56),))
        theme.field(self.screen, inner, t, t.field)
        self.results_view = inner
        self.mouse_in_results = inner.collidepoint(self.mouse)
        row_h = 40
        visible = max(1, inner.height // row_h)
        self.scroll_results = max(0, min(self.scroll_results,
                                         max(0, len(self.results) - visible)))
        if not self.results:
            self._text(inner.x + 6, inner.y + 6, "nothing converted yet", "small",
                       t.pattern_empty)
        for slot in range(min(visible, len(self.results) - self.scroll_results)):
            index = slot + self.scroll_results
            result = self.results[index]
            row = pygame.Rect(inner.x + 2, inner.y + 2 + slot * row_h,
                              inner.width - 4, row_h - 2)
            selected = index == self.selected_result
            if selected:
                self.screen.fill(t.playing, row)
            elif row.collidepoint(self.mouse):
                self.screen.fill(t.stripe, row)
            self._text(row.x + 4, row.y + 2, "%02d" % (index + 1), "head",
                       t.playing_text if selected else t.pattern_vol)
            duration = ""
            if result.ok and result.seconds:
                minutes, seconds = divmod(int(round(result.seconds)), 60)
                duration = "%d:%02d" % (minutes, seconds)
            name = os.path.basename(result.wav_path) or result.name or "file"
            self._text(row.x + 30, row.y + 2,
                       _fit(self.fonts["small"], name,
                            row.width - 34 - self.fonts["tiny"].size(duration)[0]),
                       "small", t.bad if not result.ok else
                       (t.playing_text if selected else t.field_text))
            if duration:
                clock = self.fonts["tiny"].render(duration, t.smooth,
                                                  t.playing_text if selected
                                                  else t.pattern_inst)
                self.screen.blit(clock, (row.right - clock.get_width() - 4,
                                         row.y + 3))
            if result.ok:
                line = "%d voices · %d kept · %d out" % (
                    result.voices, result.kept, result.left_out)
                if getattr(result, "thinned", 0):
                    line += " · %d thinned" % result.thinned
            else:
                line = "failed — " + (result.error or "unknown problem")
            self._text(row.x + 30, row.y + 21,
                       _fit(self.fonts["tiny"], line, row.width - 34), "tiny",
                       t.bad if not result.ok else (t.pattern_inst if selected
                                                    else t.pattern_vol))
            self.hits.append((row.copy(), (lambda i=index: self.select_result(i))))

    # ------------------------------------------------------------ song browser

    def _draw_song_window(self, outer: pygame.Rect) -> None:
        """A floating FT2-style list of the songs inside a DS archive."""
        t = self.theme
        window = self.song_window
        item = window["item"]
        catalogue = item.catalogue

        width = max(440, min(680, int(outer.width * 0.64)))
        rows = max(3, min(13, len(catalogue["songs"]) if catalogue else 6))
        height = max(206, min(int(outer.height * 0.7),
                              rows * window["row_h"] + 136))
        box = pygame.Rect(outer.centerx - width // 2,
                          outer.centery - height // 2, width, height)

        # a soft shadow, so it reads as a window lying on the desk
        shade = pygame.Surface((box.width + 8, box.height + 8), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 70))
        self.screen.blit(shade, (box.x + 5, box.y + 5))
        title = "SONGS IN  %s" % _fit(self.fonts["tiny"], item.name, width - 90)
        inner = theme.panel(self.screen, box, t, title, self.fonts["tiny"])

        head = self.fonts["tiny"]
        if catalogue:
            summary = "%d song%s · %d bank%s · %d wave archive%s" % (
                len(catalogue["songs"]), "" if len(catalogue["songs"]) == 1 else "s",
                catalogue["banks"], "" if catalogue["banks"] == 1 else "s",
                catalogue["waves"], "" if catalogue["waves"] == 1 else "s")
        elif item.catalogue_note:
            summary = item.catalogue_note
        else:
            summary = "reading the archive…"
        summary_rect = pygame.Rect(inner.x, inner.y, inner.width,
                                   head.get_height() + 5)
        theme.field(self.screen, summary_rect, t, t.field)
        self._text(summary_rect.x + 5, summary_rect.y + 2,
                   _fit(head, summary, summary_rect.width - 10), "tiny",
                   t.field_text)

        footer_h = 58
        list_rect = pygame.Rect(inner.x, summary_rect.bottom + 4, inner.width,
                                inner.height - summary_rect.height - 4 - footer_h)
        theme.field(self.screen, list_rect, t, t.field)
        self.song_list_view = list_rect

        row_h = window["row_h"]
        songs = self._window_songs()
        visible = max(1, (list_rect.height - 4) // row_h)
        window["scroll"] = max(0, min(window["scroll"],
                                      max(0, len(songs) - visible)))
        self.song_rows = []
        if not songs:
            self._text(list_rect.x + 8, list_rect.y + 8,
                       "no songs to list" if catalogue else "reading…", "small",
                       t.field_text)
        for slot in range(min(visible, len(songs) - window["scroll"])):
            position = slot + window["scroll"]
            _index, bank, name = songs[position]
            row = pygame.Rect(list_rect.x + 2, list_rect.y + 2 + slot * row_h,
                              list_rect.width - 16, row_h - 1)
            selected = position == window["selected"]
            if selected:
                self.screen.fill(t.playing, row)
            elif row.collidepoint(self.mouse):
                self.screen.fill(t.stripe, row)
            number = self.fonts["head"].render("%02d" % (position + 1), t.smooth,
                                               t.playing_text if selected
                                               else t.field_text)
            self.screen.blit(number, (row.x + 4, row.y + 2))
            bank_text = self.fonts["tiny"].render("bank %d" % bank, t.smooth,
                                                  t.playing_text if selected
                                                  else t.field_text)
            self.screen.blit(bank_text, (row.x + 34, row.y + 3))
            chosen = name.lower() == item.song().lower()
            self._text(row.x + 100, row.y + 1,
                       _fit(self.fonts["body"], name, row.width - 210), "body",
                       t.playing_text if selected else t.field_text)
            if chosen:
                tick = self.fonts["tiny"].render("CURRENT", t.smooth,
                                                 t.playing_text if selected
                                                 else t.field_text)
                self.screen.blit(tick, (row.right - tick.get_width() - 4,
                                        row.y + 3))
            self.song_rows.append((position, row.copy()))
            self.hits.append((row.copy(), (lambda p=position: self.pick_song_row(p))))

        if len(songs) > visible:
            track = pygame.Rect(list_rect.right - 12, list_rect.y + 1, 11,
                                list_rect.height - 2)
            fraction = window["scroll"] / float(max(1, len(songs) - visible))
            theme.scrollbar(self.screen, track, t, fraction,
                            visible / float(len(songs)))

        # --- footer: bank, then the three things you can do
        footer = pygame.Rect(inner.x, inner.bottom - footer_h + 4, inner.width,
                             footer_h - 4)
        self.screen.fill(t.face, footer)
        self.screen.fill(t.groove, (footer.x, footer.y, footer.width, 1))

        button_h = 28
        small = self.fonts["tiny"]

        def fit_width(text: str) -> int:
            return small.size(text)[0] + 16

        cancel = pygame.Rect(footer.right - fit_width("CANCEL"), footer.y + 14,
                             fit_width("CANCEL"), button_h)
        gap = 6
        use = pygame.Rect(cancel.x - fit_width("USE THIS SONG") - gap, footer.y + 14,
                          fit_width("USE THIS SONG"), button_h)
        all_songs = pygame.Rect(use.x - fit_width("ADD ALL SONGS") - gap,
                                footer.y + 14, fit_width("ADD ALL SONGS"),
                                button_h)
        self._button(cancel, "CANCEL", self.close_songs, font="tiny")
        self._button(all_songs, "ADD ALL SONGS", self.add_all_songs,
                     enabled=bool(songs), font="tiny")
        self._button(use, "USE THIS SONG", self.use_song, enabled=bool(songs),
                     primary=True, font="tiny")

        banks = (catalogue or {}).get("banks", 0) or 1
        label = self.fonts["tiny"].render("BANK", t.smooth, t.dim)
        self.screen.blit(label, (footer.x + 2, footer.y + 2))
        value = window["bank"]
        if value == "":
            songs_now = self._window_songs()
            shown = (str(songs_now[window["selected"]][1])
                     if songs_now else "0") + " *"
        else:
            shown = value
        field = pygame.Rect(footer.x + 2, footer.y + 16, 54, 24)
        theme.numeric(self.screen, field, t, shown, self.fonts["small"])
        up = pygame.Rect(field.right + 3, field.y, 22, 12)
        down = pygame.Rect(field.right + 3, field.y + 12, 22, 12)
        for arrow_rect, step in ((up, 1), (down, -1)):
            theme.arrow(self.screen, arrow_rect, t, "up" if step > 0 else "down")
            self.hits.append((arrow_rect.copy(), (lambda s=step: self.change_bank(s))))
        room = max(40, all_songs.x - (down.right + 8) - 6)
        if banks > 1:
            hint_text = "of %d banks · * = the song's own" % banks
        else:
            hint_text = "the only bank in this archive"
        hint = self.fonts["tiny"].render(_fit(self.fonts["tiny"], hint_text, room),
                                         t.smooth, t.pattern_empty)
        self.screen.blit(hint, (down.right + 8, footer.y + 22))

    def play_selected(self) -> None:
        self.play(self.selected_result)

    def save_selected(self) -> None:
        self.save_result(self.selected_result)

    def open_folder_selected(self) -> None:
        self.open_folder(self.selected_result)

    def select_result(self, index: int) -> None:
        if 0 <= index < len(self.results):
            self.selected_result = index
            self.pattern_row = 0
            self.pattern_column = 0

    # ------------------------------------------------------------------ status

    def _draw_status(self, rect: pygame.Rect) -> None:
        """The bottom line: what the window is doing, and what it is doing it to."""
        t = self.theme
        self.screen.fill(t.panel, rect)
        pygame.draw.rect(self.screen, t.dark, rect, 1)

        if self.busy:
            state, chip = "WORKING", t.warn
        elif self.playing is not None:
            state, chip = "PLAYING", t.pattern_inst
        else:
            state, chip = "READY", t.accent
        label = self._surface("tiny", state, t.desktop)
        box = pygame.Rect(rect.x + 8, rect.centery - 9, label.get_width() + 20, 18)
        self.screen.fill(chip, box)
        self.screen.blit(label, (box.centerx - label.get_width() // 2,
                                 box.centery - label.get_height() // 2))

        message = self.progress_label if self.busy else self.status
        right = _fit(self.fonts["tiny"], "%d VOICES · %d CHIP%s · %s" % (
            self.voice_count(), self.chip_count(),
            "" if self.chip_count() == 1 else "S",
            self.console_label().upper()), max(80, rect.width // 2))
        right_surface = self._surface("tiny", right, t.dim)
        self.screen.blit(right_surface,
                         (rect.right - right_surface.get_width() - 12,
                          rect.centery - right_surface.get_height() // 2))
        room = rect.right - 20 - right_surface.get_width() - (box.right + 12)
        colour = t.bad if self.status_error else t.field_text
        text = _fit(self.fonts["small"], message, max(40, room))
        surface = self._surface("small", text, colour)
        self.screen.blit(surface, (box.right + 12,
                                   rect.centery - surface.get_height() // 2))

    def run(self) -> int:
        """The window's loop: handle what happened, then repaint if it matters.

        `_needs_redraw` is what stops the window burning a full repaint sixty
        times a second while it is sitting still.
        """
        while self.running:
            for event in pygame.event.get():
                self._dirty = True        # anything at all may change the picture
                self.handle_event(event)
            self._drain()
            if self._needs_redraw():
                self.draw()
                pygame.display.flip()
            self.clock.tick(FPS)
        self.stop()
        pygame.quit()
        return 0

    def render_once(self):
        self.draw()
        pygame.display.flip()
        return self.screen


def _groups(columns: int) -> int:
    return max(1, (columns + GROUP_SIZE - 1) // GROUP_SIZE)


def run(files: Optional[List[str]] = None) -> int:
    return App(files=files).run()


def _visible_columns(app) -> int:
    return getattr(app, "pattern_columns", 1)


def _selftest_ds_rom(app, check, click) -> None:
    """Queue and convert a DS ROM in the window.

    The ROM is built by tests/make_test_rom.py, which a packaged build does not
    carry; there the check says so instead of failing, because the pipeline test
    job covers it with the real file.
    """
    try:
        tests_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tests")
        if tests_dir not in sys.path:
            sys.path.insert(0, tests_dir)
        import make_test_rom
    except Exception:
        if sys.stdout is not None:
            sys.stdout.write("  --   DS window check skipped: no test ROM builder "
                             "in this build\n")
        return

    rom = None
    try:
        rom = make_test_rom.write(os.path.join(tempfile.mkdtemp(), "gui.nds"),
                                  two_songs=True)
        app.add_path(rom)
        check("a DS ROM can be queued", any(item.path == rom for item in app.items),
              str([item.name for item in app.items]))

        # the song browser: list the songs, pick the second one, then convert it
        deadline = time.time() + 30
        while app.items[0].catalogue is None and time.time() < deadline:
            app._drain()
            time.sleep(0.02)
        app._drain()
        check("the ROM's songs are listed",
              bool(app.items[0].catalogue),
              app.items[0].catalogue_note or "no catalogue")
        # click the row's SONGS button, the way a person does
        app.draw()
        check("the queued ROM shows a SONGS button", bool(app.songs_buttons),
              str(app.songs_buttons))
        if app.songs_buttons:
            click(app.songs_buttons[0][1])
        app.draw()
        check("the song browser opens over the window",
              bool(app.song_window) and len(app.song_rows) >= 2,
              str(len(app.song_rows)))
        if app.song_window and len(app.song_rows) >= 2:
            click(app.song_rows[1][1])
            app.draw()
        check("clicking a song in the list highlights it",
              bool(app.song_window) and app.song_window["selected"] == 1,
              str(app.song_window["selected"] if app.song_window else "closed"))
        use_buttons = sorted([rect for rect, _action in app.hits
                              if rect.height == 28], key=lambda rect: rect.x)
        if use_buttons:
            click(use_buttons[1])           # ADD ALL SONGS, USE THIS SONG, CANCEL
        app.draw()
        check("a song can be picked for one file",
              app.items[0].sequence != "" and
              app.items[0].sequence != app.items[0].catalogue["chosen"],
              app.items[0].sequence or "nothing picked")
        check("the browser closes when a song is picked", app.song_window is None)
        app.settings.extensions = []
        app.start_convert()
        deadline = time.time() + 120
        while app.busy and time.time() < deadline:
            app._drain()
            time.sleep(0.02)
        app._drain()
        check("a DS ROM converts in the window",
              bool(app.results) and app.results[0].ok,
              app.results[0].error if app.results else "no result")
        check("the window says a MIDI and a SoundFont came out",
              "MID" in app.status and "SF2" in app.status, app.status)
        app.draw()
        check("the window still draws after a DS conversion",
              app.screen is not None)
        check("the window says which song it converted",
              bool(app.results) and app.results[0].song != "",
              app.results[0].song if app.results else "no result")
        if app.results and app.results[0].ok:
            app.play(0)
            check("the DS result plays like any other", app.playing is not None,
                  str(app.playing))
            app.stop()
    except Exception as error:               # a broken window test must say why
        check("a DS ROM converts in the window", False,
              "%s: %s" % (type(error).__name__, error))


def selftest(screenshot: Optional[str] = None) -> int:
    """Drive the window headlessly: click the chips, convert, play, switch look."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    failures: List[str] = []

    def check(label, condition, detail=""):
        line = ("  ok   " if condition else "  FAIL ") + label + \
               ("" if condition else "  " + detail)
        if sys.stdout is not None:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except Exception:
                pass
        if not condition:
            failures.append(label)

    settings_path = os.path.join(tempfile.gettempdir(), "chip8bit-selftest.json")
    try:
        os.unlink(settings_path)
    except OSError:
        pass

    app = App(settings_path=settings_path)
    app.draw()

    def click(rect: pygame.Rect) -> bool:
        """Press a control the way the window does: a real mouse event.

        Going through handle_event means the check also proves the button is
        reachable — a control drawn *under* a bigger one answers nothing.
        """
        app.mouse = rect.center
        app.draw()
        reachable = any(hit_rect.collidepoint(rect.center)
                        for hit_rect, _action in app.hits)
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                            pos=rect.center))
        return reachable

    def unreachable_hits() -> List[str]:
        """Controls whose middle is covered by a bigger control drawn later."""
        app.draw()
        hidden: List[str] = []
        for rect, action in app.hits:
            under = [hit for hit in app.hits
                     if hit[0].collidepoint(rect.center)]
            if not under:
                continue
            winner = min(under, key=lambda hit: hit[0].width * hit[0].height)
            if winner[1] is not action:
                hidden.append("%s loses to %s" % (action, winner[1]))
        return hidden

    try:
        check("window opens", app.screen.get_size() == (WIDTH, HEIGHT))
        check("one dark look, and no look switch",
              app.theme.key == "dark" and len(theme.THEMES) == 1 and
              not hasattr(app, "switch_look"),
              "%s / %s" % (app.theme.key, sorted(theme.THEMES)))
        check("the desk is dark and flat",
              sum(app.theme.desktop) < 120 and app.theme.border == 1 and
              app.theme.rounded == 0, str(app.theme.desktop))
        check("no skin is written to the settings file",
              "look" not in json.load(open(settings_path, encoding="utf-8"))
              if os.path.isfile(settings_path) else True,
              open(settings_path).read() if os.path.isfile(settings_path) else "")
        check("starts with 4 voices", app.voice_count() == 4)
        check("one chip row per console and cartridge chip",
              len(app.chip_rects) == 1 + len(chips.EXTENSION_CHANNELS),
              str(len(app.chip_rects)))
        check("pattern text is big enough to read",
              app.fonts["pattern"].get_height() >= 20,
              str(app.fonts["pattern"].get_height()))

        for name, rect in app.chip_rects:
            if name:
                click(rect)
        all_voices = 4 + sum(len(spec) for spec in chips.EXTENSION_CHANNELS.values())
        check("all chips on => every voice (4 APU + 2x NES + a PC Engine + "
              "the cartridge chips)",
              app.voice_count() == all_voices and all_voices == 32,
              "%d, expected %d" % (app.voice_count(), all_voices))

        app.add_demo()
        check("demo queued", len(app.items) == 1)
        check("queued file starts as waiting",
              app.items[0].status == "waiting", app.items[0].status)
        click(app.convert_rect)
        deadline = time.time() + 120
        while app.busy and time.time() < deadline:
            app._drain()
            app.render_once()
            time.sleep(0.02)
        check("conversion finished", not app.busy)
        check("one result", len(app.results) == 1)
        check("the converted file left the queue", not app.items,
              str([(i.name, i.status) for i in app.items]))
        check("the status line says what happened",
              "Converted 1 file" in app.status, app.status)
        if app.results:
            result = app.results[0]
            check("result ok", result.ok, result.error)
            check("wav on disk", os.path.isfile(result.wav_path))
            check("wav lands in the folder the window shows",
                  os.path.dirname(result.wav_path) == app.output_dir,
                  "%s vs %s" % (os.path.dirname(result.wav_path),
                                app.output_dir))
            check("understood the file", bool(result.analysis_lines),
                  str(result.analysis_lines))
            check("ten or more voices", result.voices >= 10, str(result.voices))
            check("a melody was found",
                  any(v.role == "melody" for v in result.analysis.voices))
            check("a bass was found",
                  any(v.role == "bass" for v in result.analysis.voices))
            pattern = app._pattern_data()
            check("pattern grid has channels", bool(pattern[1]),
                  str(len(pattern[1])))
            check("pattern grid has rows", pattern[3] > 8, str(pattern[3]))
            check("pattern grid has notes", bool(pattern[4]), str(len(pattern[4])))
            stacked = sum(len(cell) - 1 for cell in pattern[4].values())
            check("the pattern puts one note in a cell, never two",
                  stacked == 0, "%d notes stacked" % stacked)
            check("notes left out are reported",
                  isinstance(getattr(result, "left_out", None), int),
                  str(getattr(result, "left_out", None)))

            app.draw()
            before = app.pattern_row
            app.mouse_in_pattern = True
            app.handle_event(pygame.event.Event(
                pygame.MOUSEWHEEL, {"x": 0, "y": -3, "flipped": False,
                                    "touch": False, "precise_x": 0.0,
                                    "precise_y": -3.0}))
            check("wheel scrolls the pattern", app.pattern_row > before,
                  "%s -> %s" % (before, app.pattern_row))
            app.mouse_in_pattern = False
            app.pattern_row = 0
            columns = len(app._pattern_data()[1])
            app.draw()
            app.handle_event(pygame.event.Event(
                pygame.KEYDOWN, {"key": pygame.K_RIGHT, "mod": 0, "unicode": ""}))
            app.draw()
            check("arrows scroll the channel columns",
                  app.pattern_column == (1 if columns > _visible_columns(app) else 0),
                  "%s (columns %s, visible %s)" % (
                      app.pattern_column, columns, _visible_columns(app)))
            app.pattern_column = 0
            app.pattern_row = 0
            app.draw()
            page = app._pattern_page()
            app.mouse = (page.x + 120,
                         page.y + app._pattern_head_height() +
                         app._row_height() * 3 + 8)
            app._pattern_click()
            check("clicking a pattern row plays",
                  app.playing == 0 or not app.mixer_ready, str(app.playing))
            app.stop()

            app.draw()
            check("pattern page fills the window",
                  app.pattern_height > 300, str(app.pattern_height))

        # --- a file that cannot be converted must not stop the batch
        missing = os.path.join(tempfile.gettempdir(), "chip8bit-not-music.txt")
        with open(missing, "w") as handle:
            handle.write("this is not music")
        before = app.status
        app.add_path(missing)
        check("an unreadable extension is refused straight away",
              "Can't read" in app.status and app.status != before, app.status)

        broken = os.path.join(tempfile.gettempdir(), "chip8bit-broken.mid")
        with open(broken, "wb") as handle:
            handle.write(b"not really a midi file")
        app.add_path(broken)
        check("a bogus .mid is still queued so it can be tried",
              any(item.path == broken for item in app.items))
        app.start_convert()
        deadline = time.time() + 60
        while app.busy and time.time() < deadline:
            app._drain()
            time.sleep(0.02)
        failed = [item for item in app.items if item.path == broken]
        check("a failed file stays in the queue to retry", bool(failed),
              str([(i.name, i.status) for i in app.items]))
        check("the failure is reported", app.status_error and failed
              and failed[0].status == "failed", app.status)
        app.draw()
        check("a failed result still has a name in CONVERTED",
              bool(app.results) and bool(app.results[0].name))
        app.remove_item(app.items.index(failed[0]) if failed else 0)
        check("a failed file can be removed",
              not any(item.path == broken for item in app.items))

        # --- the little switches in the panel title lines
        app.draw()
        none_rect = None
        for rect, action in app.hits:
            if getattr(action, "__func__", None) is not None and \
                    getattr(action, "__func__", None).__name__ == "no_chips":
                none_rect = rect
        check("NONE turns every extension chip off",
              click(none_rect) if none_rect else False)
        check("no extensions left", app.settings.extensions == [],
              str(app.settings.extensions))
        app.all_chips()
        check("ALL turns them back on",
              len(app.settings.extensions) == len(chips.EXTENSION_CHANNELS),
              str(len(app.settings.extensions)))

        # --- the two whole consoles are one click each, and the count follows
        app.no_chips()
        app.draw()
        rows = dict(app.chip_rects)
        if "dual" in rows:
            click(rows["dual"])
            check("2x NES is one click and doubles the console",
                  app.voice_count() == 8, str(app.voice_count()))
        if "pce" in rows:
            click(rows["pce"])
            check("PC Engine adds its six wave channels",
                  app.voice_count() == 14, str(app.voice_count()))
            check("both consoles are on at once",
                  set(["dual", "pce"]) <= set(app.settings.extensions),
                  str(app.settings.extensions))
        for name in ("dual", "pce"):
            if name in rows:
                click(rows[name])          # leave them off for the next checks
        app.no_chips()

        # --- the NES is a switch too: a PC Engine is a PC Engine on its own
        app.no_chips()
        app.draw()
        rows = dict(app.chip_rects)
        click(rows["nes"])
        check("the last console cannot be switched off",
              app.settings.base and app.voice_count() >= 4 and app.status_error,
              "%s / %s" % (app.settings.base, app.status))
        click(rows["pce"])
        click(rows["nes"])
        check("with a PC Engine on, the NES can be switched off",
              not app.settings.base and app.voice_count() == 6,
              "%s voices, base=%s" % (app.voice_count(), app.settings.base))
        check("a PC Engine on its own has only PC Engine voices",
              [spec.id for spec in app.settings.channels()] ==
              ["pce1", "pce2", "pce3", "pce4", "pce5", "pce6"],
              str([spec.id for spec in app.settings.channels()]))
        check("and its files are named for it, not for a NES",
              app.settings.tag() == "pce", app.settings.tag())
        click(rows["pce"])
        check("the PC Engine cannot be the thing you switch off last",
              app.settings.extensions == ["pce"],
              str(app.settings.extensions))
        app.no_chips()
        check("NONE brings the plain four-voice NES back",
              app.settings.base and not app.settings.extensions and
              app.voice_count() == 4,
              "%s voices, base=%s" % (app.voice_count(), app.settings.base))

        # --- the header spinners must do what their numbers say
        app.draw()
        arrows = [rect for rect, _action in app.hits
                  if rect.width == 23 and rect.height == 12]
        # two arrows per box, stacked in one column: group by x, keep the higher
        # one as "up", then order the boxes left to right and top to bottom
        columns = {}
        for rect in arrows:
            columns.setdefault(rect.x, []).append(rect)
        boxes = []
        for x in sorted(columns):
            stacked = sorted(columns[x], key=lambda rect: rect.y)
            for start in range(0, len(stacked) - 1, 2):
                boxes.append((stacked[start], stacked[start + 1]))
        boxes.sort(key=lambda pair: (pair[0].y, pair[0].x))
        check("the header has eight live spinner arrows",
              len(arrows) == 8 and len(boxes) == 4,
              "%d arrows in %d boxes" % (len(arrows), len(boxes)))
        if len(arrows) == 8 and len(boxes) == 4:
            app.no_chips()
            voices_up, voices_down = sorted(boxes[0], key=lambda r: r.y)
            chips_up, chips_down = sorted(boxes[1], key=lambda r: r.y)
            bits_up, bits_down = sorted(boxes[2], key=lambda r: r.y)
            rate_up, rate_down = sorted(boxes[3], key=lambda r: r.y)
            before = len(app.settings.extensions)
            click(voices_up)
            check("VOICES up adds a chip, and the number follows",
                  len(app.settings.extensions) == before + 1 and
                  app.voice_count() > 4,
                  "%s chips, %s voices" % (len(app.settings.extensions),
                                           app.voice_count()))
            click(voices_down)
            check("VOICES down takes it away again",
                  len(app.settings.extensions) == before,
                  str(app.settings.extensions))
            click(chips_up)
            check("CHIPS up is the same control",
                  len(app.settings.extensions) == before + 1,
                  str(app.settings.extensions))
            click(chips_down)
            click(bits_down)
            check("BITS down chooses 8 bit", app.settings.bits == 8,
                  str(app.settings.bits))
            click(bits_up)
            check("BITS up chooses 16 bit", app.settings.bits == 16,
                  str(app.settings.bits))
            rate_before = app.settings.rate
            click(rate_up)
            check("RATE up picks the next sample rate",
                  app.settings.rate == 48000, str(app.settings.rate))
            click(rate_down)
            check("RATE down comes back", app.settings.rate == rate_before,
                  str(app.settings.rate))
            app.all_chips()
            app.settings.rate = 44100

        # --- a Nintendo DS ROM: queue it, convert it, and see the extras named
        _selftest_ds_rom(app, check, click)

        # A control drawn under a bigger one answers nothing, so every
        # button and row has to win the click at its own middle.
        hidden = unreachable_hits()
        check("every control answers a click", not hidden, "; ".join(hidden[:3]))

        # ...and the toolbar really is a row of live buttons, not a picture of
        # one: every button in the strip must be its own control.
        toolbar = list(app.toolbar_rects)
        check("the toolbar has its seven buttons", len(toolbar) == 7,
              "%d buttons: %s" % (len(toolbar), [tuple(r) for r in toolbar]))
        check("no two toolbar buttons sit on top of each other",
              len({tuple(rect) for rect in toolbar}) == len(toolbar))

        # --- the window must not stutter: a still desk is not repainted, and a
        # frame with a song loaded stays well inside one 60 Hz frame.
        app.draw()
        app._last_draw = 0.0             # pretend the last paint was long ago
        app._dirty = False
        check("a still window has nothing to repaint", app._needs_redraw())
        app._last_draw = time.time()
        check("and the very next frame is skipped", not app._needs_redraw())
        app._dirty = True
        check("an event still paints it", app._needs_redraw())
        if app.results:
            app.draw()
            started = time.perf_counter()
            for _frame in range(10):
                app._body_key = None           # worst case: rebuild the page
                app.draw()
            rebuilt = (time.perf_counter() - started) / 10.0 * 1000.0
            app.draw()
            started = time.perf_counter()
            for _frame in range(10):
                app.draw()                     # the play frame: cached page
            cached = (time.perf_counter() - started) / 10.0 * 1000.0
            check("a played-back frame is inside a 60 Hz frame",
                  cached < 16.0, "%.1f ms" % cached)
            check("even a full pattern repaint is inside it",
                  rebuilt < 40.0, "%.1f ms (first paint allowed to be slow)" %
                  rebuilt)

        if screenshot:
            base, extension = os.path.splitext(screenshot)
            app.draw()
            target = "%s-%s%s" % (base, app.theme.key, extension or ".png")
            pygame.image.save(app.screen, target)
            check("screenshot written (%s)" % app.theme.key,
                  os.path.isfile(target))
    finally:
        pygame.quit()

    print("%d window check(s) failed" % len(failures))
    return 0 if not failures else 1
