# Depth Render Guard

This directory is for canonical per-direction depth maps only.

Expected generated files for `male_normal` are:

- `male_normal_S.png`
- `male_normal_SE.png`
- `male_normal_E.png`
- `male_normal_NE.png`
- `male_normal_N.png`

Do not keep composite sheets, discarded direction experiments, or non-canonical directions here, such as `SW`, `W`, `*_5views_depth.png`, or `*_5faces_*_depth.png`.

If a render is useful only for comparison or debugging, move it outside this canonical input set instead of mixing it into `depth`.
