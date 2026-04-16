"""
AI-powered image generation using xAI Grok (or alternate model via config).

Image-quality levers handled here:
  - Universal eye-catch anchor (scroll-stopping cinematic cues) applied to
    every prompt. Engagement is driven by images that make a thumb stop.
  - Per-post-type style anchor (REPORT/META/ANALYSIS/BULLETIN/PRIMARY/CORRECTION).
  - Aspect ratio configurable via `image.aspect_ratio` in config.yaml.
  - Model selectable via `image.model` in config.yaml (default: grok).
  - Optional QC retry loop via src/image_qc.py (Claude Haiku vision check)
    runs when `image.qc.enabled` is true in config.yaml.
"""
import os
from typing import Optional

import requests
import yaml
from openai import OpenAI

# The subject identity anchor — the cat MUST be photorealistic, anatomically
# correct, and have real personality. A forgettable cat = forgettable image.
# Applied to every prompt regardless of post type.
_SUBJECT_ANCHOR = (
    "Photorealistic brown tabby cat with an intense, intelligent gaze and the "
    "bearing of a seasoned news anchor — dignified, authoritative, fully present. "
    "Correct four-paw anatomy, no human hands or fingers. "
)

# The eye-catch anchor — scroll-stopping DNA applied to every prompt.
# Engagement data suggests the images that get a thumb to stop share these
# cues: dramatic light, cinematic framing, direct eye contact, an element of
# surprise. These are stacked on top of the per-post-type style anchor.
_EYECATCH_ANCHOR = (
    "Scroll-stopping editorial image. Dramatic cinematic lighting with strong "
    "highlights and deep shadows. Sharp eye contact with the viewer. Cinematic "
    "composition like a film still, not stock photography. Rich color grading, "
    "strong focal point, a single arresting detail the viewer can't look away from. "
)

# Per-post-type style anchor prefixes. Stacked AFTER _SUBJECT_ANCHOR +
# _EYECATCH_ANCHOR. Keyed by PostType.value so callers don't need to import
# the dossier_store enum. Each anchor evokes a specific, recognizable
# editorial aesthetic — not just "journalism style" but a publication
# someone would actually pick up off a newsstand.
POST_TYPE_STYLE_ANCHORS = {
    "REPORT": (
        "Vanity Fair editorial portrait. 85mm lens, shallow depth of field, "
        "three-point studio lighting. Subtle newsroom depth in the background. "
        "The cat at the center, fully in control of the frame. "
    ),
    "META": (
        "Cinematic wide shot of a wire-service desk at midnight. Multiple TV "
        "monitors glowing behind the cat, each showing a different outlet's "
        "framing of the same story. Warm tungsten mixed with cool blue monitor "
        "glow. Film-noir contrast. The cat is the only thing in focus. "
    ),
    "ANALYSIS": (
        "New Yorker cover illustration style — slightly painterly, strong visual "
        "metaphor carrying the argument. Moody chiaroscuro lighting. A single "
        "unexpected detail (a chess piece, a tipped scale, a half-burned match) "
        "that makes the viewer lean in to decode it. "
    ),
    "BULLETIN": (
        "Breaking-news urgency. Hand-held camera energy, motion blur at the edges, "
        "red emergency glow from off-frame. The cat caught mid-action — paw raised, "
        "ears forward, something just happened. Grainy photojournalism with kinetic "
        "tension. "
    ),
    "PRIMARY": (
        "Presidential-archive photograph. Cat seated at a dark mahogany desk "
        "strewn with labeled folders and documents, a single spotlit page in the "
        "foreground. Kodak Portra 400 on 35mm. Warm amber tones, deep shadows, the "
        "gravity of an official record. "
    ),
    "CORRECTION": (
        "Minimalist black-and-white editorial. The cat in profile against a stark "
        "white background, looking thoughtful and a little humbled. One crisp "
        "graphic element — a red correction stamp, a crossed-out line, a pen — "
        "as the only color accent. Quiet dignity, no drama. "
    ),
}

# Generic anchor used when no post_type is provided (legacy pipeline path).
_DEFAULT_STYLE_ANCHOR = (
    "Editorial photojournalism with cinematic lighting and a strong focal point. "
)


def _load_image_config() -> dict:
    """Read `image:` block from config.yaml if present. Returns a dict with
    safe defaults so callers can .get() without KeyErrors."""
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return raw.get("image") or {}
    except Exception:
        return {}


class ImageGenerator:
    """Generates images using xAI Grok (default) or configured alternate."""

    # Valid aspect ratios Grok accepts. 3:2 reads well on both Bluesky
    # (4:5-favoring inline) and X (16:9-favoring cards). Default chosen
    # because it's the best compromise without a per-platform split.
    SUPPORTED_ASPECT_RATIOS = {"3:2", "16:9", "4:5", "1:1"}

    def __init__(self):
        """Initialize image-gen client."""
        api_key = os.getenv("X_AI_API_KEY")
        if not api_key:
            raise ValueError("Missing X_AI_API_KEY. Check your .env file.")

        # xAI uses OpenAI-compatible API
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1"
        )

        image_cfg = _load_image_config()
        self.model = image_cfg.get("model", "grok-imagine-image")
        self.aspect_ratio = image_cfg.get("aspect_ratio", "3:2")
        if self.aspect_ratio not in self.SUPPORTED_ASPECT_RATIOS:
            print(
                f"⚠️  image.aspect_ratio={self.aspect_ratio!r} not in supported set "
                f"{self.SUPPORTED_ASPECT_RATIOS}; falling back to 3:2"
            )
            self.aspect_ratio = "3:2"
        self.resolution = image_cfg.get("resolution", "2k")

        # QC loop config — opt-in via image.qc.enabled
        qc_cfg = image_cfg.get("qc") or {}
        self.qc_enabled = bool(qc_cfg.get("enabled", False))
        self.qc_max_retries = int(qc_cfg.get("max_retries", 2))

    def _anchor_prompt(self, prompt: str, post_type: Optional[str] = None) -> str:
        """Compose the full prompt: subject anchor + eye-catch anchor +
        post-type style anchor + the dynamic prompt.

        Kept as its own method so tests can introspect the composition
        without needing to mock the OpenAI client.
        """
        style = POST_TYPE_STYLE_ANCHORS.get(post_type, _DEFAULT_STYLE_ANCHOR) if post_type else _DEFAULT_STYLE_ANCHOR
        return f"{_SUBJECT_ANCHOR}{_EYECATCH_ANCHOR}{style}{prompt}"

    def _generate_once(self, anchored_prompt: str) -> Optional[str]:
        """Single generation attempt. Returns the image URL or None."""
        response = self.client.images.generate(
            model=self.model,
            prompt=anchored_prompt,
            n=1,
            extra_body={
                "aspect_ratio": self.aspect_ratio,
                "resolution": self.resolution,
            },
        )
        return response.data[0].url if response.data else None

    def _download(self, image_url: str, save_path: str) -> None:
        """Download image URL to local path."""
        img_response = requests.get(image_url, timeout=30)
        img_response.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(img_response.content)

    def generate_image(
        self,
        prompt: str,
        save_path: str = "temp_image.png",
        post_type: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Generate an image.

        Args:
            prompt: Text description of the image to generate.
            save_path: Where to save the generated image.
            post_type: Optional post type string (e.g. "REPORT", "META") used
                to pick the style anchor. If omitted, a generic anchor is used.

        Returns:
            A tuple (image_path, anchored_prompt). Both are None on failure.
            The anchored_prompt is the FULL prompt that was sent to the image
            model (subject anchor + eye-catch anchor + per-post-type style
            anchor + dynamic prompt). Callers should persist it for audit.
        """
        anchored_prompt = self._anchor_prompt(prompt, post_type=post_type)
        try:
            print(f"🎨 Generating image with {self.model} ({self.aspect_ratio})...")
            print(f"   Prompt: {prompt[:80]}...")

            attempts = 1 + (self.qc_max_retries if self.qc_enabled else 0)
            image_url = None
            for attempt in range(1, attempts + 1):
                image_url = self._generate_once(anchored_prompt)
                if not image_url:
                    print(f"   Attempt {attempt}: generation returned no URL")
                    continue
                print(f"✓ Image generated (attempt {attempt}): {image_url[:60]}...")
                self._download(image_url, save_path)
                print(f"✓ Image saved to: {save_path}")

                # Optional QC loop
                if self.qc_enabled:
                    try:
                        from image_qc import check_image
                    except ImportError:
                        from src.image_qc import check_image  # pragma: no cover

                    passed, reason = check_image(save_path)
                    if passed:
                        print(f"✓ QC passed: {reason}")
                        return save_path, anchored_prompt
                    print(f"✗ QC failed (attempt {attempt}/{attempts}): {reason}")
                    if attempt < attempts:
                        print("   Retrying generation...")
                        continue
                    print("   Retries exhausted — returning the last attempt anyway")
                    return save_path, anchored_prompt
                else:
                    return save_path, anchored_prompt

            return None, None

        except Exception as e:
            print(f"✗ Image generation failed: {e}")
            return None, None
