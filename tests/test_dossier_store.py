"""
Unit tests for src/dossier_store.py — the data classes + file-based JSON
store for the Walter Croncat journalism workflow.

Covers:
  - ArticleRecord / PrimarySource / StoryDossier round-trip
  - MetaAnalysisBrief + Disagreement round-trip
  - DraftPost round-trip
  - PostType + SIGN_OFFS keystone table
  - DossierStore save/load/list file-path layout
  - JSON schema correctness
"""
import json
import os
import sys

import pytest

# Path setup — matches tests/test_bots.py convention
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _SRC_DIR)

from dossier_store import (  # noqa: E402
    ArticleRecord,
    Disagreement,
    DossierStore,
    DraftPost,
    MetaAnalysisBrief,
    PostType,
    PrimarySource,
    SIGN_OFFS,
    StoryDossier,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_dossier() -> StoryDossier:
    return StoryDossier(
        story_id="20260408-senate-approps",
        headline_seed="Senate passes appropriations bill 68-32",
        detected_at="2026-04-08T19:30:00+00:00",
        articles=[
            ArticleRecord(
                outlet="Reuters",
                url="https://reuters.com/x",
                title="Senate passes $1.2T bill 68-32",
                body="The Senate voted 68-32 ...",
                fetched_at="2026-04-08T19:35:00+00:00",
                is_wire_derived=False,
            ),
            ArticleRecord(
                outlet="Associated Press",
                url="https://apnews.com/y",
                title="Senate passes appropriations 68-32",
                body="By a vote of 68 to 32 ...",
                fetched_at="2026-04-08T19:36:00+00:00",
                is_wire_derived=False,
            ),
        ],
        primary_sources=[
            PrimarySource(
                kind="congress_vote",
                url="https://www.senate.gov/roll_call_312",
                title="Senate roll call vote 312",
                excerpt="Yeas 68, nays 32",
            )
        ],
        outlet_slants={"Reuters": "wire", "Associated Press": "wire"},
    )


@pytest.fixture
def sample_brief() -> MetaAnalysisBrief:
    return MetaAnalysisBrief(
        story_id="20260408-senate-approps",
        consensus_facts=["Senate voted 68-32"],
        disagreements=[
            Disagreement(
                topic="framing",
                positions={"Reuters": "bipartisan", "Fox News": "eight defectors"},
            )
        ],
        framing_analysis={"Reuters": "leads on math"},
        primary_source_alignment=["Roll call confirms 68-32"],
        missing_context=["$14B disaster supplement not mentioned"],
        suggested_post_type=PostType.META,
        suggested_post_type_reason="Framing divergence.",
        confidence=0.88,
    )


@pytest.fixture
def sample_draft() -> DraftPost:
    return DraftPost(
        text="COVERAGE REPORT - the vote was 68-32.\n\nAnd that's the mews - coverage report.",
        post_type=PostType.META,
        sign_off=SIGN_OFFS[PostType.META],
        story_id="20260408-senate-approps",
        outlets_referenced=["Reuters", "Associated Press"],
        primary_source_urls=["https://www.senate.gov/roll_call_312"],
    )


# ---------------------------------------------------------------------------
# PostType + SIGN_OFFS keystone table
# ---------------------------------------------------------------------------

class TestPostTypeAndSignoffs:
    """The SIGN_OFFS dict is the single source of truth for the Cronkite rule."""

    def test_sign_offs_has_all_six_post_types(self):
        # All six post types must appear in the table — missing one would break
        # verification_gate for that type.
        assert set(SIGN_OFFS.keys()) == {
            PostType.REPORT,
            PostType.META,
            PostType.ANALYSIS,
            PostType.BULLETIN,
            PostType.CORRECTION,
            PostType.PRIMARY,
        }

    def test_report_signoff_is_the_signature(self):
        assert SIGN_OFFS[PostType.REPORT] == "And that's the mews."

    def test_meta_signoff_is_differentiated(self):
        assert SIGN_OFFS[PostType.META] == "And that's the mews — coverage report."

    def test_analysis_signoff_labels_opinion(self):
        assert SIGN_OFFS[PostType.ANALYSIS] == "This cat's view — speculative, personal, subjective."

    def test_bulletin_is_unsigned(self):
        assert SIGN_OFFS[PostType.BULLETIN] is None

    def test_correction_is_unsigned(self):
        assert SIGN_OFFS[PostType.CORRECTION] is None

    def test_primary_signoff_is_the_source_variant(self):
        assert SIGN_OFFS[PostType.PRIMARY] == "And that's the mews — straight from the source."

    def test_post_type_values_are_string_enums(self):
        # PostType must serialize as a string so the dossier JSON is stable
        assert PostType.REPORT.value == "REPORT"
        assert str(PostType.REPORT.value) == "REPORT"

    def test_coerce_post_type_from_string(self):
        assert PostType("REPORT") == PostType.REPORT
        assert PostType("META") == PostType.META


# ---------------------------------------------------------------------------
# Dataclass round-trip tests
# ---------------------------------------------------------------------------

class TestDataclassRoundTrip:
    """Every dataclass in dossier_store must round-trip cleanly through
    to_dict / from_dict via JSON. This is the contract the DossierStore
    relies on."""

    def test_article_record_roundtrip(self):
        art = ArticleRecord(
            outlet="Reuters",
            url="https://example.com/x",
            title="Title",
            body="Body",
            fetched_at="2026-04-08T19:35:00+00:00",
            is_wire_derived=True,
        )
        encoded = json.dumps(art.to_dict())
        decoded = ArticleRecord.from_dict(json.loads(encoded))
        assert decoded.to_dict() == art.to_dict()
        assert decoded.is_wire_derived is True

    def test_article_record_defaults_is_wire_derived_false(self):
        # Legacy records without is_wire_derived should load cleanly
        legacy = {
            "outlet": "Reuters",
            "url": "https://x",
            "title": "t",
            "body": "b",
            "fetched_at": "2026-04-08T00:00:00+00:00",
        }
        art = ArticleRecord.from_dict(legacy)
        assert art.is_wire_derived is False

    def test_primary_source_roundtrip_with_excerpt(self):
        ps = PrimarySource(
            kind="congress_vote",
            url="https://senate.gov/x",
            title="Roll call",
            excerpt="Yeas 68, nays 32",
        )
        encoded = json.dumps(ps.to_dict())
        decoded = PrimarySource.from_dict(json.loads(encoded))
        assert decoded.to_dict() == ps.to_dict()

    def test_primary_source_roundtrip_without_excerpt(self):
        ps = PrimarySource(
            kind="court_filing",
            url="https://pacer.uscourts.gov/x",
            title="Filing",
            excerpt=None,
        )
        decoded = PrimarySource.from_dict(json.loads(json.dumps(ps.to_dict())))
        assert decoded.excerpt is None

    def test_story_dossier_roundtrip(self, sample_dossier):
        encoded = json.dumps(sample_dossier.to_dict())
        decoded = StoryDossier.from_dict(json.loads(encoded))
        assert decoded.to_dict() == sample_dossier.to_dict()
        assert len(decoded.articles) == 2
        assert len(decoded.primary_sources) == 1
        assert decoded.outlet_slants["Reuters"] == "wire"

    def test_story_dossier_empty_defaults(self):
        d = StoryDossier(
            story_id="x",
            headline_seed="h",
            detected_at="2026-04-08T00:00:00+00:00",
        )
        decoded = StoryDossier.from_dict(json.loads(json.dumps(d.to_dict())))
        assert decoded.articles == []
        assert decoded.primary_sources == []
        assert decoded.outlet_slants == {}

    def test_disagreement_roundtrip(self):
        d = Disagreement(
            topic="casualty count",
            positions={"NYT": "14", "Fox News": "at least 20"},
        )
        encoded = json.dumps(d.to_dict())
        decoded = Disagreement.from_dict(json.loads(encoded))
        assert decoded.to_dict() == d.to_dict()

    def test_meta_analysis_brief_roundtrip(self, sample_brief):
        encoded = json.dumps(sample_brief.to_dict())
        decoded = MetaAnalysisBrief.from_dict(json.loads(encoded))
        assert decoded.to_dict() == sample_brief.to_dict()
        assert decoded.suggested_post_type == PostType.META

    def test_meta_analysis_brief_coerces_string_post_type(self, sample_brief):
        # When Claude returns a JSON payload, suggested_post_type arrives as a
        # string; from_dict must coerce it back to PostType.
        raw = sample_brief.to_dict()
        assert isinstance(raw["suggested_post_type"], str)
        decoded = MetaAnalysisBrief.from_dict(raw)
        assert decoded.suggested_post_type == PostType.META

    def test_draft_post_roundtrip(self, sample_draft):
        encoded = json.dumps(sample_draft.to_dict())
        decoded = DraftPost.from_dict(json.loads(encoded))
        assert decoded.to_dict() == sample_draft.to_dict()
        assert decoded.post_type == PostType.META
        assert decoded.sign_off == SIGN_OFFS[PostType.META]


# ---------------------------------------------------------------------------
# DossierStore file layout tests
# ---------------------------------------------------------------------------

class TestDossierStore:
    """Verify the file-path layout, save/load/list semantics, and JSON shape."""

    def test_save_and_load_dossier(self, tmp_path, sample_dossier):
        store = DossierStore(root_dir=str(tmp_path))
        path = store.save_dossier(sample_dossier)
        assert os.path.exists(path)
        assert path.startswith(str(tmp_path))
        # Filename is <story_id>.json
        assert os.path.basename(path) == sample_dossier.story_id + ".json"

        loaded = store.load_dossier(sample_dossier.story_id)
        assert loaded is not None
        assert loaded.to_dict() == sample_dossier.to_dict()

    def test_save_and_load_brief(self, tmp_path, sample_brief):
        store = DossierStore(root_dir=str(tmp_path))
        store.save_brief(sample_brief)
        loaded = store.load_brief(sample_brief.story_id)
        assert loaded is not None
        assert loaded.to_dict() == sample_brief.to_dict()

    def test_save_and_load_post_record(self, tmp_path, sample_draft):
        store = DossierStore(root_dir=str(tmp_path))
        store.save_post_record(
            sample_draft.story_id,
            sample_draft,
            post_url="https://x.com/WalterCroncat/status/1",
        )
        record = store.load_post_record(sample_draft.story_id)
        assert record is not None
        assert record["draft"] == sample_draft.to_dict()
        assert record["post_url"] == "https://x.com/WalterCroncat/status/1"
        assert "published_at" in record

    def test_dossier_brief_post_share_same_file(
        self, tmp_path, sample_dossier, sample_brief, sample_draft
    ):
        """All three records for one story_id end up in a single JSON file."""
        store = DossierStore(root_dir=str(tmp_path))
        store.save_dossier(sample_dossier)
        store.save_brief(sample_brief)
        store.save_post_record(sample_dossier.story_id, sample_draft, post_url="https://x/1")

        # There should be exactly one JSON file on disk
        files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".json")]
        assert len(files) == 1
        assert files[0] == sample_dossier.story_id + ".json"

        # Inspect raw JSON shape
        with open(os.path.join(str(tmp_path), files[0]), "r", encoding="utf-8") as f:
            raw = json.load(f)
        assert raw["story_id"] == sample_dossier.story_id
        assert "saved_at" in raw
        assert "dossier" in raw
        assert "brief" in raw
        assert "post" in raw
        assert raw["post"]["post_url"] == "https://x/1"

    def test_list_dossiers_returns_sorted(self, tmp_path, sample_dossier):
        store = DossierStore(root_dir=str(tmp_path))
        # Save three dossiers with different ids
        for suffix in ["a", "c", "b"]:
            d = StoryDossier(
                story_id=f"story-{suffix}",
                headline_seed="h",
                detected_at="2026-04-08T00:00:00+00:00",
            )
            store.save_dossier(d)
        ids = store.list_dossiers()
        assert ids == sorted(ids)
        assert "story-a" in ids and "story-b" in ids and "story-c" in ids

    def test_load_dossier_absent_returns_none(self, tmp_path):
        store = DossierStore(root_dir=str(tmp_path))
        assert store.load_dossier("nope") is None
        assert store.load_brief("nope") is None
        assert store.load_post_record("nope") is None

    def test_story_id_sanitized_for_filesystem(self, tmp_path):
        """Story IDs with characters like / or : must be coerced to a safe name."""
        store = DossierStore(root_dir=str(tmp_path))
        dirty_id = "2026/04/08:story"
        d = StoryDossier(
            story_id=dirty_id,
            headline_seed="h",
            detected_at="2026-04-08T00:00:00+00:00",
        )
        path = store.save_dossier(d)
        # The file actually on disk must NOT contain any slashes (beyond
        # the parent directory separator)
        basename = os.path.basename(path)
        assert "/" not in basename and ":" not in basename
        # And load-back by the original dirty id should still work
        loaded = store.load_dossier(dirty_id)
        assert loaded is not None

    def test_empty_story_id_rejected(self, tmp_path):
        store = DossierStore(root_dir=str(tmp_path))
        with pytest.raises(ValueError):
            DossierStore._safe_story_id("")

    def test_root_dir_auto_created(self, tmp_path):
        nested = os.path.join(str(tmp_path), "a", "b", "c")
        store = DossierStore(root_dir=nested)
        assert os.path.isdir(nested)
