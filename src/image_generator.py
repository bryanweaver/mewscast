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
    "highlights and deep shadows. Cinematic composition like a film still, not "
    "stock photography. Rich color grading, strong focal point, a single "
    "arresting detail the viewer can't look away from. When Walter's face is "
    "in frame, sharp eye contact with the viewer. "
)

# Per-post-type style anchor prefixes. Stacked AFTER _SUBJECT_ANCHOR +
# _EYECATCH_ANCHOR. Keyed by PostType.value so callers don't need to import
# the dossier_store enum. Each anchor evokes a specific, recognizable
# editorial aesthetic — not just "journalism style" but a publication
# someone would actually pick up off a newsstand.
# Per-post-type style anchors. Define AESTHETIC (lens choice, lighting,
# color grade, set/mood/era) but NOT composition or framing. Composition
# (where Walter sits in the frame, the camera angle, what's in foreground
# vs background) is owned by the shot-type rotation in main.py — these
# anchors must not contradict it. Older revisions of these anchors said
# things like "the cat at the center, fully in control of the frame" or
# "the cat is the only thing in focus" — that locked every image to a
# centered medium portrait regardless of shot type. Composition language
# was stripped 2026-05-05 so WIDE_ESTABLISHING / LOW_ANGLE_HERO / DETAIL
# / THROUGH_THE_LENS shot types could actually express themselves.
POST_TYPE_STYLE_ANCHORS = {
    "REPORT": (
        "Vanity Fair editorial portrait aesthetic. 85mm lens look, shallow "
        "depth of field, three-point lighting. Newsroom or field-reportage "
        "context. Authoritative, present-tense mood. "
    ),
    "META": (
        "Wire-service-at-midnight aesthetic. Multiple TV monitors glowing "
        "with different outlet logos / framing of the same story. Warm "
        "tungsten mixed with cool blue monitor glow. Film-noir contrast. "
        "The newsroom is part of the subject. "
    ),
    "ANALYSIS": (
        "New Yorker cover illustration style — slightly painterly, strong "
        "visual metaphor carrying the argument. Moody chiaroscuro lighting. "
        "A single unexpected symbolic detail (a chess piece, a tipped scale, "
        "a half-burned match) that rewards a second look. "
    ),
    "BULLETIN": (
        "Breaking-news urgency aesthetic. Hand-held energy, motion blur at "
        "frame edges, red emergency glow from off-frame. Grainy "
        "photojournalism with kinetic tension. Walter caught mid-action — "
        "paw raised or ears forward — something just happened. "
    ),
    "PRIMARY": (
        "Presidential-archive photograph aesthetic. Dark mahogany surfaces, "
        "labeled folders and documents, official seals, a single spotlit "
        "page. Kodak Portra 400 on 35mm. Warm amber tones, deep shadows, "
        "the gravity of an official record. "
    ),
    "CORRECTION": (
        "Minimalist black-and-white editorial aesthetic. Stark white space "
        "and quiet dignity. One crisp graphic element as the only color "
        "accent (a red correction stamp, a crossed-out line, a pen). "
        "Thoughtful, slightly humbled mood — no drama. "
    ),
}

# Generic anchor used when no post_type is provided (legacy pipeline path).
_DEFAULT_STYLE_ANCHOR = (
    "Editorial photojournalism with cinematic lighting and a strong focal point. "
)


# Locked style spec for Walter's "Field Notes" reply image — meant to be
# instantly recognizable as a Walter Croncat brand asset on every render.
# Reproducibility comes from over-specifying every visual element so Grok
# has minimal room to drift. The reference flatlay in the brand kit is the
# style anchor; this prompt describes the same notepad in isolation.
#
# Fact text is embedded VERBATIM in the prompt with explicit "render exactly
# as written" instructions — Grok handles text well but still occasionally
# paraphrases, so faithfulness is enforced via prompt language. A future
# vision-QC pass can verify post-render.
_FIELD_NOTES_STYLE_SPEC = (
    "Overhead flatlay photograph of a single page in a reporter's "
    "spiral-bound notepad, photographed from directly above. Top spiral "
    "binding visible at the top of the frame. Cream / lightly aged paper "
    "with subtle texture, faint horizontal rule lines, soft natural lighting "
    "from the upper left casting a gentle shadow. The notepad rests on a "
    "dark weathered leather surface; only a sliver of the leather is visible "
    "around the edges. Warm brown / cream / black palette, slightly "
    "desaturated, cinematic mood lighting. No camera, no microphone, no other "
    "objects in frame — only the notepad. "
    "The handwriting is consistent ALL-CAPS BLOCK PRINT in black marker, "
    "slightly rough and rapid, the way a working reporter scribbles in the "
    "field. Header underlined with a single hand-drawn line. Each numbered "
    "entry begins with a dash. Small black inked paw-print stamps in two "
    "corners as a subtle decorative motif (4 toe pads + 1 main pad each, "
    "slightly imperfect ink). At the bottom-right of the page: a larger "
    "single black inked cat's paw-print stamp next to a flowing cursive "
    "signature reading '— Walter'. "
    "No additional doodles, no coffee stains, no margin notes, no other "
    "decorations. Sparse, deliberate, journalistic. "
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

    @staticmethod
    def _sanitize_for_prompt(text: str) -> str:
        """Normalize dynamic text for safe embedding inside double-quoted
        prompt literals. Replaces double quotes with single quotes so the
        surrounding "..." structure remains parseable as a single string,
        and collapses internal newlines/tabs to single spaces so each
        embedded value remains a one-liner. Strips leading/trailing
        whitespace as a final cleanup.

        This preserves the human-readable meaning of the text (a fact with
        an internal "quote" still reads as quoted speech) while keeping the
        prompt's literal structure intact.
        """
        if not text:
            return ""
        # Collapse CR/LF/TAB to a single space so each entry stays on one line.
        normalized = (
            text.replace("\r\n", " ")
            .replace("\r", " ")
            .replace("\n", " ")
            .replace("\t", " ")
        )
        # Replace double-quote with single-quote so the outer "..." wrappers
        # used in the prompt aren't terminated mid-value.
        normalized = normalized.replace('"', "'")
        # Collapse runs of whitespace introduced by the swaps.
        while "  " in normalized:
            normalized = normalized.replace("  ", " ")
        return normalized.strip()

    def _build_field_notes_prompt(
        self, facts: list[str], headline: str, dateline: Optional[str] = None
    ) -> str:
        """Compose the full Grok prompt for Walter's Field Notes image.

        Bypasses the cat-subject anchor and eye-catch anchor — this image is
        a notepad photo, not a Walter portrait. Facts are quoted and the
        model is instructed to render them exactly as written.

        Dynamic text (facts, headline, dateline) is sanitized to swap
        embedded double-quotes for single-quotes and collapse newlines so
        the prompt's "..." literal wrappers remain structurally intact.
        """
        # Build the dateline line that appears under the FIELD NOTES header.
        # Kept short — the page is text-dense already.
        dateline_line = ""
        if dateline:
            safe_dateline = self._sanitize_for_prompt(dateline)
            dateline_line = (
                f' Beneath the header, a smaller dateline reads exactly: '
                f'"{safe_dateline}".'
            )

        # Numbered entries, each on its own line in the prompt for clarity.
        entries = []
        for idx, fact in enumerate(facts, start=1):
            safe_fact = self._sanitize_for_prompt(fact)
            entries.append(f'    {idx}. "{safe_fact}"')
        entries_block = "\n".join(entries)

        story_line = ""
        if headline:
            safe_headline = self._sanitize_for_prompt(headline)
            story_line = (
                f' below a smaller subtitle that reads exactly: '
                f'"{safe_headline}"'
            )

        return (
            f"{_FIELD_NOTES_STYLE_SPEC}"
            f"\n\nText content on the page, rendered EXACTLY as written below "
            f"(do not paraphrase, do not abbreviate, do not add or drop words, "
            f"do not change punctuation, do not correct spelling). All page "
            f"text appears in ALL-CAPS BLOCK PRINT.\n\n"
            f'Top of page, larger and underlined: "FIELD NOTES".'
            f"{dateline_line}"
            f"{story_line}"
            f"\n\n{len(facts)} numbered entries follow, each prefixed with a dash, "
            f"in the order shown, written exactly:\n\n"
            f"{entries_block}\n\n"
            f"Bottom-right corner of the page: a black inked cat's paw-print "
            f"stamp next to a flowing cursive signature reading exactly: "
            f'"— Walter".'
        )

    def generate_field_notes(
        self,
        facts: list[str],
        headline: str = "",
        dateline: Optional[str] = None,
        save_path: str = "temp_field_notes.png",
        aspect_ratio: str = "4:5",
    ) -> tuple[Optional[str], Optional[str]]:
        """Generate a "Walter's Field Notes" reply image.

        A locked-style overhead flatlay of a spiral-bound reporter's pad with
        the supplied facts rendered as numbered entries and a paw-print
        signature. Designed to be Walter Croncat's iconic visual signature
        on consensus-facts dossier replies.

        Args:
            facts: 1-3 consensus-fact strings to render verbatim on the page.
                Each fact should already be trimmed of attribution tails
                like "— reported by CNBC and NPR" before being passed here.
            headline: Optional short story name shown beneath the FIELD NOTES
                header (e.g. "San Diego Mosque Shooting"). Pass an empty
                string to omit.
            dateline: Optional date string (e.g. "May 19, 2026") shown beneath
                the header. Pass None to omit.
            save_path: Where to write the downloaded image.
            aspect_ratio: Image aspect ratio. Defaults to 4:5 (portrait, matches
                a real notepad page and renders well inline on Bluesky).
                Falls back to 3:2 if an unsupported ratio is passed.

        Returns:
            (image_path, anchored_prompt). Both None on failure.
        """
        if not facts:
            print("✗ Field notes generation skipped: no facts provided.")
            return None, None
        if aspect_ratio not in self.SUPPORTED_ASPECT_RATIOS:
            print(
                f"⚠️  field_notes aspect_ratio={aspect_ratio!r} not supported; "
                f"falling back to 3:2"
            )
            aspect_ratio = "3:2"

        prompt = self._build_field_notes_prompt(facts, headline, dateline=dateline)
        try:
            print(f"🎨 Generating field-notes image ({aspect_ratio}, {len(facts)} facts)...")
            response = self.client.images.generate(
                model=self.model,
                prompt=prompt,
                n=1,
                extra_body={
                    "aspect_ratio": aspect_ratio,
                    "resolution": self.resolution,
                },
            )
            image_url = response.data[0].url if response.data else None
            if not image_url:
                print("✗ Field notes generation returned no URL")
                return None, None
            self._download(image_url, save_path)
            print(f"✓ Field notes image saved: {save_path}")
            return save_path, prompt
        except Exception as e:
            print(f"✗ Field notes generation failed: {e}")
            return None, None
