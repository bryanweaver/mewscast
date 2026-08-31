# STATUS.md — Dead Files Cleanup PR

This document records what was shipped and what was refused in the dead-files cleanup PR.

## Shipped

### Deleted Files (confirmed zero live references)

**Dead JSON at repo root:**
- `outlet_reply_history.json` — orphaned after X outlet reply disabled
- `x_engagement_history.json` — no Python readers
- `x_scrape_result.json` — no Python readers

**Dead modules in src/:**
- `src/vocab_report.py` — standalone diagnostic, never imported

**Dead scripts:**
- `scripts/analytics.py` — replaced by `scripts/track_analytics.py`
- `scripts/filter_history.py` — one-shot cleanup, never automated
- `scripts/generate_og_image.py` — one-shot image generation, never automated
- `scripts/prep_signature.py` — one-shot signature prep, never automated
- `scripts/preview_watermark.py` — local preview tool, never automated
- `scripts/backfill_thumbnails.py` — one-shot backfill, never automated

### README Corrections (404/ghost removals only)

- Removed `src/positive_news_post.py` (never existed)
- Removed `src/vocab_report.py` (deleted)
- Removed `scripts/analytics.py` and `scripts/filter_history.py` (deleted)
- Removed ghost test files `test_outlet_reply.py` and `test_x_engagement.py` (never existed)

### Supporting Files Added

- `AGENTS.md` — do-not-add rules for coding agents
- `docs/STATUS.md` — this file
- `tests/test_dead_files_cleanup.py` — tests proving the claim

### Config/Gitignore Cleanup

- Removed comment referencing deleted `outlet_reply_history.json` from `config.yaml`
- Removed gitignore entry for `preview_watermark/` (script deleted)

## Refused (out of scope)

1. **Bluesky engagement duplicate** — `bluesky-engage.yml` and `engage-cats-bluesky.yml` both exist; deduplicating them was out of scope for this cleanup.

2. **Adding pytest to CI** — No new pytest GitHub Actions job was added. Tests run locally via `pytest tests/`.

3. **ContentGenerator removal** — `src/content_generator.py` is used by tests and possibly downstream; not part of this dead-files claim.

4. **Action SHA-pinning of untouched YAML** — Only edited files that needed changes. Did not SHA-pin actions in workflows that weren't otherwise modified.

5. **pyproject.toml / uv / FastAPI** — Repository uses `requirements.txt`; no new package managers or frameworks added.

6. **README inventory gold-plating (reviewer bounce)** — The following were attempted but reverted per review feedback (claim is "404s gone", not "README must list all live files"):
   - Adding missing workflows to README (`post-pin-explainer.yml`, `seed-history-images.yml`, `test-dedup.yml`, `x-cat-repost.yml`, `x-mention-reply.yml`)
   - Adding missing tests to README table (`test_watermark.py`, `test_x_cat_repost.py`, `test_x_mention_reply.py`, `test_dead_files_cleanup.py`)
   - Updating README test file count from 21 to 23
   - Enforcing README workflow-list or test-table completeness invariants in tests
