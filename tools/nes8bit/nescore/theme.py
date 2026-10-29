"""The look of the window: FastTracker II, Windows 95 and Amiga Workbench.

FastTracker II (the default) is the one from the screenshot: a blue window frame,
lavender chunky buttons with black text, black pattern pages with pale blue notes,
and pale blue row numbers. Windows 95 and Amiga Workbench are the same geometry in
very different clothes.
"""

from dataclasses import dataclass
from typing import Tuple

import pygame

Color = Tuple[int, int, int]


@dataclass
class Theme:
    key: str
    name: str

    desktop: Color            # behind the window frame
    face: Color               # button and panel faces
    face_alt: Color           # a slightly different face (headers, lists)
    light: Color              # raised highlight
    shadow: Color             # raised shadow
    dark: Color               # outline / separator
    text: Color               # normal text on a face
    dim: Color                # secondary text
    field: Color              # input / display background
    field_text: Color         # text inside a field
    title_active: Color
    title_text: Color
    accent: Color
    accent_dark: Color
    warn: Color
    bad: Color
    ok: Color

    title_height: int = 22
    border: int = 2
    rounded: int = 0
    mono: bool = False
    smooth: bool = False      # antialias text (FT2 look) or keep it chunky?

    # the window frame around the panels
    frame: Color = (0, 0, 0)
    frame_light: Color = (255, 255, 255)

    # the pattern page: this is the part people recognise
    pattern_note: Color = (255, 255, 255)
    pattern_inst: Color = (158, 211, 255)
    pattern_vol: Color = (158, 211, 255)
    pattern_empty: Color = (40, 70, 110)
    pattern_row: Color = (158, 211, 255)
    pattern_row_beat: Color = (255, 255, 255)
    pattern_group: Color = (16, 32, 52)      # the gap between channel groups
    pattern_head: Color = (150, 150, 182)    # the channel-number strip
    playing: Color = (73, 150, 235)
    playing_text: Color = (255, 255, 255)
    stripe: Color = (10, 20, 40)             # every fourth row
    cursor: Color = (73, 150, 235)

    def fonts(self):
        """Font family list, most authentic first, with a guaranteed fallback."""
        if self.mono:
            return ["Topaz", "DejaVu Sans Mono", "Liberation Mono", "Courier New"]
        return ["MS Sans Serif", "Tahoma", "Verdana", "DejaVu Sans", "Liberation Sans"]


# FastTracker II v2.04, sampled from the screenshot: blue frame, lavender buttons,
# black pattern pages, pale blue hex data.
TRACKER = Theme(
    key="tracker",
    name="FastTracker II",
    desktop=(40, 85, 134),
    face=(150, 150, 182),
    face_alt=(150, 150, 182),
    light=(231, 231, 255),
    shadow=(16, 32, 52),
    dark=(0, 0, 0),
    text=(0, 0, 0),
    dim=(52, 52, 65),
    field=(0, 0, 0),
    field_text=(158, 211, 255),
    title_active=(73, 150, 235),
    title_text=(255, 255, 255),
    accent=(158, 211, 255),
    accent_dark=(40, 85, 134),
    warn=(255, 220, 120),
    bad=(255, 120, 120),
    ok=(170, 240, 170),
    title_height=18,
    border=1,
    rounded=0,
    mono=True,
    smooth=True,
    frame=(73, 150, 235),
    frame_light=(231, 231, 255),
    pattern_note=(255, 255, 255),
    pattern_inst=(158, 211, 255),
    pattern_vol=(120, 175, 225),
    pattern_empty=(38, 62, 96),
    pattern_row=(158, 211, 255),
    pattern_row_beat=(255, 255, 255),
    pattern_group=(16, 32, 52),
    pattern_head=(150, 150, 182),
    playing=(73, 150, 235),
    playing_text=(255, 255, 255),
    stripe=(8, 18, 38),
    cursor=(73, 150, 235),
)

WIN95 = Theme(
    key="win95",
    name="Windows 95",
    desktop=(0, 128, 128),          # the classic teal desktop
    face=(192, 192, 192),
    face_alt=(192, 192, 192),
    light=(255, 255, 255),
    shadow=(128, 128, 128),
    dark=(0, 0, 0),
    text=(0, 0, 0),
    dim=(96, 96, 96),
    field=(255, 255, 255),
    field_text=(0, 0, 0),
    title_active=(0, 0, 128),
    title_text=(255, 255, 255),
    accent=(0, 0, 128),
    accent_dark=(160, 160, 160),
    warn=(128, 64, 0),
    bad=(160, 0, 0),
    ok=(0, 100, 0),
    title_height=22,
    border=2,
    rounded=0,
    frame=(0, 0, 0),
    pattern_note=(0, 0, 0),
    pattern_inst=(0, 0, 128),
    pattern_vol=(0, 0, 128),
    pattern_empty=(190, 190, 190),
    pattern_row=(0, 0, 128),
    pattern_row_beat=(0, 0, 0),
    pattern_group=(236, 236, 236),
    pattern_head=(192, 192, 192),
    playing=(0, 0, 128),
    playing_text=(255, 255, 255),
    stripe=(236, 236, 236),
    cursor=(0, 0, 128),
)

AMIGA = Theme(
    key="amiga",
    name="Amiga Workbench",
    desktop=(0, 85, 170),           # Workbench 1.x blue
    face=(160, 160, 160),
    face_alt=(170, 170, 170),
    light=(238, 238, 238),
    shadow=(85, 85, 85),
    dark=(0, 0, 0),
    text=(0, 0, 0),
    dim=(64, 64, 64),
    field=(0, 0, 0),                # the Workbench CLI black
    field_text=(255, 170, 0),       # the famous orange
    title_active=(255, 136, 0),
    title_text=(0, 0, 0),
    accent=(255, 136, 0),
    accent_dark=(200, 200, 200),
    warn=(160, 70, 0),
    bad=(190, 0, 0),
    ok=(0, 90, 0),
    title_height=24,
    border=3,
    rounded=0,
    mono=True,
    frame=(0, 0, 0),
    frame_light=(238, 238, 238),
    pattern_note=(255, 255, 255),
    pattern_inst=(255, 170, 0),
    pattern_vol=(230, 150, 0),
    pattern_empty=(90, 60, 20),
    pattern_row=(255, 170, 0),
    pattern_row_beat=(255, 255, 255),
    pattern_group=(40, 25, 0),
    pattern_head=(160, 160, 160),
    playing=(255, 136, 0),
    playing_text=(0, 0, 0),
    stripe=(20, 12, 0),
    cursor=(255, 136, 0),
)

THEMES = {"tracker": TRACKER, "win95": WIN95, "amiga": AMIGA}


def get(key: str) -> Theme:
    return THEMES.get(key, TRACKER)


def next_theme(key: str) -> Theme:
    order = ["tracker", "win95", "amiga"]
    index = order.index(key) if key in order else 0
    return THEMES[order[(index + 1) % len(order)]]


# --------------------------------------------------------------------- drawing
#
# FastTracker II did not do bevels, it did two-pixel offsets: a raised panel has a
# white line along its top and left and a black line along its bottom and right.
# Everything here follows that rule, so the three looks share the geometry.

def raised(surface, rect, theme: Theme, width: int = 2) -> None:
    w = max(1, min(width, rect.width // 2, rect.height // 2))
    for step in range(w):
        box = rect.inflate(-2 * step, -2 * step)
        if box.width <= 0 or box.height <= 0:
            break
        surface.fill(theme.light, (box.x, box.y, box.width, 1))
        surface.fill(theme.light, (box.x, box.y, 1, box.height))
        surface.fill(theme.shadow, (box.x, box.bottom - 1, box.width, 1))
        surface.fill(theme.shadow, (box.right - 1, box.y, 1, box.height))


def sunken(surface, rect, theme: Theme, width: int = 2) -> None:
    w = max(1, min(width, rect.width // 2, rect.height // 2))
    for step in range(w):
        box = rect.inflate(-2 * step, -2 * step)
        if box.width <= 0 or box.height <= 0:
            break
        surface.fill(theme.shadow, (box.x, box.y, box.width, 1))
        surface.fill(theme.shadow, (box.x, box.y, 1, box.height))
        surface.fill(theme.dark, (box.x, box.bottom - 1, box.width, 1))
        surface.fill(theme.dark, (box.right - 1, box.y, 1, box.height))


def outline(surface, rect, color, width: int = 1) -> None:
    for step in range(width):
        box = pygame.Rect(rect.x + step, rect.y + step,
                          rect.width - 2 * step, rect.height - 2 * step)
        if box.width <= 0 or box.height <= 0:
            return
        surface.fill(color, (box.x, box.y, box.width, 1))
        surface.fill(color, (box.x, box.bottom - 1, box.width, 1))
        surface.fill(color, (box.x, box.y, 1, box.height))
        surface.fill(color, (box.right - 1, box.y, 1, box.height))


def frame(surface, rect, theme: Theme) -> pygame.Rect:
    """The window frame: black outline, coloured frame, inside that the content."""
    surface.fill(theme.dark, rect)
    inner = rect.inflate(-2, -2)
    surface.fill(theme.frame, inner)
    inner = inner.inflate(-2, -2)
    surface.fill(theme.frame_light if theme.key == "win95" else theme.frame, inner)
    return inner.inflate(-2, -2)


def panel(surface, rect, theme: Theme, title: str = "", font=None,
          bar: bool = True) -> pygame.Rect:
    """A raised panel with an optional lavender title bar."""
    surface.fill(theme.face, rect)
    raised(surface, rect, theme, 2)
    if not title or font is None or not bar:
        return rect.inflate(-6, -6)
    height = max(16, font.get_height() + 3)
    bar_rect = pygame.Rect(rect.x + 2, rect.y + 2, rect.width - 4, height)
    surface.fill(theme.face_alt, bar_rect)
    raised(surface, bar_rect, theme, 1)
    label = font.render(title, theme.smooth, theme.text)
    surface.blit(label, (bar_rect.x + 4,
                         bar_rect.centery - label.get_height() // 2 + 1))
    return pygame.Rect(rect.x + 4, bar_rect.bottom + 3,
                       rect.width - 8, rect.bottom - bar_rect.bottom - 5)


def field(surface, rect, theme: Theme, color=None) -> None:
    """A sunken display well (the black pattern page, a numeric readout)."""
    surface.fill(color or theme.field, rect)
    sunken(surface, rect, theme, 1)
    outline(surface, rect.inflate(-1, -1), theme.dark, 1)


def button(surface, rect, theme: Theme, label: str, font,
           pressed: bool = False, enabled: bool = True,
           primary: bool = False) -> None:
    face = theme.face if enabled else theme.face_alt
    if primary and enabled:
        face = theme.accent if theme.key == "tracker" else theme.face
    surface.fill(face, rect)
    if pressed:
        sunken(surface, rect, theme, 2)
    else:
        raised(surface, rect, theme, 2)
    outline(surface, rect, theme.dark, 1)
    color = theme.text if enabled else theme.dim
    text = font.render(label, theme.smooth, color)
    if text.get_width() > rect.width - 8:
        label = label[:max(1, int(len(label) * (rect.width - 8) / max(1, text.get_width())))]
        text = font.render(label.rstrip(), theme.smooth, color)
    offset = 1 if pressed else 0
    surface.blit(text, (rect.centerx - text.get_width() // 2 + offset,
                        rect.centery - text.get_height() // 2 + 1 + offset))


def numeric(surface, rect, theme: Theme, text: str, font, colour=None) -> None:
    """A small black readout, like the FT2 tempo/length boxes."""
    surface.fill(theme.field, rect)
    sunken(surface, rect, theme, 1)
    outline(surface, rect, theme.dark, 1)
    label = font.render(text, theme.smooth, colour or theme.field_text)
    surface.blit(label, (rect.x + 3, rect.centery - label.get_height() // 2))


def arrow(surface, rect, theme: Theme, direction: str = "up",
          enabled: bool = True) -> None:
    """The little up/down buttons next to every number in FT2."""
    button(surface, rect, theme, "", pygame.font.Font(None, 10), enabled=enabled)
    colour = theme.text if enabled else theme.dim
    cx, cy = rect.center
    if direction == "up":
        points = [(cx, cy - 3), (cx - 3, cy + 2), (cx + 3, cy + 2)]
    elif direction == "down":
        points = [(cx, cy + 3), (cx - 3, cy - 2), (cx + 3, cy - 2)]
    elif direction == "left":
        points = [(cx - 3, cy), (cx + 2, cy - 3), (cx + 2, cy + 3)]
    else:
        points = [(cx + 3, cy), (cx - 2, cy - 3), (cx - 2, cy + 3)]
    pygame.draw.polygon(surface, colour, points)


def checkbox(surface, rect, theme: Theme, checked: bool) -> None:
    surface.fill(theme.field if checked else theme.face_alt, rect)
    sunken(surface, rect, theme, 1)
    outline(surface, rect, theme.dark, 1)
    if checked:
        inner = rect.inflate(-6, -6)
        surface.fill(theme.field_text, inner)


def scrollbar(surface, rect, theme: Theme, fraction: float,
              visible: float) -> None:
    """A chunky scrollbar, because a smooth one would look out of period."""
    field(surface, rect, theme, theme.face_alt)
    fraction = max(0.0, min(1.0, fraction))
    visible = max(0.0, min(1.0, visible))

    if rect.width > rect.height:
        size = min(rect.height - 2, 12) if rect.height >= 8 else 0
        track = pygame.Rect(rect.x + 1 + size, rect.y + 1,
                            rect.width - 2 - 2 * size, rect.height - 2)
        if size:
            for arrow_rect in (pygame.Rect(rect.x + 1, rect.y + 1, size, size),
                               pygame.Rect(rect.right - size - 1, rect.y + 1,
                                           size, size)):
                button(surface, arrow_rect, theme, "", pygame.font.Font(None, 10))
        if visible >= 1.0 or track.width <= 0:
            return
        thumb_width = max(14, int(track.width * visible))
        thumb = pygame.Rect(track.x + int((track.width - thumb_width) * fraction),
                            track.y, thumb_width, track.height)
        button(surface, thumb, theme, "", pygame.font.Font(None, 10))
        return

    size = min(rect.width - 2, max(8, rect.height // 4))
    top = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, size)
    bottom = pygame.Rect(rect.x + 1, rect.bottom - size - 1, rect.width - 2, size)
    for direction, up in ((top, True), (bottom, False)):
        button(surface, direction, theme, "", pygame.font.Font(None, 10))
        if up:
            points = [(direction.centerx, direction.y + 4),
                      (direction.x + 4, direction.bottom - 4),
                      (direction.right - 4, direction.bottom - 4)]
        else:
            points = [(direction.centerx, direction.bottom - 4),
                      (direction.x + 4, direction.y + 4),
                      (direction.right - 4, direction.y + 4)]
        pygame.draw.polygon(surface, theme.text, points)
    track = pygame.Rect(rect.x + 1, top.bottom + 1, rect.width - 2,
                        rect.height - 2 * (size + 1))
    if visible >= 1.0 or track.height <= 0:
        return
    thumb_height = max(14, int(track.height * visible))
    travel = track.height - thumb_height
    thumb_y = track.y + int(travel * fraction)
    thumb = pygame.Rect(track.x, thumb_y, track.width, thumb_height)
    button(surface, thumb, theme, "", pygame.font.Font(None, 10))
