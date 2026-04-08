"""
Walter Croncat journalism workflow — end-to-end dry-run smoke test.

Runs `post_journalism_cycle(dry_run=True)` once and reports which stages
ran, which failed, and where the drafts landed. This is the "is the wire-up
right?" verification script asked for in Phase C.

Usage:
    python scripts/journalism_dry_run.py            # real pipeline, drafts only
    python scripts/journalism_dry_run.py --mock     # fully-offline with stub
                                                    # Anthropic + NewsFetcher
    python scripts/journalism_dry_run.py --help

Notes:
- Without --mock, the script hits the Anthropic API for meta_analysis and
  composition. Set ANTHROPIC_API_KEY in your environment (or .env).
- The script does NOT require network access for trend detection — if the
  X API is not wired, the pipeline falls back to NewsFetcher. With --mock
  both are replaced by stubs so the run is fully offline.
- Drafts land under <repo-root>/drafts/<story_id>_<post_type>.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


# Path setup — mirror the test files so relative imports resolve when the
# script is run from the repo root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_SRC = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _SRC)


def _apply_mock_mode() -> None:
    """Replace the pipeline's external dependencies with deterministic stubs.

    We do this by monkey-patching the constructors of the pipeline classes
    imported inside src/main.py. The goal is a fully-offline run that
    exercises orchestration, prompt construction, verification gate, and
    draft-file writing without touching any real API.
    """
    import main as main_mod  # type: ignore
    from dossier_store import (
        ArticleRecord,
        Disagreement,
        MetaAnalysisBrief,
        PostType,
        PrimarySource,
        StoryDossier,
    )
    from trend_detector import TrendCandidate

    # --- Stub NewsFetcher --------------------------------------------------
    class _StubNewsFetcher:
        def __init__(self, *_, **__):
            pass

        def get_top_stories(self, max_stories: int = 20):
            return [
                {
                    "title": "Senate passes appropriations bill 68-32",
                    "source": "Reuters",
                    "published_date": "2026-04-08T19:30:00+00:00",
                    "url": "https://reuters.com/x",
                    "description": "Wire copy",
                }
            ]

        def get_articles_for_topic(self, topic, max_articles=10, outlets=None):
            return [
                {
                    "title": "Reuters: Senate 68-32",
                    "url": "https://reuters.com/x",
                    "source": "Reuters",
                    "description": "Wire copy",
                },
                {
                    "title": "AP: Senate 68-32",
                    "url": "https://apnews.com/y",
                    "source": "AP News",
                    "description": "Wire copy",
                },
                {
                    "title": "NYT framing: bipartisan vote",
                    "url": "https://nytimes.com/z",
                    "source": "The New York Times",
                    "description": "A rare bipartisan vote",
                },
            ]

        def fetch_article_content(self, url: str) -> str:
            return (
                "WASHINGTON (Reuters) - The U.S. Senate voted 68-32 on Tuesday "
                "to pass a $1.2 trillion appropriations bill. The roll call is "
                "available at https://www.congress.gov/118/votes/2026/04/08/roll312.htm. "
                + ("lorem ipsum " * 30)
            )

    # --- Stub TrendDetector (returns a single deterministic candidate) ----
    class _StubTrendDetector:
        def __init__(self, *_, **__):
            pass

        def detect_trends(self, max_candidates: int = 15):
            return [
                TrendCandidate(
                    headline_seed="Senate passes appropriations bill 68-32",
                    detected_at="2026-04-08T19:30:00+00:00",
                    source_signals=["Reuters", "AP", "FoxNews"],
                    engagement=200,
                    story_id="20260408-senate-approps-mock",
                )
            ]

    # --- Stub MetaAnalyzer ------------------------------------------------
    class _StubMetaAnalyzer:
        def __init__(self, *_, **__):
            pass

        def analyze(self, dossier: StoryDossier) -> MetaAnalysisBrief:
            return MetaAnalysisBrief(
                story_id=dossier.story_id,
                consensus_facts=["Senate voted 68-32"],
                disagreements=[
                    Disagreement(
                        topic="framing",
                        positions={
                            "Reuters": "leads on the math",
                            "The New York Times": "leads on the bipartisan moment",
                        },
                    )
                ],
                framing_analysis={
                    "Reuters": "math-first",
                    "The New York Times": "politics-first",
                },
                primary_source_alignment=["Roll call confirms 68-32"],
                missing_context=["No mention of $14B disaster supplement"],
                suggested_post_type=PostType.REPORT,
                suggested_post_type_reason="Two outlets confirm identical vote counts.",
                confidence=0.85,
            )

    # --- Stub PostComposer ------------------------------------------------
    class _StubPostComposer:
        def __init__(self, *_, **__):
            pass

        def compose(
            self,
            brief,
            dossier: StoryDossier,
            post_type=None,
            max_length: int = 280,
            correction_inputs=None,
            retry_reasons=None,
        ):
            from dossier_store import DraftPost, SIGN_OFFS, PostType as _PT
            chosen = post_type or brief.suggested_post_type
            if not isinstance(chosen, _PT):
                chosen = _PT(chosen)

            # Produce a well-formed stub draft that passes verification_gate
            if chosen == _PT.REPORT:
                text = (
                    "Reuters and AP News both report the Senate passed the $1.2T "
                    "appropriations bill 68-32. Bill heads to the House.\n\n"
                    "And that's the mews."
                )
            elif chosen == _PT.META:
                text = (
                    "COVERAGE REPORT — Reuters leads on the 68-32 math while "
                    "The New York Times frames it as a rare bipartisan moment.\n\n"
                    "And that's the mews — coverage report."
                )
            elif chosen == _PT.ANALYSIS:
                text = (
                    "ANALYSIS\n\nReuters buried the defection pattern — eight GOP "
                    "senators crossed the aisle, and that's the real story.\n\n"
                    "This cat's view — speculative, personal, subjective."
                )
            elif chosen == _PT.BULLETIN:
                text = "Reuters reports a missile strike downtown. Not yet confirmed by other outlets."
            elif chosen == _PT.CORRECTION:
                text = "CORRECTION: A prior post said 72-28. The actual vote was 68-32 per congress.gov."
            else:  # PRIMARY
                text = (
                    "Per the Senate roll call, Reuters reports 68-32 on the $1.2T bill. "
                    "Bill now heads to the House.\n\n"
                    "And that's the mews — straight from the source."
                )

            return DraftPost(
                text=text,
                post_type=chosen,
                sign_off=SIGN_OFFS.get(chosen),
                story_id=dossier.story_id,
                outlets_referenced=[a.outlet for a in dossier.articles],
                primary_source_urls=[p.url for p in dossier.primary_sources],
            )

    # Apply the patches to the main module's namespace so its constructors
    # produce the stubs when post_journalism_cycle instantiates them.
    main_mod.NewsFetcher = _StubNewsFetcher
    main_mod.TrendDetector = _StubTrendDetector
    main_mod.MetaAnalyzer = _StubMetaAnalyzer
    main_mod.PostComposer = _StubPostComposer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Replace TrendDetector/NewsFetcher/MetaAnalyzer/PostComposer with "
             "deterministic stubs for fully-offline runs.",
    )
    args = parser.parse_args()

    # Make sure the repo's .env is loaded so ANTHROPIC_API_KEY is picked up
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    if args.mock:
        print("[journalism_dry_run] --mock active, installing stubs...")
        _apply_mock_mode()

    # Import AFTER any mock patching so the right symbols are in place
    import main as main_mod  # type: ignore

    print("[journalism_dry_run] running post_journalism_cycle(dry_run=True)")
    ok = main_mod.post_journalism_cycle(dry_run=True)

    drafts_dir = os.path.join(_PROJECT_ROOT, "drafts")
    landed = []
    if os.path.isdir(drafts_dir):
        for root, _dirs, files in os.walk(drafts_dir):
            for name in files:
                if name.endswith(".md"):
                    landed.append(os.path.relpath(os.path.join(root, name), _PROJECT_ROOT))

    summary = {
        "dry_run_ok": bool(ok),
        "drafts_dir": os.path.relpath(drafts_dir, _PROJECT_ROOT),
        "drafts_written": sorted(landed),
    }
    print("\n[journalism_dry_run] summary:")
    print(json.dumps(summary, indent=2))

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
