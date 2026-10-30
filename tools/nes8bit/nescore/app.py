"""The chip8bit window: a FastTracker II desk, in 1995.

One native window with three period looks — FastTracker II (the default, taken
from the v2.04 screenshot: blue frame, lavender buttons, black pattern pages with
pale blue hex data), Windows 95 and Amiga Workbench. No browser, no server.

The big pattern page is built from the arrangement that really went to the chips:
one column per console voice, note / instrument / volume in hex, row numbers down
the side of every group of four channels, and a play cursor that follows the music.
The boxes above it show what the converter understood about the file.
"""

import json
import os
import queue
import sys
import tempfile
import threading
import time
from typing import Dict, List, Optional

import pygame

from . import chips, convert, dialogs, demo, gm, theme

WIDTH, HEIGHT = 1200, 830
MIN_WIDTH, MIN_HEIGHT = 1000, 740
FPS = 60

LOOK_LABELS = {"tracker": "FT2 LOOK", "win95": "WIN95 LOOK",
               "amiga": "AMIGA LOOK"}
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


class QueueItem:
    """One file waiting to be converted, plus what happened to it."""

    def __init__(self, path: str, name: str, size: int = 0):
        self.path = path
        self.name = name
        self.size = size
        self.status = "waiting"      # waiting | working | failed  (done leaves)
        self.fraction = 0.0
        self.stage = ""
        self.error = ""


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
        self.settings, self.look = self._load_settings()
        self.theme = theme.get(self.look)

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
        self.queue_view = pygame.Rect(0, 0, 0, 0)
        self.results_view = pygame.Rect(0, 0, 0, 0)

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
        settings = convert.Settings()
        look = "tracker"
        try:
            with open(self.settings_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, ValueError):
            return settings, look
        settings.extensions = [name for name in saved.get("extensions", [])
                               if name in chips.EXTENSION_CHANNELS]
        settings.bits = 16 if saved.get("bits", 16) != 8 else 8
        settings.export_vgm = bool(saved.get("export_vgm", False))
        settings.sharing = False        # never resurrect arpeggio cramming
        settings.sampled_drums = bool(saved.get("sampled_drums", True))
        look = saved.get("look", "tracker")
        return settings, look

    def _save_settings(self) -> None:
        try:
            with open(self.settings_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "extensions": list(self.settings.extensions),
                    "bits": self.settings.bits,
                    "export_vgm": self.settings.export_vgm,
                    "sharing": self.settings.sharing,
                    "sampled_drums": self.settings.sampled_drums,
                    "look": self.look,
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

    def add_path(self, path: str) -> None:
        if not os.path.isfile(path):
            self.status = "Not a file: %s" % path
            self.status_error = True
            return
        if any(item.path == path for item in self.items):
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
        self.items.append(QueueItem(path, os.path.basename(path), size))
        self.status = "%d file%s queued — press CONVERT" % (
            len(self.items), "" if len(self.items) == 1 else "s")
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
        if 0 <= index < len(self.items):
            self.items.pop(index)

    def clear_queue(self) -> None:
        if self.busy:
            self.status = "Still converting — wait, or press STOP"
            self.status_error = True
            return
        self.items = []
        self.scroll_queue = 0
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
        files = [(item.path, item.name) for item in pending]
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
            for index, (path, name) in enumerate(files):
                self.messages.put(("begin", index))

                def progress(stage, fraction, index=index):
                    self.messages.put(("progress", index, stage,
                                       max(0.0, min(1.0, fraction))))

                try:
                    target = os.path.join(output_dir,
                                          convert.output_name(path, settings))
                    result = convert.convert_file(path, settings,
                                                  output_path=target,
                                                  progress=progress)
                except Exception as error:      # one bad file must not stop the rest
                    result = convert.Result(ok=False, name=name,
                                            error="%s: %s" % (type(error).__name__,
                                                              error))
                self.messages.put(("result", index, result, path))
        finally:
            self.messages.put(("done",))

    def _drain(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                return
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
            for rect, action in reversed(self.hits):
                if rect.collidepoint(event.pos):
                    action()
                    break

    # ----------------------------------------------------------------- switches

    def switch_look(self) -> None:
        self.theme = theme.next_theme(self.look)
        self.look = self.theme.key
        self._build_fonts()
        self._save_settings()

    def toggle_chip(self, name: str) -> None:
        if name in self.settings.extensions:
            self.settings.extensions.remove(name)
        else:
            self.settings.extensions.append(name)
        self._save_settings()

    def all_chips(self) -> None:
        if len(self.settings.extensions) == len(chips.EXTENSION_CHANNELS):
            self.settings.extensions = []
        else:
            self.settings.extensions = list(chips.EXTENSION_CHANNELS)
        self._save_settings()

    def no_chips(self) -> None:
        self.settings.extensions = []
        self._save_settings()

    def toggle_bits(self) -> None:
        self.settings.bits = 8 if self.settings.bits > 8 else 16
        self._save_settings()

    def toggle_vgm(self) -> None:
        self.settings.export_vgm = not self.settings.export_vgm
        self._save_settings()

    def toggle_drums(self) -> None:
        self.settings.sampled_drums = not self.settings.sampled_drums
        self._save_settings()

    def voice_count(self) -> int:
        return 4 + sum(len(chips.EXTENSION_CHANNELS[name])
                       for name in self.settings.extensions
                       if name in chips.EXTENSION_CHANNELS)

    # ---------------------------------------------------------------- geometry

    def _row_height(self) -> int:
        return self.fonts["pattern"].get_height() + 6

    def _layout(self):
        """Every panel in the window, recomputed from the current size."""
        width, height = self.screen.get_size()
        outer = pygame.Rect(0, 0, width, height)
        content = outer.inflate(-8, -8)

        status_h = 26
        top_h = 108
        scope_h = 86
        right_w = max(286, min(330, int(content.width * 0.27)))

        top = pygame.Rect(content.x, content.y, content.width, top_h)
        scope = pygame.Rect(content.x, top.bottom + 4, content.width, scope_h)
        status = pygame.Rect(content.x, content.bottom - status_h,
                             content.width, status_h)
        body_top = scope.bottom + 4
        body_bottom = status.y - 4
        pattern = pygame.Rect(content.x, body_top,
                              content.width - right_w - 6, body_bottom - body_top)
        side = pygame.Rect(pattern.right + 6, body_top, right_w,
                           body_bottom - body_top)
        return outer, content, top, scope, pattern, side, status

    def _pattern_rect(self) -> pygame.Rect:
        return self._layout()[4]

    # ----------------------------------------------------------------- drawing

    def draw(self) -> None:
        self.hits = []
        self.mouse = pygame.mouse.get_pos()
        t = self.theme
        self.screen.fill(t.desktop)

        outer, content, top, scope, pattern, side, status = self._layout()
        theme.frame(self.screen, outer, t)

        self._draw_header(top)
        self._draw_scope(scope)
        self._draw_pattern(pattern)
        self._draw_side(side)
        self._draw_status(status)

    def _text(self, x, y, text, font="body", color=None):
        t = self.theme
        surface = self.fonts[font].render(text, t.smooth, color or t.text)
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

    def _draw_header(self, rect: pygame.Rect) -> None:
        """The FT2 top strip: settings boxes, logo, and what the file contained."""
        t = self.theme
        self.screen.fill(t.desk, rect)

        # --- left: the little numeric boxes with arrows, like FT2's tempo boxes
        left = pygame.Rect(rect.x, rect.y, 250, rect.height)
        theme.panel(self.screen, left, t)
        field_font = self.fonts["small"]

        def value_box(x, y, w, label, value, action=None):
            self._text(x, y - 13, label, "tiny", t.dim)
            box = pygame.Rect(x, y, w - 28, 26)
            theme.numeric(self.screen, box, t, value, field_font)
            up = pygame.Rect(box.right + 3, y, 23, 12)
            down = pygame.Rect(box.right + 3, y + 14, 23, 12)
            for arrow_rect, direction in ((up, "up"), (down, "down")):
                theme.arrow(self.screen, arrow_rect, t, direction)
                if action:
                    self.hits.append((arrow_rect.copy(), action))
            return box

        value_box(left.x + 8, left.y + 20, 116, "VOICES", "%02d" % self.voice_count())
        value_box(left.x + 134, left.y + 20, 108, "CHIPS", "%02d" % (
            1 + len(self.settings.extensions)))
        value_box(left.x + 8, left.y + 62, 116, "BITS",
                  "%02d" % self.settings.bits, self.toggle_bits)
        value_box(left.x + 134, left.y + 62, 108, "RATE",
                  "%dk" % (self.settings.rate // 1000))

        # --- middle: the logo block
        logo_x = left.right + 6
        logo_w = max(210, min(292, int(rect.width * 0.24)))
        logo = pygame.Rect(logo_x, rect.y, logo_w, rect.height)
        theme.panel(self.screen, logo, t)
        self._draw_logo(logo)

        # --- right: "what I found", in the place of FT2's "Composed by" box
        info = pygame.Rect(logo.right + 6, rect.y, rect.right - logo.right - 6,
                           rect.height)
        inner = theme.panel(self.screen, info, t, "WHAT I FOUND", self.fonts["tiny"])
        theme.field(self.screen, inner, t, t.field)
        lines = self._found_lines()
        y = inner.y + 4
        colours = (t.field_text, t.pattern_inst, t.pattern_vol, t.accent)
        for index, line in enumerate(lines[:4]):
            if not line:
                continue
            key = "body" if index == 0 else "small"
            font = self.fonts[key]
            self._text(inner.x + 8, y, _fit(font, line, inner.width - 16), key,
                       colours[min(index, 3)])
            y += font.get_height() + 5

    def _draw_logo(self, rect: pygame.Rect) -> None:
        t = self.theme
        font = self.fonts["logo"]
        parts = [("chip", t.text), ("8", t.frame), ("bit", t.text)]
        width = sum(font.size(text)[0] for text, _ in parts)
        x = rect.centerx - width // 2
        y = rect.centery - font.get_height() // 2 - 4
        for text, colour in parts:
            surface = font.render(text, t.smooth, colour)
            self.screen.blit(surface, (x, y))
            x += surface.get_width()
        caption = self.fonts["small"].render(
            "NES / 8-bit transcoder", t.smooth, t.dim)
        self.screen.blit(caption, (rect.centerx - caption.get_width() // 2,
                                   y + font.get_height() - 4))

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
        for line in lines:
            if line.startswith("Instruments: "):
                out.append("Instr: " + line[len("Instruments: "):])
            elif line.startswith("Found "):
                out.append(line)
        if not out:
            out = lines[:1]
        if result.ok:
            kept = "%d notes kept" % result.kept
            if getattr(result, "left_out", 0):
                kept += " · %d left out" % result.left_out
            if getattr(result, "thinned", 0):
                kept += " · %d lines thinned" % result.thinned
            out.append(kept)
        while len(out) < 4:
            out.append("")
        return out[:4]

    def request_quit(self) -> None:
        self.running = False

    # ------------------------------------------------------------------- scope

    def _draw_scope(self, rect: pygame.Rect) -> None:
        """The row of little waveform boxes FT2 shows for every channel."""
        t = self.theme
        self.screen.fill(t.desk, rect)
        theme.panel(self.screen, rect, t)
        area = pygame.Rect(rect.x + 3, rect.y + 3, rect.width - 6, rect.height - 6)

        result, _channels, _row_seconds, _rows, grid = self._pattern_data()
        active = [spec.id for spec in
                  chips.build_channel_set(self.settings.extensions)]
        every = [spec.id for spec in
                 chips.build_channel_set(list(chips.EXTENSION_CHANNELS))]

        per_row = 11
        rows = 2
        box_w = (area.width - (per_row - 1) * 3) // per_row
        box_h = (area.height - (rows - 1) * 3 - 2) // rows
        duration = 1.0
        if result is not None and getattr(result, "notes", None):
            duration = max(0.2, max(n.end() for n in result.notes))

        for index in range(min(len(every), per_row * rows)):
            column = index % per_row
            row = index // per_row
            box = pygame.Rect(area.x + column * (box_w + 3),
                              area.y + row * (box_h + 3), box_w, box_h)
            live = every[index] in active
            self.screen.fill(t.field if live else t.stripe, box)
            theme.sunken(self.screen, box, t, 1)
            if live:
                self._draw_scope_trace(box, every[index], result, duration)
            else:
                mid = box.centery + 7
                self.screen.fill(t.pattern_empty,
                                 (box.x + 4, mid, box.width - 8, 1))

            number = self.fonts["head"].render("%02d" % (index + 1), t.smooth,
                                               t.pattern_head if live
                                               else t.pattern_empty)
            self.screen.blit(number, (box.x + 3, box.y + 1))
            if result is not None and live:
                count = len([n for n in result.notes if n.channel == every[index]])
                if count:
                    tag = self.fonts["head"].render(str(count), t.smooth,
                                                    t.pattern_inst)
                    self.screen.blit(tag, (box.right - tag.get_width() - 3, box.y + 1))
            elif not live:
                tag = self.fonts["head"].render("OFF", t.smooth, t.pattern_empty)
                self.screen.blit(tag, (box.right - tag.get_width() - 3, box.y + 1))

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

    def _pattern_data(self):
        """Rows of channel cells for the last conversion, in tracker form.

        The row length is chosen from the music, not fixed: a 226 BPM tune needs
        shorter rows than a 90 BPM one, otherwise two notes land in the same cell
        and the page silently hides half the song.
        """
        result = (self.results[self.selected_result]
                  if self.results else None)
        if result is None or not getattr(result, "notes", None):
            return None, [], 0.0, 0, {}
        tempo = float(getattr(result, "tempo", 0.0) or 120.0)
        channels = [spec.id for spec in
                    chips.build_channel_set(self.settings.extensions)]
        for note in result.notes:
            if note.channel and note.channel not in channels:
                channels.append(note.channel)
        index_of = {name: index for index, name in enumerate(channels)}

        # pick the row length from the music: the longest rows that still leave
        # almost every note in its own cell. A fast tune gets short rows instead of
        # a page that hides half of it.
        tolerance = max(2, int(len(result.notes) * 0.01))
        best = None
        for speed in (PATTERN_SPEED, 4, 3, 2, 1):
            candidate = 2.5 * speed / max(30.0, tempo)
            cells: Dict[tuple, List] = {}
            for note in result.notes:
                if note.channel in index_of:
                    cells.setdefault((int(note.start / candidate),
                                      index_of[note.channel]), []).append(note)
            collisions = sum(len(group) - 1 for group in cells.values())
            if collisions <= tolerance:
                best = (candidate, cells)      # coarsest page that still works
                break
            if best is None or collisions < best[0]:
                best = (candidate, cells)
        row_seconds, grid = best

        rows = int(max(n.end() for n in result.notes) / row_seconds) + 2
        return result, channels, row_seconds, rows, grid

    # ----------------------------------------------------------------- pattern

    def _draw_pattern(self, rect: pygame.Rect) -> None:
        t = self.theme
        self.screen.fill(t.desk, rect)
        theme.panel(self.screen, rect, t)
        page = pygame.Rect(rect.x + 4, rect.y + 4, rect.width - 8, rect.height - 8)
        theme.field(self.screen, page, t, t.field)
        self.mouse_in_pattern = page.collidepoint(self.mouse)

        data = self._pattern_data()
        if data[0] is None:
            self._empty_pattern(page)
            self.pattern_height = 0
            self.hits.append((page, self._pattern_click))
            return
        result, channels, row_seconds, rows, grid = data

        info_h = self.fonts["head"].get_height() + 10
        head_h = info_h + self.fonts["head"].get_height() + 12
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
        x = page.x + 4
        for slot in range(columns):
            if slot % GROUP_SIZE == 0:
                x += gutter
            positions.append(x)
            x += cell

        self._draw_pattern_info(pygame.Rect(page.x + 4, page.y + 4,
                                            page.width - 8, info_h),
                                channels, cursor_row, row_seconds, rows, result,
                                grid)
        self._draw_channel_head(page, info_h, head_h, positions, cell, channels,
                                first)

        # rows
        for slot in range(visible):
            row_index = self.pattern_row + slot
            y = page.y + head_h + slot * row_h
            row_rect = pygame.Rect(page.x + 2, y, page.width - 4, row_h)
            highlight = playing_row is not None and row_index == playing_row
            if highlight:
                self.screen.fill(t.playing, row_rect)
            elif row_index % 4 == 0:
                self.screen.fill(t.stripe, row_rect)

            pattern_row = row_index % PATTERN_ROWS
            number_colour = (t.pattern_row_beat if pattern_row % 16 == 0
                             else t.pattern_row)
            for slot_index in range(0, columns, GROUP_SIZE):
                number_x = positions[slot_index] - gutter + 2
                number = self.fonts["head"].render(
                    "%02X" % pattern_row, t.smooth,
                    t.playing_text if highlight else number_colour)
                self.screen.blit(number, (number_x, y + 3))

            # the blue background shows between each group of four channels
            for slot_index in range(GROUP_SIZE, columns, GROUP_SIZE):
                line_x = positions[slot_index] - 3
                self.screen.fill(t.pattern_group,
                                 pygame.Rect(line_x, row_rect.y, 3, row_rect.height))
            if row_index == cursor_row:
                pygame.draw.rect(self.screen, t.cursor, row_rect, 1)
            elif row_index == self.pattern_row and not highlight:
                pygame.draw.rect(self.screen, t.accent_dark, row_rect, 1)

            for column in range(columns):
                index = first + column
                if index >= len(channels):
                    break
                x = positions[column]
                notes_here = grid.get((row_index, index))
                note = notes_here[0] if notes_here else None
                if note is None:
                    self.screen.blit(font.render("--- · ---", t.smooth,
                                                 t.pattern_empty),
                                     (x + 4, y + 3))
                    continue
                pitch = gm.pitch_name(note.pitch)
                letter, octave = pitch[:-1], pitch[-1]
                name = "%s%s%s" % (letter, "" if len(letter) > 1 else "-", octave)
                colour = t.playing_text if highlight else t.pattern_note
                inst_colour = t.playing_text if highlight else t.pattern_inst
                vol_colour = t.playing_text if highlight else t.pattern_vol
                self.screen.blit(font.render(name, t.smooth, colour), (x + 4, y + 3))
                wid = font.size(name)[0]
                instrument = "%X" % (note.program % 16)
                self.screen.blit(font.render(instrument, t.smooth, inst_colour),
                                 (x + 4 + wid + 10, y + 3))
                volume = "%02X" % int(round(max(0, min(15, note.volume)) * 0x40 / 15.0))
                self.screen.blit(font.render(volume, t.smooth, vol_colour),
                                 (x + 4 + wid + 10 + font.size("0")[0] + 12, y + 3))
        if pages > 1:
            self._draw_jump_strip(
                pygame.Rect(page.right - jump_w - 18, page.y + head_h, jump_w,
                            page.height - head_h - 6), rows, visible, row_seconds)

        if rows > visible:
            bar = pygame.Rect(page.right - 14, page.y + head_h, 12,
                              page.height - head_h - 8)
            theme.scrollbar(self.screen, bar, t,
                            self.pattern_row / max(1, rows - visible),
                            visible / max(1, rows))
        if len(channels) > columns:
            bar = pygame.Rect(page.x + 4, page.bottom - 12, page.width - 26, 10)
            theme.scrollbar(self.screen, bar, t,
                            first / max(1, len(channels) - columns),
                            columns / max(1, len(channels)))

        self.hits.append((page, self._pattern_click))

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
        page = self._layout()[4].inflate(-8, -8)
        offset = self.mouse[1] - (page.y + self.fonts["head"].get_height() + 12)
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

        # --- buttons, two columns, like the FT2 menu column
        button_h = 30
        gap = 5
        rows = [
            (("ADD MUSIC", self.pick_files), ("DEMO", self.add_demo)),
            (("CONVERT", self.start_convert), ("STOP", self.stop)),
            (("PLAY", self.play_selected), ("SAVE AS", self.save_selected)),
            (("FOLDER", self.open_folder_selected), ("ALL CHIPS", self.all_chips)),
            (("16-BIT" if self.settings.bits > 8 else "8-BIT", self.toggle_bits),
             (LOOK_LABELS.get(self.look, "LOOK"), self.switch_look)),
        ]
        col_w = (rect.width - gap) // 2
        y = rect.y
        for pair in rows:
            for column, (label, action) in enumerate(pair):
                box = pygame.Rect(rect.x + column * (col_w + gap), y,
                                  col_w, button_h)
                enabled = True
                if action == self.start_convert:
                    label = ("CONVERT %d" % len(self.items) if self.items
                             else "CONVERT")
                    enabled = bool(self.items) and not self.busy
                    self.convert_rect = box.copy()
                if action in (self.play_selected, self.save_selected,
                              self.open_folder_selected):
                    enabled = bool(self.results)
                    if action == self.play_selected:
                        self.play_rect = box.copy()
                self._button(box, label, action, pressed=(
                    action == self.start_convert and self.busy),
                    enabled=enabled)
            y += button_h + gap

        # --- chips: two columns, one row per chip, like FT2's button blocks
        entries = [("", "NES", 4)] + [
            (name, name.upper(), len(spec))
            for name, spec in chips.EXTENSION_CHANNELS.items()]
        rows_needed = (len(entries) + 1) // 2
        row_h = 24
        chips_h = rows_needed * row_h + 28
        chips_box = pygame.Rect(rect.x, y + 2, rect.width, chips_h)
        inner = theme.panel(self.screen, chips_box, t, "CHIPS", self.fonts["tiny"])
        self._tiny_buttons(chips_box, (("ALL", self.all_chips, 44),
                                       ("NONE", self.no_chips, 52)))
        theme.field(self.screen, inner, t, t.field)
        self.chip_rects = []
        col_w = inner.width // 2
        for index, (name, label, count) in enumerate(entries):
            column = index % 2
            line = index // 2
            row = pygame.Rect(inner.x + column * col_w,
                              inner.y + 1 + line * row_h,
                              col_w - 2, row_h - 2)
            on = name == "" or name in self.settings.extensions
            if row.collidepoint(self.mouse) and name:
                self.screen.fill(t.playing, row)
            self._text(row.x + 4, row.y + (row_h - 16) // 2, "%02d" % (index + 1),
                       "head", t.pattern_vol if on else t.pattern_empty)
            self._text(row.x + 32, row.y + (row_h - self.fonts["small"].get_height()) // 2,
                       label, "small", t.field_text if on else t.pattern_empty)
            tag = "+%d %s" % (count, "ON" if on else "OFF")
            tag_surface = self.fonts["tiny"].render(
                tag, t.smooth, t.ok if on else t.pattern_empty)
            self.screen.blit(tag_surface,
                             (row.right - tag_surface.get_width() - 4,
                              row.y + (row_h - 16) // 2))
            self.chip_rects.append((name, row.copy()))
            if name:
                self.hits.append((row.copy(), (lambda n=name: self.toggle_chip(n))))

        # --- queue: one row per file with its own status, so a batch is visible
        rest = rect.bottom - chips_box.bottom - 6
        queue_h = max(112, min(168, int(rest * 0.46)))
        queue_box = pygame.Rect(rect.x, chips_box.bottom + 6, rect.width, queue_h)
        inner = theme.panel(self.screen, queue_box, t,
                            "FILES TO CONVERT  %d" % len(self.items),
                            self.fonts["tiny"])
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
                       "MIDI · VGM · GYM · ZIP", "tiny", t.pattern_empty)
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
            self._text(row.x + 3, row.y + 3, "%02d" % (index + 1), "head",
                       t.bad if failed else t.pattern_vol)
            name_colour = t.bad if failed else (t.playing_text if working
                                                else t.field_text)
            self._text(row.x + 30, row.y + 3,
                       _fit(self.fonts["small"], item.name, row.width - 106),
                       "small", name_colour)
            if failed:
                tag, colour = "FAIL", t.bad
            elif working:
                tag, colour = "%d%%" % int(item.fraction * 100), t.playing_text
            else:
                tag, colour = "WAIT", t.pattern_empty
            tag_surface = self.fonts["tiny"].render(tag, t.smooth, colour)
            self.screen.blit(tag_surface,
                             (row.right - tag_surface.get_width() - 30, row.y + 4))
            close = pygame.Rect(row.right - 24, row.y + 3, 22, row_h - 8)
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
        self.hits.append((queue_box, self.pick_files))

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
        t = self.theme
        self.screen.fill(t.desk, rect)
        theme.panel(self.screen, rect, t)
        inner = rect.inflate(-8, -6)
        message = self.progress_label if self.busy else self.status
        colour = t.bad if self.status_error else t.text

        state = ("WORKING" if self.busy else
                 ("PLAYING" if self.playing is not None else "READY"))
        state_surface = self.fonts["button"].render(state, t.smooth, t.text)
        voices = self.fonts["small"].render(
            "%d voices · %d chips" % (self.voice_count(),
                                      1 + len(self.settings.extensions)),
            t.smooth, t.dim)
        right = inner.right - state_surface.get_width() - 14
        self.screen.blit(state_surface, (inner.right - state_surface.get_width(), inner.y))
        self.screen.blit(voices, (right - voices.get_width() - 14, inner.y + 2))
        self._text(inner.x, inner.y,
                   _fit(self.fonts["body"], message,
                        right - voices.get_width() - 20), "body", colour)

    # -------------------------------------------------------------------- loop

    def run(self) -> int:
        while self.running:
            for event in pygame.event.get():
                self.handle_event(event)
            self._drain()
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


def _selftest_ds_rom(app, check) -> None:
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
        rom = make_test_rom.write(os.path.join(tempfile.mkdtemp(), "gui.nds"))
        app.add_path(rom)
        check("a DS ROM can be queued", any(item.path == rom for item in app.items),
              str([item.name for item in app.items]))
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
        app.mouse = rect.center
        app.draw()
        for hit_rect, action in reversed(app.hits):
            if hit_rect.collidepoint(rect.center):
                action()
                return True
        return False

    try:
        check("window opens", app.screen.get_size() == (WIDTH, HEIGHT))
        check("starts in the tracker look", app.look == "tracker", app.look)
        check("starts with 4 voices", app.voice_count() == 4)
        check("seven chip rows", len(app.chip_rects) == 7, str(len(app.chip_rects)))
        check("pattern text is big enough to read",
              app.fonts["pattern"].get_height() >= 20,
              str(app.fonts["pattern"].get_height()))

        for name, rect in app.chip_rects:
            if name:
                click(rect)
        check("all chips on => 22 voices", app.voice_count() == 22,
              str(app.voice_count()))

        app.switch_look()
        check("switching the look works", app.look == "win95", app.look)
        app.draw()
        app.switch_look()
        app.switch_look()
        check("three looks, back to the tracker", app.look == "tracker", app.look)
        app.draw()

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
            page = app._layout()[4].inflate(-8, -8)
            app.mouse = (page.x + 120,
                         page.y + app.fonts["head"].get_height() + 12 +
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
        check("ALL turns them back on", len(app.settings.extensions) == 6,
              str(len(app.settings.extensions)))

        # --- a Nintendo DS ROM: queue it, convert it, and see the extras named
        _selftest_ds_rom(app, check)

        if screenshot:
            base, extension = os.path.splitext(screenshot)
            for key, theme_obj in theme.THEMES.items():
                app.theme = theme_obj
                app.look = theme_obj.key
                app._build_fonts()
                app.draw()
                target = "%s-%s%s" % (base, key, extension or ".png")
                pygame.image.save(app.screen, target)
                check("screenshot written (%s)" % key, os.path.isfile(target))
    finally:
        pygame.quit()

    print("%d window check(s) failed" % len(failures))
    return 0 if not failures else 1
