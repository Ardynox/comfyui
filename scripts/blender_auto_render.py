"""Batch render practical isometric directions from a loaded Blender scene.

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
  "pose_armature": "CMU compliant skeleton",
  "view_layer": "ViewLayer",
  "output_root": "D:/Godot/comfyui/02_blender/renders",
  "directions": ["S", "SE", "SW", "E", "NE"],
  "resolution_x": 768,
  "resolution_y": 1024,
  "engine": "BLENDER_EEVEE_NEXT",
  "ortho_scale": 42.999996,
  "invert_normal_y": false
}
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


DEFAULT_DIRECTIONS = ("S", "SE", "SW", "E", "NE")
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
DEFAULT_ENGINE = "BLENDER_EEVEE"
DEFAULT_VIEW_TRANSFORM = "Standard"
DEFAULT_CAMERA_ROTATION = (63.435, 0.0, 45.0)
DEFAULT_CAMERA_TYPE = "ORTHO"
DEFAULT_TARGET_WIDTH_FILL = 0.62
DEFAULT_TARGET_HEIGHT_FILL = 0.72
DEFAULT_FRAMING_MESH_RATIO = 0.08
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "02_blender" / "renders"
ENGINE_ALIASES = {
    "BLENDER_EEVEE_NEXT": "BLENDER_EEVEE",
    "EEVEE": "BLENDER_EEVEE",
}
POSE_BACKGROUND = (0.0, 0.0, 0.0, 1.0)
POSE_TORSO_COLOR = (0.0, 0.75, 1.0, 1.0)
POSE_RIGHT_COLOR = (1.0, 0.45, 0.0, 1.0)
POSE_LEFT_COLOR = (0.15, 1.0, 0.45, 1.0)
POSE_HEAD_COLOR = (1.0, 0.2, 0.85, 1.0)
POSE_JOINT_RADIUS = 9
POSE_LINE_RADIUS = 5
POSE_BONE_POINTS = {
    "head": ("Head", "tail"),
    "neck": ("Neck1", "head"),
    "right_shoulder": ("RightArm", "head"),
    "right_elbow": ("RightForeArm", "head"),
    "right_wrist": ("RightHand", "head"),
    "left_shoulder": ("LeftArm", "head"),
    "left_elbow": ("LeftForeArm", "head"),
    "left_wrist": ("LeftHand", "head"),
    "right_hip": ("RightUpLeg", "head"),
    "right_knee": ("RightLeg", "head"),
    "right_ankle": ("RightFoot", "head"),
    "left_hip": ("LeftUpLeg", "head"),
    "left_knee": ("LeftLeg", "head"),
    "left_ankle": ("LeftFoot", "head"),
}
POSE_CONNECTIONS = (
    ("head", "neck", POSE_HEAD_COLOR),
    ("neck", "right_shoulder", POSE_RIGHT_COLOR),
    ("right_shoulder", "right_elbow", POSE_RIGHT_COLOR),
    ("right_elbow", "right_wrist", POSE_RIGHT_COLOR),
    ("neck", "left_shoulder", POSE_LEFT_COLOR),
    ("left_shoulder", "left_elbow", POSE_LEFT_COLOR),
    ("left_elbow", "left_wrist", POSE_LEFT_COLOR),
    ("neck", "mid_hip", POSE_TORSO_COLOR),
    ("mid_hip", "right_hip", POSE_RIGHT_COLOR),
    ("right_hip", "right_knee", POSE_RIGHT_COLOR),
    ("right_knee", "right_ankle", POSE_RIGHT_COLOR),
    ("mid_hip", "left_hip", POSE_LEFT_COLOR),
    ("left_hip", "left_knee", POSE_LEFT_COLOR),
    ("left_knee", "left_ankle", POSE_LEFT_COLOR),
)


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


@dataclass
class CameraState:
    location: tuple[float, float, float]
    rotation_mode: str
    rotation_euler: tuple[float, float, float]
    rotation_quaternion: tuple[float, float, float, float] | None
    rotation_axis_angle: tuple[float, float, float, float] | None
    camera_type: str
    ortho_scale: float


def log(message: str) -> None:
    print(f"[blender_auto_render] {message}")


def resolve_path(path_value: str) -> Path:
    if path_value.startswith("//"):
        return Path(bpy.path.abspath(path_value)).resolve()
    return Path(path_value).expanduser().resolve()


def blender_argv() -> list[str]:
    argv = list(getattr(bpy.app, "argv", sys.argv))
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
    arg_parser.add_argument("--pose-armature", dest="pose_armature")
    arg_parser.add_argument("--view-layer", dest="view_layer")
    arg_parser.add_argument("--output-root", dest="output_root")
    arg_parser.add_argument("--scene-file", dest="scene_file")
    arg_parser.add_argument("--directions", help="Comma-separated direction names.")
    arg_parser.add_argument("--resolution-x", dest="resolution_x", type=int)
    arg_parser.add_argument("--resolution-y", dest="resolution_y", type=int)
    arg_parser.add_argument("--ortho-scale", dest="ortho_scale", type=float)
    arg_parser.add_argument("--target-width-fill", dest="target_width_fill", type=float)
    arg_parser.add_argument("--target-height-fill", dest="target_height_fill", type=float)
    arg_parser.add_argument("--framing-mesh-ratio", dest="framing_mesh_ratio", type=float)
    arg_parser.add_argument(
        "--auto-frame",
        dest="auto_frame",
        action="store_true",
        default=None,
        help="Automatically scale and center the orthographic camera to fit the character.",
    )
    arg_parser.add_argument(
        "--no-auto-frame",
        dest="auto_frame",
        action="store_false",
        help="Keep the configured orthographic camera framing as-is.",
    )
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
        "pose_armature": config.get("pose_armature"),
        "view_layer": config.get("view_layer"),
        "output_root": config.get("output_root"),
        "scene_file": config.get("scene_file"),
        "directions": config.get("directions"),
        "resolution_x": config.get("resolution_x", DEFAULT_RESOLUTION_X),
        "resolution_y": config.get("resolution_y", DEFAULT_RESOLUTION_Y),
        "ortho_scale": config.get("ortho_scale"),
        "target_width_fill": config.get("target_width_fill", DEFAULT_TARGET_WIDTH_FILL),
        "target_height_fill": config.get("target_height_fill", DEFAULT_TARGET_HEIGHT_FILL),
        "framing_mesh_ratio": config.get("framing_mesh_ratio", DEFAULT_FRAMING_MESH_RATIO),
        "auto_frame": config.get("auto_frame", True),
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


def resolve_camera(scene: bpy.types.Scene, camera_name: str | None) -> bpy.types.Object:
    if not camera_name:
        if scene.camera is None:
            raise RuntimeError("Scene has no active camera. Provide --camera or set scene.camera.")
        return scene.camera

    camera_obj = bpy.data.objects.get(camera_name)
    if camera_obj is None:
        raise RuntimeError(f"Camera not found: {camera_name}")
    scene.camera = camera_obj
    return camera_obj


def resolve_pose_armature(target_obj: bpy.types.Object, pose_armature_name: str | None) -> bpy.types.Object:
    if pose_armature_name:
        pose_armature = resolve_object(pose_armature_name)
        if pose_armature.type != "ARMATURE":
            raise RuntimeError(f"Pose armature must be an armature object: {pose_armature_name}")
        return pose_armature

    if target_obj.type == "ARMATURE":
        return target_obj

    if target_obj.parent is not None and target_obj.parent.type == "ARMATURE":
        return target_obj.parent

    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if len(armatures) == 1:
        return armatures[0]

    raise RuntimeError("Unable to infer pose armature. Provide --pose-armature.")


def resolve_directions(value: Any) -> dict[str, float]:
    if value is None:
        return {name: SUPPORTED_DIRECTION_ANGLES[name] for name in DEFAULT_DIRECTIONS}

    if isinstance(value, str):
        names = [item.strip() for item in value.split(",") if item.strip()]
        invalid = [name for name in names if name not in SUPPORTED_DIRECTION_ANGLES]
        if invalid:
            raise RuntimeError(f"Unsupported directions: {', '.join(invalid)}")
        return {name: SUPPORTED_DIRECTION_ANGLES[name] for name in names}

    if isinstance(value, list):
        names = [str(name) for name in value]
        invalid = [name for name in names if name not in SUPPORTED_DIRECTION_ANGLES]
        if invalid:
            raise RuntimeError(f"Unsupported directions: {', '.join(invalid)}")
        return {name: SUPPORTED_DIRECTION_ANGLES[name] for name in names}

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


def capture_camera_state(camera_obj: bpy.types.Object) -> CameraState:
    quaternion = tuple(camera_obj.rotation_quaternion) if camera_obj.rotation_mode == "QUATERNION" else None
    axis_angle = tuple(camera_obj.rotation_axis_angle) if camera_obj.rotation_mode == "AXIS_ANGLE" else None
    return CameraState(
        location=tuple(camera_obj.location),
        rotation_mode=camera_obj.rotation_mode,
        rotation_euler=tuple(camera_obj.rotation_euler),
        rotation_quaternion=quaternion,
        rotation_axis_angle=axis_angle,
        camera_type=camera_obj.data.type,
        ortho_scale=float(getattr(camera_obj.data, "ortho_scale", 0.0)),
    )


def restore_camera_state(camera_obj: bpy.types.Object, state: CameraState) -> None:
    camera_obj.location = state.location
    camera_obj.rotation_mode = state.rotation_mode
    if state.rotation_mode == "QUATERNION" and state.rotation_quaternion is not None:
        camera_obj.rotation_quaternion = state.rotation_quaternion
    elif state.rotation_mode == "AXIS_ANGLE" and state.rotation_axis_angle is not None:
        camera_obj.rotation_axis_angle = state.rotation_axis_angle
    else:
        camera_obj.rotation_euler = state.rotation_euler
    camera_obj.data.type = state.camera_type
    if hasattr(camera_obj.data, "ortho_scale"):
        camera_obj.data.ortho_scale = state.ortho_scale


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
    scene.render.use_compositing = False
    scene.render.use_sequencer = False

    scene.view_settings.view_transform = DEFAULT_VIEW_TRANSFORM

    view_layer.use_pass_z = True
    view_layer.use_pass_normal = True


def configure_camera(camera_obj: bpy.types.Object, ortho_scale: float | None) -> None:
    camera_obj.rotation_mode = "XYZ"
    camera_obj.rotation_euler = tuple(math.radians(value) for value in DEFAULT_CAMERA_ROTATION)
    camera_obj.data.type = DEFAULT_CAMERA_TYPE
    if ortho_scale is not None:
        camera_obj.data.ortho_scale = ortho_scale


def make_output_dirs(output_root: str | None) -> dict[str, Path]:
    root = resolve_path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    dirs = {
        "beauty": root / "beauty",
        "depth": root / "depth",
        "normal": root / "normal",
        "pose": root / "pose",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def configure_file_output(node: bpy.types.CompositorNodeOutputFile, base_path: Path, color_mode: str) -> None:
    if hasattr(node, "base_path"):
        node.base_path = str(base_path)
    else:
        node.directory = str(base_path)
    node.format.file_format = "PNG"
    node.format.color_mode = color_mode
    node.format.color_depth = "8"
    if hasattr(node, "file_slots"):
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
    node_tree = getattr(scene, "node_tree", None)
    if node_tree is None:
        node_tree = getattr(scene, "compositing_node_group", None)
    if node_tree is None:
        node_tree = bpy.data.node_groups.new(f"Compositor_{scene.name}", "CompositorNodeTree")
        scene.compositing_node_group = node_tree
    node_tree.nodes.clear()

    nodes = node_tree.nodes
    links = node_tree.links

    render_layers = nodes.new("CompositorNodeRLayers")
    render_layers.layer = view_layer.name
    render_layers.location = (-800, 0)

    beauty_output = nodes.new("CompositorNodeOutputFile")
    beauty_output.label = "Beauty Output"
    beauty_output.location = (600, 120)
    configure_file_output(beauty_output, output_dirs["beauty"], "RGBA")
    links.new(render_layers.outputs["Image"], beauty_output.inputs[0])

    normalize = nodes.new("CompositorNodeNormalize")
    normalize.location = (-420, -200)
    links.new(render_layers.outputs["Depth"], normalize.inputs[0])

    depth_ramp = nodes.new("ShaderNodeValToRGB")
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

    separate_xyz = nodes.new("ShaderNodeSeparateXYZ")
    separate_xyz.location = (-420, -520)
    links.new(render_layers.outputs["Normal"], separate_xyz.inputs[0])

    normal_x = map_normal_channel(nodes, links, separate_xyz.outputs["X"], False, -100, -700)
    normal_y = map_normal_channel(nodes, links, separate_xyz.outputs["Y"], invert_normal_y, -100, -520)
    normal_z = map_normal_channel(nodes, links, separate_xyz.outputs["Z"], False, -100, -340)

    alpha_value = nodes.new("CompositorNodeValue")
    alpha_value.outputs[0].default_value = 1.0
    alpha_value.location = (120, -760)

    combine_rgba = nodes.new("CompositorNodeCombineColor")
    combine_rgba.mode = "RGB"
    combine_rgba.location = (300, -520)
    links.new(normal_x, combine_rgba.inputs[0])
    links.new(normal_y, combine_rgba.inputs[1])
    links.new(normal_z, combine_rgba.inputs[2])
    links.new(alpha_value.outputs[0], combine_rgba.inputs[3])

    normal_output = nodes.new("CompositorNodeOutputFile")
    normal_output.label = "Normal Output"
    normal_output.location = (600, -420)
    configure_file_output(normal_output, output_dirs["normal"], "RGB")
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
    if hasattr(nodes.beauty, "file_slots"):
        nodes.beauty.file_slots[0].path = f"{stem}_"
        nodes.depth.file_slots[0].path = f"{stem}_"
        nodes.normal.file_slots[0].path = f"{stem}_"
        return

    nodes.beauty.file_name = stem
    nodes.depth.file_name = stem
    nodes.normal.file_name = stem


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


def iter_child_meshes(root_obj: bpy.types.Object) -> list[bpy.types.Object]:
    meshes: list[bpy.types.Object] = []
    stack = list(root_obj.children)
    while stack:
        current = stack.pop()
        stack.extend(current.children)
        if current.type == "MESH" and not current.hide_render:
            meshes.append(current)
    return meshes


def resolve_render_meshes(target_obj: bpy.types.Object) -> list[bpy.types.Object]:
    if target_obj.type == "MESH" and not target_obj.hide_render:
        return [target_obj]

    child_meshes = iter_child_meshes(target_obj)
    if child_meshes:
        return child_meshes

    visible_meshes = [obj for obj in bpy.data.objects if obj.type == "MESH" and not obj.hide_render]
    if visible_meshes:
        return visible_meshes

    raise RuntimeError("No renderable mesh objects found for depth/normal export.")


def select_framing_meshes(mesh_objects: list[bpy.types.Object], mesh_ratio: float) -> list[bpy.types.Object]:
    if not mesh_objects:
        raise RuntimeError("No mesh objects available for automatic camera framing.")

    max_extent = max(max(obj.dimensions) for obj in mesh_objects)
    threshold = max_extent * mesh_ratio
    framing_meshes = [obj for obj in mesh_objects if max(obj.dimensions) >= threshold]
    return framing_meshes or mesh_objects


def camera_local_bounds(
    camera_obj: bpy.types.Object,
    mesh_objects: list[bpy.types.Object],
) -> tuple[float, float, float, float]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    camera_inverse = camera_obj.matrix_world.inverted()
    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")

    for mesh_obj in mesh_objects:
        eval_obj = mesh_obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        try:
            for vertex in eval_mesh.vertices:
                local_point = camera_inverse @ (eval_obj.matrix_world @ vertex.co)
                min_x = min(min_x, local_point.x)
                max_x = max(max_x, local_point.x)
                min_y = min(min_y, local_point.y)
                max_y = max(max_y, local_point.y)
        finally:
            eval_obj.to_mesh_clear()

    if min_x == float("inf"):
        raise RuntimeError("Automatic camera framing failed because no visible mesh vertices were found.")

    return (min_x, max_x, min_y, max_y)


def projected_view_bounds(
    scene: bpy.types.Scene,
    camera_obj: bpy.types.Object,
    mesh_objects: list[bpy.types.Object],
) -> tuple[float, float, float, float]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    min_u = float("inf")
    max_u = float("-inf")
    min_v = float("inf")
    max_v = float("-inf")

    for mesh_obj in mesh_objects:
        eval_obj = mesh_obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        try:
            for vertex in eval_mesh.vertices:
                projected = world_to_camera_view(scene, camera_obj, eval_obj.matrix_world @ vertex.co)
                if projected.z < 0.0:
                    continue
                min_u = min(min_u, projected.x)
                max_u = max(max_u, projected.x)
                min_v = min(min_v, projected.y)
                max_v = max(max_v, projected.y)
        finally:
            eval_obj.to_mesh_clear()

    if min_u == float("inf"):
        raise RuntimeError("Automatic camera framing failed because no projected mesh vertices were found.")

    return (min_u, max_u, min_v, max_v)


def auto_frame_camera(
    scene: bpy.types.Scene,
    camera_obj: bpy.types.Object,
    mesh_objects: list[bpy.types.Object],
    target_width_fill: float,
    target_height_fill: float,
    framing_mesh_ratio: float,
) -> None:
    framing_meshes = select_framing_meshes(mesh_objects, framing_mesh_ratio)
    min_x, max_x, min_y, max_y = camera_local_bounds(camera_obj, framing_meshes)

    bbox_center_x = (min_x + max_x) * 0.5
    bbox_center_y = (min_y + max_y) * 0.5

    camera_rotation = camera_obj.matrix_world.to_quaternion()
    camera_obj.location = camera_obj.location + camera_rotation @ Vector((bbox_center_x, bbox_center_y, 0.0))
    bpy.context.view_layer.update()

    min_u, max_u, min_v, max_v = projected_view_bounds(scene, camera_obj, framing_meshes)
    fill_width = max_u - min_u
    fill_height = max_v - min_v
    scale_factor = max(
        fill_width / max(target_width_fill, 1e-6),
        fill_height / max(target_height_fill, 1e-6),
        1e-6,
    )
    camera_obj.data.ortho_scale = max(camera_obj.data.ortho_scale * scale_factor, 1e-6)
    bpy.context.view_layer.update()

    final_min_u, final_max_u, final_min_v, final_max_v = projected_view_bounds(scene, camera_obj, framing_meshes)
    final_fill_width = final_max_u - final_min_u
    final_fill_height = final_max_v - final_min_v
    log(
        "Auto-framed camera: "
        f"ortho_scale={camera_obj.data.ortho_scale:.4f}, "
        f"fill_width={final_fill_width:.3f}, "
        f"fill_height={final_fill_height:.3f}, "
        f"framing_meshes={len(framing_meshes)}"
    )

    bpy.context.view_layer.update()


def project_point_to_screen(
    scene: bpy.types.Scene,
    camera_obj: bpy.types.Object,
    world_point: bpy.types.Vector,
    width: int,
    height: int,
) -> tuple[float, float, float]:
    projected = world_to_camera_view(scene, camera_obj, world_point)
    camera_space_point = camera_obj.matrix_world.inverted() @ world_point
    x = projected.x * (width - 1)
    y = projected.y * (height - 1)
    depth = -camera_space_point.z
    return (x, y, depth)


def edge_function(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (cx - ax) * (by - ay) - (cy - ay) * (bx - ax)


def save_image_pixels(path: Path, width: int, height: int, pixels: array, image_name: str) -> None:
    image = bpy.data.images.new(image_name, width=width, height=height, alpha=True)
    image.alpha_mode = "STRAIGHT"
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.pixels.foreach_set(pixels)
    image.save()
    bpy.data.images.remove(image)


def save_depth_and_normal_maps(
    scene: bpy.types.Scene,
    camera_obj: bpy.types.Object,
    mesh_objects: list[bpy.types.Object],
    depth_path: Path,
    normal_path: Path,
    invert_normal_y: bool,
) -> None:
    width = scene.render.resolution_x
    height = scene.render.resolution_y
    depth_buffer = [float("inf")] * (width * height)
    normal_buffer = array("f", [0.0]) * (width * height * 4)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    camera_rotation = camera_obj.matrix_world.to_quaternion().inverted()

    for pixel_index in range(width * height):
        normal_buffer[pixel_index * 4 + 3] = 1.0

    for mesh_obj in mesh_objects:
        eval_obj = mesh_obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        try:
            eval_mesh.calc_loop_triangles()
            world_matrix = eval_obj.matrix_world
            normal_matrix = world_matrix.to_3x3()

            projected_vertices = [
                project_point_to_screen(scene, camera_obj, world_matrix @ vertex.co, width, height)
                for vertex in eval_mesh.vertices
            ]

            for triangle in eval_mesh.loop_triangles:
                vertex_ids = triangle.vertices
                vertices = [projected_vertices[index] for index in vertex_ids]

                if all(vertex[2] <= 0.0 for vertex in vertices):
                    continue

                x0, y0, z0 = vertices[0]
                x1, y1, z1 = vertices[1]
                x2, y2, z2 = vertices[2]

                min_x = max(int(math.floor(min(x0, x1, x2))), 0)
                max_x = min(int(math.ceil(max(x0, x1, x2))), width - 1)
                min_y = max(int(math.floor(min(y0, y1, y2))), 0)
                max_y = min(int(math.ceil(max(y0, y1, y2))), height - 1)

                if min_x > max_x or min_y > max_y:
                    continue

                area = edge_function(x0, y0, x1, y1, x2, y2)
                if abs(area) <= 1e-8:
                    continue

                camera_normal = (camera_rotation @ (normal_matrix @ triangle.normal)).normalized()
                if invert_normal_y:
                    camera_normal.y *= -1.0
                normal_color = (
                    camera_normal.x * 0.5 + 0.5,
                    camera_normal.y * 0.5 + 0.5,
                    camera_normal.z * 0.5 + 0.5,
                    1.0,
                )

                for pixel_y in range(min_y, max_y + 1):
                    sample_y = pixel_y + 0.5
                    for pixel_x in range(min_x, max_x + 1):
                        sample_x = pixel_x + 0.5
                        w0 = edge_function(x1, y1, x2, y2, sample_x, sample_y)
                        w1 = edge_function(x2, y2, x0, y0, sample_x, sample_y)
                        w2 = edge_function(x0, y0, x1, y1, sample_x, sample_y)

                        if area > 0.0:
                            inside = w0 >= 0.0 and w1 >= 0.0 and w2 >= 0.0
                        else:
                            inside = w0 <= 0.0 and w1 <= 0.0 and w2 <= 0.0
                        if not inside:
                            continue

                        barycentric_0 = w0 / area
                        barycentric_1 = w1 / area
                        barycentric_2 = w2 / area
                        depth = (
                            barycentric_0 * z0
                            + barycentric_1 * z1
                            + barycentric_2 * z2
                        )

                        buffer_index = pixel_y * width + pixel_x
                        if depth <= 0.0 or depth >= depth_buffer[buffer_index]:
                            continue

                        depth_buffer[buffer_index] = depth
                        pixel_base = buffer_index * 4
                        normal_buffer[pixel_base + 0] = normal_color[0]
                        normal_buffer[pixel_base + 1] = normal_color[1]
                        normal_buffer[pixel_base + 2] = normal_color[2]
                        normal_buffer[pixel_base + 3] = normal_color[3]
        finally:
            eval_obj.to_mesh_clear()

    visible_depths = [depth for depth in depth_buffer if depth != float("inf")]
    if not visible_depths:
        raise RuntimeError("Depth export failed because no visible geometry was projected.")

    min_depth = min(visible_depths)
    max_depth = max(visible_depths)
    depth_pixels = array("f", [0.0]) * (width * height * 4)

    for pixel_index, depth in enumerate(depth_buffer):
        base = pixel_index * 4
        depth_pixels[base + 3] = 1.0
        if depth == float("inf"):
            continue
        if max_depth - min_depth <= 1e-8:
            intensity = 1.0
        else:
            intensity = 1.0 - ((depth - min_depth) / (max_depth - min_depth))
        depth_pixels[base + 0] = intensity
        depth_pixels[base + 1] = intensity
        depth_pixels[base + 2] = intensity

    save_image_pixels(depth_path, width, height, depth_pixels, f"depth_map_{depth_path.stem}")
    save_image_pixels(normal_path, width, height, normal_buffer, f"normal_map_{normal_path.stem}")


def bone_world_position(armature_obj: bpy.types.Object, bone_name: str, endpoint: str) -> bpy.types.Vector:
    pose_bone = armature_obj.pose.bones.get(bone_name)
    if pose_bone is None:
        raise RuntimeError(f"Bone not found on pose armature: {bone_name}")
    point = pose_bone.head if endpoint == "head" else pose_bone.tail
    return armature_obj.matrix_world @ point


def midpoint(a: bpy.types.Vector, b: bpy.types.Vector) -> bpy.types.Vector:
    return (a + b) * 0.5


def gather_pose_points(armature_obj: bpy.types.Object) -> dict[str, bpy.types.Vector]:
    points = {
        key: bone_world_position(armature_obj, bone_name, endpoint)
        for key, (bone_name, endpoint) in POSE_BONE_POINTS.items()
    }
    points["mid_hip"] = midpoint(points["left_hip"], points["right_hip"])
    points["neck"] = midpoint(points["left_shoulder"], points["right_shoulder"])
    return points


def project_point_to_pixel(
    scene: bpy.types.Scene,
    camera_obj: bpy.types.Object,
    point: bpy.types.Vector,
    width: int,
    height: int,
) -> tuple[int, int] | None:
    projected = world_to_camera_view(scene, camera_obj, point)
    if projected.z < 0.0:
        return None
    x = int(round(projected.x * (width - 1)))
    y = int(round(projected.y * (height - 1)))
    return (x, y)


def new_pose_buffer(width: int, height: int) -> array:
    pixels = array("f", [0.0]) * (width * height * 4)
    for pixel_index in range(width * height):
        base = pixel_index * 4
        pixels[base + 0] = POSE_BACKGROUND[0]
        pixels[base + 1] = POSE_BACKGROUND[1]
        pixels[base + 2] = POSE_BACKGROUND[2]
        pixels[base + 3] = POSE_BACKGROUND[3]
    return pixels


def write_pixel(pixels: array, width: int, height: int, x: int, y: int, color: tuple[float, float, float, float]) -> None:
    if x < 0 or x >= width or y < 0 or y >= height:
        return
    base = (y * width + x) * 4
    pixels[base + 0] = color[0]
    pixels[base + 1] = color[1]
    pixels[base + 2] = color[2]
    pixels[base + 3] = color[3]


def draw_disk(
    pixels: array,
    width: int,
    height: int,
    center_x: int,
    center_y: int,
    radius: int,
    color: tuple[float, float, float, float],
) -> None:
    radius_squared = radius * radius
    for y in range(center_y - radius, center_y + radius + 1):
        for x in range(center_x - radius, center_x + radius + 1):
            if (x - center_x) * (x - center_x) + (y - center_y) * (y - center_y) <= radius_squared:
                write_pixel(pixels, width, height, x, y, color)


def draw_line(
    pixels: array,
    width: int,
    height: int,
    start: tuple[int, int],
    end: tuple[int, int],
    radius: int,
    color: tuple[float, float, float, float],
) -> None:
    x0, y0 = start
    x1, y1 = end
    steps = max(abs(x1 - x0), abs(y1 - y0))
    if steps == 0:
        draw_disk(pixels, width, height, x0, y0, radius, color)
        return

    for step in range(steps + 1):
        factor = step / steps
        x = int(round(x0 + (x1 - x0) * factor))
        y = int(round(y0 + (y1 - y0) * factor))
        draw_disk(pixels, width, height, x, y, radius, color)


def save_pose_map(
    scene: bpy.types.Scene,
    camera_obj: bpy.types.Object,
    pose_armature: bpy.types.Object,
    output_path: Path,
    width: int,
    height: int,
    image_name: str,
) -> None:
    points = gather_pose_points(pose_armature)
    projected_points = {
        key: project_point_to_pixel(scene, camera_obj, point, width, height)
        for key, point in points.items()
    }
    pixels = new_pose_buffer(width, height)

    for start_name, end_name, color in POSE_CONNECTIONS:
        start = projected_points.get(start_name)
        end = projected_points.get(end_name)
        if start is None or end is None:
            continue
        draw_line(pixels, width, height, start, end, POSE_LINE_RADIUS, color)

    for point_name, point in projected_points.items():
        if point is None:
            continue
        color = POSE_HEAD_COLOR if point_name == "head" else (1.0, 1.0, 1.0, 1.0)
        draw_disk(pixels, width, height, point[0], point[1], POSE_JOINT_RADIUS, color)

    image = bpy.data.images.new(image_name, width=width, height=height, alpha=True)
    image.alpha_mode = "STRAIGHT"
    image.filepath_raw = str(output_path)
    image.file_format = "PNG"
    image.pixels.foreach_set(pixels)
    image.save()
    bpy.data.images.remove(image)


def render_direction(
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    target_obj: bpy.types.Object,
    camera_obj: bpy.types.Object,
    baseline_camera_state: CameraState,
    pose_armature: bpy.types.Object,
    mesh_objects: list[bpy.types.Object],
    base_z_radians: float,
    direction_name: str,
    angle_degrees: float,
    body_type: str,
    output_dirs: dict[str, Path],
    auto_frame: bool,
    target_width_fill: float,
    target_height_fill: float,
    framing_mesh_ratio: float,
    invert_normal_y: bool,
) -> None:
    stem = f"{body_type}_{direction_name}"
    clear_old_outputs(output_dirs, stem)

    restore_camera_state(camera_obj, baseline_camera_state)
    target_obj.rotation_euler.z = base_z_radians + math.radians(angle_degrees)
    bpy.context.view_layer.update()

    if auto_frame:
        auto_frame_camera(
            scene=scene,
            camera_obj=camera_obj,
            mesh_objects=mesh_objects,
            target_width_fill=target_width_fill,
            target_height_fill=target_height_fill,
            framing_mesh_ratio=framing_mesh_ratio,
        )

    log(f"Rendering {direction_name} at Z={angle_degrees:.1f} degrees")
    beauty_path = output_dirs["beauty"] / f"{stem}.png"
    scene.render.filepath = str(beauty_path)
    bpy.ops.render.render(write_still=True, use_viewport=False, scene=scene.name, layer=view_layer.name)
    log(f"Saved beauty: {beauty_path}")

    depth_path = output_dirs["depth"] / f"{stem}.png"
    normal_path = output_dirs["normal"] / f"{stem}.png"
    save_depth_and_normal_maps(
        scene=scene,
        camera_obj=camera_obj,
        mesh_objects=mesh_objects,
        depth_path=depth_path,
        normal_path=normal_path,
        invert_normal_y=invert_normal_y,
    )
    log(f"Saved depth: {depth_path}")
    log(f"Saved normal: {normal_path}")

    pose_path = output_dirs["pose"] / f"{stem}.png"
    save_pose_map(
        scene=scene,
        camera_obj=camera_obj,
        pose_armature=pose_armature,
        output_path=pose_path,
        width=scene.render.resolution_x,
        height=scene.render.resolution_y,
        image_name=f"pose_map_{stem}",
    )
    log(f"Saved pose: {pose_path}")


def main() -> None:
    cli_args = parser().parse_args(blender_argv())
    config = load_config(cli_args.config)
    settings = merge_settings(cli_args, config)

    scene = resolve_scene(settings)
    view_layer = resolve_view_layer(scene, settings.get("view_layer"))
    target_obj = resolve_object(settings["model_object"])
    camera_obj = resolve_camera(scene, settings.get("camera"))
    pose_armature = resolve_pose_armature(target_obj, settings.get("pose_armature"))
    mesh_objects = resolve_render_meshes(target_obj)

    direction_map = resolve_directions(settings.get("directions"))
    output_dirs = make_output_dirs(settings.get("output_root"))

    configure_render(scene, view_layer, settings)
    original_camera_state = capture_camera_state(camera_obj)
    configure_camera(camera_obj, settings.get("ortho_scale"))
    bpy.context.view_layer.update()
    configured_camera_state = capture_camera_state(camera_obj)

    original_state = capture_rotation_state(target_obj)

    try:
        target_obj.rotation_mode = "XYZ"
        base_z_radians = target_obj.rotation_euler.z

        for direction_name, angle_degrees in direction_map.items():
            render_direction(
                scene=scene,
                view_layer=view_layer,
                target_obj=target_obj,
                camera_obj=camera_obj,
                baseline_camera_state=configured_camera_state,
                pose_armature=pose_armature,
                mesh_objects=mesh_objects,
                base_z_radians=base_z_radians,
                direction_name=direction_name,
                angle_degrees=angle_degrees,
                body_type=settings["body_type"],
                output_dirs=output_dirs,
                auto_frame=bool(settings.get("auto_frame", True)),
                target_width_fill=float(settings.get("target_width_fill", DEFAULT_TARGET_WIDTH_FILL)),
                target_height_fill=float(settings.get("target_height_fill", DEFAULT_TARGET_HEIGHT_FILL)),
                framing_mesh_ratio=float(settings.get("framing_mesh_ratio", DEFAULT_FRAMING_MESH_RATIO)),
                invert_normal_y=bool(settings.get("invert_normal_y")),
            )
    finally:
        restore_rotation_state(target_obj, original_state)
        restore_camera_state(camera_obj, original_camera_state)
        bpy.context.view_layer.update()

    log("Batch render finished.")


if __name__ == "__main__":
    main()
