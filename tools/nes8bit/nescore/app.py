"""The chip8bit window, drawn like it is 1995.

One native window, three period looks. The default is FastTracker II: navy
panels, cyan labels, a hex pattern grid with one column per console voice. The
other two are Windows 95 (teal desktop, bevelled grey, navy title bars) and Amiga
Workbench (blue desktop, orange accents, chunky borders). No browser, no server,
no page.

The pattern grid is built from the arrangement that actually went to the chips,
and the header boxes show what the converter understood about the file: tempo,
meter, instruments, which lines it found, and how many notes it had to leave out
because every voice was busy.
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

WIDTH, HEIGHT = 1080, 760
PATTERN_SPEED = 6          # ticks per pattern row, so an 8 s song is ~64 rows
MIN_WIDTH, MIN_HEIGHT = 940, 660
FPS = 60


_FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/TTF",
    "/usr/local/share/fonts",
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
]


def _font_path(names, bold=False, mono=False):
    """Find a usable TrueType file: fontconfig first, then the usual folders.

    The sandbox (and many CI images) have no fc-list, so match_font finds
    nothing and everything falls back to pygame's tiny bitmap face.
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
        wanted.append(flat + ("-Bold" if bold else "") + ".ttf")
        wanted.append(flat + ".ttf")
    for folder in _FONT_DIRS:
        if not os.path.isdir(folder):
            continue
        for entry in sorted(os.listdir(folder)):
            if entry.lower() in [w.lower() for w in wanted]:
                return os.path.join(folder, entry)
    return None


def _font(theme_obj: theme.Theme, size: int, bold: bool = False):
    path = _font_path(theme_obj.fonts(), bold=bold)
    return pygame.font.Font(path, size)


def _font_mono(theme_obj: theme.Theme, size: int):
    """A monospaced font, so tracker columns line up like they should."""
    path = _font_path(("DejaVu Sans Mono", "Liberation Mono", "Consolas",
                       "Courier New", "Courier"), mono=True)
    return pygame.font.Font(path, size)


_CHANNEL_NAMES = {
    "pulse1": "PU1", "pulse2": "PU2", "triangle": "TRI", "noise": "NOI",
    "dmc": "DMC", "fds": "FDS", "vrc6_saw": "V6S",
    "vrc6_pulse1": "V6-1", "vrc6_pulse2": "V6-2",
    "mmc5_pulse1": "M5-1", "mmc5_pulse2": "M5-2",
}


def _channel_short(channel: str) -> str:
    """Two or three characters of channel name, so columns stay tidy."""
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


def _human(size: int) -> str:
    if size > 1024 * 1024:
        return "%.1f MB" % (size / 1048576.0)
    if size > 1024:
        return "%d KB" % round(size / 1024.0)
    return "%d B" % size


class QueueItem:
    def __init__(self, path: str, name: str, size: int = 0):
        self.path = path
        self.name = name
        self.size = size


class App:
    def __init__(self, files: Optional[List[str]] = None,
                 settings_path: Optional[str] = None, headless: bool = False):
        pygame.init()
        pygame.display.set_caption("chip8bit — NES / 8-bit transcoder")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()

        self.settings_path = settings_path or self._default_settings_path()
        self.settings, self.look = self._load_settings()
        self.theme = theme.get(self.look)

        self.fonts: Dict[str, object] = {}
        self._build_fonts()

        self.items: List[QueueItem] = []
        self.results: List[convert.Result] = []
        self.messages: queue.Queue = queue.Queue()
        self.busy = False
        self.progress = 0.0
        self.progress_label = ""
        self.status = "Drop MIDI, VGM or GYM files here, or press Add files…"
        self.status_error = False

        self.hits: List[tuple] = []
        self.mouse = (0, 0)
        self.scroll_queue = 0
        self.scroll_results = 0
        self.playing: Optional[int] = None
        self.mixer_ready = self._init_mixer()
        self.running = True
        self.chip_rects: List[tuple] = []
        self.pattern_row = 0
        self.pattern_column = 0
        self.selected_result = 0
        self.mouse_in_pattern = False
        self.convert_rect = pygame.Rect(0, 0, 0, 0)
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
            "logo": _font(t, 26, bold=True),
            "title": _font(t, 16, bold=True),
            "head": _font(t, 12, bold=True),
            "body": _font(t, 12),
            "small": _font(t, 11),
            "tiny": _font(t, 10),
            "button": _font(t, 11, bold=True),
            "pattern": _font_mono(t, 13),
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
        # never resurrect arpeggio cramming from an old settings file
        settings.sharing = False
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
            return
        if any(item.path == path for item in self.items):
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        self.items.append(QueueItem(path, os.path.basename(path), size))
        self.status = "%d file%s queued. Press Convert." % (
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
        self.items = []
        self.scroll_queue = 0

    def pick_files(self) -> None:
        paths = dialogs.open_files()
        if paths:
            for path in paths:
                self.add_path(path)
        else:
            self.status = "If no picker opens, just drop files onto this window."

    # ----------------------------------------------------------------- convert

    def start_convert(self) -> None:
        if self.busy or not self.items:
            return
        files = [(item.path, item.name) for item in self.items]
        settings = self.settings
        self.busy = True
        self.progress = 0.0
        self.progress_label = "Starting…"
        self.status_error = False
        threading.Thread(target=self._work, args=(files, settings), daemon=True).start()

    def _work(self, files, settings) -> None:
        output_dir = dialogs.default_output_dir()
        for index, (path, name) in enumerate(files):
            def progress(stage, fraction, index=index, name=name):
                self.messages.put(("progress", stage,
                                   (index + max(0.0, min(1.0, fraction))) / len(files),
                                   name))

            target = os.path.join(output_dir, convert.output_name(path, settings))
            result = convert.convert_file(path, settings, output_path=target,
                                          progress=progress)
            self.messages.put(("result", result, path))
        self.messages.put(("done",))

    def _drain(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                return
            if message[0] == "progress":
                _, stage, fraction, name = message
                self.progress = fraction
                self.progress_label = "%s — %s" % (name, stage)
            elif message[0] == "result":
                _, result, path = message
                self.results.insert(0, result)
                self.items = [item for item in self.items if item.path != path]
                if result.ok:
                    self.status = "Saved %s" % os.path.basename(result.wav_path)
                    self.status_error = False
                else:
                    self.status = "%s: %s" % (os.path.basename(path), result.error)
                    self.status_error = True
            elif message[0] == "done":
                self.busy = False
                self.progress = 0.0

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
        result = self.results[index]
        destination = dialogs.save_as(os.path.basename(result.wav_path) or "song.wav")
        if not destination:
            self.status = "Already saved to %s" % result.wav_path
            return
        try:
            with open(result.wav_path, "rb") as source, open(destination, "wb") as out:
                out.write(source.read())
            self.status = "Copied to %s" % destination
            self.status_error = False
        except OSError as error:
            self.status = "Could not save: %s" % error
            self.status_error = True

    def open_folder(self, index: int) -> None:
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
            if self.mouse_in_pattern:
                if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                    self.pattern_column = max(0, self.pattern_column - event.y)
                else:
                    self.pattern_row = max(0, self.pattern_row - event.y * 2)
            elif self.mouse_in_queue:
                self.scroll_queue = max(0, self.scroll_queue - event.y)
            elif self.mouse_in_results:
                self.scroll_results = max(0, self.scroll_results - event.y)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_UP:
                self.pattern_row = max(0, self.pattern_row - 1)
            elif event.key == pygame.K_DOWN:
                self.pattern_row += 1
            elif event.key == pygame.K_PAGEUP:
                self.pattern_row = max(0, self.pattern_row - 16)
            elif event.key == pygame.K_PAGEDOWN:
                self.pattern_row += 16
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
                self.stop() if self.playing is not None else setattr(self, "running", False)
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

    # ----------------------------------------------------------------- drawing

    def draw(self) -> None:
        self.hits = []
        self.mouse = pygame.mouse.get_pos()
        t = self.theme
        width, height = self.screen.get_size()
        self.screen.fill(t.desktop)

        self._draw_titlebar(width)

        status_h = 22
        top = 68
        bottom = height - status_h - 6
        right_w = 244
        pattern_rect = pygame.Rect(4, top, width - right_w - 12, bottom - top)
        side_rect = pygame.Rect(width - right_w - 4, top, right_w, bottom - top)

        self._draw_pattern(pattern_rect)
        self._draw_side(side_rect)
        self._draw_status(width, height - status_h - 2, status_h)

    def _text(self, x, y, text, font="body", color=None):
        t = self.theme
        surface = self.fonts[font].render(text, t.smooth, color or t.text)
        self.screen.blit(surface, (x, y))

    def _button(self, rect, label, action, pressed=False, enabled=True, primary=False):
        theme.button(self.screen, rect, self.theme, label, self.fonts["button"],
                     pressed=pressed, enabled=enabled, primary=primary)
        if enabled:
            self.hits.append((rect.copy(), action))

    def _draw_titlebar(self, width: int) -> None:
        """The FastTracker II header: a strip of small labelled boxes."""
        t = self.theme
        strip = pygame.Rect(0, 0, width, 64)
        pygame.draw.rect(self.screen, t.face, strip)

        x = 4
        for label, value, box_width in (
                ("VOICES", str(self.voice_count()), 58),
                ("CHIPS", "%d" % (1 + len(self.settings.extensions)), 50),
                ("BITS", str(self.settings.bits), 44),
                ("RATE", "%dk" % (self.settings.rate // 1000), 50)):
            box = pygame.Rect(x, 4, box_width, 26)
            theme.field(self.screen, box, t, t.field)
            self._text(box.x + 3, box.y + 1, label, "tiny", t.dim)
            self._text(box.x + 3, box.y + 12, value, "small", t.accent)
            x += box_width + 4

        logo_x = x + 10
        title = self.fonts["logo"].render("chip", t.smooth, t.text)
        self.screen.blit(title, (logo_x, 2))
        offset = logo_x + title.get_width()
        accent = self.fonts["logo"].render("8", t.smooth, t.accent)
        self.screen.blit(accent, (offset, 2))
        self.screen.blit(self.fonts["logo"].render("bit", t.smooth, t.text),
                         (offset + accent.get_width(), 2))
        self._text(logo_x + 4, 40, "NES / 8-bit transcoder", "tiny", t.dim)
        self._text(logo_x + 4, 51, "the tracker way", "tiny", t.dim)

        # "what I found": the same boxes the tracker puts above its pattern
        info_left = logo_x + 190
        look = pygame.Rect(width - 176, 4, 84, 26)
        quit_rect = pygame.Rect(width - 88, 4, 84, 26)
        info_width = look.x - info_left - 8
        found = self._found_lines()
        while len(found) < 4:
            found.append("")
        rows = ((found[0], found[1]), (found[2], found[3]))
        y = 4
        for first, second in rows:
            box = pygame.Rect(info_left, y, max(160, info_width), 27)
            theme.field(self.screen, box, t, t.field)
            if first:
                self._text(box.x + 4, box.y + 2,
                           _fit(self.fonts["small"], first, box.width - 10),
                           "small", t.text)
            if second:
                self._text(box.x + 4, box.y + 14,
                           _fit(self.fonts["tiny"], second, box.width - 10),
                           "tiny", t.dim)
            y += 29

        short = {"tracker": "FT2", "win95": "WIN95", "amiga": "AMIGA"}
        theme.button(self.screen, look, t, short.get(t.key, "LOOK"),
                     self.fonts["tiny"])
        self.hits.append((look, self.switch_look))
        theme.button(self.screen, quit_rect, t, "Quit", self.fonts["tiny"])
        self.hits.append((quit_rect, self.request_quit))

        pygame.draw.line(self.screen, t.light, (0, 63), (width, 63))

    def _found_lines(self):
        """Four short lines for the header: what the converter understood."""
        if not self.results:
            return ["No file analysed yet - add music, then CONVERT",
                    "drop .mid .vgm .vgz .gym .zip anywhere on this window",
                    "", ""]
        result = self.results[self.selected_result] if self.results else None
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
                kept += " · %d left out (no free channel)" % result.left_out
            if getattr(result, "dropped", 0):
                kept += " · %d too quiet" % result.dropped
            out.append(kept)
        while len(out) < 4:
            out.append("")
        return out[:4]

    def request_quit(self) -> None:
        self.running = False

    # ------------------------------------------------------------ pattern grid

    def _pattern_data(self):
        """Rows of channel cells for the last conversion, in tracker form."""
        result = self.results[self.selected_result] if self.results else None
        if result is None or not getattr(result, "notes", None):
            return None, [], 0.0
        tempo = float(getattr(result, "tempo", 0.0) or 120.0)
        # a tracker row: the FT2 tick is 2.5/BPM seconds and a row is six ticks
        row_seconds = 2.5 * PATTERN_SPEED / max(30.0, tempo)
        # every voice the chips offer, in chip order, like a tracker's columns
        channels = [spec.id for spec in
                    chips.build_channel_set(self.settings.extensions)]
        for note in result.notes:
            if note.channel and note.channel not in channels:
                channels.append(note.channel)
        rows = int(max(n.end() for n in result.notes) / row_seconds) + 2
        grid = {}
        for note in result.notes:
            row = int(note.start / row_seconds)
            index = channels.index(note.channel) if note.channel in channels else -1
            if index >= 0:
                grid[(row, index)] = note
        return result, channels, row_seconds, rows, grid

    def _draw_pattern(self, rect: pygame.Rect) -> None:
        t = self.theme
        theme.field(self.screen, rect, t, t.field)
        self.mouse_in_pattern = rect.collidepoint(self.mouse)

        data = self._pattern_data()
        if data[0] is None:
            self._empty_pattern(rect)
            self.hits.append((rect, self._pattern_click))
            return

        result, channels, row_seconds, rows, grid = data
        header_h = 20
        row_h = self.fonts["pattern"].get_height() + 2
        gutter = 28                      # the row-number column
        visible = max(1, (rect.height - header_h - 6) // row_h)
        max_rows = max(visible, rows)
        self.pattern_row = max(0, min(self.pattern_row, max_rows - visible))

        # playing position, so the tracker scrolls like a tracker
        playing_row = None
        if self.playing is not None and pygame.mixer.get_init():
            position = pygame.mixer.music.get_pos()
            if position >= 0:
                playing_row = int(position / 1000.0 / row_seconds)
                if self.playing < len(self.results):
                    self.pattern_row = max(
                        0, min(playing_row - visible // 2, max_rows - visible))

        pattern_font = self.fonts["pattern"]
        readout_w = self.fonts["tiny"].size("ROW FF  00.0s  BPM 000")[0] + 10
        usable = rect.width - gutter - 12 - readout_w
        cell_w = pattern_font.size("C-4 50 33")[0] + 14
        columns = max(1, min(len(channels), usable // cell_w))
        cell_w = min(120, max(cell_w, usable // max(1, columns)))
        self.pattern_columns = columns
        self.pattern_column = max(0, min(self.pattern_column,
                                         max(0, len(channels) - columns)))
        first = self.pattern_column

        # the row under the mouse gets the tracker's edit cursor
        hover = None
        if self.mouse_in_pattern:
            offset = self.mouse[1] - (rect.y + 2 + header_h)
            if offset >= 0:
                hover = self.pattern_row + offset // row_h

        # channel headers, like the numbered columns at the top of a pattern
        head = pygame.Rect(rect.x + 2, rect.y + 2, rect.width - 4, header_h)
        pygame.draw.rect(self.screen, t.face_alt, head)
        pygame.draw.line(self.screen, t.light, (head.x, head.bottom - 1),
                         (head.right, head.bottom - 1))
        for slot in range(columns):
            index = first + slot
            if index >= len(channels):
                break
            x = rect.x + 4 + gutter + slot * cell_w
            name = channels[index]
            label = "%02d %s" % (index + 1, _channel_short(name))
            self._text(x + 2, head.y + 3, label, "small",
                       t.accent if index == 0 else t.pattern_header_text)
            if slot:
                pygame.draw.line(self.screen, t.shadow, (x - 1, head.y),
                                 (x - 1, head.bottom - 1))
        readout = "ROW %02X  %0.1fs  BPM %d" % (
            (hover if hover is not None else self.pattern_row) % 256,
            (hover if hover is not None else self.pattern_row) * row_seconds,
            int(round(getattr(result, "tempo", 0.0) or 120.0)))
        readout_x = head.right - self.fonts["tiny"].size(readout)[0] - 4
        self._text(readout_x, head.y + 4, readout, "tiny", t.dim)

        # if the chips offer more voices than the panel can show, say so
        if len(channels) > columns:
            hint = "\u2039 %d-%d of %d \u203a" % (first + 1, first + columns,
                                                  len(channels))
            hint_w = self.fonts["tiny"].size(hint)[0]
            last_x = rect.x + 4 + gutter + columns * cell_w
            if last_x + 8 + hint_w < readout_x - 8:
                self._text(readout_x - hint_w - 8, head.y + 4, hint, "tiny",
                           t.warn)


        for slot in range(visible):
            row_index = self.pattern_row + slot
            y = rect.y + 2 + header_h + slot * row_h
            row_rect = pygame.Rect(rect.x + 2, y, rect.width - 4, row_h)
            highlight = playing_row is not None and row_index == playing_row
            if highlight:
                pygame.draw.rect(self.screen, t.playing, row_rect)
            elif row_index % 4 == 0:
                pygame.draw.rect(self.screen, t.stripe, row_rect)

            if row_index == hover:
                pygame.draw.rect(self.screen, t.light, row_rect, 1)
            elif row_index == self.pattern_row and not highlight:
                pygame.draw.rect(self.screen, t.accent, row_rect, 1)
            number_color = t.accent if row_index % 16 == 0 else t.text
            self._text(rect.x + 6, y, "%02X" % (row_index % 256), "small",
                       number_color)
            for column in range(columns):
                index = first + column
                if index >= len(channels):
                    break
                x = rect.x + 4 + gutter + column * cell_w
                note = grid.get((row_index, index))
                if note is None:
                    self.screen.blit(pattern_font.render("--- .. ..", t.smooth,
                                                         t.empty_text),
                                     (x + 2, y))
                    continue
                pitch = gm.pitch_name(note.pitch)
                letter, octave = pitch[:-1], pitch[-1]
                text = "%s%s%s" % (letter, "" if len(letter) > 1 else "-", octave)
                colour = t.playing_text if highlight else (
                    t.dim if note.shared else t.field_text)
                secondary = t.playing_text if highlight else t.pattern_header_text
                self.screen.blit(pattern_font.render(text, t.smooth, colour),
                                 (x + 2, y))
                wid = pattern_font.size(text)[0]
                instrument = "%02X" % (note.program % 256)
                self.screen.blit(pattern_font.render(instrument, t.smooth,
                                                     secondary),
                                 (x + 2 + wid + 6, y))
                volume = "%02X" % int(round(max(0, min(15, note.volume)) * 0x40 / 15.0))
                self.screen.blit(
                    pattern_font.render(volume, t.smooth,
                                        t.pattern_value if note.volume > 3
                                        else t.dim),
                    (x + 2 + wid + 6 + pattern_font.size(instrument)[0] + 8, y))

        # scrollbars: rows on the right, channels along the bottom
        if rows > visible:
            bar = pygame.Rect(rect.right - 13, rect.y + 2 + header_h, 11,
                              rect.height - header_h - 6)
            theme.scrollbar(self.screen, bar, t,
                            self.pattern_row / max(1, rows - visible),
                            visible / max(1, rows))
        if len(channels) > columns:
            bar = pygame.Rect(rect.x + 4 + gutter, rect.bottom - 12,
                              rect.width - gutter - 20, 10)
            theme.scrollbar(self.screen, bar, t,
                            first / max(1, len(channels) - columns),
                            columns / max(1, len(channels)))

        self.hits.append((rect, self._pattern_click))

    def _pattern_click(self) -> None:
        """Clicking a row starts playback there, like clicking in a tracker."""
        data = self._pattern_data()
        if data[0] is None or not self.results:
            return
        row_seconds = data[2]
        header_h = 20
        row_h = self.fonts["pattern"].get_height() + 2
        pattern_rect = self._pattern_rect()
        if pattern_rect is None:
            return
        row = self.pattern_row + max(0, (self.mouse[1] - pattern_rect.y - 2 - header_h)
                                     // row_h)
        seconds = max(0.0, row * row_seconds)
        if self.playing is not None:
            self.stop()
        self.play(self.selected_result, start=seconds)

    def _pattern_rect(self):
        width, height = self.screen.get_size()
        top = 68
        bottom = height - 22 - 6
        right_w = 244
        return pygame.Rect(4, top, width - right_w - 12, bottom - top)

    def _empty_pattern(self, rect: pygame.Rect) -> None:
        t = self.theme
        message = [
            "no song loaded",
            "",
            "drop a .mid / .vgm / .vgz / .gym / .zip anywhere on this window",
            "then press CONVERT",
            "",
            "the NES channels appear here as tracker columns:",
            "pulse1  pulse2  triangle  noise  (+ VRC6 / MMC5 / FDS / N163 / PSG)",
        ]
        y = rect.y + 14
        for line in message:
            colour = t.dim if line.startswith("drop") or line.startswith("then") else t.text
            self._text(rect.x + 14, y, line, "small", colour)
            y += 16

    # -------------------------------------------------------------- side panel

    def _draw_side(self, rect: pygame.Rect) -> None:
        t = self.theme
        x = rect.x
        width = rect.width

        chips_box = pygame.Rect(x, rect.y, width, 168)
        self._box(chips_box, "CHIPS")
        entries = [("", "NES base", 4)]
        for name, spec in chips.EXTENSION_CHANNELS.items():
            entries.append((name, name.upper(), len(spec)))
        self.chip_rects = []
        y = chips_box.y + 18
        for index, (name, label, count) in enumerate(entries):
            row = pygame.Rect(chips_box.x + 3, y, chips_box.width - 6, 17)
            on = name == "" or name in self.settings.extensions
            if row.collidepoint(self.mouse) and name:
                pygame.draw.rect(self.screen, t.face_alt, row)
            self._text(row.x + 2, row.y + 1, "%02d" % (index + 1), "tiny",
                       t.accent if on else (0, 0, 96))
            self._text(row.x + 24, row.y + 1, "%s +%d" % (label, count), "small",
                       t.text if on else t.dim)
            self._text(row.right - 18, row.y + 1, "ON" if on else "..", "tiny",
                       t.ok if on else (0, 0, 96))
            self.chip_rects.append((name, row.copy()))
            if name:
                self.hits.append((row.copy(), (lambda n=name: self.toggle_chip(n))))
            y += 17

        queue_box = pygame.Rect(x, chips_box.bottom + 6, width, 104)
        self._box(queue_box, "FILES TO CONVERT")
        if not self.items:
            self._text(queue_box.x + 5, queue_box.y + 20,
                       "drop files here", "small", t.dim)
        self.mouse_in_queue = queue_box.collidepoint(self.mouse)
        row_h = 17
        visible = (queue_box.height - 22) // row_h
        self.scroll_queue = max(0, min(self.scroll_queue,
                                       max(0, len(self.items) - visible)))
        for slot in range(min(visible, len(self.items) - self.scroll_queue)):
            index = slot + self.scroll_queue
            item = self.items[index]
            row = pygame.Rect(queue_box.x + 3, queue_box.y + 18 + slot * row_h,
                              queue_box.width - 6, row_h)
            if row.collidepoint(self.mouse):
                pygame.draw.rect(self.screen, t.face_alt, row)
            self._text(row.x + 2, row.y + 1,
                       _fit(self.fonts["small"], item.name, row.width - 30),
                       "small", t.text)
            close = pygame.Rect(row.right - 22, row.y + 1, 20, 13)
            self._text(close.x + 6, close.y, "x", "small", t.dim)
            self.hits.append((close, (lambda i=index: self.remove_item(i))))
        self.hits.append((queue_box, self.pick_files))

        # the menu: a column of tracker-style buttons
        menu_top = queue_box.bottom + 6
        rows = [
            [("ADD FILES", self.pick_files), ("DEMO", self.add_demo)],
            [("CONVERT", self.start_convert), ("STOP", self.stop)],
            [("PLAY", lambda: self.play(self.selected_result)),
             ("SAVE AS", lambda: self.save_result(self.selected_result))],
            [("FOLDER", lambda: self.open_folder(self.selected_result)),
             ("CLEAR", self.clear_queue)],
            [("16-BIT" if self.settings.bits > 8 else "8-BIT", self.toggle_bits),
             ("VGM", self.toggle_vgm)],
            [("DRUMS" if self.settings.sampled_drums else "NOISE", self.toggle_drums),
             ("LOOK", self.switch_look)],
        ]
        button_h = 22
        gap = 4
        y = menu_top
        for pairs in rows:
            for column, (label, action) in enumerate(pairs):
                button_rect = pygame.Rect(x + 2 + column * (width // 2),
                                          y, width // 2 - 4, button_h)
                active = (label == "VGM" and self.settings.export_vgm) or \
                         (label == "DRUMS")
                pressed = label == "CONVERT" and self.busy
                theme.button(self.screen, button_rect, t,
                             label, self.fonts["small"], pressed=pressed)
                if active:
                    pygame.draw.rect(self.screen, t.accent, button_rect.inflate(-6, -6), 1)
                enabled = True
                if label in ("CONVERT",):
                    enabled = bool(self.items) and not self.busy
                if label in ("PLAY", "STOP", "SAVE AS", "FOLDER"):
                    enabled = bool(self.results)
                if label == "CONVERT":
                    self.convert_rect = button_rect.copy()
                if enabled:
                    self.hits.append((button_rect.copy(), action))
            y += button_h + gap

        results_box = pygame.Rect(x, y + 2, width, rect.bottom - (y + 2))
        self._box(results_box, "CONVERTED  %d" % len(self.results))
        if not self.results:
            self._text(results_box.x + 5, results_box.y + 19,
                       "nothing converted yet", "small", t.dim)
            self._draw_progress(results_box)
            return

        self.mouse_in_results = results_box.collidepoint(self.mouse)
        row_h = 32
        visible = max(1, (results_box.height - 22) // row_h)
        self.scroll_results = max(0, min(self.scroll_results,
                                         max(0, len(self.results) - visible)))
        for slot in range(min(visible, len(self.results) - self.scroll_results)):
            index = slot + self.scroll_results
            result = self.results[index]
            row = pygame.Rect(results_box.x + 3, results_box.y + 18 + slot * row_h,
                              results_box.width - 6, row_h - 2)
            selected = index == self.selected_result
            if selected:
                pygame.draw.rect(self.screen, t.title_active, row)
            elif row.collidepoint(self.mouse):
                pygame.draw.rect(self.screen, t.face_alt, row)
            marker = ">" if selected else " "
            self._text(row.x + 2, row.y + 1, marker + os.path.basename(
                result.wav_path)[:26], "small",
                t.title_text if selected else t.text)
            if result.ok:
                line = "%d voices · %d kept" % (result.voices, result.kept)
                if result.left_out:
                    line += " · %d left out" % result.left_out
                if getattr(result, "dropped", 0):
                    line += " · %d dropped" % result.dropped
            else:
                line = "failed: " + result.error[:30]
            self._text(row.x + 12, row.y + 14, _fit(self.fonts["tiny"], line,
                                                    row.width - 16), "tiny",
                       t.light if selected else t.dim)
            self.hits.append((row, (lambda i=index: self.select_result(i))))

        self._draw_progress(results_box)

    def _draw_progress(self, box: pygame.Rect) -> None:
        t = self.theme
        if not self.busy:
            return
        well = pygame.Rect(box.x + 4, box.bottom - 16, box.width - 8, 12)
        theme.field(self.screen, well, t, t.accent_dark)
        filled = int((well.width - 4) * max(0.0, min(1.0, self.progress)))
        pygame.draw.rect(self.screen, t.accent,
                         pygame.Rect(well.x + 2, well.y + 2, filled, well.height - 4))

    def _box(self, rect: pygame.Rect, title: str) -> None:
        t = self.theme
        pygame.draw.rect(self.screen, t.face, rect)
        theme.bevel(self.screen, rect, t, raised=True)
        bar = pygame.Rect(rect.x + 2, rect.y + 2, rect.width - 4, 14)
        pygame.draw.rect(self.screen, t.title_active, bar)
        self._text(bar.x + 3, bar.y, title, "tiny", t.title_text)

    def select_result(self, index: int) -> None:
        if 0 <= index < len(self.results):
            self.selected_result = index
            self.pattern_row = 0

    def _draw_status(self, width: int, y: int, height: int) -> None:
        t = self.theme
        bar = pygame.Rect(2, y, width - 4, height)
        pygame.draw.rect(self.screen, t.face, bar)
        theme.bevel(self.screen, bar, t, raised=False)
        text = self.progress_label if self.busy else self.status
        self._text(bar.x + 4, bar.y + 3, _fit(self.fonts["small"], text,
                                              bar.width - 160),
                   "small", t.bad if self.status_error else t.text)
        state = "Working" if self.busy else ("Playing" if self.playing is not None
                                             else "Free")
        state_font = self.fonts["small"]
        state_x = bar.right - state_font.size(state)[0] - 6
        self._text(state_x, bar.y + 3, state, "small",
                   t.accent if state == "Free" else t.warn)
        voices = "%d voices" % self.voice_count()
        voices_x = state_x - self.fonts["small"].size(voices)[0] - 18
        self._text(voices_x, bar.y + 3, voices, "small", t.dim)
        total = len(chips.build_channel_set(self.settings.extensions))
        shown = getattr(self, "pattern_columns", total)
        first = getattr(self, "pattern_column", 0) + 1
        ratio = ("CH %d-%d/%d" % (first, min(first + shown - 1, total), total)
                 if shown < total else "CH %d/%d" % (total, total))
        ratio_x = voices_x - self.fonts["small"].size(ratio)[0] - 14
        self._text(ratio_x, bar.y + 3, ratio, "small",
                   t.warn if shown < total else t.dim)

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


def run(files: Optional[List[str]] = None) -> int:
    return App(files=files).run()


def _visible_columns(app) -> int:
    return getattr(app, "pattern_columns", 1)


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

        for name, rect in app.chip_rects:
            if name:
                click(rect)
        check("all chips on => 22 voices", app.voice_count() == 22,
              str(app.voice_count()))

        app.switch_look()
        check("switching the look works", app.look == "win95", app.look)
        app.draw()

        app.add_demo()
        check("demo queued", len(app.items) == 1)
        click(app.convert_rect)
        deadline = time.time() + 120
        while app.busy and time.time() < deadline:
            app._drain()
            app.render_once()
            time.sleep(0.02)
        check("conversion finished", not app.busy)
        check("one result", len(app.results) == 1)
        if app.results:
            result = app.results[0]
            check("result ok", result.ok, result.error)
            check("wav on disk", os.path.isfile(result.wav_path))
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
            check("pattern grid has notes", bool(pattern[4]),
                  str(len(pattern[4])))
            check("notes left out are reported",
                  isinstance(getattr(result, "left_out", None), int),
                  str(getattr(result, "left_out", None)))
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
            rect = app._pattern_rect()
            app.mouse = (rect.x + 120, rect.y + 2 + 20 +
                         (app.fonts["pattern"].get_height() + 2) * 3 + 8)
            app._pattern_click()
            check("clicking a pattern row plays",
                  app.playing == 0 or not app.mixer_ready, str(app.playing))
            app.stop()

        if screenshot:
            # both looks, so the release shows what switching the theme does
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
