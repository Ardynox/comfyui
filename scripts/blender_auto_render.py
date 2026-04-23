"""Batch render 5 isometric directions from a loaded Blender scene.

Usage:
    blender --background path/to/scene.blend --python scripts/blender_auto_render.py -- \
        --body-type male_normal \
        --model-object CharacterRoot

    blender --background path/to/scene.blend --python scripts/blender_auto_render.py -- \
        --config D:/Godot/comfyui/scripts/render_config.json

Config file example:
{
  "body_type": "male_normal",
  "model_object": "CharacterRoot",
  "camera": "Camera",
  "view_layer": "ViewLayer",
  "output_root": "D:/Godot/comfyui/02_blender/renders",
  "directions": ["S", "SE", "E", "NE", "N"],
  "resolution_x": 768,
  "resolution_y": 1024,
  "engine": "BLENDER_EEVEE_NEXT",
  "invert_normal_y": false
}
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bpy


DEFAULT_DIRECTION_ANGLES = {
    "S": 0.0,
    "SE": -45.0,
    "E": -90.0,
    "NE": -135.0,
    "N": 180.0,
}

DEFAULT_RESOLUTION_X = 768
DEFAULT_RESOLUTION_Y = 1024
DEFAULT_ENGINE = "BLENDER_EEVEE_NEXT"
DEFAULT_VIEW_TRANSFORM = "Standard"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "02_blender" / "renders"
ENGINE_ALIASES = {
    "BLENDER_EEVEE": "BLENDER_EEVEE_NEXT",
    "EEVEE": "BLENDER_EEVEE_NEXT",
}


@dataclass
class ObjectRotationState:
    rotation_mode: str
    rotation_euler: tuple[float, float, float]
    rotation_quaternion: tuple[float, float, float, float] | None
    rotation_axis_angle: tuple[float, float, float, float] | None


@dataclass
class OutputNodes:
    beauty: bpy.types.CompositorNodeOutputFile
    depth: bpy.types.CompositorNodeOutputFile
    normal: bpy.types.CompositorNodeOutputFile


def log(message: str) -> None:
    print(f"[blender_auto_render] {message}")


def resolve_path(path_value: str) -> Path:
    if path_value.startswith("//"):
        return Path(bpy.path.abspath(path_value)).resolve()
    return Path(path_value).expanduser().resolve()


def blender_argv() -> list[str]:
    argv = list(bpy.app.argv)
    if "--" not in argv:
        return []
    return argv[argv.index("--") + 1 :]


def load_config(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {}

    config_path = resolve_path(path_value)
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise RuntimeError(f"Config must be a JSON object: {config_path}")

    return data


def parser() -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument("--config", help="Optional JSON config file.")
    arg_parser.add_argument("--body-type", dest="body_type")
    arg_parser.add_argument("--model-object", dest="model_object")
    arg_parser.add_argument("--camera")
    arg_parser.add_argument("--view-layer", dest="view_layer")
    arg_parser.add_argument("--output-root", dest="output_root")
    arg_parser.add_argument("--scene-file", dest="scene_file")
    arg_parser.add_argument("--directions", help="Comma-separated direction names.")
    arg_parser.add_argument("--resolution-x", dest="resolution_x", type=int)
    arg_parser.add_argument("--resolution-y", dest="resolution_y", type=int)
    arg_parser.add_argument("--engine")
    arg_parser.add_argument(
        "--invert-normal-y",
        dest="invert_normal_y",
        action="store_true",
        default=None,
        help="Invert the Y channel when exporting the normal pass.",
    )
    arg_parser.add_argument(
        "--no-invert-normal-y",
        dest="invert_normal_y",
        action="store_false",
        help="Keep the Y channel as-is when exporting the normal pass.",
    )
    return arg_parser


def merge_settings(cli_args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "body_type": config.get("body_type"),
        "model_object": config.get("model_object"),
        "camera": config.get("camera"),
        "view_layer": config.get("view_layer"),
        "output_root": config.get("output_root"),
        "scene_file": config.get("scene_file"),
        "directions": config.get("directions"),
        "resolution_x": config.get("resolution_x", DEFAULT_RESOLUTION_X),
        "resolution_y": config.get("resolution_y", DEFAULT_RESOLUTION_Y),
        "engine": config.get("engine", DEFAULT_ENGINE),
        "invert_normal_y": config.get("invert_normal_y", False),
    }

    for key, value in vars(cli_args).items():
        if key == "config" or value is None:
            continue
        merged[key] = value

    if not merged["body_type"]:
        raise RuntimeError("Missing required argument: --body-type or config.body_type")

    if not merged["model_object"]:
        raise RuntimeError("Missing required argument: --model-object or config.model_object")

    return merged


def resolve_scene(settings: dict[str, Any]) -> bpy.types.Scene:
    scene = bpy.context.scene
    if scene is None:
        raise RuntimeError("No active Blender scene is loaded.")

    expected_scene = settings.get("scene_file")
    if expected_scene:
        current_scene = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
        expected_path = resolve_path(expected_scene)
        if current_scene != expected_path:
            raise RuntimeError(
                "Loaded scene does not match --scene-file. "
                "Run Blender with the target .blend file, for example: "
                "blender --background path/to/scene.blend --python scripts/blender_auto_render.py -- ..."
            )

    return scene


def resolve_view_layer(scene: bpy.types.Scene, view_layer_name: str | None) -> bpy.types.ViewLayer:
    if view_layer_name:
        view_layer = scene.view_layers.get(view_layer_name)
        if view_layer is None:
            raise RuntimeError(f"View layer not found: {view_layer_name}")
        return view_layer

    return bpy.context.view_layer


def resolve_object(name: str) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise RuntimeError(f"Object not found: {name}")
    return obj


def resolve_camera(scene: bpy.types.Scene, camera_name: str | None) -> None:
    if not camera_name:
        if scene.camera is None:
            raise RuntimeError("Scene has no active camera. Provide --camera or set scene.camera.")
        return

    camera_obj = bpy.data.objects.get(camera_name)
    if camera_obj is None:
        raise RuntimeError(f"Camera not found: {camera_name}")
    scene.camera = camera_obj


def resolve_directions(value: Any) -> dict[str, float]:
    if value is None:
        return dict(DEFAULT_DIRECTION_ANGLES)

    if isinstance(value, str):
        names = [item.strip() for item in value.split(",") if item.strip()]
        invalid = [name for name in names if name not in DEFAULT_DIRECTION_ANGLES]
        if invalid:
            raise RuntimeError(f"Unsupported directions: {', '.join(invalid)}")
        return {name: DEFAULT_DIRECTION_ANGLES[name] for name in names}

    if isinstance(value, list):
        names = [str(name) for name in value]
        invalid = [name for name in names if name not in DEFAULT_DIRECTION_ANGLES]
        if invalid:
            raise RuntimeError(f"Unsupported directions: {', '.join(invalid)}")
        return {name: DEFAULT_DIRECTION_ANGLES[name] for name in names}

    if isinstance(value, dict):
        return {str(name): float(angle) for name, angle in value.items()}

    raise RuntimeError("directions must be a comma-separated string, list, or object.")


def normalize_engine(engine_name: str) -> str:
    return ENGINE_ALIASES.get(engine_name, engine_name)


def capture_rotation_state(obj: bpy.types.Object) -> ObjectRotationState:
    quaternion = tuple(obj.rotation_quaternion) if obj.rotation_mode == "QUATERNION" else None
    axis_angle = tuple(obj.rotation_axis_angle) if obj.rotation_mode == "AXIS_ANGLE" else None
    return ObjectRotationState(
        rotation_mode=obj.rotation_mode,
        rotation_euler=tuple(obj.rotation_euler),
        rotation_quaternion=quaternion,
        rotation_axis_angle=axis_angle,
    )


def restore_rotation_state(obj: bpy.types.Object, state: ObjectRotationState) -> None:
    obj.rotation_mode = state.rotation_mode
    if state.rotation_mode == "QUATERNION" and state.rotation_quaternion is not None:
        obj.rotation_quaternion = state.rotation_quaternion
    elif state.rotation_mode == "AXIS_ANGLE" and state.rotation_axis_angle is not None:
        obj.rotation_axis_angle = state.rotation_axis_angle
    else:
        obj.rotation_euler = state.rotation_euler


def configure_render(scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer, settings: dict[str, Any]) -> None:
    scene.render.engine = normalize_engine(settings["engine"])
    scene.render.film_transparent = True
    scene.render.use_file_extension = True
    scene.render.resolution_x = settings["resolution_x"]
    scene.render.resolution_y = settings["resolution_y"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.use_compositing = True
    scene.render.use_sequencer = False

    scene.view_settings.view_transform = DEFAULT_VIEW_TRANSFORM

    view_layer.use_pass_z = True
    view_layer.use_pass_normal = True


def make_output_dirs(output_root: str | None) -> dict[str, Path]:
    root = resolve_path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    dirs = {
        "beauty": root / "beauty",
        "depth": root / "depth",
        "normal": root / "normal",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def configure_file_output(node: bpy.types.CompositorNodeOutputFile, base_path: Path, color_mode: str) -> None:
    node.base_path = str(base_path)
    node.format.file_format = "PNG"
    node.format.color_mode = color_mode
    node.format.color_depth = "8"
    node.file_slots[0].use_node_format = True


def map_normal_channel(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    source_socket: bpy.types.NodeSocket,
    invert: bool,
    x_location: int,
    y_location: int,
) -> bpy.types.NodeSocket:
    current_socket = source_socket

    if invert:
        invert_node = nodes.new("CompositorNodeMath")
        invert_node.operation = "MULTIPLY"
        invert_node.inputs[1].default_value = -1.0
        invert_node.location = (x_location, y_location + 80)
        links.new(current_socket, invert_node.inputs[0])
        current_socket = invert_node.outputs[0]

    add_node = nodes.new("CompositorNodeMath")
    add_node.operation = "ADD"
    add_node.inputs[1].default_value = 1.0
    add_node.location = (x_location + 180, y_location)
    links.new(current_socket, add_node.inputs[0])

    multiply_node = nodes.new("CompositorNodeMath")
    multiply_node.operation = "MULTIPLY"
    multiply_node.inputs[1].default_value = 0.5
    multiply_node.location = (x_location + 360, y_location)
    links.new(add_node.outputs[0], multiply_node.inputs[0])

    return multiply_node.outputs[0]


def setup_compositor(
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    output_dirs: dict[str, Path],
    invert_normal_y: bool,
) -> OutputNodes:
    scene.use_nodes = True
    node_tree = scene.node_tree
    node_tree.nodes.clear()

    nodes = node_tree.nodes
    links = node_tree.links

    render_layers = nodes.new("CompositorNodeRLayers")
    render_layers.layer = view_layer.name
    render_layers.location = (-800, 0)

    composite = nodes.new("CompositorNodeComposite")
    composite.location = (600, 320)
    links.new(render_layers.outputs["Image"], composite.inputs["Image"])

    beauty_output = nodes.new("CompositorNodeOutputFile")
    beauty_output.label = "Beauty Output"
    beauty_output.location = (600, 120)
    configure_file_output(beauty_output, output_dirs["beauty"], "RGBA")
    links.new(render_layers.outputs["Image"], beauty_output.inputs[0])

    normalize = nodes.new("CompositorNodeNormalize")
    normalize.location = (-420, -200)
    links.new(render_layers.outputs["Depth"], normalize.inputs[0])

    depth_ramp = nodes.new("CompositorNodeValToRGB")
    depth_ramp.location = (-160, -200)
    depth_ramp.color_ramp.elements[0].position = 0.0
    depth_ramp.color_ramp.elements[0].color = (1.0, 1.0, 1.0, 1.0)
    depth_ramp.color_ramp.elements[1].position = 1.0
    depth_ramp.color_ramp.elements[1].color = (0.0, 0.0, 0.0, 1.0)
    links.new(normalize.outputs[0], depth_ramp.inputs[0])

    depth_output = nodes.new("CompositorNodeOutputFile")
    depth_output.label = "Depth Output"
    depth_output.location = (600, -120)
    configure_file_output(depth_output, output_dirs["depth"], "RGB")
    links.new(depth_ramp.outputs[0], depth_output.inputs[0])

    separate_xyz = nodes.new("CompositorNodeSeparateXYZ")
    separate_xyz.location = (-420, -520)
    links.new(render_layers.outputs["Normal"], separate_xyz.inputs[0])

    normal_x = map_normal_channel(nodes, links, separate_xyz.outputs["X"], False, -100, -700)
    normal_y = map_normal_channel(nodes, links, separate_xyz.outputs["Y"], invert_normal_y, -100, -520)
    normal_z = map_normal_channel(nodes, links, separate_xyz.outputs["Z"], False, -100, -340)

    alpha_value = nodes.new("CompositorNodeValue")
    alpha_value.outputs[0].default_value = 1.0
    alpha_value.location = (120, -760)

    combine_rgba = nodes.new("CompositorNodeCombRGBA")
    combine_rgba.location = (300, -520)
    links.new(normal_x, combine_rgba.inputs[0])
    links.new(normal_y, combine_rgba.inputs[1])
    links.new(normal_z, combine_rgba.inputs[2])
    links.new(alpha_value.outputs[0], combine_rgba.inputs[3])

    normal_output = nodes.new("CompositorNodeOutputFile")
    normal_output.label = "Normal Output"
    normal_output.location = (600, -420)
    configure_file_output(normal_output, output_dirs["normal"], "RGBA")
    links.new(combine_rgba.outputs[0], normal_output.inputs[0])

    return OutputNodes(beauty=beauty_output, depth=depth_output, normal=normal_output)


def clear_old_outputs(output_dirs: dict[str, Path], stem: str) -> None:
    patterns = (f"{stem}.png", f"{stem}_*.png", f"{stem}[0-9]*.png")
    for directory in output_dirs.values():
        removed: set[Path] = set()
        for pattern in patterns:
            for path in directory.glob(pattern):
                if path in removed or not path.is_file():
                    continue
                path.unlink()
                removed.add(path)


def assign_output_stems(nodes: OutputNodes, stem: str) -> None:
    nodes.beauty.file_slots[0].path = f"{stem}_"
    nodes.depth.file_slots[0].path = f"{stem}_"
    nodes.normal.file_slots[0].path = f"{stem}_"


def finalize_output(directory: Path, stem: str) -> Path:
    exact_path = directory / f"{stem}.png"
    candidates = sorted(
        {
            *directory.glob(f"{stem}_*.png"),
            *directory.glob(f"{stem}[0-9]*.png"),
        },
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )

    if exact_path.exists():
        return exact_path

    if not candidates:
        raise RuntimeError(f"Rendered file not found for {directory / stem}")

    candidates[0].replace(exact_path)
    return exact_path


def render_direction(
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    target_obj: bpy.types.Object,
    base_z_radians: float,
    direction_name: str,
    angle_degrees: float,
    body_type: str,
    nodes: OutputNodes,
    output_dirs: dict[str, Path],
) -> None:
    stem = f"{body_type}_{direction_name}"
    clear_old_outputs(output_dirs, stem)
    assign_output_stems(nodes, stem)

    target_obj.rotation_euler.z = base_z_radians + math.radians(angle_degrees)
    bpy.context.view_layer.update()

    log(f"Rendering {direction_name} at Z={angle_degrees:.1f} degrees")
    bpy.ops.render.render(write_still=False, use_viewport=False, scene=scene.name, layer=view_layer.name)

    for pass_name, directory in output_dirs.items():
        final_path = finalize_output(directory, stem)
        log(f"Saved {pass_name}: {final_path}")


def main() -> None:
    cli_args = parser().parse_args(blender_argv())
    config = load_config(cli_args.config)
    settings = merge_settings(cli_args, config)

    scene = resolve_scene(settings)
    view_layer = resolve_view_layer(scene, settings.get("view_layer"))
    target_obj = resolve_object(settings["model_object"])
    resolve_camera(scene, settings.get("camera"))

    direction_map = resolve_directions(settings.get("directions"))
    output_dirs = make_output_dirs(settings.get("output_root"))

    configure_render(scene, view_layer, settings)
    nodes = setup_compositor(scene, view_layer, output_dirs, bool(settings.get("invert_normal_y")))

    original_state = capture_rotation_state(target_obj)

    try:
        target_obj.rotation_mode = "XYZ"
        base_z_radians = target_obj.rotation_euler.z

        for direction_name, angle_degrees in direction_map.items():
            render_direction(
                scene=scene,
                view_layer=view_layer,
                target_obj=target_obj,
                base_z_radians=base_z_radians,
                direction_name=direction_name,
                angle_degrees=angle_degrees,
                body_type=settings["body_type"],
                nodes=nodes,
                output_dirs=output_dirs,
            )
    finally:
        restore_rotation_state(target_obj, original_state)
        bpy.context.view_layer.update()

    log("Batch render finished.")


if __name__ == "__main__":
    main()
