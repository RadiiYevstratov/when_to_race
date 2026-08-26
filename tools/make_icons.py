"""Generate the ON TRACK icon set.

Run from the repository root: `python tools/make_icons.py [sheet-dir]`. Pass a
directory to also write a contact sheet, which is how the mark gets judged at
the sizes it is actually seen at rather than at the size it was drawn.

The mark is a chequered block in the board palette with the final square in the
"live" green - a chequered flag is the one motorsport signifier that survives a
favicon, because it is already a grid of squares, and green is the product's own
vocabulary for "running now".

The grid coarsens as the icon shrinks. A four-by-four chequer at 16px is three
pixels a cell, which is high-frequency noise rather than a flag; below 24px the
mark drops to a two-by-two, which is the same idea drawn at a size that can hold
it. That is what a multi-resolution .ico is for: each entry is its own drawing,
not a downscale of one master.

Geometry lands on whole pixels at every size: with a margin of S/8 the block is
3S/4 across, so a cell is 3S/16 for the fine grid and 3S/8 for the coarse one.
Drawing directly at the target size keeps the edges hard.
"""
import sys

from PIL import Image, ImageDraw

BOARD = (8, 9, 10, 255)
INK = (238, 240, 241, 255)
RULE = (36, 39, 45, 255)
LIVE = (53, 209, 131, 255)


def render(size: int, inset: int = 8) -> Image.Image:
    """`inset` is the divisor for the margin: 8 for the normal mark, 4 for maskable."""
    img = Image.new("RGBA", (size, size), BOARD)
    d = ImageDraw.Draw(img)

    # A hairline edge so the tile still reads as a tile against dark browser
    # chrome, where the near-black ground has almost nothing to sit against.
    # Omitted on the small sizes, where one pixel of it costs a third of a cell.
    if size >= 32:
        d.rectangle([0, 0, size - 1, size - 1], outline=RULE, width=max(1, size // 64))

    n = 2 if size < 24 else 4
    margin = size // inset
    cell = (size - 2 * margin) // n
    for row in range(n):
        for col in range(n):
            if (row + col) % 2:
                continue
            # The bottom-right square is the live one, at either grid size.
            colour = LIVE if (row, col) == (n - 1, n - 1) else INK
            x0, y0 = margin + col * cell, margin + row * cell
            d.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], fill=colour)
    return img


def main() -> None:
    render(48).save("web/app/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    # A dedicated raster for search engines. Google asks for a square that is a
    # multiple of 48 and picks the icon itself; the .ico holds a 48 but which
    # entry of a multi-size file gets read is not something to leave to chance,
    # and a plain PNG is the format every crawler handles without argument.
    render(96).convert("RGB").save("web/app/icon.png")
    # iOS home screen: full bleed and opaque, because the system applies its own mask.
    render(180).convert("RGB").save("web/app/apple-icon.png")
    for s in (192, 512):
        render(s).save(f"web/public/icon-{s}.png")

    # Android crops a maskable icon to its own shape, and only a centred circle
    # of 80% diameter is guaranteed to survive. At the normal inset the block's
    # corners sit outside that circle, so the maskable copy is drawn smaller:
    # a half-width block puts its corners at 0.71 of the icon, safely inside.
    render(512, inset=4).save("web/public/icon-maskable-512.png")
    print("wrote favicon.ico, apple-icon.png, icon-192.png, icon-512.png, icon-maskable-512.png")

    if len(sys.argv) > 1:
        sheet = Image.new("RGB", (420, 130), (18, 19, 23))
        x = 24
        for s in (16, 32, 48, 64, 180):
            tile = render(s)
            sheet.paste(tile, (x, (130 - s) // 2), tile)
            x += s + 28
        sheet.resize((840, 260), Image.NEAREST).save(f"{sys.argv[1]}/icon-sheet.png")


main()
