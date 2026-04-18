"""
Unit tests for _compose_dossier_reply_text in src/main.py.

Covers the template branches — disagreements, missing_context, multi-
framing, generic fallback — and edge cases (empty brief, outlet_count
below 2).
"""
import pytest


# Heavy module mocking (tweepy, atproto, anthropic, content_generator)
# is done once in tests/conftest.py before any test module is collected.
# main.py is imported lazily inside fixtures so its module-level state
# doesn't leak into other test files' fixtures (seen under pytest 9.x:
# importing main.py at test-module import time poisons test_outlet_reply's
# bot fixture with "Cannot spec a Mock object" in the shared session).

@pytest.fixture(scope="module")
def _main_module():
    import main as _m
    return _m


@pytest.fixture
def compose(_main_module):
    return _main_module._compose_dossier_reply_text


@pytest.fixture
def inline_meta(_main_module):
    return _main_module._inline_dossier_url_into_meta


class TestComposeDossierReplyText:
    def test_disagreements_branch(self, compose):
        brief = {"disagreements": [{"claim": "x"}]}
        out = compose(brief, 5)
        assert "5 outlets" in out
        assert "diverge" in out
        assert out.endswith(":")

    def test_missing_context_branch(self, compose):
        brief = {"missing_context": ["the subsidy detail nobody mentioned"]}
        out = compose(brief, 4)
        assert "4 outlets" in out
        assert "left out" in out

    def test_multi_framing_branch(self, compose):
        brief = {"framing_analysis": {"a": "x", "b": "y", "c": "z"}}
        out = compose(brief, 3)
        assert "framings" in out or "framing" in out
        assert "3" in out

    def test_generic_fallback_no_signals(self, compose):
        out = compose({}, 2)
        assert "cross-outlet" in out.lower()
        # Generic branch doesn't name a count
        assert "outlets" not in out or "dossier" in out.lower()

    def test_none_brief_falls_back_to_generic(self, compose):
        out = compose(None, 0)
        assert "dossier" in out.lower()

    def test_single_outlet_phrasing_is_plural_neutral(self, compose):
        # outlet_count=1 should not produce "1 outlets"
        out = compose({"disagreements": [1]}, 1)
        assert "1 outlets" not in out
        assert "these outlets" in out

    def test_multi_framing_uses_framing_count_when_outlet_count_small(self, compose):
        # outlet_count=0 but framing has 3 entries — use framing count
        brief = {"framing_analysis": {"a": "x", "b": "y", "c": "z"}}
        out = compose(brief, 0)
        assert "3" in out

    def test_disagreements_precedence_over_missing_context(self, compose):
        brief = {
            "disagreements": [{"claim": "x"}],
            "missing_context": ["y"],
            "framing_analysis": {"a": "b", "c": "d", "e": "f"},
        }
        out = compose(brief, 5)
        assert "diverge" in out

    def test_inline_meta_inserts_url_before_signoff(self, inline_meta):
        """META posts inline the dossier URL before the sign-off so the
        sign-off remains the final line (Cronkite-seal invariant) and X
        renders the URL as a card preview."""
        text = (
            "COVERAGE REPORT — four stories most outlets missed together\n\n"
            "{body paragraphs}\n\n"
            "And that's the mews — coverage report."
        )
        sign_off = "And that's the mews — coverage report."
        url = "https://mewscast.us/dossiers/2026-04-18-example.html"

        out = inline_meta(text, url, sign_off)

        assert out.endswith(sign_off), "sign-off must be the final line"
        assert url in out, "URL must be present"
        # URL should appear before the sign-off in the output
        assert out.index(url) < out.index(sign_off)
        # And the body before the URL should be preserved intact
        assert "COVERAGE REPORT" in out
        assert "{body paragraphs}" in out

    def test_inline_meta_handles_missing_signoff(self, inline_meta):
        """Defensive fallback: if the draft doesn't end with the expected
        sign-off, the URL is appended to the end rather than the logic
        crashing. (Shouldn't happen in practice — gate enforces sign-off —
        but belt-and-suspenders.)"""
        text = "Some META-ish body without the sign-off"
        url = "https://mewscast.us/dossiers/foo.html"

        out = inline_meta(text, url, "And that's the mews — coverage report.")

        assert url in out
        assert out.strip().endswith(url)

    def test_inline_meta_handles_none_signoff(self, inline_meta):
        """Hypothetical: called with sign_off=None (caller couldn't resolve
        it). Should still produce a valid post with the URL appended."""
        text = "META body"
        url = "https://mewscast.us/dossiers/bar.html"

        out = inline_meta(text, url, None)

        assert url in out
        assert "META body" in out

    def test_length_leaves_room_for_url(self, compose):
        # Reply body is hook + "\n" + URL (~50 chars). X tweet limit 280.
        # Hook should be under ~240 to stay safe.
        for brief in [
            {"disagreements": [1]},
            {"missing_context": ["x"]},
            {"framing_analysis": {"a": "1", "b": "2", "c": "3"}},
            {},
        ]:
            out = compose(brief, 99)  # worst-case big count
            assert len(out) <= 240, f"hook too long ({len(out)}): {out}"
