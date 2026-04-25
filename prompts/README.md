# `prompts/` — Reusable prompt templates for GPT Image generation

This directory holds **pure prompt text** files. Every byte of a file here
is sent verbatim to the OpenAI image API when referenced via
``@prompts/<name>.md`` in [`scripts/gpt_image_edit.py`](../scripts/gpt_image_edit.py)
or through [`scripts/gpt_image_batch_5views.py`](../scripts/gpt_image_batch_5views.py).

## Rules

- **Pure prompt body only.** No YAML front-matter, no comments, no
  "how to use" headers inside the file — the loader does not strip them.
  Put all meta-documentation in this README, not inside the prompt files.
- **One concept per file.** If you want a variant, copy the file to a new
  name rather than adding conditional branches. Makes A/B comparisons
  reproducible.
- **Language is intentional.** The user's native Chinese wording is kept
  as-is where that wording came from the user. Do not "translate to
  English for compatibility" — gpt-image-2 handles both languages, and
  re-translation loses nuance.

## Current templates

### `isometric_base_5views.md`

Base **female** character sheet for isometric 2.5D RPG use. Designed to
be paired with a five-panel depth composite from
[`02_blender/renders/depth/`](../02_blender/renders/depth) (layout
`SW, S, SE, E, NE`, black background, isometric camera at 63.435° pitch).
Currently the only consumer is the `female_age{0-8}` track from
`fbx/n*.fbx`, which is why gender is hard-coded into the prompt — without
it, gpt-image-2 will sometimes produce a male body for the more
androgynous depth maps (observed on `female_age1/2/4/8` at quality
`medium`). If a male/non-binary variant is needed later, copy this file
to a new name (e.g. `isometric_base_5views_male.md`) rather than
parameterising — see the "one concept per file" rule above.

Intent encoded in the prompt:

- 等距 2.5D RPG 用基底，**女性人体**，器官明确，不要头发
- 纯白背景，动漫手绘风格，色调柔和、低饱和度、简洁线条、轻微阴影、低信息密度、清晰轮廓
- 禁止戏剧灯光、碎片、颗粒、纸张/画布纹理、棕褐色晕染、嘈杂背景

Use via the batch script:

```
python scripts/gpt_image_batch_5views.py --prompt-file prompts/isometric_base_5views.md
```

Or for a single test call:

```
python scripts/gpt_image_edit.py \
    --input 02_blender/renders/depth/female_age4_5views_depth.png \
    --prompt "@prompts/isometric_base_5views.md" \
    --output 04_comfyui_output/raw/female_age4_5views_gptimage.png \
    --model gpt-image-2 --size 1536x1024 --quality low
```
