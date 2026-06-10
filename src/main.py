"""
Mewscast - AI-powered X news reporter cat bot
Main entry point for scheduled posts and automation
"""
import json
import os
import re
import sys
import random
import time
import yaml
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

from content_generator import ContentGenerator
from twitter_bot import TwitterBot
from bluesky_bot import BlueskyBot
from news_fetcher import NewsFetcher
from image_generator import ImageGenerator
from post_tracker import PostTracker

# --- Walter Croncat journalism workflow imports --------------------------
# These modules are pure-Python and import with zero side-effects at module
# level; the whole pipeline is only instantiated inside post_journalism_cycle
# so the existing modes (scheduled/reply/both/special) are unaffected when
# the journalism workflow is disabled.
from dossier_store import DossierStore, DraftPost, PostType, SIGN_OFFS, StoryDossier
from trend_detector import TrendDetector, TrendCandidate, _extract_proper_nouns, _stable_story_id
from story_triage import StoryTriage
from source_gatherer import _FLUFF_PREFIXES, _SUFFIX_STRIP_RE, SourceGatherer
from primary_source_finder import PrimarySourceFinder
from meta_analyzer import MetaAnalyzer
from post_composer import PostComposer
from verification_gate import (
    CHAR_LIMIT_REASON_PREFIX,
    VerificationGate,
    VerificationResult,
)
from draft_analyzer import analyze_draft, print_analysis
from dossier_renderer import (
    bluesky_web_url,
    render_dossier_page,
    render_feed_json,
    render_index_page,
    render_sitemap,
)
from r2_uploader import upload_dossier_image


def _load_config():
    """Load the project config.yaml and return parsed dict."""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Walter Croncat journalism workflow — Stage 7 orchestrator
# ---------------------------------------------------------------------------

_JOURNALISM_POST_TYPE_ALIASES = {
    "brief": PostType.REPORT,
    "report": PostType.REPORT,
    "meta": PostType.META,
    "analysis": PostType.ANALYSIS,
    "bulletin": PostType.BULLETIN,
    "correction": PostType.CORRECTION,
    "primary": PostType.PRIMARY,
}


def _inline_dossier_url_into_meta(
    text: str,
    dossier_url: str,
    sign_off: str | None,
) -> str:
    """Return META post text with the dossier URL inlined before the sign-off.

    META posts are long-form (6500-char budget) and the self-reply pattern
    added a second tweet that looked redundant in the profile feed — the
    first line of a META post is often visible in the feed view while the
    rest is collapsed behind "Show more". Inlining the URL makes the
    dossier link part of the same post, so no self-reply is needed.

    Shape:
        {body text}

        Full dossier: {url}

        {sign_off}

    If the draft doesn't end with the expected sign-off (shouldn't happen
    — the verification gate enforces it — but defend anyway), the URL is
    appended to the end.
    """
    if sign_off and text.rstrip().endswith(sign_off):
        body = text.rstrip()[: -len(sign_off)].rstrip()
        return f"{body}\n\nFull dossier: {dossier_url}\n\n{sign_off}"
    return f"{text.rstrip()}\n\nFull dossier: {dossier_url}"


def _compose_dossier_reply_text(
    brief_data: dict | None,
    outlet_count: int,
) -> str:
    """Short self-reply line that introduces the dossier link.

    Picks a template based on what the brief flagged — disagreements,
    missing context, or multi-outlet framing differences. Falls back
    to a generic line when the brief is empty or none of the hooks
    apply. Pure function; no I/O.

    Callers append a newline + dossier URL after this string to form
    the full reply body. Budget: ~240 chars, leaving room for the URL.
    """
    brief_data = brief_data or {}
    disagreements = brief_data.get("disagreements") or []
    missing_context = brief_data.get("missing_context") or []
    framing = brief_data.get("framing_analysis") or {}

    # Avoid ungrammatical "1 outlets". Below 2, use a plural-neutral phrase.
    count_phrase = f"{outlet_count} outlets" if outlet_count >= 2 else "these outlets"

    if disagreements:
        return f"Where {count_phrase}' accounts diverge — full dossier:"
    if missing_context:
        return f"What {count_phrase} reported — and what they left out:"
    if len(framing) >= 3:
        n = outlet_count if outlet_count >= 2 else len(framing)
        return f"{n} outlets, {n} framings — cross-outlet breakdown:"
    return "Full cross-outlet dossier on this story:"


def _compose_platform_variant(
    post_composer,
    verification_gate,
    brief,
    dossier: StoryDossier,
    post_type: PostType,
    canonical: DraftPost,
    platform: str,
) -> DraftPost:
    """Compose a platform-specific initial-post variant, verified independently.

    The per-platform fork: Bluesky keeps the canonical `draft`; X gets its own
    text composed with platform-specific guidance (prompts/platform_<p>.md).
    Structural verification (sign-off, char limit, forbidden words) runs on the
    variant; the expensive fabrication analyzer does NOT — the canonical already
    cleared it and the variant restates the same facts from the same brief.

    On any compose/verify failure — after one retry with the gate feedback —
    this falls back to the canonical draft, so the platform always publishes
    valid text and Bluesky's quality bar is never undercut by the X experiment.
    """
    def _try(reasons=None):
        d = post_composer.compose(
            brief=brief, dossier=dossier, post_type=post_type,
            platform=platform, retry_reasons=reasons,
        )
        return d, verification_gate.verify(d, dossier, brief=brief)

    try:
        d, g = _try()
        if g.passed:
            return d
        print(f"[journalism] {platform} variant failed gate: {g.failures}; retrying")
        retry = list(g.failures) + [
            f"{CHAR_LIMIT_REASON_PREFIX} draft MUST be <= "
            f"{post_composer._effective_max_length(post_type)} chars"
        ]
        d, g = _try(retry)
        if g.passed:
            return d
        print(f"[journalism] {platform} variant still failing ({g.failures}); "
              f"falling back to canonical draft")
    except Exception as e:
        print(f"[journalism] {platform} variant compose error ({e}); "
              f"falling back to canonical draft")
    return canonical


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _safe_filename_component(text: str) -> str:
    """Make a story id / post type safe for use in a filename."""
    if not text:
        return "unknown"
    out = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("-")
    return "".join(out)


# Shot-type rotation table. Keeps the brand consistent (Walter, press badge,
# news-broadcast vibe) while breaking up the visual sameness of always-centered
# eye-level medium portraits. Weighted so CLASSIC_PORTRAIT remains the most
# common baseline (~30%) and the four genuine variations split the rest.
# Tuning rule: if a shot type starts feeling repetitive, reweight here without
# touching prompt logic. To kill a shot type entirely set its weight to 0.
_SHOT_TYPES: list[tuple[str, int, str]] = [
    (
        "CLASSIC_PORTRAIT", 30,
        "Medium-shot portrait, Walter centered and prominent in frame, "
        "press badge clearly visible, eye-level lens, looking toward camera. "
        "The current default — use it for most cycles."
    ),
    (
        "WIDE_ESTABLISHING", 18,
        "Wide establishing shot — Walter SMALL in the frame, the LOCATION "
        "dominates. Think editorial photojournalism: Walter is a recognizable "
        "speck in the corner or lower third, while the architecture / scene / "
        "weather fills two-thirds of the canvas. Press badge readable but tiny. "
        "Use this when the location IS the story."
    ),
    (
        "LOW_ANGLE_HERO", 18,
        "Low-angle hero shot — camera at paw level looking UP at Walter, "
        "with a tall structure (column, building, podium) rising behind him. "
        "Slight wide-angle distortion, dramatic sky. Walter looks authoritative, "
        "almost statuesque. Press badge prominent because the camera is below it."
    ),
    (
        "DETAIL_NO_FULL_CAT", 17,
        "Detail / object-focused shot — Walter is NOT fully in frame. Show only "
        "his paws on a press notebook, his press badge in extreme close-up with "
        "a story element reflected in the metal, his glasses + microphone on a "
        "desk, or a partial profile (one eye + ear + badge edge). The OBJECTS "
        "of journalism are the subject; Walter is implied. Cinematic depth of "
        "field, very tight crop. Excellent for META and PRIMARY post types."
    ),
    (
        "THROUGH_THE_LENS", 17,
        "Frame-within-a-frame — the viewer sees Walter THROUGH something: a "
        "TV monitor bezel with broadcast overlay, a video viewfinder reticle, "
        "a window with raindrops, a doorway, the space between two columns. "
        "Adds 'live from / on assignment' energy. Walter can be medium or wide "
        "inside the inner frame; the OUTER frame is the visual signature."
    ),
]


def _pick_shot_type() -> tuple[str, str]:
    """Roll a shot type from _SHOT_TYPES using the configured weights.
    Returns (label, description). Independent random call per cycle so
    different cycles get different shots; not seeded by story_id (we want
    variety even within a single news event covered across days)."""
    import random as _random
    labels = [t[0] for t in _SHOT_TYPES]
    weights = [t[1] for t in _SHOT_TYPES]
    descriptions = {t[0]: t[2] for t in _SHOT_TYPES}
    chosen = _random.choices(labels, weights=weights, k=1)[0]
    return chosen, descriptions[chosen]


# Cat-behavior rotation. Survey of recent posts showed Walter defaulting to
# "standing centered, looking at camera, expression focused" on nearly every
# render — the journalism_image.md cat-behavior list existed but the Haiku
# wasn't actually picking from it. This list is now an explicit per-cycle
# injection (like shot type) so a concrete behavior is committed BEFORE the
# Haiku writes the prompt body.
#
# Mix of "dignified" behaviors (Walter as poised reporter) and "candid"
# behaviors (Walter as a real cat caught mid-action). Candid is the variance
# unlocker — it's what breaks the stiff-mascot pose.
_CAT_BEHAVIORS: list[tuple[str, int]] = [
    # Dignified / reporter-mode behaviors
    ("Sniffing intently at the focal object, nose nearly touching it", 5),
    ("Peering around a corner or over an edge at the scene", 5),
    ("Stalking low to the ground, eyes locked on a target in frame", 4),
    ("Paw raised mid-step, frozen as if he just heard something", 4),
    ("Mid-stride toward the action, ears forward, tail straight up", 5),
    ("Head tilted slightly, intrigued by what's in front of him", 4),
    ("Tail in a tense S-curve, head turned three-quarters toward camera", 4),
    # Candid / cat-being-a-cat behaviors (the variance unlockers)
    ("Mid-yawn, mouth open wide, eyes squeezed shut", 3),
    ("Batting a paw at a dangling microphone, wire, or light cord", 3),
    ("Sitting smugly ON TOP of the story's papers / documents / evidence", 3),
    ("Grooming a paw with detached calm while chaos unfolds behind him", 3),
    ("Curled up asleep on top of the story's key evidence", 2),
    ("Mid-paw-swat at a coffee cup, mug captured mid-tip", 2),
    ("Caught mid-blink, one eye closed in slow-shutter timing", 3),
    ("Ears flat back, hackles slightly raised — wary of the scene", 2),
]


def _pick_cat_behavior() -> str:
    """Roll a cat behavior from _CAT_BEHAVIORS using weights. Returns the
    behavior string. Independent random call per cycle."""
    import random as _random
    behaviors = [b[0] for b in _CAT_BEHAVIORS]
    weights = [b[1] for b in _CAT_BEHAVIORS]
    return _random.choices(behaviors, weights=weights, k=1)[0]


# Badge-visibility rotation. The "PRESS / Walter Croncat" badge appeared in
# 8/8 of the prior survey images — locking visual identity to a label
# instead of to the cat's bearing and the scene. Visibility now varies by
# shot type with a random factor: badge-as-default-on becomes badge-when-
# it-actually-helps.
def _pick_badge_visibility(shot_label: str) -> bool:
    """Decide whether Walter's press badge appears in this image.
    Deterministic-ish by shot type with a random factor."""
    import random as _random
    # DETAIL never shows the full cat, so badge is incoherent
    if shot_label == "DETAIL_NO_FULL_CAT":
        return False
    # WIDE: Walter is tiny — badge would just be a pixel smear
    if shot_label == "WIDE_ESTABLISHING":
        return _random.random() < 0.20
    # THROUGH_THE_LENS: outer frame is the visual signature; let it carry
    if shot_label == "THROUGH_THE_LENS":
        return _random.random() < 0.25
    # CLASSIC_PORTRAIT / LOW_ANGLE_HERO: Walter is the focal point
    return _random.random() < 0.45


# Chyron (broadcast-news lower-third) rotation. Adds a TV-broadcast layer to
# ~30% of images. Grok renders text well — this turns the image into a
# self-explanatory broadcast still: punchy headline, channel bug, optional
# LIVE indicator. Skipped for CORRECTION (the format would undercut the
# sober tone) and PRIMARY (document focus, not broadcast).
def _pick_chyron(post_type: str) -> bool:
    """Decide whether to render a broadcast chyron on this image.

    Always on, except for CORRECTION (the broadcast-graphic format would
    undercut the sober correction tone) and PRIMARY (document focus, not a
    broadcast still). Previously a ~30% roll; made unconditional so every
    eligible post ships as a self-explanatory WCN broadcast still."""
    if post_type in ("CORRECTION", "PRIMARY"):
        return False
    return True


def _generate_journalism_image(
    draft: DraftPost, dossier: StoryDossier, save_path: str = "temp_image.png"
) -> tuple:
    """Generate a post-type-aware image for a journalism post.

    Returns (image_file_path, anchored_prompt) on success, (None, None) on
    failure. The `anchored_prompt` is the FULL prompt sent to the image
    model — subject + eye-catch + style-anchor + dynamic prompt — captured
    for audit. Best-effort: never raises.
    """
    try:
        print(f"[journalism] generating {draft.post_type.value}-style image...")
        article_body = dossier.articles[0].body if dossier.articles else ""
        article_section = (
            f"\nFULL ARTICLE CONTENT (extract visual details):\n{article_body[:3000]}\n"
            if article_body else ""
        )

        # Roll a shot type. Keeps post-type vibes (REPORT-on-location vs META-
        # at-the-desk) intact while varying the camera angle / framing / crop.
        shot_label, shot_desc = _pick_shot_type()
        cat_behavior = _pick_cat_behavior()
        badge_visible = _pick_badge_visibility(shot_label)
        chyron_visible = _pick_chyron(draft.post_type.value)
        print(
            f"[journalism] image rolls: shot={shot_label} "
            f"behavior={cat_behavior[:40]!r} badge={badge_visible} "
            f"chyron={chyron_visible}"
        )

        badge_instruction = (
            "Walter wears a small press badge clipped to his collar — render "
            "it as a SMALL plain rectangular tag, not a focal element. Do NOT "
            "attempt readable text on the badge (text will be composited on "
            "in post-processing)."
            if badge_visible
            else "No press badge visible on Walter in this shot. His identity "
            "comes from his bearing, his behavior, and the scene around him "
            "— not from a label. (A press credential will be added in "
            "post-processing if needed.)"
        )

        chyron_instruction = (
            "BROADCAST CHYRON: render a news-broadcast lower-third graphic "
            "across the bottom of the frame as if this image is a still from "
            "the WCN (Walter Croncast Network) broadcast. The chyron should "
            "include: a punchy 3-7 WORD headline derived from the story (NOT "
            "the full topic, a broadcaster's short headline) in bold sans-"
            "serif; a small WCN channel bug in one corner; optionally a "
            "ticker tape with a fragment of secondary text below the main "
            "headline. Style: modern CNN/MSNBC-style chyron with a colored "
            "bar (red for breaking, navy for standard, gold for analysis). "
            "Render text crisply and legibly — Grok handles short broadcast-"
            "graphic text well. This is part of the visual story, not an "
            "overlay afterthought."
            if chyron_visible
            else "No broadcast chyron in this image."
        )

        img_prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "prompts", "journalism_image.md"
        )
        with open(img_prompt_path, "r", encoding="utf-8") as f:
            img_template = f.read()

        img_request = img_template.replace("{post_type}", draft.post_type.value)
        img_request = img_request.replace("{topic}", dossier.headline_seed[:200])
        img_request = img_request.replace("{draft_text}", draft.text[:500])
        img_request = img_request.replace("{article_section}", article_section)
        img_request = img_request.replace("{shot_type}", shot_label)
        img_request = img_request.replace("{shot_type_description}", shot_desc)
        img_request = img_request.replace("{cat_behavior}", cat_behavior)
        img_request = img_request.replace("{badge_instruction}", badge_instruction)
        img_request = img_request.replace("{chyron_instruction}", chyron_instruction)

        from anthropic import Anthropic as _Anthropic
        _img_client = _Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        _img_resp = _img_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": img_request}],
        )
        image_prompt = _img_resp.content[0].text.strip().strip('"').strip("'")
        # Budget raised to 800 as part of A5 overhaul — matches the legacy
        # content_generator.generate_image_prompt path.
        if len(image_prompt) > 800:
            image_prompt = image_prompt[:800]
        print(f"[journalism] image prompt ({draft.post_type.value}): {image_prompt[:100]}...")

        img_gen = ImageGenerator()
        # Pass post_type so the generator can pick the matching style anchor.
        # Capture the FULL anchored prompt (subject + eye-catch + style +
        # dynamic) and propagate it up — audit history saves what was actually
        # sent to the model, not the pre-anchor Claude suggestion.
        image_path, anchored_prompt = img_gen.generate_image(
            image_prompt,
            save_path=save_path,
            post_type=draft.post_type.value,
        )
        return image_path, anchored_prompt
    except Exception as e:
        print(f"[journalism] image generation failed (continuing): {e}")
        return None, None


def _generate_field_notes_image_if_eligible(
    brief_dict: dict,
    headline: str,
    story_id: str,
    journalism_cfg: dict,
    dossier_store=None,
) -> Optional[str]:
    """Decide eligibility and (if eligible) build the Field Notes image
    that will become the visual for both the Bluesky and X dossier-link
    replies. Returns the local image path on success or None if the
    feature is disabled, gates fail, or generation errors.

    Generating once (vs. once per platform) saves a Grok call AND keeps
    the visual identical across platforms.

    Args:
        brief_dict: dossier brief as a dict (consensus_facts, confidence).
        headline: short story name for the subtitle. Truncated to 60 chars.
        story_id: dossier story_id; used for filename + audit persistence.
        journalism_cfg: the `journalism:` block from config.yaml.
        dossier_store: optional — when provided, the image and condensed
            facts are persisted into the dossier JSON for the audit trail.
    """
    field_notes_cfg = (journalism_cfg or {}).get("field_notes_reply") or {}
    if not field_notes_cfg.get("enabled", True):
        return None

    try:
        from field_notes import condense_facts_for_notebook, extract_top_facts
    except ImportError:
        from src.field_notes import (  # pragma: no cover
            condense_facts_for_notebook, extract_top_facts,
        )

    brief_dict = brief_dict or {}

    # Defensive config parsing — a typo'd string in config must not abort
    # the whole reply chain. On parse failure, fall back to safe defaults
    # so we still try field-notes rather than dropping straight to the
    # link-card fallback.
    try:
        min_conf = float(field_notes_cfg.get("min_confidence", 0.5))
    except (ValueError, TypeError):
        print("[journalism] field-notes: bad min_confidence in config; defaulting to 0.0")
        min_conf = 0.0
    try:
        min_facts = int(field_notes_cfg.get("min_facts", 3))
    except (ValueError, TypeError):
        print("[journalism] field-notes: bad min_facts in config; defaulting to 3")
        min_facts = 3
    # Clamp to a positive floor. A configured 0 or negative would slip past
    # the gate (extract_top_facts returns [] for n<=0, and len([]) < n is
    # False for n<=0), propagating an empty fact list through the condense
    # LLM call before generate_field_notes finally bails.
    if min_facts < 1:
        min_facts = 1
    try:
        brief_conf = float(brief_dict.get("confidence", 0) or 0)
    except (ValueError, TypeError):
        brief_conf = 0.0

    if brief_conf < min_conf:
        print(f"[journalism] field-notes skip: confidence < {min_conf}")
        return None

    # Gate (have at least min_facts strong points) is decoupled from render
    # count (target 3 — three on a notepad reads right and fits the visual,
    # but render fewer if that's all the brief has). extract_top_facts is
    # all-or-nothing for n, so the gate and render counts are queried
    # separately; a min_facts of 1 or 2 must not silently require 3.
    gate_facts = extract_top_facts(brief_dict, n=min_facts)
    if len(gate_facts) < min_facts:
        print("[journalism] field-notes skip: insufficient consensus facts after cleanup")
        return None
    render_facts = extract_top_facts(brief_dict, n=3) or gate_facts
    facts = render_facts[:3]

    # Condense full consensus-facts into ~60-char notebook bullets so they
    # render legibly on the notepad page. The Haiku condenser preserves
    # entities/numbers/dates and falls back to the originals on any LLM
    # failure (caller doesn't need to handle that — empty result returns
    # the original list).
    bullets = condense_facts_for_notebook(facts, headline=headline)
    if not bullets or len(bullets) != len(facts):
        bullets = facts

    try:
        gen = ImageGenerator()
    except Exception as e:
        print(f"[journalism] field-notes ImageGenerator init failed: {e}")
        return None

    safe_id = _safe_filename_component(story_id)
    temp_path = f"temp_field_notes_{safe_id}.png"
    # Use Central time for the dateline so the runner timezone (UTC) doesn't
    # produce a "next day" date during the late-evening Central runs. The
    # dossier renderer already uses America/Chicago via ZoneInfo.
    try:
        from zoneinfo import ZoneInfo
        dateline = datetime.now(ZoneInfo("America/Chicago")).strftime("%B %d, %Y")
    except Exception:
        dateline = datetime.utcnow().strftime("%B %d, %Y")
    short_headline = (headline or "")[:60]

    fn_path, fn_prompt = gen.generate_field_notes(
        facts=bullets,
        headline=short_headline,
        dateline=dateline,
        save_path=temp_path,
    )
    if not fn_path:
        return None

    # Persist the field-notes image + prompt + facts alongside the dossier
    # so the audit trail captures both the original and condensed forms.
    if dossier_store is not None:
        try:
            html_dir = os.path.join(_project_root(), "docs", "dossiers")
            images_dir = os.path.join(html_dir, "images")
            os.makedirs(images_dir, exist_ok=True)
            dest = os.path.join(images_dir, f"{safe_id}.field-notes.png")
            if os.path.abspath(fn_path) != os.path.abspath(dest):
                import shutil
                shutil.copy2(fn_path, dest)
            raw = dossier_store.read_raw(story_id)
            if raw:
                raw["field_notes_image_path"] = f"images/{safe_id}.field-notes.png"
                raw["field_notes_prompt"] = fn_prompt
                raw["field_notes_facts"] = facts
                raw["field_notes_bullets"] = bullets
                dossier_store._write(story_id, raw)
        except Exception as e:
            print(f"[journalism] field-notes persist failed (continuing): {e}")

    return fn_path


def _post_bluesky_field_notes_reply(
    bluesky_bot,
    bluesky_uri: str,
    image_path: str,
    dossier_url: str,
) -> Optional[str]:
    """Post the pre-generated Field Notes image as the Bluesky dossier
    reply with the dossier URL clickable in the reply text. Returns the
    reply URI on success, or None on failure (callers fall back to the
    link-card reply).
    """
    reply_text = f"Walter's field notes from this story:\n{dossier_url}"
    try:
        result = bluesky_bot.reply_to_skeet_with_image(
            bluesky_uri, reply_text, image_path,
        )
        if result:
            uri = result.get("uri")
            print(f"[journalism] field-notes Bluesky reply ok: {uri}")
            return uri
    except Exception as e:
        print(f"[journalism] field-notes Bluesky reply failed: {e}")
    return None


def _post_x_field_notes_reply(
    twitter_bot,
    tweet_id: str,
    image_path: str,
    dossier_url: str,
) -> Optional[str]:
    """Post the pre-generated Field Notes image as the X dossier reply
    with the dossier URL inline (X auto-detects URLs in tweet text and
    makes them clickable). Returns the reply tweet id on success, or
    None on failure (callers fall back to text-only reply).
    """
    reply_text = f"Walter's field notes from this story:\n{dossier_url}"
    try:
        result = twitter_bot.reply_to_tweet_with_image(
            tweet_id, reply_text, image_path,
        )
        if result:
            reply_id = result.get("id")
            print(f"[journalism] field-notes X reply ok: {reply_id}")
            return reply_id
    except Exception as e:
        print(f"[journalism] field-notes X reply failed: {e}")
    return None


def _persist_dossier_image(
    draft: DraftPost,
    dossier_store,
    image_source_path: str,
    image_prompt: str | None = None,
) -> str | None:
    """Copy/persist an image to docs/dossiers/images/ and write the relative
    path — plus the full anchored prompt, if provided — into the dossier
    JSON. Returns the relative image path or None.

    The `image_prompt` argument should be the anchored prompt actually sent
    to the image model (not just the Claude-generated dynamic piece). It is
    written to `raw["image_prompt"]` for audit alongside `raw["image_path"]`.
    """
    try:
        html_dir = os.path.join(_project_root(), "docs", "dossiers")
        images_dir = os.path.join(html_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        safe_id = _safe_filename_component(draft.story_id)
        dest = os.path.join(images_dir, f"{safe_id}.png")

        # If source != dest, copy; otherwise it was already saved there
        if os.path.abspath(image_source_path) != os.path.abspath(dest):
            import shutil
            shutil.copy2(image_source_path, dest)

        rel_path = f"images/{safe_id}.png"

        # Upload the full-res image to Cloudflare R2 (the canonical public
        # store). Fail-soft: a failed upload never blocks publishing.
        upload_dossier_image(dest, key=f"{safe_id}.png")

        # Generate a small WebP thumbnail for the homepage card feed. Tiny
        # (~40 KB) and committed to git, so the feed grid loads fast without
        # pulling the multi-MB originals. Fail-soft — never blocks publishing.
        try:
            from thumbnailer import make_thumbnail
            thumb_dest = os.path.join(html_dir, "thumbs", f"{safe_id}.webp")
            make_thumbnail(dest, thumb_dest)
        except Exception as e:
            print(f"[journalism] thumbnail generation failed (continuing): {e}")

        # Write into dossier JSON so the renderer can find the image AND so
        # the audit trail captures the exact prompt that was sent to Grok.
        raw = dossier_store.read_raw(draft.story_id)
        if raw:
            raw["image_path"] = rel_path
            if image_prompt is not None:
                raw["image_prompt"] = image_prompt
            dossier_store._write(draft.story_id, raw)

        print(f"[journalism] dossier image persisted: {dest}")
        return rel_path
    except Exception as e:
        print(f"[journalism] image persist failed (continuing): {e}")
        return None


def _render_dossier_html(dossier_store, draft: DraftPost, dossier: StoryDossier) -> None:
    """Render dossier HTML page + write a metadata sidecar for the index +
    rebuild the index page. Used by both dry-run and publish paths."""
    try:
        dossier_data = dossier_store.read_raw(draft.story_id)
        if not dossier_data:
            return

        html_dir = os.path.join(_project_root(), "docs", "dossiers")
        os.makedirs(html_dir, exist_ok=True)

        safe_id = _safe_filename_component(draft.story_id)

        # 1. Render the individual dossier page
        dossier_html = render_dossier_page(dossier_data)
        html_path = os.path.join(html_dir, f"{safe_id}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(dossier_html)
        print(f"[journalism] dossier HTML written to {html_path}")

        # 2. Write a metadata sidecar (no article bodies — just index fields).
        # The full dossier JSON is gitignored (copyrighted bodies). This small
        # sidecar file IS committed so the index can be rebuilt on any runner
        # without needing the full JSON.
        import json as _json
        meta = {
            "story_id": draft.story_id,
            "headline_seed": dossier.headline_seed,
            "post_type": draft.post_type.value if draft.post_type else "",
            "confidence": dossier_data.get("brief", {}).get("confidence", 0),
            "published_at": dossier_data.get("post", {}).get("published_at")
                or dossier_data.get("saved_at", ""),
            "draft_text": draft.text,
        }
        meta_path = os.path.join(html_dir, f"{safe_id}.meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            _json.dump(meta, f, indent=2)

        # 2b. Write a brief sidecar for the outlet reply bot.
        # Contains the MetaAnalysisBrief + article outlet/URL list (no bodies).
        # The full dossier JSON is gitignored, but this lightweight sidecar IS
        # committed so the outlet reply bot can score meta-angle quality and
        # match outlet tweets from any CI runner.
        brief_data = dossier_data.get("brief", {})
        if brief_data:
            brief_sidecar = {
                "story_id": draft.story_id,
                "headline_seed": dossier.headline_seed,
                "brief": brief_data,
                "articles": [
                    {"outlet": a.get("outlet", ""), "url": a.get("url", ""),
                     "title": a.get("title", "")}
                    for a in dossier_data.get("dossier", {}).get("articles", [])
                ],
            }
            brief_path = os.path.join(html_dir, f"{safe_id}.brief.json")
            with open(brief_path, "w", encoding="utf-8") as f:
                _json.dump(brief_sidecar, f, indent=2)
            print(f"[journalism] brief sidecar written to {brief_path}")

        # 3. Rebuild the index from all .meta.json files in the directory
        import glob as _glob
        entries = []
        for mp in sorted(_glob.glob(os.path.join(html_dir, "*.meta.json"))):
            try:
                with open(mp, "r", encoding="utf-8") as f:
                    m = _json.load(f)
                # Wrap in the structure render_index_page expects
                entries.append({
                    "story_id": m.get("story_id", ""),
                    "dossier": {"headline_seed": m.get("headline_seed", "")},
                    "post": {
                        "draft": {"post_type": m.get("post_type", "")},
                        "published_at": m.get("published_at", ""),
                    },
                    "brief": {"confidence": m.get("confidence", 0)},
                })
            except Exception:
                continue

        index_html = render_index_page(entries)
        index_path = os.path.join(html_dir, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_html)
        print(f"[journalism] dossier index updated ({len(entries)} entries)")

        # 3b. Build feed.json — the manifest the homepage card grid reads.
        # One entry per dossier (newest first) with exactly the fields the
        # client renders: headline, date, post type/badge, confidence, and the
        # thumbnail + page URLs (relative to docs/ root). `thumb` is null when
        # no thumbnail exists; the client falls back to the site OG image.
        try:
            feed_json = render_feed_json(entries, os.path.join(html_dir, "thumbs"))
            feed_path = os.path.join(_project_root(), "docs", "feed.json")
            with open(feed_path, "w", encoding="utf-8") as f:
                f.write(feed_json)
            count = feed_json.count('"id"')
            print(f"[journalism] feed.json updated ({count} items)")
        except Exception as e:
            print(f"[journalism] feed.json generation failed (non-fatal): {e}")

        # 4. Regenerate sitemap.xml at docs/ root so new dossier pages
        # are discoverable by crawlers and agents. robots.txt at the same
        # level references it. Cheap to rebuild on every publish.
        try:
            sitemap_xml = render_sitemap(entries)
            sitemap_path = os.path.join(_project_root(), "docs", "sitemap.xml")
            with open(sitemap_path, "w", encoding="utf-8") as f:
                f.write(sitemap_xml)
            print(
                f"[journalism] sitemap.xml updated "
                f"({len(entries)} dossiers + static pages)"
            )
        except Exception as e:
            print(f"[journalism] sitemap generation failed (non-fatal): {e}")

    except Exception as e:
        print(f"[journalism] dossier HTML render failed (non-fatal): {e}")


_TRIAGE_DECISIONS_PATH = os.path.join(
    _project_root(), "docs", "reports", "triage_decisions.jsonl"
)


def _append_triage_decisions(decisions: list[dict]) -> None:
    """Append each triage decision as a single JSON line.

    Read back weekly by scripts/triage_review.py which summarises
    borderline drops, hard-rejects by rule, and which signals are
    most-often missing. The file is committed alongside the seen-stories
    list so the record survives across GHA runs.

    Failure is non-fatal: if we can't write the feedback log, the
    journalism pipeline still publishes.
    """
    if not decisions:
        return
    try:
        os.makedirs(os.path.dirname(_TRIAGE_DECISIONS_PATH), exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with open(_TRIAGE_DECISIONS_PATH, "a", encoding="utf-8") as f:
            for d in decisions:
                # Embed the timestamp on every row so later offline
                # analysis can group by day/week without needing any
                # auxiliary context.
                f.write(json.dumps({"ts": ts, **d}, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[journalism] could not append triage decisions: {e}")


def _maybe_repair_bulletin_hedge(
    draft: DraftPost,
    dossier: StoryDossier,
    max_length: int,
) -> Optional[DraftPost]:
    """Last-resort mechanical repair for a BULLETIN missing its hedge phrase.

    Called ONLY after the LLM retry budget has been exhausted and the
    composer still hasn't included a hedge. The hedge is a literal-string
    requirement ("not yet confirmed" / "not yet verified" / "also covered
    by") and we can safely append the standard form without changing any
    factual content.

    Returns a new DraftPost with the hedge appended, or None if the draft
    already has a hedge OR appending would blow the char limit OR the
    post is not a BULLETIN.

    The goal: publish a hedged BULLETIN beats rejecting the story entirely.
    Same philosophy as the missing-signoff softening.
    """
    from verification_gate import VerificationGate as _VG  # local to avoid cycles

    if draft.post_type != PostType.BULLETIN:
        return None

    text_lower = (draft.text or "").lower()
    if any(h in text_lower for h in _VG.HEDGE_PHRASES_FOR_BULLETIN):
        return None  # already hedged

    outlets = list(dossier.outlet_slants.keys())
    if not outlets:
        outlets = [a.outlet for a in dossier.articles if a.outlet]
    outlet = next((o for o in outlets if o), None)
    if not outlet:
        return None

    hedge_line = f"\n\nreported by {outlet}, not yet confirmed elsewhere."
    new_text = (draft.text or "").rstrip() + hedge_line
    if len(new_text) > max_length:
        return None  # can't fit within budget

    return DraftPost(
        text=new_text,
        post_type=draft.post_type,
        sign_off=draft.sign_off,
        story_id=draft.story_id,
        outlets_referenced=list(draft.outlets_referenced),
        primary_source_urls=list(draft.primary_source_urls),
        hedges_used=draft.hedges_used + ["not yet confirmed"],
    )


def _write_draft_file(
    drafts_dir: str,
    draft: DraftPost,
    dossier: StoryDossier,
    subfolder: str = "",
) -> str:
    """Write a DraftPost + dossier metadata to a markdown file under drafts/.

    Returns the absolute path that was written.
    """
    target_dir = os.path.join(drafts_dir, subfolder) if subfolder else drafts_dir
    os.makedirs(target_dir, exist_ok=True)

    story_slug = _safe_filename_component(draft.story_id)
    type_slug = _safe_filename_component(draft.post_type.value)
    filename = f"{story_slug}_{type_slug}.md"
    path = os.path.join(target_dir, filename)

    # Dedup outlets while preserving first-seen order. When a dossier has
    # two articles from the same outlet (e.g., two WaPo stories on the
    # same event), the draft header was showing "Reuters, WaPo, WaPo, AP"
    # which read as a cosmetic bug. Iteration 9 cleanup.
    _seen_outlets: set[str] = set()
    _unique_outlets: list[str] = []
    for _a in dossier.articles:
        if _a.outlet and _a.outlet not in _seen_outlets:
            _seen_outlets.add(_a.outlet)
            _unique_outlets.append(_a.outlet)
    outlets_list = ", ".join(_unique_outlets) or "(none)"
    primary_urls = ", ".join(p.url for p in dossier.primary_sources) or "(none)"

    dossier_meta = {
        "story_id": dossier.story_id,
        "headline_seed": dossier.headline_seed,
        "detected_at": dossier.detected_at,
        "article_count": len(dossier.articles),
        "primary_source_count": len(dossier.primary_sources),
        "outlet_slants": dossier.outlet_slants,
    }

    body = [
        f"# Croncat DRAFT — {draft.post_type.value}",
        "",
        f"- **story_id**: `{draft.story_id}`",
        f"- **post_type**: {draft.post_type.value}",
        f"- **sign_off**: {draft.sign_off!r}",
        f"- **outlets**: {outlets_list}",
        f"- **primary_sources**: {primary_urls}",
        "",
        "## Draft post",
        "",
        "```",
        draft.text,
        "```",
        "",
        "## Dossier metadata",
        "",
        "```json",
        json.dumps(dossier_meta, indent=2, default=str),
        "```",
        "",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(body))
    return path


def post_journalism_cycle(
    dry_run: bool = False,
    forced_post_type: PostType | None = None,
    topic: str | None = None,
) -> bool:
    """
    Run one cycle of the Walter Croncat journalism pipeline.

    Stages 1-7:
      1. Trend detection (TrendDetector)
      2. Story triage (StoryTriage)
      3. Source gather + primary source find (SourceGatherer, PrimarySourceFinder)
      4. Meta-analysis (MetaAnalyzer -> MetaAnalysisBrief)
      5. Post composition (PostComposer -> DraftPost)
      6. Verification gate (VerificationGate)
      7. Publish (TwitterBot / BlueskyBot) + record dossier

    Args:
      dry_run: if True, write the DraftPost to drafts/<story_id>_<post_type>.md
        instead of publishing. Useful for validation runs.
      forced_post_type: if provided, override the brief's suggested_post_type
        with this one (used by the `journalism brief|meta|bulletin|correction`
        CLI modes for deterministic per-type cycles).
      topic: if provided, skip Stages 1-2 (trend detection + triage) and use
        this as the headline_seed directly. Useful for testing the pipeline
        against a specific story.

    Returns:
      True: the cycle ran to completion. This may mean a post was published
        or a draft written, OR that there were no newsworthy candidates this
        cycle (a legitimate no-op — Cronkite himself would sometimes not have
        enough for a story).
      False: an actual error occurred — meta-analysis crashed, verification
        gate could not evaluate, the publish path failed on all platforms, etc.
    """
    print(f"\n{'=' * 60}")
    print(f"Walter Croncat journalism cycle — {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if dry_run:
        print("Mode: DRY RUN (drafts only, no publish)")
    if forced_post_type:
        print(f"Forced post type: {forced_post_type.value}")
    if topic:
        print(f"Manual topic: {topic[:100]}")
    print(f"{'=' * 60}\n")

    try:
        config = _load_config()
    except Exception as e:
        print(f"[journalism] failed to load config.yaml: {e}")
        return False

    journalism_cfg = config.get("journalism", {}) or {}
    # Config gate — if the master switch is off and this is NOT a dry run,
    # refuse to publish. Dry runs are always allowed because they are the
    # validation mechanism.
    if not journalism_cfg.get("enabled", False) and not dry_run:
        print(
            "[journalism] config.journalism.enabled is false; refusing to "
            "publish. Re-run with --dry-run to generate drafts only."
        )
        return False

    trend_cfg = journalism_cfg.get("trend_detection", {}) or {}
    triage_cfg = journalism_cfg.get("triage", {}) or {}
    gather_cfg = journalism_cfg.get("source_gather", {}) or {}
    meta_cfg = journalism_cfg.get("meta_analysis", {}) or {}
    composer_cfg = journalism_cfg.get("composer", {}) or {}
    verification_cfg = journalism_cfg.get("verification", {}) or {}
    dry_run_cfg = journalism_cfg.get("dry_run", {}) or {}

    max_candidates = int(trend_cfg.get("max_candidates", 15))
    use_llm_triage = bool(triage_cfg.get("use_llm", False))
    target_sources = int(gather_cfg.get("target_count", 7))
    max_fallback_candidates = int(gather_cfg.get("max_fallback_candidates", 3))
    meta_model = meta_cfg.get("model", "claude-opus-4-8")
    composer_model = composer_cfg.get("model", "claude-sonnet-4-6")
    max_length = int(composer_cfg.get("max_length", 280))
    long_form_max_length = int(composer_cfg.get("long_form_max_length", 4000))
    drafts_dir = os.path.join(_project_root(), dry_run_cfg.get("drafts_dir", "drafts"))
    os.makedirs(drafts_dir, exist_ok=True)

    registry_path = os.path.join(
        _project_root(),
        journalism_cfg.get("outlet_registry", "outlet_registry.yaml"),
    )

    # ---- Bot / fetcher init -----------------------------------------------
    # TwitterBot is initialized in publish mode for the POST /tweets call.
    # As of 2026-05-02, trend_detection.use_x_api is false — Stage 1 reads
    # are routed through NewsFetcher only (X reads were burning the
    # enrolled-account spend cap). The bot still gets constructed because
    # the publish-side post_tweet call needs it; if init fails (missing
    # creds), we fall through and the Bluesky path keeps publishing alone.
    twitter_bot = None
    bluesky_bot = None
    generator = None
    tracker = None

    print("[journalism] Initializing TwitterBot for publish path...")
    try:
        twitter_bot = TwitterBot()
    except Exception as e:
        print(f"[journalism] X bot init failed: {e} — Stage 1 will fall back to NewsFetcher")
        twitter_bot = None

    if not dry_run:
        print("[journalism] Initializing Bluesky + content generator for publish mode...")
        bluesky_bot = None
        for _attempt in range(1, 4):
            try:
                bluesky_bot = BlueskyBot()
                break
            except Exception as e:
                print(f"[journalism] Bluesky init attempt {_attempt}/3 failed: {type(e).__name__}: {e!r}")
                if _attempt < 3:
                    time.sleep(5 * _attempt)
        if bluesky_bot is None:
            print("[journalism] Bluesky init failed after 3 attempts; continuing X-only")
        if twitter_bot is None and bluesky_bot is None:
            print("[journalism] both X and Bluesky bots failed to init; aborting publish cycle")
            return False
        try:
            generator = ContentGenerator()
        except Exception as e:
            print(f"[journalism] ContentGenerator init failed: {e}")
            generator = None
        dedup_config = config.get("deduplication", {}) or {}
        tracker = PostTracker(config=dedup_config)

    print("[journalism] Initializing NewsFetcher + pipeline stages...")
    news_fetcher = NewsFetcher()
    dossier_store = DossierStore()

    # Honor trend_detection.use_x_api: when false, withhold the twitter_bot
    # so TrendDetector skips the billable X recent-search path and falls
    # straight through to NewsFetcher. The bot itself stays initialized for
    # the publish-side post_tweet calls.
    trend_use_x = bool(trend_cfg.get("use_x_api", True))
    trend_detector = TrendDetector(
        registry_path=registry_path,
        twitter_bot=twitter_bot if trend_use_x else None,
        news_fetcher=news_fetcher,
    )
    if not trend_use_x:
        print("[journalism] trend_detection.use_x_api=false — TrendDetector will use NewsFetcher only")
    story_triage = StoryTriage(use_llm=use_llm_triage)
    source_gatherer = SourceGatherer(
        news_fetcher=news_fetcher,
        registry_path=registry_path,
    )
    primary_finder = PrimarySourceFinder()
    meta_analyzer = MetaAnalyzer(model=meta_model)
    post_composer = PostComposer(
        model=composer_model,
        max_length=max_length,
        long_form_max_length=long_form_max_length,
    )
    verification_gate = VerificationGate(
        max_length=max_length,
        long_form_max_length=long_form_max_length,
    )

    # ---- Manual topic override: skip Stages 1-2 ----------------------------
    if topic:
        detected_at = datetime.now(timezone.utc).isoformat()
        manual_candidate = TrendCandidate(
            headline_seed=topic.strip(),
            detected_at=detected_at,
            source_signals=["manual"],
            engagement=0,
            story_id=_stable_story_id(topic.strip(), detected_at),
            source="manual",
        )
        print(f"[journalism] Skipping Stages 1-2 (manual topic)")
        print(f"[journalism] Synthetic candidate: {manual_candidate.headline_seed[:80]}...")
        candidate = manual_candidate
        passed = [manual_candidate]
    else:
        # ---- Stage 1: trend detection -----------------------------------------
        print(f"\n[journalism] Stage 1 — detecting trends (max_candidates={max_candidates})")
        candidates = trend_detector.detect_trends(max_candidates=max_candidates)
        print(f"[journalism] Stage 1 yielded {len(candidates)} candidates")
        if not candidates:
            print("[journalism] no candidates from Stage 1 — clean exit, nothing to post this cycle")
            print("[journalism] CYCLE END: published=0 reason=no_stage1_candidates")
            return True

        # ---- Stage 2: triage --------------------------------------------------
        print("[journalism] Stage 2 — triaging candidates")
        passed = story_triage.triage(candidates)
        print(f"[journalism] Stage 2 passed {len(passed)} / {len(candidates)}")
        # Persist the per-candidate verdicts to a feedback log so we can
        # later review which verbs / rules are causing real news to be
        # dropped. See scripts/triage_review.py (reviewed weekly).
        _append_triage_decisions(story_triage.last_decisions)
        if not passed:
            print("[journalism] no candidates passed triage — clean exit, nothing to post this cycle")
            print("[journalism] CYCLE END: published=0 reason=no_triage_passes")
            return True

    # ---- Stage 2b: story-level dedup -------------------------------------
    # Walter Croncat runs multiple times per day. Without dedup the pipeline
    # picks the same dominant X story every cycle and burns Claude calls on
    # the same META. Iteration 7 added a persistent `journalism_seen_stories.txt`
    # committed by the dry-run workflow: one story_id per line, plus its first-
    # seen timestamp for future pruning. Before selecting a candidate, we walk
    # the triage-passed list in rank order and pick the first story_id we have
    # not seen today. If every candidate is already seen, we fall through and
    # take the top one anyway (better to re-report than to post nothing) but
    # we log it explicitly so QA sees the fallback firing.
    seen_path = os.path.join(_project_root(), "journalism_seen_stories.txt")
    seen_story_ids: set[str] = set()
    # Iteration 11: semantic dedup via proper-noun overlap. Iteration 10
    # surfaced the Bondi-subpoena-vs-Bondi-deposition case where the same
    # underlying event got two different story_ids because the two outlets
    # used different headline wording. story_id-exact dedup missed it.
    # Fix: store each seen headline alongside the story_id and timestamp,
    # then at dedup time extract proper nouns from the candidate and each
    # seen headline, skip on >= SEMANTIC_DEDUP_OVERLAP shared proper nouns.
    # File format (backward-compatible): <story_id>\t<iso_timestamp>\t<headline>
    # Legacy 1-column and 2-column lines still parse; they just can't
    # contribute to semantic overlap (only byte-identical story_id match).
    # Iteration 18 Bug 26 stoplist: common headline verbs, prepositions,
    # and institutional tokens that pollute the title-case proper-noun set.
    # Without filtering these, any two stories with the same institution
    # doing the same action (e.g., "Senate Passes Bill" vs "House Passes
    # Bill", "Pentagon Announces X" vs "Pentagon Announces Y") would share
    # 2+ tokens and false-match. The stoplist is applied AFTER the
    # suffix/prefix strip but BEFORE the overlap comparison.
    #
    # Conservative list — includes only tokens that are structurally
    # high-frequency in news headlines AND not distinctive as entities.
    # Tokens like "Trump", "Biden", "Iran" stay IN the noun set because
    # they're actual entity content.
    _DEDUP_STOP_TOKENS = {
        # Title-case common verbs (noise, not content entities)
        "says", "said", "reports", "report", "claims", "claim",
        "denies", "deny", "denied", "declares", "declare", "declared",
        "announces", "announce", "announced",
        "passes", "passed", "rules", "ruled", "ruling",
        "charges", "charge", "charged", "considers", "considered",
        "issues", "issued", "votes", "voted", "voting",
        "vetoes", "vetoed", "approves", "approved", "rejects", "rejected",
        "warns", "urges", "seeks", "admits", "reveals",
        # Prepositions/conjunctions capitalized in title case
        "against", "with", "from", "after", "before", "over", "under",
        "into", "onto", "through", "about", "between", "during", "while",
        # Institutional tokens — too common across unrelated stories to
        # serve as distinctive entity match keys on their own
        "house", "senate", "congress", "court", "committee",
        "administration", "department", "pentagon", "doj", "white",
        # Generic headline fillers
        "bill", "case", "plan", "deal", "news", "update", "report",
        "statement", "probe", "inquiry", "investigation",
    }

    def _normalize_url_for_dedup(u: str) -> str:
        """Canonicalize a URL for cross-cycle overlap comparison: lowercase
        scheme/host, strip tracking params (utm_*/fbclid/gclid/ref/src),
        drop trailing slash, drop fragment. Empty / unparseable input
        returns ''. Stable across outlets that sprinkle utm tags onto the
        same article."""
        if not u:
            return ""
        try:
            from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
            p = urlparse(u.strip())
            keep_qs = [
                (k, v) for k, v in parse_qsl(p.query)
                if not k.lower().startswith("utm_")
                and k.lower() not in {"fbclid", "gclid", "ref", "src", "mc_cid", "mc_eid"}
            ]
            path = p.path.rstrip("/") or "/"
            return urlunparse((
                p.scheme.lower(), p.netloc.lower(), path,
                p.params, urlencode(keep_qs), "",
            ))
        except Exception:
            return u.strip().lower()

    def _llm_same_event_check(cand_headline: str,
                              recent_seen: list[tuple[str, str]]) -> tuple[bool, str]:
        """Layer 3 dedup: ask Haiku whether the candidate is the same news
        event as any seen headline in the prune window, regardless of
        phrasing/outlet/angle. Returns (is_duplicate, matched_story_id).

        Why this exists: the proper-noun semantic layer is blind to
        topic-driven stories where the subject is lowercase ('mifepristone',
        'tariffs'). Bug reproduced 2026-05-05: NPR 'Supreme Court gives
        abortion pill mifepristone a 1-week reprieve' and Axios 'Abortion
        pill rulings cause whiplash and confusion' shared zero proper nouns
        after the stoplist and slipped past the mechanical layer.

        Failure mode: returns (False, '') on API error or missing API key
        — the caller falls through to the next candidate, never silently
        publishes. The mechanical URL-overlap and proper-noun layers
        remain as belt-and-suspenders. Same-cycle latency is one Haiku
        call per candidate evaluated (~500ms), short-circuited as soon
        as a non-duplicate is found."""
        if not recent_seen:
            return (False, "")
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("[journalism] LLM dedup: ANTHROPIC_API_KEY missing — skipping LLM check")
            return (False, "")
        try:
            from anthropic import Anthropic as _Anthropic
            client = _Anthropic(api_key=api_key)
            seen_block = "\n".join(f"[{sid}] {hl}" for sid, hl in recent_seen)
            prompt = (
                "You are an editor judging whether a CANDIDATE news story is the "
                "SAME NEWS EVENT as any story already covered, regardless of "
                "headline phrasing, outlet, or framing angle.\n\n"
                "ALREADY-COVERED (last 14 days):\n"
                f"{seen_block}\n\n"
                f"CANDIDATE: {cand_headline}\n\n"
                "SAME news event examples:\n"
                "- 'Supreme Court gives abortion pill mifepristone a 1-week reprieve'\n"
                "  vs 'Abortion pill rulings cause whiplash and confusion'\n"
                "  → SAME (same SCOTUS mifepristone stay)\n"
                "- 'Pentagon to pull 5,000 troops from Germany'\n"
                "  vs 'Germany urges defense after US withdrawal announcement'\n"
                "  → SAME (same Pentagon decision)\n"
                "- 'Iran says US has responded to peace proposal'\n"
                "  vs 'Iran reviewing Washington reply on 14-point plan'\n"
                "  → SAME (same diplomatic exchange)\n\n"
                "DIFFERENT events:\n"
                "- 'SCOTUS Voting Rights ruling' vs 'SCOTUS abortion ruling'\n"
                "  → DIFFERENT (different cases)\n"
                "- 'Trump fires Iran envoy' vs 'Trump-Iran deal talks resume'\n"
                "  → DIFFERENT (different actions, even if same actors)\n\n"
                "Respond with STRICT JSON only, no other text:\n"
                '{"duplicate_of": "<story_id from list above>", "reasoning": "<one sentence>"}\n'
                "or if novel:\n"
                '{"duplicate_of": null, "reasoning": "<one sentence>"}'
            )
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=250,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip() if resp.content else ""
            import re as _re
            m = _re.search(r"\{.*\}", text, _re.DOTALL)
            if not m:
                print(f"[journalism] LLM dedup: unparseable response: {text[:160]!r}")
                return (False, "")
            data = json.loads(m.group(0))
            dup_id = data.get("duplicate_of")
            reasoning = data.get("reasoning", "")
            if dup_id and isinstance(dup_id, str):
                print(f"[journalism] LLM dedup: candidate matches seen story_id={dup_id} "
                      f"— reasoning: {reasoning[:160]}")
                return (True, dup_id)
            return (False, "")
        except Exception as e:
            print(f"[journalism] LLM dedup call failed ({e}); falling through to next layer")
            return (False, "")

    def _clean_headline_for_matching(h: str) -> str:
        """Normalize a headline for semantic dedup: strip outlet suffix and
        fluff prefix. Both transforms are idempotent. Used at two sites:
        the seen-file read path (to populate noun sets) and the
        _semantic_match candidate path (to extract the candidate's nouns).
        Both sites must use the same normalization for symmetric matching.

        Iteration 16 added the outlet suffix strip (Bug 24: Adam Back vs
        Rex Heuermann false-matched via {new, york, times} suffix tokens).
        Iteration 17 added the fluff prefix strip (Bug 25: any two stories
        starting with "Live Updates:" false-matched via {live, updates}).
        """
        if not h:
            return ""
        # Strip outlet suffix first (e.g. " - The New York Times")
        cleaned = _SUFFIX_STRIP_RE.sub("", h).strip()
        # Then strip fluff prefix (e.g. "Live Updates:", "BREAKING:")
        for prefix in _FLUFF_PREFIXES:
            if cleaned.upper().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break
        return cleaned

    def _dedup_nouns(h: str) -> set[str]:
        """Extract proper nouns for semantic dedup: clean the headline,
        extract capitalized tokens, then filter out the Bug-26 stoplist
        (common title-case verbs + institutional tokens + prepositions +
        generic headline fillers) that would otherwise cause false
        positives between unrelated stories sharing the same institutional
        actor and action verb."""
        cleaned = _clean_headline_for_matching(h)
        if not cleaned:
            return set()
        return _extract_proper_nouns(cleaned) - _DEDUP_STOP_TOKENS

    SEEN_PRUNE_DAYS = 14
    # Semantic-dedup threshold. 2 shared proper nouns is intentionally loose
    # because news headlines are often written in different phrasings for the
    # same event (e.g., "Bondi won't testify" vs "Bondi Won't Appear on Capitol
    # Hill for Scheduled Epstein Deposition" — they share exactly {bondi,
    # epstein}, which is 2). Threshold 3 missed that case in iteration 10.
    # Tradeoff: 2 will occasionally collapse two legitimately-distinct
    # political stories that share two common named entities (e.g. "Trump +
    # Iran deal" and "Trump fires Iran envoy") into one cycle's worth of
    # coverage. In practice, re-reporting related Trump/Iran stories within
    # a 14-day window is acceptable because the trend feed moves faster than
    # our cycle cadence anyway.
    SEMANTIC_DEDUP_OVERLAP = 2  # >= this many shared proper nouns = same story
    seen_header_lines: list[str] = []
    seen_kept_lines: list[str] = []
    # list of (story_id, headline, proper_noun_set) for semantic matching
    seen_entries: list[tuple[str, str, set[str]]] = []
    # normalized-url -> story_id index for Layer-2 (URL overlap) dedup. Built
    # from the optional 4th TSV column written at mark-as-seen time.
    seen_url_index: dict[str, str] = {}
    # (story_id, headline) for the LLM dedup layer (only entries with non-
    # empty headline; pruned entries already excluded).
    seen_for_llm: list[tuple[str, str]] = []
    pruned_count = 0
    try:
        if os.path.exists(seen_path):
            now_utc = datetime.now(timezone.utc)
            with open(seen_path, "r", encoding="utf-8") as f:
                for line in f:
                    raw = line.rstrip("\n")
                    stripped = raw.strip()
                    if not stripped or stripped.startswith("#"):
                        seen_header_lines.append(raw)
                        continue
                    # Format (current): "<story_id>\t<iso_timestamp>\t<headline>\t<url1>|<url2>|..."
                    # 3-column variant (iteration 11): no URL column.
                    # 2-column variant (iteration 7): no headline column.
                    # 1-column variant (legacy): just <story_id>.
                    # All four variants parse — older variants just contribute
                    # less signal to the dedup layers.
                    parts = stripped.split("\t", 3)
                    story_id_part = parts[0].strip()
                    if not story_id_part:
                        continue
                    # Pruning decision: if we can parse a timestamp and it's
                    # older than the threshold, drop the entry. If we can't
                    # parse a timestamp (legacy / malformed lines), keep it —
                    # we don't have enough information to prune safely.
                    keep = True
                    if len(parts) >= 2:
                        ts_str = parts[1].strip()
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            age_days = (now_utc - ts).total_seconds() / 86400.0
                            if age_days > SEEN_PRUNE_DAYS:
                                keep = False
                                pruned_count += 1
                        except Exception:
                            pass  # unparseable timestamp — keep the entry
                    if keep:
                        seen_kept_lines.append(raw)
                        seen_story_ids.add(story_id_part)
                        # Capture the headline for semantic dedup if present.
                        # Legacy lines without a headline column still get
                        # story_id-exact matching; just no semantic signal.
                        headline_part = parts[2].strip() if len(parts) >= 3 else ""
                        # Iterations 16-18: three-stage normalization for
                        # semantic dedup noun extraction:
                        #   - Strip outlet suffix (Bug 24, iter 16)
                        #   - Strip fluff prefix (Bug 25, iter 17)
                        #   - Apply stoplist filter (Bug 26, iter 18)
                        # All three are bundled in _dedup_nouns().
                        nouns = _dedup_nouns(headline_part) if headline_part else set()
                        seen_entries.append((story_id_part, headline_part, nouns))
                        # 4th column (optional): pipe-separated normalized URLs.
                        # Populates seen_url_index for Layer-2 URL overlap dedup.
                        if len(parts) >= 4:
                            url_blob = parts[3].strip()
                            if url_blob:
                                for raw_u in url_blob.split("|"):
                                    nu = _normalize_url_for_dedup(raw_u)
                                    if nu and nu not in seen_url_index:
                                        seen_url_index[nu] = story_id_part
                        if headline_part:
                            seen_for_llm.append((story_id_part, headline_part))
            # If any entries were pruned, rewrite the file. The workflow's
            # commit step will pick up the change and commit it just like
            # a mark-as-seen append.
            if pruned_count > 0:
                try:
                    with open(seen_path, "w", encoding="utf-8") as f:
                        for h in seen_header_lines:
                            f.write(h + "\n")
                        for k in seen_kept_lines:
                            f.write(k + "\n")
                    print(f"[journalism] pruned {pruned_count} seen-stories entries "
                          f"older than {SEEN_PRUNE_DAYS} days")
                except Exception as e:
                    print(f"[journalism] could not rewrite pruned seen-stories file ({e})")
    except Exception as e:
        print(f"[journalism] could not read seen-stories file ({e}); continuing without dedup")

    def _url_overlap_match(cand_urls: list[str]) -> tuple[bool, str, str]:
        """Layer 2 dedup: deterministic URL overlap. Returns
        (is_match, matched_story_id, matched_url) when ANY of the candidate's
        original_urls (after normalization) matches a URL stored on a seen
        entry. Catches the case where two cycles cluster on the same article
        but pick different headline phrasings."""
        for u in cand_urls or []:
            nu = _normalize_url_for_dedup(u)
            if nu and nu in seen_url_index:
                return (True, seen_url_index[nu], nu)
        return (False, "", "")

    def _semantic_match(cand_headline: str) -> tuple[bool, str, int]:
        """Return (is_match, matched_story_id, overlap_count) if this candidate
        headline shares >=SEMANTIC_DEDUP_OVERLAP proper nouns with any seen
        entry that has a stored headline. Otherwise (False, '', 0).

        Iterations 16-18: the candidate is normalized through _dedup_nouns
        which strips outlet suffix (iter 16), fluff prefix (iter 17), and
        filters a stoplist of common title-case noise tokens (iter 18)
        before computing the noun set. The seen entries are normalized
        the same way at read time so the comparison is symmetric.
        """
        cand_nouns = _dedup_nouns(cand_headline)
        if len(cand_nouns) < SEMANTIC_DEDUP_OVERLAP:
            return (False, "", 0)
        for sid, shl, snouns in seen_entries:
            if not snouns:
                continue
            overlap = len(cand_nouns & snouns)
            if overlap >= SEMANTIC_DEDUP_OVERLAP:
                return (True, sid, overlap)
        return (False, "", 0)

    # When a manual topic is provided, candidate is already set — preserve it
    # through the dedup loop (the loop will break immediately).
    candidate = candidate if topic else None
    skipped_count = 0
    # Four-layer dedup gauntlet — every candidate must pass ALL FOUR before
    # being selected. Hard requirement (2026-05-05 Bryan): same news event
    # must NEVER appear twice on the feed.
    #   L1 story_id exact      — cheap, byte-identical headline+URL match
    #   L2 URL overlap         — deterministic; same article URL across cycles
    #   L3 proper-noun overlap — semantic, same named entities
    #   L4 LLM same-event check — Haiku judges "same news event?" semantically;
    #                             catches the L3-blind case where the topic is
    #                             lowercase ('mifepristone', 'tariffs') and no
    #                             distinctive proper nouns survive the stoplist.
    # On L4 LLM error: fall through (treat as not-duplicate). Reaches into the
    # next candidate via the loop, never publishes silently.
    for c in passed:
        if candidate is not None:
            break
        # L1: Exact story_id
        if c.story_id in seen_story_ids:
            skipped_count += 1
            print(f"[journalism] [L1] skipping already-seen story_id={c.story_id} "
                  f"({c.headline_seed[:60]}...)")
            continue
        # L2: URL overlap (deterministic)
        u_matched, u_sid, u_url = _url_overlap_match(getattr(c, "original_urls", []) or [])
        if u_matched:
            skipped_count += 1
            print(f"[journalism] [L2] skipping URL-overlap candidate "
                  f"({c.headline_seed[:60]}...) — url={u_url[:80]} "
                  f"matches already-seen story_id={u_sid}")
            continue
        # L3: Proper-noun semantic
        matched, matched_sid, overlap = _semantic_match(c.headline_seed)
        if matched:
            skipped_count += 1
            print(f"[journalism] [L3] skipping semantically-duplicate candidate "
                  f"({c.headline_seed[:60]}...) — {overlap} proper nouns match "
                  f"already-seen story_id={matched_sid}")
            continue
        # L4: LLM-judged same-event check (catches lowercase-topic cases)
        llm_dup, llm_sid = _llm_same_event_check(c.headline_seed, seen_for_llm)
        if llm_dup:
            skipped_count += 1
            print(f"[journalism] [L4] skipping LLM-flagged same-event candidate "
                  f"({c.headline_seed[:60]}...) — same event as story_id={llm_sid}")
            continue
        candidate = c
        break

    if candidate is None:
        # Every triage-passed candidate is already in the seen set.
        # Clean exit — same semantics as "no candidates passed triage":
        # nothing new to report this cycle. Iteration 7 originally fell
        # through to passed[0] ("better to re-report than sit out"), but
        # iteration 13 run 30 proved that logic wrong: re-reporting a
        # story Cronkite already filed is worse than skipping the cycle.
        # Cronkite didn't do the same lead twice on the same broadcast.
        print(
            f"[journalism] all {len(passed)} triage-passed candidates are already "
            f"covered (rejected by L1 story_id / L2 URL-overlap / L3 proper-noun / "
            f"L4 LLM-judged); clean exit, nothing new to report this cycle"
        )
        print("[journalism] CYCLE END: published=0 reason=all_candidates_seen")
        return True

    if skipped_count > 0:
        print(f"[journalism] dedup skipped {skipped_count} already-seen candidate(s); "
              f"selected the next unseen story")

    print(f"[journalism] Selected candidate: {candidate.headline_seed[:80]}...")

    # ---- Stage 3: gather + primary source (with fallback loop) ------------
    # Build a ranked list of fallback candidates from the triage-passed set.
    # If the primary candidate yields 0 articles, try the next unseen one.
    fallback_candidates = [candidate]
    for c in passed:
        if len(fallback_candidates) >= max_fallback_candidates:
            break
        if c is candidate:
            continue
        # Apply the same four-layer gauntlet as primary selection so a
        # fallback can never re-introduce a duplicate that L1-L4 already
        # rejected upstream.
        if c.story_id in seen_story_ids:
            continue
        u_m, _, _ = _url_overlap_match(getattr(c, "original_urls", []) or [])
        if u_m:
            continue
        matched, _, _ = _semantic_match(c.headline_seed)
        if matched:
            continue
        llm_m, _ = _llm_same_event_check(c.headline_seed, seen_for_llm)
        if llm_m:
            continue
        fallback_candidates.append(c)

    dossier = None
    for fb_idx, fb_candidate in enumerate(fallback_candidates, start=1):
        fb_label = f"[{fb_idx}/{len(fallback_candidates)}]"
        print(f"[journalism] {fb_label} Stage 3a — gathering sources for: "
              f"{fb_candidate.headline_seed[:70]}...")
        fb_dossier = source_gatherer.gather(
            fb_candidate,
            target_count=target_sources,
            seed_urls=getattr(fb_candidate, "original_urls", []),
        )
        print(f"[journalism] {fb_label} Stage 3a collected {len(fb_dossier.articles)} articles")

        print(f"[journalism] {fb_label} Stage 3b — finding primary sources")
        added_primary = primary_finder.find(fb_dossier)
        print(f"[journalism] {fb_label} Stage 3b added {len(added_primary)} primary sources")

        dossier_store.save_dossier(fb_dossier)

        # Require at least 2 articles to proceed (type-specific minimums
        # are enforced after Stage 4 decides the post type)
        if len(fb_dossier.articles) < 2:
            print(f"[journalism] {fb_label} only {len(fb_dossier.articles)} articles "
                  f"— trying next candidate")
            continue

        # This candidate worked — use it
        dossier = fb_dossier
        candidate = fb_candidate
        break

    # If all fallback candidates yielded too few articles, clean exit.
    if dossier is None or len(dossier.articles) < 2:
        print(
            f"[journalism] Stage 3 returned 0 articles for all "
            f"{len(fallback_candidates)} candidate(s) — clean exit, "
            f"nothing to report on this cycle"
        )
        print("[journalism] CYCLE END: published=0 reason=no_articles")
        return True

    # ---- Stage 4: meta-analysis -------------------------------------------
    print("[journalism] Stage 4 — meta-analysis")
    try:
        brief = meta_analyzer.analyze(dossier)
    except Exception as e:
        print(f"[journalism] Stage 4 failed: {e}")
        return False
    if brief.suggested_post_type == PostType.META:
        print("[journalism] INFO: META suggestion normalized to REPORT per policy")
        brief.suggested_post_type = PostType.REPORT
    dossier_store.save_brief(brief)
    print(
        f"[journalism] Stage 4 suggested_post_type="
        f"{brief.suggested_post_type.value} confidence={brief.confidence}"
    )

    # ---- Quality gate: tiered by post type ----------------------------------
    chosen_type = forced_post_type or brief.suggested_post_type

    # Thresholds per post type:
    #   REPORT/META: 3 sources, 0.45 confidence (multi-source corroboration)
    #   BULLETIN:    2 sources, 0.25 confidence (breaking, hedged language —
    #                the safety-net tier; caught runs with 0.30 confidence
    #                that had valid sourcing but died just below the floor)
    #   Others:      2 sources, 0.40 confidence
    _QUALITY_GATES = {
        PostType.REPORT:     {"min_articles": 3, "min_confidence": 0.45},
        PostType.META:       {"min_articles": 3, "min_confidence": 0.45},
        PostType.BULLETIN:   {"min_articles": 2, "min_confidence": 0.25},
        PostType.ANALYSIS:   {"min_articles": 2, "min_confidence": 0.40},
        PostType.PRIMARY:    {"min_articles": 2, "min_confidence": 0.40},
        PostType.CORRECTION: {"min_articles": 2, "min_confidence": 0.40},
    }
    gate = _QUALITY_GATES.get(chosen_type, {"min_articles": 3, "min_confidence": 0.45})
    n_articles = len(dossier.articles)

    if n_articles < gate["min_articles"]:
        # Auto-downgrade: if REPORT/META/ANALYSIS can't meet its 3-source
        # floor but we have ≥2 articles, re-route the story as a BULLETIN
        # (which needs only 2). BULLETIN is the safety-net post type —
        # hedged language, shorter budget — exactly what a thin-sourced
        # story should be published as. Run 24630187199 proved this was a
        # silent killer: 2 articles gathered, gate suggested REPORT, clean
        # exit. Better a smaller post than none.
        bulletin_gate = _QUALITY_GATES[PostType.BULLETIN]
        if (
            not forced_post_type
            and chosen_type in (PostType.REPORT, PostType.META, PostType.ANALYSIS)
            and n_articles >= bulletin_gate["min_articles"]
            and brief.confidence >= bulletin_gate["min_confidence"]
        ):
            print(
                f"[journalism] {chosen_type.value} requires {gate['min_articles']} sources "
                f"but only {n_articles} found — downgrading to BULLETIN"
            )
            chosen_type = PostType.BULLETIN
            gate = bulletin_gate
        else:
            print(
                f"[journalism] {chosen_type.value} requires {gate['min_articles']} sources "
                f"but only {n_articles} found — clean exit"
            )
            print(f"[journalism] CYCLE END: published=0 reason=too_few_articles_for_{chosen_type.value}")
            return True

    if brief.confidence < gate["min_confidence"]:
        print(
            f"[journalism] confidence {brief.confidence:.2f} < "
            f"{gate['min_confidence']} for {chosen_type.value} — clean exit"
        )
        print(f"[journalism] CYCLE END: published=0 reason=low_confidence_{chosen_type.value}")
        return True
    print(f"[journalism] Stage 5 — composing {chosen_type.value} post")
    try:
        # Don't pass max_length — let the composer pick the right budget
        # per post type (long_form_max_length for META, max_length for the
        # rest). Passing max_length=280 here is how the char_limit bug
        # slipped in before.
        draft = post_composer.compose(
            brief=brief,
            dossier=dossier,
            post_type=chosen_type,
        )
    except Exception as e:
        print(f"[journalism] Stage 5 failed: {e}")
        return False

    # ---- Stage 6 + 6.5: unified editor-mode retry loop --------------------
    # Gate (structure) and fabrication (factuality) checks share ONE retry
    # budget and ONE merged feedback set per attempt. Two bugs in the
    # earlier split design caused the 2026-04-22 20:21 UTC failure:
    #   (a) a successful fab-retry that re-introduced a gate violation
    #       (lost the BULLETIN hedge) died instantly instead of retrying
    #       with the combined feedback;
    #   (b) feedback loops didn't cross-pollinate — gate feedback never
    #       reached the fab-retry composer and vice versa.
    # Unified loop: compose → gate-check → (if passes) fab-check → collect
    # all failures → retry with the merged set. Fab analyzer only runs when
    # the gate passes, so broken-structure drafts don't burn fab LLM calls.
    MAX_RETRIES = 2

    def _run_verification(d: DraftPost):
        """Run gate + (conditionally) fab analysis. Returns
        (gate_result, fab_findings_or_None, merged_retry_reasons)."""
        g = verification_gate.verify(d, dossier, brief=brief)
        f_findings = None
        merged: list[str] = []
        if not g.passed:
            merged.extend(g.failures)
        else:
            try:
                f_findings = analyze_draft(d.text, candidate.headline_seed, dossier)
                print_analysis(f_findings)
                if f_findings.get("overall") == "FABRICATION":
                    merged.extend(
                        f"FABRICATION: {entry.get('assessment', '')}"
                        for entry in f_findings.get("findings", [])
                        if entry.get("severity") == "major"
                    )
            except Exception as analyze_err:
                print(f"[draft_analyzer] analysis failed (continuing): {analyze_err}")
        return g, f_findings, merged

    print("[journalism] Stage 6 — verifying draft")
    result, findings, reasons = _run_verification(draft)
    for attempt in range(1, MAX_RETRIES + 1):
        if not reasons:
            break
        print(f"[journalism] Stage 6 attempt {attempt}/{MAX_RETRIES} failures: {reasons}")
        print(f"[journalism] Stage 6 — retry {attempt} with merged editor feedback")
        retry_feedback = list(reasons) + [
            f"{CHAR_LIMIT_REASON_PREFIX} draft MUST be <= "
            f"{post_composer._effective_max_length(chosen_type)} chars"
        ]
        try:
            draft = post_composer.compose(
                brief=brief,
                dossier=dossier,
                post_type=chosen_type,
                retry_reasons=retry_feedback,
            )
        except Exception as e:
            print(f"[journalism] Stage 5 retry {attempt} failed: {e}")
            return False
        result, findings, reasons = _run_verification(draft)

    # Last-resort mechanical repair BEFORE BULLETIN fallback or reject:
    # if the only outstanding failure is a BULLETIN missing its hedge,
    # append the hedge. The composer already had 3 swings at it; at this
    # point "publish hedged BULLETIN" > "reject whole story".
    if reasons and draft.post_type == PostType.BULLETIN:
        repaired = _maybe_repair_bulletin_hedge(
            draft,
            dossier,
            post_composer._effective_max_length(PostType.BULLETIN),
        )
        if repaired is not None:
            print("[journalism] Stage 6 — mechanical hedge repair applied")
            draft = repaired
            result, findings, reasons = _run_verification(draft)

    # BULLETIN fallback — pivot a failed long-form type to a short
    # BULLETIN before giving up. Preserves the previous "publish something
    # beats publishing nothing" philosophy, now at the tail of a richer
    # retry loop.
    if reasons and chosen_type in (PostType.REPORT, PostType.META, PostType.ANALYSIS):
        print(
            f"[journalism] Stage 6 — falling back to BULLETIN after "
            f"{chosen_type.value} exhausted {MAX_RETRIES + 1} retry attempts"
        )
        try:
            draft = post_composer.compose(
                brief=brief,
                dossier=dossier,
                post_type=PostType.BULLETIN,
                retry_reasons=reasons,
            )
            result, findings, reasons = _run_verification(draft)
            # Same mechanical repair chance for the fallback
            if reasons:
                repaired = _maybe_repair_bulletin_hedge(
                    draft,
                    dossier,
                    post_composer._effective_max_length(PostType.BULLETIN),
                )
                if repaired is not None:
                    print("[journalism] Stage 6 — hedge repair applied to BULLETIN fallback")
                    draft = repaired
                    result, findings, reasons = _run_verification(draft)
            if not reasons:
                chosen_type = PostType.BULLETIN
                print("[journalism] Stage 6 — BULLETIN fallback verified")
            else:
                print(f"[journalism] BULLETIN fallback also failed: {reasons}")
        except Exception as e:
            print(f"[journalism] BULLETIN fallback compose failed: {e}")

    if reasons:
        print(f"[journalism] Stage 6 FINAL failures: {reasons}")
        rejected_path = _write_draft_file(
            drafts_dir, draft, dossier, subfolder="rejected"
        )
        print(f"[journalism] rejected draft written to {rejected_path}")
        return False

    # Fill in a SKIPPED-style findings record for drafts that never
    # tripped the fab analyzer (e.g. the initial gate check already
    # failed and we never reached the fab stage on any attempt). Keeps
    # the dossier audit record shape stable.
    if findings is None:
        findings = {"overall": "SKIPPED", "findings": []}

    # Save findings to the dossier for downstream audit
    dossier_store.save_post_record(
        dossier.story_id, draft,
        post_url=None,
    )

    # Persist verification + analysis + selection data for dossier viewer
    try:
        raw = dossier_store.read_raw(dossier.story_id)
        raw["verification"] = result.to_dict() if result else None
        raw["analysis"] = findings if findings else None
        raw["selection"] = {
            "candidates_detected": len(candidates) if candidates else 0,
            "candidates_passed_triage": len(passed) if passed else 0,
            "story_id": candidate.story_id,
            "headline_seed": candidate.headline_seed,
            "source": getattr(candidate, "source", "unknown"),
        }
        dossier_store._write(dossier.story_id, raw)
    except Exception as e:
        print(f"[journalism] failed to persist extended dossier data: {e}")

    # ---- Per-platform content fork ----------------------------------------
    # Bluesky publishes the canonical `draft` (verified above) unchanged — it's
    # the account's strongest surface. X gets its own initial-post text tuned
    # for X's out-of-network retrieval ranking (prompts/platform_x.md), verified
    # independently, with a safe fallback to the canonical draft on failure.
    # Shared downstream: the Grok image and the dossier-link reply are unchanged.
    x_draft = _compose_platform_variant(
        post_composer, verification_gate, brief, dossier, chosen_type,
        canonical=draft, platform="x",
    )
    x_variant_used = x_draft is not draft
    print(f"[journalism] X variant: "
          f"{'distinct from canonical' if x_variant_used else 'fell back to canonical'}")

    # ---- Stage 7: publish or dry-run write --------------------------------

    # Mark the story as seen BEFORE writing the draft so the seen-stories
    # file reflects that this story has been successfully processed this
    # cycle. If we crash between draft-write and mark-seen, the next run
    # would pick it up again — acceptable, since "re-report after a crash"
    # is better than "silently skip after a crash." Idempotent: if the
    # story_id is already in the file, this is a no-op.
    try:
        already_seen = candidate.story_id in seen_story_ids
        if not already_seen:
            # 4-column TSV (current): story_id\ttimestamp\theadline\turls
            # The 4th URL column powers the L2 URL-overlap dedup layer on
            # subsequent cycles. Sources for the URL set: the candidate's
            # original_urls plus every dossier article URL gathered in
            # Stage 3a. URLs are normalized (strip utm_*, lowercase host,
            # drop trailing slash) and de-duplicated before pipe-joining.
            safe_headline = (candidate.headline_seed or "").replace("\t", " ").replace("\n", " ").strip()
            url_seen: set[str] = set()
            urls_to_persist: list[str] = []
            for u in (getattr(candidate, "original_urls", []) or []):
                nu = _normalize_url_for_dedup(u)
                if nu and nu not in url_seen:
                    url_seen.add(nu)
                    urls_to_persist.append(nu)
            for art in (dossier.articles or []):
                nu = _normalize_url_for_dedup(getattr(art, "url", "") or "")
                if nu and nu not in url_seen:
                    url_seen.add(nu)
                    urls_to_persist.append(nu)
            url_blob = "|".join(urls_to_persist).replace("\t", "").replace("\n", "")
            with open(seen_path, "a", encoding="utf-8") as f:
                f.write(
                    f"{candidate.story_id}\t"
                    f"{datetime.now(timezone.utc).isoformat()}\t"
                    f"{safe_headline}\t"
                    f"{url_blob}\n"
                )
            print(f"[journalism] marked story_id={candidate.story_id} as seen "
                  f"with {len(urls_to_persist)} URLs")
    except Exception as e:
        print(f"[journalism] could not update seen-stories file ({e}); continuing")

    if dry_run:
        path = _write_draft_file(drafts_dir, draft, dossier)
        print(f"[journalism] DRY RUN draft written to {path}")

        # Per-platform fork preview — eyeball X vs Bluesky before going live.
        print("\n[journalism] ===== DRY RUN platform preview =====")
        print(f"--- BLUESKY ({len(draft.text)} chars) ---\n{draft.text}\n")
        if x_variant_used:
            x_path = _write_draft_file(drafts_dir, x_draft, dossier, subfolder="x")
            print(f"--- X ({len(x_draft.text)} chars) [written to {x_path}] ---\n{x_draft.text}\n")
        else:
            print("--- X --- fell back to the canonical draft (identical to Bluesky)\n")
        print("[journalism] ===== end platform preview =====\n")

        # Best-effort image generation for dry-run dossier preview.
        # Save directly to the dossier images directory (no temp file).
        safe_id = _safe_filename_component(draft.story_id)
        images_dir = os.path.join(_project_root(), "docs", "dossiers", "images")
        os.makedirs(images_dir, exist_ok=True)
        dest_path = os.path.join(images_dir, f"{safe_id}.png")

        image_path, anchored_prompt = _generate_journalism_image(draft, dossier, save_path=dest_path)
        if image_path:
            _persist_dossier_image(draft, dossier_store, image_path, image_prompt=anchored_prompt)

        # Render dossier HTML + rebuild index
        _render_dossier_html(dossier_store, draft, dossier)
        return True

    print("[journalism] Stage 7 — publishing")

    # Best-effort POST-TYPE-AWARE image generation (see prompts/journalism_image.md).
    # `image_prompt` here is the FULL anchored prompt sent to Grok — flows
    # into both the dossier JSON and posts_history.json for full audit.
    image_path, image_prompt = _generate_journalism_image(draft, dossier)
    if image_path:
        _persist_dossier_image(draft, dossier_store, image_path, image_prompt=image_prompt)

    # Primary publish: post to X and Bluesky.
    # META posts on X inline the dossier URL in the post itself (one
    # tweet instead of two) — the self-reply was redundant with the
    # long-form coverage body and cluttered the profile feed. On
    # Bluesky, META is already truncated to 300 chars so inlining the
    # URL would just get chopped off; keep the link-card self-reply
    # there as the discoverable path.
    # All other post types keep the existing self-reply pattern on both.
    dossier_url = f"https://mewscast.us/dossiers/{candidate.story_id}.html"
    is_meta = chosen_type == PostType.META
    if is_meta:
        sign_off = SIGN_OFFS.get(chosen_type)
        x_post_text = _inline_dossier_url_into_meta(x_draft.text, dossier_url, sign_off)
    else:
        x_post_text = x_draft.text
    bluesky_post_text = draft.text

    # Generate the Field Notes reply image ONCE (per cycle) — both platforms
    # share it. Returns None when the feature is disabled, gates fail, or
    # generation errors; each platform's reply path then falls back to the
    # legacy text/link-card reply on a None.
    field_notes_image_path = _generate_field_notes_image_if_eligible(
        brief_dict=brief.to_dict() if brief else {},
        headline=dossier.headline_seed or "",
        story_id=draft.story_id,
        journalism_cfg=journalism_cfg,
        dossier_store=dossier_store,
    )

    tweet_id = None
    reply_tweet_id = None
    x_success = False
    bluesky_uri = None
    bluesky_reply_uri = None
    bluesky_success = False

    synthetic_story = {
        "title": dossier.headline_seed,
        "url": dossier.articles[0].url if dossier.articles else None,
        "source": dossier.articles[0].outlet if dossier.articles else "Unknown",
    }

    def _persist_post_artifacts() -> None:
        """Write source-of-truth (posts_history, dossier_store, dossier HTML)
        as soon as any platform success is known. Idempotent — safe to call
        multiple times in the same cycle. Never raises: each substep is
        wrapped so a single failure can't abort the publish loop.

        Why this lives inline and runs after every platform success: prior
        end-of-cycle persistence let runner crashes (post-publish but
        pre-record) leave Bluesky with a live post and the repo with no
        record, which then re-published the same story on the next cron.
        """
        try:
            if tracker is not None:
                tracker.upsert_post(
                    synthetic_story,
                    post_content=draft.text,
                    tweet_id=tweet_id,
                    reply_tweet_id=reply_tweet_id,
                    bluesky_uri=bluesky_uri,
                    bluesky_reply_uri=bluesky_reply_uri,
                    image_prompt=image_prompt,
                    dossier_id=draft.story_id,
                    post_type=draft.post_type.value,
                    post_pipeline="journalism",
                )
        except Exception as e:
            print(f"[journalism] posts_history upsert failed (non-fatal): {e}")

        try:
            post_url = None
            if tweet_id:
                post_url = f"https://x.com/i/web/status/{tweet_id}"
            bluesky_url = bluesky_web_url(bluesky_uri) if bluesky_uri else None
            if post_url is None and bluesky_url is not None:
                post_url = bluesky_url
            dossier_store.save_post_record(
                draft.story_id, draft, post_url=post_url, bluesky_url=bluesky_url
            )
        except Exception as e:
            print(f"[journalism] dossier_store.save_post_record failed (non-fatal): {e}")

        try:
            _render_dossier_html(dossier_store, draft, dossier)
        except Exception as e:
            print(f"[journalism] dossier HTML render failed (non-fatal): {e}")

    if twitter_bot is not None:
        try:
            if image_path:
                x_result = twitter_bot.post_tweet_with_image(x_post_text, image_path)
            else:
                x_result = twitter_bot.post_tweet(x_post_text)
            if x_result:
                tweet_id = x_result.get("id")
                x_success = True
                print(f"[journalism] X post ok: {tweet_id}")
                _persist_post_artifacts()

                if not is_meta:
                    # Dossier reply — try the Field Notes image first (same
                    # visual asset Bluesky uses). On failure or when not
                    # eligible, fall back to the plain-text dossier reply.
                    time.sleep(2)
                    x_fn_reply_id = None
                    if field_notes_image_path:
                        x_fn_reply_id = _post_x_field_notes_reply(
                            twitter_bot,
                            tweet_id,
                            field_notes_image_path,
                            dossier_url,
                        )
                    if x_fn_reply_id:
                        reply_tweet_id = x_fn_reply_id
                        _persist_post_artifacts()
                    else:
                        brief_dict = brief.to_dict() if brief else {}
                        outlet_count = len(dossier.articles) if dossier.articles else 0
                        reply_hook = _compose_dossier_reply_text(brief_dict, outlet_count)
                        reply_body = f"{reply_hook}\n{dossier_url}"
                        try:
                            reply_result = twitter_bot.reply_to_tweet(tweet_id, reply_body)
                            if reply_result:
                                reply_tweet_id = reply_result.get("id")
                                print(f"[journalism] X dossier reply ok: {reply_tweet_id}")
                                _persist_post_artifacts()
                        except Exception as re:
                            print(f"[journalism] X dossier reply failed: {re}")
                else:
                    print("[journalism] META — dossier URL inlined, no self-reply")
        except Exception as e:
            print(f"[journalism] X publish failed: {e}")

    if bluesky_bot is not None:
        try:
            if image_path:
                bs_result = bluesky_bot.post_skeet_with_image(bluesky_post_text, image_path)
            else:
                bs_result = bluesky_bot.post_skeet(bluesky_post_text)
            if bs_result:
                bluesky_uri = bs_result.get("uri")
                bluesky_success = True
                print(f"[journalism] Bluesky post ok: {bluesky_uri}")
                _persist_post_artifacts()

                # Dossier reply — Field Notes image (generated once above,
                # reused across platforms). On any failure or when the
                # feature isn't eligible, fall back to the prior link-card
                # reply so the dossier link still ships.
                time.sleep(2)
                field_notes_uri = None
                if field_notes_image_path:
                    field_notes_uri = _post_bluesky_field_notes_reply(
                        bluesky_bot,
                        bluesky_uri,
                        field_notes_image_path,
                        dossier_url,
                    )
                if field_notes_uri:
                    bluesky_reply_uri = field_notes_uri
                    _persist_post_artifacts()
                else:
                    # Fallback: clickable link card (no banner thumbnail).
                    brief_dict = brief.to_dict() if brief else {}
                    outlet_count = len(dossier.articles) if dossier.articles else 0
                    reply_hook = _compose_dossier_reply_text(brief_dict, outlet_count)
                    try:
                        reply_result = bluesky_bot.reply_to_skeet_with_link(
                            bluesky_uri, dossier_url,
                            text=reply_hook,
                        )
                        if reply_result:
                            bluesky_reply_uri = reply_result.get("uri")
                            print(f"[journalism] Bluesky dossier reply ok: {bluesky_reply_uri}")
                            _persist_post_artifacts()
                    except Exception as re:
                        print(f"[journalism] Bluesky dossier reply failed: {re}")
        except Exception as e:
            print(f"[journalism] Bluesky publish failed: {e}")

    if not (x_success or bluesky_success):
        print("[journalism] no platform accepted the post; failing cycle")
        return False

    print(f"\n{'=' * 60}")
    print("[journalism] cycle complete")
    print(
        f"[journalism] CYCLE END: published=1 post_type={chosen_type.value} "
        f"story_id={draft.story_id}"
    )
    print(f"{'=' * 60}\n")
    return True


def republish_draft(story_id: str, post_text: str, post_type_str: str = "REPORT") -> bool:
    """Publish a specific draft directly — skips Stages 1-6.

    Used when a dry-run produced a good draft and you want to publish
    exactly that text with an image and dossier reply, without re-running
    the full pipeline (which would pick a different trending story).

    Args:
        story_id: the dossier story_id (e.g. "2026-04-11-pope-leo-xiv-issued-0276fdcfd2")
        post_text: the exact post text to publish
        post_type_str: REPORT, META, BULLETIN, ANALYSIS, PRIMARY, CORRECTION

    Returns True on success.
    """
    print(f"\n{'=' * 60}")
    print(f"Walter Croncat republish — {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Story: {story_id}")
    print(f"Type:  {post_type_str}")
    print(f"{'=' * 60}\n")

    post_type = PostType(post_type_str)

    # ---- Generate image ------------------------------------------------
    image_path = None
    image_prompt = None
    try:
        print(f"[republish] generating {post_type.value}-style image...")
        img_prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "prompts", "journalism_image.md"
        )
        with open(img_prompt_path, "r", encoding="utf-8") as f:
            img_template = f.read()

        img_request = img_template.replace("{post_type}", post_type.value)
        img_request = img_request.replace("{topic}", post_text[:200])
        img_request = img_request.replace("{draft_text}", post_text[:500])
        img_request = img_request.replace("{article_section}", "")

        from anthropic import Anthropic as _Anthropic
        _img_client = _Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        _img_resp = _img_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": img_request}],
        )
        image_prompt = _img_resp.content[0].text.strip().strip('"').strip("'")
        if len(image_prompt) > 800:
            image_prompt = image_prompt[:800]
        print(f"[republish] image prompt: {image_prompt[:100]}...")

        img_gen = ImageGenerator()
        # Capture the full anchored prompt for audit (posts_history.json).
        image_path, image_prompt = img_gen.generate_image(image_prompt, post_type=post_type.value)
    except Exception as e:
        print(f"[republish] image generation failed (continuing): {e}")

    # ---- Load brief sidecar for dossier-reply personalization ----------
    # The full dossier JSON is gitignored; the brief sidecar is committed
    # alongside the dossier HTML and carries the disagreements/framing/
    # missing-context signals we need. Absence is fine — the compose
    # function falls back to a generic line.
    reply_brief: dict = {}
    reply_outlet_count: int = 0
    try:
        safe_id = _safe_filename_component(story_id)
        brief_sidecar_path = os.path.join(
            _project_root(), "docs", "dossiers", f"{safe_id}.brief.json"
        )
        if os.path.exists(brief_sidecar_path):
            import json as _json
            with open(brief_sidecar_path, "r", encoding="utf-8") as f:
                _sidecar = _json.load(f)
            reply_brief = _sidecar.get("brief", {}) or {}
            reply_outlet_count = len(_sidecar.get("articles", []) or [])
    except Exception as _sidecar_err:
        print(f"[republish] brief sidecar load failed (using generic reply): {_sidecar_err}")

    # ---- Publish to X --------------------------------------------------
    # META posts inline the dossier URL in the X post itself and skip
    # the self-reply (mirrors post_journalism_cycle). Other types keep
    # the self-reply pattern.
    dossier_url = f"https://mewscast.us/dossiers/{story_id}.html"
    is_meta = post_type == PostType.META
    if is_meta:
        sign_off = SIGN_OFFS.get(post_type)
        x_post_text = _inline_dossier_url_into_meta(post_text, dossier_url, sign_off)
    else:
        x_post_text = post_text
    bluesky_post_text = post_text

    # Republish path uses the brief sidecar (loaded above as reply_brief)
    # for the field-notes feature. dossier_store is omitted — the audit
    # persistence step is skipped on republish, but the image still gets
    # generated and posted.
    _republish_journalism_cfg = (_load_config() or {}).get("journalism") or {}
    field_notes_image_path = _generate_field_notes_image_if_eligible(
        brief_dict=reply_brief or {},
        headline=post_text[:60] if post_text else "",
        story_id=story_id,
        journalism_cfg=_republish_journalism_cfg,
        dossier_store=None,
    )

    tweet_id = None
    reply_tweet_id = None
    x_success = False
    bluesky_uri = None
    bluesky_reply_uri = None
    bluesky_success = False

    tracker = PostTracker()
    synthetic_story = {"title": post_text[:100], "url": None, "source": "republish"}

    def _persist_post_artifacts() -> None:
        """Idempotent: write to posts_history as soon as any platform success
        is known. Keyed on (dossier_id, post_pipeline) so successive calls
        merge IDs into one record. See post_journalism_cycle for the full
        rationale (runner crash mid-cycle previously left posts untracked)."""
        try:
            tracker.upsert_post(
                synthetic_story,
                post_content=post_text,
                tweet_id=tweet_id,
                reply_tweet_id=reply_tweet_id,
                bluesky_uri=bluesky_uri,
                bluesky_reply_uri=bluesky_reply_uri,
                image_prompt=image_prompt,
                dossier_id=story_id,
                post_type=post_type.value,
                post_pipeline="journalism",
            )
        except Exception as e:
            print(f"[republish] posts_history upsert failed (non-fatal): {e}")

    try:
        twitter_bot = TwitterBot()
        if image_path:
            x_result = twitter_bot.post_tweet_with_image(x_post_text, image_path)
        else:
            x_result = twitter_bot.post_tweet(x_post_text)
        if x_result:
            tweet_id = x_result.get("id")
            x_success = True
            print(f"[republish] X post ok: {tweet_id}")
            _persist_post_artifacts()

            if is_meta:
                print("[republish] META — dossier URL inlined, no X self-reply")
            else:
                # Dossier reply — Field Notes image first, plain-text fallback.
                time.sleep(2)
                x_fn_reply_id = None
                if field_notes_image_path:
                    x_fn_reply_id = _post_x_field_notes_reply(
                        twitter_bot,
                        tweet_id,
                        field_notes_image_path,
                        dossier_url,
                    )
                if x_fn_reply_id:
                    reply_tweet_id = x_fn_reply_id
                    _persist_post_artifacts()
                else:
                    reply_hook = _compose_dossier_reply_text(reply_brief, reply_outlet_count)
                    reply_body = f"{reply_hook}\n{dossier_url}"
                    try:
                        reply_result = twitter_bot.reply_to_tweet(tweet_id, reply_body)
                        if reply_result:
                            reply_tweet_id = reply_result.get("id")
                            print(f"[republish] X dossier reply ok: {reply_tweet_id}")
                            _persist_post_artifacts()
                    except Exception as re:
                        print(f"[republish] X dossier reply failed: {re}")
    except Exception as e:
        print(f"[republish] X publish failed: {e}")

    # ---- Publish to Bluesky --------------------------------------------
    # Bluesky keeps the link-card self-reply even for META, because the
    # 300-char cap truncates long META bodies and the card is how users
    # reach the dossier.
    try:
        bluesky_bot = BlueskyBot()
        if image_path:
            bs_result = bluesky_bot.post_skeet_with_image(bluesky_post_text, image_path)
        else:
            bs_result = bluesky_bot.post_skeet(bluesky_post_text)
        if bs_result:
            bluesky_uri = bs_result.get("uri")
            bluesky_success = True
            print(f"[republish] Bluesky post ok: {bluesky_uri}")
            _persist_post_artifacts()

            # Dossier reply — reuse the field-notes image generated above
            # for both platforms.
            time.sleep(2)
            field_notes_uri = None
            if field_notes_image_path:
                field_notes_uri = _post_bluesky_field_notes_reply(
                    bluesky_bot,
                    bluesky_uri,
                    field_notes_image_path,
                    dossier_url,
                )
            if field_notes_uri:
                bluesky_reply_uri = field_notes_uri
                _persist_post_artifacts()
            else:
                # Fallback: clickable link card, no banner thumbnail.
                reply_hook = _compose_dossier_reply_text(reply_brief, reply_outlet_count)
                try:
                    reply_result = bluesky_bot.reply_to_skeet_with_link(
                        bluesky_uri, dossier_url,
                        text=reply_hook,
                    )
                    if reply_result:
                        bluesky_reply_uri = reply_result.get("uri")
                        print("[republish] Bluesky dossier reply ok")
                        _persist_post_artifacts()
                except Exception as re:
                    print(f"[republish] Bluesky dossier reply failed: {re}")
    except Exception as e:
        print(f"[republish] Bluesky publish failed: {e}")

    if not (x_success or bluesky_success):
        print("[republish] no platform accepted the post")
        return False

    print(f"\n{'=' * 60}")
    print("[republish] done")
    if tweet_id:
        print(f"  X: https://x.com/mewscast/status/{tweet_id}")
    print(f"  Dossier: https://mewscast.us/dossiers/{story_id}.html")
    print(f"{'=' * 60}\n")
    return True


def main():
    """Main entry point"""
    # Load environment variables
    load_dotenv()

    # Check mode from environment or argument
    mode = os.getenv("BOT_MODE", "scheduled")

    if len(sys.argv) > 1:
        mode = sys.argv[1]

    print(f"\n🚀 Starting Mewscast in '{mode}' mode...\n")

    if mode == "scheduled" or mode == "post":
        # The legacy single-article pipeline was removed 2026-06; scheduled
        # posts now always run the Walter Croncat journalism pipeline.
        # pipelines.journalism.enabled in config.yaml remains as a kill switch.
        try:
            _cfg = _load_config()
        except Exception as _e:
            _config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
            raise RuntimeError(
                f"Failed to load config at {os.path.abspath(_config_path)}: {_e}"
            ) from _e
        _pipelines_cfg = (_cfg.get("pipelines") or {})
        _journalism_enabled = bool((_pipelines_cfg.get("journalism") or {}).get("enabled", True))
        if _journalism_enabled:
            success = post_journalism_cycle()
        else:
            print(
                "❌ pipelines.journalism.enabled is false in config.yaml — "
                "nothing to run. Flip it to true."
            )
            success = False
    elif mode == "journalism":
        # Walter Croncat journalism workflow — new pipeline.
        #
        # Subcommands:
        #   python src/main.py journalism                  # one cycle, real publish
        #   python src/main.py journalism --dry-run        # one cycle, drafts only
        #   python src/main.py journalism brief            # force a REPORT cycle
        #   python src/main.py journalism meta             # force a META cycle
        #   python src/main.py journalism bulletin         # force a BULLETIN cycle
        #   python src/main.py journalism correction       # force a CORRECTION cycle
        #   python src/main.py journalism --topic "US tariffs on China" --dry-run
        #
        # --dry-run and --topic can be combined with any post-type subcommand.
        extra_args = [a for a in sys.argv[2:]]
        dry_run = "--dry-run" in extra_args
        extra_args = [a for a in extra_args if a != "--dry-run"]

        # Parse --topic "some topic here"
        topic_override: str | None = None
        filtered_args = []
        i = 0
        while i < len(extra_args):
            if extra_args[i] == "--topic" and i + 1 < len(extra_args):
                topic_override = extra_args[i + 1]
                i += 2
            else:
                filtered_args.append(extra_args[i])
                i += 1
        extra_args = filtered_args

        forced_type: PostType | None = None
        if extra_args:
            subtype = extra_args[0].lower()
            if subtype in _JOURNALISM_POST_TYPE_ALIASES:
                forced_type = _JOURNALISM_POST_TYPE_ALIASES[subtype]
            else:
                print(f"❌ Unknown journalism post type: {subtype}")
                print("Available: brief, meta, analysis, bulletin, correction, primary")
                sys.exit(1)

        success = post_journalism_cycle(
            dry_run=dry_run, forced_post_type=forced_type, topic=topic_override
        )
    elif mode == "republish":
        # Republish a specific draft without re-running the pipeline.
        #   python src/main.py republish <story_id>
        # Reads the draft text from docs/dossiers/<story_id>.meta.json
        # (saved during dry-run). No manual text entry needed.
        if len(sys.argv) < 3:
            print("Usage: python src/main.py republish <story_id>")
            sys.exit(1)
        story_id = sys.argv[2]
        # Load draft text and post type from the committed meta sidecar
        meta_path = os.path.join(
            _project_root(), "docs", "dossiers", f"{story_id}.meta.json"
        )
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            post_text = meta.get("draft_text", "")
            post_type_str = meta.get("post_type", "REPORT")
            if not post_text:
                print(f"Error: no draft_text in {meta_path}")
                print("This dossier may predate the draft_text sidecar. "
                      "Re-run the dry-run to regenerate it.")
                sys.exit(1)
            print(f"[republish] loaded draft from {meta_path}")
            print(f"[republish] post type: {post_type_str}")
            print(f"[republish] text ({len(post_text)} chars): {post_text[:80]}...")
        except FileNotFoundError:
            print(f"Error: {meta_path} not found. Run a dry-run first.")
            sys.exit(1)
        success = republish_draft(story_id, post_text, post_type_str)
    else:
        print(f"❌ Unknown mode: {mode}")
        print("Available modes: scheduled, journalism, republish")
        sys.exit(1)

    # Exit with appropriate code for CI/CD
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
