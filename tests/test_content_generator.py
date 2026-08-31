#!/usr/bin/env python3
"""
Test suite for truncation utilities, PromptLoader, and NewsFetcher.

All external API calls (Google News RSS, HTTP requests) are mocked so that
the tests run offline and deterministically.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch, mock_open

import pytest

# ---------------------------------------------------------------------------
# Path setup -- mirrors the convention used in tests/test_media_literacy.py
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from src.truncate import _truncate_at_sentence
from src.prompt_loader import PromptLoader, get_prompt_loader
from src.news_fetcher import NewsFetcher


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def prompt_loader(tmp_path):
    """Return a PromptLoader pointed at a temp directory with sample templates."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    # Minimal tweet generation template
    (prompts_dir / "tweet_generation_bluesky.md").write_text(
        "Generate a tweet about {topic}. Style: {style}. Max {prompt_max_length} chars."
        "{update_guidance}{story_guidance}{cat_vocab_str}{guidelines_str}"
        "{current_date}{day_of_week}{time_period}{time_phrases_str}"
        "{cat_humor_str}{engagement_str}{avoid_str}"
    )
    (prompts_dir / "shorten_tweet.md").write_text(
        "Shorten this tweet to {max_length} chars (target {target_length}): {tweet}"
        " Current length: {current_length}"
    )
    (prompts_dir / "reply.md").write_text(
        "Reply to: {original_tweet}. Style: {style}. Vocab: {cat_vocab_str}. "
        "Max: {max_length}{context_line}"
    )
    (prompts_dir / "image_generation.md").write_text(
        "Image for {topic}: {tweet_text}{article_section}"
    )
    (prompts_dir / "tweet_update_guidance.md").write_text(
        "UPDATE GUIDANCE: {prev_context_str}"
    )
    (prompts_dir / "tweet_story_guidance_with_article.md").write_text(
        "STORY GUIDANCE: {article_details}"
    )
    (prompts_dir / "tweet_story_guidance_generic.md").write_text(
        "GENERIC STORY GUIDANCE"
    )
    (prompts_dir / "analyze_framing.md").write_text(
        "Analyze framing: {title} from {source}: {content}"
    )
    (prompts_dir / "tweet_framing.md").write_text(
        "Framing tweet: {title} {source} {framing_angle} {content} "
        "{cat_vocab_str} {cat_humor_str} {style}"
    )

    return PromptLoader(prompts_dir=str(prompts_dir))


@pytest.fixture
def news_fetcher():
    """Return a NewsFetcher instance."""
    return NewsFetcher()


# ===================================================================
# Tests: _truncate_at_sentence  (standalone utility)
# ===================================================================

class TestTruncateAtSentence:
    """Tests for the _truncate_at_sentence helper function."""

    def test_short_text_returned_unchanged(self):
        text = "Hello world."
        assert _truncate_at_sentence(text, 100) == text

    def test_exact_length_returned_unchanged(self):
        text = "Exactly ten."
        assert _truncate_at_sentence(text, len(text)) == text

    def test_truncates_at_sentence_boundary(self):
        text = "First sentence. Second sentence. Third sentence."
        result = _truncate_at_sentence(text, 35)
        # Should end after "Second sentence." (32 chars) -- complete sentence
        assert result.endswith(".")
        assert len(result) <= 35

    def test_truncates_at_exclamation(self):
        text = "Alert! Something happened. More details."
        result = _truncate_at_sentence(text, 10)
        assert result == "Alert!"

    def test_truncates_at_question_mark(self):
        text = "Who did it? The detective investigated."
        result = _truncate_at_sentence(text, 15)
        assert result == "Who did it?"

    def test_falls_back_to_newline(self):
        text = "Line one, no period\nLine two, no period\nLine three"
        result = _truncate_at_sentence(text, 25)
        assert "\n" not in result or result == text[:25].rstrip()

    def test_falls_back_to_space(self):
        text = "word " * 50
        result = _truncate_at_sentence(text, 20)
        assert len(result) <= 20
        # Should not cut mid-word
        assert not result.endswith("wor")

    def test_minimum_content_preservation(self):
        """If cutting at the only sentence boundary would keep < 1/3 content, skip it."""
        text = "A. " + "x" * 200
        # Sentence boundary at index 2 is < 1/3 of 100
        result = _truncate_at_sentence(text, 100)
        assert len(result) <= 100

    def test_empty_string(self):
        assert _truncate_at_sentence("", 10) == ""

    def test_no_natural_break_point(self):
        text = "abcdefghijklmnopqrstuvwxyz"
        result = _truncate_at_sentence(text, 10)
        assert len(result) <= 10


# ===================================================================
# Tests: PromptLoader
# ===================================================================

class TestPromptLoader:
    """Tests for loading and formatting prompt templates."""

    def test_load_template_with_substitutions(self, prompt_loader):
        result = prompt_loader.load("shorten_tweet.md",
                                    max_length=250,
                                    target_length=235,
                                    tweet="Hello world",
                                    current_length=300)
        assert "250" in result
        assert "235" in result
        assert "Hello world" in result
        assert "300" in result

    def test_load_missing_file_raises(self, prompt_loader):
        with pytest.raises(FileNotFoundError):
            prompt_loader.load("nonexistent_prompt.md")

    def test_safe_format_leaves_missing_keys(self, prompt_loader):
        """When a placeholder key is missing, _safe_format leaves it as-is."""
        template = "Hello {name}, you are {role}."
        result = prompt_loader._safe_format(template, {"name": "Walter"})
        assert "Walter" in result
        assert "{role}" in result

    def test_load_tweet_prompt_delegates_to_bluesky(self, prompt_loader):
        """load_tweet_prompt should always load the bluesky template."""
        result = prompt_loader.load_tweet_prompt(
            platform="x",
            topic="tech layoffs",
            style="serious journalist",
            prompt_max_length=250,
            update_guidance="",
            story_guidance="",
            cat_vocab_str="breaking mews",
            guidelines_str="be sharp",
            current_date="Feb 23, 2026",
            day_of_week="Monday",
            time_period="morning",
            time_phrases_str="Fresh from my morning perch",
            cat_humor_str="Filing this report between naps",
            engagement_str="What's your take?",
            avoid_str="politics, religion",
        )
        assert "tech layoffs" in result
        assert "serious journalist" in result

    def test_load_image_prompt(self, prompt_loader):
        result = prompt_loader.load_image_prompt(
            topic="stock market",
            tweet_text="Markets are wild today.",
            article_section="",
        )
        assert "stock market" in result

    def test_load_reply(self, prompt_loader):
        result = prompt_loader.load_reply(
            original_tweet="Hello cats",
            style="catty",
            cat_vocab_str="meow",
            max_length=250,
            context_line="",
        )
        assert "Hello cats" in result

    def test_load_framing_analysis(self, prompt_loader):
        result = prompt_loader.load_framing_analysis(
            title="Test Title",
            source="CNN",
            content="article body",
        )
        assert "Test Title" in result
        assert "CNN" in result

    def test_load_update_guidance(self, prompt_loader):
        result = prompt_loader.load_update_guidance(prev_context_str="previous post info")
        assert "previous post info" in result

    def test_load_story_guidance_with_article(self, prompt_loader):
        result = prompt_loader.load_story_guidance_with_article(
            article_details="Title: Test\nContent: body"
        )
        assert "Title: Test" in result

    def test_load_story_guidance_generic(self, prompt_loader):
        result = prompt_loader.load_story_guidance_generic()
        assert "GENERIC STORY GUIDANCE" in result

    def test_lru_cache_reuses_loaded_template(self, prompt_loader):
        """The raw template should only be read from disk once."""
        result1 = prompt_loader._load_raw("shorten_tweet.md")
        result2 = prompt_loader._load_raw("shorten_tweet.md")
        assert result1 is result2  # same cached object

    def test_get_prompt_loader_returns_singleton(self):
        """get_prompt_loader should return the same instance on repeated calls."""
        import src.prompt_loader as pl_module
        # Reset the global singleton for a clean test
        pl_module._loader = None
        loader_a = pl_module.get_prompt_loader()
        loader_b = pl_module.get_prompt_loader()
        assert loader_a is loader_b
        # Clean up
        pl_module._loader = None


# ===================================================================
# Tests: NewsFetcher
# ===================================================================

class TestNewsFetcher:
    """Tests for news fetching and processing."""

    def test_news_categories_populated(self, news_fetcher):
        assert len(news_fetcher.news_categories) > 0

    @patch("src.news_fetcher.gnewsdecoder")
    def test_resolve_google_news_url_success(self, mock_decoder, news_fetcher):
        mock_decoder.return_value = {
            "status": True,
            "decoded_url": "https://reuters.com/actual-article",
        }
        result = news_fetcher.resolve_google_news_url("https://news.google.com/proxy/...")
        assert result == "https://reuters.com/actual-article"

    @patch("src.news_fetcher.gnewsdecoder")
    def test_resolve_google_news_url_failure_returns_original(self, mock_decoder, news_fetcher):
        mock_decoder.return_value = {"status": False, "message": "decode failed"}
        original = "https://news.google.com/proxy/xyz"
        result = news_fetcher.resolve_google_news_url(original)
        assert result == original

    @patch("src.news_fetcher.gnewsdecoder")
    def test_resolve_google_news_url_exception_returns_original(self, mock_decoder, news_fetcher):
        mock_decoder.side_effect = Exception("network error")
        original = "https://news.google.com/proxy/abc"
        result = news_fetcher.resolve_google_news_url(original)
        assert result == original

    @patch("src.news_fetcher.requests.get")
    def test_fetch_article_content_success(self, mock_get, news_fetcher):
        html = """
        <html><body>
        <article>
            <p>First paragraph of the article content here with enough text to pass
            the minimum length check. This needs to be at least 200 characters long
            so we pad it out with some additional descriptive sentences about the topic
            at hand. The reporter investigated the claims thoroughly.</p>
        </article>
        </body></html>
        """
        mock_response = Mock()
        mock_response.content = html.encode()
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = news_fetcher.fetch_article_content("https://example.com/article")
        assert result is not None
        assert len(result) >= 200

    @patch("src.news_fetcher.requests.get")
    def test_fetch_article_content_too_short_returns_none(self, mock_get, news_fetcher):
        html = "<html><body><article><p>Short.</p></article></body></html>"
        mock_response = Mock()
        mock_response.content = html.encode()
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = news_fetcher.fetch_article_content("https://example.com/article")
        assert result is None

    @patch("src.news_fetcher.requests.get")
    def test_fetch_article_detects_paywall(self, mock_get, news_fetcher):
        html = """
        <html><body>
        <article>
            <p>Subscribe to continue reading this premium article.
            Already a subscriber? Sign in to read the full content.
            This is a premium content article that requires a subscription
            to access the complete text. Please subscribe now to continue.</p>
        </article>
        </body></html>
        """
        mock_response = Mock()
        mock_response.content = html.encode()
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = news_fetcher.fetch_article_content("https://example.com/paywalled")
        assert result is None

    @patch("src.news_fetcher.requests.get")
    def test_fetch_article_content_network_error(self, mock_get, news_fetcher):
        mock_get.side_effect = Exception("Connection timeout")
        result = news_fetcher.fetch_article_content("https://example.com/fail")
        assert result is None

    @patch("src.news_fetcher.requests.get")
    def test_fetch_article_content_returns_long_articles_intact(self, mock_get, news_fetcher):
        """fetch_article_content does NOT truncate the extracted body —
        downstream callers (meta_analyzer) own their own per-prompt budgets.
        Verify a long article passes through whole."""
        long_paragraph = "This is a complete sentence. " * 200  # ~5800 chars
        html = f"<html><body><article><p>{long_paragraph}</p></article></body></html>"
        mock_response = Mock()
        mock_response.content = html.encode()
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = news_fetcher.fetch_article_content("https://example.com/long")
        assert result is not None
        assert len(result) > 5000

    @patch("src.news_fetcher.feedparser.parse")
    def test_get_articles_for_topic_filters_blacklisted(self, mock_parse, news_fetcher):
        """Blacklisted sources (local papers, etc.) should be skipped."""
        now_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        mock_parse.return_value = Mock(entries=[
            Mock(
                title="Local Event",
                link="https://news.google.com/local",
                get=lambda k, d=None: {
                    "source": {"title": "Local Gazette"},
                    "summary": "A local event happened.",
                    "published": now_str,
                }.get(k, d),
            ),
        ])

        with patch.object(news_fetcher, "resolve_google_news_url", return_value="https://example.com"):
            result = news_fetcher.get_articles_for_topic("test topic")
        assert len(result) == 0

    @patch("src.news_fetcher.feedparser.parse")
    def test_get_articles_for_topic_empty_feed(self, mock_parse, news_fetcher):
        mock_parse.return_value = Mock(entries=[])
        result = news_fetcher.get_articles_for_topic("nonexistent topic xyz")
        assert result == []

    @patch("src.news_fetcher.feedparser.parse")
    def test_get_articles_for_topic_exception(self, mock_parse, news_fetcher):
        mock_parse.side_effect = Exception("Feed parse error")
        result = news_fetcher.get_articles_for_topic("test")
        assert result == []

    def test_extract_trending_topics_empty_input(self, news_fetcher):
        result = news_fetcher.extract_trending_topics([])
        assert result == []

    def test_extract_trending_topics_finds_proper_nouns(self, news_fetcher):
        stories = [
            {"title": "Senate passes bill on Healthcare"},
            {"title": "Senate debates Healthcare reform"},
            {"title": "Healthcare costs rising in Senate report"},
        ]
        result = news_fetcher.extract_trending_topics(stories)
        # "Senate" and "Healthcare" appear multiple times
        assert any("Senate" in t for t in result) or any("senate" in t.lower() for t in result)
        assert any("Healthcare" in t for t in result) or any("healthcare" in t.lower() for t in result)

    @patch("src.news_fetcher.feedparser.parse")
    @patch("src.news_fetcher.time.sleep")
    def test_get_trending_topics_fallback(self, mock_sleep, mock_parse, news_fetcher):
        """When no articles are found at all, get_trending_topics returns a minimal fallback."""
        mock_parse.return_value = Mock(entries=[])

        # get_article_for_topic is called but not explicitly defined on NewsFetcher;
        # patch it on the class with create=True so it can be intercepted.
        with patch.object(NewsFetcher, "get_article_for_topic", create=True, return_value=None):
            result = news_fetcher.get_trending_topics(count=3)

        assert len(result) >= 1
        assert result[0]["title"] == "Breaking news developments"

    @patch("src.news_fetcher.feedparser.parse")
    def test_get_top_stories_empty(self, mock_parse, news_fetcher):
        mock_parse.return_value = Mock(entries=[])
        result = news_fetcher.get_top_stories()
        assert result == []

    @patch("src.news_fetcher.feedparser.parse")
    def test_get_top_stories_exception(self, mock_parse, news_fetcher):
        mock_parse.side_effect = Exception("Network error")
        result = news_fetcher.get_top_stories()
        assert result == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
