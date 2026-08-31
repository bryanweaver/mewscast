# AGENTS.md — Coding Agent Guidelines

This file defines constraints for AI coding agents working on this repository.

## Do-Not-Add List

The following patterns and tools are explicitly prohibited:

1. **No extra package managers** — Use `requirements.txt` only. Do not add `pyproject.toml`, `uv`, `poetry`, `pipenv`, or similar.

2. **No reusable-workflow libraries** — GitHub Actions workflows must remain self-contained. Do not extract shared actions into reusable workflow repositories.

3. **No live X/Bluesky API calls in tests** — All tests must run offline. Mock external API calls; do not make real posts or engagement actions during test runs.

4. **Do not disable journalism-publish** — The `journalism-publish.yml` workflow is the core publishing pipeline and must remain enabled and functional.

5. **Preserve src/ structure** — Do not reorganize `src/` into subpackages, add `__init__.py` files beyond what exists, or introduce new top-level directories.

## Repository Conventions

- Python 3.11+
- Dependencies: `requirements.txt` (no version pinning beyond what's already there)
- Test runner: `pytest tests/`
- Entry point: `python src/main.py`
- GitHub Actions for CI/CD

## Known Leftovers

- **Bluesky engagement duplicate** — `bluesky-engage.yml` and `engage-cats-bluesky.yml` both write `bluesky_engagement_history.json`. Do not disable either until a later claim picks a schema.
- **pytest not in CI** — pytest is used by `tests/` but is not in `requirements.txt` and there is no pytest GitHub Actions job. Missing CI is not a hold; do not add a pytest workflow without explicit instruction.
