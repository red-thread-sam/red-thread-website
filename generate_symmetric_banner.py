#!/usr/bin/env python3
"""Generate a supersampled bilateral LinkedIn banner with an inner hairline stroke."""

from __future__ import annotations

import math
import random
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# Working canvas is 2x LinkedIn (1584×396).
CANVAS_W, CANVAS_H = 3168, 792
OUTPUT_W, OUTPUT_H = 1584, 396
GAP = 32
BLEED = 48
STEP = 8
CORNER_RADIUS = 48
HAIRLINE_PX = 2
HAIRLINE_RGBA = (245, 245, 247, 40)  # #f5f5f7 @ 15%
VERTICAL_OFFSET = 80  # 2x scale: 40px up at 1x
LINE_BOX_GAP = 40  # scaled with the half-size type; still clears i-dot vs p
TEXT_PAD = 40
FONT_SIZE = 80
KEEP_OUT = 280  # extra black field around the smaller headline
LINE1 = "Creator-powered"
LINE2 = "Commercial impact."

CREATOR_DIR = Path("./creator-images")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
FONT_FILENAME = "Inter-SemiBold.ttf"
FONT_URLS = [
    "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
    "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
]
OUTPUT_PATH = Path("linkedin-banner-symmetric.png")

# Sizes at 2x; 16:9 / 9:16 / 1:1 from original orientation.
SIZES = {
    "wide": [(288, 162), (256, 144), (224, 126), (192, 108), (160, 90)],
    "portrait": [(162, 288), (144, 256), (126, 224), (108, 192), (90, 160)],
    "square": [(192, 192), (160, 160), (144, 144), (128, 128), (112, 112)],
}


def _download(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; generate-symmetric-banner/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def ensure_inter_semibold(dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"Using existing font: {dest}")
        return dest
    for sibling_name in ("Inter-Black.ttf", "Inter-Regular.ttf"):
        sibling = dest.with_name(sibling_name)
        if sibling.exists() and sibling.stat().st_size > 0:
            dest.write_bytes(sibling.read_bytes())
            print(f"Copied variable Inter from {sibling.name} → {dest.name}")
            return dest
    last_error: Exception | None = None
    for url in FONT_URLS:
        print(f"Downloading {FONT_FILENAME} from {url}")
        try:
            data = _download(url)
            if len(data) < 10_000:
                raise RuntimeError(f"too small ({len(data)} bytes)")
            dest.write_bytes(data)
            return dest
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"  failed: {exc}")
    raise RuntimeError(f"Could not download {FONT_FILENAME}") from last_error


def load_semibold_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(font_path), size)
    try:
        axes = font.get_variation_axes()
    except OSError:
        return font
    values = []
    for axis in axes:
        tag = axis.get("tag") or axis.get("name")
        tag_str = tag.decode("ascii", "ignore") if isinstance(tag, bytes) else str(tag)
        lowered = tag_str.lower()
        if "wght" in lowered or "weight" in lowered:
            values.append(600.0)
        elif "opsz" in lowered or "optical" in lowered:
            values.append(float(axis["maximum"]))
        else:
            values.append(float(axis["default"]))
    if values:
        font.set_variation_by_axes(values)
    return font


def classify(img: Image.Image) -> str:
    w, h = img.size
    if w > h * 1.15:
        return "wide"
    if h > w * 1.15:
        return "portrait"
    return "square"


def load_all_images(directory: Path) -> list[tuple[Image.Image, str, str]]:
    paths = sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not paths:
        raise FileNotFoundError(f"No images in {directory.resolve()}")
    random.shuffle(paths)
    loaded = []
    for path in paths:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            rgb = ImageEnhance.Color(rgb).enhance(1.05)
            rgb = ImageEnhance.Contrast(rgb).enhance(1.04)
            kind = classify(rgb)
            loaded.append((rgb, kind, path.name))
        print(f"Loaded {path.name} ({kind})")
    return loaded


def crop_to_aspect(img: Image.Image, aspect: float) -> Image.Image:
    w, h = img.size
    current = w / h
    if current > aspect:
        new_w = max(1, int(round(h * aspect)))
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    new_h = max(1, int(round(w / aspect)))
    top = (h - new_h) // 2
    return img.crop((0, top, w, top + new_h))


def make_radial_gradient(width: int, height: int) -> Image.Image:
    sw, sh = max(1, width // 4), max(1, height // 4)
    small = Image.new("RGB", (sw, sh))
    px = small.load()
    cx, cy = (sw - 1) / 2, (sh - 1) / 2
    max_d = math.hypot(cx, cy) or 1.0
    for y in range(sh):
        for x in range(sw):
            t = min(1.0, math.hypot(x - cx, y - cy) / max_d)
            t = t * t * (3 - 2 * t)
            v = int(round(10 * (1 - t)))  # 10 == 0x0a
            px[x, y] = (v, v, v)
    return small.resize((width, height), Image.Resampling.BICUBIC)


def rounded_mask(size: tuple[int, int], radius: int, inset: int = 0) -> Image.Image:
    """Anti-aliased rounded-rect mask. `inset` shrinks the rect and radius together."""
    w, h = size
    mask = Image.new("L", (w, h), 0)
    # Draw at 2x then downsample so the 48px corners stay smooth.
    scale = 2
    big = Image.new("L", (w * scale, h * scale), 0)
    r = max(radius - inset, 0) * scale
    box = [
        inset * scale,
        inset * scale,
        w * scale - inset * scale - 1,
        h * scale - inset * scale - 1,
    ]
    ImageDraw.Draw(big).rounded_rectangle(box, radius=r, fill=255)
    return big.resize((w, h), Image.Resampling.LANCZOS)


def inner_hairline_ring(size: tuple[int, int], radius: int, width: int) -> Image.Image:
    """Stroke locked to the inner edge of the card mask — never outside it."""
    outer = rounded_mask(size, radius, inset=0)
    inner = rounded_mask(size, radius, inset=width)
    ring = ImageChops.subtract(outer, inner)
    return ImageChops.multiply(ring, outer)


def rounded_card(img: Image.Image, radius: int) -> Image.Image:
    """Photo clipped to a rounded rect, with an edge-locked inner hairline."""
    w, h = img.size
    card = img.convert("RGBA")
    outer = rounded_mask((w, h), radius)
    card.putalpha(outer)

    ring = inner_hairline_ring((w, h), radius, HAIRLINE_PX)
    hairline = Image.new("RGBA", (w, h), (*HAIRLINE_RGBA[:3], 0))
    # Scale the ring (0–255) into the requested 40/255 opacity.
    hairline.putalpha(ring.point(lambda a: a * HAIRLINE_RGBA[3] // 255))
    card = Image.alpha_composite(card, hairline)

    # Re-clip so no hairline pixel can live outside the photo mask.
    r, g, b, a = card.split()
    a = ImageChops.multiply(a, outer)
    return Image.merge("RGBA", (r, g, b, a))


def with_drop_shadow(card: Image.Image) -> tuple[Image.Image, int, int]:
    blur, offset, opacity, pad = 24, (0, 12), 110, 48
    cw, ch = card.size
    canvas = Image.new(
        "RGBA",
        (cw + pad * 2 + abs(offset[0]), ch + pad * 2 + abs(offset[1])),
        (0, 0, 0, 0),
    )
    alpha = card.getchannel("A")
    shade = Image.new("RGBA", card.size, (0, 0, 0, 0))
    shade.putalpha(alpha.point(lambda a: int(a * opacity / 255)))
    canvas.paste(shade, (pad + offset[0], pad + offset[1]), shade)
    canvas = canvas.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(card, (pad, pad))
    return canvas, pad, pad


def paste_layer(base: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    bw, bh = base.size
    lw, lh = layer.size
    src_x = 0 if x >= 0 else -x
    src_y = 0 if y >= 0 else -y
    dst_x = max(x, 0)
    dst_y = max(y, 0)
    if dst_x >= bw or dst_y >= bh or src_x >= lw or src_y >= lh:
        return
    crop_w = min(lw - src_x, bw - dst_x)
    crop_h = min(lh - src_y, bh - dst_y)
    if crop_w <= 0 or crop_h <= 0:
        return
    piece = layer.crop((src_x, src_y, src_x + crop_w, src_y + crop_h))
    dest = Image.alpha_composite(
        base.crop((dst_x, dst_y, dst_x + crop_w, dst_y + crop_h)),
        piece,
    )
    base.paste(dest, (dst_x, dst_y))


def clip_visible(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int] | None:
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(CANVAS_W, x + w), min(CANVAS_H, y + h)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def rects_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def inflate(rect: tuple[int, int, int, int], pad: int) -> tuple[int, int, int, int]:
    return (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)


class Packer:
    def __init__(self, text_box: tuple[int, int, int, int]):
        self.text_box = text_box
        self.placed: list[tuple[int, int, int, int]] = []

    def fits(self, x: int, y: int, w: int, h: int) -> bool:
        if clip_visible(x, y, w, h) is None:
            return False
        card = (x, y, x + w, y + h)
        if rects_overlap(card, self.text_box):
            return False
        padded = inflate(card, GAP)
        return not any(rects_overlap(padded, other) for other in self.placed)

    def place(self, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        rect = (x, y, x + w, y + h)
        self.placed.append(rect)
        return rect

    def try_left(self, w: int, h: int) -> tuple[int, int, int, int] | None:
        max_x = self.text_box[0] - GAP - w
        x = -BLEED
        while x <= max_x:
            y = -BLEED
            while y <= CANVAS_H + BLEED - h:
                if self.fits(x, y, w, h):
                    return self.place(x, y, w, h)
                y += STEP
            x += STEP
        return None

    def try_right(self, w: int, h: int) -> tuple[int, int, int, int] | None:
        min_x = self.text_box[2] + GAP
        x = CANVAS_W - w + BLEED
        while x >= min_x:
            y = -BLEED
            while y <= CANVAS_H + BLEED - h:
                if self.fits(x, y, w, h):
                    return self.place(x, y, w, h)
                y += STEP
            x -= STEP
        return None


def measure_line(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def layout_headline(font_path: Path) -> tuple[ImageFont.FreeTypeFont, int, int, int, tuple[int, int, int, int]]:
    """Return font plus line-1/line-2 center points and the padded exclusion box."""
    probe = ImageDraw.Draw(Image.new("L", (CANVAS_W, CANVAS_H)))
    font = load_semibold_font(font_path, FONT_SIZE)
    w1, h1 = measure_line(probe, LINE1, font)
    w2, h2 = measure_line(probe, LINE2, font)

    cx = CANVAS_W // 2
    cy = CANVAS_H // 2 - VERTICAL_OFFSET
    block_h = h1 + LINE_BOX_GAP + h2
    top = cy - block_h // 2
    y1 = top + h1 // 2
    y2 = top + h1 + LINE_BOX_GAP + h2 // 2

    b1 = probe.textbbox((cx, y1), LINE1, font=font, anchor="mm")
    b2 = probe.textbbox((cx, y2), LINE2, font=font, anchor="mm")
    text_box = inflate(
        (
            min(b1[0], b2[0]) - TEXT_PAD,
            min(b1[1], b2[1]) - TEXT_PAD,
            max(b1[2], b2[2]) + TEXT_PAD,
            max(b1[3], b2[3]) + TEXT_PAD,
        ),
        KEEP_OUT,
    )
    print(f"Headline {FONT_SIZE}pt  leading-gap={LINE_BOX_GAP}px  box={text_box}")
    return font, cx, y1, y2, text_box


def pack_flank(
    packer: Packer,
    items: list[tuple[Image.Image, str, str]],
    side: str,
) -> list[tuple[Image.Image, int, int, int, int]]:
    laid: list[tuple[Image.Image, int, int, int, int]] = []
    remaining = list(items)
    remaining.sort(key=lambda t: 0 if t[1] == "portrait" else 1)

    def consume() -> None:
        still = []
        for img, kind, name in remaining:
            placed = None
            for w, h in SIZES[kind]:
                placed = packer.try_left(w, h) if side == "left" else packer.try_right(w, h)
                if placed:
                    x1, y1, x2, y2 = placed
                    laid.append((img, x1, y1, x2 - x1, y2 - y1))
                    print(f"  {side:5} {kind:8} {x2 - x1}×{y2 - y1} at ({x1},{y1})  {name}")
                    break
            if not placed:
                still.append((img, kind, name))
        remaining[:] = still

    consume()
    if remaining:
        names = ", ".join(n for _, _, n in remaining)
        print(f"WARNING: {side} could not place {len(remaining)}: {names}")
    return laid


def main() -> None:
    random.seed()
    root = Path(__file__).resolve().parent
    font_path = root / FONT_FILENAME
    output_path = root / OUTPUT_PATH

    ensure_inter_semibold(font_path)
    font, cx, y1, y2, text_box = layout_headline(font_path)

    items = load_all_images((root / CREATOR_DIR).resolve())
    left_items = items[::2]
    right_items = items[1::2]
    print(f"Flanks: {len(left_items)} left, {len(right_items)} right")

    packer = Packer(text_box)
    layout = pack_flank(packer, left_items, "left")
    layout += pack_flank(packer, right_items, "right")

    canvas = make_radial_gradient(CANVAS_W, CANVAS_H).convert("RGBA")
    for img, x, y, w, h in layout:
        card = rounded_card(
            crop_to_aspect(img, w / h).resize((w, h), Image.Resampling.LANCZOS),
            CORNER_RADIUS,
        )
        shadowed, pad_x, pad_y = with_drop_shadow(card)
        paste_layer(canvas, shadowed, x - pad_x, y - pad_y)

    draw = ImageDraw.Draw(canvas)
    draw.text((cx, y1), LINE1, font=font, fill=(255, 255, 255, 255), anchor="mm")
    draw.text((cx, y2), LINE2, font=font, fill=(255, 255, 255, 255), anchor="mm")

    banner = canvas.convert("RGB").resize((OUTPUT_W, OUTPUT_H), Image.Resampling.LANCZOS)
    banner.save(output_path, format="PNG", optimize=False, compress_level=1)
    print(f"Wrote {output_path} ({OUTPUT_W}×{OUTPUT_H}), {len(layout)} cards")


if __name__ == "__main__":
    main()
