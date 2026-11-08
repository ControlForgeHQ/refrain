"""Generate Refrain backgrounds from scratch.

Requires Python, NumPy and Pillow. Run with --help for output options.
The accepted masters were verified with NumPy 2.3.5 and Pillow 13.0.0.
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
W, H = SIZE = (3840, 2400)
X = np.arange(W, dtype=np.float32)[None, :]
Y = np.arange(H, dtype=np.float32)[:, None]

DESIGNS = {
    "aged-paper": ((242, 222, 185), "Warm stock with pressed grain", "Replacement"),
    "canvas": ((236, 230, 221), "Light canvas with raised yarns", "Replacement"),
    "cloth": ((228, 220, 210), "Soft linen with irregular threads", "Replacement"),
    "hex": ((241, 242, 238), "Graphite honeycomb ruling", "Replacement"),
    "handmade-paper": ((245, 241, 226), "Cotton rag with visible pulp fibres", "New"),
    "vellum": ((239, 232, 210), "Ivory vellum with a close stipple", "New"),
    "limestone": ((225, 225, 220), "Fine stone with mineral flecks", "New"),
    "drafting-grid": ((232, 239, 242), "Pale blue square ruling", "New"),
    "isometric-grid": ((239, 236, 243), "Triangular ruling on pale lilac", "New"),
    "recursive-squares": ((236, 241, 232), "Two scales of square outlines", "New"),
}


def field(rng, sx, sy=None):
    """Interpolated noise used for thread variation and fine material tooth."""
    sy = sx if sy is None else sy
    nx = max(1, round(W / sx))
    ny = max(1, round(H / sy))
    knots = rng.standard_normal((ny + 4, nx + 4), dtype=np.float32)
    return np.array(Image.fromarray(knots).resize(
        SIZE, Image.Resampling.BICUBIC, box=(2, 2, nx + 2, ny + 2)
    ))


def light(height, dx=1, dy=2):
    """Small directional slope across native pixels, with no cast shadows."""
    left = np.roll(height, dx, axis=1)
    upper = np.roll(height, dy, axis=0)
    left[:, :dx] = height[:, :dx]
    upper[:dy, :] = height[:dy, :]
    return .35 * (left - height) + .65 * (upper - height)


def marks(rng, count, lengths, widths, angles, tones, soft=0.0):
    """Render many short curved deposits without repeating a texture tile."""
    spans = rng.uniform(*lengths, count)
    directions = rng.uniform(*angles, count)
    xs = rng.uniform(-lengths[1], W + lengths[1], count)
    ys = rng.uniform(-lengths[1], H + lengths[1], count)
    dxs = spans * np.cos(directions)
    dys = spans * np.sin(directions)
    bends = rng.uniform(-.22, .22, count)
    values = rng.uniform(*tones, count)
    line_widths = rng.integers(widths[0], widths[1] + 1, count)
    image = Image.new("L", SIZE, 128)
    draw = ImageDraw.Draw(image)
    for x, y, dx, dy, bend, value, width in zip(xs, ys, dxs, dys, bends, values, line_widths):
        points = (
            (x, y),
            (x + dx * .23 - dy * bend * .7, y + dy * .23 + dx * bend * .7),
            (x + dx * .56 - dy * bend, y + dy * .56 + dx * bend),
            (x + dx * .83 - dy * bend * .43, y + dy * .83 + dx * bend * .43),
            (x + dx, y + dy),
        )
        for a, b, weight in zip(points, points[1:], (.48, 1, .93, .42)):
            draw.line((a, b), fill=round(128 + value * weight), width=int(width))
    if soft:
        image = image.filter(ImageFilter.GaussianBlur(soft))
    return np.asarray(image).astype(np.float32) - 128


def dots(rng, count, radius, tone, soft, shape=(1., 1.)):
    x = rng.uniform(-6, W + 6, count)
    y = rng.uniform(-6, H + 6, count)
    r = rng.uniform(*radius, count)
    dx = r * rng.uniform(.58, 1.25, count) * shape[0]
    dy = r * rng.uniform(.58, 1.25, count) * shape[1]
    v = rng.uniform(*tone, count)
    image = Image.new("L", SIZE, 128)
    draw = ImageDraw.Draw(image)
    for cx, cy, a, b, value in zip(x, y, dx, dy, v):
        draw.ellipse((cx - a, cy - b, cx + a, cy + b), fill=round(128 + value))
    return np.asarray(image.filter(ImageFilter.GaussianBlur(soft))).astype(np.float32) - 128


def paper_tooth(rng, amount=1.0):
    # Follow narrow, irregular ridges in a crushed pulp height field.
    noise = field(rng, 9, 7) + .38 * field(rng, 4, 4)
    relief = 1 - np.tanh(1.3 * np.abs(noise))
    return amount * (7.4 * light(relief, 2, 2) + 1.65 * (relief - .51) + 1.7 * field(rng, 3, 3))


def aged_paper(rng):
    # Keep the honey colour and irregular paper grain of the bundled reference.
    # A shallow warm transition near the edges survives the three crops.
    shortest = np.minimum(np.minimum(X, W - 1 - X), np.minimum(Y, H - 1 - Y))
    width = 273 + 34 * field(rng, 128, 128)
    edge = np.exp(-shortest / width)
    tooth = paper_tooth(rng, 1.57)
    compressed = field(rng, 17, 13)
    tooth += 2.7 * light(compressed, 3, 3) + 1.4 * compressed
    pulp = marks(rng, 45000, (5, 22), (2, 5), (-3.14, 3.14), (-8, 8), .7)
    specks = dots(rng, 21000, (.7, 2.3), (-10, 5), .65)
    toast = -8.2 * edge - .7 * field(rng, 30)
    tone = tooth + pulp + specks + toast
    return tone, .62 * toast + .28 * np.minimum(tooth + pulp, 0)


def yarn_coords(rng, pitch_x, pitch_y, irregularity):
    # Jitter the position of each yarn and allow a small drift along its path.
    nx = round(W / pitch_x) + 4
    ny = round(H / pitch_y) + 4
    xpos = np.cumsum(pitch_x * (1 + rng.uniform(-irregularity, irregularity, nx))) - 2 * pitch_x
    ypos = np.cumsum(pitch_y * (1 + rng.uniform(-irregularity, irregularity, ny))) - 2 * pitch_y
    warp = np.interp(X, xpos, np.arange(nx)).astype(np.float32) + .48 * irregularity * field(rng, 36, 83)
    weft = np.interp(Y, ypos, np.arange(ny)).astype(np.float32) + .48 * irregularity * field(rng, 76, 32)
    warp_center = np.floor(warp + .5)
    weft_center = np.floor(weft + .5)
    return warp - warp_center, weft - weft_center, warp_center + weft_center


def canvas(rng):
    u, v, crossings = yarn_coords(rng, 15.6, 15.1, .16)
    # Smooth rounded tops crest at alternate crossings in a plain weave.
    ww = np.exp(-9.6 * u**2)
    ff = np.exp(-10.6 * v**2)
    crest = np.cos(np.pi * crossings)
    warp = ww * (.91 + .45 * crest * np.cos(np.pi * v) + .10 * field(rng, 11, 57))
    weft = ff * (.92 - .46 * crest * np.cos(np.pi * u) + .10 * field(rng, 64, 11))
    top = np.maximum(warp, weft)
    yarn_fuzz = .95 * field(rng, 2.8, 3.1)
    tone = 15.4 * (top - .74) + 33 * light(top, 2, 2) + yarn_fuzz
    tone += marks(rng, 21000, (3, 16), (1, 3), (-.22, .22), (-9, 7), .65)
    tone += marks(rng, 17000, (3, 16), (1, 3), (1.35, 1.79), (-7, 8), .65)
    return tone, 0


def cloth(rng):
    u, v, crossings = yarn_coords(rng, 10.4, 12.9, .24)
    # Skinny, uneven strands and small slubs in a tighter fabric.
    slub_u = np.clip(1 + .22 * field(rng, 9, 41), .64, 1.45)
    slub_v = np.clip(1 + .23 * field(rng, 57, 10), .65, 1.48)
    warp = np.exp(-21.5 * (u / slub_u)**2)
    weft = np.exp(-19.5 * (v / slub_v)**2)
    alternation = np.cos(np.pi * crossings)
    warp *= (.81 + .16 * alternation + .18 * field(rng, 10, 37))
    weft *= (.72 - .16 * alternation + .16 * field(rng, 44, 10))
    top = warp + .86 * weft - .40 * warp * weft
    tone = 16.8 * (top - .58) + 24.5 * light(top, 2, 2)
    tone += 2.4 * field(rng, 4, 3) + 1.45 * field(rng, 3, 10)
    tone += marks(rng, 43000, (6, 36), (1, 3), (1.42, 1.72), (-13, 13), .60)
    tone += marks(rng, 38000, (5, 28), (1, 3), (-.14, .14), (-12, 11), .60)
    return tone, .1 * tone


def handmade(rng):
    pulp = marks(rng, 30200, (10, 47), (2, 5), (-3.14, 3.14), (-21, 14), .60)
    longer = marks(rng, 2900, (30, 82), (2, 4), (-3.14, 3.14), (-24, 12), .7)
    mottles = dots(rng, 24000, (.6, 3.2), (-14, 9), .7)
    tone = 1.05 * paper_tooth(rng) + pulp + longer + mottles
    return tone, .36 * np.minimum(pulp + longer, 0)


def vellum(rng):
    # Fine, rounded pores and embossed wrinkles across a smooth matte ground.
    pore = dots(rng, 112000, (1.4, 4.3), (-18, 12), 1.05)
    wrinkles = marks(rng, 42000, (7, 24), (2, 4), (-2.65, .32), (-8, 8), 1.25)
    touch = field(rng, 5.3, 4.1) + .28 * field(rng, 3, 2.7)
    ridges = np.tanh(1.55 * touch)
    tone = .79 * pore + 6.2 * light(ridges, 2, 2) + 1.3 * ridges + .65 * wrinkles
    return tone, .16 * pore


def limestone(rng):
    grain = dots(rng, 132000, (.9, 4.2), (-15, 14), .78)
    chips = dots(rng, 19000, (2.4, 7.0), (-26, 13), 1.1)
    fine = field(rng, 4, 3.7)
    tone = grain + chips + 1.8 * fine + 2.3 * light(fine, 1, 1)
    return tone, .22 * chips


def layers(rng, *specs):
    tone = np.zeros((H, W), dtype=np.float32)
    for amp, sx, sy in specs:
        tone += amp * field(rng, sx, sy)
    return tone


def honeycomb(rng):
    # Distance to the regular flat-top hexagonal Voronoi boundary.
    radius = 91.0
    h = radius * np.sqrt(3) / 2
    x = X + 38
    y = Y + 27
    xa = np.abs((x + 1.5 * radius) % (3 * radius) - 1.5 * radius)
    ya = np.abs((y + h) % (2 * h) - h)
    xb = np.abs(x % (3 * radius) - 1.5 * radius)
    yb = np.abs(y % (2 * h) - h)
    a = np.maximum(ya, np.sqrt(3) / 2 * xa + ya / 2)
    b = np.maximum(yb, np.sqrt(3) / 2 * xb + yb / 2)
    edge = np.clip(2.7 - (h - np.minimum(a, b)), 0, 1)
    tone = layers(rng, (.6, 340, 290), (.45, 9, 8), (.38, 2, 2))
    return tone - 12.5 * edge, -.9 * edge


def drafting(rng):
    spacing = 57
    dx = np.abs((X + 9 + spacing / 2) % spacing - spacing / 2)
    dy = np.abs((Y + 24 + spacing / 2) % spacing - spacing / 2)
    line = np.clip(1.9 - np.minimum(dx, dy), 0, 1)
    pitch = spacing * 5
    major_x = np.abs((X + 9 + pitch / 2) % pitch - pitch / 2)
    major_y = np.abs((Y + 24 + pitch / 2) % pitch - pitch / 2)
    major = np.clip(2.45 - np.minimum(major_x, major_y), 0, 1)
    rule = 7.2 * line + 4.2 * major
    tone = layers(rng, (.65, 370, 280), (.5, 7, 6), (.37, 2, 2))
    return tone - rule, .18 * rule


def centered_wrap(value, period):
    return (value + period / 2) % period - period / 2


def line_alpha(distance, width):
    return np.clip((width + 1) / 2 - np.abs(distance), 0, 1)


def isometric_grid():
    # The three line families have the same perpendicular spacing and
    # share vertices. Max coverage gives junctions the same ink as lines.
    side = 125
    spacing = side * np.sqrt(3) / 2
    x = (X + 17) * np.sqrt(3) / 2
    y = Y + 41
    alpha = line_alpha(centered_wrap(y, spacing), 3.8)
    for diagonal in (x - y / 2, x + y / 2):
        alpha = np.maximum(alpha, line_alpha(centered_wrap(diagonal, spacing), 3.8))
    return 11.3 * alpha


def recursive_squares():
    # Outline the center third of each tile and the center third of each
    # surviving neighbor. Leave the tile boundaries entirely unruled.
    pitch = 306.0
    step = pitch / 3
    x = centered_wrap(X + 67, pitch)
    y = centered_wrap(Y + 39, pitch)
    x_local = centered_wrap(x, step)
    y_local = centered_wrap(y, step)
    frame = np.maximum(np.abs(x), np.abs(y))
    inset = np.maximum(np.abs(x_local), np.abs(y_local))
    central = 12.3 * line_alpha(frame - step / 2, 4.2)
    details = 9.7 * line_alpha(inset - step / 6, 3.8)
    details[frame < step / 2] = 0
    return np.maximum(central, details)


# Fixed seeds keep each accepted design independent of generation order.
SURFACES = {
    "aged-paper": (302773, aged_paper, .48),
    "canvas": (302774, canvas, .48),
    "cloth": (302775, cloth, .48),
    "hex": (371904, honeycomb, .55),
    "handmade-paper": (302777, handmade, .48),
    "vellum": (302778, vellum, .48),
    "limestone": (302779, limestone, .48),
    "drafting-grid": (371908, drafting, .55),
}

RULES = {
    "isometric-grid": (612751, isometric_grid),
    "recursive-squares": (612752, recursive_squares),
}


def surface_pixels(base, seed, texture, grain_strength):
    rng = np.random.default_rng(seed)
    tone, chroma = texture(rng)
    tone += grain_strength * rng.standard_normal((H, W), dtype=np.float32)
    rgb = np.empty((H, W, 3), dtype=np.uint8)
    for channel, (color, tint) in enumerate(zip(base, (.46, .03, -.72))):
        rgb[:, :, channel] = np.rint(np.clip(color + tone + tint * chroma, 0, 255))
    return rgb


def ruled_pixels(base, seed, pattern):
    rng = np.random.default_rng(seed)
    rule = pattern()
    grain = .38 * rng.standard_normal((H, W), dtype=np.float32)
    channels = [
        np.rint(value + grain - weight * rule).astype(np.uint8)
        for value, weight in zip(base, (1.02, 1.0, .94))
    ]
    return np.stack(channels, axis=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backgrounds"),
        help="PNG destination (default: backgrounds/ in the current directory)",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, (base, _, _) in DESIGNS.items():
        if name in RULES:
            pixels = ruled_pixels(base, *RULES[name])
        else:
            pixels = surface_pixels(base, *SURFACES[name])
        path = args.output_dir / f"{name}.png"
        Image.fromarray(pixels).save(path, compress_level=7)
        print(f"{path.name}: {path.stat().st_size / 2**20:.2f} MiB", flush=True)


if __name__ == "__main__":
    main()
