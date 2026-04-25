# `fbx/` — Age-sorted female reference FBX set

Nine female character FBX files sorted by age from youngest to oldest:

| File | Age position |
|------|--------------|
| `n0.fbx` | youngest (toddler) |
| `n1.fbx` | |
| `n2.fbx` | |
| `n3.fbx` | |
| `n4.fbx` | |
| `n5.fbx` | |
| `n6.fbx` | |
| `n7.fbx` | |
| `n8.fbx` | oldest |

Exact ages are not recorded; only the ordinal (youngest → oldest) is
authoritative.

## What these feed

This is the **reference study track**, not the shipping player track. The
canonical player character is `male_normal` from `makehuman.blend`.

Derived outputs live under
[`02_blender/renders/depth/`](../02_blender/renders/depth) with the stem
`female_age{0-8}`:

- Per-direction: `female_age{N}_{S,SE,SW,E,NE}.png`
- 5-view composite: `female_age{N}_5views_depth.png`

Index mapping: `n{i}.fbx` → `female_age{i}` in the outputs. The output
stem encodes **age order**, not a filename, so the renders survive any
future rename of the FBX files.

## Regeneration

See [`02_blender/renders/depth/README.md`](../02_blender/renders/depth/README.md)
and [`docs/pipeline.md`](../docs/pipeline.md) section 3.2. Scripts:

- [`scripts/blender_fbx_depth.py`](../scripts/blender_fbx_depth.py)
- [`scripts/compose_5views_depth.py`](../scripts/compose_5views_depth.py)

## Ground rules

- Do not rename `n{i}.fbx` without renaming every downstream
  `female_age{i}_*.png` and updating the docs.
- Do not add new FBX files here without extending the table above and
  re-running the render + compose pipeline.
- Do not import these into the player pipeline; they are reference data.
