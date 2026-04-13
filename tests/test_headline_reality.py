#!/usr/bin/env python3
"""
Tests for the Headline vs Reality CLI feature (src/headline_reality_post.py).

Covers:
- URL mode with mocked Jina response
- Paste mode
- Dry run (post not published)
- Mismatch analysis — real gap detected
- Accurate headline — no post generated
- Character limit enforcement (Bluesky and X)
- Fallback chain: Jina → trafilatura → BeautifulSoup → failed
"""
import json
import os
import sys
from unittest.mock import MagicMock, Mock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — same convention as other tests in this repo
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
)

from src.headline_reality_post import (
    BLUESKY_LIMIT,
    TARGET_LIMIT,
    X_LIMIT,
    HeadlineRealityChecker,
    get_paste_input,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SAMPLE_HEADLINE = "Trump Announces Historic Peace Deal for Ukraine"

SAMPLE_ARTICLE_MISMATCH = (
    "Trump Announces Plan for Ukraine. "
    "President Trump announced his own peace framework for Ukraine on Monday, "
    "a proposal drafted by his transition team. Ukrainian officials said they "
    "had not been briefed on the full plan. Russian officials declined to comment. "
    "No deal has been signed. The proposal is described as 'preliminary' and "
    "'a starting point for discussion' according to sources familiar with the matter. "
    "Both parties would need to agree before any framework could be called a deal. " * 5
)

SAMPLE_ARTICLE_ACCURATE = (
    "Trump Announces Historic Peace Deal for Ukraine. "
    "President Trump announced a landmark peace agreement on Monday after months "
    "of negotiations. Both Ukrainian President Zelensky and Russian President Putin "
    "signed the accord in Vienna. The historic deal ends two years of conflict and "
    "has been praised by NATO allies. UN Secretary-General called it an unprecedented "
    "diplomatic achievement. " * 5
)

ANALYSIS_MISMATCH = {
    "has_mismatch": True,
    "headline_claims": "Trump has finalized a historic, signed peace deal for Ukraine.",
    "article_actually_says": (
        "- No deal has been signed\n"
        "- Ukraine officials were not briefed on the plan\n"
        "- The proposal is described as 'preliminary'\n"
        "- Both parties still need to agree"
    ),
    "mismatch_description": (
        "The headline calls it a 'deal' but the article describes "
        "an unsigned proposal with no agreement from either party."
    ),
    "severity": "major",
}

ANALYSIS_ACCURATE = {
    "has_mismatch": False,
    "headline_claims": "Trump announced a historic, signed peace deal for Ukraine.",
    "article_actually_says": "Both leaders signed the accord in Vienna; widely praised.",
    "mismatch_description": None,
    "severity": None,
}

SAMPLE_POST = (
    "🚨 HEADLINE vs REALITY\n\n"
    '📰 Headline: "Trump Announces Historic Peace Deal for Ukraine"\n\n'
    "📖 What the article ACTUALLY says:\n"
    "- No deal signed\n"
    "- Ukraine not briefed on the plan\n"
    "- Called 'preliminary'\n\n"
    "🐱 Announcing your proposal as a done deal is... a choice.\n\n"
    "This cat reads past paragraph one. 📰↓"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def checker():
    """HeadlineRealityChecker with mocked Anthropic client."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("src.headline_reality_post.Anthropic"):
            c = HeadlineRealityChecker()
            c.client = Mock()
            return c


def _make_claude_response(data):
    """Build a minimal Anthropic response mock returning JSON."""
    msg = Mock()
    msg.content = [Mock(text=json.dumps(data))]
    return msg


def _make_claude_text_response(text):
    """Build a minimal Anthropic response mock returning raw text."""
    msg = Mock()
    msg.content = [Mock(text=text)]
    return msg


# ===========================================================================
# Jina Reader API
# ===========================================================================

class TestFetchViaJina:
    def test_returns_content_on_success(self, checker):
        body = "# Article Headline\n\nFull content here. " * 20
        mock_resp = Mock(text=body)
        mock_resp.raise_for_status = Mock()

        with patch("src.headline_reality_post.requests.get", return_value=mock_resp) as mock_get:
            result = checker.fetch_via_jina("https://example.com/article")

        assert result is not None
        assert "Article Headline" in result

        # Verify Jina URL is constructed correctly
        called_url = mock_get.call_args[0][0]
        assert called_url == "https://r.jina.ai/https://example.com/article"

    def test_returns_none_on_network_error(self, checker):
        with patch("src.headline_reality_post.requests.get", side_effect=Exception("timeout")):
            result = checker.fetch_via_jina("https://example.com/article")
        assert result is None

    def test_returns_none_when_content_too_short(self, checker):
        mock_resp = Mock(text="tiny")
        mock_resp.raise_for_status = Mock()
        with patch("src.headline_reality_post.requests.get", return_value=mock_resp):
            result = checker.fetch_via_jina("https://example.com/article")
        assert result is None

    def test_passes_markdown_accept_header(self, checker):
        body = "# Article\n\n" + "Content. " * 50
        mock_resp = Mock(text=body)
        mock_resp.raise_for_status = Mock()

        with patch("src.headline_reality_post.requests.get", return_value=mock_resp) as mock_get:
            checker.fetch_via_jina("https://example.com/article")

        headers = mock_get.call_args[1]["headers"]
        assert "markdown" in headers.get("Accept", "").lower()


# ===========================================================================
# trafilatura fallback
# ===========================================================================

class TestFetchViaTrafilatura:
    def test_returns_content_on_success(self, checker):
        long_text = "Article content paragraph. " * 50

        with patch("src.headline_reality_post.trafilatura") as mock_tf:
            mock_tf.fetch_url.return_value = "<html><body>...</body></html>"
            mock_tf.extract.return_value = long_text

            result = checker.fetch_via_trafilatura("https://example.com/article")

        assert result is not None
        assert "Article content" in result

    def test_returns_none_when_download_fails(self, checker):
        with patch("src.headline_reality_post.trafilatura") as mock_tf:
            mock_tf.fetch_url.return_value = None
            result = checker.fetch_via_trafilatura("https://example.com/article")
        assert result is None

    def test_returns_none_when_extract_returns_empty(self, checker):
        with patch("src.headline_reality_post.trafilatura") as mock_tf:
            mock_tf.fetch_url.return_value = "<html>...</html>"
            mock_tf.extract.return_value = ""
            result = checker.fetch_via_trafilatura("https://example.com/article")
        assert result is None

    def test_returns_none_when_not_installed(self, checker):
        with patch.dict("sys.modules", {"trafilatura": None}):
            # ImportError should be caught gracefully
            result = checker.fetch_via_trafilatura("https://example.com/article")
        assert result is None


# ===========================================================================
# BeautifulSoup fallback
# ===========================================================================

class TestFetchViaBeautifulSoup:
    def _mock_response(self, html):
        mock_resp = Mock()
        mock_resp.content = html.encode("utf-8")
        mock_resp.raise_for_status = Mock()
        return mock_resp

    def test_returns_content_from_article_element(self, checker):
        html = (
            "<html><body><article>"
            "<p>First paragraph of the article with enough text.</p>"
            "<p>Second paragraph with more detailed information here.</p>"
            "<p>Third paragraph continues the story with further context.</p>"
            "</article></body></html>"
        )
        with patch("src.headline_reality_post.requests.get",
                   return_value=self._mock_response(html)):
            result = checker.fetch_via_beautifulsoup("https://example.com/article")

        assert result is not None
        assert "First paragraph" in result

    def test_falls_back_to_paragraphs_when_no_article_element(self, checker):
        paragraphs = "".join(
            f"<p>Paragraph {i} with enough text to pass the minimum length check.</p>"
            for i in range(10)
        )
        html = f"<html><body>{paragraphs}</body></html>"
        with patch("src.headline_reality_post.requests.get",
                   return_value=self._mock_response(html)):
            result = checker.fetch_via_beautifulsoup("https://example.com/article")

        assert result is not None

    def test_returns_none_on_network_error(self, checker):
        with patch("src.headline_reality_post.requests.get",
                   side_effect=Exception("connection refused")):
            result = checker.fetch_via_beautifulsoup("https://example.com/article")
        assert result is None

    def test_returns_none_when_content_too_short(self, checker):
        html = "<html><body><article><p>Too short.</p></article></body></html>"
        with patch("src.headline_reality_post.requests.get",
                   return_value=self._mock_response(html)):
            result = checker.fetch_via_beautifulsoup("https://example.com/article")
        assert result is None

    def test_applies_high_char_limit(self, checker):
        # Generate content well over 8000 chars
        long_para = "W" * 200
        paragraphs = "".join(f"<p>{long_para}</p>" for _ in range(60))
        html = f"<html><body><article>{paragraphs}</article></body></html>"

        with patch("src.headline_reality_post.requests.get",
                   return_value=self._mock_response(html)):
            result = checker.fetch_via_beautifulsoup("https://example.com/article")

        assert result is not None
        # Should be truncated at or below 8000 chars
        from src.headline_reality_post import BS_MAX_CHARS
        assert len(result) <= BS_MAX_CHARS


# ===========================================================================
# Fallback chain: Jina → trafilatura → BeautifulSoup → failed
# ===========================================================================

class TestFallbackChain:
    def test_uses_jina_first_when_successful(self, checker):
        jina_content = "Jina article content. " * 20
        checker.fetch_via_jina = Mock(return_value=jina_content)
        checker.fetch_via_trafilatura = Mock(return_value="trafilatura content " * 20)
        checker.fetch_via_beautifulsoup = Mock(return_value="bs content " * 20)

        content, method = checker.get_article_content("https://example.com/article")

        assert content == jina_content
        assert method == "jina"
        checker.fetch_via_jina.assert_called_once()
        checker.fetch_via_trafilatura.assert_not_called()
        checker.fetch_via_beautifulsoup.assert_not_called()

    def test_falls_back_to_trafilatura_when_jina_fails(self, checker):
        tf_content = "trafilatura article content. " * 20
        checker.fetch_via_jina = Mock(return_value=None)
        checker.fetch_via_trafilatura = Mock(return_value=tf_content)
        checker.fetch_via_beautifulsoup = Mock(return_value="bs content " * 20)

        content, method = checker.get_article_content("https://example.com/article")

        assert content == tf_content
        assert method == "trafilatura"
        checker.fetch_via_beautifulsoup.assert_not_called()

    def test_falls_back_to_beautifulsoup_when_jina_and_trafilatura_fail(self, checker):
        bs_content = "BeautifulSoup content. " * 20
        checker.fetch_via_jina = Mock(return_value=None)
        checker.fetch_via_trafilatura = Mock(return_value=None)
        checker.fetch_via_beautifulsoup = Mock(return_value=bs_content)

        content, method = checker.get_article_content("https://example.com/article")

        assert content == bs_content
        assert method == "beautifulsoup"

    def test_returns_failed_when_all_extractors_fail(self, checker):
        checker.fetch_via_jina = Mock(return_value=None)
        checker.fetch_via_trafilatura = Mock(return_value=None)
        checker.fetch_via_beautifulsoup = Mock(return_value=None)

        content, method = checker.get_article_content("https://example.com/article")

        assert content is None
        assert method == "failed"


# ===========================================================================
# Phase 1 — Mismatch analysis
# ===========================================================================

class TestAnalyzeMismatch:
    def test_detects_real_mismatch(self, checker):
        checker.client.messages.create = Mock(
            return_value=_make_claude_response(ANALYSIS_MISMATCH)
        )
        result = checker.analyze_mismatch(SAMPLE_HEADLINE, SAMPLE_ARTICLE_MISMATCH)

        assert result is not None
        assert result["has_mismatch"] is True
        assert result["severity"] == "major"
        assert result["mismatch_description"] is not None

    def test_identifies_accurate_headline(self, checker):
        checker.client.messages.create = Mock(
            return_value=_make_claude_response(ANALYSIS_ACCURATE)
        )
        result = checker.analyze_mismatch(SAMPLE_HEADLINE, SAMPLE_ARTICLE_ACCURATE)

        assert result is not None
        assert result["has_mismatch"] is False
        assert result["mismatch_description"] is None
        assert result["severity"] is None

    def test_strips_json_code_fence(self, checker):
        raw_with_fence = "```json\n" + json.dumps(ANALYSIS_MISMATCH) + "\n```"
        checker.client.messages.create = Mock(
            return_value=_make_claude_text_response(raw_with_fence)
        )
        result = checker.analyze_mismatch(SAMPLE_HEADLINE, SAMPLE_ARTICLE_MISMATCH)

        assert result is not None
        assert result["has_mismatch"] is True

    def test_strips_plain_code_fence(self, checker):
        raw_with_fence = "```\n" + json.dumps(ANALYSIS_MISMATCH) + "\n```"
        checker.client.messages.create = Mock(
            return_value=_make_claude_text_response(raw_with_fence)
        )
        result = checker.analyze_mismatch(SAMPLE_HEADLINE, SAMPLE_ARTICLE_MISMATCH)

        assert result is not None
        assert result["has_mismatch"] is True

    def test_returns_none_on_invalid_json(self, checker):
        checker.client.messages.create = Mock(
            return_value=_make_claude_text_response("This is not JSON at all.")
        )
        result = checker.analyze_mismatch(SAMPLE_HEADLINE, SAMPLE_ARTICLE_MISMATCH)
        assert result is None

    def test_returns_none_on_api_exception(self, checker):
        checker.client.messages.create = Mock(side_effect=Exception("API error"))
        result = checker.analyze_mismatch(SAMPLE_HEADLINE, SAMPLE_ARTICLE_MISMATCH)
        assert result is None


# ===========================================================================
# Phase 2 — Post generation
# ===========================================================================

class TestGeneratePost:
    def test_generates_post_with_expected_structure(self, checker):
        checker.client.messages.create = Mock(
            return_value=_make_claude_text_response(SAMPLE_POST)
        )
        result = checker.generate_post(SAMPLE_HEADLINE, ANALYSIS_MISMATCH)

        assert result is not None
        assert "HEADLINE vs REALITY" in result
        assert SAMPLE_HEADLINE in result

    def test_strips_surrounding_quotes(self, checker):
        quoted = f'"{SAMPLE_POST}"'
        checker.client.messages.create = Mock(
            return_value=_make_claude_text_response(quoted)
        )
        result = checker.generate_post(SAMPLE_HEADLINE, ANALYSIS_MISMATCH)
        assert result is not None
        assert not result.startswith('"')

    def test_enforces_target_character_limit(self, checker):
        # Claude returns something way over the limit
        long_post = "🚨 HEADLINE vs REALITY\n\n" + "x" * 400
        checker.client.messages.create = Mock(
            return_value=_make_claude_text_response(long_post)
        )
        result = checker.generate_post(SAMPLE_HEADLINE, ANALYSIS_MISMATCH)

        assert result is not None
        assert len(result) <= TARGET_LIMIT

    def test_target_limit_fits_x_constraint(self):
        # TARGET_LIMIT must be ≤ X_LIMIT so posts work on both platforms
        assert TARGET_LIMIT <= X_LIMIT

    def test_bluesky_limit_is_more_generous_than_x(self):
        assert BLUESKY_LIMIT >= X_LIMIT

    def test_does_not_truncate_posts_within_limit(self, checker):
        short_post = "🚨 SHORT POST\n\nThis cat reads past paragraph one. 📰↓"
        assert len(short_post) <= TARGET_LIMIT

        checker.client.messages.create = Mock(
            return_value=_make_claude_text_response(short_post)
        )
        result = checker.generate_post(SAMPLE_HEADLINE, ANALYSIS_MISMATCH)

        assert result == short_post

    def test_returns_none_on_api_exception(self, checker):
        checker.client.messages.create = Mock(side_effect=Exception("network error"))
        result = checker.generate_post(SAMPLE_HEADLINE, ANALYSIS_MISMATCH)
        assert result is None


# ===========================================================================
# Character limit constants
# ===========================================================================

class TestCharacterLimitConstants:
    def test_bluesky_limit_is_300(self):
        assert BLUESKY_LIMIT == 300

    def test_x_limit_is_280(self):
        assert X_LIMIT == 280

    def test_target_limit_satisfies_both_platforms(self):
        assert TARGET_LIMIT <= X_LIMIT
        assert TARGET_LIMIT <= BLUESKY_LIMIT


# ===========================================================================
# Paste mode
# ===========================================================================

class TestPasteMode:
    def test_returns_headline_and_article_text(self):
        inputs = iter([
            "Trump Announces Major Peace Deal",   # headline prompt
            "First paragraph of the article.",
            "Second paragraph with more information.",
            "",                                   # first blank line
            "",                                   # second blank line — signals end
        ])
        with patch("builtins.input", side_effect=lambda _="": next(inputs)):
            headline, article_text = get_paste_input()

        assert headline == "Trump Announces Major Peace Deal"
        assert "First paragraph" in article_text
        assert "Second paragraph" in article_text

    def test_exits_on_empty_headline(self):
        inputs = iter([""])  # empty headline → sys.exit(1)
        with patch("builtins.input", side_effect=lambda _="": next(inputs)):
            with pytest.raises(SystemExit) as exc_info:
                get_paste_input()
        assert exc_info.value.code == 1

    def test_exits_on_empty_article_text(self):
        # Headline provided, article text is empty (EOF immediately)
        inputs = iter(["Good Headline"])  # then EOF
        with patch("builtins.input", side_effect=lambda _="": next(inputs)):
            with patch("builtins.input", side_effect=["Good Headline", EOFError()]):
                with pytest.raises(SystemExit) as exc_info:
                    get_paste_input()
        assert exc_info.value.code == 1

    def test_eof_terminates_article_input(self):
        # EOFError (Ctrl-D) should end article input gracefully
        call_count = 0

        def mock_input(_=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "The Headline"
            raise EOFError

        with patch("builtins.input", side_effect=mock_input):
            with pytest.raises(SystemExit):
                # Article text will be empty after EOFError, causing sys.exit(1)
                get_paste_input()


# ===========================================================================
# Dry run — posting methods must not be called
# ===========================================================================

class TestDryRunBehavior:
    def test_post_to_bluesky_not_called_in_dry_run(self, checker):
        """
        Dry-run logic lives in main(). Here we verify that post_to_bluesky
        and post_to_x are completely independent from generate_post, so
        callers (main()) can choose not to invoke them.
        """
        checker.client.messages.create = Mock(
            return_value=_make_claude_text_response(SAMPLE_POST)
        )
        # Generate post — this should NOT call any bot
        with patch("src.headline_reality_post.BlueskyBot") as mock_bsky:
            with patch("src.headline_reality_post.TwitterBot") as mock_x:
                post = checker.generate_post(SAMPLE_HEADLINE, ANALYSIS_MISMATCH)
                mock_bsky.assert_not_called()
                mock_x.assert_not_called()

        assert post is not None

    def test_post_to_bluesky_is_only_called_explicitly(self, checker):
        """post_to_bluesky must be called explicitly — it never auto-fires."""
        with patch("src.headline_reality_post.BlueskyBot") as mock_bsky_cls:
            mock_bot = Mock()
            mock_bot.post_skeet.return_value = {"uri": "at://did/post/1", "cid": "abc"}
            mock_bsky_cls.return_value = mock_bot

            # Only fires when we call it
            checker.post_to_bluesky(SAMPLE_POST, "https://example.com/article")
            mock_bsky_cls.assert_called_once()

    def test_post_to_x_is_only_called_explicitly(self, checker):
        """post_to_x must be called explicitly — it never auto-fires."""
        with patch("src.headline_reality_post.TwitterBot") as mock_x_cls:
            mock_bot = Mock()
            mock_bot.post_tweet.return_value = {"id": "1234567890"}
            mock_x_cls.return_value = mock_bot

            checker.post_to_x(SAMPLE_POST, "https://example.com/article")
            mock_x_cls.assert_called_once()


# ===========================================================================
# Platform posting — Bluesky
# ===========================================================================

class TestPostToBluesky:
    def test_posts_skeet_and_replies_with_source_url(self, checker):
        with patch("src.headline_reality_post.BlueskyBot") as mock_cls:
            mock_bot = Mock()
            mock_bot.post_skeet.return_value = {"uri": "at://did/post/abc", "cid": "cid123"}
            mock_cls.return_value = mock_bot

            result = checker.post_to_bluesky(SAMPLE_POST, "https://example.com/article")

        assert result is not None
        mock_bot.post_skeet.assert_called_once_with(SAMPLE_POST)
        mock_bot.reply_to_skeet_with_link.assert_called_once_with(
            "at://did/post/abc", "https://example.com/article"
        )

    def test_skips_source_reply_when_no_url(self, checker):
        with patch("src.headline_reality_post.BlueskyBot") as mock_cls:
            mock_bot = Mock()
            mock_bot.post_skeet.return_value = {"uri": "at://did/post/abc", "cid": "cid123"}
            mock_cls.return_value = mock_bot

            checker.post_to_bluesky(SAMPLE_POST, None)

        mock_bot.reply_to_skeet_with_link.assert_not_called()

    def test_returns_none_on_exception(self, checker):
        with patch("src.headline_reality_post.BlueskyBot", side_effect=Exception("auth fail")):
            result = checker.post_to_bluesky(SAMPLE_POST, None)
        assert result is None


# ===========================================================================
# Platform posting — X / Twitter
# ===========================================================================

class TestPostToX:
    def test_posts_tweet_and_replies_with_source_url(self, checker):
        with patch("src.headline_reality_post.TwitterBot") as mock_cls:
            mock_bot = Mock()
            mock_bot.post_tweet.return_value = {"id": "1234567890"}
            mock_cls.return_value = mock_bot

            result = checker.post_to_x(SAMPLE_POST, "https://example.com/article")

        assert result is not None
        mock_bot.post_tweet.assert_called_once()
        mock_bot.reply_to_tweet.assert_called_once_with("1234567890", "https://example.com/article")

    def test_trims_post_to_x_limit_before_posting(self, checker):
        # Generate a post that is over X_LIMIT but under BLUESKY_LIMIT
        over_x = "🚨 " + "x" * (X_LIMIT + 20)

        with patch("src.headline_reality_post.TwitterBot") as mock_cls:
            mock_bot = Mock()
            mock_bot.post_tweet.return_value = {"id": "999"}
            mock_cls.return_value = mock_bot

            checker.post_to_x(over_x, None)

        posted_text = mock_bot.post_tweet.call_args[0][0]
        assert len(posted_text) <= X_LIMIT

    def test_skips_source_reply_when_no_url(self, checker):
        with patch("src.headline_reality_post.TwitterBot") as mock_cls:
            mock_bot = Mock()
            mock_bot.post_tweet.return_value = {"id": "999"}
            mock_cls.return_value = mock_bot

            checker.post_to_x(SAMPLE_POST, None)

        mock_bot.reply_to_tweet.assert_not_called()

    def test_returns_none_on_exception(self, checker):
        with patch("src.headline_reality_post.TwitterBot", side_effect=Exception("rate limit")):
            result = checker.post_to_x(SAMPLE_POST, None)
        assert result is None
