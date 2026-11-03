#!/usr/bin/env python3
"""Organic multi-scale Instagram bento cascade."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import generate_symmetric_banner as brand

CANVAS_W, CANVAS_H = 2160, 2160
OUTPUT_W, OUTPUT_H = 1080, 1080
GAP = brand.GAP  # 32px at 2x
BLEED = brand.BLEED
STEP = 8
CORNER_RADIUS = brand.CORNER_RADIUS  # 48px on every card
LINE1 = brand.LINE1
LINE2 = brand.LINE2
LINE_BOX_GAP = 88
FONT_SIZE = 156
ELLIPSE_RX = 800
ELLIPSE_RY = 660
OUTPUT_PATH = Path("ig-banner-organic.png")

# Long-side bases at 2x. Squares sit a bit under the landscape long-side
# so a hero tile can still live in a corner without eating the type.
TIER_BASES = {
    "small": [232, 248, 256, 272],
    "medium": [384, 400, 416],
    "large": [624, 640, 656],
}
SQUARE_BASES = {
    "small": [232, 248, 256],
    "medium": [368, 384, 400],
    "large": [496, 512, 544],
}


def dims_for(kind: str, tier: str) -> tuple[int, int]:
    if kind == "square":
        b = random.choice(SQUARE_BASES[tier])
        return b, b
    b = random.choice(TIER_BASES[tier])
    short = max(8, int(round(b * 9 / 16)))
    short -= short % 2
    if kind == "wide":
        return b, short
    return short, b


def clip_visible(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int] | None:
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(CANVAS_W, x + w), min(CANVAS_H, y + h)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def overlaps_ellipse(x: int, y: int, w: int, h: int) -> bool:
    cx, cy = CANVAS_W / 2, CANVAS_H / 2
    px = min(max(cx, x), x + w)
    py = min(max(cy, y), y + h)
    return ((px - cx) / ELLIPSE_RX) ** 2 + ((py - cy) / ELLIPSE_RY) ** 2 < 1.0


def in_corner_band(x: int, y: int, w: int, h: int) -> bool:
    """True when the card lives in a corner, not the mid-side waist."""
    cy = y + h / 2
    return cy < CANVAS_H * 0.42 or cy > CANVAS_H * 0.58


def on_far_edge(x: int, w: int) -> bool:
    return x <= -BLEED + 4 or x + w >= CANVAS_W + BLEED - 4


def flank_center(x: int, w: int, left: float, right: float) -> bool:
    cx = x + w / 2
    return cx <= CANVAS_W * left or cx >= CANVAS_W * right


class Packer:
    def __init__(self) -> None:
        self.placed: list[tuple[int, int, int, int]] = []

    def fits(self, x: int, y: int, w: int, h: int) -> bool:
        vis = clip_visible(x, y, w, h)
        if vis is None:
            return False
        vw, vh = vis[2] - vis[0], vis[3] - vis[1]
        if vw < 96 or vh < 96 or vw * vh < 0.6 * w * h:
            return False
        if overlaps_ellipse(x, y, w, h):
            return False
        card = (x, y, x + w, y + h)
        padded = brand.inflate(card, GAP)
        return not any(brand.rects_overlap(padded, other) for other in self.placed)

    def place(self, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        rect = (x, y, x + w, y + h)
        self.placed.append(rect)
        return rect

    def candidates(self, w: int, h: int) -> list[tuple[int, int]]:
        pts: list[tuple[int, int]] = []
        y_max = CANVAS_H + BLEED - h
        x_left = -BLEED
        x_right = CANVAS_W - w + BLEED
        for y in range(-BLEED, y_max + 1, STEP):
            pts.append((x_left, y))
            pts.append((x_right, y))
        for x1, y1, x2, y2 in self.placed:
            pts.extend(
                (
                    (x2 + GAP, y1),
                    (x2 + GAP, y2 - h),
                    (x1 - GAP - w, y1),
                    (x1 - GAP - w, y2 - h),
                    (x1, y2 + GAP),
                    (x2 - w, y2 + GAP),
                    (x1, y1 - GAP - h),
                    (x2 - w, y1 - GAP - h),
                )
            )
        # Unique, keep order.
        seen: set[tuple[int, int]] = set()
        out: list[tuple[int, int]] = []
        for p in pts:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def allowed(self, x: int, y: int, w: int, h: int, tier: str) -> bool:
        if not self.fits(x, y, w, h):
            return False
        if tier == "large":
            return on_far_edge(x, w)
        if tier == "medium":
            return flank_center(x, w, 0.32, 0.68)
        return in_corner_band(x, y, w, h) and flank_center(x, w, 0.40, 0.60)

    def score(self, x: int, y: int, w: int, h: int, tier: str) -> tuple[float, ...]:
        vis = clip_visible(x, y, w, h)
        assert vis is not None
        vw, vh = vis[2] - vis[0], vis[3] - vis[1]
        left_dist = abs(x - (-BLEED))
        right_dist = abs((x + w) - (CANVAS_W + BLEED))
        edgeness = min(left_dist, right_dist)
        inward = min(max(0, x), max(0, CANVAS_W - (x + w)))
        end_y = min(max(0, y + BLEED), max(0, CANVAS_H + BLEED - (y + h)))
        if tier == "large":
            return (edgeness, -vw * vh, end_y)
        if tier == "small":
            return (-inward, end_y, edgeness)
        return (edgeness, -vw * vh)

    def try_place(self, w: int, h: int, tier: str) -> tuple[int, int, int, int] | None:
        best: tuple[tuple[float, ...], int, int] | None = None
        for x, y in self.candidates(w, h):
            if not self.allowed(x, y, w, h, tier):
                continue
            sc = self.score(x, y, w, h, tier)
            if best is None or sc < best[0]:
                best = (sc, x, y)
        if best is None:
            return None
        _, x, y = best
        return self.place(x, y, w, h)


def assign_tiers(n: int) -> list[str]:
    n_large = random.randint(4, 6)
    n_small = random.randint(6, 8)
    n_medium = max(4, n - n_large - n_small)
    while n_large + n_medium + n_small > n:
        if n_small > 5:
            n_small -= 1
        elif n_medium > 4:
            n_medium -= 1
        else:
            n_large -= 1
    while n_large + n_medium + n_small < n:
        n_medium += 1
    tiers = ["large"] * n_large + ["medium"] * n_medium + ["small"] * n_small
    random.shuffle(tiers)
    return tiers


def layout_headline(font_path: Path) -> tuple[ImageFont.FreeTypeFont, int, int, int]:
    probe = ImageDraw.Draw(Image.new("L", (CANVAS_W, CANVAS_H)))
    size = FONT_SIZE
    font = brand.load_semibold_font(font_path, size)
    h1 = h2 = 0
    while size >= 104:
        font = brand.load_semibold_font(font_path, size)
        w1, h1 = brand.measure_line(probe, LINE1, font)
        w2, h2 = brand.measure_line(probe, LINE2, font)
        if max(w1, w2) <= 1680:
            break
        size -= 4
    cx = CANVAS_W // 2
    cy = CANVAS_H // 2
    block_h = h1 + LINE_BOX_GAP + h2
    top = cy - block_h // 2
    y1 = top + h1 // 2
    y2 = top + h1 + LINE_BOX_GAP + h2 // 2
    print(f"Headline {size}pt  leading-gap={LINE_BOX_GAP}px")
    return font, cx, y1, y2


def main() -> None:
    random.seed(33)
    root = Path(__file__).resolve().parent
    font_path = root / brand.FONT_FILENAME
    output_path = root / OUTPUT_PATH

    brand.ensure_inter_semibold(font_path)
    font, cx, y1, y2 = layout_headline(font_path)

    items = brand.load_all_images((root / brand.CREATOR_DIR).resolve())
    tiers = assign_tiers(len(items))
    tagged = list(zip(items, tiers))
    order = {"large": 0, "medium": 1, "small": 2}
    tagged.sort(key=lambda t: (order[t[1]], 0 if t[0][1] == "portrait" else 1))

    packer = Packer()
    layout: list[tuple[Image.Image, int, int, int, int]] = []
    leftover: list[tuple[tuple[Image.Image, str, str], str]] = []

    for (img, kind, name), tier in tagged:
        placed = None
        # A couple of size draws inside the tier so a reject can retry.
        for _ in range(4):
            w, h = dims_for(kind, tier)
            placed = packer.try_place(w, h, tier)
            if placed:
                break
        if placed is None and tier != "small":
            for fallback in ("medium", "small"):
                if fallback == tier:
                    continue
                for _ in range(3):
                    w, h = dims_for(kind, fallback)
                    placed = packer.try_place(w, h, fallback)
                    if placed:
                        tier = fallback
                        break
                if placed:
                    break
        if placed is None:
            leftover.append(((img, kind, name), tier))
            print(f"  SKIP {tier:6} {kind:8}  {name}")
            continue
        x1, y1p, x2, y2p = placed
        layout.append((img, x1, y1p, x2 - x1, y2p - y1p))
        print(f"  {tier:6} {kind:8} {x2 - x1}×{y2p - y1p} at ({x1},{y1p})  {name}")

    if leftover:
        print(f"WARNING: {len(leftover)} unplaced")

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
