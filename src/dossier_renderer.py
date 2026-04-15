"""
Dossier renderer — generates static HTML pages for the Walter Croncat
public dossier viewer at dossier.mewscast.us.

Two public functions:
  render_dossier_page(dossier_data) -> str   # full <!DOCTYPE html> for one story
  render_index_page(entries)        -> str   # archive listing of all dossiers

Design rules:
  - Article body text NEVER appears in HTML output (copyright protection).
    Only metadata: outlet, title, URL, character count.
  - ALL string interpolation uses html.escape() (XSS prevention).
  - Failure never blocks the publishing pipeline — callers wrap in try/except.

This module is standalone: ``python src/dossier_renderer.py`` runs a smoke test
against the mock dossier at dossiers/20260408-senate-approps-mock.json.
"""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(value) -> str:
    """HTML-escape any value, coercing to str first."""
    if value is None:
        return ""
    return html.escape(str(value))


_CENTRAL = ZoneInfo("America/Chicago")


def _parse_iso(iso_str: str) -> str:
    """Parse an ISO-8601 timestamp and return a human-readable string in Central Time.

    Returns the raw string on failure (never crashes).
    """
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        # If naive (no tzinfo), assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_central = dt.astimezone(_CENTRAL)
        # %Z gives CDT or CST depending on DST
        return dt_central.strftime("%B %d, %Y at %I:%M %p %Z")
    except (ValueError, TypeError):
        return str(iso_str)


def _badge_class_for_post_type(post_type: str) -> str:
    """Return the CSS class suffix for a post type badge."""
    mapping = {
        "REPORT": "report",
        "META": "meta",
        "ANALYSIS": "analysis",
        "BULLETIN": "bulletin",
        "CORRECTION": "correction",
        "PRIMARY": "primary",
    }
    return mapping.get(post_type.upper(), "report") if post_type else "report"


def _badge_class_for_slant(slant: str) -> str:
    """Return the CSS class suffix for a slant badge."""
    mapping = {
        "wire": "wire",
        "lean-left": "lean-left",
        "lean-right": "lean-right",
        "left": "left",
        "right": "right",
        "center": "center",
        "international": "international",
        "specialized": "specialized",
        # Legacy names (pre-AllSides alignment)
        "left-mainstream": "lean-left",
        "right-mainstream": "lean-right",
    }
    return mapping.get(slant, "wire") if slant else "wire"


def _reader_friendly_slant(slant: str) -> str:
    """Convert internal slant values to reader-friendly labels for display.
    Returns empty string if the slant should be hidden."""
    mapping = {
        "wire": "Wire Service",
        "lean-left": "Lean Left",
        "lean-right": "Lean Right",
        "left": "Left",
        "right": "Right",
        "center": "Center",
        "international": "International",
        "specialized": "Beat Reporter",
        # Legacy
        "left-mainstream": "Lean Left",
        "right-mainstream": "Lean Right",
    }
    return mapping.get(slant, "") if slant else ""


# Common URL shorteners used by news outlets
_URL_SHORTENER_MAP = {
    "wapo.st": "Washington Post",
    "apo.st": "Washington Post",
    "nyti.ms": "New York Times",
    "bbc.in": "BBC News",
    "reut.rs": "Reuters",
    "abcnews.link": "ABC News",
    "nbcnews.to": "NBC News",
    "cbsn.ws": "CBS News",
    "politi.co": "Politico",
    "trib.al": "Various (via trib.al)",
    "bit.ly": "",
    "t.co": "",
    "x.com": "",
}


def _title_from_url(url: str) -> str:
    """Extract a readable title from a URL when the article title is missing.
    Tries URL shortener lookup first, then extracts from the URL path."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = (parsed.netloc or "").lower().lstrip("www.")

        # Check shortener map
        if domain in _URL_SHORTENER_MAP:
            name = _URL_SHORTENER_MAP[domain]
            if name:
                return f"Article via {name}"
            return ""

        # Extract a readable slug from the URL path
        path = parsed.path or ""
        # Get the last meaningful path segment
        segments = [s for s in path.strip("/").split("/") if s and s not in ("article", "news", "story", "live")]
        if segments:
            slug = segments[-1]
            # Convert slug to readable: "trump-iran-ceasefire" -> "Trump iran ceasefire"
            readable = slug.replace("-", " ").replace("_", " ")
            # Strip file extensions
            for ext in (".html", ".htm", ".php", ".asp"):
                if readable.endswith(ext.replace(".", " ")):
                    readable = readable[:-len(ext) + 1]
            if len(readable) > 10:
                return readable.capitalize()[:80]

        return f"Article from {domain}"
    except Exception:
        return url[:60] if url else ""


def _confidence_class(confidence: float) -> str:
    """Return the CSS class for the confidence bar fill."""
    if confidence >= 0.7:
        return "confidence-high"
    elif confidence >= 0.4:
        return "confidence-medium"
    else:
        return "confidence-low"


def bluesky_web_url(uri: str) -> str:
    """Convert a Bluesky at:// URI to a bsky.app web URL.

    Example:
      ``at://did:plc:abc/app.bsky.feed.post/xyz``
        -> ``https://bsky.app/profile/did:plc:abc/post/xyz``

    If ``uri`` is already an http(s) URL, it is returned unchanged. Returns
    an empty string for empty/unparseable input so callers can treat it as
    "no link".
    """
    if not uri:
        return ""
    if uri.startswith("http://") or uri.startswith("https://"):
        return uri
    if not uri.startswith("at://"):
        return ""
    parts = uri[len("at://"):].split("/")
    # Expect [did, collection, rkey] — anything else is malformed.
    if len(parts) < 3:
        return ""
    did, _collection, rkey = parts[0], parts[1], parts[2]
    if not did or not rkey:
        return ""
    return f"https://bsky.app/profile/{did}/post/{rkey}"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_section_1_post(data: dict) -> str:
    """Section 1 — The Post."""
    post = data.get("post") or {}
    draft = post.get("draft") or {}

    text = draft.get("text", "")
    post_type = draft.get("post_type", "")
    sign_off = draft.get("sign_off", "")
    published_at = post.get("published_at", "")
    post_url = post.get("post_url")
    bluesky_url = post.get("bluesky_url")
    outlets = draft.get("outlets_referenced") or []

    badge_cls = _badge_class_for_post_type(post_type)

    lines = []
    lines.append('<h2 class="section-heading">The Post</h2>')
    lines.append('<div class="card">')

    # Post type badge + timestamp
    lines.append('<div class="header-meta">')
    lines.append(f'  <span class="badge badge-{_esc(badge_cls)}">{_esc(post_type)}</span>')
    if published_at:
        lines.append(f'  <span>{_esc(_parse_iso(published_at))}</span>')
    lines.append('</div>')

    # Post text block
    lines.append(f'<div class="post-text">{_esc(text)}</div>')

    # Sign-off
    if sign_off:
        lines.append(f'<span class="post-sign-off">{_esc(sign_off)}</span>')

    # Links — render "View on X" and/or "View on Bluesky" depending on
    # which platforms accepted the post. Older records only stored a single
    # post_url; if that URL is an at:// URI it belongs to Bluesky, so we
    # convert and route it accordingly.
    x_link = None
    bsky_link = bluesky_web_url(bluesky_url) if bluesky_url else ""

    if post_url:
        if post_url.startswith("at://"):
            # Legacy record: post_url actually points at a Bluesky skeet.
            if not bsky_link:
                bsky_link = bluesky_web_url(post_url)
        else:
            x_link = post_url

    links_parts = []
    if x_link:
        links_parts.append(
            f'<a href="{_esc(x_link)}" target="_blank" rel="noopener">View on X</a>'
        )
    if bsky_link:
        links_parts.append(
            f'<a href="{_esc(bsky_link)}" target="_blank" rel="noopener">View on Bluesky</a>'
        )
    if links_parts:
        lines.append(f'<div class="post-links">{" ".join(links_parts)}</div>')

    # Outlet tags
    if outlets:
        lines.append('<div class="outlet-tags">')
        for outlet in outlets:
            lines.append(f'  <span class="outlet-tag">{_esc(outlet)}</span>')
        lines.append('</div>')

    lines.append('</div>')
    return "\n".join(lines)


def _render_section_2_sources(data: dict) -> str:
    """Section 2 — What Walter Read."""
    dossier = data.get("dossier") or {}
    articles = dossier.get("articles") or []
    primary_sources = dossier.get("primary_sources") or []
    outlet_slants = dossier.get("outlet_slants") or {}

    lines = []
    lines.append('<h2 class="section-heading">What Walter Read</h2>')

    if not articles:
        lines.append('<div class="card"><p>No articles were gathered for this story.</p></div>')
    else:
        for article in articles:
            outlet = article.get("outlet", "Unknown")
            url = article.get("url", "")
            title = article.get("title", "")
            body = article.get("body", "")
            headline_only = article.get("headline_only", False)
            char_count = len(body) if body else 0

            # Determine fetch status
            is_headline_only = headline_only or char_count < 500
            slant = outlet_slants.get(outlet, "")
            slant_label = _reader_friendly_slant(slant)
            slant_cls = _badge_class_for_slant(slant)

            # Build a display title — fall back to a cleaned-up URL if title is empty
            display_title = title.strip() if title else ""
            if not display_title and url:
                display_title = _title_from_url(url)

            lines.append('<div class="article-card">')
            lines.append('  <div class="article-card-header">')
            lines.append(f'    <span class="article-card-outlet">{_esc(outlet)}</span>')
            if slant_label:
                lines.append(f'    <span class="badge badge-{_esc(slant_cls)}">{_esc(slant_label)}</span>')
            if is_headline_only:
                lines.append('    <span class="fetch-status fetch-status-headline">Headline Only</span>')
            else:
                lines.append('    <span class="fetch-status fetch-status-full">Full Text</span>')
            lines.append('  </div>')

            if display_title:
                if url:
                    lines.append(f'  <div class="article-card-title"><a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(display_title)}</a></div>')
                else:
                    lines.append(f'  <div class="article-card-title">{_esc(display_title)}</div>')

            lines.append('  <div class="article-card-meta">')
            lines.append(f'    <span>{_esc(str(char_count))} characters fetched</span>')
            if url:
                lines.append(f'    <a href="{_esc(url)}" target="_blank" rel="noopener">View original</a>')
            lines.append('  </div>')
            lines.append('</div>')

    # Primary sources
    if primary_sources:
        lines.append('<h3 style="margin-top: 1.25rem; margin-bottom: 0.75rem; font-size: 0.95rem; color: var(--teal);">Primary Sources</h3>')
        for source in primary_sources:
            kind = source.get("kind", "")
            s_url = source.get("url", "")
            s_title = source.get("title", "")

            lines.append('<div class="source-card">')
            if kind:
                lines.append(f'  <div class="source-card-kind">{_esc(kind)}</div>')
            if s_title:
                if s_url:
                    lines.append(f'  <div class="source-card-title"><a href="{_esc(s_url)}" target="_blank" rel="noopener">{_esc(s_title)}</a></div>')
                else:
                    lines.append(f'  <div class="source-card-title">{_esc(s_title)}</div>')
            elif s_url:
                lines.append(f'  <div class="source-card-title"><a href="{_esc(s_url)}" target="_blank" rel="noopener">{_esc(s_url)}</a></div>')
            lines.append('</div>')

    return "\n".join(lines)


def _render_section_3_brief(data: dict) -> str:
    """Section 3 — The Meta-Analysis Brief."""
    brief = data.get("brief") or {}

    confidence = brief.get("confidence", 0.0)
    suggested_type = brief.get("suggested_post_type", "")
    suggested_reason = brief.get("suggested_post_type_reason", "")
    consensus = brief.get("consensus_facts") or []
    disagreements = brief.get("disagreements") or []
    framing = brief.get("framing_analysis") or {}
    alignment = brief.get("primary_source_alignment") or []
    missing = brief.get("missing_context") or []

    pct = int(confidence * 100)
    conf_cls = _confidence_class(confidence)

    lines = []
    lines.append('<h2 class="section-heading">Meta-Analysis Brief</h2>')
    lines.append('<div class="card">')

    # Confidence bar
    lines.append('<div class="confidence-bar-container">')
    lines.append(f'  <div class="confidence-label">Confidence: <strong>{_esc(str(pct))}%</strong></div>')
    lines.append('  <div class="confidence-bar">')
    lines.append(f'    <div class="confidence-bar-fill {conf_cls}" style="width: {pct}%"></div>')
    lines.append('  </div>')
    lines.append('</div>')

    # Suggested post type
    if suggested_type:
        badge_cls = _badge_class_for_post_type(suggested_type)
        lines.append(f'<p style="margin-top: 0.75rem; font-size: 0.85rem; color: var(--secondary);">')
        lines.append(f'  Suggested post type: <span class="badge badge-{_esc(badge_cls)}">{_esc(suggested_type)}</span>')
        if suggested_reason:
            lines.append(f'  &mdash; {_esc(suggested_reason)}')
        lines.append('</p>')

    # Consensus facts
    if consensus:
        lines.append('<h3 style="margin-top: 1.25rem; font-size: 0.9rem;">Consensus Facts</h3>')
        lines.append('<ul class="fact-list">')
        for fact in consensus:
            lines.append(f'  <li>{_esc(fact)}</li>')
        lines.append('</ul>')

    # Disagreements
    if disagreements:
        lines.append('<h3 style="margin-top: 1.25rem; font-size: 0.9rem;">Disagreements</h3>')
        for d in disagreements:
            topic = d.get("topic", "")
            positions = d.get("positions") or {}
            lines.append('<div class="disagreement-row">')
            lines.append(f'  <div class="disagreement-topic">{_esc(topic)}</div>')
            for outlet, position in positions.items():
                lines.append(f'  <div class="disagreement-position"><strong>{_esc(outlet)}:</strong> {_esc(position)}</div>')
            lines.append('</div>')

    # Framing analysis
    if framing:
        lines.append('<h3 style="margin-top: 1.25rem; font-size: 0.9rem;">Framing Analysis</h3>')
        for outlet, description in framing.items():
            lines.append('<div class="framing-entry">')
            lines.append(f'  <span class="framing-outlet">{_esc(outlet)}</span>')
            lines.append(f'  <span class="framing-description">{_esc(description)}</span>')
            lines.append('</div>')

    # Primary source alignment
    if alignment:
        lines.append('<h3 style="margin-top: 1.25rem; font-size: 0.9rem;">Primary Source Alignment</h3>')
        lines.append('<ul class="alignment-list">')
        for item in alignment:
            lines.append(f'  <li>{_esc(item)}</li>')
        lines.append('</ul>')

    # Missing context
    if missing:
        lines.append('<div class="warning-box" style="margin-top: 1.25rem;">')
        lines.append('  <div class="warning-box-title">Missing Context</div>')
        lines.append('  <ul>')
        for item in missing:
            lines.append(f'    <li>{_esc(item)}</li>')
        lines.append('  </ul>')
        lines.append('</div>')

    lines.append('</div>')
    return "\n".join(lines)


def _render_section_4_verification(data: dict) -> str:
    """Section 4 — Verification Gate Results."""
    verification = data.get("verification")

    lines = []
    lines.append('<h2 class="section-heading">Verification Gate Results</h2>')

    if not verification:
        lines.append('<div class="coming-soon">')
        lines.append('  <h3>Coming Soon: Verification Gate Results</h3>')
        lines.append('  <p>Every hard rule check run before publication.</p>')
        lines.append('</div>')
        return "\n".join(lines)

    passed = verification.get("passed", False)
    failures = verification.get("failures") or []

    lines.append('<div class="card">')
    if passed:
        lines.append('  <span class="badge badge-primary">PASSED</span>')
        if not failures:
            lines.append('  <p style="margin-top: 0.75rem;">All verification checks passed.</p>')
    else:
        lines.append('  <span class="badge badge-bulletin">FAILED</span>')

    if failures:
        lines.append('  <div class="warning-box" style="margin-top: 0.75rem;">')
        lines.append('    <div class="warning-box-title">Failures</div>')
        lines.append('    <ul>')
        for failure in failures:
            lines.append(f'      <li>{_esc(failure)}</li>')
        lines.append('    </ul>')
        lines.append('  </div>')

    lines.append('</div>')
    return "\n".join(lines)


def _render_section_5_analysis(data: dict) -> str:
    """Section 5 — Draft Analysis."""
    analysis = data.get("analysis")

    lines = []
    lines.append('<h2 class="section-heading">Draft Analysis</h2>')

    if not analysis or analysis.get("overall") == "SKIPPED":
        lines.append('<div class="coming-soon">')
        lines.append('  <h3>Coming Soon: Draft Analysis</h3>')
        lines.append('  <p>AI fact-check comparing the draft against source material.</p>')
        lines.append('</div>')
        return "\n".join(lines)

    overall = analysis.get("overall", "UNKNOWN")
    findings = analysis.get("findings") or []

    lines.append('<div class="card">')

    if overall == "CLEAN":
        lines.append('  <span class="badge badge-primary">CLEAN</span>')
        lines.append('  <p style="margin-top: 0.75rem;">No factual issues found.</p>')
    elif overall == "ESCALATION":
        lines.append('  <span class="badge badge-analysis">ESCALATION</span>')
    elif overall == "FABRICATION":
        lines.append('  <span class="badge badge-bulletin">FABRICATION</span>')
    else:
        lines.append(f'  <span class="badge badge-wire">{_esc(overall)}</span>')

    if findings:
        lines.append('  <ul class="fact-list" style="margin-top: 0.75rem;">')
        for finding in findings:
            category = finding.get("category", "")
            severity = finding.get("severity", "")
            assessment = finding.get("assessment", "")
            draft_says = finding.get("draft_says", "")
            sources_say = finding.get("sources_say", "")

            parts = []
            if category:
                parts.append(f'<strong>{_esc(category)}</strong>')
            if severity:
                parts.append(f'({_esc(severity)})')
            if assessment:
                parts.append(f'&mdash; {_esc(assessment)}')
            label = " ".join(parts)

            lines.append(f'    <li>{label}')
            if draft_says:
                lines.append(f'      <br><span style="color: var(--secondary); font-size: 0.85rem;">Draft says: {_esc(draft_says)}</span>')
            if sources_say:
                lines.append(f'      <br><span style="color: var(--secondary); font-size: 0.85rem;">Sources say: {_esc(sources_say)}</span>')
            lines.append('    </li>')
        lines.append('  </ul>')

    lines.append('</div>')
    return "\n".join(lines)


def _render_section_6_selection(data: dict) -> str:
    """Section 6 — Story Selection."""
    selection = data.get("selection")

    lines = []
    lines.append('<h2 class="section-heading">Story Selection</h2>')

    if not selection:
        lines.append('<div class="coming-soon">')
        lines.append('  <h3>Coming Soon: Story Selection</h3>')
        lines.append('  <p>How this story was chosen from the trending candidates.</p>')
        lines.append('</div>')
        return "\n".join(lines)

    candidates_detected = selection.get("candidates_detected", 0)
    candidates_passed = selection.get("candidates_passed_triage", 0)
    headline = selection.get("headline_seed", "")
    source = selection.get("source", "unknown")

    lines.append('<div class="card">')
    lines.append(f'  <p><strong>{_esc(str(candidates_detected))}</strong> candidates detected, '
                 f'<strong>{_esc(str(candidates_passed))}</strong> passed triage</p>')

    if headline:
        lines.append(f'  <p style="margin-top: 0.5rem;">Selected: <strong>{_esc(headline)}</strong></p>')

    lines.append(f'  <p style="margin-top: 0.5rem; font-size: 0.85rem; color: var(--secondary);">'
                 f'Source: {_esc(source)}</p>')

    lines.append('</div>')
    return "\n".join(lines)


def _render_post_image(data: dict) -> str:
    """Render the generated post image, if one exists in the dossier data."""
    image_path = data.get("image_path")
    if not image_path:
        return ""
    return (
        '<div class="post-image-container">\n'
        f'  <img class="post-image" src="./{_esc(image_path)}"'
        f' alt="AI-generated illustration for this story">\n'
        '</div>'
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_dossier_page(dossier_data: dict) -> str:
    """Render a full dossier page as a complete HTML document.

    Takes the full dossier JSON dict (same shape as dossiers/<story_id>.json)
    and returns a ``<!DOCTYPE html>`` string.

    Article body text NEVER appears in the output — only metadata.
    All string interpolation uses html.escape().
    """
    dossier = dossier_data.get("dossier") or {}
    headline = dossier.get("headline_seed", "Walter Croncat Dossier")
    story_id = dossier_data.get("story_id", "")
    post = dossier_data.get("post") or {}
    draft = post.get("draft") or {}
    published_at = post.get("published_at", "")

    # OG description: first consensus fact, or the post text truncated
    brief = dossier_data.get("brief") or {}
    consensus = brief.get("consensus_facts") or []
    post_text = draft.get("text", "")
    og_description = consensus[0] if consensus else (post_text[:200] if post_text else "Walter Croncat journalism dossier")

    image_path = dossier_data.get("image_path")

    sections = [
        _render_section_1_post(dossier_data),
        _render_post_image(dossier_data),
        _render_section_2_sources(dossier_data),
        _render_section_3_brief(dossier_data),
        _render_section_4_verification(dossier_data),
        _render_section_5_analysis(dossier_data),
        _render_section_6_selection(dossier_data),
    ]

    body_html = "\n\n".join(sections)

    # Header
    header_html = f"""<div class="header">
  <div class="header-brand">
    <a href="../">Walter Croncat</a> &middot; <a href="./index.html">Dossiers</a>
  </div>
  <h1>{_esc(headline)}</h1>
  <div class="header-meta">
    <span>{_esc(story_id)}</span>
    {f'<span>{_esc(_parse_iso(published_at))}</span>' if published_at else ''}
  </div>
</div>"""

    # Footer
    footer_html = """<div class="footer">
  And that's the mews. &middot;
  <a href="./index.html">Dossiers</a> &middot;
  Made by <a href="https://x.com/bryanofearth" target="_blank" rel="noopener">@bryanofearth</a>
</div>"""

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(headline)} &mdash; Walter Croncat Dossier</title>
  <meta property="og:title" content="{_esc(headline)}">
  <meta property="og:description" content="{_esc(og_description)}">
  <meta property="og:type" content="article">
  <meta property="og:image" content="{f'https://mewscast.us/dossiers/{_esc(image_path)}' if image_path else 'https://mewscast.us/images/walter-croncat-dossier-og.png'}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{f'https://mewscast.us/dossiers/{_esc(image_path)}' if image_path else 'https://mewscast.us/images/walter-croncat-dossier-og.png'}">
  <link rel="stylesheet" href="./style.css">
</head>
<body>
<div class="page">

{header_html}

{body_html}

{footer_html}

</div>
</body>
</html>"""

    return page


def render_index_page(entries: list[dict]) -> str:
    """Render the dossier archive index page.

    Takes a list of dossier data dicts (same shape as individual JSON files),
    sorted chronologically (newest first). Each entry becomes a card showing
    date, headline, post-type badge, confidence score, and link.
    """
    # Sort entries by published_at descending (newest first)
    def _sort_key(entry: dict) -> str:
        post = entry.get("post") or {}
        return post.get("published_at") or entry.get("saved_at") or ""

    sorted_entries = sorted(entries, key=_sort_key, reverse=True)

    entry_cards = []
    for entry in sorted_entries:
        dossier = entry.get("dossier") or {}
        headline = dossier.get("headline_seed", "Untitled")
        story_id = entry.get("story_id", "")
        post = entry.get("post") or {}
        draft = post.get("draft") or {}
        post_type = draft.get("post_type", "")
        published_at = post.get("published_at") or entry.get("saved_at", "")
        brief = entry.get("brief") or {}
        confidence = brief.get("confidence", 0.0)
        pct = int(confidence * 100)

        badge_cls = _badge_class_for_post_type(post_type)

        # Build filename the same way main.py does
        safe_id = _safe_filename(story_id) if story_id else "unknown"

        card = f"""<a class="index-entry" href="./{_esc(safe_id)}.html">
  <span class="index-date">{_esc(_parse_iso(published_at))}</span>
  <span class="index-headline">{_esc(headline)}</span>
  <span class="badge badge-{_esc(badge_cls)}">{_esc(post_type)}</span>
  <span class="index-confidence">{_esc(str(pct))}% confidence</span>
</a>"""
        entry_cards.append(card)

    if not entry_cards:
        entries_html = '<div class="card"><p>No dossiers have been published yet. Check back after Walter Croncat publishes a story.</p></div>'
    else:
        entries_html = '<div class="index-grid">\n' + "\n".join(entry_cards) + "\n</div>"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dossiers &mdash; Walter Croncat</title>
  <meta property="og:title" content="Dossiers - Walter Croncat">
  <meta property="og:description" content="Every Walter Croncat journalism post, fully sourced and transparent.">
  <meta property="og:type" content="website">
  <meta property="og:image" content="https://mewscast.us/images/walter-croncat-dossier-og.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="https://mewscast.us/images/walter-croncat-dossier-og.png">
  <link rel="stylesheet" href="./style.css">
</head>
<body>
<div class="page">

<div class="header">
  <div class="header-brand"><a href="../">Walter Croncat</a> &middot; Dossiers</div>
  <h1>Dossiers</h1>
  <div class="header-meta">
    <span>Every story, fully sourced</span>
  </div>
</div>

{entries_html}

<div class="footer">
  And that's the mews. &middot;
  Made by <a href="https://x.com/bryanofearth" target="_blank" rel="noopener">@bryanofearth</a>
</div>

</div>
</body>
</html>"""

    return page


def _safe_filename(text: str) -> str:
    """Make a story id safe for use as a filename (matches main.py logic)."""
    if not text:
        return "unknown"
    out = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("-")
    return "".join(out)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    """Quick validation against the mock dossier."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mock_path = os.path.join(project_root, "dossiers", "20260408-senate-approps-mock.json")

    with open(mock_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Render the dossier page
    output = render_dossier_page(data)

    # Check it's valid HTML
    assert "<!DOCTYPE html>" in output, "Missing DOCTYPE"
    assert "<html" in output, "Missing <html> tag"
    assert "</html>" in output, "Missing closing </html> tag"

    # 2. Check all 6 sections are present (3 rendered, 3 coming-soon for mock)
    assert "The Post" in output, "Missing Section 1: The Post"
    assert "What Walter Read" in output, "Missing Section 2: What Walter Read"
    assert "Meta-Analysis Brief" in output, "Missing Section 3: Meta-Analysis Brief"
    assert "Verification Gate Results" in output, "Missing Section 4: Verification Gate"
    assert "Draft Analysis" in output, "Missing Section 5: Draft Analysis"
    assert "Story Selection" in output, "Missing Section 6: Story Selection"
    # Mock has no verification/analysis/selection keys — coming-soon fallback
    assert "Coming Soon" in output, "Missing coming-soon placeholders for mock dossier"

    # 3. XSS escaping test — inject a script tag
    xss_data = json.loads(json.dumps(data))
    xss_data["dossier"]["headline_seed"] = '<script>alert("xss")</script>'
    xss_output = render_dossier_page(xss_data)
    assert "<script>" not in xss_output, "XSS: unescaped <script> tag found in output"
    assert "&lt;script&gt;" in xss_output, "XSS: escaped script tag not found"

    # 4. No article body text in output
    for article in data.get("dossier", {}).get("articles", []):
        body = article.get("body", "")
        if body and len(body) > 100:
            # Check a substantial substring of the body does NOT appear
            body_snippet = body[50:150]
            assert body_snippet not in output, (
                f"Article body text leaked into HTML output: ...{body_snippet[:40]}..."
            )

    # 5. Test the index page
    index_output = render_index_page([data])
    assert "<!DOCTYPE html>" in index_output, "Index: missing DOCTYPE"
    assert "senate-approps" in index_output.lower() or "Senate" in index_output, "Index: missing entry"

    # 6. Empty index
    empty_index = render_index_page([])
    assert "<!DOCTYPE html>" in empty_index, "Empty index: missing DOCTYPE"

    # 7. Test sections 4-6 with populated data
    rich_data = json.loads(json.dumps(data))
    rich_data["verification"] = {"passed": True, "failures": []}
    rich_data["analysis"] = {"overall": "CLEAN", "findings": []}
    rich_data["selection"] = {
        "candidates_detected": 12,
        "candidates_passed_triage": 4,
        "story_id": "test-story",
        "headline_seed": "Test headline",
        "source": "x",
    }
    rich_output = render_dossier_page(rich_data)
    assert "PASSED" in rich_output, "Section 4: missing PASSED badge"
    assert "CLEAN" in rich_output, "Section 5: missing CLEAN badge"
    assert "12" in rich_output, "Section 6: missing candidates_detected"
    assert "4" in rich_output, "Section 6: missing candidates_passed_triage"
    assert "Test headline" in rich_output, "Section 6: missing headline_seed"
    assert "Coming Soon" not in rich_output, "Sections 4-6 should not show Coming Soon with data"

    # 8. Test section 5 with FABRICATION findings
    fab_data = json.loads(json.dumps(rich_data))
    fab_data["analysis"] = {
        "overall": "FABRICATION",
        "findings": [
            {
                "category": "attribution",
                "severity": "major",
                "assessment": "Outlet not in sources",
                "draft_says": "CNN reports...",
                "sources_say": "No CNN article in dossier",
            }
        ],
    }
    fab_output = render_dossier_page(fab_data)
    assert "FABRICATION" in fab_output, "Section 5: missing FABRICATION badge"
    assert "attribution" in fab_output, "Section 5: missing finding category"
    assert "Draft says:" in fab_output, "Section 5: missing draft_says"
    assert "Sources say:" in fab_output, "Section 5: missing sources_say"

    # 9. Test section 4 with failures
    fail_data = json.loads(json.dumps(rich_data))
    fail_data["verification"] = {"passed": False, "failures": ["Char limit exceeded", "Missing sign-off"]}
    fail_output = render_dossier_page(fail_data)
    assert "FAILED" in fail_output, "Section 4: missing FAILED badge"
    assert "Char limit exceeded" in fail_output, "Section 4: missing failure detail"
    assert "Missing sign-off" in fail_output, "Section 4: missing second failure"

    # 10. XSS in section 6 headline_seed
    xss_sel_data = json.loads(json.dumps(rich_data))
    xss_sel_data["selection"]["headline_seed"] = '<img src=x onerror=alert(1)>'
    xss_sel_output = render_dossier_page(xss_sel_data)
    assert "<img" not in xss_sel_output, "XSS: unescaped <img> tag in section 6"

    print("dossier_renderer smoke test OK")


if __name__ == "__main__":
    _smoke_test()
