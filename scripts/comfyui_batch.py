"""Batch-generate directional character renders through the ComfyUI HTTP API.

Usage:
    python scripts/comfyui_batch.py ^
        --workflow 00_workflows/char_5direction_v1.json ^
        --body-type male_normal ^
        --reference-image 03_comfyui_input/reference.png

Optional:
    --directions S SE E
    --directions S,SE,E
    --comfyui-root C:\\Users\\12536\\Documents\\ComfyUI
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_API_URL = "http://127.0.0.1:8188"
DEFAULT_COMFYUI_ROOT = Path(r"C:\Users\12536\Documents\ComfyUI")
DEFAULT_DIRECTIONS = ("S", "SE", "E", "NE", "N")
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_POLL_INTERVAL = 1.0

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RENDER_ROOT = PROJECT_ROOT / "02_blender" / "renders"
RAW_OUTPUT_ROOT = PROJECT_ROOT / "04_comfyui_output" / "raw"

EXPECTED_MODELS = {
    "checkpoint": ("checkpoints", "meinamix_v12Final.safetensors"),
    "clip_vision": ("clip_vision", "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"),
    "ipadapter": ("ipadapter", "ip-adapter-plus_sd15.safetensors"),
    "controlnet_depth": ("controlnet", "control_v11f1p_sd15_depth.pth"),
    "controlnet_pose": ("controlnet", "control_v11p_sd15_openpose.pth"),
    "controlnet_normal": ("controlnet", "control_v11p_sd15_normalbae.pth"),
}

UI_WIDGET_FIELDS: dict[str, tuple[str | None, ...]] = {
    "CheckpointLoaderSimple": ("ckpt_name",),
    "CLIPTextEncode": ("text",),
    "EmptyLatentImage": ("width", "height", "batch_size"),
    "LoadImage": ("image", None),
    "ControlNetLoader": ("control_net_name",),
    "ControlNetApplyAdvanced": ("strength", "start_percent", "end_percent"),
    "CLIPVisionLoader": ("clip_name",),
    "IPAdapterModelLoader": ("ipadapter_file",),
    "IPAdapterAdvanced": (
        "weight",
        "weight_type",
        "combine_embeds",
        "start_at",
        "end_at",
        "embeds_scaling",
    ),
    "KSampler": ("seed", None, "steps", "cfg", "sampler_name", "scheduler", "denoise"),
    "VAEDecode": (),
    "PreviewImage": (),
    "SaveImage": ("filename_prefix",),
}


@dataclass(frozen=True)
class DirectionAssets:
    reference_src: Path
    depth_src: Path
    pose_src: Path
    normal_src: Path
    reference_name: str
    depth_name: str
    pose_name: str
    normal_name: str
    final_output: Path


def log(message: str) -> None:
    print(f"[comfyui_batch] {message}")


def sanitize_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def resolve_path(path_value: str | Path) -> Path:
    return Path(path_value).expanduser().resolve()


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise RuntimeError(f"{label} not found: {path}")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", required=True, help="Path to a ComfyUI workflow JSON file.")
    parser.add_argument("--body-type", required=True, help="Body type such as male_normal.")
    parser.add_argument("--reference-image", required=True, help="IPAdapter reference image.")
    parser.add_argument(
        "--directions",
        nargs="*",
        help="Directions to generate. Supports 'S SE E' or 'S,SE,E'. Defaults to all 5.",
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="ComfyUI HTTP API base URL.")
    parser.add_argument(
        "--comfyui-root",
        default=str(DEFAULT_COMFYUI_ROOT),
        help="ComfyUI portable root that contains input/, output/, and models/.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-direction timeout while waiting for ComfyUI history output.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help="Seconds between history polls.",
    )
    return parser.parse_args()


def parse_directions(raw_values: list[str] | None) -> list[str]:
    if not raw_values:
        return list(DEFAULT_DIRECTIONS)

    parsed: list[str] = []
    for raw_value in raw_values:
        for part in raw_value.split(","):
            direction = part.strip().upper()
            if not direction:
                continue
            if direction not in DEFAULT_DIRECTIONS:
                raise RuntimeError(f"Unsupported direction: {direction}")
            if direction not in parsed:
                parsed.append(direction)

    if not parsed:
        raise RuntimeError("No valid directions were provided.")

    return parsed


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def request_json(url: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset("utf-8")
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc.reason}") from exc


def ensure_server(api_url: str) -> None:
    request_json(f"{api_url.rstrip('/')}/queue")


def resolve_installed_models(comfyui_root: Path) -> dict[str, str]:
    resolved: dict[str, str] = {}
    models_root = comfyui_root / "models"
    for key, (subdir, filename) in EXPECTED_MODELS.items():
        model_path = models_root / subdir / filename
        if not model_path.is_file():
            raise RuntimeError(f"Required model not found: {model_path}")
        resolved[key] = filename
    return resolved


def direction_assets(body_type: str, direction: str, reference_image: Path) -> DirectionAssets:
    stem = f"{body_type}_{direction}"
    safe_stem = sanitize_name(stem)
    reference_suffix = reference_image.suffix.lower() or ".png"

    depth_src = require_file(RENDER_ROOT / "depth" / f"{stem}.png", f"Depth map for {stem}")
    pose_src = require_file(RENDER_ROOT / "pose" / f"{stem}.png", f"Pose map for {stem}")
    normal_src = require_file(RENDER_ROOT / "normal" / f"{stem}.png", f"Normal map for {stem}")
    reference_src = require_file(reference_image, "Reference image")
    final_output = RAW_OUTPUT_ROOT / f"{stem}.png"

    return DirectionAssets(
        reference_src=reference_src,
        depth_src=depth_src,
        pose_src=pose_src,
        normal_src=normal_src,
        reference_name=f"{safe_stem}_reference{reference_suffix}",
        depth_name=f"{safe_stem}_depth.png",
        pose_name=f"{safe_stem}_pose.png",
        normal_name=f"{safe_stem}_normal.png",
        final_output=final_output,
    )


def stage_input_file(source: Path, input_dir: Path, target_name: str) -> str:
    input_dir.mkdir(parents=True, exist_ok=True)
    target_path = input_dir / target_name
    if source.resolve() != target_path.resolve():
        shutil.copy2(source, target_path)
    return target_name


def stage_inputs(assets: DirectionAssets, comfyui_root: Path) -> dict[str, str]:
    input_dir = comfyui_root / "input"
    return {
        "reference": stage_input_file(assets.reference_src, input_dir, assets.reference_name),
        "depth": stage_input_file(assets.depth_src, input_dir, assets.depth_name),
        "pose": stage_input_file(assets.pose_src, input_dir, assets.pose_name),
        "normal": stage_input_file(assets.normal_src, input_dir, assets.normal_name),
    }


def build_link_lookup(workflow: dict[str, Any]) -> dict[int, tuple[int, int]]:
    lookup: dict[int, tuple[int, int]] = {}
    for link in workflow.get("links", []):
        link_id = int(link[0])
        source_node_id = int(link[1])
        source_slot = int(link[2])
        lookup[link_id] = (source_node_id, source_slot)
    return lookup


def patch_load_image_nodes(nodes: list[dict[str, Any]], staged_inputs: dict[str, str]) -> None:
    placeholder_map = {
        "beauty_ref": "reference",
        "depth_map": "depth",
        "pose_map": "pose",
        "normal_map": "normal",
    }

    assigned: set[int] = set()
    by_role: dict[str, dict[str, Any]] = {}

    for node in nodes:
        if node.get("type") != "LoadImage":
            continue
        widget_values = node.setdefault("widgets_values", [])
        current_name = str(widget_values[0]).lower() if widget_values else ""
        for placeholder, role in placeholder_map.items():
            if placeholder in current_name and role not in by_role:
                by_role[role] = node
                assigned.add(int(node["id"]))
                break

    fallback_roles = ("reference", "depth", "pose", "normal")
    unassigned_nodes = [node for node in nodes if node.get("type") == "LoadImage" and int(node["id"]) not in assigned]
    unassigned_nodes.sort(key=lambda item: int(item["id"]))

    for role in fallback_roles:
        if role in by_role:
            continue
        if not unassigned_nodes:
            raise RuntimeError(f"Workflow is missing a LoadImage node for {role}.")
        by_role[role] = unassigned_nodes.pop(0)

    for role, node in by_role.items():
        widget_values = node.setdefault("widgets_values", [])
        if not widget_values:
            widget_values.append(staged_inputs[role])
        else:
            widget_values[0] = staged_inputs[role]


def patch_controlnet_loader_nodes(nodes: list[dict[str, Any]], installed_models: dict[str, str]) -> None:
    role_to_model = {
        "depth": installed_models["controlnet_depth"],
        "pose": installed_models["controlnet_pose"],
        "normal": installed_models["controlnet_normal"],
    }

    by_role: dict[str, dict[str, Any]] = {}
    assigned: set[int] = set()

    for node in nodes:
        if node.get("type") != "ControlNetLoader":
            continue
        widget_values = node.setdefault("widgets_values", [])
        current_name = str(widget_values[0]).lower() if widget_values else ""
        for role in ("depth", "pose", "normal"):
            if role in current_name and role not in by_role:
                by_role[role] = node
                assigned.add(int(node["id"]))
                break

    unassigned_nodes = [node for node in nodes if node.get("type") == "ControlNetLoader" and int(node["id"]) not in assigned]
    unassigned_nodes.sort(key=lambda item: int(item["id"]))

    for role in ("depth", "pose", "normal"):
        if role in by_role:
            continue
        if not unassigned_nodes:
            raise RuntimeError(f"Workflow is missing a ControlNetLoader node for {role}.")
        by_role[role] = unassigned_nodes.pop(0)

    for role, node in by_role.items():
        widget_values = node.setdefault("widgets_values", [])
        if not widget_values:
            widget_values.append(role_to_model[role])
        else:
            widget_values[0] = role_to_model[role]


def patch_workflow_ui(
    workflow: dict[str, Any],
    body_type: str,
    direction: str,
    staged_inputs: dict[str, str],
    installed_models: dict[str, str],
) -> tuple[dict[str, Any], str]:
    patched = copy.deepcopy(workflow)
    nodes = patched.get("nodes")
    if not isinstance(nodes, list):
        raise RuntimeError("Workflow JSON is missing the top-level 'nodes' list.")

    patch_load_image_nodes(nodes, staged_inputs)
    patch_controlnet_loader_nodes(nodes, installed_models)

    save_node_id: str | None = None
    safe_prefix = sanitize_name(f"{body_type}_{direction}")

    for node in nodes:
        node_type = node.get("type")
        widget_values = node.setdefault("widgets_values", [])

        if node_type == "CheckpointLoaderSimple":
            if not widget_values:
                widget_values.append(installed_models["checkpoint"])
            else:
                widget_values[0] = installed_models["checkpoint"]
        elif node_type == "CLIPVisionLoader":
            if not widget_values:
                widget_values.append(installed_models["clip_vision"])
            else:
                widget_values[0] = installed_models["clip_vision"]
        elif node_type == "IPAdapterModelLoader":
            if not widget_values:
                widget_values.append(installed_models["ipadapter"])
            else:
                widget_values[0] = installed_models["ipadapter"]
        elif node_type == "SaveImage":
            if not widget_values:
                widget_values.append(safe_prefix)
            else:
                widget_values[0] = safe_prefix
            save_node_id = str(node["id"])

    if save_node_id is None:
        raise RuntimeError("Workflow does not contain a SaveImage node.")

    return patched, save_node_id


def widget_inputs_for_node(node: dict[str, Any]) -> dict[str, Any]:
    node_type = str(node.get("type"))
    if node_type not in UI_WIDGET_FIELDS:
        raise RuntimeError(
            f"Unsupported node type '{node_type}' in UI workflow. "
            "Extend UI_WIDGET_FIELDS in scripts/comfyui_batch.py for this node."
        )

    widget_values = list(node.get("widgets_values") or [])
    field_names = UI_WIDGET_FIELDS[node_type]
    inputs: dict[str, Any] = {}

    for index, field_name in enumerate(field_names):
        if field_name is None or index >= len(widget_values):
            continue
        inputs[field_name] = widget_values[index]

    return inputs


def ui_workflow_to_prompt(workflow: dict[str, Any]) -> dict[str, Any]:
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        raise RuntimeError("Workflow JSON is missing the top-level 'nodes' list.")

    link_lookup = build_link_lookup(workflow)
    prompt: dict[str, Any] = {}

    sorted_nodes = sorted(nodes, key=lambda item: (int(item.get("order", 0)), int(item["id"])))
    for node in sorted_nodes:
        node_id = str(node["id"])
        node_inputs = widget_inputs_for_node(node)

        for input_socket in node.get("inputs", []):
            link_id = input_socket.get("link")
            if link_id is None:
                continue
            source_node_id, source_slot = link_lookup[int(link_id)]
            node_inputs[input_socket["name"]] = [str(source_node_id), int(source_slot)]

        prompt[node_id] = {
            "class_type": node["type"],
            "inputs": node_inputs,
        }

    return prompt


def submit_prompt(api_url: str, prompt: dict[str, Any]) -> str:
    payload = {
        "prompt": prompt,
        "client_id": f"comfyui_batch_{uuid.uuid4().hex}",
    }
    response = request_json(f"{api_url.rstrip('/')}/prompt", payload=payload)
    prompt_id = response.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return a prompt_id: {response}")
    return str(prompt_id)


def wait_for_history(api_url: str, prompt_id: str, timeout_seconds: int, poll_interval: float) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_seconds
    history_url = f"{api_url.rstrip('/')}/history/{urllib.parse.quote(prompt_id)}"

    while time.perf_counter() < deadline:
        history_response = request_json(history_url)
        prompt_history = history_response.get(prompt_id)
        if prompt_history:
            status = prompt_history.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI prompt failed: {status}")
            if status.get("completed") or prompt_history.get("outputs"):
                return prompt_history
        time.sleep(poll_interval)

    raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id} after {timeout_seconds} seconds.")


def resolve_history_image_path(comfyui_root: Path, image_info: dict[str, Any]) -> Path:
    image_type = str(image_info.get("type", "output"))
    if image_type == "input":
        base_dir = comfyui_root / "input"
    elif image_type == "temp":
        base_dir = comfyui_root / "temp"
    else:
        base_dir = comfyui_root / "output"

    subfolder = str(image_info.get("subfolder") or "")
    filename = image_info.get("filename")
    if not filename:
        raise RuntimeError(f"History image entry is missing filename: {image_info}")

    return (base_dir / subfolder / filename).resolve()


def extract_output_image(history: dict[str, Any], save_node_id: str, comfyui_root: Path) -> Path:
    outputs = history.get("outputs", {})
    if not isinstance(outputs, dict):
        raise RuntimeError(f"Unexpected history payload: {history}")

    preferred_node_ids = [save_node_id]
    for node_id in outputs:
        if node_id not in preferred_node_ids:
            preferred_node_ids.append(node_id)

    for node_id in preferred_node_ids:
        node_output = outputs.get(node_id, {})
        images = node_output.get("images") or []
        if not images:
            continue
        image_path = resolve_history_image_path(comfyui_root, images[0])
        if image_path.is_file():
            return image_path
        raise RuntimeError(f"ComfyUI reported an output that does not exist on disk: {image_path}")

    raise RuntimeError(f"No image output found in ComfyUI history: {history}")


def generate_direction(
    workflow_data: dict[str, Any],
    api_url: str,
    body_type: str,
    direction: str,
    reference_image: Path,
    comfyui_root: Path,
    installed_models: dict[str, str],
    timeout_seconds: int,
    poll_interval: float,
) -> Path:
    assets = direction_assets(body_type, direction, reference_image)
    assets.final_output.parent.mkdir(parents=True, exist_ok=True)

    if assets.final_output.is_file():
        log(f"[{direction}] Skip existing output: {assets.final_output}")
        return assets.final_output

    staged_inputs = stage_inputs(assets, comfyui_root)
    patched_workflow, save_node_id = patch_workflow_ui(
        workflow=workflow_data,
        body_type=body_type,
        direction=direction,
        staged_inputs=staged_inputs,
        installed_models=installed_models,
    )
    prompt = ui_workflow_to_prompt(patched_workflow)

    direction_start = time.perf_counter()
    prompt_id = submit_prompt(api_url, prompt)
    log(f"[{direction}] Submitted prompt {prompt_id}")

    history = wait_for_history(
        api_url=api_url,
        prompt_id=prompt_id,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
    )
    source_output = extract_output_image(history, save_node_id, comfyui_root)
    shutil.copy2(source_output, assets.final_output)

    elapsed = time.perf_counter() - direction_start
    log(f"[{direction}] Saved {assets.final_output} ({elapsed:.1f}s)")
    return assets.final_output


def main() -> None:
    args = parse_args()

    workflow_path = require_file(resolve_path(args.workflow), "Workflow JSON")
    reference_image = require_file(resolve_path(args.reference_image), "Reference image")
    comfyui_root = resolve_path(args.comfyui_root)
    if not comfyui_root.is_dir():
        raise RuntimeError(f"ComfyUI root not found: {comfyui_root}")

    directions = parse_directions(args.directions)
    workflow_data = load_json(workflow_path)
    if "nodes" not in workflow_data or "links" not in workflow_data:
        raise RuntimeError(
            "The workflow must be an exported ComfyUI UI workflow JSON containing 'nodes' and 'links'."
        )

    log(f"Workflow: {workflow_path}")
    log(f"ComfyUI root: {comfyui_root}")
    log(f"Directions: {', '.join(directions)}")

    ensure_server(args.api_url)
    installed_models = resolve_installed_models(comfyui_root)

    total_start = time.perf_counter()
    for index, direction in enumerate(directions, start=1):
        log(f"({index}/{len(directions)}) Start {args.body_type}_{direction}")
        generate_direction(
            workflow_data=workflow_data,
            api_url=args.api_url,
            body_type=args.body_type,
            direction=direction,
            reference_image=reference_image,
            comfyui_root=comfyui_root,
            installed_models=installed_models,
            timeout_seconds=args.timeout_seconds,
            poll_interval=args.poll_interval,
        )

    total_elapsed = time.perf_counter() - total_start
    log(f"All directions finished in {total_elapsed:.1f}s")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        raise SystemExit(f"[comfyui_batch] ERROR: {exc}")
