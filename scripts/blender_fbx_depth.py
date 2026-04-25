"""Batch FBX -> depth PNG renderer.

Imports each FBX into an empty scene, applies the same orthographic camera
setup as ``blender_auto_render.py``, projects mesh triangles through the
camera to build a z-buffer, normalises visible depths, and writes one
black-background RGB PNG per requested direction.

Usage:
    blender --background --python scripts/blender_fbx_depth.py -- \
        --fbx-dir D:/Godot/comfyui/fbx \
        --out-dir D:/Godot/comfyui/02_blender/renders/depth \
        --directions S

Current production use: the `female_age{0-8}` reference set under
`02_blender/renders/depth/`. Run with::

    --stem-format "female_age{index}" --directions "S,SE,SW,E,NE"
    --pattern "n*.fbx"

Then compose via ``scripts/compose_5views_depth.py``. See
``02_blender/renders/depth/README.md`` and ``docs/pipeline.md`` section 3.2
for the full track definition.

Do NOT change the camera rotation (``DEFAULT_CAMERA_ROTATION``) or framing
fills (``DEFAULT_TARGET_WIDTH_FILL`` / ``DEFAULT_TARGET_HEIGHT_FILL``)
without mirroring the same change in ``blender_auto_render.py``; both
tracks share these constants so their depth output is comparable.
"""

from __future__ import annotations

import argparse
import math
import sys
from array import array
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


SUPPORTED_DIRECTION_ANGLES = {
    "S": 0.0,
    "SE": -45.0,
    "SW": 45.0,
    "E": -90.0,
    "NE": -135.0,
    "N": 180.0,
}

DEFAULT_RESOLUTION_X = 768
DEFAULT_RESOLUTION_Y = 1024
DEFAULT_CAMERA_ROTATION = (63.435, 0.0, 45.0)
DEFAULT_TARGET_WIDTH_FILL = 0.62
DEFAULT_TARGET_HEIGHT_FILL = 0.72
DEFAULT_FRAMING_MESH_RATIO = 0.08


def log(message: str) -> None:
    print(f"[blender_fbx_depth] {message}")


def blender_argv() -> list[str]:
    argv = list(getattr(bpy.app, "argv", sys.argv))
    if "--" not in argv:
        return []
    return argv[argv.index("--") + 1 :]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fbx-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--pattern", default="*.fbx")
    parser.add_argument("--directions", default="S")
    parser.add_argument("--stem-format", default="{stem}",
                        help="Output stem template with {stem} and {index} placeholders. "
                             "Example: 'female_age{index}' renames n0.fbx output to 'female_age0_*.png'.")
    parser.add_argument("--resolution-x", type=int, default=DEFAULT_RESOLUTION_X)
    parser.add_argument("--resolution-y", type=int, default=DEFAULT_RESOLUTION_Y)
    parser.add_argument("--face-offset-deg", type=float, default=0.0,
                        help="Extra rotation about Z applied so the model faces -Y (camera) at S=0deg.")
    return parser.parse_args(blender_argv())


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_fbx(path: Path) -> None:
    bpy.ops.import_scene.fbx(filepath=str(path))


def collect_mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.data.objects if obj.type == "MESH" and not obj.hide_render]


def pick_root_object(mesh_objects: list[bpy.types.Object]) -> bpy.types.Object:
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if len(armatures) == 1:
        return armatures[0]
    if armatures:
        return armatures[0]
    if not mesh_objects:
        raise RuntimeError("No mesh objects found after FBX import.")
    roots = [obj for obj in mesh_objects if obj.parent is None]
    return roots[0] if roots else mesh_objects[0]


def ensure_camera(scene: bpy.types.Scene) -> bpy.types.Object:
    camera_data = bpy.data.cameras.new("DepthCamera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 10.0
    camera_obj = bpy.data.objects.new("DepthCamera", camera_data)
    bpy.context.collection.objects.link(camera_obj)
    camera_obj.rotation_mode = "XYZ"
    camera_obj.rotation_euler = tuple(math.radians(value) for value in DEFAULT_CAMERA_ROTATION)
    camera_obj.location = Vector((15.0, -15.0, 15.0))
    scene.camera = camera_obj
    return camera_obj


def configure_render(scene: bpy.types.Scene, width: int, height: int) -> None:
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100


def select_framing_meshes(mesh_objects: list[bpy.types.Object], mesh_ratio: float) -> list[bpy.types.Object]:
    if not mesh_objects:
        raise RuntimeError("No mesh objects available for framing.")
    max_extent = max(max(obj.dimensions) for obj in mesh_objects)
    threshold = max_extent * mesh_ratio
    framing = [obj for obj in mesh_objects if max(obj.dimensions) >= threshold]
    return framing or mesh_objects


def camera_local_bounds(camera_obj, mesh_objects):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    camera_inverse = camera_obj.matrix_world.inverted()
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for mesh_obj in mesh_objects:
        eval_obj = mesh_obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        try:
            for vertex in eval_mesh.vertices:
                local = camera_inverse @ (eval_obj.matrix_world @ vertex.co)
                if local.x < min_x: min_x = local.x
                if local.x > max_x: max_x = local.x
                if local.y < min_y: min_y = local.y
                if local.y > max_y: max_y = local.y
        finally:
            eval_obj.to_mesh_clear()
    if min_x == float("inf"):
        raise RuntimeError("Framing failed: no mesh vertices found.")
    return min_x, max_x, min_y, max_y


def projected_view_bounds(scene, camera_obj, mesh_objects):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    min_u = min_v = float("inf")
    max_u = max_v = float("-inf")
    for mesh_obj in mesh_objects:
        eval_obj = mesh_obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        try:
            for vertex in eval_mesh.vertices:
                projected = world_to_camera_view(scene, camera_obj, eval_obj.matrix_world @ vertex.co)
                if projected.z < 0.0:
                    continue
                if projected.x < min_u: min_u = projected.x
                if projected.x > max_u: max_u = projected.x
                if projected.y < min_v: min_v = projected.y
                if projected.y > max_v: max_v = projected.y
        finally:
            eval_obj.to_mesh_clear()
    if min_u == float("inf"):
        raise RuntimeError("Framing failed: no projected vertices.")
    return min_u, max_u, min_v, max_v


def auto_frame_camera(scene, camera_obj, mesh_objects,
                      target_width_fill=DEFAULT_TARGET_WIDTH_FILL,
                      target_height_fill=DEFAULT_TARGET_HEIGHT_FILL,
                      framing_mesh_ratio=DEFAULT_FRAMING_MESH_RATIO):
    framing_meshes = select_framing_meshes(mesh_objects, framing_mesh_ratio)
    min_x, max_x, min_y, max_y = camera_local_bounds(camera_obj, framing_meshes)
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5
    rotation = camera_obj.matrix_world.to_quaternion()
    camera_obj.location = camera_obj.location + rotation @ Vector((center_x, center_y, 0.0))
    bpy.context.view_layer.update()

    min_u, max_u, min_v, max_v = projected_view_bounds(scene, camera_obj, framing_meshes)
    fill_w = max_u - min_u
    fill_h = max_v - min_v
    scale_factor = max(
        fill_w / max(target_width_fill, 1e-6),
        fill_h / max(target_height_fill, 1e-6),
        1e-6,
    )
    camera_obj.data.ortho_scale = max(camera_obj.data.ortho_scale * scale_factor, 1e-6)
    bpy.context.view_layer.update()


def project_point(scene, camera_obj, world_point, width, height):
    projected = world_to_camera_view(scene, camera_obj, world_point)
    camera_space = camera_obj.matrix_world.inverted() @ world_point
    x = projected.x * (width - 1)
    y = projected.y * (height - 1)
    depth = -camera_space.z
    return x, y, depth


def edge(ax, ay, bx, by, cx, cy):
    return (cx - ax) * (by - ay) - (cy - ay) * (bx - ax)


def save_depth_png(path: Path, width: int, height: int,
                   scene, camera_obj, mesh_objects) -> None:
    depth_buffer = [float("inf")] * (width * height)
    depsgraph = bpy.context.evaluated_depsgraph_get()

    for mesh_obj in mesh_objects:
        eval_obj = mesh_obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        try:
            eval_mesh.calc_loop_triangles()
            world_matrix = eval_obj.matrix_world
            projected = [
                project_point(scene, camera_obj, world_matrix @ v.co, width, height)
                for v in eval_mesh.vertices
            ]
            for tri in eval_mesh.loop_triangles:
                ids = tri.vertices
                v = [projected[i] for i in ids]
                if all(pt[2] <= 0.0 for pt in v):
                    continue
                x0, y0, z0 = v[0]
                x1, y1, z1 = v[1]
                x2, y2, z2 = v[2]
                min_x = max(int(math.floor(min(x0, x1, x2))), 0)
                max_x = min(int(math.ceil(max(x0, x1, x2))), width - 1)
                min_y = max(int(math.floor(min(y0, y1, y2))), 0)
                max_y = min(int(math.ceil(max(y0, y1, y2))), height - 1)
                if min_x > max_x or min_y > max_y:
                    continue
                area = edge(x0, y0, x1, y1, x2, y2)
                if abs(area) <= 1e-8:
                    continue
                for py in range(min_y, max_y + 1):
                    sy = py + 0.5
                    for px in range(min_x, max_x + 1):
                        sx = px + 0.5
                        w0 = edge(x1, y1, x2, y2, sx, sy)
                        w1 = edge(x2, y2, x0, y0, sx, sy)
                        w2 = edge(x0, y0, x1, y1, sx, sy)
                        if area > 0.0:
                            inside = w0 >= 0.0 and w1 >= 0.0 and w2 >= 0.0
                        else:
                            inside = w0 <= 0.0 and w1 <= 0.0 and w2 <= 0.0
                        if not inside:
                            continue
                        b0 = w0 / area
                        b1 = w1 / area
                        b2 = w2 / area
                        depth = b0 * z0 + b1 * z1 + b2 * z2
                        idx = py * width + px
                        if depth <= 0.0 or depth >= depth_buffer[idx]:
                            continue
                        depth_buffer[idx] = depth
        finally:
            eval_obj.to_mesh_clear()

    visible = [d for d in depth_buffer if d != float("inf")]
    if not visible:
        raise RuntimeError(f"No visible geometry for depth output: {path}")
    min_d = min(visible)
    max_d = max(visible)
    span = max_d - min_d
    pixels = array("f", [0.0]) * (width * height * 4)
    for i, d in enumerate(depth_buffer):
        base = i * 4
        pixels[base + 3] = 1.0
        if d == float("inf"):
            continue
        intensity = 1.0 if span <= 1e-8 else 1.0 - ((d - min_d) / span)
        pixels[base + 0] = intensity
        pixels[base + 1] = intensity
        pixels[base + 2] = intensity

    image = bpy.data.images.new(f"depth_{path.stem}", width=width, height=height, alpha=True)
    image.alpha_mode = "STRAIGHT"
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.pixels.foreach_set(pixels)
    image.save()
    bpy.data.images.remove(image)


def render_fbx(fbx_path: Path, directions: dict[str, float], out_dir: Path,
               width: int, height: int, face_offset_deg: float,
               output_stem: str) -> None:
    reset_scene()
    scene = bpy.context.scene
    configure_render(scene, width, height)
    import_fbx(fbx_path)

    mesh_objects = collect_mesh_objects()
    if not mesh_objects:
        raise RuntimeError(f"{fbx_path.name}: no meshes imported.")
    root = pick_root_object(mesh_objects)
    root.rotation_mode = "XYZ"
    base_z = root.rotation_euler.z + math.radians(face_offset_deg)

    camera_obj = ensure_camera(scene)
    base_camera_location = Vector(camera_obj.location)
    base_camera_rotation = tuple(camera_obj.rotation_euler)
    base_ortho = camera_obj.data.ortho_scale

    for name, angle_deg in directions.items():
        camera_obj.location = base_camera_location
        camera_obj.rotation_euler = base_camera_rotation
        camera_obj.data.ortho_scale = base_ortho
        root.rotation_euler.z = base_z + math.radians(angle_deg)
        bpy.context.view_layer.update()

        auto_frame_camera(scene, camera_obj, mesh_objects)

        out_path = out_dir / f"{output_stem}_{name}.png"
        save_depth_png(out_path, width, height, scene, camera_obj, mesh_objects)
        log(f"wrote {out_path}")


def main() -> None:
    args = parse_args()
    fbx_dir = Path(args.fbx_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    direction_names = [d.strip() for d in args.directions.split(",") if d.strip()]
    invalid = [d for d in direction_names if d not in SUPPORTED_DIRECTION_ANGLES]
    if invalid:
        raise RuntimeError(f"Unknown directions: {invalid}")
    directions = {d: SUPPORTED_DIRECTION_ANGLES[d] for d in direction_names}

    fbx_files = sorted(fbx_dir.glob(args.pattern))
    if not fbx_files:
        raise RuntimeError(f"No FBX files matched {args.pattern} in {fbx_dir}")

    for index, fbx_path in enumerate(fbx_files):
        output_stem = args.stem_format.format(stem=fbx_path.stem, index=index)
        log(f"processing {fbx_path.name} -> {output_stem}")
        render_fbx(fbx_path, directions, out_dir,
                   args.resolution_x, args.resolution_y, args.face_offset_deg,
                   output_stem)


if __name__ == "__main__":
    main()
