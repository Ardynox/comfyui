"""Call OpenAI GPT Image for image-to-image generation.

Wraps ``client.images.edit`` from the OpenAI Python SDK so depth/normal
reference sheets from this repo can be turned into coloured character
renders. Supports one or many reference images, optional mask, and the
standard ``size``/``quality``/``background`` knobs exposed by gpt-image.

Quick start
-----------

Set your key once (PowerShell example)::

    setx OPENAI_API_KEY "sk-..."

If you route through a relay / proxy (中转站, common for users in China),
also set ``OPENAI_BASE_URL`` to the proxy's OpenAI-compatible endpoint::

    setx OPENAI_API_KEY   "sk-proxy-..."
    setx OPENAI_BASE_URL  "https://your-relay.example.com/v1"

The OpenAI Python SDK reads ``OPENAI_BASE_URL`` natively. You can also
override just for one run with ``--base-url``. A proxy works only if it
forwards the ``/images/edits`` endpoint in OpenAI-compatible form — verify
with the relay provider before burning quota.

Single shot with one depth reference::

    python scripts/gpt_image_edit.py \
        --input 02_blender/renders/depth/female_age4_5views_depth.png \
        --prompt "anime-style young woman character sheet, five views, soft lighting, transparent background" \
        --output 04_comfyui_output/raw/female_age4_5views_gptimage.png \
        --size auto --quality high --background transparent

Multiple references (e.g. depth + style ref)::

    python scripts/gpt_image_edit.py \
        --input 02_blender/renders/depth/female_age4_S.png \
        --input 03_comfyui_input/style_reference.png \
        --prompt @prompts/ninja_master.txt \
        --output 04_comfyui_output/raw/female_age4_S_gptimage.png

Batch over the 9 female composites::

    for I in 0 1 2 3 4 5 6 7 8; do \
      python scripts/gpt_image_edit.py \
        --input 02_blender/renders/depth/female_age${I}_5views_depth.png \
        --prompt @prompts/female_age${I}.txt \
        --output 04_comfyui_output/raw/female_age${I}_5views_gptimage.png \
        --size 1536x1024 --quality high; \
    done

Model name
----------

Default is ``gpt-image-1`` because that is the model name verified against
the OpenAI public API. If OpenAI has released a newer ``gpt-image-2`` on
your account, pass ``--model gpt-image-2`` and the SDK will forward the
string unchanged; the server validates it.

Output format
-------------

``gpt-image-*`` always returns base64 PNG, so this script writes PNG. If
``--n`` > 1 the output path is suffixed with ``_0``, ``_1``, etc.

Model quirks observed
---------------------

- ``gpt-image-2`` via relay rejects ``--background transparent`` with
  ``image_generation_user_error``. Stick with ``auto`` / ``opaque`` for
  that model, and describe a plain background in the prompt instead.
- ``--quality`` / ``--background`` are forwarded through ``extra_body`` so
  older SDK versions (pre-1.67) still work.

Safety
------

- The API key is read from ``OPENAI_API_KEY``. The script never prints or
  logs the key.
- Each generation call costs money; this script does no caching. Don't
  loop it blindly over large sets without checking pricing first.
"""

from __future__ import annotations

import argparse
import base64
import os
import random
import sys
import time
from pathlib import Path

# Windows cp936 consoles garble UTF-8 prompts when we echo them back.
# This is cosmetic (the API always gets UTF-8 from load_prompt), but the
# garbled echo makes debugging confusing. Force stdout to UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


SUPPORTED_SIZES = ("auto", "1024x1024", "1024x1536", "1536x1024")
SUPPORTED_QUALITY = ("auto", "low", "medium", "high")
SUPPORTED_BACKGROUND = ("auto", "transparent", "opaque")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True, action="append",
                        help="Reference image path. Repeat for multiple references.")
    parser.add_argument("--prompt", required=True,
                        help="Prompt text, or '@path/to/file.txt' to load from a file.")
    parser.add_argument("--output", required=True,
                        help="Output PNG path. If --n > 1 becomes '{stem}_0.png', '{stem}_1.png', ...")
    parser.add_argument("--model", default="gpt-image-1",
                        help="OpenAI image model (default: gpt-image-1; try gpt-image-2 if available).")
    parser.add_argument("--base-url", default=None,
                        help="Override the OpenAI base URL (e.g. a relay/proxy endpoint). "
                             "Falls back to the OPENAI_BASE_URL env var, then the OpenAI default.")
    parser.add_argument("--timeout", type=float, default=180.0,
                        help="HTTP timeout per request in seconds (relays can be slow).")
    parser.add_argument("--max-retries", type=int, default=10,
                        help="Retry attempts for moderation/rate/5xx/timeout errors "
                             "(moderation is probabilistic, so retries often succeed).")
    parser.add_argument("--retry-delay", type=float, default=3.0,
                        help="Base seconds between retries; rate-limit gets 4x, with +-25%% jitter.")
    parser.add_argument("--size", default="auto", choices=SUPPORTED_SIZES)
    parser.add_argument("--quality", default="auto", choices=SUPPORTED_QUALITY)
    parser.add_argument("--background", default="auto", choices=SUPPORTED_BACKGROUND)
    parser.add_argument("--n", type=int, default=1, help="Number of images to generate.")
    parser.add_argument("--mask",
                        help="Optional mask PNG; transparent pixels in the mask are the region to edit.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the request summary without calling the API.")
    return parser.parse_args()


def load_prompt(prompt_arg: str) -> str:
    if prompt_arg.startswith("@"):
        return Path(prompt_arg[1:]).read_text(encoding="utf-8").strip()
    return prompt_arg


RETRYABLE_BAD_REQUEST_CODES = {
    "moderation_blocked",
    "content_policy_violation",
    # Relay wrapper codes (timesniper.club et al.). The relay re-labels
    # upstream issues with its own codes — observed so far:
    #   bad_response_status_code  - "I forwarded an upstream bad status"
    #   invalid_request           - generic "something's off, retry"
    # Both are unreliable signals (sometimes genuine moderation, sometimes
    # upstream stall, sometimes its own parser dropping the UTF-8 prompt
    # field). All cases benefit from another attempt.
    "bad_response_status_code",
    "invalid_request",
}


def _is_chinese_error_message(msg: str) -> bool:
    """A Chinese-language error message is almost certainly a relay wrapper
    rather than OpenAI's own response (OpenAI errors are English). Treat as
    relay-side flake → retry."""
    if not msg:
        return False
    return any("\u4e00" <= ch <= "\u9fff" for ch in msg)


def _error_body(exc) -> dict:
    # SDK exposes body as the raw JSON dict. Some relays return already-unwrapped
    # error objects; handle both shapes plus the .response.json() fallback.
    candidates = []
    body = getattr(exc, "body", None)
    if body is not None:
        candidates.append(body)
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            candidates.append(response.json())
        except Exception:  # noqa: BLE001
            pass
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if "error" in candidate and isinstance(candidate["error"], dict):
            return candidate["error"]
        if "code" in candidate or "message" in candidate:
            return candidate
    return {}


def _should_retry(exc) -> tuple[bool, str]:
    """Return (retry, reason). Only retry on transient / probabilistic errors."""
    # Import lazily so --help works without the SDK installed.
    from openai import (
        APIConnectionError,
        APITimeoutError,
        BadRequestError,
        InternalServerError,
        RateLimitError,
    )

    if isinstance(exc, (APITimeoutError, APIConnectionError, InternalServerError)):
        return True, type(exc).__name__
    if isinstance(exc, RateLimitError):
        return True, "RateLimitError"
    if isinstance(exc, BadRequestError):
        err = _error_body(exc)
        code = err.get("code") or ""
        if code in RETRYABLE_BAD_REQUEST_CODES:
            return True, f"BadRequestError/{code}"
        # Some relays stuff the code in message/type; string match as fallback.
        blob = (err.get("type") or "") + " " + (err.get("message") or "") + " " + str(exc)
        blob_lower = blob.lower()
        if "moderation" in blob_lower or "safety" in blob_lower:
            return True, "BadRequestError/moderation(str-match)"
        # Relay claims "prompt is empty" / "prompt 不能为空" when our prompt is
        # demonstrably non-empty (we log it before the call). Treat as a
        # relay-side multipart/encoding flake and retry. Match Chinese and
        # English variants.
        if "prompt" in blob_lower and (
            "不能为空" in blob or "为空" in blob
            or "empty" in blob_lower or "missing" in blob_lower
        ):
            return True, "BadRequestError/relay-empty-prompt(str-match)"
        # Last resort: any 400 whose error message is in Chinese is almost
        # certainly a relay wrapper (OpenAI's own errors are always English).
        # Examples observed: "请求无法完成，请检查输入后重试", "prompt 不能为空".
        # Hard OpenAI 400s (invalid_api_key, model_not_found, unsupported_value)
        # carry English messages and aren't matched here.
        if _is_chinese_error_message(err.get("message") or ""):
            return True, "BadRequestError/relay-chinese-message"
    return False, ""


def call_with_retry(fn, *, max_retries: int, base_delay: float, label: str):
    attempt = 0
    while True:
        try:
            return fn()
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 — intentional broad catch for retry classifier
            retry, reason = _should_retry(exc)
            if not retry or attempt >= max_retries:
                if retry:
                    print(f"[retry] {label} giving up after {attempt} retries ({reason})",
                          file=sys.stderr)
                raise
            attempt += 1
            from openai import RateLimitError
            delay = base_delay * (4.0 if isinstance(exc, RateLimitError) else 1.0)
            delay *= random.uniform(0.75, 1.25)
            print(f"[retry] {label} attempt {attempt}/{max_retries} ({reason}); "
                  f"sleeping {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)


def require_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY is not set. Set it in your shell before running.\n"
            "  PowerShell: setx OPENAI_API_KEY \"sk-...\"\n"
            "  bash:       export OPENAI_API_KEY=sk-...",
            file=sys.stderr,
        )
        sys.exit(2)


def write_output(output_path: Path, n: int, data) -> list[Path]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, item in enumerate(data):
        if n == 1:
            target = output_path
        else:
            target = output_path.with_name(f"{output_path.stem}_{index}{output_path.suffix}")
        if not item.b64_json:
            raise RuntimeError(f"API response {index} has no b64_json payload.")
        target.write_bytes(base64.b64decode(item.b64_json))
        written.append(target)
    return written


def main() -> None:
    args = parse_args()
    prompt = load_prompt(args.prompt)

    input_paths = [Path(p) for p in args.input]
    for p in input_paths:
        if not p.is_file():
            raise SystemExit(f"Input image not found: {p}")
    mask_path = Path(args.mask) if args.mask else None
    if mask_path and not mask_path.is_file():
        raise SystemExit(f"Mask not found: {mask_path}")

    print(f"[gpt_image_edit] model={args.model} size={args.size} quality={args.quality} "
          f"background={args.background} n={args.n}")
    print(f"[gpt_image_edit] inputs={[str(p) for p in input_paths]}")
    if mask_path:
        print(f"[gpt_image_edit] mask={mask_path}")
    print(f"[gpt_image_edit] prompt={prompt[:120]}{'...' if len(prompt) > 120 else ''}")

    if args.dry_run:
        print("[gpt_image_edit] --dry-run set; not calling API.")
        return

    require_api_key()
    from openai import OpenAI  # imported late so --help / --dry-run work without the key

    client_kwargs: dict = {"timeout": args.timeout}
    base_url = args.base_url or os.environ.get("OPENAI_BASE_URL")
    if base_url:
        client_kwargs["base_url"] = base_url
        print(f"[gpt_image_edit] base_url={base_url}")
    client = OpenAI(**client_kwargs)

    # File handles have to be re-opened between retries because the SDK
    # consumes the stream. Wrap the call in a closure so each attempt gets
    # fresh handles.
    def do_call():
        opened_inputs = [p.open("rb") for p in input_paths]
        opened_mask = mask_path.open("rb") if mask_path else None
        try:
            kwargs = {
                "model": args.model,
                "image": opened_inputs if len(opened_inputs) > 1 else opened_inputs[0],
                "prompt": prompt,
                "n": args.n,
                "size": args.size,
            }
            # quality / background were added to gpt-image after the SDK
            # signature changed; pass via extra_body so older SDKs still work.
            extra_body: dict = {}
            if args.quality != "auto":
                extra_body["quality"] = args.quality
            if args.background != "auto":
                extra_body["background"] = args.background
            if extra_body:
                kwargs["extra_body"] = extra_body
            if opened_mask is not None:
                kwargs["mask"] = opened_mask

            return client.images.edit(**kwargs)
        finally:
            for handle in opened_inputs:
                handle.close()
            if opened_mask is not None:
                opened_mask.close()

    result = call_with_retry(
        do_call,
        max_retries=args.max_retries,
        base_delay=args.retry_delay,
        label=f"{Path(input_paths[0]).name}",
    )

    written = write_output(Path(args.output), args.n, result.data)
    for path in written:
        print(f"[gpt_image_edit] wrote {path}")


if __name__ == "__main__":
    main()
