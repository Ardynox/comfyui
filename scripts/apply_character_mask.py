"""Replace a generated image background using a Blender character alpha mask.

Usage:
    python scripts/apply_character_mask.py ^
        --source 04_comfyui_output/raw/male_ninja_v2raw_S.png ^
        --mask-image 02_blender/renders/beauty/male_normal_S.png ^
        --output 04_comfyui_output/raw/male_ninja_v2_S.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageColor, ImageFilter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Generated image to clean.")
    parser.add_argument("--mask-image", required=True, help="Image whose alpha channel defines the character mask.")
    parser.add_argument("--output", required=True, help="Cleaned output path.")
    parser.add_argument("--alpha-threshold", type=int, default=10)
    parser.add_argument("--edge-blur", type=float, default=1.0)
    parser.add_argument("--background", default="#f5f3ee", help="Background color, e.g. '#f5f3ee'.")
    return parser.parse_args()


def require_file(path_value: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def main() -> None:
    args = parse_args()
    source_path = require_file(args.source)
    mask_path = require_file(args.mask_image)
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source_image = Image.open(source_path).convert("RGBA")
    mask_alpha = Image.open(mask_path).convert("RGBA").getchannel("A")
    mask_alpha = mask_alpha.point(lambda value: 255 if value >= args.alpha_threshold else 0)
    if args.edge_blur > 0:
        mask_alpha = mask_alpha.filter(ImageFilter.GaussianBlur(radius=args.edge_blur))

    background_rgb = ImageColor.getrgb(args.background)
    background = Image.new("RGBA", source_image.size, (*background_rgb, 255))
    cleaned = Image.composite(source_image, background, mask_alpha)
    cleaned.save(output_path)


if __name__ == "__main__":
    main()
