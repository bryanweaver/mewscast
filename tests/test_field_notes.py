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
    condense_facts_for_notebook,
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

    def test_n_zero_returns_empty(self):
        # Caller asked for nothing — return nothing, regardless of how
        # many facts the brief carries. Matches the contract for empty /
        # missing inputs.
        brief = {
            "consensus_facts": [
                "Fact one here is long enough.",
                "Fact two here is long enough.",
                "Fact three here is long enough.",
            ]
        }
        assert extract_top_facts(brief, n=0) == []

    def test_n_negative_returns_empty(self):
        # Negative n is nonsense — treat it like n=0 rather than letting
        # the internal loop quietly return whatever it had accumulated.
        brief = {
            "consensus_facts": [
                "Fact one here is long enough.",
                "Fact two here is long enough.",
                "Fact three here is long enough.",
            ]
        }
        assert extract_top_facts(brief, n=-1) == []
        assert extract_top_facts(brief, n=-100) == []

    def test_non_positive_n_consistent_with_empty_brief(self):
        # Non-positive n should behave the same as None / empty inputs.
        assert extract_top_facts(None, n=0) == []
        assert extract_top_facts({}, n=-1) == []
        assert extract_top_facts({"consensus_facts": []}, n=0) == []


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
        # A fact with internal double-quotes must not break the prompt
        # structure. We swap to single quotes; the quoted-speech intent
        # survives, and Grok no longer transcribes literal double quotes
        # into the image (which had been producing unterminated marks).
        fact_with_dq = 'Wahl called the actions "heroic" in his briefing.'
        facts = [fact_with_dq, "Second fact here is long.", "Third fact here is long."]
        prompt = gen._build_field_notes_prompt(facts, headline="X")
        # Double quotes inside the fact should be swapped for single quotes.
        assert '"heroic"' not in prompt
        assert "'heroic'" in prompt
        # Entries are dash-prefixed and numbered, with no surrounding
        # quotation marks around the fact text itself.
        assert "- 1. " in prompt

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

    def test_no_quote_wrappers_around_facts(self, gen):
        # Regression: earlier prompts wrapped each fact in literal double
        # quotes (1. "fact text") which Grok transcribed into the image,
        # producing mismatched / unterminated quotation marks. Facts must
        # now appear bare in the prompt — no surrounding " " around the
        # text or its numbering.
        facts = [
            "First long fact for testing.",
            "Second long fact for testing.",
            "Third long fact for testing.",
        ]
        prompt = gen._build_field_notes_prompt(facts, headline="X")
        for fact in facts:
            quoted = '"' + fact + '"'
            assert quoted not in prompt, (
                f"Fact should not be wrapped in double quotes: {quoted!r}"
            )

    def test_no_quote_wrappers_around_headline_or_dateline(self, gen):
        facts = ["A long enough fact.", "B long enough fact.", "C long enough fact."]
        prompt = gen._build_field_notes_prompt(
            facts, headline="My Story Title", dateline="May 21, 2026",
        )
        assert '"My Story Title"' not in prompt
        assert '"May 21, 2026"' not in prompt
        # The values themselves are still present in the prompt as text.
        assert "My Story Title" in prompt
        assert "May 21, 2026" in prompt

    def test_default_aspect_ratio_is_3_2(self):
        # Switched from 3:4 to 3:2 on 2026-05-21 because the portrait image
        # wasn't rendering on X. Should remain 3:2 so the reply image fits
        # the same media slot as the main post image.
        from inspect import signature
        from image_generator import ImageGenerator
        sig = signature(ImageGenerator.generate_field_notes)
        assert sig.parameters["aspect_ratio"].default == "3:2"


# ---------------------------------------------------------------------------
# condense_facts_for_notebook
# ---------------------------------------------------------------------------


class TestCondenseFactsForNotebook:
    def test_empty_input_returns_empty(self):
        assert condense_facts_for_notebook([]) == []

    def test_no_api_key_returns_originals(self, monkeypatch):
        # When ANTHROPIC_API_KEY is missing the condenser must not raise;
        # it should fall through and return the input list unchanged so
        # the field-notes pipeline keeps working.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        facts = [
            "First original fact, fully formed and intact.",
            "Second original fact, fully formed and intact.",
        ]
        result = condense_facts_for_notebook(facts)
        assert result == facts

    def test_llm_failure_returns_originals(self, monkeypatch):
        # When the anthropic client raises (network, rate limit, auth) the
        # condenser must catch and return the originals — not propagate.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        class _Boom:
            def __init__(self, *_, **__):
                pass

            class messages:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("simulated network failure")

        import field_notes as fn_module
        import anthropic as _anthropic_module
        monkeypatch.setattr(_anthropic_module, "Anthropic", _Boom)
        # field_notes does `from anthropic import Anthropic` lazily inside
        # the function, so the swap above is enough.
        facts = ["Fact one stays intact.", "Fact two stays intact."]
        assert condense_facts_for_notebook(facts) == facts

    def test_returns_originals_on_wrong_shape(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        class _StubResp:
            class _Block:
                text = '["just one entry"]'  # wrong length vs 3 input facts
            content = [_Block()]

        class _StubClient:
            def __init__(self, *_, **__):
                pass

            class messages:
                @staticmethod
                def create(**_):
                    return _StubResp()

        import anthropic as _anthropic_module
        monkeypatch.setattr(_anthropic_module, "Anthropic", _StubClient)

        facts = ["A.", "B.", "C."]
        assert condense_facts_for_notebook(facts) == facts

    def test_returns_originals_on_invalid_json(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        class _StubResp:
            class _Block:
                text = "this is not json"
            content = [_Block()]

        class _StubClient:
            def __init__(self, *_, **__):
                pass

            class messages:
                @staticmethod
                def create(**_):
                    return _StubResp()

        import anthropic as _anthropic_module
        monkeypatch.setattr(_anthropic_module, "Anthropic", _StubClient)

        facts = ["A long enough fact.", "B long enough fact.", "C long enough fact."]
        assert condense_facts_for_notebook(facts) == facts

    def test_uses_condensed_when_short_enough(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        class _StubResp:
            class _Block:
                text = '["Short A", "Short B", "Short C"]'
            content = [_Block()]

        class _StubClient:
            def __init__(self, *_, **__):
                pass

            class messages:
                @staticmethod
                def create(**_):
                    return _StubResp()

        import anthropic as _anthropic_module
        monkeypatch.setattr(_anthropic_module, "Anthropic", _StubClient)

        facts = [
            "First original fact that's much longer than the condensed.",
            "Second original fact that's also much longer than the condensed.",
            "Third original fact that's also much longer than the condensed.",
        ]
        result = condense_facts_for_notebook(facts)
        assert result == ["Short A", "Short B", "Short C"]

    def test_falls_back_per_fact_if_over_budget(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        long_blob = "x" * 200
        stub_text = '["OK short bullet", "' + long_blob + '", "OK third bullet"]'

        class _StubResp:
            class _Block:
                text = stub_text
            content = [_Block()]

        class _StubClient:
            def __init__(self, *_, **__):
                pass

            class messages:
                @staticmethod
                def create(**_):
                    return _StubResp()

        import anthropic as _anthropic_module
        monkeypatch.setattr(_anthropic_module, "Anthropic", _StubClient)

        facts = [
            "First original fact, long.",
            "Second original fact, intentionally kept intact for fallback.",
            "Third original fact, also long.",
        ]
        result = condense_facts_for_notebook(facts, max_chars=90)
        # First was within budget — use the condensed version.
        assert result[0] == "OK short bullet"
        # Second exceeded budget — original is preserved.
        assert result[1] == facts[1]
        # Third was within budget — use the condensed version.
        assert result[2] == "OK third bullet"
