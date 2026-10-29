"""The chip8bit window: a self-contained desktop app drawn with pygame.

No browser, no server, no page: one native window with drag-and-drop, chip
toggles, a conversion button, and a player for the result. pygame is used only
for the window, the drawing and the audio playback; the conversion itself is the
same code the command line runs.
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

from . import chips, convert, dialogs, demo, samples

WIDTH, HEIGHT = 1080, 740
MIN_WIDTH, MIN_HEIGHT = 940, 640
FPS = 60

BG = (13, 17, 23)
PANEL = (22, 27, 34)
PANEL_2 = (28, 36, 48)
LINE = (42, 53, 66)
TEXT = (230, 237, 243)
MUTED = (139, 152, 165)
DIM = (95, 107, 120)
ACCENT = (110, 231, 183)
ACCENT_DARK = (16, 36, 29)
BLUE = (56, 189, 248)
WARN = (251, 191, 36)
BAD = (248, 113, 113)
OK = (52, 211, 153)


def _font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in ("Segoe UI", "DejaVu Sans", "Noto Sans", "Liberation Sans",
                 "Arial", "Helvetica"):
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


def _fit(font: pygame.font.Font, text: str, width: int) -> str:
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "…")[0] > width:
        text = text[:-1]
    return text + "…" if text else ""


def _icon_close(surface: pygame.Surface, rect: pygame.Rect, color) -> None:
    inset = 7
    pygame.draw.line(surface, color, (rect.x + inset, rect.y + inset),
                     (rect.right - inset, rect.bottom - inset), 2)
    pygame.draw.line(surface, color, (rect.right - inset, rect.y + inset),
                     (rect.x + inset, rect.bottom - inset), 2)


def _human(size: int) -> str:
    if size > 1024 * 1024:
        return "%.1f MB" % (size / 1048576.0)
    if size > 1024:
        return "%d KB" % round(size / 1024.0)
    return "%d B" % size


class QueueItem:
    def __init__(self, path: str, name: str, size: int = 0, error: str = ""):
        self.path = path
        self.name = name
        self.size = size
        self.error = error


class App:
    """The whole window: state, input, drawing and playback."""

    def __init__(self, files: Optional[List[str]] = None,
                 settings_path: Optional[str] = None, headless: bool = False):
        pygame.init()
        pygame.display.set_caption("chip8bit — NES / 8-bit transcoder")
        flags = pygame.RESIZABLE
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), flags)
        self.clock = pygame.time.Clock()
        self.headless = headless

        self.f_title = _font(26, bold=True)
        self.f_sub = _font(13)
        self.f_head = _font(12, bold=True)
        self.f_body = _font(14)
        self.f_small = _font(12)
        self.f_button = _font(14, bold=True)
        self.f_big = _font(16, bold=True)

        self.settings_path = settings_path or self._default_settings_path()
        self.settings = self._load_settings()

        self.items: List[QueueItem] = []
        self.results: List[convert.Result] = []
        self.messages: queue.Queue = queue.Queue()
        self.busy = False
        self.progress = 0.0
        self.progress_label = ""
        self.status = "Drop MIDI, VGM or GYM files onto the window, or press Add files."
        self.status_error = False

        self.hits: List[tuple] = []
        self.hover: Optional[str] = None
        self.scroll_queue = 0
        self.scroll_results = 0
        self.playing: Optional[int] = None
        self.mixer_ready = self._init_mixer()
        self.audio_cache: Dict[str, str] = {}
        self.running = True
        self.chip_rects: List[tuple] = []
        self.convert_rect = pygame.Rect(0, 0, 0, 0)
        self.queue_remove_rects: List[pygame.Rect] = []
        self.mouse_in_queue = False
        self.mouse_in_results = False

        for path in files or []:
            self.add_path(path)

    # ------------------------------------------------------------------ startup

    @staticmethod
    def _default_settings_path() -> str:
        base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base, "chip8bit-settings.json")

    def _load_settings(self) -> convert.Settings:
        settings = convert.Settings()
        try:
            with open(self.settings_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, ValueError):
            return settings
        settings.extensions = [name for name in saved.get("extensions", [])
                               if name in chips.EXTENSION_CHANNELS]
        settings.bits = 16 if saved.get("bits", 16) != 8 else 8
        settings.export_vgm = bool(saved.get("export_vgm", False))
        settings.sharing = bool(saved.get("sharing", True))
        settings.sampled_drums = bool(saved.get("sampled_drums", True))
        return settings

    def _save_settings(self) -> None:
        try:
            with open(self.settings_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "extensions": list(self.settings.extensions),
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

    # -------------------------------------------------------------------- files

    def add_path(self, path: str) -> None:
        if not os.path.isfile(path):
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if any(item.path == path for item in self.items):
            return
        self.items.append(QueueItem(path, os.path.basename(path), size))
        self.status = "Ready. %d file%s queued." % (len(self.items),
                                                    "" if len(self.items) == 1 else "s")
        self.status_error = False

    def add_demo(self) -> None:
        directory = os.path.join(tempfile.gettempdir(), "chip8bit-demo")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "chip8bit demo tune.mid")
        if not os.path.isfile(path):
            with open(path, "wb") as handle:
                handle.write(demo.build())
        self.add_path(path)
        self.status = "Demo tune queued — press Convert."

    # ------------------------------------------------------------------- convert

    def start_convert(self) -> None:
        if self.busy or not self.items:
            return
        settings = self.settings
        files = [(item.path, item.name) for item in self.items]
        self.busy = True
        self.progress = 0.0
        self.progress_label = "Starting"
        self.status_error = False
        thread = threading.Thread(target=self._work, args=(files, settings), daemon=True)
        thread.start()

    def _work(self, files, settings: convert.Settings) -> None:
        output_dir = dialogs.default_output_dir()
        for index, (path, name) in enumerate(files):
            def progress(stage, fraction, path=path, index=index):
                overall = (index + max(0.0, min(1.0, fraction))) / len(files)
                self.messages.put(("progress", stage, overall, name))

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
                for item in list(self.items):
                    if item.path == path:
                        self.items.remove(item)
                if result.ok:
                    self.status = "Saved %s" % os.path.basename(result.wav_path)
                    self.status_error = False
                else:
                    self.status = "%s: %s" % (os.path.basename(path), result.error)
                    self.status_error = True
            elif message[0] == "done":
                self.busy = False
                self.progress = 0.0
                self.progress_label = ""

    # ------------------------------------------------------------------ playback

    def play(self, index: int) -> None:
        if not (0 <= index < len(self.results)):
            return
        result = self.results[index]
        if not result.ok:
            return
        if not self.mixer_ready:
            self.status = "No audio device available."
            self.status_error = True
            return
        path = result.wav_path
        if not path or not os.path.isfile(path):
            if not result.wav_bytes:
                return
            handle, path = tempfile.mkstemp(suffix=".wav", prefix="chip8bit-")
            with os.fdopen(handle, "wb") as out:
                out.write(result.wav_bytes)
            self.audio_cache[result.wav_path] = path
        try:
            pygame.mixer.music.load(path)
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
        default = os.path.basename(result.wav_path) or convert.output_name(
            result.name, self.settings)
        destination = dialogs.save_as(default)
        if not destination:
            if result.wav_path and os.path.isfile(result.wav_path):
                self.status = "Already saved to %s" % result.wav_path
                self.status_error = False
            return
        try:
            if result.wav_bytes:
                with open(destination, "wb") as handle:
                    handle.write(result.wav_bytes)
            else:
                with open(result.wav_path, "rb") as source, open(destination, "wb") as out:
                    out.write(source.read())
            self.status = "Copied to %s" % destination
            self.status_error = False
        except OSError as error:
            self.status = "Could not save: %s" % error
            self.status_error = True

    def open_folder(self, index: int) -> None:
        result = self.results[index]
        if result.wav_path:
            dialogs.reveal(result.wav_path)

    # -------------------------------------------------------------------- events

    def handle_event(self, event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.VIDEORESIZE:
            width = max(MIN_WIDTH, event.w)
            height = max(MIN_HEIGHT, event.h)
            self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        elif event.type == pygame.DROPFILE:
            paths = getattr(event, "files", None) or [event.file]
            for path in paths:
                self.add_path(path)
        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.start_convert()
            elif event.key == pygame.K_SPACE:
                if self.playing is None:
                    self.play(0)
                else:
                    self.stop()
            elif event.key in (pygame.K_o,) and event.mod & pygame.KMOD_CTRL:
                self.pick_files()
            elif event.key == pygame.K_ESCAPE:
                if self.playing is not None:
                    self.stop()
                else:
                    self.running = False
        elif event.type == pygame.MOUSEWHEEL:
            if self.mouse_in_queue:
                self.scroll_queue = max(0, self.scroll_queue - event.y)
            elif self.mouse_in_results:
                self.scroll_results = max(0, self.scroll_results - event.y)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, action in self.hits:
                if rect.collidepoint(event.pos):
                    action()
                    break

    def pick_files(self) -> None:
        paths = dialogs.open_files()
        if paths:
            for path in paths:
                self.add_path(path)
        else:
            self.status = ("Use drag and drop if the file picker does not open — "
                           "drop files straight onto this window.")
            self.status_error = False

    # ------------------------------------------------------------------- drawing

    def draw(self) -> None:
        self.hits = []
        width, height = self.screen.get_size()
        self.screen.fill(BG)
        self.mouse = pygame.mouse.get_pos()

        self._draw_header(width)
        left = pygame.Rect(20, 84, 348, height - 104)
        right = pygame.Rect(384, 84, width - 404, height - 104)
        self._draw_queue(left)
        self._draw_right(right, height)

    def _panel(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=14)
        pygame.draw.rect(self.screen, LINE, rect, width=1, border_radius=14)

    def _heading(self, x: int, y: int, text: str) -> None:
        self.screen.blit(self.f_head.render(text.upper(), True, MUTED), (x, y))

    def _text(self, x: int, y: int, text: str, font=None, color=TEXT) -> None:
        self.screen.blit((font or self.f_body).render(text, True, color), (x, y))

    def _button(self, rect: pygame.Rect, label: str, action, kind: str = "normal",
                enabled: bool = True, key: str = "") -> None:
        hovered = enabled and rect.collidepoint(self.mouse)
        if kind == "primary":
            base = (46, 230, 166) if hovered else (34, 197, 141)
            foreground = (4, 35, 26)
        elif kind == "ghost":
            base = (34, 43, 54) if hovered else PANEL_2
            foreground = TEXT if enabled else DIM
        else:
            base = (44, 56, 70) if hovered else (33, 42, 53)
            foreground = TEXT if enabled else DIM
        pygame.draw.rect(self.screen, base, rect, border_radius=9)
        if kind != "primary":
            pygame.draw.rect(self.screen, LINE, rect, width=1, border_radius=9)
        font = self.f_big if kind == "primary" else self.f_button
        surface = font.render(label, True, foreground)
        self.screen.blit(surface, surface.get_rect(center=rect.center))
        if enabled:
            self.hits.append((rect.copy(), action))

    def _draw_header(self, width: int) -> None:
        pygame.draw.rect(self.screen, (17, 22, 30),
                         pygame.Rect(0, 0, width, 64))
        pygame.draw.line(self.screen, LINE, (0, 64), (width, 64))
        title = self.f_title.render("chip", True, TEXT)
        self.screen.blit(title, (22, 16))
        offset = 22 + title.get_width()
        accent = self.f_title.render("8", True, ACCENT)
        self.screen.blit(accent, (offset, 16))
        offset += accent.get_width()
        rest = self.f_title.render("bit", True, TEXT)
        self.screen.blit(rest, (offset, 16))
        self.screen.blit(self.f_sub.render(
            "MIDI & Genesis game music, re-composed for the NES chip",
            True, MUTED), (22 + self.f_title.size("chip8bit")[0] + 18, 24))

        voices = self.voice_count()
        badge = "%d voices" % voices
        surface = self.f_button.render(badge, True, ACCENT)
        rect = pygame.Rect(width - surface.get_width() - 40, 20,
                           surface.get_width() + 24, 26)
        pygame.draw.rect(self.screen, ACCENT_DARK, rect, border_radius=13)
        pygame.draw.rect(self.screen, (31, 92, 72), rect, width=1, border_radius=13)
        self.screen.blit(surface, surface.get_rect(center=rect.center))

    def voice_count(self) -> int:
        return 4 + sum(len(chips.EXTENSION_CHANNELS[name])
                       for name in self.settings.extensions
                       if name in chips.EXTENSION_CHANNELS)

    # ---- left panel: the queue

    def _draw_queue(self, panel: pygame.Rect) -> None:
        self._panel(panel)
        x = panel.x + 16
        self._heading(x, panel.y + 14, "1 · Add music")

        zone = pygame.Rect(x, panel.y + 38, panel.width - 32, 84)
        hot = zone.collidepoint(self.mouse)
        pygame.draw.rect(self.screen, (18, 26, 22) if hot else (17, 22, 29),
                         zone, border_radius=11)
        pygame.draw.rect(self.screen, ACCENT if hot else LINE, zone, width=2,
                         border_radius=11)
        label = self.f_body.render("Drop files here", True, TEXT if hot else MUTED)
        self.screen.blit(label, label.get_rect(center=(zone.centerx, zone.centery - 10)))
        hint = self.f_small.render(".mid .midi .rmi .kar .vgm .vgz .gym .zip",
                                   True, DIM)
        self.screen.blit(hint, hint.get_rect(center=(zone.centerx, zone.centery + 14)))
        self.hits.append((zone, self.pick_files))

        buttons_y = panel.bottom - 46
        self._button(pygame.Rect(x, buttons_y, 128, 32), "Add files…",
                     self.pick_files, "ghost")
        self._button(pygame.Rect(x + 136, buttons_y, 92, 32), "Demo tune",
                     self.add_demo, "ghost")
        self._button(pygame.Rect(x + 236, buttons_y, 80, 32), "Clear",
                     self.clear_results_and_queue, "ghost")

        list_top = zone.bottom + 12
        list_bottom = buttons_y - 10
        self.queue_view = pygame.Rect(x, list_top, panel.width - 32,
                                      max(10, list_bottom - list_top))
        self.mouse_in_queue = panel.collidepoint(self.mouse)

        row_height = 40
        visible = max(1, self.queue_view.height // row_height)
        self.scroll_queue = min(self.scroll_queue,
                                max(0, len(self.items) - visible))
        self.queue_remove_rects = []

        if not self.items:
            self._text(x + 2, list_top + 6, "Nothing queued yet.", self.f_small, DIM)
        for index in range(visible):
            item_index = index + self.scroll_queue
            if item_index >= len(self.items):
                break
            item = self.items[item_index]
            row = pygame.Rect(self.queue_view.x, list_top + index * row_height,
                              self.queue_view.width, row_height - 6)
            pygame.draw.rect(self.screen, PANEL_2, row, border_radius=9)
            pygame.draw.rect(self.screen, LINE, row, width=1, border_radius=9)
            name = _fit(self.f_body, item.name, row.width - 96)
            self._text(row.x + 10, row.y + 9, name)
            size = _human(item.size) if item.size else ""
            self._text(row.right - 66, row.y + 10, size, self.f_small, MUTED)
            close = pygame.Rect(row.right - 30, row.y + 7, 22, 22)
            pygame.draw.rect(self.screen, (38, 47, 60), close, border_radius=6)
            _icon_close(self.screen, close, MUTED)
            self.queue_remove_rects.append(close)
            self.hits.append((close, (lambda i=item_index: self.remove_item(i))))
            self.hits.append((row, (lambda i=item_index: self.inspect_item(i))))

    def remove_item(self, index: int) -> None:
        if 0 <= index < len(self.items):
            self.items.pop(index)

    def inspect_item(self, index: int) -> None:
        if 0 <= index < len(self.items):
            self.status = "%s · %s" % (self.items[index].path,
                                       _human(self.items[index].size))

    def clear_results_and_queue(self) -> None:
        self.items = []
        self.scroll_queue = 0
        self.status = "Queue cleared."

    # ---- right panel: chips, convert, results

    def _draw_right(self, panel: pygame.Rect, window_height: int) -> None:
        self._panel(panel)
        x = panel.x + 16
        inner_width = panel.width - 32

        self._heading(x, panel.y + 14, "2 · Pick chips")
        self.chip_rects = []
        card_height = 54
        gap = 10
        columns = 2 if inner_width > 560 else 1
        card_width = (inner_width - gap * (columns - 1)) // columns
        rows = 0
        y = panel.y + 38

        entries = [("", "NES base console", 4,
                    "pulse1, pulse2, triangle, noise")]
        descriptions = {
            "vrc6": "Konami VRC6 · 2 pulses + sawtooth",
            "mmc5": "Nintendo MMC5 · 2 extra pulses",
            "fds": "Famicom Disk System · wavetable voice",
            "n163": "Namco 163 · 8 wavetable voices",
            "psg": "SN76489 · 3 squares, the Genesis chip",
            "dmc": "APU delta channel · sampled drums",
        }
        for name, spec in chips.EXTENSION_CHANNELS.items():
            entries.append((name, name.upper(), len(spec),
                            descriptions.get(name, "")))

        for index, (name, label, count, description) in enumerate(entries):
            column = index % columns
            row = index // columns
            rect = pygame.Rect(x + column * (card_width + gap), y + row * (card_height + gap),
                               card_width, card_height)
            enabled = name == "" or name in self.settings.extensions
            hovered = rect.collidepoint(self.mouse) and name != ""
            pygame.draw.rect(self.screen, ACCENT_DARK if enabled else
                             ((26, 34, 44) if hovered else PANEL_2), rect,
                             border_radius=10)
            pygame.draw.rect(self.screen, ACCENT if enabled else LINE, rect, width=1,
                             border_radius=10)
            dot = pygame.Rect(rect.x + 12, rect.y + card_height // 2 - 5, 10, 10)
            pygame.draw.circle(self.screen, ACCENT if enabled else (57, 72, 90),
                               dot.center, 5)
            title_text = "%s  +%d" % (label, count) if name else "%s  %d" % (label, count)
            self.screen.blit(self.f_button.render(
                _fit(self.f_button, title_text, rect.width - 46), True,
                TEXT if enabled else MUTED), (rect.x + 30, rect.y + 9))
            self.screen.blit(self.f_small.render(
                _fit(self.f_small, description, rect.width - 46), True, DIM),
                (rect.x + 30, rect.y + 29))
            self.chip_rects.append((name, rect))
            if name:
                self.hits.append((rect, (lambda n=name: self.toggle_chip(n))))
            rows = row + 1

        chips_bottom = y + rows * (card_height + gap)

        # two small options under the chips
        options_y = chips_bottom + 2
        self._checkbox(pygame.Rect(x, options_y, 150, 26), "16-bit output",
                       self.settings.bits > 8, self.toggle_bits)
        self._checkbox(pygame.Rect(x + 158, options_y, 150, 26), "also write .vgm",
                       self.settings.export_vgm, self.toggle_vgm)
        self._checkbox(pygame.Rect(x + 316, options_y, 190, 26), "sampled drums",
                       self.settings.sampled_drums, self.toggle_drums)

        convert_y = options_y + 38
        self.convert_rect = pygame.Rect(x, convert_y, inner_width, 52)
        busy = self.busy
        self._button(self.convert_rect,
                     "Converting…" if busy else "Convert", self.start_convert,
                     "primary", enabled=bool(self.items) and not busy)

        status_y = convert_y + 62
        if busy:
            bar = pygame.Rect(x, status_y, inner_width, 6)
            pygame.draw.rect(self.screen, PANEL_2, bar, border_radius=3)
            filled = pygame.Rect(x, status_y, int(inner_width * self.progress), 6)
            pygame.draw.rect(self.screen, ACCENT, filled, border_radius=3)
            self._text(x, status_y + 12, _fit(self.f_small,
                                             self.progress_label, inner_width),
                       self.f_small, MUTED)
            status_y += 30
        else:
            self._text(x, status_y,
                       _fit(self.f_small, self.status, inner_width), self.f_small,
                       BAD if self.status_error else MUTED)
            status_y += 24

        # results
        self._heading(x, status_y + 4, "3 · Results")
        list_top = status_y + 26
        self.results_view = pygame.Rect(x, list_top, inner_width,
                                        max(10, panel.bottom - list_top - 14))
        self.mouse_in_results = self.results_view.collidepoint(self.mouse)

        card_h = 96
        visible = max(1, self.results_view.height // (card_h + 10))
        self.scroll_results = min(self.scroll_results,
                                  max(0, len(self.results) - visible))
        if not self.results:
            self._text(x + 2, list_top + 8, "Converted files land here, ready to play.",
                       self.f_small, DIM)
        for slot in range(visible):
            index = slot + self.scroll_results
            if index >= len(self.results):
                break
            rect = pygame.Rect(self.results_view.x,
                               list_top + slot * (card_h + 10),
                               self.results_view.width, card_h)
            self._draw_result(index, rect)

    def _checkbox(self, rect: pygame.Rect, label: str, checked: bool, action) -> None:
        hovered = rect.collidepoint(self.mouse)
        box = pygame.Rect(rect.x, rect.centery - 8, 16, 16)
        pygame.draw.rect(self.screen, ACCENT_DARK if checked else PANEL_2, box,
                         border_radius=4)
        pygame.draw.rect(self.screen, ACCENT if checked else LINE, box, width=1,
                         border_radius=4)
        if checked:
            pygame.draw.lines(self.screen, ACCENT, False,
                              [(box.x + 4, box.centery + 1), (box.x + 7, box.centery + 4),
                               (box.x + 12, box.centery - 3)], 2)
        self.screen.blit(self.f_small.render(label, True, TEXT if hovered else MUTED),
                         (rect.x + 24, rect.centery - 8))
        self.hits.append((rect, action))

    def _draw_result(self, index: int, rect: pygame.Rect) -> None:
        result = self.results[index]
        pygame.draw.rect(self.screen, PANEL_2, rect, border_radius=11)
        pygame.draw.rect(self.screen, LINE, rect, width=1, border_radius=11)

        name = os.path.basename(result.wav_path) if result.wav_path else result.name
        self.screen.blit(self.f_button.render(
            _fit(self.f_button, name, rect.width - 24), True, TEXT),
            (rect.x + 12, rect.y + 9))

        if result.ok:
            stats = result.stats
            bits = "16-bit" if self.settings.bits > 8 else "8-bit"
            pieces = ["%.1fs" % result.seconds, "%d voices" % result.voices, bits,
                      "%d shared" % (stats.shared if stats else 0),
                      "%d thinned" % (stats.simplified if stats else 0)]
            self.screen.blit(self.f_small.render(" · ".join(pieces), True, MUTED),
                             (rect.x + 12, rect.y + 30))
        else:
            self.screen.blit(self.f_small.render(
                _fit(self.f_small, result.error, rect.width - 24), True, BAD),
                (rect.x + 12, rect.y + 30))

        playing = self.playing == index
        self._small_button(pygame.Rect(rect.x + 12, rect.y + 54, 74, 26),
                           "Stop" if playing else "Play",
                           (lambda i=index: self.stop() if self.playing == i
                            else self.play(i)),
                           icon="stop" if playing else "play")
        self._small_button(pygame.Rect(rect.x + 94, rect.y + 54, 92, 26),
                           "Save as…", lambda i=index: self.save_result(i))
        self._small_button(pygame.Rect(rect.x + 194, rect.y + 54, 104, 26),
                           "Open folder", lambda i=index: self.open_folder(i))

        if result.warnings:
            warning = result.warnings[0]
            self.screen.blit(self.f_small.render(
                _fit(self.f_small, "! " + warning, rect.width - 330), True, WARN),
                (rect.x + 308, rect.y + 60))

    def _small_button(self, rect: pygame.Rect, label: str, action,
                      icon: str = "") -> None:
        hovered = rect.collidepoint(self.mouse)
        pygame.draw.rect(self.screen, (44, 56, 70) if hovered else (36, 46, 58),
                         rect, border_radius=7)
        pygame.draw.rect(self.screen, LINE, rect, width=1, border_radius=7)
        surface = self.f_small.render(label, True, TEXT)
        icon_width = 12 if icon else 0
        total = surface.get_width() + icon_width
        left = rect.centerx - total // 2
        if icon == "play":
            pygame.draw.polygon(self.screen, ACCENT, [
                (left, rect.centery - 6), (left, rect.centery + 6),
                (left + 9, rect.centery)])
        elif icon == "stop":
            pygame.draw.rect(self.screen, ACCENT,
                             pygame.Rect(left, rect.centery - 5, 9, 10))
        self.screen.blit(surface, (left + icon_width, rect.centery - 8))
        self.hits.append((rect, action))

    # -------------------------------------------------------------------- toggles

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

    # ----------------------------------------------------------------- main loop

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

    # -------------------------------------------------------------------- tests

    def render_once(self) -> pygame.Surface:
        """One frame, without the event loop (used by the self test)."""
        self.draw()
        pygame.display.flip()
        return self.screen


def run(files: Optional[List[str]] = None) -> int:
    app = App(files=files)
    return app.run()


def selftest(screenshot: Optional[str] = None) -> int:
    """Drive the window headlessly: click chips, drop a file, convert, play."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    failures: List[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        line = ("  ok   " if condition else "  FAIL ") + label + \
               ("" if condition else "  " + detail)
        stream = sys.stdout
        if stream is not None:
            try:
                stream.write(line + "\n")
                stream.flush()
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
    app.messages = queue.Queue()

    def click(rect: pygame.Rect) -> None:
        app.mouse = rect.center
        app.draw()
        for hit_rect, action in app.hits:
            if hit_rect.collidepoint(rect.center):
                action()
                return
        raise AssertionError("nothing to click at %s" % (rect,))

    try:
        app.draw()
        check("window opens", app.screen.get_size() == (WIDTH, HEIGHT),
              str(app.screen.get_size()))
        check("starts with 4 voices", app.voice_count() == 4, str(app.voice_count()))
        check("chip cards drawn", len(app.chip_rects) == 7, str(len(app.chip_rects)))

        for name, rect in app.chip_rects:
            if name:
                click(rect)
        check("all chips enabled", app.voice_count() == 22, str(app.voice_count()))
        check("settings persisted", os.path.isfile(settings_path))

        app.add_demo()
        check("demo queued", len(app.items) == 1, str(len(app.items)))
        app.draw()
        check("convert button is live", bool(app.items) and not app.busy)

        click(app.convert_rect)
        deadline = time.time() + 120
        while app.busy and time.time() < deadline:
            app._drain()
            app.render_once()
            time.sleep(0.02)
        check("conversion finished", not app.busy)
        check("one result", len(app.results) == 1, str(len(app.results)))
        if app.results:
            result = app.results[0]
            check("result is ok", result.ok, result.error)
            check("wav written", os.path.isfile(result.wav_path), result.wav_path)
            check("many voices used", result.voices >= 8, str(result.voices))
            check("drums are sampled",
                  app.settings.sampled_drums and bool(samples.get("kick")))
            check("duration sane", 2.0 < result.seconds < 60.0, str(result.seconds))
            if os.path.isfile(result.wav_path):
                with open(result.wav_path, "rb") as handle:
                    check("wav is a RIFF file", handle.read(4) == b"RIFF")
            app.play(0)
            check("playback accepted", app.playing == 0 or not app.mixer_ready)
            app.stop()

        app.draw()
        if screenshot:
            pygame.image.save(app.screen, screenshot)
            check("screenshot written", os.path.isfile(screenshot))
    finally:
        pygame.quit()

    print("%d window check(s) failed" % len(failures))
    return 0 if not failures else 1
