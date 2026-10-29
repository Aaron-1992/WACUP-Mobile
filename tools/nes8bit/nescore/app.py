"""The chip8bit window, drawn like it is 1995.

One native window, two period looks — Windows 95 (teal desktop, bevelled grey,
navy title bars) and Amiga Workbench (blue desktop, orange accents, chunky
borders). No browser, no server, no page.

The window also shows what the converter understood about the file: tempo, meter,
instruments, and how many melody/bass/harmony/percussion lines it found.
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

from . import chips, convert, dialogs, demo, theme

WIDTH, HEIGHT = 1080, 760
MIN_WIDTH, MIN_HEIGHT = 940, 660
FPS = 60


def _font(theme_obj: theme.Theme, size: int, bold: bool = False):
    for name in theme_obj.fonts():
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


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
            "title": _font(t, 17, bold=True),
            "head": _font(t, 12, bold=True),
            "body": _font(t, 14),
            "small": _font(t, 12),
            "button": _font(t, 13, bold=True),
        }

    @staticmethod
    def _default_settings_path() -> str:
        base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base, "chip8bit-settings.json")

    def _load_settings(self):
        settings = convert.Settings()
        look = "win95"
        try:
            with open(self.settings_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, ValueError):
            return settings, look
        settings.extensions = [name for name in saved.get("extensions", [])
                               if name in chips.EXTENSION_CHANNELS]
        settings.bits = 16 if saved.get("bits", 16) != 8 else 8
        settings.export_vgm = bool(saved.get("export_vgm", False))
        settings.sharing = bool(saved.get("sharing", True))
        settings.sampled_drums = bool(saved.get("sampled_drums", True))
        look = saved.get("look", "win95")
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

    def play(self, index: int) -> None:
        if not (0 <= index < len(self.results)):
            return
        result = self.results[index]
        if not result.ok or not self.mixer_ready:
            return
        try:
            pygame.mixer.music.load(result.wav_path)
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
            if self.mouse_in_queue:
                self.scroll_queue = max(0, self.scroll_queue - event.y)
            elif self.mouse_in_results:
                self.scroll_results = max(0, self.scroll_results - event.y)
        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.start_convert()
            elif event.key == pygame.K_SPACE:
                self.stop() if self.playing is not None else self.play(0)
            elif event.key == pygame.K_o and event.mod & pygame.KMOD_CTRL:
                self.pick_files()
            elif event.key == pygame.K_ESCAPE:
                self.stop() if self.playing is not None else setattr(self, "running", False)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
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
        left = pygame.Rect(16, 46, 356, height - 62)
        right = pygame.Rect(384, 46, width - 400, height - 62)
        self._draw_queue(left)
        self._draw_right(right)

    def _text(self, x, y, text, font="body", color=None):
        t = self.theme
        surface = self.fonts[font].render(text, False, color or t.text)
        self.screen.blit(surface, (x, y))

    def _draw_titlebar(self, width: int) -> None:
        t = self.theme
        bar = pygame.Rect(4, 4, width - 8, 30)
        pygame.draw.rect(self.screen, t.face, bar)
        pygame.draw.rect(self.screen, t.dark, bar, 1)
        fill = pygame.Rect(bar.x + 3, bar.y + 3, bar.width - 6, bar.height - 6)
        pygame.draw.rect(self.screen, t.title_active, fill)
        self._text(fill.x + 6, fill.y + 4, "chip8bit — NES / 8-bit transcoder",
                   "title", t.title_text)

        # the two buttons a 1995 title bar always had
        size = fill.height - 4
        x = fill.right - size - 4
        for glyph in ("_", "X"):
            rect = pygame.Rect(x, fill.y + 2, size, size)
            pygame.draw.rect(self.screen, t.face, rect)
            theme.bevel(self.screen, rect, t, raised=True)
            text = self.fonts["small"].render(glyph, False, t.text)
            self.screen.blit(text, text.get_rect(center=(rect.centerx,
                                                         rect.centery - 1)))
            x -= size + 3

        badge = "%d voices · %s" % (self.voice_count(), t.name)
        surface = self.fonts["small"].render(badge, False, t.title_text)
        self.screen.blit(surface, (fill.right - 110 - surface.get_width(),
                                   fill.y + 4))
        # clicking the title bar button toggles the look
        self.hits.append((pygame.Rect(fill.right - 260, fill.y, 150, fill.height),
                          self.switch_look))

    def _panel(self, rect: pygame.Rect, title: str) -> pygame.Rect:
        return theme.window(self.screen, rect, self.theme, title,
                            self.fonts["button"])

    def _draw_queue(self, panel: pygame.Rect) -> None:
        t = self.theme
        client = self._panel(panel, "1 · Add music")
        x = client.x + 2
        width = client.width - 4

        zone = pygame.Rect(x, client.y + 2, width, 74)
        theme.field(self.screen, zone, t, t.face_alt)
        hot = zone.collidepoint(self.mouse)
        if hot:
            pygame.draw.rect(self.screen, t.accent, zone, 2)
        line1 = self.fonts["body"].render("Drop files here", False, t.text)
        line2 = self.fonts["small"].render(".mid  .midi  .rmi  .kar  .vgm  .vgz  .gym  .zip",
                                           False, t.dim)
        self.screen.blit(line1, line1.get_rect(center=(zone.centerx, zone.centery - 11)))
        self.screen.blit(line2, line2.get_rect(center=(zone.centerx, zone.centery + 13)))
        self.hits.append((zone, self.pick_files))

        buttons_y = client.bottom - 32
        self._button(pygame.Rect(x, buttons_y, 108, 26), "Add files…", self.pick_files)
        self._button(pygame.Rect(x + 114, buttons_y, 92, 26), "Demo tune", self.add_demo)
        self._button(pygame.Rect(x + 212, buttons_y, 60, 26), "Clear", self.clear_queue)

        list_top = zone.bottom + 8
        self.queue_view = pygame.Rect(x, list_top, width, max(20, buttons_y - 8 - list_top))
        self.mouse_in_queue = panel.collidepoint(self.mouse)
        theme.field(self.screen, self.queue_view, t, t.face_alt)

        row_height = 34
        visible = max(1, (self.queue_view.height - 4) // row_height)
        if len(self.items) > visible:
            self.queue_view.width -= 14
        self.scroll_queue = min(self.scroll_queue, max(0, len(self.items) - visible))

        if not self.items:
            self._text(x + 6, list_top + 6, "Nothing queued yet.", "small", t.dim)
        for slot in range(visible):
            index = slot + self.scroll_queue
            if index >= len(self.items):
                break
            item = self.items[index]
            row = pygame.Rect(self.queue_view.x + 2, list_top + 2 + slot * row_height,
                              self.queue_view.width - 4, row_height - 4)
            if row.collidepoint(self.mouse):
                pygame.draw.rect(self.screen, t.accent, row.inflate(-2, -2), 1)
            name = _fit(self.fonts["body"], item.name, row.width - 90)
            self._text(row.x + 4, row.y + 6, name, "body")
            self._text(row.right - 76, row.y + 8, _human(item.size) if item.size else "",
                       "small", t.dim)
            close = pygame.Rect(row.right - 24, row.y + 5, 18, 18)
            theme.button(self.screen, close, t, "×", self.fonts["small"])
            self.hits.append((close, (lambda i=index: self.remove_item(i))))

        if len(self.items) > visible:
            bar = pygame.Rect(list_top + 2, self.queue_view.y + 2, 12,
                              self.queue_view.height - 4)
            bar = pygame.Rect(self.queue_view.right + 2, list_top + 2, 12,
                              self.queue_view.height - 4)
            theme.scrollbar(self.screen, bar, t, self.scroll_queue / max(1, len(self.items)),
                            visible / max(1, len(self.items)))

    def _button(self, rect, label, action, pressed=False, enabled=True, primary=False):
        theme.button(self.screen, rect, self.theme, label, self.fonts["button"],
                     pressed=pressed, enabled=enabled, primary=primary)
        if enabled:
            self.hits.append((rect.copy(), action))

    def _draw_right(self, panel: pygame.Rect) -> None:
        t = self.theme
        client = self._panel(panel, "2 · Pick chips")
        x = client.x + 2
        width = client.width - 4

        self.chip_rects = []
        entries = [("", "NES base console", 4, "pulse1 · pulse2 · triangle · noise")]
        blurbs = {
            "vrc6": "Konami VRC6 · 2 pulses + saw",
            "mmc5": "Nintendo MMC5 · 2 pulses",
            "fds": "Famicom Disk System · wavetable",
            "n163": "Namco 163 · 8 wavetables",
            "psg": "SN76489 · 3 squares (Genesis)",
            "dmc": "APU delta · sampled drums",
        }
        for name, spec in chips.EXTENSION_CHANNELS.items():
            entries.append((name, name.upper(), len(spec), blurbs.get(name, "")))

        card_h, gap = 46, 6
        columns = 2 if width > 520 else 1
        card_w = (width - gap * (columns - 1)) // columns
        for index, (name, label, count, blurb) in enumerate(entries):
            column, row = index % columns, index // columns
            rect = pygame.Rect(x + column * (card_w + gap), client.y + row * (card_h + gap),
                               card_w, card_h)
            enabled = name == "" or name in self.settings.extensions
            face = t.accent_dark if enabled else t.face
            pygame.draw.rect(self.screen, face, rect)
            theme.bevel(self.screen, rect, t, raised=not enabled)
            tick = pygame.Rect(rect.x + 6, rect.y + card_h // 2 - 7, 14, 14)
            theme.field(self.screen, tick, t, t.field if enabled else t.face)
            if enabled:
                pygame.draw.lines(self.screen, t.text, False,
                                  [(tick.x + 3, tick.centery), (tick.x + 6, tick.bottom - 4),
                                   (tick.right - 3, tick.y + 4)], 2)
            self._text(rect.x + 26, rect.y + 6,
                       _fit(self.fonts["button"], "%s  +%d" % (label, count), card_w - 34),
                       "button")
            self._text(rect.x + 26, rect.y + 24,
                       _fit(self.fonts["small"], blurb, card_w - 34), "small", t.dim)
            self.chip_rects.append((name, rect))
            if name:
                self.hits.append((rect, (lambda n=name: self.toggle_chip(n))))

        rows = (len(entries) + columns - 1) // columns
        options_y = client.y + rows * (card_h + gap) + 2
        self._check(pygame.Rect(x, options_y, 130, 22), "16-bit output",
                    self.settings.bits > 8, self.toggle_bits)
        self._check(pygame.Rect(x + 136, options_y, 130, 22), "write .vgm",
                    self.settings.export_vgm, self.toggle_vgm)
        self._check(pygame.Rect(x + 272, options_y, 150, 22), "sampled drums",
                    self.settings.sampled_drums, self.toggle_drums)

        convert_y = options_y + 34
        self.convert_rect = pygame.Rect(x + 4, convert_y, width - 8, 40)
        self._button(self.convert_rect, "Converting…" if self.busy else "Convert",
                     self.start_convert, pressed=self.busy,
                     enabled=bool(self.items) and not self.busy, primary=True)

        status_y = convert_y + 48
        if self.busy:
            well = pygame.Rect(x, status_y, width, 18)
            theme.field(self.screen, well, t, t.face_alt)
            filled = int((width - 4) * max(0.0, min(1.0, self.progress)))
            pygame.draw.rect(self.screen, t.accent,
                             pygame.Rect(well.x + 2, well.y + 2, filled, 14))
            self._text(x, status_y + 22,
                       _fit(self.fonts["small"], self.progress_label, width),
                       "small", t.dim)
            status_y += 40
        else:
            self._text(x, status_y, _fit(self.fonts["small"], self.status, width),
                       "small", t.bad if self.status_error else t.dim)
            status_y += 20

        self._text(x, status_y + 2, "3 · RESULTS", "head", t.dim)
        list_top = status_y + 20
        self.results_view = pygame.Rect(x, list_top, width,
                                        max(20, client.bottom - list_top))
        self.mouse_in_results = self.results_view.collidepoint(self.mouse)
        theme.field(self.screen, self.results_view, t, t.face_alt)

        card_h = 112
        visible = max(1, (self.results_view.height - 4) // (card_h + 6))
        self.scroll_results = min(self.scroll_results,
                                  max(0, len(self.results) - visible))
        if not self.results:
            self._text(x + 6, list_top + 6, "Converted files land here.", "small", t.dim)
        for slot in range(visible):
            index = slot + self.scroll_results
            if index >= len(self.results):
                break
            rect = pygame.Rect(self.results_view.x + 2,
                               list_top + 2 + slot * (card_h + 6),
                               self.results_view.width - 4, card_h - 2)
            self._draw_result(index, rect)

    def _check(self, rect, label, checked, action):
        theme.checkbox(self.screen, rect, self.theme, label, self.fonts["small"], checked)
        self.hits.append((rect, action))

    def _draw_result(self, index: int, rect: pygame.Rect) -> None:
        t = self.theme
        result = self.results[index]
        pygame.draw.rect(self.screen, t.face, rect)
        theme.bevel(self.screen, rect, t, raised=False)

        name = os.path.basename(result.wav_path) if result.wav_path else result.name
        self._text(rect.x + 6, rect.y + 5,
                   _fit(self.fonts["button"], name, rect.width - 14), "button")

        if not result.ok:
            self._text(rect.x + 6, rect.y + 26,
                       _fit(self.fonts["small"], result.error, rect.width - 14),
                       "small", t.bad)
            return

        stats = result.stats
        line = "%.1f s · %d voices · %d placed · %d shared · %d thinned" % (
            result.seconds, result.voices, stats.direct if stats else 0,
            stats.shared if stats else 0, stats.simplified if stats else 0)
        self._text(rect.x + 6, rect.y + 24, _fit(self.fonts["small"], line,
                                                 rect.width - 14), "small", t.dim)

        # what the converter understood about the file
        lines = list(getattr(result, "analysis_lines", []) or [])
        for offset, text in enumerate(lines[:2]):
            self._text(rect.x + 6, rect.y + 38 + offset * 14,
                       _fit(self.fonts["small"], text, rect.width - 14),
                       "small", t.text)

        playing = self.playing == index
        y = rect.bottom - 26
        self._button(pygame.Rect(rect.x + 6, y, 64, 22),
                     "Stop" if playing else "Play",
                     (lambda i=index: self.stop() if self.playing == i else self.play(i)))
        self._button(pygame.Rect(rect.x + 76, y, 84, 22), "Save as…",
                     lambda i=index: self.save_result(i))
        self._button(pygame.Rect(rect.x + 166, y, 96, 22), "Open folder",
                     lambda i=index: self.open_folder(i))
        if result.warnings:
            self._text(rect.x + 270, y + 5,
                       _fit(self.fonts["small"], result.warnings[0], rect.width - 280),
                       "small", t.warn)

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
        check("starts in Windows 95", app.look == "win95", app.look)
        check("starts with 4 voices", app.voice_count() == 4)
        check("seven chip cards", len(app.chip_rects) == 7, str(len(app.chip_rects)))

        for name, rect in app.chip_rects:
            if name:
                click(rect)
        check("all chips on => 22 voices", app.voice_count() == 22,
              str(app.voice_count()))

        app.switch_look()
        check("switching the look works", app.look == "amiga", app.look)
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
            app.play(0)
            check("play accepted", app.playing == 0 or not app.mixer_ready)
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
