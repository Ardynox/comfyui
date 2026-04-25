"""Compose per-direction depth PNGs into a single 5-view horizontal strip.

Usage:
    python scripts/compose_5views_depth.py \
        --depth-dir D:/Godot/comfyui/02_blender/renders/depth \
        --stems female_age0,female_age1,female_age2,female_age3,female_age4,female_age5,female_age6,female_age7,female_age8

For each stem the script reads ``{stem}_{DIR}.png`` for the 5 canonical
directions (SW, S, SE, E, NE) and writes
``{stem}_5views_depth.png`` side-by-side in the same directory.

Composite layout order (left-to-right): SW, S, SE, E, NE. That sweeps from
pure front (SW, 0 deg) through profile (SE, E) to pure back (NE, 180 deg)
so the sheet reads as a clean rotation. Do not reorder without also
updating ``02_blender/renders/depth/README.md`` and
``docs/pipeline.md`` section 3.2, otherwise downstream AI agents will mis-
interpret the panels.

Produces PNG only; inputs must already be the canonical black-background
RGB depth maps from ``blender_auto_render.py`` or ``blender_fbx_depth.py``.
Do NOT feed it beauty renders, normal maps, or GPT-generated images.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


DEFAULT_VIEW_ORDER = ("SW", "S", "SE", "E", "NE")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth-dir", required=True)
    parser.add_argument("--stems", required=True,
                        help="Comma-separated list of stems, e.g. 'female_age0,female_age1'.")
    parser.add_argument("--views", default=",".join(DEFAULT_VIEW_ORDER),
                        help="Comma-separated direction order (left-to-right).")
    parser.add_argument("--suffix", default="_5views_depth",
                        help="Suffix appended to each stem for the composite filename.")
    return parser.parse_args()


def compose_stem(depth_dir: Path, stem: str, views: list[str], suffix: str) -> Path:
    tiles = []
    for view in views:
        tile_path = depth_dir / f"{stem}_{view}.png"
        if not tile_path.is_file():
            raise FileNotFoundError(f"Missing tile: {tile_path}")
        tiles.append(Image.open(tile_path).convert("RGB"))

    width, height = tiles[0].size
    for tile in tiles[1:]:
        if tile.size != (width, height):
            raise RuntimeError(f"Tile size mismatch for {stem}: expected {width}x{height}, "
                               f"got {tile.size}")

    composite = Image.new("RGB", (width * len(tiles), height), color=(0, 0, 0))
    for index, tile in enumerate(tiles):
        composite.paste(tile, (index * width, 0))

    out_path = depth_dir / f"{stem}{suffix}.png"
    composite.save(out_path, "PNG")
    return out_path


def main() -> None:
    args = parse_args()
    depth_dir = Path(args.depth_dir).resolve()
    if not depth_dir.is_dir():
        raise RuntimeError(f"Not a directory: {depth_dir}")

    views = [v.strip() for v in args.views.split(",") if v.strip()]
    stems = [s.strip() for s in args.stems.split(",") if s.strip()]

    for stem in stems:
        out_path = compose_stem(depth_dir, stem, views, args.suffix)
        print(f"[compose_5views_depth] wrote {out_path}")


if __name__ == "__main__":
    main()
