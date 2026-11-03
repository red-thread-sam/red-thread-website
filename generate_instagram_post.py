#!/usr/bin/env python3
"""Instagram feed post matching the LinkedIn symmetric banner system."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import generate_symmetric_banner as brand

# Instagram feed post: 1080×1080, composed at 2x for the same Lanczos crispness.
CANVAS_W, CANVAS_H = 2160, 2160
OUTPUT_W, OUTPUT_H = 1080, 1080
GAP = brand.GAP  # 32px at 2x → 16px at 1x
BLEED = brand.BLEED
STEP = 8
CORNER_RADIUS = brand.CORNER_RADIUS
LINE1 = brand.LINE1
LINE2 = brand.LINE2
LINE_BOX_GAP = brand.LINE_BOX_GAP
TEXT_PAD = brand.TEXT_PAD
FONT_SIZE = 152
VERTICAL_OFFSET = 36  # slight optical lift; no LinkedIn profile overlap
EDGE_INSET = 96  # air from the top/bottom of the frame (no flush edges)
# One portrait-width column on each flank; only cap cards may hook inward.
STACK_DEPTH = 248
CREEP_INSET = 780  # cap cards reach in, leaving black above/below the title
BAND = 500  # two-step staircase along the top/bottom of each stack
OUTPUT_PATH = Path("instagram-post-symmetric.png")

# Portraits (and squares) build the side columns; leftover wides hook along the caps.
COLUMN_SIZES = {
    "wide": [(208, 208), (176, 176), (240, 135)],
    "portrait": [(225, 400), (189, 336), (162, 288), (135, 240)],
    "square": [(208, 208), (176, 176), (144, 144)],
}
CREEP_SIZES = {
    "wide": [(400, 225), (336, 189), (288, 162), (240, 135)],
    "portrait": [(189, 336), (162, 288)],
    "square": [(256, 256), (208, 208)],
}


def clip_visible(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int] | None:
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(CANVAS_W, x + w), min(CANVAS_H, y + h)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


class Packer:
    def __init__(self, text_box: tuple[int, int, int, int]):
        self.text_box = text_box
        self.placed: list[tuple[int, int, int, int]] = []
        self.allow_creep = False

    def fits(self, x: int, y: int, w: int, h: int) -> bool:
        vis = clip_visible(x, y, w, h)
        if vis is None:
            return False
        vw, vh = vis[2] - vis[0], vis[3] - vis[1]
        if vw < 80 or vh < 80:
            return False
        card = (x, y, x + w, y + h)
        if brand.rects_overlap(card, self.text_box):
            return False
        padded = brand.inflate(card, GAP)
        return not any(brand.rects_overlap(padded, other) for other in self.placed)

    def place(self, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        rect = (x, y, x + w, y + h)
        self.placed.append(rect)
        return rect

    def _in_cap(self, y: int, h: int) -> bool:
        """True when the card lives in the top or bottom band (not the stack body)."""
        top_end = EDGE_INSET + BAND
        bot_start = CANVAS_H - EDGE_INSET - BAND
        return y + h <= top_end + 48 or y >= bot_start - 48

    def try_left(self, w: int, h: int) -> tuple[int, int, int, int] | None:
        y_min = EDGE_INSET
        y_max = CANVAS_H - EDGE_INSET - h
        if y_max < y_min:
            return None
        x = -BLEED
        x_limit = CREEP_INSET - w
        while x <= x_limit:
            y = y_min
            while y <= y_max:
                max_right = CREEP_INSET if (self.allow_creep and self._in_cap(y, h)) else STACK_DEPTH
                if x + w <= max_right and self.fits(x, y, w, h):
                    return self.place(x, y, w, h)
                y += STEP
            x += STEP
        return None

    def try_right(self, w: int, h: int) -> tuple[int, int, int, int] | None:
        y_min = EDGE_INSET
        y_max = CANVAS_H - EDGE_INSET - h
        if y_max < y_min:
            return None
        x = CANVAS_W - w + BLEED
        x_limit = CANVAS_W - CREEP_INSET
        while x >= x_limit:
            y = y_min
            while y <= y_max:
                min_left = (
                    CANVAS_W - CREEP_INSET
                    if (self.allow_creep and self._in_cap(y, h))
                    else CANVAS_W - STACK_DEPTH
                )
                if x >= min_left and self.fits(x, y, w, h):
                    return self.place(x, y, w, h)
                y += STEP
            x -= STEP
        return None


def layout_headline(font_path: Path) -> tuple[ImageFont.FreeTypeFont, int, int, int, tuple[int, int, int, int]]:
    probe = ImageDraw.Draw(Image.new("L", (CANVAS_W, CANVAS_H)))
    size = FONT_SIZE
    h1 = h2 = 0
    font = brand.load_semibold_font(font_path, size)
    while size >= 96:
        font = brand.load_semibold_font(font_path, size)
        w1, h1 = brand.measure_line(probe, LINE1, font)
        w2, h2 = brand.measure_line(probe, LINE2, font)
        block_w = max(w1, w2)
        block_h = h1 + LINE_BOX_GAP + h2
        min_flank = 180
        min_cap = EDGE_INSET + 80
        if (
            block_w + TEXT_PAD * 2 + min_flank * 2 <= CANVAS_W
            and block_h + TEXT_PAD * 2 + min_cap * 2 <= CANVAS_H
        ):
            break
        size -= 4

    cx = CANVAS_W // 2
    cy = CANVAS_H // 2 - VERTICAL_OFFSET
    block_h = h1 + LINE_BOX_GAP + h2
    top = cy - block_h // 2
    y1 = top + h1 // 2
    y2 = top + h1 + LINE_BOX_GAP + h2 // 2

    b1 = probe.textbbox((cx, y1), LINE1, font=font, anchor="mm")
    b2 = probe.textbbox((cx, y2), LINE2, font=font, anchor="mm")
    text_box = (
        min(b1[0], b2[0]) - TEXT_PAD,
        min(b1[1], b2[1]) - TEXT_PAD,
        max(b1[2], b2[2]) + TEXT_PAD,
        max(b1[3], b2[3]) + TEXT_PAD,
    )
    print(f"Headline {size}pt  leading-gap={LINE_BOX_GAP}px  box={text_box}")
    return font, cx, y1, y2, text_box


def consume(
    packer: Packer,
    items: list[tuple[Image.Image, str, str]],
    side: str,
    sizes: dict[str, list[tuple[int, int]]],
) -> tuple[list[tuple[Image.Image, int, int, int, int]], list[tuple[Image.Image, str, str]]]:
    laid: list[tuple[Image.Image, int, int, int, int]] = []
    still: list[tuple[Image.Image, str, str]] = []
    place = packer.try_left if side == "left" else packer.try_right
    for img, kind, name in items:
        placed = None
        for w, h in sizes[kind]:
            placed = place(w, h)
            if placed:
                x1, y1, x2, y2 = placed
                laid.append((img, x1, y1, x2 - x1, y2 - y1))
                print(f"  {side:5} {kind:8} {x2 - x1}×{y2 - y1} at ({x1},{y1})  {name}")
                break
        if not placed:
            still.append((img, kind, name))
    return laid, still


def pack_flank(
    packer: Packer,
    items: list[tuple[Image.Image, str, str]],
    side: str,
) -> list[tuple[Image.Image, int, int, int, int]]:
    remaining = list(items)
    remaining.sort(key=lambda t: 0 if t[1] == "portrait" else 1)

    # 1) Tetris-fill the side column (no inward hooks yet).
    packer.allow_creep = False
    laid, remaining = consume(packer, remaining, side, COLUMN_SIZES)

    # 2) Leftover cards hook inward along the top/bottom of that stack.
    packer.allow_creep = True
    creeps, remaining = consume(packer, remaining, side, CREEP_SIZES)
    laid += creeps

    if remaining:
        names = ", ".join(n for _, _, n in remaining)
        print(f"WARNING: {side} could not place {len(remaining)}: {names}")
    return laid


def main() -> None:
    random.seed()
    root = Path(__file__).resolve().parent
    font_path = root / brand.FONT_FILENAME
    output_path = root / OUTPUT_PATH

    brand.ensure_inter_semibold(font_path)
    font, cx, y1, y2, text_box = layout_headline(font_path)
    text_box = brand.inflate(text_box, 72)  # extra black field around the headline

    items = brand.load_all_images((root / brand.CREATOR_DIR).resolve())
    portraits = [t for t in items if t[1] == "portrait"]
    others = [t for t in items if t[1] != "portrait"]
    left_items: list[tuple[Image.Image, str, str]] = []
    right_items: list[tuple[Image.Image, str, str]] = []
    for i, item in enumerate(portraits):
        (left_items if i % 2 == 0 else right_items).append(item)
    for i, item in enumerate(others):
        (left_items if i % 2 == 0 else right_items).append(item)
    print(f"Flanks: {len(left_items)} left, {len(right_items)} right")

    packer = Packer(text_box)
    layout = pack_flank(packer, left_items, "left")
    layout += pack_flank(packer, right_items, "right")

    canvas = brand.make_radial_gradient(CANVAS_W, CANVAS_H).convert("RGBA")
    for img, x, y, w, h in layout:
        card = brand.rounded_card(
            brand.crop_to_aspect(img, w / h).resize((w, h), Image.Resampling.LANCZOS),
            CORNER_RADIUS,
        )
        shadowed, pad_x, pad_y = brand.with_drop_shadow(card)
        brand.paste_layer(canvas, shadowed, x - pad_x, y - pad_y)

    draw = ImageDraw.Draw(canvas)
    draw.text((cx, y1), LINE1, font=font, fill=(255, 255, 255, 255), anchor="mm")
    draw.text((cx, y2), LINE2, font=font, fill=(255, 255, 255, 255), anchor="mm")

    post = canvas.convert("RGB").resize((OUTPUT_W, OUTPUT_H), Image.Resampling.LANCZOS)
    post.save(output_path, format="PNG", optimize=False, compress_level=1)
    print(f"Wrote {output_path} ({OUTPUT_W}×{OUTPUT_H}), {len(layout)} cards")


if __name__ == "__main__":
    main()
