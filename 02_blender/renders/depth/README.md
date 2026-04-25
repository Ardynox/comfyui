# Depth Render Guard

This directory holds canonical per-direction depth maps used downstream by
ComfyUI and Photoshop. Every file here must come from Blender scene or FBX
geometry through one of the scripts listed below. Never derive a depth map
from a beauty render, a prompt-generated image, or a photograph. Never
copy `*_S.png` over a direction slot that needs its own projection.

## Tracks

Two independent tracks live here. Do not mix them, do not delete one
thinking the other is "the real one".

### 1. `male_normal` — canonical player character

Produced by [`scripts/blender_auto_render.py`](../../../scripts/blender_auto_render.py)
from the live `makehuman.blend` scene. These feed the shipping player
pipeline.

Files:

- `male_normal_S.png`
- `male_normal_SE.png`
- `male_normal_SW.png`
- `male_normal_E.png`
- `male_normal_NE.png`

`N` and `E` are mirror-equivalent for the current player-facing production
set, so only `E` is kept by default. Regenerate `N` only when a workflow
explicitly needs it.

The sibling file `male_normal_5views_player_depth_gptimage.png` is a
GPT-image composite kept for reference, not a Blender render.

### 2. `female_age{0-8}` — age-sorted female reference study

Produced by [`scripts/blender_fbx_depth.py`](../../../scripts/blender_fbx_depth.py)
from the FBX files in [`fbx/`](../../../fbx) (which are sorted by age:
`n0.fbx` is the youngest, `n8.fbx` is the oldest).

For each age index 0–8 there are six files:

- `female_age{N}_S.png`, `_SE.png`, `_SW.png`, `_E.png`, `_NE.png` — individual
  per-direction depth maps, one projection per direction
- `female_age{N}_5views_depth.png` — horizontal 5-panel composite built by
  [`scripts/compose_5views_depth.py`](../../../scripts/compose_5views_depth.py);
  panel order left-to-right is `SW, S, SE, E, NE` so the strip reads as a
  rotation from pure front to pure back

Index mapping is intentionally `age{index}` rather than `n{index}` so the
sorted-by-age meaning survives if the FBX files are ever renamed.

## How to regenerate

Male track (must have `makehuman.blend` open as the scene):

```
blender --background makehuman.blend --python scripts/blender_auto_render.py -- \
    --body-type male_normal --model-object CharacterRoot
```

Female track (imports each FBX into an empty scene, five directions, then
composites):

```
"D:/Games/SteamLibrary/steamapps/common/Blender/blender.exe" --background \
    --python scripts/blender_fbx_depth.py -- \
    --fbx-dir D:/Godot/comfyui/fbx \
    --out-dir D:/Godot/comfyui/02_blender/renders/depth \
    --pattern "n*.fbx" \
    --directions "S,SE,SW,E,NE" \
    --stem-format "female_age{index}"

python scripts/compose_5views_depth.py \
    --depth-dir D:/Godot/comfyui/02_blender/renders/depth \
    --stems female_age0,female_age1,female_age2,female_age3,female_age4,female_age5,female_age6,female_age7,female_age8
```

Both scripts use the same orthographic camera setup (rotation
`63.435°/0°/45°`, auto-framing at `target_width_fill=0.62`,
`target_height_fill=0.72`) so depths are comparable across tracks.

## Feeding these into GPT Image

To turn a depth sheet into a coloured character via OpenAI gpt-image, use
[`scripts/gpt_image_edit.py`](../../../scripts/gpt_image_edit.py) for
single calls, or
[`scripts/gpt_image_batch_5views.py`](../../../scripts/gpt_image_batch_5views.py)
for the full 9-model loop (skip-existing, resumable, shares the prompt
template in [`prompts/isometric_base_5views.md`](../../../prompts/isometric_base_5views.md)).

Single call example:

```
python scripts/gpt_image_edit.py \
    --input 02_blender/renders/depth/female_age4_5views_depth.png \
    --prompt "@prompts/isometric_base_5views.md" \
    --output 04_comfyui_output/raw/female_age4_5views_gptimage.png \
    --model gpt-image-2 --size 1536x1024 --quality low
```

`gpt-image-2` rejects `--background transparent`; use `auto` or `opaque`
and put "纯白背景" in the prompt instead.

Generated PNGs go to `04_comfyui_output/raw/`, **never back into this
directory**. See `docs/pipeline.md` sections 4.2–4.3 for details.

## What must not go in here

- Composite sheets from other sources (GPT images, AI upscales, etc.)
  except the pre-existing `male_normal_5views_player_depth_gptimage.png`
- Discarded direction experiments such as `W`, `*_5faces_*_depth.png`,
  `*_5views.png` without a track prefix
- Depth maps derived from beauty renders or generated images
- New body types without an accompanying README update that documents the
  track

If a render is useful only for comparison or debugging, move it outside
this directory. Create a sibling `renders/depth_wip/` or similar if you
need scratch space.
