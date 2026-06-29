"""Cloudflare R2 upload helper for dossier images.

Why this exists: dossier PNGs used to be committed to git under
docs/dossiers/images/. That bloated the repo to multi-GB and made every
clone slow. Now the canonical public store is an R2 bucket served at
R2_IMAGE_BASE_URL, and the local file under docs/dossiers/images/ is
gitignored — kept only because the X/Bluesky media-upload paths need a
local file path.

Behavior:
- If all R2_* env vars are set, upload to R2 and return True.
- If any are missing, log once per process and return False (fail-soft —
  the local file still exists for X/Bluesky media upload, and the static
  site can keep working during cutover if R2_IMAGE_BASE_URL is left
  pointing at the legacy mewscast.us path).
"""

from __future__ import annotations

import os
import threading
from typing import Optional

_REQUIRED_ENV = (
    "R2_ENDPOINT_URL",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
)

_warned_missing = False
_warn_lock = threading.Lock()
_client_cache: dict = {}


def _r2_configured() -> bool:
    return all(os.environ.get(k) for k in _REQUIRED_ENV)


def _warn_once_missing() -> None:
    global _warned_missing
    with _warn_lock:
        if _warned_missing:
            return
        missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
        print(
            f"[r2] R2 upload disabled — missing env vars: {', '.join(missing)}. "
            f"Images will be written locally only."
        )
        _warned_missing = True


def _get_client():
    """Build (and cache) a boto3 S3 client pointed at R2.

    Cached per-process so we don't pay the boto session cost per upload.
    """
    if "client" in _client_cache:
        return _client_cache["client"]
    import boto3
    from botocore.client import Config

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        region_name="auto",
    )
    _client_cache["client"] = client
    return client


def upload_dossier_image(local_path: str, key: Optional[str] = None) -> bool:
    """Upload a PNG to R2. Returns True on success, False on any failure.

    Fail-soft by design: a failed R2 upload must not break publishing.
    The X/Bluesky bots still have the local file; only the public OG/IMG
    URLs will 404 until a retry uploads them.
    """
    if not _r2_configured():
        _warn_once_missing()
        return False

    if not os.path.isfile(local_path):
        print(f"[r2] skip upload — file missing: {local_path}")
        return False

    if key is None:
        key = os.path.basename(local_path)

    try:
        client = _get_client()
        client.upload_file(
            Filename=local_path,
            Bucket=os.environ["R2_BUCKET"],
            Key=key,
            ExtraArgs={"ContentType": "image/png", "CacheControl": "public, max-age=31536000, immutable"},
        )
        print(f"[r2] uploaded {key} ({os.path.getsize(local_path)} bytes)")
        return True
    except Exception as e:
        print(f"[r2] upload failed for {key}: {e}")
        return False


def public_image_url(image_path: str) -> str:
    """Convert a stored relative path (``images/X.png``) to a public URL.

    If R2_IMAGE_BASE_URL is set, returns ``{base}/X.png``. Otherwise falls
    back to the legacy ``https://mewscast.us/dossiers/{image_path}`` form
    so the renderer keeps working before the cutover is complete.
    """
    base = os.environ.get("R2_IMAGE_BASE_URL", "").rstrip("/")
    filename = image_path.rsplit("/", 1)[-1]
    if base:
        return f"{base}/{filename}"
    return f"https://mewscast.us/dossiers/{image_path}"
