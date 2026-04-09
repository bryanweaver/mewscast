"""
Stage 3 helper — Primary Source Finder (Walter Croncat journalism workflow).

Pattern-matches article bodies for known primary-source URLs and signatures
(court filings, congress.gov roll calls, federalregister.gov rules, BLS/BEA
releases, SEC filings, White House press releases, generic .gov PDFs). Returns
the list of PrimarySource records and ALSO mutates the dossier by appending
them to dossier.primary_sources.

Per the workflow doc: "Primary source is king." For accountability stories,
the verification gate at Stage 6 will check whether dossier.primary_sources is
populated and use that as a precondition for ACCOUNTABILITY-tagged posts.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from dossier_store import StoryDossier, PrimarySource


# ---------------------------------------------------------------------------
# Pattern table — order matters: most specific patterns first.
# Each entry: (regex_pattern, kind, optional_title_template)
# ---------------------------------------------------------------------------

URL_PATTERNS: list[tuple[re.Pattern, str, Optional[str]]] = [
    # ---- Legislative (most specific to least) ----
    (re.compile(r"https?://[^\s\"'<>]*congress\.gov[^\s\"'<>]*", re.IGNORECASE),
     "congress_record", None),

    # ---- Judicial ----
    (re.compile(r"https?://[^\s\"'<>]*supremecourt\.gov[^\s\"'<>]*", re.IGNORECASE),
     "scotus_filing", None),
    (re.compile(r"https?://[^\s\"'<>]*pacer\.uscourts\.gov[^\s\"'<>]*", re.IGNORECASE),
     "court_filing", None),
    (re.compile(r"https?://[^\s\"'<>]*uscourts\.gov[^\s\"'<>]*", re.IGNORECASE),
     "court_filing", "U.S. federal courts"),

    # ---- Executive branch — White House + cabinet departments ----
    (re.compile(r"https?://[^\s\"'<>]*whitehouse\.gov/briefing-room[^\s\"'<>]*", re.IGNORECASE),
     "white_house_release", None),
    (re.compile(r"https?://[^\s\"'<>]*whitehouse\.gov[^\s\"'<>]*", re.IGNORECASE),
     "white_house_release", None),
    (re.compile(r"https?://[^\s\"'<>]*justice\.gov[^\s\"'<>]*", re.IGNORECASE),
     "doj_release", "U.S. Department of Justice"),
    (re.compile(r"https?://[^\s\"'<>]*fbi\.gov[^\s\"'<>]*", re.IGNORECASE),
     "fbi_release", "FBI"),
    (re.compile(r"https?://[^\s\"'<>]*state\.gov[^\s\"'<>]*", re.IGNORECASE),
     "state_dept_release", "U.S. Department of State"),
    (re.compile(r"https?://[^\s\"'<>]*treasury\.gov[^\s\"'<>]*", re.IGNORECASE),
     "treasury_release", "U.S. Department of the Treasury"),
    (re.compile(r"https?://[^\s\"'<>]*irs\.gov[^\s\"'<>]*", re.IGNORECASE),
     "irs_release", "Internal Revenue Service"),
    (re.compile(r"https?://[^\s\"'<>]*defense\.gov[^\s\"'<>]*", re.IGNORECASE),
     "pentagon_release", "U.S. Department of Defense"),
    (re.compile(r"https?://[^\s\"'<>]*dhs\.gov[^\s\"'<>]*", re.IGNORECASE),
     "dhs_release", "U.S. Department of Homeland Security"),
    (re.compile(r"https?://[^\s\"'<>]*hhs\.gov[^\s\"'<>]*", re.IGNORECASE),
     "hhs_release", "U.S. Department of Health and Human Services"),
    (re.compile(r"https?://[^\s\"'<>]*fda\.gov[^\s\"'<>]*", re.IGNORECASE),
     "fda_release", "FDA"),
    (re.compile(r"https?://[^\s\"'<>]*epa\.gov[^\s\"'<>]*", re.IGNORECASE),
     "epa_release", "Environmental Protection Agency"),

    # ---- Independent agencies ----
    (re.compile(r"https?://[^\s\"'<>]*sec\.gov[^\s\"'<>]*", re.IGNORECASE),
     "sec_filing", None),
    (re.compile(r"https?://[^\s\"'<>]*ftc\.gov[^\s\"'<>]*", re.IGNORECASE),
     "ftc_release", "Federal Trade Commission"),
    (re.compile(r"https?://[^\s\"'<>]*federalregister\.gov[^\s\"'<>]*", re.IGNORECASE),
     "federal_register", None),

    # ---- Statistics agencies ----
    (re.compile(r"https?://[^\s\"'<>]*bls\.gov[^\s\"'<>]*", re.IGNORECASE),
     "stats_release", "Bureau of Labor Statistics release"),
    (re.compile(r"https?://[^\s\"'<>]*bea\.gov[^\s\"'<>]*", re.IGNORECASE),
     "stats_release", "Bureau of Economic Analysis release"),
    (re.compile(r"https?://[^\s\"'<>]*census\.gov[^\s\"'<>]*", re.IGNORECASE),
     "stats_release", "U.S. Census Bureau release"),

    # ---- International primary sources ----
    (re.compile(r"https?://[^\s\"'<>]*(?:un\.org|unhcr\.org|unicef\.org)[^\s\"'<>]*", re.IGNORECASE),
     "un_document", "United Nations document"),
    (re.compile(r"https?://[^\s\"'<>]*imf\.org[^\s\"'<>]*", re.IGNORECASE),
     "imf_document", "International Monetary Fund"),
    (re.compile(r"https?://[^\s\"'<>]*worldbank\.org[^\s\"'<>]*", re.IGNORECASE),
     "world_bank_document", "World Bank"),
    (re.compile(r"https?://[^\s\"'<>]*wto\.org[^\s\"'<>]*", re.IGNORECASE),
     "wto_document", "World Trade Organization"),

    # ---- Catch-all: any .pdf hosted on a .gov domain ----
    (re.compile(r"https?://[^\s\"'<>]*\.gov[^\s\"'<>]*\.pdf\b", re.IGNORECASE),
     "gov_document", None),

    # ---- Generic .gov catch-all (LAST — any specific pattern above wins) ----
    # Matches any URL with a .gov TLD that wasn't caught by a more specific
    # pattern. The negative lookahead (?![\w.-]) excludes .gov.uk, .govern,
    # .gov-site.com and similar false positives where .gov is part of a
    # larger token, not the actual TLD.
    (re.compile(r"https?://[^\s\"'<>]*\.gov(?![\w.-])(?:/[^\s\"'<>]*)?", re.IGNORECASE),
     "gov_source", "U.S. government source"),
]


def _trim_url_punctuation(url: str) -> str:
    """Strip trailing punctuation that often gets glued onto URLs in prose."""
    while url and url[-1] in ").,;:!?\"']>":
        url = url[:-1]
    return url


def _short_excerpt(body: str, url: str, span: int = 200) -> str:
    """Return a short context window around the matched URL — useful for review."""
    idx = body.find(url)
    if idx < 0:
        return ""
    start = max(0, idx - span // 2)
    end = min(len(body), idx + len(url) + span // 2)
    excerpt = body[start:end]
    excerpt = re.sub(r"\s+", " ", excerpt).strip()
    return excerpt


def _title_from_url(url: str, default: str) -> str:
    """Synthesize a human-readable title from a URL."""
    try:
        parsed = urlparse(url)
        host = parsed.netloc or url
        path = parsed.path or ""
        path_part = path.rstrip("/").split("/")[-1] if path else ""
        if path_part:
            return f"{host} — {path_part}"
        return host
    except Exception:
        return default or url


# ---------------------------------------------------------------------------
# PrimarySourceFinder
# ---------------------------------------------------------------------------

class PrimarySourceFinder:
    """Stage 3 helper — extract primary-source URLs from article bodies."""

    def find(self, dossier: StoryDossier) -> list[PrimarySource]:
        """Scan every article body in the dossier for primary-source URLs.

        Mutates `dossier.primary_sources` (appending new ones, deduplicating
        on URL) AND returns the new PrimarySource records added by this call.
        """
        existing_urls = {p.url for p in dossier.primary_sources}
        added: list[PrimarySource] = []

        for article in dossier.articles:
            body = article.body or ""
            for pattern, kind, title_template in URL_PATTERNS:
                for match in pattern.finditer(body):
                    raw_url = _trim_url_punctuation(match.group(0))
                    if raw_url in existing_urls:
                        continue
                    # Avoid duplicates within this scan as well
                    if any(p.url == raw_url for p in added):
                        continue

                    title = title_template or _title_from_url(raw_url, default=kind)
                    excerpt = _short_excerpt(body, raw_url)

                    ps = PrimarySource(
                        kind=kind,
                        url=raw_url,
                        title=title,
                        excerpt=excerpt or None,
                    )
                    added.append(ps)
                    existing_urls.add(raw_url)

        if added:
            dossier.primary_sources.extend(added)
        return added


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    from dossier_store import ArticleRecord

    body_1 = (
        "The Senate voted 68-32 on Tuesday. The roll call is available at "
        "https://www.congress.gov/118/votes/2026/04/08/roll312.htm. "
        "The bill text was published in the Federal Register at "
        "https://www.federalregister.gov/documents/2026/04/08/2026-12345/example-rule. "
        "Bureau of Labor Statistics figures came from "
        "https://www.bls.gov/news.release/empsit.pdf, "
        "and a court filing is available on PACER at "
        "https://pacer.uscourts.gov/case/12345."
    )
    body_2 = (
        "The SEC complaint was posted at https://www.sec.gov/litigation/complaints/2026/comp-2026-100.pdf. "
        "The White House issued a statement at https://www.whitehouse.gov/briefing-room/statements/2026/04/08/example/. "
        "An additional supporting PDF was hosted at https://www.example.gov/reports/2026.pdf."
    )
    # Iteration 15: added federal agency + international + generic .gov patterns.
    body_3 = (
        "DOJ press release: https://www.justice.gov/opa/pr/example-2026. "
        "FBI announcement: https://www.fbi.gov/news/press-releases/example. "
        "State Department statement: https://www.state.gov/press-release/example/. "
        "Pentagon briefing: https://www.defense.gov/News/Releases/example/. "
        "Treasury sanctions list: https://home.treasury.gov/news/press-releases/example. "
        "IRS guidance: https://www.irs.gov/newsroom/example. "
        "FDA advisory: https://www.fda.gov/news-events/press-announcements/example. "
        "EPA ruling: https://www.epa.gov/newsreleases/example. "
        "FTC complaint: https://www.ftc.gov/news-events/news/press-releases/example. "
        "DHS advisory: https://www.dhs.gov/news/2026/04/08/example. "
        "HHS report: https://www.hhs.gov/about/news/2026/04/08/example.html. "
        "UN resolution: https://www.un.org/securitycouncil/s/res/2026/example. "
        "IMF statement: https://www.imf.org/en/News/Articles/2026/example. "
        "World Bank report: https://www.worldbank.org/en/news/press-release/2026/example. "
        "WTO ruling: https://www.wto.org/english/news_e/example.htm. "
        # Generic .gov catch-all — DOT and DOE are not covered by specific patterns
        "DOT press release: https://www.transportation.gov/briefing-room/example. "
        "DOE statement: https://www.energy.gov/articles/example. "
        # False positive check: .gov.uk should NOT match
        "BBC reference: https://www.bbc.gov.uk/news/example (should be ignored)."
    )

    dossier = StoryDossier(
        story_id="20260408-test",
        headline_seed="Test story",
        detected_at="2026-04-08T19:30:00+00:00",
        articles=[
            ArticleRecord(
                outlet="Reuters",
                url="https://reuters.com/x",
                title="Story 1",
                body=body_1,
                fetched_at="2026-04-08T19:35:00+00:00",
            ),
            ArticleRecord(
                outlet="AP News",
                url="https://apnews.com/y",
                title="Story 2",
                body=body_2,
                fetched_at="2026-04-08T19:36:00+00:00",
            ),
            ArticleRecord(
                outlet="Bloomberg",
                url="https://bloomberg.com/z",
                title="Story 3",
                body=body_3,
                fetched_at="2026-04-08T19:37:00+00:00",
            ),
        ],
    )

    finder = PrimarySourceFinder()
    added = finder.find(dossier)
    kinds = {p.kind for p in added}
    # Existing v1 patterns
    expected = {
        "congress_record",
        "federal_register",
        "stats_release",
        "court_filing",
        "sec_filing",
        "white_house_release",
        "gov_document",
    }
    # Iteration 15 new patterns
    expected.update({
        "doj_release",
        "fbi_release",
        "state_dept_release",
        "treasury_release",
        "irs_release",
        "pentagon_release",
        "dhs_release",
        "hhs_release",
        "fda_release",
        "epa_release",
        "ftc_release",
        "un_document",
        "imf_document",
        "world_bank_document",
        "wto_document",
        "gov_source",  # generic .gov catch-all for state courts
    })
    missing = expected - kinds
    assert not missing, f"missing primary source kinds: {missing}"
    # False positive check: bbc.gov.uk must NOT appear in any result
    bad_urls = [p.url for p in added if "bbc.gov.uk" in p.url]
    assert not bad_urls, f"false positive on .gov.uk TLD: {bad_urls}"
    # Mutation check: dossier.primary_sources now contains them all
    assert len(dossier.primary_sources) == len(added)
    # Idempotency check: a second call should add nothing
    second_pass = finder.find(dossier)
    assert second_pass == [], f"second pass should be a no-op, added={second_pass}"

    # Punctuation strip check — trailing period should not be part of the URL
    body_3 = "See https://www.congress.gov/bill/118/HR4821."
    d2 = StoryDossier(
        story_id="d2", headline_seed="t", detected_at="2026-04-08T19:30:00+00:00",
        articles=[ArticleRecord(
            outlet="Reuters", url="https://r/x", title="t", body=body_3,
            fetched_at="2026-04-08T19:35:00+00:00",
        )],
    )
    added2 = finder.find(d2)
    assert added2, "should detect a congress.gov URL with trailing period"
    assert not added2[0].url.endswith("."), f"URL not trimmed: {added2[0].url}"

    print(f"primary_source_finder smoke test OK ({len(added)} sources detected)")


if __name__ == "__main__":
    _smoke_test()
