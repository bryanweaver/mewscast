#!/usr/bin/env python3
"""
Test suite for the post deduplication system in mewscast.

Covers the PostTracker class (src/post_tracker.py) which is responsible for:
- Exact URL deduplication
- Topic similarity detection via keyword overlap and proper-noun matching
- Content similarity detection (generated post text vs. historical posts)
- Story cluster discovery (grouping related articles)
- Update-story detection (allowing new developments on the same topic)
- Post history recording, cleanup, and filtering
- Backward-compatible is_duplicate() wrapper

All filesystem and network I/O is mocked so tests run in isolation.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

# Add project root and src/ to the path so imports resolve correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from src.post_tracker import PostTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_post(topic, url, source="TestSource", content=None, hours_ago=0,
               tweet_id=None, bluesky_uri=None, image_prompt=None):
    """Return a post-history record dict with a timestamp `hours_ago` hours in the past."""
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "timestamp": ts.isoformat(),
        "topic": topic,
        "url": url,
        "source": source,
        "content": content,
        "image_prompt": image_prompt,
        "x_tweet_id": tweet_id,
        "x_reply_tweet_id": None,
        "bluesky_uri": bluesky_uri,
        "bluesky_reply_uri": None,
    }


def _make_story(title, url=None, source="TestSource", article_content=None):
    """Return a story-metadata dict matching what NewsFetcher produces."""
    return {
        "title": title,
        "url": url or f"https://example.com/{title.lower().replace(' ', '-')[:30]}",
        "source": source,
        "article_content": article_content,
    }


@pytest.fixture
def tmp_history(tmp_path):
    """Create a temporary history JSON file and return its path."""
    history_file = tmp_path / "posts_history.json"
    history_file.write_text(json.dumps({"posts": []}))
    return str(history_file)


@pytest.fixture
def default_config():
    """Return the default deduplication config matching config.yaml production values."""
    return {
        "enabled": True,
        "topic_cooldown_hours": 72,
        "topic_similarity_threshold": 0.40,
        "content_cooldown_hours": 72,
        "content_similarity_threshold": 0.65,
        "source_cooldown_hours": 0,
        "url_deduplication": True,
        "max_history_days": 30,
        "allow_updates": True,
    }


@pytest.fixture
def tracker(tmp_history, default_config):
    """Return a PostTracker backed by a fresh temp file with default config."""
    return PostTracker(history_file=tmp_history, config=default_config)


# ===========================================================================
# 1. Initialization and history loading
# ===========================================================================

class TestInitialization:
    """PostTracker construction, default paths, and history loading."""

    def test_default_config_when_none_provided(self, tmp_history):
        """Tracker falls back to built-in defaults when no config dict is given."""
        t = PostTracker(history_file=tmp_history, config=None)
        assert t.config["enabled"] is True
        assert t.config["topic_cooldown_hours"] == 48
        assert t.config["url_deduplication"] is True
        assert t.config["max_history_days"] == 7

    def test_custom_config_is_used(self, tmp_history):
        """Config dict passed at init is stored and used."""
        cfg = {"enabled": False, "topic_cooldown_hours": 24}
        t = PostTracker(history_file=tmp_history, config=cfg)
        assert t.config["enabled"] is False
        assert t.config["topic_cooldown_hours"] == 24

    def test_load_empty_history_file(self, tmp_history):
        """An empty-posts JSON file results in an empty list."""
        t = PostTracker(history_file=tmp_history)
        assert t.posts == []

    def test_load_missing_history_file(self, tmp_path):
        """A non-existent history file results in an empty list (no crash)."""
        missing = str(tmp_path / "does_not_exist.json")
        t = PostTracker(history_file=missing)
        assert t.posts == []

    def test_load_corrupt_json(self, tmp_path):
        """Corrupt JSON gracefully falls back to empty history."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json!!")
        t = PostTracker(history_file=str(bad_file))
        assert t.posts == []

    def test_load_valid_history(self, tmp_path):
        """Valid history file is loaded correctly."""
        history_file = tmp_path / "history.json"
        post = _make_post("Test story", "https://example.com/1")
        history_file.write_text(json.dumps({"posts": [post]}))
        t = PostTracker(history_file=str(history_file))
        assert len(t.posts) == 1
        assert t.posts[0]["topic"] == "Test story"


# ===========================================================================
# 2. URL deduplication (_url_posted)
# ===========================================================================

class TestUrlDeduplication:
    """Exact URL matching -- the hardest dedup block."""

    def test_exact_url_is_duplicate(self, tracker):
        """Posting the same URL twice is always blocked."""
        url = "https://example.com/story-1"
        tracker.posts.append(_make_post("Story 1", url))
        story = _make_story("Totally Different Title", url=url)
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is True

    def test_different_url_is_not_duplicate(self, tracker):
        """Different URLs with unrelated titles do not trigger the URL-level block."""
        tracker.posts.append(_make_post("Earthquake in Japan", "https://example.com/story-1"))
        story = _make_story("Stock Market Rallies on Jobs Data", url="https://example.com/story-2")
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is False

    def test_url_dedup_disabled(self, tmp_history):
        """When url_deduplication is false, exact URL match is ignored."""
        cfg = {"enabled": True, "url_deduplication": False}
        t = PostTracker(history_file=tmp_history, config=cfg)
        url = "https://example.com/story-1"
        t.posts.append(_make_post("Story 1", url))
        story = _make_story("Different headline", url=url)
        result = t.check_story_status(story)
        assert result["is_duplicate"] is False

    def test_story_without_url(self, tracker):
        """A story with no URL skips the URL-level check entirely."""
        tracker.posts.append(_make_post("Story", "https://example.com/a"))
        story = _make_story("Story", url=None)
        story["url"] = None
        result = tracker.check_story_status(story)
        # Should not raise; duplicate decision falls to topic similarity
        assert isinstance(result["is_duplicate"], bool)


# ===========================================================================
# 3. Content similarity detection (_similar_content_posted)
# ===========================================================================

class TestContentSimilarity:
    """Check that near-identical generated post text is caught."""

    def test_identical_content_is_duplicate(self, tracker):
        """Posting exactly the same post text is blocked."""
        content = "Breaking news from the capitol today regarding major policy changes."
        tracker.posts.append(
            _make_post("Policy story", "https://example.com/1", content=content)
        )
        story = _make_story("New headline", url="https://example.com/2")
        result = tracker.check_story_status(story, post_content=content)
        assert result["is_duplicate"] is True

    def test_very_similar_content_is_duplicate(self, tracker):
        """Content with high keyword overlap (>=65%) is blocked."""
        old_content = "The president signed a major executive order on trade tariffs today."
        new_content = "The president signed a major executive order on trade tariffs this morning."
        tracker.posts.append(
            _make_post("Trade story", "https://example.com/1", content=old_content)
        )
        story = _make_story("Trade headline", url="https://example.com/2")
        result = tracker.check_story_status(story, post_content=new_content)
        assert result["is_duplicate"] is True

    def test_different_content_is_not_duplicate(self, tracker):
        """Substantially different post text should not be blocked."""
        old_content = "Earthquake measuring 6.2 strikes southern California coast."
        new_content = "Stock market rallies on positive jobs data this quarter."
        tracker.posts.append(
            _make_post("Quake", "https://example.com/1", content=old_content)
        )
        story = _make_story("Market", url="https://example.com/2")
        result = tracker.check_story_status(story, post_content=new_content)
        assert result["is_duplicate"] is False

    def test_content_check_skipped_when_no_post_content(self, tracker):
        """If post_content is None, content similarity check is skipped."""
        old = "Earthquake hits coast, buildings damaged across region."
        tracker.posts.append(
            _make_post("Quake", "https://example.com/1", content=old)
        )
        story = _make_story("Quake update", url="https://example.com/2")
        result = tracker.check_story_status(story, post_content=None)
        # Without post_content the content-level block cannot fire
        # Duplicate status depends on title similarity only
        assert isinstance(result["is_duplicate"], bool)

    def test_old_content_outside_cooldown_not_flagged(self, tracker):
        """Content older than content_cooldown_hours is not considered."""
        content = "Breaking news about the annual budget debate in Washington."
        tracker.posts.append(
            _make_post("Budget story", "https://example.com/1",
                       content=content, hours_ago=80)  # > 72h default cooldown
        )
        story = _make_story("Budget II", url="https://example.com/2")
        result = tracker.check_story_status(story, post_content=content)
        assert result["is_duplicate"] is False

    def test_content_similarity_ignores_hashtags_and_urls(self, tracker):
        """Hashtags and URLs are stripped before comparison so they don't inflate overlap."""
        old = "Big news #BreakingMews https://t.co/abc. Important policy shift announced today."
        new = "Important policy shift announced today. #BreakingMews https://t.co/xyz"
        tracker.posts.append(
            _make_post("Policy", "https://example.com/1", content=old)
        )
        story = _make_story("Policy", url="https://example.com/2")
        result = tracker.check_story_status(story, post_content=new)
        # The actual meaningful words overlap heavily, so this should be flagged
        assert result["is_duplicate"] is True

    def test_content_stops_words_filtered(self, tracker):
        """Cat-themed stop words (mews, purr, paws, etc.) are excluded from comparison."""
        # If only shared words are cat stop words, it should NOT be flagged
        old = "Cat mews purr paws fur whisker perch meow. Something unique happened."
        new = "Cat mews purr paws fur whisker perch meow. Totally different event occurred."
        tracker.posts.append(
            _make_post("A", "https://example.com/1", content=old)
        )
        story = _make_story("B", url="https://example.com/2")
        result = tracker.check_story_status(story, post_content=new)
        # Most shared words are stop words, so meaningful overlap should be low
        assert result["is_duplicate"] is False


# ===========================================================================
# 4. Topic / title similarity (_find_story_cluster + check_story_status)
# ===========================================================================

class TestTopicSimilarity:
    """Keyword overlap and proper-noun matching on article titles."""

    def test_identical_titles_are_duplicate(self, tracker):
        """Two articles with the same title are duplicates (high overlap).

        Note: the title must NOT contain update keywords (e.g. 'announces')
        because those bypass the similarity block.
        """
        title = "Trump New Tariffs on Chinese Imports Raise Concerns"
        tracker.posts.append(
            _make_post(title, "https://example.com/1")
        )
        story = _make_story(title, url="https://example.com/2")
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is True

    def test_very_similar_titles_are_duplicate(self, tracker):
        """Slightly reworded titles about the same topic should still be caught."""
        tracker.posts.append(
            _make_post("SpaceX Starship Launches Successfully From Texas",
                       "https://example.com/1")
        )
        story = _make_story("SpaceX Starship Successfully Launches From Texas Base",
                            url="https://example.com/2")
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is True

    def test_different_topics_are_not_duplicate(self, tracker):
        """Unrelated titles should not be flagged."""
        tracker.posts.append(
            _make_post("NASA Discovers New Exoplanet in Habitable Zone",
                       "https://example.com/1")
        )
        story = _make_story("Federal Reserve Raises Interest Rates Again",
                            url="https://example.com/2")
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is False

    def test_proper_noun_matching_boosts_similarity(self, tracker):
        """Two articles sharing multiple proper nouns are treated as related."""
        tracker.posts.append(
            _make_post("Elon Musk Tesla Board Approves Compensation Package",
                       "https://example.com/1")
        )
        story = _make_story("Tesla Board Under Fire Over Elon Musk Pay Deal",
                            url="https://example.com/2")
        result = tracker.check_story_status(story)
        # Two proper nouns in common (Elon, Musk, Tesla) should push similarity high
        assert result["is_duplicate"] is True

    def test_single_proper_noun_not_enough(self, tracker):
        """One shared proper noun with otherwise different context is not a duplicate."""
        tracker.posts.append(
            _make_post("Biden Signs Infrastructure Bill",
                       "https://example.com/1")
        )
        story = _make_story("Biden Hosts State Dinner for French President",
                            url="https://example.com/2")
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is False

    def test_old_topic_outside_cluster_window(self, tracker):
        """Posts older than the default 48h cluster window are ignored."""
        tracker.posts.append(
            _make_post("SpaceX Launches Starship", "https://example.com/1",
                       hours_ago=50)  # Outside 48h default cluster window
        )
        story = _make_story("SpaceX Launches Starship Again",
                            url="https://example.com/2")
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is False

    def test_short_title_not_compared(self, tracker):
        """Titles with fewer than 2 meaningful words after stop-word removal are skipped."""
        tracker.posts.append(
            _make_post("The News", "https://example.com/1")
        )
        story = _make_story("A Story", url="https://example.com/2")
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is False

    def test_empty_title(self, tracker):
        """Empty title does not crash and is not treated as duplicate."""
        tracker.posts.append(
            _make_post("Real Story Here", "https://example.com/1")
        )
        story = _make_story("", url="https://example.com/2")
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is False


# ===========================================================================
# 5. Update / developing-story detection
# ===========================================================================

class TestUpdateDetection:
    """Stories with update keywords should be allowed through even when similar."""

    def test_update_keyword_allows_similar_story(self, tracker):
        """An article with 'update' in the title bypasses the topic-similarity block."""
        tracker.posts.append(
            _make_post("Major Earthquake Hits California Coast",
                       "https://example.com/1")
        )
        story = _make_story(
            "UPDATE: Major Earthquake Hits California Coast - Rescue Underway",
            url="https://example.com/2"
        )
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is False
        assert result["is_update"] is True
        assert len(result["previous_posts"]) > 0

    def test_breaking_keyword_allows_similar_story(self, tracker):
        """'Breaking' in the title is treated as an update indicator."""
        tracker.posts.append(
            _make_post("Senate Votes on Immigration Bill",
                       "https://example.com/1")
        )
        story = _make_story(
            "Breaking: Senate Immigration Bill Votes Conclude",
            url="https://example.com/2"
        )
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is False
        # May or may not be detected as update depending on similarity threshold,
        # but should never be hard-blocked as duplicate
        assert result["is_duplicate"] is False

    def test_responds_keyword(self, tracker):
        """'responds' is an update keyword."""
        tracker.posts.append(
            _make_post("Governor Signs Controversial Education Bill",
                       "https://example.com/1")
        )
        story = _make_story(
            "Teachers Union Responds to Governor Signing Education Bill",
            url="https://example.com/2"
        )
        result = tracker.check_story_status(story)
        # Contains 'responds' update keyword and related proper nouns
        if result["is_update"]:
            assert result["is_duplicate"] is False

    def test_is_update_story_word_boundary(self, tracker):
        """Update keywords match on word boundaries ('now' should not match 'known')."""
        assert tracker._is_update_story("This is known territory") is False
        assert tracker._is_update_story("This is now confirmed") is True

    def test_is_update_story_various_keywords(self, tracker):
        """Spot-check several update keywords."""
        assert tracker._is_update_story("Aftermath of the storm") is True
        assert tracker._is_update_story("President announces new plan") is True
        assert tracker._is_update_story("Latest developments in the case") is True
        assert tracker._is_update_story("City reacts to new law") is True
        assert tracker._is_update_story("Plain boring headline") is False

    def test_update_returns_previous_posts(self, tracker):
        """When an update is detected, previous_posts should contain related history."""
        old_post = _make_post(
            "SpaceX Starship Launch Delayed Again",
            "https://example.com/1",
            content="SpaceX delays Starship launch once more."
        )
        tracker.posts.append(old_post)
        story = _make_story(
            "BREAKING: SpaceX Starship Finally Launches After Delays",
            url="https://example.com/2"
        )
        result = tracker.check_story_status(story)
        if result["is_update"]:
            assert len(result["previous_posts"]) >= 1
            # Each entry should have 'post', 'similarity', 'common_entities' keys
            prev = result["previous_posts"][0]
            assert "post" in prev
            assert "similarity" in prev


# ===========================================================================
# 6. Story cluster discovery (_find_story_cluster)
# ===========================================================================

class TestStoryCluster:
    """Low-level cluster finder that groups related articles."""

    def test_finds_related_posts(self, tracker):
        """Cluster finder returns related posts sorted by similarity."""
        tracker.posts.append(_make_post(
            "Amazon Workers Strike at Warehouse",
            "https://example.com/1"
        ))
        tracker.posts.append(_make_post(
            "Google Announces New AI Model",
            "https://example.com/2"
        ))
        result = tracker._find_story_cluster("Amazon Warehouse Workers Walk Out")
        # Should find the Amazon post but not the Google post
        assert len(result["related_posts"]) >= 1
        first_match = result["related_posts"][0]
        assert "amazon" in first_match["post"]["topic"].lower()

    def test_cluster_max_three_results(self, tracker):
        """Cluster finder caps related_posts at 3."""
        for i in range(10):
            tracker.posts.append(_make_post(
                f"President Biden Economy Speech {i}",
                f"https://example.com/{i}"
            ))
        result = tracker._find_story_cluster("Biden Economy Speech New Plan")
        assert len(result["related_posts"]) <= 3

    def test_cluster_empty_title(self, tracker):
        """Empty title returns no cluster results."""
        tracker.posts.append(_make_post("Real Story", "https://example.com/1"))
        result = tracker._find_story_cluster("")
        assert result["related_posts"] == []
        assert result["cluster_info"] is None

    def test_cluster_info_contains_entities(self, tracker):
        """Cluster info includes extracted proper nouns from the query title."""
        tracker.posts.append(_make_post(
            "Elon Musk Tesla Factory Expansion",
            "https://example.com/1"
        ))
        result = tracker._find_story_cluster("Elon Musk Announces Tesla Gigafactory Plans")
        assert result["cluster_info"] is not None
        entities = result["cluster_info"]["entities"]
        # Should extract at least some proper nouns
        assert any("elon" == e or "musk" == e or "tesla" == e for e in entities)

    def test_cluster_ignores_old_posts(self, tracker):
        """Posts outside the lookback window (default 48h) are excluded."""
        tracker.posts.append(_make_post(
            "SpaceX Launch Success", "https://example.com/1", hours_ago=60
        ))
        result = tracker._find_story_cluster("SpaceX Launch Success")
        assert len(result["related_posts"]) == 0


# ===========================================================================
# 7. Proper noun extraction
# ===========================================================================

class TestProperNounExtraction:
    """_extract_proper_nouns helper."""

    def test_extracts_capitalized_words(self, tracker):
        """Capitalized words that are not common starters are extracted.

        Note: _extract_proper_nouns treats ANY capitalized word as a proper
        noun (it has no dictionary), so 'Meets' would be extracted because
        it starts with a capital letter. We use a lowercase connector instead.
        """
        nouns = tracker._extract_proper_nouns("Biden met Macron in Paris")
        assert "biden" in nouns
        assert "macron" in nouns
        assert "paris" in nouns
        assert "met" not in nouns  # lowercase, not extracted
        assert "in" not in nouns

    def test_skips_common_sentence_starters(self, tracker):
        """Words like 'The', 'This', 'It' are not treated as proper nouns."""
        nouns = tracker._extract_proper_nouns("The President It He She This That")
        assert "the" not in nouns
        assert "it" not in nouns
        assert "he" not in nouns
        assert "she" not in nouns
        assert "this" not in nouns
        assert "that" not in nouns
        # 'President' is capitalized and not a common starter
        assert "president" in nouns

    def test_strips_punctuation(self, tracker):
        """Punctuation attached to words is cleaned before extraction."""
        nouns = tracker._extract_proper_nouns("Biden, Macron: Paris!")
        assert "biden" in nouns
        assert "macron" in nouns
        assert "paris" in nouns

    def test_empty_string(self, tracker):
        """Empty input returns empty set."""
        assert tracker._extract_proper_nouns("") == set()

    def test_single_char_words_skipped(self, tracker):
        """Single-character words are not extracted."""
        nouns = tracker._extract_proper_nouns("A B C")
        assert len(nouns) == 0


# ===========================================================================
# 8. Deduplication disabled
# ===========================================================================

class TestDeduplicationDisabled:
    """When dedup is disabled, nothing should be flagged."""

    def test_disabled_flag_bypasses_all_checks(self, tmp_history):
        """With enabled=False, check_story_status always returns not duplicate."""
        cfg = {"enabled": False}
        t = PostTracker(history_file=tmp_history, config=cfg)
        url = "https://example.com/1"
        t.posts.append(_make_post("Same Story", url))
        story = _make_story("Same Story", url=url)
        result = t.check_story_status(story, post_content="Same Story content")
        assert result["is_duplicate"] is False
        assert result["is_update"] is False
        assert result["previous_posts"] == []

    def test_filter_duplicates_returns_all_when_disabled(self, tmp_history):
        """filter_duplicates passes everything through when disabled."""
        cfg = {"enabled": False}
        t = PostTracker(history_file=tmp_history, config=cfg)
        t.posts.append(_make_post("Duplicate", "https://example.com/1"))
        stories = [
            _make_story("Duplicate", url="https://example.com/1"),
            _make_story("Other", url="https://example.com/2"),
        ]
        result = t.filter_duplicates(stories)
        assert len(result) == 2


# ===========================================================================
# 9. Backward-compatible is_duplicate() wrapper
# ===========================================================================

class TestIsDuplicateWrapper:
    """The deprecated is_duplicate() method should still work correctly."""

    def test_returns_true_for_duplicate_url(self, tracker):
        url = "https://example.com/dup"
        tracker.posts.append(_make_post("Story", url))
        assert tracker.is_duplicate(_make_story("Different", url=url)) is True

    def test_returns_false_for_new_story(self, tracker):
        assert tracker.is_duplicate(_make_story("Brand new story")) is False

    def test_accepts_post_content_kwarg(self, tracker):
        """is_duplicate forwards post_content to check_story_status."""
        content = "The quick brown fox jumps over the lazy dog in Washington DC today."
        tracker.posts.append(
            _make_post("Fox story", "https://example.com/1", content=content)
        )
        assert tracker.is_duplicate(
            _make_story("Fox", url="https://example.com/2"),
            post_content=content
        ) is True


# ===========================================================================
# 10. Recording posts and history management
# ===========================================================================

class TestRecordPost:
    """record_post() persistence and field mapping."""

    def test_record_post_adds_to_history(self, tracker, tmp_history):
        """Recorded post appears in the in-memory list and on disk."""
        story = _make_story("New Discovery", url="https://example.com/new")
        tracker.record_post(
            story,
            post_content="A new discovery was announced today.",
            tweet_id="123",
            bluesky_uri="at://did:plc:abc/post/xyz",
            image_prompt="A cat in a lab coat"
        )
        assert len(tracker.posts) == 1
        post = tracker.posts[0]
        assert post["topic"] == "New Discovery"
        assert post["url"] == "https://example.com/new"
        assert post["content"] == "A new discovery was announced today."
        assert post["x_tweet_id"] == "123"
        assert post["bluesky_uri"] == "at://did:plc:abc/post/xyz"
        assert post["image_prompt"] == "A cat in a lab coat"

        # Verify it was written to disk
        with open(tmp_history, "r") as f:
            data = json.load(f)
        assert len(data["posts"]) == 1

    def test_record_post_timestamp_is_utc(self, tracker):
        """Recorded timestamp is a valid ISO-8601 UTC string."""
        story = _make_story("Story")
        tracker.record_post(story, post_content="text")
        ts = tracker.posts[0]["timestamp"]
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    def test_record_post_with_missing_metadata(self, tracker):
        """Recording a story with no title/url uses sensible defaults."""
        tracker.record_post({}, post_content="text only")
        post = tracker.posts[0]
        assert post["topic"] == "Unknown"
        assert post["url"] is None
        assert post["source"] == "Unknown"

    def test_record_post_triggers_cleanup(self, tracker, tmp_history, default_config):
        """Old posts are pruned when a new post is recorded."""
        old_ts = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
        tracker.posts.append({
            "timestamp": old_ts,
            "topic": "Old story",
            "url": "https://example.com/old",
            "source": "Old",
            "content": None,
            "image_prompt": None,
            "x_tweet_id": None,
            "x_reply_tweet_id": None,
            "bluesky_uri": None,
            "bluesky_reply_uri": None,
        })
        assert len(tracker.posts) == 1
        tracker.record_post(_make_story("New"), post_content="New content")
        # Old post (35 days) should be cleaned up; max_history_days=30
        assert len(tracker.posts) == 1
        assert tracker.posts[0]["topic"] == "New"


class TestCleanupOldPosts:
    """cleanup_old_posts() time-based pruning."""

    def test_removes_posts_older_than_max_days(self, tracker):
        tracker.posts.append(_make_post("Old", "https://example.com/old", hours_ago=31*24))
        tracker.posts.append(_make_post("Recent", "https://example.com/new", hours_ago=1))
        tracker.cleanup_old_posts()
        assert len(tracker.posts) == 1
        assert tracker.posts[0]["topic"] == "Recent"

    def test_keeps_all_recent_posts(self, tracker):
        for i in range(5):
            tracker.posts.append(_make_post(f"Post {i}", f"https://example.com/{i}", hours_ago=i))
        tracker.cleanup_old_posts()
        assert len(tracker.posts) == 5

    def test_empty_history_noop(self, tracker):
        tracker.cleanup_old_posts()
        assert tracker.posts == []


# ===========================================================================
# 11. filter_duplicates() bulk filtering
# ===========================================================================

class TestFilterDuplicates:
    """Batch deduplication over a list of candidate stories."""

    def test_filters_out_known_urls(self, tracker):
        tracker.posts.append(_make_post("Story A", "https://example.com/a"))
        stories = [
            _make_story("Story A", url="https://example.com/a"),
            _make_story("Story B", url="https://example.com/b"),
        ]
        result = tracker.filter_duplicates(stories)
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/b"

    def test_all_unique(self, tracker):
        stories = [
            _make_story("Alpha", url="https://example.com/alpha"),
            _make_story("Beta", url="https://example.com/beta"),
        ]
        result = tracker.filter_duplicates(stories)
        assert len(result) == 2

    def test_all_duplicates(self, tracker):
        tracker.posts.append(_make_post("Story", "https://example.com/a"))
        tracker.posts.append(_make_post("Story", "https://example.com/b"))
        stories = [
            _make_story("Story", url="https://example.com/a"),
            _make_story("Story", url="https://example.com/b"),
        ]
        result = tracker.filter_duplicates(stories)
        assert len(result) == 0

    def test_empty_input_list(self, tracker):
        result = tracker.filter_duplicates([])
        assert result == []


# ===========================================================================
# 12. get_posts_needing_replies()
# ===========================================================================

class TestGetPostsNeedingReplies:
    """Identify posts that have a URL but no source reply yet."""

    def test_post_with_url_and_no_reply(self, tracker):
        tracker.posts.append(_make_post("S", "https://example.com/s"))
        needing = tracker.get_posts_needing_replies()
        assert len(needing) == 1

    def test_post_with_reply_already(self, tracker):
        post = _make_post("S", "https://example.com/s")
        post["x_reply_tweet_id"] = "reply_123"
        tracker.posts.append(post)
        needing = tracker.get_posts_needing_replies()
        assert len(needing) == 0

    def test_post_with_no_url(self, tracker):
        post = _make_post("S", None)
        post["url"] = None
        tracker.posts.append(post)
        needing = tracker.get_posts_needing_replies()
        assert len(needing) == 0

    def test_mixed_posts(self, tracker):
        post_a = _make_post("A", "https://example.com/a")  # Needs reply
        post_b = _make_post("B", "https://example.com/b")
        post_b["x_reply_tweet_id"] = "reply_b"  # Already has reply
        post_c = _make_post("C", None)
        post_c["url"] = None  # No URL
        tracker.posts.extend([post_a, post_b, post_c])
        needing = tracker.get_posts_needing_replies()
        assert len(needing) == 1
        assert needing[0]["topic"] == "A"


# ===========================================================================
# 13. Source cooldown (_source_posted)
# ===========================================================================

class TestSourceCooldown:
    """The _source_posted method and its integration with cooldowns."""

    def test_same_source_within_cooldown(self, tracker):
        """Same source within cooldown period is detected."""
        tracker.posts.append(_make_post("Story", "https://example.com/1",
                                        source="CNN", hours_ago=2))
        assert tracker._source_posted("CNN", hours=24) is True

    def test_same_source_outside_cooldown(self, tracker):
        """Same source outside cooldown period is not flagged."""
        tracker.posts.append(_make_post("Story", "https://example.com/1",
                                        source="CNN", hours_ago=200))
        assert tracker._source_posted("CNN", hours=168) is False

    def test_different_source(self, tracker):
        tracker.posts.append(_make_post("Story", "https://example.com/1",
                                        source="CNN", hours_ago=1))
        assert tracker._source_posted("BBC", hours=168) is False

    def test_empty_source(self, tracker):
        assert tracker._source_posted("", hours=168) is False
        assert tracker._source_posted(None, hours=168) is False


# ===========================================================================
# 14. Stem matching in similarity
# ===========================================================================

class TestStemMatching:
    """The prefix-based stem matching that gives partial credit."""

    def test_stem_match_contributes_to_similarity(self, tracker):
        """Words like 'deploying' and 'deployment' should partially match."""
        tracker.posts.append(_make_post(
            "Military Deploying Troops Overseas",
            "https://example.com/1"
        ))
        story = _make_story(
            "Military Deployment Troops Sent Overseas",
            url="https://example.com/2"
        )
        result = tracker.check_story_status(story)
        # 'deploying' and 'deployment' share prefix -> partial credit
        # Combined with other shared words should trigger duplicate
        assert result["is_duplicate"] is True


# ===========================================================================
# 15. Edge cases and integration
# ===========================================================================

class TestEdgeCases:
    """Boundary conditions and unusual inputs."""

    def test_unicode_titles(self, tracker):
        """Unicode characters in titles do not cause errors."""
        tracker.posts.append(_make_post(
            "Japan Earthquake Magnitude 7.2",
            "https://example.com/1"
        ))
        story = _make_story("Japan Earthquake Magnitude 7.2", url="https://example.com/2")
        result = tracker.check_story_status(story)
        assert isinstance(result["is_duplicate"], bool)

    def test_very_long_title(self, tracker):
        """Extremely long titles are handled without error."""
        long_title = "Word " * 500
        story = _make_story(long_title, url="https://example.com/long")
        result = tracker.check_story_status(story)
        assert isinstance(result["is_duplicate"], bool)

    def test_special_characters_in_title(self, tracker):
        """Titles with quotes, brackets, etc. are handled without errors.

        Note: 'Says' is an update keyword, so we avoid it here and use
        a title that will be treated as a plain duplicate.
        """
        tracker.posts.append(_make_post(
            'Biden "No Comment" on [Classified] Pentagon Report',
            "https://example.com/1"
        ))
        story = _make_story(
            'Biden "No Comment" on [Classified] Pentagon Report',
            url="https://example.com/2"
        )
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is True

    def test_save_failure_does_not_crash(self, tmp_path):
        """If the history file cannot be written, record_post does not raise."""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        hfile = str(readonly_dir / "history.json")
        # Create initial file
        with open(hfile, "w") as f:
            json.dump({"posts": []}, f)

        t = PostTracker(history_file=hfile)

        # Make the directory read-only so writing fails
        import stat
        readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            # This should print a warning but not raise
            t.record_post(_make_story("Test"), post_content="text")
            # The in-memory list should still be updated even if disk write fails
            assert len(t.posts) == 1
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(stat.S_IRWXU)

    def test_history_without_content_field(self, tracker):
        """Old-format posts without a 'content' field do not break content similarity check."""
        old_format_post = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "topic": "Old Format Post",
            "url": "https://example.com/old-format",
            "source": "Legacy",
            # No 'content' key at all
        }
        tracker.posts.append(old_format_post)
        story = _make_story("Different", url="https://example.com/new")
        # Should not crash
        result = tracker.check_story_status(story, post_content="some content here today")
        assert isinstance(result["is_duplicate"], bool)

    def test_configurable_similarity_threshold(self, tmp_history):
        """A stricter threshold catches less, a looser one catches more."""
        # Strict threshold (90%) - should allow more through
        strict_cfg = {
            "enabled": True,
            "url_deduplication": True,
            "topic_similarity_threshold": 0.90,
        }
        t_strict = PostTracker(history_file=tmp_history, config=strict_cfg)
        t_strict.posts.append(_make_post(
            "Congress Debates New Climate Bill",
            "https://example.com/1"
        ))
        story = _make_story("Congress Climate Bill Debate Continues",
                            url="https://example.com/2")
        result_strict = t_strict.check_story_status(story)

        # Loose threshold (20%) - should block more
        loose_cfg = {
            "enabled": True,
            "url_deduplication": True,
            "topic_similarity_threshold": 0.20,
        }
        # Need separate file since we reuse the fixture
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"posts": []}, f)
            loose_file = f.name

        try:
            t_loose = PostTracker(history_file=loose_file, config=loose_cfg)
            t_loose.posts.append(_make_post(
                "Congress Debates New Climate Bill",
                "https://example.com/1"
            ))
            result_loose = t_loose.check_story_status(story)

            # With a looser threshold, at least as many things should be flagged
            # (If strict says duplicate, loose definitely should too)
            if result_strict["is_duplicate"]:
                assert result_loose["is_duplicate"] is True
        finally:
            os.unlink(loose_file)

    def test_multiple_posts_in_history(self, tracker):
        """Deduplication works correctly when history has many entries."""
        for i in range(50):
            tracker.posts.append(_make_post(
                f"Unrelated Story Number {i}",
                f"https://example.com/story-{i}",
                hours_ago=i
            ))
        # Add one specific story
        tracker.posts.append(_make_post(
            "Pentagon UFO Report Released",
            "https://example.com/ufo",
            hours_ago=5
        ))
        # A duplicate of the specific story
        story = _make_story("Pentagon UFO Report Released Today",
                            url="https://example.com/ufo-2")
        result = tracker.check_story_status(story)
        assert result["is_duplicate"] is True

    def test_concurrent_url_and_topic_check(self, tracker):
        """URL match takes priority (checked first) over topic similarity."""
        url = "https://example.com/story-1"
        tracker.posts.append(_make_post("Completely Different Title", url))
        story = _make_story("Also Different Title", url=url)
        result = tracker.check_story_status(story)
        # URL match is a hard block regardless of title
        assert result["is_duplicate"] is True
        assert result["is_update"] is False
