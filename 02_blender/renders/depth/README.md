# Depth Render Guard

This directory is for canonical per-direction depth maps only.

Depth maps must be generated from Blender scene geometry by `scripts/blender_auto_render.py`. The script projects mesh triangles through the camera, fills a z-buffer, normalizes visible depths, and writes a black-background RGB map. Do not derive depth maps from beauty renders or prompt/generated images.

Expected practical input files for `male_normal` are:

- `male_normal_S.png`
- `male_normal_SE.png`
- `male_normal_SW.png` after it is generated through Blender, not copied or derived from a beauty render
- `male_normal_E.png`
- `male_normal_NE.png`

`N` and `E` are mirror-equivalent for the current player-facing production set, so only one of them is needed by default. Keep `E`; generate `N` only when a workflow explicitly needs it.

Do not keep composite sheets, discarded direction experiments, or non-canonical directions here, such as `W`, `*_5views_depth.png`, or `*_5faces_*_depth.png`.

If a render is useful only for comparison or debugging, move it outside this canonical input set instead of mixing it into `depth`.
