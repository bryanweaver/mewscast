# Dossier images — Cloudflare R2 migration

## Why

`docs/dossiers/images/` was committed to git. With ~200 PNGs at 5–6 MB each,
the working tree had ballooned past 1 GB and `.git` past 1.2 GB. PNGs don't
delta-compress, so every new image added its full size to history. This
migration moves the canonical store of dossier images to a Cloudflare R2
bucket served at `images.mewscast.us`. The local file under
`docs/dossiers/images/` is still written (the X/Bluesky media-upload paths
need a real file) but is no longer tracked by git.

## What landed in code

- `src/r2_uploader.py` — fail-soft R2 upload + URL helper.
- `src/main.py::_persist_dossier_image` — uploads to R2 right after the local copy.
- `src/dossier_renderer.py` — `<img src>` and OG/Twitter meta now use `public_image_url()`.
- `scripts/upload_dossier_images_to_r2.py` — one-shot seed of every existing PNG.
- `scripts/rewrite_dossier_html_image_urls.py` — one-shot rewrite of the 150 existing HTMLs.
- `.gitignore` — adds `docs/dossiers/images/`.
- `requirements.txt` — adds `boto3`.
- `.github/workflows/journalism-{publish,dry-run,republish}.yml` — pass `R2_*` env vars.

`public_image_url()` is **fail-safe**: if `R2_IMAGE_BASE_URL` is unset, it
falls back to the legacy `https://mewscast.us/dossiers/images/X.png` form.
So the renderer keeps working at every step of the cutover.

## Manual steps (in order)

### 1. Create R2 bucket
- Cloudflare dashboard → R2 → **Create bucket** → name `mewscast-dossier-images`.
- Settings → **Public access** → enable.
- Settings → **Custom domains** → add `images.mewscast.us`. Cloudflare will
  create the CNAME automatically if the zone is already in your account.

### 2. Generate R2 API token
- R2 → **Manage R2 API Tokens** → **Create API token**.
- Permissions: **Object Read & Write**, scoped to `mewscast-dossier-images`.
- Note the access key ID, secret access key, and account-level endpoint URL
  (`https://<accountid>.r2.cloudflarestorage.com`).

### 3. Add the secrets to GitHub
Repo → Settings → Secrets and variables → Actions → **New repository secret**:
- `R2_ENDPOINT_URL`  → `https://<accountid>.r2.cloudflarestorage.com`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`        → `mewscast-dossier-images`
- `R2_IMAGE_BASE_URL` → `https://images.mewscast.us`

### 4. Seed the bucket from your laptop
Put the same five values in `.env`, then:
```
pip install boto3
python scripts/upload_dossier_images_to_r2.py --dry-run   # sanity check
python scripts/upload_dossier_images_to_r2.py             # real upload
```
~200 files, ~1 GB. Expect a few minutes on a normal home connection.

Spot-check one URL in a browser:
`https://images.mewscast.us/2026-06-09-house-passes-bill-to-e8bb867d3a.png`

### 5. Rewrite the existing HTML files
```
R2_IMAGE_BASE_URL=https://images.mewscast.us \
    python scripts/rewrite_dossier_html_image_urls.py --dry-run
R2_IMAGE_BASE_URL=https://images.mewscast.us \
    python scripts/rewrite_dossier_html_image_urls.py
```
This edits 150 files in place. Diff them and commit on the
`chore/images-to-r2` branch.

### 6. Untrack the images directory
The `.gitignore` rule alone doesn't untrack already-tracked files.
```
git rm -r --cached docs/dossiers/images/
git commit -m "chore(images): untrack docs/dossiers/images (now in R2)"
```
Working-tree size drops by ~1 GB on the next clean clone. (The local copy
stays on disk because it's still written at publish time — git just stops
caring about it.)

### 7. Merge to main
Open a PR from `chore/images-to-r2` → `main`. Once merged, the next
journalism-publish run uploads to R2 and emits the new URLs automatically.

### 8. (Optional) Reclaim `.git` history
After main has the new world for ~a week and nothing has regressed:
```
git filter-repo --path docs/dossiers/images/ --invert-paths
git push --force origin main
```
**This is destructive — rewrites history, invalidates other clones, breaks
PRs that touch images.** Coordinate first. If you skip this, `.git` keeps
the old 1.2 GB but the working tree stays small forever — that's the
acceptable middle ground.

## Cost sanity check

R2: storage $0.015/GB-month, **zero** egress. At 200 PNGs × ~6 MB = 1.2 GB,
storage costs ~$0.018/month. Even at 10x growth this is < $1/year.
