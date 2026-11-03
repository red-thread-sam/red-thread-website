#!/usr/bin/env python3
"""Generate a text-masked LinkedIn banner from local creator images."""

from __future__ import annotations

import io
import math
import random
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# --- Canvas & safe zones ---
CANVAS_W, CANVAS_H = 1584, 396
BACKGROUND = "#1d1d1f"
VERTICAL_OFFSET_PX = 40  # shift text up to clear the mobile profile photo

# --- Collage ---
CREATOR_DIR = Path("./creator-images")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
TILE_SIZE = 160
BRIGHTNESS_BOOST = 1.30  # +30%
SATURATION_BOOST = 1.20  # +20%

# --- Type ---
FONT_FILENAME = "Inter-Black.ttf"
FONT_SIZE_PT = 140
TEXT = "Creator-powered\nCommercial impact."
HORIZONTAL_PADDING = 28
VERTICAL_PADDING = 10
LINE_SPACING_RATIO = -0.22  # negative leading: a tight stacked block
STROKE_PX = 1

# Google Fonts ships Inter as a variable TTF; Black (900) is instantiated at load time.
# The official Inter zip provides a true static Inter-Black.ttf fallback.
FONT_URLS = [
    "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
    "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
]
INTER_ZIP_URL = "https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip"

OUTPUT_PATH = Path("linkedin-banner-masked.png")


def _download(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; generate-banner/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def ensure_inter_black(dest: Path) -> Path:
    """Download Inter-Black.ttf if it is not already present."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"Using existing font: {dest}")
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None

    for url in FONT_URLS:
        print(f"Downloading {FONT_FILENAME} from {url}")
        try:
            data = _download(url, timeout=30)
            if len(data) < 10_000:
                raise RuntimeError(f"Downloaded file looks too small ({len(data)} bytes)")
            dest.write_bytes(data)
            print(f"Saved font to {dest} ({len(data):,} bytes)")
            return dest
        except Exception as exc:  # noqa: BLE001 — try the next source
            last_error = exc
            print(f"  failed: {exc}")

    print(f"Falling back to Inter release zip: {INTER_ZIP_URL}")
    try:
        archive = zipfile.ZipFile(io.BytesIO(_download(INTER_ZIP_URL, timeout=90)))
        candidate = next(
            name
            for name in archive.namelist()
            if name.endswith("Inter-Black.ttf") and "Display" not in name
        )
        dest.write_bytes(archive.read(candidate))
        print(f"Extracted {candidate} to {dest}")
        return dest
    except Exception as exc:  # noqa: BLE001
        last_error = exc
        print(f"  failed: {exc}")

    raise RuntimeError(f"Could not download {FONT_FILENAME}") from last_error


def load_black_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont:
    """Load Inter at the heaviest available weight (Black / 900)."""
    font = ImageFont.truetype(str(font_path), size)
    try:
        axes = font.get_variation_axes()
    except OSError:
        return font

    values = []
    for axis in axes:
        tag = axis.get("tag") or axis.get("name")
        tag_str = tag.decode("ascii", "ignore") if isinstance(tag, bytes) else str(tag)
        maximum = float(axis["maximum"])
        default = float(axis["default"])
        # Prefer max optical size + max weight so display-sized type is as thick as possible.
        if "wght" in tag_str.lower() or "weight" in tag_str.lower():
            values.append(maximum)
        elif "opsz" in tag_str.lower() or "optical" in tag_str.lower():
            values.append(maximum)
        else:
            values.append(default)
    if values:
        font.set_variation_by_axes(values)
    return font


def line_spacing_for(size: int) -> int:
    return int(round(size * LINE_SPACING_RATIO))


def load_creator_images(directory: Path) -> list[Image.Image]:
    if not directory.is_dir():
        raise FileNotFoundError(f"Creator images directory not found: {directory.resolve()}")

    paths = sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not paths:
        raise FileNotFoundError(f"No jpg/png/webp images found in {directory.resolve()}")

    images: list[Image.Image] = []
    for path in paths:
        with Image.open(path) as img:
            images.append(img.convert("RGB"))
        print(f"Loaded {path.name} ({images[-1].size[0]}×{images[-1].size[1]})")

    print(f"Loaded {len(images)} creator images")
    return images


def square_thumbnail(img: Image.Image, size: int) -> Image.Image:
    """Center-crop to a square, then resize."""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    cropped = img.crop((left, top, left + side, top + side))
    return cropped.resize((size, size), Image.Resampling.LANCZOS)


def enhance_collage(collage: Image.Image) -> Image.Image:
    """Brighten and saturate the grid so imagery pops on charcoal."""
    collage = ImageEnhance.Brightness(collage).enhance(BRIGHTNESS_BOOST)
    collage = ImageEnhance.Color(collage).enhance(SATURATION_BOOST)
    return collage


def build_collage(images: list[Image.Image], width: int, height: int, tile: int) -> Image.Image:
    cols = math.ceil(width / tile)
    rows = math.ceil(height / tile)
    needed = cols * rows

    thumbs = [square_thumbnail(img, tile) for img in images]
    pool: list[Image.Image] = []
    while len(pool) < needed:
        batch = thumbs[:]
        random.shuffle(batch)
        pool.extend(batch)
    pool = pool[:needed]

    grid = Image.new("RGB", (cols * tile, rows * tile), BACKGROUND)
    for i, thumb in enumerate(pool):
        x = (i % cols) * tile
        y = (i // cols) * tile
        grid.paste(thumb, (x, y))

    collage = grid.crop((0, 0, width, height))
    return enhance_collage(collage)


def text_block_size(font: ImageFont.FreeTypeFont, text: str, spacing: int) -> tuple[int, int]:
    probe = ImageDraw.Draw(Image.new("L", (CANVAS_W, CANVAS_H)))
    bbox = probe.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        align="center",
        spacing=spacing,
    )
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def block_fits(tw: int, th: int) -> bool:
    if tw > CANVAS_W - HORIZONTAL_PADDING * 2:
        return False
    cy = CANVAS_H / 2 - VERTICAL_OFFSET_PX
    top = cy - th / 2
    bottom = cy + th / 2
    return top >= VERTICAL_PADDING and bottom <= CANVAS_H - VERTICAL_PADDING


def fit_font(font_path: Path, text: str, start_size: int) -> ImageFont.FreeTypeFont:
    """Use the requested size, shrinking only if the copy would overflow the canvas."""
    size = start_size
    while size >= 48:
        font = load_black_font(font_path, size)
        tw, th = text_block_size(font, text, line_spacing_for(size))
        if block_fits(tw, th):
            if size != start_size:
                print(f"Reduced font size from {start_size}pt to {size}pt to fit the canvas")
            return font
        size -= 2
    return load_black_font(font_path, max(size, 48))


def create_text_mask(width: int, height: int, font: ImageFont.FreeTypeFont, text: str) -> Image.Image:
    """Anti-aliased mask: white glyphs on black, centered and lifted 40px."""
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    cx = width // 2
    cy = height // 2 - VERTICAL_OFFSET_PX
    draw.multiline_text(
        (cx, cy),
        text,
        font=font,
        fill=255,
        align="center",
        anchor="mm",
        spacing=line_spacing_for(font.size),
    )
    return mask


def expand_mask(mask: Image.Image, radius: int) -> Image.Image:
    """Dilate the glyph mask by `radius` pixels for a crisp outer stroke."""
    if radius <= 0:
        return mask
    return mask.filter(ImageFilter.MaxFilter(radius * 2 + 1))


def white_edge_mask(mask: Image.Image, radius: int) -> Image.Image:
    """1px white halo plus a 1px downward shadow so dark photo edges stay legible."""
    halo = expand_mask(mask, radius)
    shadow = Image.new("L", mask.size, 0)
    shadow.paste(mask, (0, 1))
    return ImageChops.lighter(halo, shadow)


def composite_banner(collage: Image.Image, mask: Image.Image) -> Image.Image:
    background = Image.new("RGB", (CANVAS_W, CANVAS_H), BACKGROUND)
    white = Image.new("RGB", (CANVAS_W, CANVAS_H), "#ffffff")
    edged = Image.composite(white, background, white_edge_mask(mask, STROKE_PX))
    return Image.composite(collage, edged, mask)


def main() -> None:
    random.seed()  # fresh shuffle each run
    root = Path(__file__).resolve().parent
    creator_dir = (root / CREATOR_DIR).resolve()
    font_path = root / FONT_FILENAME
    output_path = root / OUTPUT_PATH

    ensure_inter_black(font_path)
    images = load_creator_images(creator_dir)

    print("Building enhanced creator collage…")
    collage = build_collage(images, CANVAS_W, CANVAS_H, TILE_SIZE)

    font = fit_font(font_path, TEXT, start_size=FONT_SIZE_PT)
    print(f"Rendering text mask at {font.size}pt (leading {line_spacing_for(font.size)}px)")
    mask = create_text_mask(CANVAS_W, CANVAS_H, font, TEXT)

    banner = composite_banner(collage, mask)
    banner.save(output_path, format="PNG", optimize=False, compress_level=1)
    print(f"Wrote {output_path} ({CANVAS_W}×{CANVAS_H})")


if __name__ == "__main__":
    main()
