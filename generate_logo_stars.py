#!/usr/bin/env python3
"""Build a looping starfield GIF masked to the Red Thread icon.

Each frame is drawn at 768x672 on a solid white matte: black inside the
mark, white outside. Stars and comets are painted at that scale, then
the frame is Lanczos-scaled to 192x168 so the edge and the pinpricks
anti-alias. Nothing is transparent. The email stage is white.

The star pass takes 200 frames and still lands where it started.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

FRAMES = 200
FRAME_MS = 50
EXPORT_SIZE = (192, 168)
SUPERSAMPLE = 4
RENDER_SIZE = (EXPORT_SIZE[0] * SUPERSAMPLE, EXPORT_SIZE[1] * SUPERSAMPLE)
# Fixed star grays. 217 is 85% white. No frame-to-frame flicker.
STAR_TONES = np.array([115, 153, 184, 217], dtype=np.uint8)


def find_mask(explicit: str | None) -> Path:
    here = Path(__file__).resolve().parent
    names = [
        "logo-icon.png",
    ]
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    for name in names:
        candidates.append(here / name)
        candidates.append(Path.cwd() / name)
    for path in candidates:
        if path.is_file():
            return path
    raise SystemExit(
        "Could not find the logo mask. Expected logo-icon.png next to this script."
    )


def load_mask(path: Path) -> np.ndarray:
    image = Image.open(path).convert("RGBA")
    image = image.resize(RENDER_SIZE, Image.Resampling.LANCZOS)
    alpha = np.asarray(image)[:, :, 3]
    return alpha >= 128


def build_field(mask: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    height, width = mask.shape
    # Density is counted at the 192px export, not the 4x buffer.
    opaque = int(mask.sum() // (SUPERSAMPLE * SUPERSAMPLE))
    dense = min(opaque, max(48, opaque // 420))
    count = max(8, int(dense * 0.3))
    # One full crossing per loop. 200 frames keeps the slow crawl seamless.
    speed = height / FRAMES
    # 4px across at 4x, so Lanczos reduces it to a 1px anti-aliased point.
    radius = 2.0
    ys, xs = np.where(mask)
    pick = rng.choice(len(xs), size=count, replace=False)
    levels = rng.integers(0, len(STAR_TONES), count)
    stars = np.column_stack(
        [
            xs[pick].astype(float),
            ys[pick].astype(float),
            np.full(count, speed),
            np.full(count, radius),
            levels,
        ]
    )

    mass = np.cumsum(mask.sum(axis=0).astype(float))
    mass /= mass[-1]
    comet_x = np.array([np.searchsorted(mass, spot) for spot in (0.22, 0.51, 0.78)], dtype=float)
    # Integer crossings per loop stay seamless and read as upward shots.
    wraps = np.array([5, 8, 6], dtype=float)
    tails = np.array([0.55, 0.78, 0.64]) * height
    comets = np.column_stack(
        [
            comet_x,
            rng.uniform(0, height, len(comet_x)),
            wraps * height / FRAMES,
            tails,
        ]
    )
    return stars, comets


def stamp(buf: np.ndarray, mask: np.ndarray, x: float, y: float, level: int, radius: float) -> None:
    height, width = mask.shape
    xi = int(round(x))
    yi = int(round(y)) % height
    reach = max(0, int(round(radius)))
    for dy in range(-reach, reach + 1):
        yy = (yi + dy) % height
        for dx in range(-reach, reach + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            xx = xi + dx
            if xx < 0 or xx >= width or not mask[yy, xx]:
                continue
            if level > buf[yy, xx]:
                buf[yy, xx] = level


def paint_comet(buf: np.ndarray, mask: np.ndarray, x: float, y: float, tail: float) -> None:
    height, width = mask.shape
    xi = int(round(x))
    length = max(8, int(round(tail)))
    for step in range(length):
        yy = int(round(y + step)) % height
        fade = 1.0 - (step / max(1, length - 1))
        gray = int(round(40 + fade * 215))
        # 4px stroke at 4x, which settles to about 1px after the downscale.
        for dx in range(-2, 2):
            xx = xi + dx
            if xx < 0 or xx >= width or not mask[yy, xx]:
                continue
            if gray > buf[yy, xx]:
                buf[yy, xx] = gray


def render_frame(mask: np.ndarray, stars: np.ndarray, comets: np.ndarray, frame: int) -> Image.Image:
    height, width = mask.shape
    buf = np.full((height, width), 255, dtype=np.uint8)
    buf[mask] = 0
    for x, y, speed, radius, tone in stars:
        gray = int(STAR_TONES[int(tone)])
        stamp(buf, mask, x, (y - speed * frame) % height, gray, radius)
    for x, y, speed, tail in comets:
        paint_comet(buf, mask, x, (y - speed * frame) % height, tail)

    rgb = np.stack([buf, buf, buf], axis=-1)
    image = Image.fromarray(rgb)
    return image.resize(EXPORT_SIZE, Image.Resampling.LANCZOS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mask", help="Path to the black logo PNG.")
    parser.add_argument(
        "--output",
        default="logo-stars-loop.gif",
        help="GIF path, relative to this script unless absolute.",
    )
    args = parser.parse_args()

    mask_path = find_mask(args.mask)
    mask = load_mask(mask_path)
    rng = np.random.default_rng(7)
    stars, comets = build_field(mask, rng)
    frames = [render_frame(mask, stars, comets, i) for i in range(FRAMES)]

    output = Path(args.output)
    if not output.is_absolute():
        output = Path(__file__).resolve().parent / output
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=FRAME_MS,
        disposal=2,
        optimize=True,
    )
    size_kb = output.stat().st_size / 1024
    print(f"mask: {mask_path}")
    print(f"render: {RENDER_SIZE[0]}x{RENDER_SIZE[1]}")
    print(f"frames: {FRAMES} at {EXPORT_SIZE[0]}x{EXPORT_SIZE[1]}")
    print(f"wrote: {output} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
