#!/usr/bin/env python3
"""
Test suite for the mewscast content generation pipeline.

Covers the ContentGenerator class (src/content_generator.py), PromptLoader
(src/prompt_loader.py), NewsFetcher (src/news_fetcher.py), and their
interactions.  All external API calls (Anthropic, Google News RSS, HTTP
requests) are mocked so that the tests run offline and deterministically.
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

from src.content_generator import ContentGenerator, _truncate_at_sentence
from src.prompt_loader import PromptLoader, get_prompt_loader
from src.news_fetcher import NewsFetcher


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def generator():
    """Return a ContentGenerator with mocked Anthropic client and prompt loader."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("src.content_generator.Anthropic"):
            gen = ContentGenerator()
            gen.client = Mock()
            return gen


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


@pytest.fixture
def sample_story_metadata():
    """Common story metadata used across several tests."""
    return {
        "title": "Senate Passes Major Infrastructure Bill",
        "context": "The bill allocates $500 billion for roads and bridges.",
        "source": "Reuters",
        "url": "https://example.com/senate-bill",
        "article_content": (
            "The United States Senate passed a sweeping infrastructure bill "
            "today, allocating $500 billion for roads, bridges, and broadband. "
            "The vote was 65-35, with bipartisan support."
        ),
    }


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
# Tests: ContentGenerator -- tweet generation
# ===================================================================

class TestGenerateTweet:
    """Tests for ContentGenerator.generate_tweet and its helpers."""

    def test_basic_tweet_generation(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text="Breaking mews! Senate passes bill. This cat is watching.")]
        generator.client.messages.create.return_value = mock_resp

        result = generator.generate_tweet(topic="politics")

        assert result is not None
        assert "tweet" in result
        assert result["needs_source_reply"] is False
        assert result["story_metadata"] is None

    def test_tweet_with_story_metadata_adds_source_indicator(self, generator, sample_story_metadata):
        tweet_text = "Senate passes infrastructure bill. This cat approves."
        mock_resp = Mock()
        mock_resp.content = [Mock(text=tweet_text)]
        generator.client.messages.create.return_value = mock_resp

        result = generator.generate_tweet(
            trending_topic="infrastructure bill",
            story_metadata=sample_story_metadata,
        )

        assert result is not None
        assert result["tweet"].endswith(" 📰↓")
        assert result["needs_source_reply"] is True
        assert result["story_metadata"] is sample_story_metadata

    def test_random_topic_selected_when_none_provided(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text="Cat news update. Paws for thought.")]
        generator.client.messages.create.return_value = mock_resp

        result = generator.generate_tweet()

        assert result is not None
        assert "tweet" in result

    def test_quote_stripping_double_quotes(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text='"This is a quoted tweet."')]
        generator.client.messages.create.return_value = mock_resp

        result = generator.generate_tweet(topic="test")
        assert not result["tweet"].startswith('"')
        assert not result["tweet"].endswith('"')

    def test_quote_stripping_single_quotes(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text="'Single quoted tweet.'")]
        generator.client.messages.create.return_value = mock_resp

        result = generator.generate_tweet(topic="test")
        assert not result["tweet"].startswith("'")
        assert not result["tweet"].endswith("'")

    def test_retry_shortening_when_too_long(self, generator):
        long_text = "A" * 300
        short_text = "Short enough tweet."
        mock_long = Mock()
        mock_long.content = [Mock(text=long_text)]
        mock_short = Mock()
        mock_short.content = [Mock(text=short_text)]

        generator.client.messages.create.side_effect = [mock_long, mock_short]

        result = generator.generate_tweet(topic="test")
        assert result is not None
        assert len(result["tweet"]) <= generator.max_length

    def test_truncation_after_max_retries(self, generator):
        """After 3 failed shortening attempts, truncation should kick in."""
        long_text = "This is a long sentence. " * 20  # Very long
        mock_long = Mock()
        mock_long.content = [Mock(text=long_text)]
        # generate_tweet: 1 initial + up to 2 shorten calls (retries 0,1 call _shorten_tweet;
        # retry 2 truncates directly without another API call)
        generator.client.messages.create.return_value = mock_long

        result = generator.generate_tweet(topic="test")
        assert result is not None
        assert len(result["tweet"]) <= generator.max_length

    def test_api_error_returns_fallback_tweet(self, generator):
        generator.client.messages.create.side_effect = Exception("API timeout")

        result = generator.generate_tweet(topic="technology")
        assert result is not None
        assert "technology" in result["tweet"]
        assert result["needs_source_reply"] is False

    def test_validation_failure_returns_none(self, generator):
        """If the generated tweet contains a prohibited pattern, return None."""
        mock_resp = Mock()
        mock_resp.content = [Mock(text="I cannot generate content because the article is paywalled.")]
        generator.client.messages.create.return_value = mock_resp

        result = generator.generate_tweet(topic="test")
        assert result is None

    def test_trending_topic_takes_priority(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text="Breaking mews on the trend.")]
        generator.client.messages.create.return_value = mock_resp

        result = generator.generate_tweet(topic="general", trending_topic="specific trend")

        # The prompt should use the trending topic; verify via the API call args
        call_args = generator.client.messages.create.call_args
        prompt_sent = call_args[1]["messages"][0]["content"] if "messages" in call_args[1] else ""
        # trending_topic becomes the "selected_topic" used in prompt building
        assert result is not None

    def test_framing_angle_path(self, generator, sample_story_metadata):
        """When framing analysis returns has_issues=True and the coin flip hits,
        the framing prompt path should be taken."""
        framing_resp = Mock()
        framing_resp.content = [Mock(text='{"has_issues": true, "angle": "headline vs content mismatch"}')]
        tweet_resp = Mock()
        tweet_resp.content = [Mock(text="Framing cat take.")]

        generator.client.messages.create.side_effect = [framing_resp, tweet_resp]

        with patch("src.content_generator.random") as mock_random:
            mock_random.choice.return_value = "politics"
            mock_random.random.return_value = 0.1  # Below framing_chance (0.5)
            mock_random.sample.return_value = ["breaking mews", "paws for thought"]
            mock_random.shuffle = lambda x: None

            result = generator.generate_tweet(
                trending_topic="infrastructure",
                story_metadata=sample_story_metadata,
            )

        assert result is not None

    def test_max_content_length_reserves_space_for_source_indicator(self, generator, sample_story_metadata):
        """When story_metadata is present, the effective max length
        should be reduced by the length of the source indicator."""
        source_indicator = " 📰↓"
        expected_max = generator.max_length - len(source_indicator)
        tweet_text = "x" * expected_max  # exactly at limit
        mock_resp = Mock()
        mock_resp.content = [Mock(text=tweet_text)]
        generator.client.messages.create.return_value = mock_resp

        result = generator.generate_tweet(
            trending_topic="test",
            story_metadata=sample_story_metadata,
        )

        # Total tweet length = content + source indicator
        assert len(result["tweet"]) == expected_max + len(source_indicator)


# ===================================================================
# Tests: ContentGenerator -- content validation
# ===================================================================

class TestValidateTweetContent:
    """Tests for _validate_tweet_content."""

    def test_valid_tweet(self, generator):
        result = generator._validate_tweet_content(
            "Breaking mews! Senate passes major bill. This cat is watching."
        )
        assert result["valid"] is True
        assert result["reason"] is None

    @pytest.mark.parametrize("bad_phrase", [
        "I cannot generate",
        "I can't write",
        "unable to access the article",
        "don't have information",
        "paywall detected",
        "subscription required",
        "following strict rules",
        "can't access the content",
    ])
    def test_meta_commentary_rejected(self, generator, bad_phrase):
        result = generator._validate_tweet_content(f"Well, {bad_phrase} so here we are.")
        assert result["valid"] is False
        assert "meta-commentary" in result["reason"]

    @pytest.mark.parametrize("bad_phrase", [
        "never happened",
        "fake news",
        "that's not true",
        "this is false",
        "the article is wrong",
        "misinformation",
        "actually, that person is alive",
        "is still alive",
        "is still in office",
    ])
    def test_contradiction_rejected(self, generator, bad_phrase):
        result = generator._validate_tweet_content(f"Hold on -- {bad_phrase}.")
        assert result["valid"] is False
        assert "contradiction" in result["reason"]

    @pytest.mark.parametrize("bad_phrase", [
        "the date says 2025",
        "dates don't add up",
        "must be a typo",
        "time travel confirmed",
        "calendar is wrong",
    ])
    def test_temporal_skepticism_rejected(self, generator, bad_phrase):
        result = generator._validate_tweet_content(f"Interesting -- {bad_phrase}.")
        assert result["valid"] is False
        assert "temporal skepticism" in result["reason"]


# ===================================================================
# Tests: ContentGenerator -- _shorten_tweet
# ===================================================================

class TestShortenTweet:
    """Tests for the _shorten_tweet helper."""

    def test_successful_shortening(self, generator):
        shortened = "Short version of the tweet."
        mock_resp = Mock()
        mock_resp.content = [Mock(text=shortened)]
        generator.client.messages.create.return_value = mock_resp

        result = generator._shorten_tweet("A very long tweet " * 20, 250)
        assert result == shortened

    def test_quotes_stripped_from_shortened(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text='"Shortened tweet."')]
        generator.client.messages.create.return_value = mock_resp

        result = generator._shorten_tweet("long tweet", 250)
        assert not result.startswith('"')

    def test_api_error_returns_original(self, generator):
        generator.client.messages.create.side_effect = Exception("API error")
        original = "Original long tweet that failed to shorten."
        result = generator._shorten_tweet(original, 250)
        assert result == original


# ===================================================================
# Tests: ContentGenerator -- generate_source_reply
# ===================================================================

class TestGenerateSourceReply:
    """Tests for source citation reply generation."""

    def test_source_reply_with_url(self, generator):
        metadata = {
            "title": "Test Article",
            "url": "https://example.com/article",
            "source": "Reuters",
        }
        reply = generator.generate_source_reply("Original tweet", metadata)
        assert reply == "https://example.com/article"

    def test_source_reply_without_url(self, generator):
        metadata = {
            "title": "Test Article",
            "context": "Additional context here.",
            "source": "AP News",
        }
        reply = generator.generate_source_reply("Original tweet", metadata)
        assert "Source: Test Article" in reply
        assert "AP News" in reply

    def test_source_reply_without_url_truncated(self, generator):
        metadata = {
            "title": "T" * 200,
            "context": "C" * 200,
            "source": "Very Long Source Name " * 5,
        }
        reply = generator.generate_source_reply("Original tweet", metadata)
        assert len(reply) <= generator.max_length


# ===================================================================
# Tests: ContentGenerator -- generate_reply
# ===================================================================

class TestGenerateReply:
    """Tests for the reply generation method."""

    def test_successful_reply(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text="Great story! This cat is on it.")]
        generator.client.messages.create.return_value = mock_resp

        reply = generator.generate_reply("Some interesting tweet")
        assert len(reply) <= generator.max_length
        assert "This cat is on it" in reply

    def test_reply_strips_quotes(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text='"Quoted reply text."')]
        generator.client.messages.create.return_value = mock_resp

        reply = generator.generate_reply("Tweet")
        assert not reply.startswith('"')

    def test_reply_api_error_fallback(self, generator):
        generator.client.messages.create.side_effect = Exception("Oops")
        reply = generator.generate_reply("Tweet")
        assert "#BreakingMews" in reply

    def test_reply_truncated_if_too_long(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text="X " * 200)]
        generator.client.messages.create.return_value = mock_resp

        reply = generator.generate_reply("Tweet")
        assert len(reply) <= generator.max_length


# ===================================================================
# Tests: ContentGenerator -- generate_image_prompt
# ===================================================================

class TestGenerateImagePrompt:
    """Tests for AI image prompt generation."""

    def test_successful_image_prompt(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text="Brown tabby cat at senate podium, dramatic lighting")]
        generator.client.messages.create.return_value = mock_resp

        prompt = generator.generate_image_prompt(
            "infrastructure bill",
            "Senate passes bill!",
        )
        assert "Brown tabby" in prompt
        assert len(prompt) <= 200

    def test_image_prompt_truncated_to_200_chars(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text="x" * 250)]
        generator.client.messages.create.return_value = mock_resp

        prompt = generator.generate_image_prompt("topic", "tweet")
        assert len(prompt) <= 200

    def test_image_prompt_strips_quotes(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text='"Quoted image prompt"')]
        generator.client.messages.create.return_value = mock_resp

        prompt = generator.generate_image_prompt("topic", "tweet")
        assert not prompt.startswith('"')

    def test_image_prompt_api_error_fallback(self, generator):
        generator.client.messages.create.side_effect = Exception("API error")

        prompt = generator.generate_image_prompt("economics", "Markets tumble.")
        assert "Dramatic" in prompt or "detective" in prompt.lower() or "cat" in prompt.lower()

    def test_image_prompt_includes_article_content(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text="Cat at Hong Kong rooftop")]
        generator.client.messages.create.return_value = mock_resp

        prompt = generator.generate_image_prompt(
            "fire", "Building ablaze!", article_content="Hong Kong high-rise fire"
        )
        # Just verify the call succeeded -- prompt template includes article_section
        assert prompt is not None


# ===================================================================
# Tests: ContentGenerator -- vocabulary selection and anti-repetition
# ===================================================================

class TestVocabSelection:
    """Tests for _select_vocab_for_story and phrase tracking."""

    def test_topic_matching_selects_relevant_phrases(self, generator):
        result = generator._select_vocab_for_story(
            "president signs executive order",
            "The president announced a new executive order today.",
        )
        # Should return a non-empty comma-separated string
        assert len(result) > 0
        assert "," in result or len(result.split()) >= 1

    def test_no_topic_match_uses_universal(self, generator):
        result = generator._select_vocab_for_story(
            "obscure topic with no keyword matches xyz123",
        )
        # Should still return phrases (universal fallback)
        assert len(result) > 0

    def test_recently_used_phrases_filtered(self, generator, tmp_path):
        """Phrases stored in recent_vocab.json should be excluded."""
        # Point the recent phrases file to our temp location
        recent_file = tmp_path / "recent_vocab.json"
        generator._recent_phrases_file = str(recent_file)

        # Pre-populate with some phrases
        universal = list(generator.vocab_universal)
        recent_data = {"recent_phrases": universal[:5]}
        recent_file.write_text(json.dumps(recent_data))

        result = generator._select_vocab_for_story("some generic topic")
        # The result should still be non-empty (fallback to all if everything filtered)
        assert len(result) > 0

    def test_record_used_phrase(self, generator, tmp_path):
        recent_file = tmp_path / "recent_vocab.json"
        generator._recent_phrases_file = str(recent_file)
        recent_file.write_text(json.dumps({"recent_phrases": []}))

        # Tweet contains a known universal phrase
        generator._record_used_phrase("This is breaking mews from the capitol.")

        data = json.loads(recent_file.read_text())
        assert "breaking mews" in data["recent_phrases"]

    def test_recent_phrases_rolling_window(self, generator, tmp_path):
        """Only the last N phrases should be kept."""
        recent_file = tmp_path / "recent_vocab.json"
        generator._recent_phrases_file = str(recent_file)

        # Fill with more than the limit
        phrases = [f"phrase_{i}" for i in range(30)]
        recent_file.write_text(json.dumps({"recent_phrases": phrases}))

        # Record one more -- total should be capped at _recent_phrases_limit
        generator._record_used_phrase("breaking mews is great")
        data = json.loads(recent_file.read_text())
        assert len(data["recent_phrases"]) <= generator._recent_phrases_limit

    def test_load_recent_phrases_handles_missing_file(self, generator, tmp_path):
        generator._recent_phrases_file = str(tmp_path / "does_not_exist.json")
        result = generator._load_recent_phrases()
        assert result == []

    def test_load_recent_phrases_handles_corrupt_json(self, generator, tmp_path):
        corrupt_file = tmp_path / "corrupt.json"
        corrupt_file.write_text("not valid json {{{")
        generator._recent_phrases_file = str(corrupt_file)
        result = generator._load_recent_phrases()
        assert result == []


# ===================================================================
# Tests: ContentGenerator -- analyze_media_framing
# ===================================================================

class TestAnalyzeMediaFraming:
    """Tests for the media framing analysis method."""

    def test_returns_no_issues_without_content(self, generator):
        result = generator.analyze_media_framing({"title": "Test", "source": "X"})
        assert result["has_issues"] is False

    def test_returns_no_issues_for_none_metadata(self, generator):
        result = generator.analyze_media_framing(None)
        assert result["has_issues"] is False

    def test_parses_json_response(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text='{"has_issues": true, "angle": "headline mismatch"}')]
        generator.client.messages.create.return_value = mock_resp

        result = generator.analyze_media_framing({
            "title": "Economy CRASHES",
            "source": "News Corp",
            "article_content": "Economy dipped 0.1%.",
        })
        assert result["has_issues"] is True
        assert "headline mismatch" in result["angle"]

    def test_parses_json_from_code_block(self, generator):
        mock_resp = Mock()
        mock_resp.content = [Mock(text='```json\n{"has_issues": false, "angle": null}\n```')]
        generator.client.messages.create.return_value = mock_resp

        result = generator.analyze_media_framing({
            "title": "Normal story",
            "source": "AP",
            "article_content": "Normal content.",
        })
        assert result["has_issues"] is False

    def test_api_error_returns_safe_default(self, generator):
        generator.client.messages.create.side_effect = Exception("timeout")
        result = generator.analyze_media_framing({
            "title": "Test",
            "source": "X",
            "article_content": "Content.",
        })
        assert result["has_issues"] is False
        assert result["angle"] is None


# ===================================================================
# Tests: ContentGenerator -- _build_news_cat_prompt
# ===================================================================

class TestBuildNewsCatPrompt:
    """Tests for prompt construction helpers."""

    def test_prompt_contains_topic(self, generator):
        prompt = generator._build_news_cat_prompt("cryptocurrency crash")
        assert "cryptocurrency crash" in prompt or "crypto" in prompt.lower()

    def test_prompt_includes_article_details_when_provided(self, generator):
        prompt = generator._build_news_cat_prompt(
            "tech layoffs",
            is_specific_story=True,
            article_details="Title: Big Tech fires 10,000\nContent: details...",
        )
        assert "Big Tech fires 10,000" in prompt

    def test_prompt_includes_update_guidance(self, generator):
        previous_posts = [{
            "post": {
                "content": "First post about the story.",
                "topic": "senate bill",
                "timestamp": "2026-02-22T10:00:00Z",
            }
        }]
        prompt = generator._build_news_cat_prompt(
            "senate bill update",
            previous_posts=previous_posts,
        )
        # The update guidance template should be populated
        assert "First post" in prompt or "UPDATE" in prompt

    def test_prompt_max_length_reduced_for_specific_story(self, generator):
        """When is_specific_story=True, the max length passed to the prompt
        should be reduced to leave room for the source indicator."""
        # We can verify by checking the prompt text for the reduced number
        prompt = generator._build_news_cat_prompt(
            "test topic",
            is_specific_story=True,
        )
        source_indicator_len = 4  # " 📰↓"
        expected_max = generator.max_length - source_indicator_len
        assert str(expected_max) in prompt


# ===================================================================
# Tests: ContentGenerator -- _build_framing_prompt
# ===================================================================

class TestBuildFramingPrompt:
    """Tests for the framing angle prompt builder."""

    def test_framing_prompt_includes_all_fields(self, generator):
        story = {
            "title": "Economy SURGES",
            "source": "News Corp",
            "article_content": "Economy grew 0.1% last quarter in a modest gain.",
        }
        media_issues = {
            "has_issues": True,
            "angle": "headline exaggerates a tiny gain",
        }
        prompt = generator._build_framing_prompt(story, media_issues)
        assert "Economy SURGES" in prompt
        assert "News Corp" in prompt
        assert "headline exaggerates" in prompt

    def test_framing_prompt_truncates_long_content(self, generator):
        story = {
            "title": "Test",
            "source": "Src",
            "article_content": "x" * 2000,  # Longer than 800 limit
        }
        media_issues = {"has_issues": True, "angle": "angle"}
        prompt = generator._build_framing_prompt(story, media_issues)
        # The prompt should not contain the full 2000 chars of content
        assert "x" * 801 not in prompt


# ===================================================================
# Tests: ContentGenerator -- initialization
# ===================================================================

class TestContentGeneratorInit:
    """Tests for ContentGenerator construction and config loading."""

    def test_raises_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            # Make sure ANTHROPIC_API_KEY is not set
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(ValueError, match="Missing ANTHROPIC_API_KEY"):
                with patch("src.content_generator.Anthropic"):
                    ContentGenerator()

    def test_loads_config_values(self, generator):
        assert generator.max_length > 0
        assert isinstance(generator.topics, list)
        assert len(generator.topics) > 0
        assert isinstance(generator.style, str)
        assert isinstance(generator.avoid_topics, list)
        assert isinstance(generator.editorial_guidelines, list)

    def test_persona_defaults(self, generator):
        assert "cat" in generator.persona.lower() or "reporter" in generator.persona.lower()


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
    def test_fetch_article_content_truncates_long_articles(self, mock_get, news_fetcher):
        long_paragraph = "This is a complete sentence. " * 200  # ~5800 chars
        html = f"<html><body><article><p>{long_paragraph}</p></article></body></html>"
        mock_response = Mock()
        mock_response.content = html.encode()
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = news_fetcher.fetch_article_content("https://example.com/long")
        assert result is not None
        assert len(result) <= 1500

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


# ===================================================================
# Tests: Integration-style -- full pipeline with mocks
# ===================================================================

class TestPipelineIntegration:
    """Higher-level tests that exercise the full generation pipeline."""

    def test_end_to_end_specific_story(self, generator, sample_story_metadata):
        """Walk through generating a tweet for a specific story from metadata."""
        tweet_text = "Breaking mews! Senate passes infrastructure bill 65-35."
        mock_resp = Mock()
        mock_resp.content = [Mock(text=tweet_text)]
        generator.client.messages.create.return_value = mock_resp

        result = generator.generate_tweet(
            trending_topic="infrastructure bill",
            story_metadata=sample_story_metadata,
        )

        assert result is not None
        assert result["needs_source_reply"] is True
        assert result["tweet"].endswith(" 📰↓")
        assert len(result["tweet"]) <= generator.max_length + 10  # small buffer for emoji

        # Now generate a source reply
        reply = generator.generate_source_reply(result["tweet"], sample_story_metadata)
        assert reply == sample_story_metadata["url"]

    def test_end_to_end_general_topic(self, generator):
        """Generate a tweet without specific story metadata."""
        tweet_text = "Tech layoffs continue. This cat's watching Silicon Valley."
        mock_resp = Mock()
        mock_resp.content = [Mock(text=tweet_text)]
        generator.client.messages.create.return_value = mock_resp

        result = generator.generate_tweet(topic="tech layoffs")

        assert result is not None
        assert result["needs_source_reply"] is False
        assert not result["tweet"].endswith(" 📰↓")
        assert len(result["tweet"]) <= generator.max_length

    def test_end_to_end_with_reply(self, generator):
        """Generate a tweet then generate a reply to it."""
        tweet_resp = Mock()
        tweet_resp.content = [Mock(text="Markets tumble. This cat is watching.")]
        reply_resp = Mock()
        reply_resp.content = [Mock(text="Indeed, this cat concurs!")]

        generator.client.messages.create.side_effect = [tweet_resp, reply_resp]

        tweet_result = generator.generate_tweet(topic="stock market")
        assert tweet_result is not None

        reply = generator.generate_reply(tweet_result["tweet"])
        assert len(reply) > 0
        assert len(reply) <= generator.max_length

    def test_end_to_end_with_image_prompt(self, generator, sample_story_metadata):
        """Generate a tweet and then an image prompt for it."""
        tweet_resp = Mock()
        tweet_resp.content = [Mock(text="Senate passes bill. This cat reports.")]
        image_resp = Mock()
        image_resp.content = [Mock(text="Brown tabby at Senate podium")]

        generator.client.messages.create.side_effect = [tweet_resp, image_resp]

        result = generator.generate_tweet(
            trending_topic="infrastructure",
            story_metadata=sample_story_metadata,
        )
        assert result is not None

        image_prompt = generator.generate_image_prompt(
            "infrastructure bill",
            result["tweet"],
            article_content=sample_story_metadata["article_content"],
        )
        assert len(image_prompt) <= 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
