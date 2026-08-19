"""Tests for x_mention_reply — pure-function helpers.

The full flow (fetch + reply) is exercised via --dry-run on the GHA workflow;
unit tests here cover the deterministic pieces:
  - bait detection
  - question detection
  - reply validation (no hashtags, no sign-off, no dunks)
  - meme prompt composition
  - Cronkite reply composition
  - dedup helpers
"""
from __future__ import annotations

import os
import sys

import pytest

# Allow import of src modules without installing the project.
_here = os.path.dirname(os.path.abspath(__file__))
_src = os.path.join(os.path.dirname(_here), "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from x_mention_reply import (  # noqa: E402
    is_bait,
    is_serious_question,
    compose_meme_caption,
    compose_meme_prompt,
    compose_cronkite_reply,
    has_hashtags,
    has_sign_off,
    validate_reply_text,
    has_replied_to_user,
    has_memed_in_thread,
    get_meme_for_thread,
    has_dossier_replied_in_thread,
)


class TestIsBait:
    """Tests for bait detection."""

    def test_slop_is_bait(self):
        assert is_bait("slop") is True
        assert is_bait("Slop") is True
        assert is_bait("SLOP") is True
        assert is_bait("slop.") is True
        assert is_bait("  slop  ") is True

    def test_lol_is_bait(self):
        assert is_bait("lol") is True
        assert is_bait("LOL") is True
        assert is_bait("lmao") is True

    def test_one_word_dunks_are_bait(self):
        assert is_bait("ratio") is True
        assert is_bait("mid") is True
        assert is_bait("cope") is True
        assert is_bait("fake") is True
        assert is_bait("bot") is True
        assert is_bait("trash") is True
        assert is_bait("cringe") is True

    def test_emoji_only_is_bait(self):
        assert is_bait("💩") is True
        assert is_bait("🗑️") is True
        assert is_bait("💀") is True
        assert is_bait("😂") is True

    def test_empty_is_bait(self):
        assert is_bait("") is True
        assert is_bait("   ") is True
        assert is_bait(None) is True

    def test_real_question_is_not_bait(self):
        assert is_bait("What's the source for this?") is False
        assert is_bait("Can you explain more?") is False

    def test_real_comment_is_not_bait(self):
        assert is_bait("This is interesting analysis") is False
        assert is_bait("I disagree with the framing here") is False


class TestIsSeriousQuestion:
    """Tests for serious question detection."""

    def test_question_mark_detected(self):
        assert is_serious_question("What's the source?") is True
        assert is_serious_question("How do you know this?") is True
        assert is_serious_question("Where did this happen?") is True

    def test_question_words_detected(self):
        assert is_serious_question("Can you explain this") is True
        assert is_serious_question("Could you provide evidence") is True
        assert is_serious_question("What evidence is there") is True

    def test_source_request_detected(self):
        assert is_serious_question("Source please") is True
        assert is_serious_question("Link to the article") is True
        assert is_serious_question("Citation needed") is True

    def test_bait_is_not_serious(self):
        assert is_serious_question("slop") is False
        assert is_serious_question("lol") is False
        assert is_serious_question("") is False

    def test_statement_not_question(self):
        assert is_serious_question("This is wrong") is False
        assert is_serious_question("I disagree") is False


class TestComposeMemeCaption:
    """Tests for meme caption composition."""

    def test_caption_is_minimal(self):
        caption = compose_meme_caption("slop")
        assert len(caption) <= 10  # Almost no caption

    def test_caption_has_no_hashtags(self):
        caption = compose_meme_caption("slop")
        assert "#" not in caption


class TestComposeMemePrompt:
    """Tests for meme prompt composition."""

    def test_prompt_mentions_cat(self):
        prompt = compose_meme_prompt("slop")
        assert "cat" in prompt.lower()

    def test_prompt_mentions_indignant(self):
        prompt = compose_meme_prompt("slop")
        assert "indignant" in prompt.lower() or "outrage" in prompt.lower()

    def test_prompt_no_text_overlays(self):
        prompt = compose_meme_prompt("slop")
        assert "no text" in prompt.lower()


class TestComposeCronkiteReply:
    """Tests for Cronkite reply composition."""

    def test_empty_dossier_returns_none(self):
        assert compose_cronkite_reply("What happened?", {}) is None
        assert compose_cronkite_reply("What happened?", None) is None

    def test_reply_includes_facts(self):
        dossier = {
            "brief": {
                "consensus_facts": [
                    "The event occurred on Tuesday",
                    "Three people were involved",
                ]
            },
            "dossier": {
                "headline_seed": "Major Event Unfolds",
                "articles": [{"outlet": "AP"}, {"outlet": "Reuters"}],
            },
        }
        reply = compose_cronkite_reply("What happened?", dossier)
        assert reply is not None
        assert "Tuesday" in reply or "three" in reply.lower()

    def test_reply_mentions_outlet_count(self):
        dossier = {
            "brief": {"consensus_facts": ["Fact one"]},
            "dossier": {
                "headline_seed": "Story",
                "articles": [{"outlet": "A"}, {"outlet": "B"}, {"outlet": "C"}],
            },
        }
        reply = compose_cronkite_reply("What's the source?", dossier)
        assert reply is not None
        assert "3 outlets" in reply

    def test_reply_fits_280_chars(self):
        dossier = {
            "brief": {
                "consensus_facts": [
                    "This is a very long fact that goes on and on",
                    "Another long fact with lots of detail",
                    "Yet another fact for good measure",
                ]
            },
            "dossier": {
                "headline_seed": "A very long headline about something important",
                "articles": [{"outlet": o} for o in "ABCDEFG"],
            },
        }
        reply = compose_cronkite_reply("What happened?", dossier)
        assert reply is not None
        assert len(reply) <= 280


class TestHasHashtags:
    """Tests for hashtag detection."""

    def test_detects_hashtags(self):
        assert has_hashtags("#BreakingMews") is True
        assert has_hashtags("Check this out #news") is True
        assert has_hashtags("#one #two") is True

    def test_no_hashtags(self):
        assert has_hashtags("No hashtags here") is False
        assert has_hashtags("Just a # by itself") is False
        assert has_hashtags("") is False


class TestHasSignOff:
    """Tests for sign-off detection."""

    def test_detects_walter_signoff(self):
        assert has_sign_off("— Walter") is True
        assert has_sign_off("- Walter") is True
        assert has_sign_off("Walter Croncat") is True

    def test_detects_emoji_signoff(self):
        assert has_sign_off("Great story 🐱") is True
        assert has_sign_off("Breaking 🐾") is True
        assert has_sign_off("News 📰") is True

    def test_detects_cat_puns(self):
        assert has_sign_off("This is purrfect") is True
        assert has_sign_off("Meow about that") is True

    def test_no_signoff(self):
        assert has_sign_off("Just the facts") is False
        assert has_sign_off("Three outlets confirm this") is False


class TestValidateReplyText:
    """Tests for reply text validation."""

    def test_valid_reply_passes(self):
        is_valid, reason = validate_reply_text("Three outlets confirm the event occurred Tuesday.")
        assert is_valid is True
        assert reason == "ok"

    def test_empty_fails(self):
        is_valid, reason = validate_reply_text("")
        assert is_valid is False
        assert "empty" in reason

    def test_hashtag_fails(self):
        is_valid, reason = validate_reply_text("Check this out #BreakingMews")
        assert is_valid is False
        assert "hashtag" in reason

    def test_signoff_fails(self):
        is_valid, reason = validate_reply_text("Great story — Walter")
        assert is_valid is False
        assert "sign-off" in reason

    def test_dunk_language_fails(self):
        is_valid, reason = validate_reply_text("You just got owned")
        assert is_valid is False
        assert "dunk" in reason


class TestDedupHelpers:
    """Tests for deduplication helpers."""

    def test_has_replied_to_user(self):
        history = {
            "replies": [
                {"author_id": "123", "reply_type": "meme"},
                {"author_id": "456", "reply_type": "cronkite"},
            ]
        }
        assert has_replied_to_user(history, "123") is True
        assert has_replied_to_user(history, "456") is True
        assert has_replied_to_user(history, "789") is False

    def test_has_replied_excludes_dossier_followup(self):
        history = {
            "replies": [
                {"author_id": "123", "reply_type": "dossier_followup"},
            ]
        }
        # dossier_followup doesn't count as first-touch
        assert has_replied_to_user(history, "123") is False

    def test_has_memed_in_thread(self):
        history = {
            "memes_by_thread": {
                "conv_123": "/path/to/meme.png",
            }
        }
        assert has_memed_in_thread(history, "conv_123") is True
        assert has_memed_in_thread(history, "conv_456") is False

    def test_get_meme_for_thread(self):
        history = {
            "memes_by_thread": {
                "conv_123": "/path/to/meme.png",
            }
        }
        assert get_meme_for_thread(history, "conv_123") == "/path/to/meme.png"
        assert get_meme_for_thread(history, "conv_456") is None

    def test_has_dossier_replied_in_thread(self):
        history = {
            "replies": [
                {
                    "author_id": "123",
                    "conversation_id": "conv_abc",
                    "reply_type": "dossier_followup",
                },
            ]
        }
        assert has_dossier_replied_in_thread(history, "conv_abc", "123") is True
        assert has_dossier_replied_in_thread(history, "conv_abc", "456") is False
        assert has_dossier_replied_in_thread(history, "conv_xyz", "123") is False


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_bait_with_punctuation(self):
        assert is_bait("slop!!!") is True
        assert is_bait("LOL???") is True
        assert is_bait("ok.") is True

    def test_bait_with_whitespace(self):
        assert is_bait("  slop  ") is True
        assert is_bait("\n\nslop\n\n") is True
        assert is_bait("\tslop\t") is True

    def test_mixed_case_bait(self):
        assert is_bait("SLoP") is True
        assert is_bait("lOl") is True

    def test_question_in_statement(self):
        # "what" alone doesn't make it a question if context is bait-like
        assert is_serious_question("what") is True  # Contains question word
        assert is_bait("what") is False  # Not in bait list

    def test_empty_history(self):
        assert has_replied_to_user({}, "123") is False
        assert has_memed_in_thread({}, "conv") is False
        assert get_meme_for_thread({}, "conv") is None
        assert has_dossier_replied_in_thread({}, "conv", "123") is False
