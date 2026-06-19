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


# Photographer-flavor rotation. One named reference is picked per call and
# stacked AFTER the post-type style anchor. Concrete photographer names are
# tokens the model recognizes — rotating them is the single highest-leverage
# diversifier the locked anchor can apply without touching the dynamic
# Haiku-written prompt. Picked at the anchor stage (not by Haiku) so the
# Haiku doesn't try to "match" the name and instead just provides the
# scene; the photographer-flavor steers the rendering pass.
import random as _random  # noqa: E402

_PHOTOGRAPHER_FLAVORS: dict[str, list[str]] = {
    "REPORT": [
        "Annie Leibovitz portrait stagecraft. ",
        "Steve McCurry color saturation and locked eye contact. ",
        "James Nachtwey on-the-ground photojournalism grit. ",
        "Henri Cartier-Bresson decisive-moment timing. ",
        "Magnum Photos editorial discipline. ",
        "Eve Arnold candid intimacy. ",
    ],
    "META": [
        "Gregory Crewdson cinematic dread and tableau staging. ",
        "Saul Leiter rain-on-glass color abstraction. ",
        "Edward Hopper isolation and quiet-hour mood. ",
        "Andreas Gursky orderly scale. ",
    ],
    "ANALYSIS": [
        "Tim Walker surreal scale and dreamlike props. ",
        "Wes Anderson symmetrical composition and pastel discipline. ",
        "Sally Mann tonal richness and quiet weight. ",
        "Saul Steinberg illustrative wit. ",
    ],
    "BULLETIN": [
        "Don McCullin war-photograph grain and weight. ",
        "Robert Capa decisive-moment chaos. ",
        "Susan Meiselas conflict-zone urgency. ",
    ],
    "PRIMARY": [
        "Irving Penn studio austerity. ",
        "Richard Avedon archival formal portraiture. ",
        "Yousuf Karsh formal gravitas. ",
    ],
    "CORRECTION": [
        "Saul Leiter quiet restraint. ",
        "Robert Frank candid honesty. ",
    ],
}


def _pick_photographer_flavor(post_type: Optional[str]) -> str:
    """Pick one photographer-style reference for the given post type.
    Returns "" for unknown / None post types so the legacy / default path
    isn't perturbed (and so the no-post-type test invariants still hold)."""
    if not post_type:
        return ""
    flavors = _PHOTOGRAPHER_FLAVORS.get(post_type)
    if not flavors:
        return ""
    return _random.choice(flavors)


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
    "CRITICAL HANDWRITING STYLE — this is field-scribbled notes from a "
    "working reporter, NOT calligraphy, NOT print-perfect, NOT neat, NOT a "
    "typography sample. Hurried ALL-CAPS BLOCK PRINT in black ballpoint or "
    "marker, the way someone writes while standing in the field with the "
    "notebook on their knee. Letter shapes are deliberately inconsistent — "
    "some letters bigger than others, baselines drift up and down within a "
    "single line, letter spacing is uneven, some letters lean left while "
    "others lean right, ink pressure varies (some strokes thick, some thin, "
    "occasional darker smudge or pen drag). The left margin is uneven, "
    "lines occasionally bump or cross the rule. The header underline is a "
    "quick, slightly crooked hand-drawn slash. Each numbered entry begins "
    "with a dash that varies slightly in length. Overall the page looks "
    "rushed and authentic — the OPPOSITE of careful penmanship. "
    "Small black inked paw-print stamps in the TWO TOP corners as a subtle "
    "decorative motif (4 toe pads + 1 main pad each, slightly imperfect "
    "ink, not perfectly aligned). "
    "The image frame is 3:2 landscape and the notepad is taller than that — "
    "the bottom edge of the notepad may extend below the frame and that is "
    "fine. However the signature MUST land inside the frame: at the "
    "bottom-right of the visible area, a larger single black inked cat's "
    "paw-print stamp next to a slightly scrawled cursive signature with an "
    "em-dash followed by the word Walter. The signature must be fully "
    "visible — do not crop it off. "
    "No additional doodles beyond what's specified, no coffee stains, no "
    "margin notes, no other decorations. Sparse, hurried, journalistic. "
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

    # Valid aspect ratios Grok actually accepts. Verified against API error
    # response on 2026-05-20: the field-notes path picked "4:5" (a
    # Bluesky-favored portrait ratio) and Grok rejected it at runtime,
    # listing the supported set below. "4:5" was previously in this set
    # but never exercised because the default config used 3:2 — removed
    # to prevent the bug from resurfacing.
    SUPPORTED_ASPECT_RATIOS = {
        "1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2",
        "9:19.5", "19.5:9", "9:20", "20:9", "1:2", "2:1", "auto",
    }

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
        self.model = image_cfg.get("model", "grok-imagine-image-quality")
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

        # Watermark compositor config — applies the Walter signature asset
        # (docs/images/walter-signature.png) to every generated post image
        # with contrast-aware tinting. Field-notes images are NOT watermarked
        # by this path (they use generate_field_notes, which already renders
        # a paw + signature as part of the Grok prompt).
        wm_cfg = image_cfg.get("watermark") or {}
        self.watermark_enabled = bool(wm_cfg.get("enabled", True))
        self.watermark_opacity = float(wm_cfg.get("opacity", 0.60))
        self.watermark_size_ratio = float(wm_cfg.get("size_ratio", 0.20))
        self.watermark_corner = wm_cfg.get("corner", "bottom-right")

    def _anchor_prompt(self, prompt: str, post_type: Optional[str] = None) -> str:
        """Compose the full prompt: subject anchor + eye-catch anchor +
        post-type style anchor + (rotating) photographer flavor + the
        dynamic prompt.

        Kept as its own method so tests can introspect the composition
        without needing to mock the OpenAI client.
        """
        style = POST_TYPE_STYLE_ANCHORS.get(post_type, _DEFAULT_STYLE_ANCHOR) if post_type else _DEFAULT_STYLE_ANCHOR
        flavor = _pick_photographer_flavor(post_type)
        return f"{_SUBJECT_ANCHOR}{_EYECATCH_ANCHOR}{style}{flavor}{prompt}"

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

    def _maybe_watermark(self, image_path: str) -> None:
        """Apply the Walter signature watermark to image_path in-place if
        the feature is enabled. Best-effort: swallows errors so a watermark
        failure never breaks the post pipeline (we'd rather post an
        unwatermarked image than no image)."""
        if not self.watermark_enabled:
            return
        try:
            try:
                from watermark import apply_watermark
            except ImportError:
                from src.watermark import apply_watermark  # pragma: no cover
            apply_watermark(
                image_path,
                opacity=self.watermark_opacity,
                size_ratio=self.watermark_size_ratio,
                corner=self.watermark_corner,
            )
            print(f"✓ Watermark applied (opacity={self.watermark_opacity})")
        except Exception as e:
            print(f"⚠️  Watermark step failed (continuing unwatermarked): {e}")

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
                        self._maybe_watermark(save_path)
                        return save_path, anchored_prompt
                    print(f"✗ QC failed (attempt {attempt}/{attempts}): {reason}")
                    if attempt < attempts:
                        print("   Retrying generation...")
                        continue
                    print("   Retries exhausted — returning the last attempt anyway")
                    self._maybe_watermark(save_path)
                    return save_path, anchored_prompt
                else:
                    self._maybe_watermark(save_path)
                    return save_path, anchored_prompt

            return None, None

        except Exception as e:
            print(f"✗ Image generation failed: {e}")
            return None, None

    @staticmethod
    def _sanitize_for_prompt(text: str) -> str:
        """Normalize dynamic text for inline prompt embedding. Collapses
        internal newlines/tabs to single spaces so each embedded value
        remains a one-liner, then strips surrounding whitespace.

        Double quotes are preserved: the prompt no longer wraps values in
        "..." structural literals, and the page-text rules explicitly allow
        source quotes to render exactly as written.
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
        # Collapse runs of whitespace.
        while "  " in normalized:
            normalized = normalized.replace("  ", " ")
        return normalized.strip()

    def _build_field_notes_prompt(
        self, facts: list[str], headline: str, dateline: Optional[str] = None
    ) -> str:
        """Compose the full Grok prompt for Walter's Field Notes image.

        Bypasses the cat-subject anchor and eye-catch anchor — this image is
        a notepad photo, not a Walter portrait. The model is instructed to
        render the embedded text exactly as written.

        Dynamic payloads (facts, headline, dateline) are sanitized to
        collapse newlines into spaces and are inserted between explicit
        newline delimiters so the surrounding instructions can't be read
        as part of the literal text to render.
        """
        # Build the dateline line that appears under the FIELD NOTES header.
        # NOTE: dynamic text below is passed WITHOUT surrounding double-
        # quotes — earlier renders wrapped each value in "..." and Grok
        # transcribed the literal quote marks into the image, producing
        # mismatched / unterminated quotation marks. We tell Grok to render
        # "the following text and nothing else" so the structural quotes
        # don't leak into the visual output.
        dateline_line = ""
        if dateline:
            safe_dateline = self._sanitize_for_prompt(dateline)
            # Newlines around {safe_dateline} delimit the literal payload
            # from the following instruction so the next sentence isn't
            # read as part of the rendered dateline text.
            dateline_line = (
                f"\nBeneath the header, a smaller dateline reads exactly the "
                f"following text and nothing else, on one line:\n"
                f"{safe_dateline}\n"
            )

        # Numbered + dash-prefixed entries, each on its own line in the
        # prompt for clarity. The dash is part of the locked style spec
        # ("Each numbered entry begins with a dash") and matches the
        # reference FIELD NOTES pad in the brand kit. Entries are NOT
        # wrapped in quotation marks here — see note on dateline_line.
        entries = []
        for idx, fact in enumerate(facts, start=1):
            safe_fact = self._sanitize_for_prompt(fact)
            entries.append(f"    - {idx}. {safe_fact}")
        entries_block = "\n".join(entries)

        story_line = ""
        if headline:
            safe_headline = self._sanitize_for_prompt(headline)
            # Newlines around {safe_headline} delimit the literal payload.
            story_line = (
                f"\nBelow that, a smaller subtitle that reads exactly the "
                f"following text and nothing else, on one line:\n"
                f"{safe_headline}\n"
            )

        return (
            f"{_FIELD_NOTES_STYLE_SPEC}"
            f"\n\nText content on the page, rendered EXACTLY as written below "
            f"(do not paraphrase, do not abbreviate, do not add or drop words, "
            f"do not change punctuation, do not correct spelling, and DO NOT "
            f"add any extra quotation marks of any kind around the text — "
            f"only use quotation marks if they appear in the source text "
            f"itself as part of a quoted phrase). All page text appears in "
            f"ALL-CAPS BLOCK PRINT.\n\n"
            f"Top of page, larger and underlined: FIELD NOTES."
            f"{dateline_line}"
            f"{story_line}"
            f"\n\n{len(facts)} numbered entries follow, each prefixed with a dash, "
            f"in the order shown, written exactly (no surrounding quotation marks):\n\n"
            f"{entries_block}\n\n"
            f"Bottom-right corner of the page: a black inked cat's paw-print "
            f"stamp next to a slightly scrawled cursive signature consisting "
            f"of an em-dash followed by the word Walter."
        )

    def generate_field_notes(
        self,
        facts: list[str],
        headline: str = "",
        dateline: Optional[str] = None,
        save_path: str = "temp_field_notes.png",
        aspect_ratio: str = "3:2",
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
            aspect_ratio: Image aspect ratio. Defaults to 3:2 (landscape,
                matches the main post image so the field-notes reply renders
                inline consistently on both Bluesky and X — portrait images
                were not rendering on X in the first live runs). The notepad
                page is taller than 3:2; the style spec accepts a bottom-edge
                crop and requires the signature to remain in-frame. Falls
                back to 3:2 if an unsupported ratio is passed. Note: 4:5 is
                NOT supported by Grok — verified via API error on 2026-05-20.

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
