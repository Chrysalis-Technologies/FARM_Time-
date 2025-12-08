"""
Analyze lamb coat patterns from a folder of photos using palette extraction.

The script quantizes each image to a small adaptive palette, aggregates the
palette across all provided photos, and infers whether the coat reads as
solid, two-tone, or multi-tone based on the color distribution.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from PIL import Image

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
DEFAULT_COLORS = 6

Color = Tuple[int, int, int]
Palette = List[Tuple[Color, float]]


def find_images(root: Path) -> List[Path]:
    """Return a list of image paths under ``root``.

    The search is recursive and limited to common image extensions.
    """
    return [
        path
        for path in root.rglob("*")
        if path.suffix.lower() in SUPPORTED_EXTENSIONS and path.is_file()
    ]


def quantized_palette(image: Image.Image, colors: int = DEFAULT_COLORS) -> Palette:
    """Extract a compact palette from ``image`` using adaptive quantization.

    Returns a list of ``(rgb, fraction)`` tuples sorted by most common color.
    """
    paletted = image.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=colors)
    palette = paletted.getpalette()[: colors * 3]
    counts = paletted.getcolors()

    if not counts:
        return []

    total_pixels = sum(count for count, _ in counts)
    swatches: Palette = []
    for count, idx in sorted(counts, reverse=True):
        base = idx * 3
        color = tuple(palette[base : base + 3])
        swatches.append((color, count / total_pixels))

    return swatches


def aggregate_palette(images: Iterable[Path], colors: int = DEFAULT_COLORS) -> Palette:
    """Aggregate palettes across multiple images.

    The function downsizes images for speed, extracts individual palettes, and
    returns a combined palette sorted by frequency.
    """
    combined: Counter[Color] = Counter()

    for image_path in images:
        with Image.open(image_path) as image:
            image = image.copy()
            image.thumbnail((640, 640))
            swatches = quantized_palette(image, colors=colors)
            pixel_count = image.width * image.height
            for color, fraction in swatches:
                combined[color] += fraction * pixel_count

    total_pixels = sum(combined.values())
    if total_pixels == 0:
        return []

    palette: Palette = [
        (color, count / total_pixels) for color, count in combined.most_common()
    ]
    return palette


def nearest_basic_color(color: Color) -> str:
    """Map an RGB tuple to a coarse color name for readability."""
    basics = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "brown": (120, 72, 48),
        "tan": (194, 158, 124),
        "gray": (128, 128, 128),
        "cream": (232, 220, 190),
    }

    def squared_distance(a: Color, b: Color) -> int:
        return sum((ax - bx) ** 2 for ax, bx in zip(a, b))

    return min(basics, key=lambda name: squared_distance(color, basics[name]))


def describe_pattern(palette: Palette) -> str:
    """Provide a textual summary of the coat pattern from the palette."""
    if not palette:
        return "No palette available."

    primary_share = palette[0][1]
    secondary_share = palette[1][1] if len(palette) > 1 else 0.0

    if primary_share >= 0.85:
        return "Coat appears solid or nearly solid in the dominant hue."
    if primary_share >= 0.6 and secondary_share >= 0.15:
        return "Two-tone coat with a visible secondary color."
    if primary_share >= 0.5 and secondary_share < 0.15:
        return "Mostly solid with subtle mottling."
    return "Multi-tone or patterned coat with several color patches."


def format_palette(palette: Palette, top_n: int = 5) -> List[str]:
    """Format palette entries for CLI output."""
    lines = []
    for color, share in palette[:top_n]:
        name = nearest_basic_color(color)
        r, g, b = color
        lines.append(f"  - {share:5.1%} {name} (rgb={r},{g},{b})")
    return lines


def analyze_directory(directory: Path) -> Tuple[Palette, List[Path]]:
    images = find_images(directory)
    palette = aggregate_palette(images)
    return palette, images


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze lamb coat patterns from photos.")
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("sheep_ids/input/Bugonia"),
        help="Folder containing Bugonia's photos (searches recursively).",
    )
    args = parser.parse_args(argv)

    palette, images = analyze_directory(args.dir)

    if not images:
        print(f"No images found under {args.dir.resolve()}. Add photos to analyze Bugonia's coat.")
        return 1

    print(f"Analyzed {len(images)} photo(s) from {args.dir.resolve()}\n")
    if palette:
        print("Dominant colors:")
        for line in format_palette(palette):
            print(line)
        print("\nPattern inference:")
        print(f"  {describe_pattern(palette)}")
    else:
        print("Could not derive a palette from the provided images.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
