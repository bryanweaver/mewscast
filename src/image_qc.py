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
import io
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


# Anthropic vision API caps images at 5 MB base64-encoded. Base64 expands
# roughly 4/3, so raw bytes must stay under ~3.75 MB to be safe. Grok
# 2k PNGs regularly exceed that (observed: 6.6 MB raw / 8.8 MB base64).
# Target a bit lower than the limit to leave headroom.
_ANTHROPIC_MAX_RAW_BYTES = 3_500_000
_QC_DOWNSCALE_WIDTH = 1280  # px wide — preserves enough detail for anatomy QC


def _encode_image(path: str) -> Tuple[str, str]:
    """Read an image file and return (base64_data, media_type).

    If the raw file exceeds ~3.5 MB (Anthropic vision API has a 5 MB
    base64-encoded limit), downscale via PIL to a 1280px-wide JPEG before
    encoding. The Grok 2k PNGs routinely blow past the limit; the downscale
    is lossy-but-lossless-enough for anatomy QC.

    media_type is inferred from the file extension; defaults to png. Falls
    back to image/jpeg when the downscale path runs.
    """
    with open(path, "rb") as f:
        raw = f.read()

    if len(raw) <= _ANTHROPIC_MAX_RAW_BYTES:
        p = Path(path)
        ext = p.suffix.lower().lstrip(".")
        media_type = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
        }.get(ext, "image/png")
        return base64.standard_b64encode(raw).decode("utf-8"), media_type

    # Too big — downscale via PIL. JPEG at quality 85 hits a reasonable
    # quality/size tradeoff for a yes/no anatomy check.
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        if img.width > _QC_DOWNSCALE_WIDTH:
            ratio = _QC_DOWNSCALE_WIDTH / img.width
            new_size = (_QC_DOWNSCALE_WIDTH, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        data = buf.getvalue()
        # Ratchet down quality if still over the limit
        q = 85
        while len(data) > _ANTHROPIC_MAX_RAW_BYTES and q > 40:
            q -= 10
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=q, optimize=True)
            data = buf.getvalue()
        return base64.standard_b64encode(data).decode("utf-8"), "image/jpeg"
    except Exception:
        # If PIL fails for some reason, fall back to the raw bytes and
        # let Anthropic return the 400. The outer check_image() catches
        # it and returns qc-skipped-due-to-error so posting still proceeds.
        return base64.standard_b64encode(raw).decode("utf-8"), "image/png"


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
