"""
Claude Haiku vision-based QC for generated images.

Called optionally from src/image_generator.py after a successful generation.
If the QC fails (detected anatomy issue, multiple cats, deformed face), the
caller retries generation up to `image.qc.max_retries` times (configured in
config.yaml).

Kept in its own module so:
  - It can be skipped entirely (opt-in via config) — zero extra cost on
    production paths that don't want it.
  - It can be unit-tested in isolation by mocking anthropic.
  - Its model choice (Haiku for speed/cost) can evolve without touching
    the image generator.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Tuple

# The QC prompt is short, strict, and returns "Yes/No" as the first token so
# parsing is trivial. We keep it deterministic so retry logic has a clean
# success signal.
_QC_PROMPT = (
    "You are a quick visual QC reviewer for a news illustration. "
    "Does this image show a single brown tabby cat with correct anatomy "
    "(exactly four legs, two eyes, two ears, natural body proportions, "
    "no deformed face, no extra limbs, no human hands or fingers in the scene)?\n\n"
    "Answer on the first line with exactly 'Yes' or 'No'. "
    "On the second line give one short reason."
)

_HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _encode_image(path: str) -> Tuple[str, str]:
    """Read an image file and return (base64_data, media_type).

    media_type is inferred from the file extension; defaults to png.
    """
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    media_type = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/png")
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, media_type


def check_image(image_path: str) -> Tuple[bool, str]:
    """Run Haiku QC on a generated image.

    Args:
        image_path: Path to the generated image file.

    Returns:
        (passed, reason) where passed is True if Haiku answered "Yes" on
        the first line. On any error (network, API key missing, parse
        failure), we return (True, "qc-skipped-due-to-error") so a flaky
        QC service doesn't block posting — the whole QC step is optional
        quality enhancement, not a correctness gate.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return True, "qc-skipped: ANTHROPIC_API_KEY missing"
    if not os.path.exists(image_path):
        return False, f"qc-error: image not found at {image_path}"

    try:
        from anthropic import Anthropic

        data, media_type = _encode_image(image_path)
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=80,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            },
                        },
                        {"type": "text", "text": _QC_PROMPT},
                    ],
                }
            ],
        )
        text = (response.content[0].text or "").strip() if response.content else ""
        first_line = text.split("\n", 1)[0].strip().lower().rstrip(".!,:;")
        reason_line = text.split("\n", 1)[1].strip() if "\n" in text else text
        passed = first_line.startswith("yes")
        return passed, reason_line or ("ok" if passed else "rejected")
    except Exception as e:
        # Don't block posting on a QC flake
        return True, f"qc-skipped-due-to-error: {e}"
