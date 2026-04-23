"""Prepare a tighter IPAdapter reference image from a rendered design image.

Usage:
    python scripts/prepare_ipadapter_reference.py ^
        --source 04_comfyui_output/raw/male_ninja_master_S.png ^
        --mask-image 02_blender/renders/beauty/male_normal_S.png ^
        --output 03_comfyui_input/male_ninja_master_reference_focus.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageColor, ImageFilter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Rendered character design image.")
    parser.add_argument("--mask-image", required=True, help="Image whose alpha channel defines the character mask.")
    parser.add_argument("--output", required=True, help="Prepared IPAdapter reference output path.")
    parser.add_argument("--canvas-width", type=int, default=768)
    parser.add_argument("--canvas-height", type=int, default=1024)
    parser.add_argument("--target-width-fill", type=float, default=0.58)
    parser.add_argument("--target-height-fill", type=float, default=0.88)
    parser.add_argument("--alpha-threshold", type=int, default=8)
    parser.add_argument("--edge-blur", type=float, default=1.25)
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
    solid_mask = mask_alpha.point(lambda value: 255 if value >= args.alpha_threshold else 0)
    bbox = solid_mask.getbbox()
    if bbox is None:
        raise RuntimeError(f"No visible alpha region found in mask image: {mask_path}")

    cropped_source = source_image.crop(bbox)
    cropped_alpha = mask_alpha.crop(bbox)

    crop_width, crop_height = cropped_source.size
    scale = min(
        (args.canvas_width * args.target_width_fill) / max(crop_width, 1),
        (args.canvas_height * args.target_height_fill) / max(crop_height, 1),
    )
    resized_size = (
        max(1, round(crop_width * scale)),
        max(1, round(crop_height * scale)),
    )

    resized_source = cropped_source.resize(resized_size, Image.Resampling.LANCZOS)
    resized_alpha = cropped_alpha.resize(resized_size, Image.Resampling.LANCZOS)
    if args.edge_blur > 0:
        resized_alpha = resized_alpha.filter(ImageFilter.GaussianBlur(radius=args.edge_blur))

    background_rgb = ImageColor.getrgb(args.background)
    canvas = Image.new("RGBA", (args.canvas_width, args.canvas_height), (*background_rgb, 255))

    offset_x = (args.canvas_width - resized_size[0]) // 2
    offset_y = (args.canvas_height - resized_size[1]) // 2
    canvas.alpha_composite(resized_source, (offset_x, offset_y))

    # Replace the source background using the prepared alpha so IPAdapter focuses on the outfit.
    final_image = Image.new("RGBA", (args.canvas_width, args.canvas_height), (*background_rgb, 255))
    pasted_character = Image.new("RGBA", (args.canvas_width, args.canvas_height), (0, 0, 0, 0))
    pasted_character.paste(resized_source, (offset_x, offset_y))
    pasted_mask = Image.new("L", (args.canvas_width, args.canvas_height), 0)
    pasted_mask.paste(resized_alpha, (offset_x, offset_y))
    final_image = Image.composite(pasted_character, final_image, pasted_mask)
    final_image.save(output_path)


if __name__ == "__main__":
    main()
