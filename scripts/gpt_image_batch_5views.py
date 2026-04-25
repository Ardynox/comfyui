"""Batch-convert 5-view depth composites into GPT-Image character sheets.

For each depth composite under ``02_blender/renders/depth/`` matching the
input pattern, this script invokes ``scripts/gpt_image_edit.py`` with a
shared prompt template. Default target is the nine
``female_age{0-8}_5views_depth.png`` sheets.

Usage::

    # required env (or --base-url / rely on OpenAI defaults):
    #   OPENAI_API_KEY=sk-...
    #   OPENAI_BASE_URL=https://your-relay.example.com/v1   (optional)

    python scripts/gpt_image_batch_5views.py

    # override prompt / pattern / quality
    python scripts/gpt_image_batch_5views.py \
        --prompt-file prompts/isometric_base_5views.md \
        --pattern "female_age*_5views_depth.png" \
        --quality medium

    # smoke test one file before the full run
    python scripts/gpt_image_batch_5views.py --limit 1 --quality low

Outputs land in ``04_comfyui_output/raw/`` and are named
``{stem_without_depth}_gptimage.png`` (``_5views_depth`` suffix becomes
``_5views_gptimage``). Outputs are skipped if they already exist, so the
script is resumable; pass ``--force`` to overwrite.

Rate-limit / cost guard: the script loops **sequentially**. Each call
burns OpenAI quota; there is no local caching beyond the skip-existing
check. Run with ``--dry-run`` first to confirm plans.

Moderation is probabilistic — identical inputs can flip between pass and
block between calls. The script forwards ``--max-retries`` (default 10)
and ``--retry-delay`` (default 3s) to ``gpt_image_edit.py``, which only
retries transient / probabilistic classes (``moderation_blocked``,
``content_policy_violation``, ``RateLimitError``, timeouts, 5xx). Hard
failures (auth, invalid args, quota exhausted) bail out immediately so we
don't burn the whole budget on a dead request.

Keep in sync with ``docs/pipeline.md`` section 4.2 if you add options.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEPTH_DIR = PROJECT_ROOT / "02_blender" / "renders" / "depth"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "04_comfyui_output" / "raw"
DEFAULT_PROMPT_FILE = PROJECT_ROOT / "prompts" / "isometric_base_5views.md"
SINGLE_SCRIPT = PROJECT_ROOT / "scripts" / "gpt_image_edit.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--depth-dir", default=str(DEFAULT_DEPTH_DIR),
                        help="Directory containing input depth composites.")
    parser.add_argument("--pattern", default="female_age*_5views_depth.png",
                        help="Glob pattern inside --depth-dir.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help="Where generated PNGs are written.")
    parser.add_argument("--prompt-file", default=str(DEFAULT_PROMPT_FILE),
                        help="Path to the shared prompt template (passed as @file).")
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--size", default="1536x1024",
                        help="OpenAI image size. 1536x1024 is the widest landscape that "
                             "fits a 5-panel sheet; per-view calls prefer 1024x1536.")
    parser.add_argument("--quality", default="medium",
                        choices=["low", "medium", "high", "auto"])
    parser.add_argument("--background", default="auto",
                        help="gpt-image-2 rejects 'transparent'; keep 'auto' or 'opaque'.")
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--max-retries", type=int, default=10,
                        help="Per-input retry budget for moderation/rate/5xx/timeout "
                             "(moderation blocks are probabilistic; 10 retries usually "
                             "converts a flagged input).")
    parser.add_argument("--retry-delay", type=float, default=3.0,
                        help="Base seconds between retries (forwarded to gpt_image_edit).")
    parser.add_argument("--base-url", default=None,
                        help="Forward to gpt_image_edit.py --base-url (relay).")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process at most N inputs (0 = unlimited).")
    parser.add_argument("--force", action="store_true",
                        help="Re-run even if the output PNG already exists.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would run without calling gpt_image_edit.py.")
    parser.add_argument("--output-suffix-replace", default="_5views_depth=_5views_gptimage",
                        help="Replacement rule 'OLD=NEW' applied to the input stem to "
                             "build the output stem.")
    return parser.parse_args()


def output_stem_for(input_path: Path, rule: str) -> str:
    if "=" not in rule:
        raise ValueError(f"--output-suffix-replace must be OLD=NEW, got: {rule}")
    old, new = rule.split("=", 1)
    stem = input_path.stem
    if old in stem:
        return stem.replace(old, new)
    return f"{stem}_gptimage"


def build_command(args: argparse.Namespace, input_path: Path, output_path: Path,
                  prompt_file: Path) -> list[str]:
    cmd = [
        sys.executable, str(SINGLE_SCRIPT),
        "--input", str(input_path),
        "--prompt", f"@{prompt_file}",
        "--output", str(output_path),
        "--model", args.model,
        "--size", args.size,
        "--quality", args.quality,
        "--background", args.background,
        "--n", str(args.n),
        "--timeout", str(args.timeout),
        "--max-retries", str(args.max_retries),
        "--retry-delay", str(args.retry_delay),
    ]
    if args.base_url:
        cmd += ["--base-url", args.base_url]
    if args.dry_run:
        cmd.append("--dry-run")
    return cmd


def main() -> None:
    args = parse_args()
    depth_dir = Path(args.depth_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    prompt_file = Path(args.prompt_file).resolve()

    if not depth_dir.is_dir():
        raise SystemExit(f"depth-dir not found: {depth_dir}")
    if not prompt_file.is_file():
        raise SystemExit(f"prompt-file not found: {prompt_file}")
    if not SINGLE_SCRIPT.is_file():
        raise SystemExit(f"single-call script missing: {SINGLE_SCRIPT}")
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = sorted(depth_dir.glob(args.pattern))
    if not inputs:
        raise SystemExit(f"No files match {args.pattern} under {depth_dir}")
    if args.limit > 0:
        inputs = inputs[:args.limit]

    if not args.dry_run and not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set. Set it or pass --dry-run.")

    print(f"[batch] prompt={prompt_file}")
    print(f"[batch] model={args.model} size={args.size} quality={args.quality} "
          f"background={args.background} n={args.n}")
    print(f"[batch] inputs={len(inputs)} output_dir={output_dir}")

    failures: list[tuple[Path, str]] = []
    for index, input_path in enumerate(inputs, start=1):
        output_stem = output_stem_for(input_path, args.output_suffix_replace)
        output_path = output_dir / f"{output_stem}.png"
        label = f"[{index}/{len(inputs)}] {input_path.name} -> {output_path.name}"

        if output_path.exists() and not args.force and not args.dry_run:
            print(f"{label}  SKIP (exists; use --force to overwrite)")
            continue

        cmd = build_command(args, input_path, output_path, prompt_file)
        print(f"{label}")
        if args.dry_run:
            print("  $ " + " ".join(cmd))
            continue

        completed = subprocess.run(cmd)
        if completed.returncode != 0:
            failures.append((input_path, f"exit={completed.returncode}"))
            print(f"{label}  FAIL (exit {completed.returncode})")
        else:
            print(f"{label}  OK")

    if failures:
        print(f"[batch] {len(failures)} failure(s):")
        for path, reason in failures:
            print(f"  - {path.name}: {reason}")
        sys.exit(1)
    print("[batch] all done")


if __name__ == "__main__":
    main()
