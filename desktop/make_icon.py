"""Draw the app icon: a knight split in two, like a piece in superposition on the board.

    pip install pillow fonttools
    python -m desktop.make_icon

Writes desktop/icon.png (1024 px), desktop/icon.ico (Windows), desktop/icon.icns (macOS) and
ui/public/favicon.svg (the browser tab), all from one layout. The knight is the ♞ glyph of
DejaVu Sans (free license; matplotlib bundles it, and cirq installs matplotlib).
"""

from __future__ import annotations

from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SIZE = 1024
RADIUS = 0.22  # corner radius, as a fraction of the tile
TOP, BOTTOM = (0x7B, 0x5C, 0xFF), (0x45, 0x2A, 0xC4)  # the UI's accent, lit from above
GHOST_OPACITY = 0.4
KNIGHT_HEIGHT = 0.6  # of the tile
SPLIT = 0.17  # how far the two halves sit apart, as a fraction of the tile


def font_path() -> Path:
    import matplotlib

    return Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"


def knight_outline() -> tuple[str, tuple[float, float, float, float]]:
    """The ♞ outline as SVG path data in font units (y up), and its bounds."""
    font = TTFont(font_path())
    glyphs = font.getGlyphSet()
    name = font.getBestCmap()[ord("♞")]
    bounds = BoundsPen(glyphs)
    glyphs[name].draw(bounds)
    pen = SVGPathPen(glyphs)
    glyphs[name].draw(pen)
    return pen.getCommands(), bounds.bounds


def layout(bounds: tuple[float, float, float, float], size: float):
    """Scale and the two knights' offsets (ghost, solid) that place the glyph on the tile."""
    x0, y0, x1, y1 = bounds
    scale = KNIGHT_HEIGHT * size / (y1 - y0)
    width = (x1 - x0) * scale
    gap = SPLIT * size
    left = (size - width - gap) / 2  # centre the pair
    top = (size - (y1 - y0) * scale) / 2
    return scale, [(left - x0 * scale + dx, top + y1 * scale) for dx in (0, gap)]


def svg() -> str:
    path, bounds = knight_outline()
    scale, (ghost, solid) = layout(bounds, SIZE)
    r = RADIUS * SIZE

    def knight(at: tuple[float, float], opacity: str = "") -> str:
        return (
            f'<path transform="translate({at[0]:.1f} {at[1]:.1f}) scale({scale:.4f} {-scale:.4f})"'
            f' fill="#fff"{opacity} d="{path}"/>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#{bytes(TOP).hex()}"/>'
        f'<stop offset="1" stop-color="#{bytes(BOTTOM).hex()}"/>'
        "</linearGradient></defs>"
        f'<rect width="{SIZE}" height="{SIZE}" rx="{r:.0f}" fill="url(#g)"/>'
        + knight(ghost, f' fill-opacity="{GHOST_OPACITY}"')
        + knight(solid)
        + "</svg>\n"
    )


def png(size: int = SIZE, margin: float = 0.0) -> Image.Image:
    """The icon as an image; ``margin`` (a fraction per side) leaves room around the tile,
    as macOS icons expect."""
    supersample = 4
    big = size * supersample
    inner = round(big * (1 - 2 * margin))
    offset = round(big * margin)

    gradient = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        gradient.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    tile = gradient.resize((inner, inner), Image.BILINEAR).convert("RGBA")
    mask = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, inner - 1, inner - 1), radius=RADIUS * inner, fill=255
    )
    tile.putalpha(mask)

    knights = knight_masks(inner)
    for knight_mask, opacity in zip(knights, (GHOST_OPACITY, 1.0)):
        white = Image.new("RGBA", (inner, inner), (255, 255, 255, 0))
        white.putalpha(knight_mask.point(lambda v: round(v * opacity)))
        tile = Image.alpha_composite(tile, white)
    tile.putalpha(ImageChops.multiply(tile.getchannel("A"), mask))

    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    canvas.paste(tile, (offset, offset))
    return canvas.resize((size, size), Image.LANCZOS)


def knight_masks(size: int) -> list[Image.Image]:
    """Coverage masks of the ghost and solid knights, filled with the glyph's own winding."""
    from fontTools.pens.recordingPen import RecordingPen

    font = TTFont(font_path())
    glyphs = font.getGlyphSet()
    name = font.getBestCmap()[ord("♞")]
    bounds = BoundsPen(glyphs)
    glyphs[name].draw(bounds)
    scale, offsets = layout(bounds.bounds, size)

    masks = []
    for dx, dy in offsets:
        recording = RecordingPen()
        glyphs[name].draw(TransformPen(recording, (scale, 0, 0, -scale, dx, dy)))
        masks.append(fill_contours(contours(recording.value), size))
    return masks


def contours(commands: list) -> list[list[tuple[float, float]]]:
    """Flatten pen commands (lines and quadratic curves) into closed polygons."""
    polygons: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for op, args in commands:
        if op == "moveTo":
            current = [args[0]]
        elif op == "lineTo":
            current.append(args[0])
        elif op == "qCurveTo":
            current.extend(flatten_qcurve(current[-1], args))
        elif op == "curveTo":
            current.extend(flatten_cubic(current[-1], *args))
        elif op in ("closePath", "endPath"):
            polygons.append(current)
            current = []
    return polygons


def flatten_qcurve(start, points, steps: int = 16):
    """A TrueType quadratic spline (implied on-curve points between off-curve ones)."""
    *offs, end = points
    if not offs:
        return [end]
    ons = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(offs, offs[1:])] + [end]
    out, p0 = [], start
    for c, p2 in zip(offs, ons):
        for i in range(1, steps + 1):
            t = i / steps
            out.append(
                (
                    (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p2[0],
                    (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p2[1],
                )
            )
        p0 = p2
    return out


def flatten_cubic(p0, c1, c2, p3, steps: int = 16):
    return [
        tuple(
            (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t**3 * d
            for a, b, c, d in zip(p0, c1, c2, p3)
        )
        for t in (i / steps for i in range(1, steps + 1))
    ]


def fill_contours(polygons, size: int) -> Image.Image:
    """Even-odd fill: each contour toggles coverage, so the glyph's holes stay open."""
    mask = Image.new("1", (size, size), 0)
    for polygon in polygons:
        layer = Image.new("1", (size, size), 0)
        ImageDraw.Draw(layer).polygon(polygon, fill=1)
        mask = ImageChops.logical_xor(mask, layer)
    return mask.convert("L")


def main() -> None:
    (ROOT / "ui" / "public").mkdir(exist_ok=True)
    (ROOT / "ui" / "public" / "favicon.svg").write_text(svg(), encoding="utf-8")

    full = png()
    full.save(ROOT / "desktop" / "icon.png")
    # Windows picks the closest size; render the small ones directly rather than shrinking.
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [png(s) for s in ico_sizes]
    images[-1].save(
        ROOT / "desktop" / "icon.ico", sizes=[(s, s) for s in ico_sizes], append_images=images
    )
    # macOS draws icons on a grid with about 10% clear space around the tile.
    png(SIZE, margin=0.1).save(ROOT / "desktop" / "icon.icns")
    print("wrote desktop/icon.png, icon.ico, icon.icns and ui/public/favicon.svg")


if __name__ == "__main__":
    main()
