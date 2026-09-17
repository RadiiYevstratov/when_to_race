"""Drawing the post.

The visual is a schedule card in ON TRACK's own palette, over the circuit
outline already traced for the site. That choice is the whole media strategy:
real motorsport photography is owned by Getty and the championships and cannot
be licensed automatically, and photorealistic generated imagery is detected by
Meta through C2PA and IPTC provenance, labelled "AI info", and subject to
mandatory disclosure. Neither is available to an unattended daily job.

Drawing our own costs nothing, cannot infringe anything, is identical every
time, and for a schedule account is more useful than a stock photograph of a
car: the schedule is the thing people came for.

Output is exactly what Instagram accepts - 1080x1350 JPEG in sRGB, comfortably
inside the 8MB ceiling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent / "assets"
FONT_DIR = ASSETS / "fonts"
CIRCUITS_TS = Path(__file__).resolve().parent.parent / "web" / "lib" / "circuits.ts"

# Instagram accepts 4:5 to 1.91:1 and no more than 1440px wide. 4:5 takes the
# most vertical space in the feed, which is the whole argument for it.
WIDTH, HEIGHT = 1080, 1350

# The site's Carbon palette, so a post and the page it links to look like one
# product. Duplicated here rather than imported because the web tokens are CSS
# and this is a Python job; the values are asserted against globals.css by test.
BOARD = (8, 9, 10)
PANEL = (18, 19, 23)
RULE = (36, 39, 45)
INK = (238, 240, 241)
INK_MUTED = (138, 146, 152)
INK_FAINT = (86, 93, 98)

MARGIN = 84


# --------------------------------------------------------------------------
# the traced outlines, read from the site's own source
# --------------------------------------------------------------------------

_ENTRY = re.compile(r'^  "?([a-z0-9_]+)"?:\s*\n((?:\s+"[^"]*"\s*\+?\s*\n)+)', re.M)
_CHUNK = re.compile(r'"([^"]*)"')
_SUBPATH = re.compile(r"M\s*(-?\d+)\s+(-?\d+)((?:\s*L\s*-?\d+\s+-?\d+)*)\s*Z?", re.I)
_POINT = re.compile(r"L\s*(-?\d+)\s+(-?\d+)", re.I)

# The paths are authored against this viewBox in circuits.ts.
VIEW_W, VIEW_H = 480, 260


def load_outlines(path: Path = CIRCUITS_TS) -> dict[str, list[list[tuple[int, int]]]]:
    """Every circuit outline, as lists of polygons.

    Parsed from the TypeScript the site renders rather than duplicated into a
    Python file: one traced path, one source of truth. They are plain
    move-line-close polygons - no curves - so parsing is honest rather than a
    partial SVG implementation pretending otherwise.
    """
    if not path.is_file():
        return {}

    source = path.read_text(encoding="utf-8")
    outlines: dict[str, list[list[tuple[int, int]]]] = {}

    for match in _ENTRY.finditer(source):
        slug = match.group(1)
        data = "".join(_CHUNK.findall(match.group(2)))
        polygons: list[list[tuple[int, int]]] = []
        for sub in _SUBPATH.finditer(data):
            points = [(int(sub.group(1)), int(sub.group(2)))]
            points.extend((int(x), int(y)) for x, y in _POINT.findall(sub.group(3)))
            if len(points) >= 3:
                polygons.append(points)
        if polygons:
            outlines[slug] = polygons
    return outlines


def _draw_outline(
    canvas: Image.Image,
    polygons: Sequence[Sequence[tuple[int, int]]],
    box: tuple[int, int, int, int],
    colour: tuple[int, int, int],
    opacity: int,
) -> None:
    """Paint one circuit into `box`, preserving its holes.

    The traced paths use even-odd fill: an outer ribbon plus a subpath for every
    enclosed area. Drawing them in order would fill the infields in solid, so
    each subpath is XORed into a mask instead, which is what even-odd means.
    """
    if not polygons:
        return

    left, top, right, bottom = box
    xs = [p[0] for poly in polygons for p in poly]
    ys = [p[1] for poly in polygons for p in poly]
    span_x = max(1, max(xs) - min(xs))
    span_y = max(1, max(ys) - min(ys))
    scale = min((right - left) / span_x, (bottom - top) / span_y)

    offset_x = left + ((right - left) - span_x * scale) / 2
    offset_y = top + ((bottom - top) - span_y * scale) / 2

    from PIL import ImageChops

    mask = Image.new("1", canvas.size, 0)
    for polygon in polygons:
        layer = Image.new("1", canvas.size, 0)
        ImageDraw.Draw(layer).polygon(
            [
                (offset_x + (x - min(xs)) * scale, offset_y + (y - min(ys)) * scale)
                for x, y in polygon
            ],
            fill=1,
        )
        mask = ImageChops.logical_xor(mask, layer)

    tint = Image.new("RGB", canvas.size, colour)
    canvas.paste(Image.blend(canvas, tint, opacity / 255), (0, 0), mask)


# --------------------------------------------------------------------------
# type
# --------------------------------------------------------------------------


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """The bundled face, or whatever the machine has.

    IBM Plex Mono ships with the repository so a GitHub runner draws the same
    card this machine does. The fallback exists so a missing font degrades the
    typography rather than failing the day's post.
    """
    candidate = FONT_DIR / name
    if candidate.is_file():
        return ImageFont.truetype(str(candidate), size)
    for fallback in ("DejaVuSansMono.ttf", "consola.ttf", "cour.ttf"):
        try:
            return ImageFont.truetype(fallback, size)
        except OSError:
            continue
    return ImageFont.load_default()


def regular(size: int) -> ImageFont.FreeTypeFont:
    return _font("IBMPlexMono-Regular.ttf", size)


def semibold(size: int) -> ImageFont.FreeTypeFont:
    return _font("IBMPlexMono-SemiBold.ttf", size)


def bold(size: int) -> ImageFont.FreeTypeFont:
    return _font("IBMPlexMono-Bold.ttf", size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit(draw: ImageDraw.ImageDraw, text: str, weight, start: int, max_width: int, min_size: int):
    """Largest size at which `text` fits on one line, down to a floor.

    Circuit and event names vary from "Spa" to "Autodromo Internazionale Enzo e
    Dino Ferrari"; a fixed size either wastes the card or runs off it.
    """
    size = start
    while size > min_size:
        font = weight(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return weight(min_size)


# --------------------------------------------------------------------------
# the card
# --------------------------------------------------------------------------


@dataclass
class CardContent:
    """Everything the drawing needs, already resolved to strings.

    Deliberately not the brief or a database row: rendering should not be able
    to reach for a field nobody checked, and a card is easy to test when its
    input is six strings.
    """

    kicker: str                 # THIS WEEKEND / TOMORROW / TODAY
    series: str                 # Formula 1
    title: str                  # Azerbaijan Grand Prix
    subtitle: Optional[str]     # Free Practice 1
    accent: tuple[int, int, int]

    # The labelled rows along the bottom, already decided and already worded:
    # (("date", "Friday 18 September"), ("start", "02:00 CEST"), ...). Which
    # rows a post gets is an editorial question - a race in the reader's own
    # timezone should not carry a second time row saying the same thing - and
    # it is answered in pipeline.py, not here.
    fields: tuple[tuple[str, str], ...] = ()

    venue_slug: Optional[str] = None
    lines: tuple[str, ...] = ()  # filled only when there is no circuit to draw
    lines_label: Optional[str] = None   # what the list above is a list of


def render(content: CardContent, outlines: Optional[dict] = None) -> Image.Image:
    """Draw the post."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BOARD)
    draw = ImageDraw.Draw(canvas)
    inner = WIDTH - 2 * MARGIN

    # --- the circuit, behind everything -----------------------------------
    #
    # Not every venue has a traced outline - the oval tracks mostly do not - and
    # a card with neither a drawing nor a list has a third of its height empty.
    # So it is one or the other, never both and never neither if there is
    # anything to say.
    outlines = load_outlines() if outlines is None else outlines
    polygons = outlines.get(content.venue_slug or "", [])
    if polygons:
        # Heavier than the site's nine percent: there the drawing sits behind
        # body text that has to stay readable, here it is the only thing in the
        # middle of the card and at that opacity it disappeared.
        _draw_outline(canvas, polygons, (MARGIN - 10, 440, WIDTH - MARGIN + 10, 880), INK, 62)

    # --- accent rule and kicker -------------------------------------------
    draw.rectangle([MARGIN, MARGIN, MARGIN + 88, MARGIN + 7], fill=content.accent)

    kicker_font = semibold(30)
    draw.text((MARGIN, MARGIN + 34), content.kicker.upper(), font=kicker_font, fill=INK_MUTED)

    series_font = semibold(30)
    series_text = content.series.upper()
    draw.text(
        (WIDTH - MARGIN - draw.textlength(series_text, font=series_font), MARGIN + 34),
        series_text,
        font=series_font,
        fill=content.accent,
    )

    # --- the headline ------------------------------------------------------
    y = MARGIN + 130
    title_font = _fit(draw, content.title, bold, 82, inner, 44)
    for line in _wrap(draw, content.title, title_font, inner)[:2]:
        draw.text((MARGIN, y), line, font=title_font, fill=INK)
        y += title_font.size + 12

    if content.subtitle:
        y += 14
        sub_font = _fit(draw, content.subtitle, semibold, 50, inner, 32)
        draw.text((MARGIN, y), content.subtitle, font=sub_font, fill=content.accent)
        y += sub_font.size + 10

    # --- the list, when there is no circuit drawing ------------------------
    if content.lines and not polygons:
        y = max(y + 56, 480)
        if content.lines_label:
            draw.text((MARGIN, y), content.lines_label.upper(), font=regular(23), fill=INK_FAINT)
            y += 46
        row_font = regular(38)
        for line in content.lines[:6]:
            fitted = row_font if draw.textlength(line, font=row_font) <= inner else _fit(
                draw, line, regular, 38, inner, 24
            )
            draw.text((MARGIN, y), line, font=fitted, fill=INK_MUTED)
            y += row_font.size + 26

    # --- the facts, along the bottom --------------------------------------
    #
    # The block is sized to the fields it actually has and then anchored above
    # the footer, rather than started at a fixed height and allowed to grow: the
    # first version ran "where" straight through "ontrackapp.me".
    fields = list(content.fields)

    ROW = 92
    FOOTER_SPACE = 92
    panel_top = HEIGHT - MARGIN - FOOTER_SPACE - len(fields) * ROW
    draw.line([(MARGIN, panel_top), (WIDTH - MARGIN, panel_top)], fill=RULE, width=2)

    label_font = regular(23)
    row = panel_top + 26
    for label, value in fields:
        draw.text((MARGIN, row), label.upper(), font=label_font, fill=INK_FAINT)
        fitted = _fit(draw, value, semibold, 44, inner, 26)
        draw.text((MARGIN, row + 30), value, font=fitted, fill=INK)
        row += ROW

    # --- the footer --------------------------------------------------------
    footer_font = regular(28)
    draw.text((MARGIN, HEIGHT - MARGIN - 34), "ontrackapp.me", font=footer_font, fill=INK_FAINT)

    mark = "ON TRACK"
    mark_font = bold(28)
    draw.text(
        (WIDTH - MARGIN - draw.textlength(mark, font=mark_font), HEIGHT - MARGIN - 34),
        mark,
        font=mark_font,
        fill=INK_MUTED,
    )
    return canvas


def to_jpeg(image: Image.Image, quality: int = 88) -> bytes:
    """JPEG bytes in sRGB, which is the only thing Instagram accepts."""
    import io

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True, subsampling=1)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# drawing one by hand
# --------------------------------------------------------------------------

SAMPLE = CardContent(
    kicker="Tomorrow",
    series="Formula 1",
    title="Azerbaijan Grand Prix",
    subtitle="F1 Qualifying",
    accent=(232, 17, 45),
    fields=(
        ("date", "Saturday 19 September"),
        ("start", "13:00 CEST"),
        ("at Baku", "15:00"),
        ("where", "Baku City Circuit, AZ"),
    ),
    venue_slug="baku",
)


def self_test() -> None:
    """Draw a card and check the things that silently degrade.

    Pillow falls back to a default bitmap font when a TrueType file is missing,
    and `load_outlines` returns an empty dict when circuits.ts moves or its
    format changes. Both produce a card - an ugly one, or one with no circuit
    behind it - so neither shows up as an error on the day it breaks. This is
    what makes them visible in CI instead.
    """
    missing = [
        name for name in ("IBMPlexMono-Regular.ttf", "IBMPlexMono-SemiBold.ttf",
                          "IBMPlexMono-Bold.ttf")
        if not (FONT_DIR / name).is_file()
    ]
    if missing:
        raise SystemExit(f"bundled fonts are missing: {', '.join(missing)}")

    outlines = load_outlines()
    if len(outlines) < 20:
        raise SystemExit(
            f"only {len(outlines)} circuit outlines parsed from {CIRCUITS_TS}; "
            "the format it is read from has probably changed"
        )

    data = to_jpeg(render(SAMPLE, outlines))
    image = Image.open(__import__("io").BytesIO(data))
    if image.size != (WIDTH, HEIGHT) or image.format != "JPEG":
        raise SystemExit(f"the card came out {image.size} {image.format}")

    print(f"{len(outlines)} outlines, {len(data) // 1024}KB {image.format} {image.size[0]}x{image.size[1]}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="python -m social.cards")
    parser.add_argument("--self-test", action="store_true", help="draw a sample and check it")
    parser.add_argument("--out", help="write the sample card to this path")
    args = parser.parse_args()

    if args.out:
        Path(args.out).write_bytes(to_jpeg(render(SAMPLE)))
        print(f"wrote {args.out}")
    else:
        self_test()
