"""
Tests for the dossier_renderer module — HTML output validation, XSS escaping,
copyright protection (no article bodies in output), and edge cases.
"""
import copy
import json
import os
import sys

import pytest

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dossier_renderer import render_dossier_page, render_index_page


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_dossier():
    """Load the mock dossier JSON from the dossiers/ directory."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mock_path = os.path.join(project_root, "dossiers", "20260408-senate-approps-mock.json")
    with open(mock_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRenderDossierPage:

    def test_render_dossier_page_produces_valid_html(self, mock_dossier):
        """Output should be a well-formed HTML document."""
        output = render_dossier_page(mock_dossier)
        assert "<!DOCTYPE html>" in output
        assert "<html" in output
        assert "</html>" in output
        assert "<head>" in output
        assert "</head>" in output
        assert "<body>" in output
        assert "</body>" in output

    def test_all_sections_present(self, mock_dossier):
        """All 6 sections should be present: 3 rendered + 3 coming-soon."""
        output = render_dossier_page(mock_dossier)
        assert "The Post" in output
        assert "What Walter Read" in output
        assert "Meta-Analysis Brief" in output
        # Three coming-soon placeholders
        assert "Coming Soon" in output
        assert "Verification Gate Results" in output
        assert "Draft Analysis" in output
        assert "Story Selection" in output

    def test_xss_escaping(self, mock_dossier):
        """Injected <script> tags must be HTML-escaped in output."""
        xss_data = copy.deepcopy(mock_dossier)
        xss_data["dossier"]["headline_seed"] = '<script>alert(\'xss\')</script>'
        output = render_dossier_page(xss_data)
        # Raw <script> must NOT appear
        assert "<script>" not in output
        assert "alert('xss')" not in output
        # Escaped form MUST appear
        assert "&lt;script&gt;" in output

    def test_no_article_body_in_output(self, mock_dossier):
        """Article body text must NEVER appear in HTML output — only metadata."""
        output = render_dossier_page(mock_dossier)
        for article in mock_dossier["dossier"]["articles"]:
            body = article.get("body", "")
            if body and len(body) > 100:
                # Check multiple substrings of the body
                body_chunk_1 = body[50:150]
                body_chunk_2 = body[100:200]
                assert body_chunk_1 not in output, (
                    f"Article body text from {article['outlet']} leaked into HTML"
                )
                assert body_chunk_2 not in output, (
                    f"Article body text from {article['outlet']} leaked into HTML (chunk 2)"
                )

    def test_post_type_badges(self, mock_dossier):
        """Each post type should get the correct badge CSS class."""
        post_types_and_classes = [
            ("REPORT", "badge-report"),
            ("META", "badge-meta"),
            ("ANALYSIS", "badge-analysis"),
            ("BULLETIN", "badge-bulletin"),
            ("CORRECTION", "badge-correction"),
            ("PRIMARY", "badge-primary"),
        ]
        for post_type, expected_class in post_types_and_classes:
            data = copy.deepcopy(mock_dossier)
            data["post"]["draft"]["post_type"] = post_type
            output = render_dossier_page(data)
            assert expected_class in output, (
                f"Post type {post_type} did not produce class {expected_class}"
            )

    def test_missing_optional_fields(self, mock_dossier):
        """Rendering should not crash when optional fields are null/empty."""
        data = copy.deepcopy(mock_dossier)
        # Null post_url (already null in mock, but be explicit)
        data["post"]["post_url"] = None
        # Empty primary sources
        data["dossier"]["primary_sources"] = []
        # Empty hedges_used
        data["post"]["draft"]["hedges_used"] = []
        # Remove optional brief fields
        data["brief"]["missing_context"] = []
        data["brief"]["primary_source_alignment"] = []
        data["brief"]["disagreements"] = []
        # Should not raise
        output = render_dossier_page(data)
        assert "<!DOCTYPE html>" in output

    def test_og_meta_tags(self, mock_dossier):
        """Open Graph meta tags should be present."""
        output = render_dossier_page(mock_dossier)
        assert 'og:title' in output
        assert 'og:description' in output
        assert 'og:type' in output
        assert 'content="article"' in output

    def test_confidence_bar(self, mock_dossier):
        """Confidence score should render as a visual bar."""
        output = render_dossier_page(mock_dossier)
        assert "confidence-bar" in output
        assert "85%" in output  # 0.85 * 100 = 85

    def test_stylesheet_link(self, mock_dossier):
        """Should link to style.css via relative path."""
        output = render_dossier_page(mock_dossier)
        assert './style.css' in output

    def test_char_count_present(self, mock_dossier):
        """Character count of article bodies should appear in output."""
        output = render_dossier_page(mock_dossier)
        # The mock articles have body text, so character counts should appear
        assert "characters fetched" in output


class TestRenderIndexPage:

    def test_render_index_page_with_entries(self, mock_dossier):
        """Index page with 2 entries should render both."""
        entry1 = copy.deepcopy(mock_dossier)
        entry2 = copy.deepcopy(mock_dossier)
        entry2["story_id"] = "20260409-house-vote-mock"
        entry2["dossier"]["headline_seed"] = "House passes infrastructure bill"
        entry2["post"]["published_at"] = "2026-04-09T14:00:00+00:00"

        output = render_index_page([entry1, entry2])
        assert "<!DOCTYPE html>" in output
        assert "Senate passes appropriations" in output
        assert "House passes infrastructure bill" in output
        # Both should have links
        assert "20260408-senate-approps-mock.html" in output
        assert "20260409-house-vote-mock.html" in output

    def test_render_index_page_empty(self, mock_dossier):
        """Empty index should render without crashing."""
        output = render_index_page([])
        assert "<!DOCTYPE html>" in output
        assert "No dossiers have been published yet" in output

    def test_index_page_sorted_newest_first(self, mock_dossier):
        """Entries should be sorted newest first."""
        entry1 = copy.deepcopy(mock_dossier)
        entry1["post"]["published_at"] = "2026-04-08T10:00:00+00:00"
        entry1["dossier"]["headline_seed"] = "Older story"

        entry2 = copy.deepcopy(mock_dossier)
        entry2["story_id"] = "20260409-newer"
        entry2["post"]["published_at"] = "2026-04-09T10:00:00+00:00"
        entry2["dossier"]["headline_seed"] = "Newer story"

        output = render_index_page([entry1, entry2])
        # Newer should appear before older
        newer_pos = output.index("Newer story")
        older_pos = output.index("Older story")
        assert newer_pos < older_pos, "Entries should be sorted newest first"
