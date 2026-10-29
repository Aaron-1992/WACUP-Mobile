"""Two period-correct looks: Windows 95 and Amiga Workbench.

No images, no fonts to ship — just the palettes and the bevel drawing that made
those interfaces recognisable: a 2-pixel raised edge, a 1-pixel sunken field, a
navy title bar with square corners, and text that is never anti-aliased.
"""

from dataclasses import dataclass
from typing import Tuple

import pygame

Color = Tuple[int, int, int]


@dataclass
class Theme:
    key: str
    name: str
    desktop: Color          # the area behind the panels
    face: Color             # window / panel face
    face_alt: Color         # list rows, fields that are slightly lighter
    light: Color            # bevel highlight
    shadow: Color           # bevel shadow
    dark: Color             # outer black line
    text: Color
    dim: Color
    field: Color            # sunken input background
    field_text: Color
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

    def fonts(self):
        """Font family list, most authentic first, with a guaranteed fallback."""
        if self.mono:
            return ["Topaz", "DejaVu Sans Mono", "Liberation Mono", "Courier New"]
        return ["MS Sans Serif", "Tahoma", "Verdana", "DejaVu Sans", "Liberation Sans"]


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
    field=(255, 170, 0),            # the famous orange
    field_text=(0, 0, 0),
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
)

THEMES = {"win95": WIN95, "amiga": AMIGA}


def get(key: str) -> Theme:
    return THEMES.get(key, WIN95)


def next_theme(key: str) -> Theme:
    order = ["win95", "amiga"]
    index = order.index(key) if key in order else 0
    return THEMES[order[(index + 1) % len(order)]]


# ------------------------------------------------------------------- drawing

def fill(surface, rect, color) -> None:
    if rect.width > 0 and rect.height > 0:
        surface.fill(color, rect)


def bevel(surface, rect: pygame.Rect, theme: Theme, raised: bool = True,
          width: int = 0) -> None:
    """The 1995 edge: light on the top-left, shadow on the bottom-right."""
    width = width or theme.border
    fill(surface, rect, theme.face)
    for step in range(width):
        top_left, bottom_right = (theme.light, theme.shadow) if raised else \
            (theme.shadow, theme.light)
        pygame.draw.line(surface, top_left, (rect.x + step, rect.y + step),
                         (rect.right - 1 - step, rect.y + step))
        pygame.draw.line(surface, top_left, (rect.x + step, rect.y + step),
                         (rect.x + step, rect.bottom - 1 - step))
        pygame.draw.line(surface, bottom_right, (rect.x + step, rect.bottom - 1 - step),
                         (rect.right - 1 - step, rect.bottom - 1 - step))
        pygame.draw.line(surface, bottom_right, (rect.right - 1 - step, rect.y + step),
                         (rect.right - 1 - step, rect.bottom - 1 - step))
    pygame.draw.rect(surface, theme.dark, rect, width=1)


def field(surface, rect: pygame.Rect, theme: Theme, background=None) -> None:
    """A sunken area: text boxes, list boxes, progress wells."""
    fill(surface, rect, background or theme.field)
    pygame.draw.line(surface, theme.shadow, (rect.x, rect.y),
                     (rect.right - 1, rect.y), 2)
    pygame.draw.line(surface, theme.shadow, (rect.x, rect.y),
                     (rect.x, rect.bottom - 1), 2)
    pygame.draw.line(surface, theme.light, (rect.x, rect.bottom - 1),
                     (rect.right - 1, rect.bottom - 1), 2)
    pygame.draw.line(surface, theme.light, (rect.right - 1, rect.y),
                     (rect.right - 1, rect.bottom - 1), 2)
    pygame.draw.rect(surface, theme.dark, rect, width=1)


def button(surface, rect: pygame.Rect, theme: Theme, label: str,
           font: pygame.font.Font, pressed: bool = False, enabled: bool = True,
           primary: bool = False) -> None:
    face = theme.face if enabled else theme.face
    fill(surface, rect, face)
    if primary and enabled:
        # the 1995 "default button": one extra black ring around the bevel
        pygame.draw.rect(surface, theme.dark, rect.inflate(4, 4), 1)
    bevel(surface, rect, theme, raised=not pressed)
    color = theme.text if enabled else theme.dim
    text = font.render(label, True, color)
    offset = 1 if pressed else 0
    surface.blit(text, text.get_rect(center=(rect.centerx + offset,
                                             rect.centery + offset)))


def checkbox(surface, rect: pygame.Rect, theme: Theme, label: str,
             font: pygame.font.Font, checked: bool) -> None:
    box = pygame.Rect(rect.x, rect.centery - 8, 16, 16)
    field(surface, box, theme, theme.field if checked else theme.face)
    if checked:
        # the tick is drawn by hand: a font glyph would look wrong in 1995
        pygame.draw.lines(surface, theme.text, False,
                          [(box.x + 4, box.centery + 1), (box.x + 7, box.centery + 4),
                           (box.x + 12, box.centery - 4)], 2)
    surface.blit(font.render(label, True, theme.text), (rect.x + 24, rect.centery - 8))


def window(surface, rect: pygame.Rect, theme: Theme, title: str,
           font: pygame.font.Font) -> pygame.Rect:
    """A panel with a title bar, and returns the client area beneath it."""
    bevel(surface, rect, theme, raised=True)
    bar = pygame.Rect(rect.x + 2, rect.y + 2, rect.width - 4, theme.title_height)
    fill(surface, bar, theme.title_active)
    surface.blit(font.render(title, True, theme.title_text),
                 (bar.x + 6, bar.y + (bar.height - font.get_height()) // 2))
    # the little window buttons every one of these systems had
    size = theme.title_height - 8
    x = bar.right - 4 - size
    for _ in range(2):
        button_rect = pygame.Rect(x, bar.y + 4, size, size)
        fill(surface, button_rect, theme.face)
        bevel(surface, button_rect, theme, raised=True, width=2)
        pygame.draw.line(surface, theme.text, (button_rect.x + 4, button_rect.centery),
                         (button_rect.right - 5, button_rect.centery), 2)
        x -= size + 3
    return pygame.Rect(rect.x + 4, bar.bottom + 4, rect.width - 8,
                       rect.bottom - bar.bottom - 8)


def scrollbar(surface, rect: pygame.Rect, theme: Theme, fraction: float,
              visible: float) -> None:
    """A chunky scrollbar, because a smooth one would look out of period."""
    field(surface, rect, theme, theme.face_alt)
    arrow = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, rect.width - 2)
    for direction in (arrow, pygame.Rect(rect.x + 1, rect.bottom - rect.width + 1,
                                         rect.width - 2, rect.width - 2)):
        button(surface, direction, theme, "", pygame.font.Font(None, 10))
        points = ([(direction.centerx, direction.y + 4),
                   (direction.x + 4, direction.bottom - 4),
                   (direction.right - 4, direction.bottom - 4)]
                  if direction.y == arrow.y else
                  [(direction.centerx, direction.bottom - 4),
                   (direction.x + 4, direction.y + 4),
                   (direction.right - 4, direction.y + 4)])
        pygame.draw.polygon(surface, theme.text, points)
    track = pygame.Rect(rect.x + 1, arrow.bottom + 1, rect.width - 2,
                        rect.height - 2 * (arrow.height + 1))
    if visible >= 1.0 or track.height <= 0:
        return
    thumb_height = max(14, int(track.height * visible))
    travel = track.height - thumb_height
    thumb_y = track.y + int(travel * max(0.0, min(1.0, fraction)))
    thumb = pygame.Rect(track.x, thumb_y, track.width, thumb_height)
    button(surface, thumb, theme, "", pygame.font.Font(None, 10))
