"""
Unit tests for src/field_notes.py — consensus-facts extractor used to
build Walter's Field Notes Bluesky reply images.

Covers:
  - strip_attribution_tail handles em-dash, en-dash, and ASCII variants
  - strip_attribution_tail leaves clean facts untouched
  - strip_attribution_tail doesn't break facts with internal hyphens
  - extract_top_facts returns first N cleaned facts
  - extract_top_facts returns [] when too few usable facts exist
  - extract_top_facts handles None / empty / malformed input
  - Real-world fact strings from dossiers round-trip correctly

Also covers the prompt-assembly half:
  - ImageGenerator._build_field_notes_prompt embeds each fact verbatim
  - The prompt contains the "render exactly as written" guardrail
  - All three numbered entries appear in the assembled prompt
"""
import os
import sys
from unittest.mock import patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, _SRC_DIR)

from field_notes import (  # noqa: E402
    extract_top_facts,
    strip_attribution_tail,
)


# ---------------------------------------------------------------------------
# strip_attribution_tail
# ---------------------------------------------------------------------------

class TestStripAttributionTail:
    def test_em_dash_reported_by(self):
        fact = (
            "Russian President Vladimir Putin stated on May 9, 2026, that he "
            "believes the war is coming to an end \u2014 reported in body text "
            "by CNBC and NPR, and headlined by Reuters."
        )
        result = strip_attribution_tail(fact)
        assert result.endswith("coming to an end.")
        assert "CNBC" not in result
        assert "NPR" not in result

    def test_em_dash_confirmed_by(self):
        fact = "Three killed in the attack \u2014 confirmed by both CNBC and NPR."
        result = strip_attribution_tail(fact)
        assert result == "Three killed in the attack."

    def test_em_dash_stated_by(self):
        fact = "The war began in February 2022 \u2014 stated by both CNBC and NPR."
        result = strip_attribution_tail(fact)
        assert result == "The war began in February 2022."

    def test_em_dash_referenced_by(self):
        fact = "May 9 is Russia's Victory Day \u2014 referenced in body text by CNBC."
        result = strip_attribution_tail(fact)
        assert result == "May 9 is Russia's Victory Day."

    def test_ascii_double_dash(self):
        fact = "Three killed in the attack -- confirmed by NPR."
        result = strip_attribution_tail(fact)
        assert result == "Three killed in the attack."

    def test_ascii_single_dash(self):
        fact = "Three killed in the attack - confirmed by NPR."
        result = strip_attribution_tail(fact)
        assert result == "Three killed in the attack."

    def test_en_dash(self):
        fact = "Three killed in the attack \u2013 confirmed by NPR."
        result = strip_attribution_tail(fact)
        assert result == "Three killed in the attack."

    def test_no_tail_unchanged(self):
        fact = "Two teenage gunmen opened fire at the Islamic Center of San Diego."
        result = strip_attribution_tail(fact)
        assert result == "Two teenage gunmen opened fire at the Islamic Center of San Diego."

    def test_internal_hyphens_preserved(self):
        # "self-inflicted" must survive — it's a hyphenated word, not a tail.
        fact = (
            "Two teenage gunmen opened fire at the Islamic Center of San Diego, "
            "killing three men before dying of self-inflicted gunshot wounds."
        )
        result = strip_attribution_tail(fact)
        assert "self-inflicted" in result
        assert result.endswith("gunshot wounds.")

    def test_empty_string(self):
        assert strip_attribution_tail("") == ""

    def test_period_added_when_missing(self):
        fact = "Three killed in the attack \u2014 confirmed by NPR"
        result = strip_attribution_tail(fact)
        assert result.endswith(".")

    def test_existing_punct_not_doubled(self):
        fact = "Was it really three? \u2014 confirmed by NPR"
        result = strip_attribution_tail(fact)
        assert result == "Was it really three?"

    def test_dash_inside_word_not_matched(self):
        # No whitespace before/after the hyphen — must not strip.
        fact = "The ex-president was indicted."
        result = strip_attribution_tail(fact)
        assert result == "The ex-president was indicted."


# ---------------------------------------------------------------------------
# extract_top_facts
# ---------------------------------------------------------------------------

class TestExtractTopFacts:
    def test_first_three_returned(self):
        brief = {
            "consensus_facts": [
                "Fact one is here, long enough.",
                "Fact two is also here, long enough.",
                "Fact three goes last, long enough.",
                "Fact four should not appear.",
            ]
        }
        result = extract_top_facts(brief, n=3)
        assert len(result) == 3
        assert "Fact one" in result[0]
        assert "Fact three" in result[2]
        assert all("four" not in f for f in result)

    def test_strips_attribution_tails(self):
        brief = {
            "consensus_facts": [
                "Putin said the war is ending \u2014 reported by CNBC and NPR.",
                "Three killed in the attack \u2014 confirmed by CNBC.",
                "Suspects were 17 and 18 \u2014 reported by NPR.",
            ]
        }
        result = extract_top_facts(brief, n=3)
        assert len(result) == 3
        assert all("CNBC" not in f and "NPR" not in f for f in result)

    def test_too_few_facts_returns_empty(self):
        brief = {
            "consensus_facts": [
                "Only one fact here, long enough to be valid.",
                "Only two facts total here.",
            ]
        }
        result = extract_top_facts(brief, n=3)
        assert result == []

    def test_none_brief(self):
        assert extract_top_facts(None, n=3) == []

    def test_empty_dict(self):
        assert extract_top_facts({}, n=3) == []

    def test_missing_consensus_facts_key(self):
        assert extract_top_facts({"other_key": "value"}, n=3) == []

    def test_non_string_facts_skipped(self):
        brief = {
            "consensus_facts": [
                "First valid fact, long enough.",
                123,
                "Second valid fact, long enough.",
                None,
                "Third valid fact, long enough.",
            ]
        }
        result = extract_top_facts(brief, n=3)
        assert len(result) == 3
        assert all(isinstance(f, str) for f in result)

    def test_too_short_facts_filtered(self):
        # Default min_chars=20 should filter out the "short" entries.
        brief = {
            "consensus_facts": [
                "Short.",
                "Also short.",
                "First long enough fact here, definitely valid.",
                "Second long enough fact here, definitely valid.",
                "Third long enough fact here, definitely valid.",
            ]
        }
        result = extract_top_facts(brief, n=3)
        assert len(result) == 3
        assert all(len(f) >= 20 for f in result)
        assert all("Short" not in f and "Also short" not in f for f in result)

    def test_n_parameter(self):
        brief = {
            "consensus_facts": [
                "Fact one here is long enough.",
                "Fact two here is long enough.",
                "Fact three here is long enough.",
                "Fact four here is long enough.",
                "Fact five here is long enough.",
            ]
        }
        result = extract_top_facts(brief, n=5)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# ImageGenerator._build_field_notes_prompt
# ---------------------------------------------------------------------------

class TestBuildFieldNotesPrompt:
    @pytest.fixture
    def gen(self):
        """Construct an ImageGenerator without hitting xAI auth."""
        from image_generator import ImageGenerator
        with patch.dict(os.environ, {"X_AI_API_KEY": "test-key"}):
            return ImageGenerator()

    def test_facts_appear_verbatim(self, gen):
        facts = [
            "Two teenage gunmen opened fire at the Islamic Center of San Diego.",
            "Chief Wahl is investigating it as a hate crime.",
            "Suspects were 17 and 18, found dead in a vehicle nearby.",
        ]
        prompt = gen._build_field_notes_prompt(facts, headline="San Diego Mosque Shooting")
        for fact in facts:
            assert fact in prompt, f"Fact missing from prompt: {fact!r}"

    def test_numbered_entries(self, gen):
        facts = ["Fact A here.", "Fact B here.", "Fact C here."]
        prompt = gen._build_field_notes_prompt(facts, headline="X")
        assert "1." in prompt
        assert "2." in prompt
        assert "3." in prompt

    def test_render_exactly_guardrail(self, gen):
        facts = ["Single fact for guardrail check."]
        prompt = gen._build_field_notes_prompt(facts, headline="")
        assert "EXACTLY" in prompt
        assert "do not paraphrase" in prompt.lower()

    def test_field_notes_header_present(self, gen):
        facts = ["A.", "B.", "C."]
        prompt = gen._build_field_notes_prompt(facts, headline="X")
        assert "FIELD NOTES" in prompt

    def test_walter_signature_present(self, gen):
        facts = ["A.", "B.", "C."]
        prompt = gen._build_field_notes_prompt(facts, headline="X")
        assert "Walter" in prompt
        assert "paw" in prompt.lower()

    def test_dateline_inlined_when_provided(self, gen):
        facts = ["A.", "B.", "C."]
        prompt = gen._build_field_notes_prompt(facts, headline="X", dateline="May 19, 2026")
        assert "May 19, 2026" in prompt

    def test_dateline_omitted_when_none(self, gen):
        facts = ["A.", "B.", "C."]
        prompt = gen._build_field_notes_prompt(facts, headline="X", dateline=None)
        # If we passed no dateline, the dateline line shouldn't appear
        assert "dateline reads" not in prompt

    def test_headline_omitted_when_empty(self, gen):
        facts = ["A.", "B.", "C."]
        prompt = gen._build_field_notes_prompt(facts, headline="")
        # No subtitle line when headline is empty.
        assert "subtitle that reads" not in prompt

    def test_double_quotes_sanitized(self, gen):
        # A fact with internal double-quotes must not break the prompt's
        # "..." literal wrappers. We swap to single quotes; the wrapping
        # is recognizable but the quoted-speech intent survives.
        fact_with_dq = 'Wahl called the actions "heroic" in his briefing.'
        facts = [fact_with_dq, "Second fact here is long.", "Third fact here is long."]
        prompt = gen._build_field_notes_prompt(facts, headline="X")
        # Double quotes inside the fact should be swapped for single quotes.
        assert '"heroic"' not in prompt
        assert "'heroic'" in prompt
        # The outer wrappers around the fact remain intact — every embedded
        # fact line begins with `N. "` and ends with `"`.
        assert '1. "' in prompt

    def test_newlines_in_facts_collapsed(self, gen):
        # A fact containing a stray newline (e.g. from a paste) must
        # become a one-liner so the entry block stays well-formed.
        fact_with_newline = "First line\nsecond line of the same fact."
        facts = [fact_with_newline, "Second long enough fact.", "Third long enough fact."]
        prompt = gen._build_field_notes_prompt(facts, headline="X")
        # The newline inside the fact text should not appear; only the
        # structural newlines added by the prompt template should.
        # Check the fact survived as a single line by looking for the
        # collapsed form.
        assert "First line second line" in prompt
        # And the original two-line form should not appear in the entry.
        assert "First line\nsecond line" not in prompt

    def test_headline_newlines_collapsed(self, gen):
        facts = ["A long enough fact for testing.", "B long enough fact.", "C long enough fact."]
        prompt = gen._build_field_notes_prompt(
            facts, headline="Story\nName with newline"
        )
        assert "Story Name with newline" in prompt

    def test_entry_count_matches_facts_length_three(self, gen):
        facts = ["First fact here.", "Second fact here.", "Third fact here."]
        prompt = gen._build_field_notes_prompt(facts, headline="X")
        # The prompt should state the entry count explicitly. With 3 facts,
        # the count line reads "3 numbered entries follow".
        assert "3 numbered entries follow" in prompt
        assert "2 numbered entries follow" not in prompt
        assert "4 numbered entries follow" not in prompt

    def test_entry_count_matches_facts_length_two(self, gen):
        facts = ["First fact here.", "Second fact here."]
        prompt = gen._build_field_notes_prompt(facts, headline="X")
        assert "2 numbered entries follow" in prompt
        assert "3 numbered entries follow" not in prompt

    def test_entry_count_matches_facts_length_five(self, gen):
        facts = [
            "First fact here.",
            "Second fact here.",
            "Third fact here.",
            "Fourth fact here.",
            "Fifth fact here.",
        ]
        prompt = gen._build_field_notes_prompt(facts, headline="X")
        assert "5 numbered entries follow" in prompt
