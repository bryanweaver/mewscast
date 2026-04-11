"""
Dossier store — persistence and data classes for the Walter Croncat journalism pipeline.

Every published post under the journalism workflow has an associated StoryDossier
(the raw inputs gathered from multiple outlets) and a MetaAnalysisBrief (the
structured analysis of how the story was reported). These are saved as JSON under
dossiers/<story_id>.json so each post is auditable after the fact.

This module is pure data + persistence — no network I/O, no LLM calls, no
dependencies on the rest of the pipeline. Stages 1-6 of the Croncat workflow
import from here; nothing here imports from them.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Post types + sign-off table (the keystone rule lives here)
# ---------------------------------------------------------------------------

class PostType(str, Enum):
    """The six post types used by the Croncat journalism workflow."""
    REPORT = "REPORT"
    META = "META"
    ANALYSIS = "ANALYSIS"
    BULLETIN = "BULLETIN"
    CORRECTION = "CORRECTION"
    PRIMARY = "PRIMARY"


# The sign-off table is the single source of truth for the Cronkite
# withholding rule. Stage 6 (verification_gate) reads from this dict to
# enforce that every post type closes with the correct sign-off — and,
# crucially, that BULLETIN and CORRECTION posts carry no sign-off at all.
SIGN_OFFS: dict[PostType, Optional[str]] = {
    PostType.REPORT:     "And that's the mews.",
    PostType.META:       "And that's the mews — coverage report.",
    PostType.ANALYSIS:   "This cat's view — speculative, personal, subjective.",
    PostType.BULLETIN:   None,
    PostType.CORRECTION: None,
    PostType.PRIMARY:    "And that's the mews — straight from the source.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _coerce_post_type(value) -> PostType:
    """Accept a PostType, a str, or None and coerce to PostType."""
    if isinstance(value, PostType):
        return value
    if isinstance(value, str):
        return PostType(value)
    raise TypeError(f"Cannot coerce {value!r} to PostType")


# ---------------------------------------------------------------------------
# Dataclasses — raw dossier inputs (Stage 3 output)
# ---------------------------------------------------------------------------

@dataclass
class ArticleRecord:
    """A single article fetched from an outlet for a given story."""
    outlet: str
    url: str
    title: str
    body: str
    fetched_at: str              # ISO-8601 timestamp
    is_wire_derived: bool = False
    headline_only: bool = False  # True when body is empty or short (<500 chars)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ArticleRecord":
        return cls(
            outlet=d["outlet"],
            url=d["url"],
            title=d["title"],
            body=d["body"],
            fetched_at=d["fetched_at"],
            is_wire_derived=bool(d.get("is_wire_derived", False)),
            headline_only=bool(d.get("headline_only", False)),
        )


@dataclass
class PrimarySource:
    """A primary-source document underlying a story."""
    kind: str                    # "court_filing", "congress_vote", "press_release", "study", "transcript", ...
    url: str
    title: str
    excerpt: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PrimarySource":
        return cls(
            kind=d["kind"],
            url=d["url"],
            title=d["title"],
            excerpt=d.get("excerpt"),
        )


@dataclass
class StoryDossier:
    """Everything Stage 3 gathered for a story, before the Stage 4 brief."""
    story_id: str
    headline_seed: str
    detected_at: str             # ISO-8601 timestamp
    articles: list[ArticleRecord] = field(default_factory=list)
    primary_sources: list[PrimarySource] = field(default_factory=list)
    outlet_slants: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "story_id": self.story_id,
            "headline_seed": self.headline_seed,
            "detected_at": self.detected_at,
            "articles": [a.to_dict() for a in self.articles],
            "primary_sources": [p.to_dict() for p in self.primary_sources],
            "outlet_slants": dict(self.outlet_slants),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StoryDossier":
        return cls(
            story_id=d["story_id"],
            headline_seed=d["headline_seed"],
            detected_at=d["detected_at"],
            articles=[ArticleRecord.from_dict(a) for a in d.get("articles", [])],
            primary_sources=[PrimarySource.from_dict(p) for p in d.get("primary_sources", [])],
            outlet_slants=dict(d.get("outlet_slants", {})),
        )


# ---------------------------------------------------------------------------
# Dataclasses — Stage 4 brief
# ---------------------------------------------------------------------------

@dataclass
class Disagreement:
    """One disagreement across outlets in how they reported a fact."""
    topic: str                   # e.g. "casualty count", "attribution of responsibility"
    positions: dict[str, str]    # e.g. {"NYT": "officials say 14", "Fox News": "at least 20"}

    def to_dict(self) -> dict:
        return {"topic": self.topic, "positions": dict(self.positions)}

    @classmethod
    def from_dict(cls, d: dict) -> "Disagreement":
        return cls(
            topic=d["topic"],
            positions=dict(d.get("positions", {})),
        )


@dataclass
class MetaAnalysisBrief:
    """The structured output of Stage 4 meta-analysis."""
    story_id: str
    consensus_facts: list[str]
    disagreements: list[Disagreement]
    framing_analysis: dict[str, str]     # outlet -> framing summary
    primary_source_alignment: list[str]
    missing_context: list[str]
    suggested_post_type: PostType
    suggested_post_type_reason: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "story_id": self.story_id,
            "consensus_facts": list(self.consensus_facts),
            "disagreements": [d.to_dict() for d in self.disagreements],
            "framing_analysis": dict(self.framing_analysis),
            "primary_source_alignment": list(self.primary_source_alignment),
            "missing_context": list(self.missing_context),
            "suggested_post_type": self.suggested_post_type.value,
            "suggested_post_type_reason": self.suggested_post_type_reason,
            "confidence": float(self.confidence),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MetaAnalysisBrief":
        return cls(
            story_id=d["story_id"],
            consensus_facts=list(d.get("consensus_facts", [])),
            disagreements=[Disagreement.from_dict(x) for x in d.get("disagreements", [])],
            framing_analysis=dict(d.get("framing_analysis", {})),
            primary_source_alignment=list(d.get("primary_source_alignment", [])),
            missing_context=list(d.get("missing_context", [])),
            suggested_post_type=_coerce_post_type(d["suggested_post_type"]),
            suggested_post_type_reason=d.get("suggested_post_type_reason", ""),
            confidence=float(d.get("confidence", 0.0)),
        )


# ---------------------------------------------------------------------------
# Dataclasses — Stage 5 draft post
# ---------------------------------------------------------------------------

@dataclass
class DraftPost:
    """A post drafted by Stage 5 (post_composer), before verification + publish."""
    text: str
    post_type: PostType
    sign_off: Optional[str]
    story_id: str
    outlets_referenced: list[str]
    primary_source_urls: list[str]
    hedges_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "post_type": self.post_type.value,
            "sign_off": self.sign_off,
            "story_id": self.story_id,
            "outlets_referenced": list(self.outlets_referenced),
            "primary_source_urls": list(self.primary_source_urls),
            "hedges_used": list(self.hedges_used),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DraftPost":
        return cls(
            text=d["text"],
            post_type=_coerce_post_type(d["post_type"]),
            sign_off=d.get("sign_off"),
            story_id=d["story_id"],
            outlets_referenced=list(d.get("outlets_referenced", [])),
            primary_source_urls=list(d.get("primary_source_urls", [])),
            hedges_used=list(d.get("hedges_used", [])),
        )


# ---------------------------------------------------------------------------
# File-based JSON store
# ---------------------------------------------------------------------------

class DossierStore:
    """File-based JSON store for StoryDossier + MetaAnalysisBrief records.

    Layout: one JSON file per story at ``<root_dir>/<story_id>.json``. Each file
    is a self-contained record containing the dossier, the brief, and the
    published post record together — so grading, replays, and transparency
    exports can all work off a single file.

    File shape:
    ```
    {
      "story_id": "...",
      "saved_at": "...",
      "dossier":   {...}  # StoryDossier.to_dict(), or missing
      "brief":     {...}  # MetaAnalysisBrief.to_dict(), or missing
      "post":      {...}  # {"draft": DraftPost.to_dict(), "post_url": ..., "published_at": ...}
    }
    ```
    """

    def __init__(self, root_dir: Optional[str] = None):
        if root_dir is None:
            root_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "dossiers",
            )
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)

    # ---- path helpers --------------------------------------------------

    def _path_for(self, story_id: str) -> str:
        safe_id = self._safe_story_id(story_id)
        return os.path.join(self.root_dir, f"{safe_id}.json")

    @staticmethod
    def _safe_story_id(story_id: str) -> str:
        """Normalize a story_id into something filesystem-safe."""
        if not story_id:
            raise ValueError("story_id cannot be empty")
        # Replace anything that isn't alnum, dash, underscore, or dot with '-'
        out = []
        for ch in story_id:
            if ch.isalnum() or ch in ("-", "_", "."):
                out.append(ch)
            else:
                out.append("-")
        return "".join(out)

    # ---- low-level read/write -----------------------------------------

    def _read(self, story_id: str) -> dict:
        path = self._path_for(story_id)
        if not os.path.exists(path):
            return {"story_id": story_id}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, story_id: str, data: dict) -> str:
        path = self._path_for(story_id)
        data["story_id"] = story_id
        data["saved_at"] = _now_iso()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        return path

    # ---- dossier ------------------------------------------------------

    def save_dossier(self, dossier: StoryDossier) -> str:
        """Write (or merge) a StoryDossier into its story file. Returns the file path."""
        data = self._read(dossier.story_id)
        data["dossier"] = dossier.to_dict()
        return self._write(dossier.story_id, data)

    def load_dossier(self, story_id: str) -> Optional[StoryDossier]:
        """Return the StoryDossier for a story, or None if absent."""
        data = self._read(story_id)
        raw = data.get("dossier")
        if not raw:
            return None
        return StoryDossier.from_dict(raw)

    # ---- brief --------------------------------------------------------

    def save_brief(self, brief: MetaAnalysisBrief) -> str:
        """Write (or merge) a MetaAnalysisBrief into its story file. Returns the file path."""
        data = self._read(brief.story_id)
        data["brief"] = brief.to_dict()
        return self._write(brief.story_id, data)

    def load_brief(self, story_id: str) -> Optional[MetaAnalysisBrief]:
        """Return the MetaAnalysisBrief for a story, or None if absent."""
        data = self._read(story_id)
        raw = data.get("brief")
        if not raw:
            return None
        return MetaAnalysisBrief.from_dict(raw)

    # ---- post record --------------------------------------------------

    def save_post_record(
        self,
        story_id: str,
        draft: DraftPost,
        post_url: Optional[str] = None,
    ) -> str:
        """Write (or merge) the published-post record for a story."""
        data = self._read(story_id)
        data["post"] = {
            "draft": draft.to_dict(),
            "post_url": post_url,
            "published_at": _now_iso(),
        }
        return self._write(story_id, data)

    def load_post_record(self, story_id: str) -> Optional[dict]:
        """Return the raw post record dict (draft + post_url + published_at), or None."""
        data = self._read(story_id)
        return data.get("post")

    # ---- raw access (for the dossier renderer) -------------------------

    def read_raw(self, story_id: str) -> dict:
        """Read the full dossier JSON dict for a story_id. Returns {} if not found."""
        data = self._read(story_id)
        # _read returns {"story_id": story_id} when the file doesn't exist,
        # but that's not a real dossier — return {} if there's no dossier key.
        if "dossier" not in data and "post" not in data and "brief" not in data:
            return {}
        return data

    # ---- listing ------------------------------------------------------

    def list_dossiers(self) -> list[str]:
        """Return the list of story_ids currently stored (sorted for determinism)."""
        if not os.path.isdir(self.root_dir):
            return []
        ids: list[str] = []
        for name in os.listdir(self.root_dir):
            if name.endswith(".json"):
                ids.append(name[:-5])
        ids.sort()
        return ids


# ---------------------------------------------------------------------------
# Self-check: round-trip the dataclasses when run as a script
# ---------------------------------------------------------------------------

def _self_check() -> None:
    """Sanity-check that the dataclasses round-trip cleanly through JSON."""
    dossier = StoryDossier(
        story_id="20260408-senate-approps",
        headline_seed="Senate passes appropriations bill",
        detected_at="2026-04-08T19:30:00+00:00",
        articles=[
            ArticleRecord(
                outlet="Reuters",
                url="https://reuters.com/x",
                title="Senate passes $1.2T bill 68-32",
                body="The Senate voted 68-32 tonight ...",
                fetched_at="2026-04-08T19:35:00+00:00",
                is_wire_derived=False,
            ),
            ArticleRecord(
                outlet="Associated Press",
                url="https://apnews.com/y",
                title="Senate passes appropriations 68-32",
                body="The Senate on Wednesday ...",
                fetched_at="2026-04-08T19:36:00+00:00",
                is_wire_derived=False,
            ),
        ],
        primary_sources=[
            PrimarySource(
                kind="congress_vote",
                url="https://www.senate.gov/legislative/LIS/roll_call_lists/roll_call_vote_cfm.cfm?vote=312",
                title="Senate roll call vote 312",
                excerpt="On passage of the bill (H.R. 4821), yeas 68, nays 32",
            ),
        ],
        outlet_slants={"Reuters": "wire", "Associated Press": "wire"},
    )

    brief = MetaAnalysisBrief(
        story_id="20260408-senate-approps",
        consensus_facts=["Senate voted 68-32", "Midnight passage", "$1.2T topline"],
        disagreements=[
            Disagreement(
                topic="attribution of bipartisan framing",
                positions={
                    "The New York Times": "rare bipartisan moment",
                    "Fox News": "eight GOP defectors drove the outcome",
                },
            )
        ],
        framing_analysis={
            "Reuters": "leads on the math",
            "Fox News": "leads on the dissent bloc",
        },
        primary_source_alignment=[
            "Roll call confirms 68-32; both outlets reported the vote count correctly.",
        ],
        missing_context=[
            "$14B disaster supplement in Title VII not mentioned by either outlet",
        ],
        suggested_post_type=PostType.META,
        suggested_post_type_reason="Multi-outlet framing divergence with primary-source gap.",
        confidence=0.88,
    )

    draft = DraftPost(
        text="COVERAGE REPORT — Senate appropriations vote ...",
        post_type=PostType.META,
        sign_off=SIGN_OFFS[PostType.META],
        story_id="20260408-senate-approps",
        outlets_referenced=["Reuters", "Associated Press", "Fox News", "The New York Times"],
        primary_source_urls=[
            "https://www.senate.gov/legislative/LIS/roll_call_lists/roll_call_vote_cfm.cfm?vote=312"
        ],
        hedges_used=[],
    )

    # Round-trip through JSON strings
    for obj, cls in (
        (dossier, StoryDossier),
        (brief, MetaAnalysisBrief),
        (draft, DraftPost),
    ):
        encoded = json.dumps(obj.to_dict(), indent=2, default=str)
        decoded_dict = json.loads(encoded)
        roundtripped = cls.from_dict(decoded_dict)
        assert roundtripped.to_dict() == obj.to_dict(), (
            f"Round-trip mismatch for {cls.__name__}:\n"
            f"  before={obj.to_dict()}\n"
            f"  after ={roundtripped.to_dict()}"
        )

    # Also exercise the file store against a throwaway directory
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        store = DossierStore(root_dir=tmp)
        store.save_dossier(dossier)
        store.save_brief(brief)
        store.save_post_record(dossier.story_id, draft, post_url="https://x.com/WalterCroncat/status/1")

        loaded_dossier = store.load_dossier(dossier.story_id)
        loaded_brief = store.load_brief(brief.story_id)
        loaded_post = store.load_post_record(dossier.story_id)

        assert loaded_dossier is not None and loaded_dossier.to_dict() == dossier.to_dict()
        assert loaded_brief is not None and loaded_brief.to_dict() == brief.to_dict()
        assert loaded_post is not None and loaded_post["draft"] == draft.to_dict()
        assert store.list_dossiers() == [DossierStore._safe_story_id(dossier.story_id)]

    print("dossier_store self-check OK")


if __name__ == "__main__":
    _self_check()
