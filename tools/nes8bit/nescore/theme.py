"""The look of the window: one dark tracker desk, in the spirit of FamiTracker.

There used to be three skins (FastTracker II's lavender, Windows 95's bevels and
an Amiga Workbench one) and a button to cycle them. That is three looks to keep
working, three sets of colours to keep legible, and a switch in the middle of a
conversion tool that nobody needs. There is one look now:

* near-black desk, panels only a shade lighter, and a single hairline between
  them instead of bevels — nothing looks raised, nothing looks pressed in;
* one accent colour (mint) for whatever is switched on, and the pattern area is
  the darkest thing on screen so the music is what the eye lands on;
* everything monospaced, because every number in this window is a hex value in a
  column and columns only line up in a mono face.

All the drawing here is flat: fills, one-pixel lines and text. That is also the
fast path — no gradients, no per-pixel work, and no font objects built inside a
draw call (building one costs ~0.1 ms, and the scrollbars alone used to build
several every frame).
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import pygame

Color = Tuple[int, int, int]


@dataclass
class Theme:
    key: str
    name: str

    desktop: Color            # behind everything
    face: Color               # button faces
    face_alt: Color           # panel title lines, list headers
    light: Color              # the one highlight colour used on lines
    shadow: Color
    dark: Color               # hairline borders and outlines
    text: Color
    dim: Color
    field: Color              # display wells (the pattern page, readouts)
    field_text: Color
    title_active: Color
    title_text: Color
    accent: Color
    accent_dark: Color
    warn: Color
    bad: Color
    ok: Color

    panel: Color = (22, 25, 31)
    hover: Color = (37, 43, 53)
    selection: Color = (33, 47, 60)
    desk: Color = (12, 14, 18)
    title_height: int = 20
    border: int = 1
    rounded: int = 0
    mono: bool = True
    smooth: bool = True       # antialias text; a modern dark desk needs it

    groove: Color = (38, 43, 52)      # the hairline that separates panels
    frame: Color = (38, 43, 52)
    frame_light: Color = (58, 65, 78)

    # the pattern page: this is the part people read for hours
    pattern_note: Color = (226, 232, 240)
    pattern_inst: Color = (118, 196, 188)
    pattern_vol: Color = (216, 178, 110)
    pattern_empty: Color = (62, 70, 84)
    pattern_row: Color = (108, 118, 132)
    pattern_row_beat: Color = (198, 207, 220)
    pattern_group: Color = (17, 20, 25)       # the gap between channel groups
    pattern_head: Color = (28, 32, 39)        # the channel-number strip
    playing: Color = (20, 42, 58)             # the row under the play cursor
    playing_text: Color = (150, 226, 250)
    stripe: Color = (15, 18, 23)              # every fourth row
    cursor: Color = (94, 214, 168)

    def fonts(self):
        """Font family list, mono first, with fallbacks that ship everywhere."""
        return ["Consolas", "DejaVu Sans Mono", "Liberation Mono", "Courier New",
                "Courier"]

    def heading_fonts(self):
        """The one place a proportional face is allowed: the title."""
        return ["Segoe UI Semibold", "Segoe UI", "Tahoma", "DejaVu Sans",
                "Liberation Sans"]


#: The one look. Kept as a dict so old call sites that iterate it still work.
DARK = Theme(
    key="dark",
    name="Dark",
    desktop=(12, 14, 18),
    desk=(12, 14, 18),
    panel=(22, 25, 31),
    face=(26, 30, 37),
    face_alt=(32, 37, 45),
    hover=(37, 43, 53),
    selection=(33, 47, 60),
    light=(52, 58, 70),
    shadow=(14, 16, 20),
    dark=(40, 45, 54),
    text=(208, 216, 228),
    dim=(120, 130, 145),
    field=(9, 11, 14),
    field_text=(205, 214, 226),
    title_active=(28, 32, 39),
    title_text=(208, 216, 228),
    accent=(94, 214, 168),
    accent_dark=(30, 74, 60),
    warn=(240, 186, 100),
    bad=(238, 122, 122),
    ok=(124, 214, 150),
    groove=(38, 43, 52),
    frame=(38, 43, 52),
    frame_light=(58, 65, 78),
    pattern_note=(226, 232, 240),
    pattern_inst=(118, 196, 188),
    pattern_vol=(216, 178, 110),
    pattern_empty=(62, 70, 84),
    pattern_row=(108, 118, 132),
    pattern_row_beat=(198, 207, 220),
    pattern_group=(17, 20, 25),
    pattern_head=(28, 32, 39),
    playing=(20, 42, 58),
    playing_text=(150, 226, 250),
    stripe=(15, 18, 23),
    cursor=(94, 214, 168),
    title_height=20,
    border=1,
    rounded=0,
    mono=True,
    smooth=True,
)

THEMES = {"dark": DARK}


def get(key: Optional[str] = None) -> Theme:
    """The theme.

    It takes an argument it ignores, and returns the one look: older builds saved
    a look name into the settings file, and the window still asks for it by name
    when it starts. Asking for "win95" now gets you the dark desk.
    """
    return DARK


# ------------------------------------------------------------------ primitives

def raised(surface, rect, theme: Theme, width: int = 2) -> None:
    """A flat panel edge: one hairline, brightest at the top.

    Bevels were what made the old paints look like 1995. A dark desk reads better
    with a single line, so the "raised" and "sunken" calls in the window now draw
    that and nothing else.
    """
    pygame.draw.rect(surface, theme.dark, rect, 1)
    surface.fill(theme.light, (rect.x + 1, rect.y + 1, max(0, rect.width - 2), 1))


def sunken(surface, rect, theme: Theme, width: int = 2) -> None:
    pygame.draw.rect(surface, theme.dark, rect, 1)


def frame(surface, rect, theme: Theme) -> pygame.Rect:
    """The window's own edge: the desk, with one line around the whole thing."""
    surface.fill(theme.desktop, rect)
    pygame.draw.rect(surface, theme.dark, rect.inflate(-1, -1), 1)
    return rect.inflate(-8, -8)


def panel(surface, rect, theme: Theme, title: str = "", font=None,
          bar: bool = True) -> pygame.Rect:
    """A flat panel with an optional title line across the top."""
    surface.fill(theme.panel, rect)
    pygame.draw.rect(surface, theme.dark, rect, 1)
    if not title or font is None or not bar:
        return rect.inflate(-6, -6)
    height = max(16, font.get_height() + 4)
    bar_rect = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, height)
    surface.fill(theme.face_alt, bar_rect)
    surface.fill(theme.dark, (bar_rect.x, bar_rect.bottom, bar_rect.width, 1))
    label = font.render(title.upper(), theme.smooth, theme.dim)
    surface.blit(label, (bar_rect.x + 7,
                         bar_rect.centery - label.get_height() // 2 + 1))
    return pygame.Rect(rect.x + 5, bar_rect.bottom + 4,
                       rect.width - 10, rect.bottom - bar_rect.bottom - 7)


def field(surface, rect, theme: Theme, color=None) -> None:
    """A display well: the pattern page, a readout, a list."""
    surface.fill(color or theme.field, rect)
    pygame.draw.rect(surface, theme.dark, rect, 1)


def button(surface, rect, theme: Theme, label: str, font,
           pressed: bool = False, enabled: bool = True,
           primary: bool = False, hover: bool = False) -> None:
    """A flat button. Primary ones are the accent; the rest are the desk."""
    if not enabled:
        face, edge, colour = theme.panel, theme.dark, theme.dim
    elif primary:
        face = theme.accent_dark if not pressed else theme.accent
        edge = theme.accent
        colour = theme.accent if not pressed else theme.field
    else:
        face = theme.hover if (pressed or hover) else theme.face
        edge = theme.light if (pressed or hover) else theme.dark
        colour = theme.text
    surface.fill(face, rect)
    pygame.draw.rect(surface, edge, rect, 1)
    if not label:
        return
    text = font.render(label, theme.smooth, colour)
    if text.get_width() > rect.width - 8:
        cut = label[:max(1, int(len(label) * (rect.width - 8) /
                                max(1, text.get_width())))]
        text = font.render(cut.rstrip(), theme.smooth, colour)
    offset = 1 if pressed else 0
    surface.blit(text, (rect.centerx - text.get_width() // 2 + offset,
                        rect.centery - text.get_height() // 2 + offset))


def numeric(surface, rect, theme: Theme, text: str, font, colour=None) -> None:
    """A readout box: dark well, hairline, left-aligned mono digits."""
    surface.fill(theme.field, rect)
    pygame.draw.rect(surface, theme.dark, rect, 1)
    label = font.render(text, theme.smooth, colour or theme.field_text)
    surface.blit(label, (rect.x + 7, rect.centery - label.get_height() // 2))


def arrow(surface, rect, theme: Theme, direction: str = "up",
          enabled: bool = True) -> None:
    """A small step arrow, drawn as a polygon: no font, no allocation."""
    surface.fill(theme.face if enabled else theme.panel, rect)
    pygame.draw.rect(surface, theme.dark, rect, 1)
    colour = theme.dim if enabled else theme.dark
    cx, cy = rect.center
    step = 3
    if direction == "up":
        points = [(cx, cy - step), (cx - step, cy + step - 1),
                  (cx + step, cy + step - 1)]
    elif direction == "down":
        points = [(cx, cy + step), (cx - step, cy - step + 1),
                  (cx + step, cy - step + 1)]
    elif direction == "left":
        points = [(cx - step, cy), (cx + step - 1, cy - step),
                  (cx + step - 1, cy + step)]
    else:
        points = [(cx + step, cy), (cx - step + 1, cy - step),
                  (cx - step + 1, cy + step)]
    pygame.draw.polygon(surface, colour, points)


def scrollbar(surface, rect, theme: Theme, fraction: float,
              visible: float) -> None:
    """A slim scrollbar: a track and a thumb, no arrow buttons.

    The old one built a font and two buttons for every scrollbar, every frame;
    this one is four rectangles and it looks like a tracker instead of a 1995
    dialog.
    """
    surface.fill(theme.field, rect)
    pygame.draw.rect(surface, theme.dark, rect, 1)
    fraction = max(0.0, min(1.0, fraction))
    visible = max(0.0, min(1.0, visible))
    if visible >= 1.0:
        return
    if rect.width > rect.height:
        track = pygame.Rect(rect.x + 2, rect.centery - 3, rect.width - 4, 6)
        thumb_width = max(18, int(track.width * visible))
        thumb = pygame.Rect(track.x + int((track.width - thumb_width) * fraction),
                            track.y, thumb_width, track.height)
    else:
        track = pygame.Rect(rect.centerx - 3, rect.y + 2, 6, rect.height - 4)
        thumb_height = max(18, int(track.height * visible))
        thumb = pygame.Rect(track.x,
                            track.y + int((track.height - thumb_height) * fraction),
                            track.width, thumb_height)
    surface.fill(theme.face_alt, track)
    surface.fill(theme.light, thumb)
