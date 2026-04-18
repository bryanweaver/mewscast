"""Mewscast nightly analytics report - v2 with extended checks."""
import json
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load(name):
    with open(os.path.join(ROOT, name), "r", encoding="utf-8") as f:
        return json.load(f)

def parse_ts(s):
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None

NOW = datetime.now(timezone.utc)
CUTOFF_24H = NOW - timedelta(hours=24)
CUTOFF_7D = NOW - timedelta(days=7)
SIX_HOURS_AGO = NOW - timedelta(hours=6)

def latest_snapshot_total(snapshots):
    if not snapshots:
        return 0, 0, 0, 0
    s = snapshots[-1]
    likes = int(s.get("likes", 0) or 0)
    reposts = int(s.get("reposts", s.get("retweets", 0)) or 0)
    replies = int(s.get("replies", 0) or 0)
    impressions = int(s.get("impressions", 0) or 0)
    return likes, reposts, replies, impressions

def fmt_post_ref(pdoc):
    pipe = pdoc.get("post_pipeline") or "legacy"
    ptype = pdoc.get("post_type") or "-"
    src = pdoc.get("source", "?")
    topic = (pdoc.get("topic") or "").strip()
    if len(topic) > 80:
        topic = topic[:77] + "..."
    ts = pdoc.get("timestamp") or pdoc.get("posted_at") or "?"
    return f"[{pipe}/{ptype}] {src}: {topic} ({ts})"

def main():
    posts_doc = load("posts_history.json")
    posts = posts_doc["posts"]
    analytics = load("analytics_history.json")
    apost = analytics["posts"]
    fh = analytics["follower_history"]
    last_updated = parse_ts(analytics.get("last_updated"))

    lines = []
    P = lines.append

    # ---- window filters ----
    recent_posts = [p for p in posts if (parse_ts(p.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)) >= CUTOFF_24H]
    posts_7d = [p for p in posts if (parse_ts(p.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)) >= CUTOFF_7D]

    x_count_24h = sum(1 for p in recent_posts if p.get("x_tweet_id"))
    bsky_count_24h = sum(1 for p in recent_posts if p.get("bluesky_uri"))
    total_platform_posts = x_count_24h + bsky_count_24h

    # Engagement totals from latest snapshots for recent posts
    agg_likes = agg_reposts = agg_replies = agg_impr = 0
    per_post_engagement = []
    zero_engagement_flagged = []

    def record_entry(pdoc, key, platform, ts):
        nonlocal agg_likes, agg_reposts, agg_replies, agg_impr
        entry = apost.get(key)
        if entry:
            l, rp, rep, impr = latest_snapshot_total(entry.get("snapshots", []))
        else:
            l = rp = rep = impr = 0
        agg_likes += l; agg_reposts += rp; agg_replies += rep; agg_impr += impr
        per_post_engagement.append((l+rp+rep, l, rp, rep, impr, platform, pdoc, key))
        if (l + rp + rep) == 0 and ts and ts <= SIX_HOURS_AGO:
            zero_engagement_flagged.append((platform, pdoc, key))

    for p in recent_posts:
        ts = parse_ts(p.get("timestamp"))
        if p.get("x_tweet_id"):
            record_entry(p, f"x:{p['x_tweet_id']}", "x", ts)
        if p.get("bluesky_uri"):
            record_entry(p, p["bluesky_uri"], "bluesky", ts)

    # Follower deltas
    def latest_before(entries, cutoff):
        best = None
        for e in entries:
            t = parse_ts(e.get("timestamp"))
            if t and t <= cutoff:
                if best is None or parse_ts(best["timestamp"]) < t:
                    best = e
        return best

    x_latest = fh["x"][-1] if fh.get("x") else None
    bsky_latest = fh["bluesky"][-1] if fh.get("bluesky") else None
    x_prev_24h = latest_before(fh.get("x", []), CUTOFF_24H)
    bsky_prev_24h = latest_before(fh.get("bluesky", []), CUTOFF_24H)
    x_prev_7d = latest_before(fh.get("x", []), CUTOFF_7D)
    bsky_prev_7d = latest_before(fh.get("bluesky", []), CUTOFF_7D)

    def delta(cur, prev):
        if cur is None or prev is None:
            return None
        return cur.get("followers", 0) - prev.get("followers", 0)

    x_delta_24h = delta(x_latest, x_prev_24h)
    bsky_delta_24h = delta(bsky_latest, bsky_prev_24h)
    x_delta_7d = delta(x_latest, x_prev_7d)
    bsky_delta_7d = delta(bsky_latest, bsky_prev_7d)

    # ---- A/B ----
    pipeline_stats = {"legacy": [], "journalism": []}
    journalism_by_type = defaultdict(list)
    for p in posts:
        pipe = p.get("post_pipeline") or "legacy"
        ptype = p.get("post_type")
        l = rp = rep = impr = 0
        any_found = False
        for key in ([f"x:{p['x_tweet_id']}"] if p.get("x_tweet_id") else []) + ([p["bluesky_uri"]] if p.get("bluesky_uri") else []):
            e = apost.get(key)
            if e:
                any_found = True
                ll, rr, pr, ii = latest_snapshot_total(e.get("snapshots", []))
                l += ll; rp += rr; rep += pr; impr += ii
        if not any_found:
            continue
        rec = {"likes": l, "reposts": rp, "replies": rep, "impressions": impr, "engagement": l+rp+rep, "ts": p.get("timestamp"), "post": p}
        if pipe in pipeline_stats:
            pipeline_stats[pipe].append(rec)
        if pipe == "journalism" and ptype:
            journalism_by_type[ptype].append(rec)

    def avg(items, k):
        if not items: return 0.0
        return sum(x[k] for x in items) / len(items)

    rolling7 = {"legacy": [], "journalism": []}
    for pipe, items in pipeline_stats.items():
        for r in items:
            t = parse_ts(r["ts"])
            if t and t >= CUTOFF_7D:
                rolling7[pipe].append(r)

    # ---- META 24h ----
    meta_posts_24h = [p for p in recent_posts if (p.get("post_type") == "META")]

    # ---- Historical-window bug detection (broader than 24h only to surface real issues) ----
    bugs = []

    # Top-level staleness checks
    if not recent_posts:
        last_post_ts = max((parse_ts(p.get("timestamp")) for p in posts if parse_ts(p.get("timestamp"))), default=None)
        hours_since = round((NOW - last_post_ts).total_seconds() / 3600, 1) if last_post_ts else None
        bugs.append({"severity": "high", "type": "bot_silence",
                     "detail": f"No posts in last 24h. Last post was {last_post_ts.isoformat() if last_post_ts else 'unknown'} ({hours_since}h ago).",
                     "post": None, "open_issue": True})

    if last_updated:
        hours_stale = round((NOW - last_updated).total_seconds() / 3600, 1)
        if hours_stale > 25:
            bugs.append({"severity": "high", "type": "analytics_tracker_stale",
                         "detail": f"analytics_history.json last_updated is {last_updated.isoformat()} ({hours_stale}h ago). Analytics snapshots have not refreshed in >24h.",
                         "post": None, "open_issue": True})

    # Content checks on 7-day window (since 24h is empty)
    window_posts = recent_posts if recent_posts else posts_7d
    for p in window_posts:
        c = p.get("content") or ""
        if not c or len(c.strip()) < 20:
            bugs.append({"severity": "med", "type": "missing_or_short_content",
                         "detail": f"content length {len(c)}", "post": p, "open_issue": False})

    # Duplicates in 7-day
    url_counts = Counter(p.get("url") for p in window_posts if p.get("url"))
    for u, cnt in url_counts.items():
        if cnt > 1:
            bugs.append({"severity": "med", "type": "duplicate_article",
                         "detail": f"URL {u} posted {cnt} times", "post": None, "open_issue": False})

    for p in window_posts:
        x_ok = bool(p.get("x_tweet_id"))
        b_ok = bool(p.get("bluesky_uri"))
        if x_ok != b_ok:
            miss = "x" if not x_ok else "bluesky"
            bugs.append({"severity": "med", "type": "cross_platform_miss",
                         "detail": f"Missing on {miss}", "post": p, "open_issue": False})

    for platform, p, key in zero_engagement_flagged:
        bugs.append({"severity": "low", "type": "zero_engagement_6h",
                     "detail": f"{platform} post has 0 engagement after >6h (key={key})",
                     "post": p, "open_issue": False})

    # Formatting checks (window)
    for p in window_posts:
        c = p.get("content") or ""
        if "  " in c:
            bugs.append({"severity": "low", "type": "formatting_double_space",
                         "detail": "contains double spaces", "post": p, "open_issue": False})
        if c.count("(") != c.count(")"):
            bugs.append({"severity": "low", "type": "formatting_unbalanced_parens",
                         "detail": "unbalanced parentheses", "post": p, "open_issue": False})
        if c.count("\"") % 2 != 0:
            bugs.append({"severity": "low", "type": "formatting_unbalanced_quotes",
                         "detail": "unbalanced double quotes", "post": p, "open_issue": False})

    # Dedupe bugs
    seen = set()
    unique_bugs = []
    for b in bugs:
        sig = (b["type"], b["detail"])
        if sig in seen:
            continue
        seen.add(sig)
        unique_bugs.append(b)

    # ---- Render Report ----
    P("# Mewscast Nightly Report")
    P(f"_Generated: {NOW.isoformat()}_")
    P("")

    P("## Quick Stats")
    P(f"- Posts (last 24h): **{total_platform_posts}** (X: {x_count_24h}, Bluesky: {bsky_count_24h}) across {len(recent_posts)} unique stories")
    P(f"- Engagement (24h, latest snapshots): **{agg_likes} likes / {agg_reposts} reposts / {agg_replies} replies / {agg_impr} impressions**")
    P(f"- Follower delta (24h): X {x_delta_24h if x_delta_24h is not None else 'n/a'} | Bluesky {bsky_delta_24h if bsky_delta_24h is not None else 'n/a'}")
    P(f"- Follower delta (7d):  X {x_delta_7d if x_delta_7d is not None else 'n/a'} | Bluesky {bsky_delta_7d if bsky_delta_7d is not None else 'n/a'}")
    P(f"- Issues detected: **{len(unique_bugs)}** (high: {sum(1 for b in unique_bugs if b['severity']=='high')}, med: {sum(1 for b in unique_bugs if b['severity']=='med')}, low: {sum(1 for b in unique_bugs if b['severity']=='low')})")
    P(f"- META posts (24h): **{len(meta_posts_24h)}**")
    P("")

    P("## 1. Daily Performance Summary")
    if not recent_posts:
        last_post_ts = max((parse_ts(p.get("timestamp")) for p in posts if parse_ts(p.get("timestamp"))), default=None)
        hours_since = round((NOW - last_post_ts).total_seconds() / 3600, 1) if last_post_ts else None
        P(f"⚠️ **No posts in the last 24 hours.** Last post was at {last_post_ts.isoformat() if last_post_ts else 'unknown'} ({hours_since}h ago).")
        P("")
        # Show last 5 posts before cutoff for context
        sorted_posts = sorted(posts, key=lambda x: parse_ts(x.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        P("**Last 5 posts (for context):**")
        for p in sorted_posts[:5]:
            P(f"- {fmt_post_ref(p)}")
        P("")
    else:
        P(f"**Posts in last 24h:** {total_platform_posts} total — X: {x_count_24h}, Bluesky: {bsky_count_24h} ({len(recent_posts)} unique stories)")
        P(f"**Total engagement (latest snapshots):** {agg_likes} likes, {agg_reposts} reposts, {agg_replies} replies, {agg_impr} impressions")
        P("")
        ranked = sorted(per_post_engagement, key=lambda x: x[0], reverse=True)
        P("**Top 3 performing posts:**")
        for i, (e, l, rp, rep, impr, plat, pdoc, key) in enumerate(ranked[:3], 1):
            P(f"{i}. [{plat}] eng={e} (L:{l} R:{rp} Re:{rep} Impr:{impr}) — {fmt_post_ref(pdoc)}")
        P("")
        P("**Bottom 3 performing posts:**")
        for i, (e, l, rp, rep, impr, plat, pdoc, key) in enumerate(ranked[-3:][::-1], 1):
            P(f"{i}. [{plat}] eng={e} (L:{l} R:{rp} Re:{rep} Impr:{impr}) — {fmt_post_ref(pdoc)}")
        P("")

    P("**Follower counts:**")
    if x_latest:
        P(f"- X: {x_latest.get('followers')} followers, following {x_latest.get('following','?')} (24h delta: {x_delta_24h if x_delta_24h is not None else 'n/a'}, 7d delta: {x_delta_7d if x_delta_7d is not None else 'n/a'})")
    if bsky_latest:
        P(f"- Bluesky: {bsky_latest.get('followers')} followers, following {bsky_latest.get('following','?')} (24h delta: {bsky_delta_24h if bsky_delta_24h is not None else 'n/a'}, 7d delta: {bsky_delta_7d if bsky_delta_7d is not None else 'n/a'})")
    if last_updated:
        hours_stale = round((NOW - last_updated).total_seconds() / 3600, 1)
        P(f"- Analytics last_updated: {last_updated.isoformat()} ({hours_stale}h ago)")
    P("")
    P(f"**Zero-engagement posts older than 6h (in window):** {len(zero_engagement_flagged)}")
    for platform, p, key in zero_engagement_flagged[:10]:
        P(f"- [{platform}] {fmt_post_ref(p)}")
    P("")

    P("## 2. A/B Test: Legacy vs Journalism Pipeline (all time)")
    for pipe in ("legacy", "journalism"):
        items = pipeline_stats[pipe]
        n = len(items)
        if n == 0:
            P(f"**{pipe}:** no posts with analytics data"); continue
        P(f"**{pipe}** — {n} posts with analytics: "
          f"avg likes={avg(items,'likes'):.2f}, reposts={avg(items,'reposts'):.2f}, "
          f"replies={avg(items,'replies'):.2f}, impressions={avg(items,'impressions'):.2f}, "
          f"total-engagement={avg(items,'engagement'):.2f}")
    P("")
    if journalism_by_type:
        P("**Journalism pipeline breakdown by post_type:**")
        for t, items in sorted(journalism_by_type.items()):
            n = len(items)
            P(f"- {t} ({n} posts): avg likes={avg(items,'likes'):.2f}, reposts={avg(items,'reposts'):.2f}, "
              f"replies={avg(items,'replies'):.2f}, impressions={avg(items,'impressions'):.2f}, total-eng={avg(items,'engagement'):.2f}")
    else:
        P("_No journalism-pipeline posts with post_type found._")
    P("")
    P("**Rolling 7-day trend:**")
    for pipe in ("legacy", "journalism"):
        items = rolling7[pipe]
        n = len(items)
        if n == 0:
            P(f"- {pipe}: 0 posts in last 7d")
        else:
            P(f"- {pipe}: {n} posts — avg likes={avg(items,'likes'):.2f}, reposts={avg(items,'reposts'):.2f}, "
              f"replies={avg(items,'replies'):.2f}, impressions={avg(items,'impressions'):.2f}, total-eng={avg(items,'engagement'):.2f}")
    P("")
    populated_pipe = sum(1 for p in posts if p.get("post_pipeline"))
    populated_type = sum(1 for p in posts if p.get("post_type"))
    P(f"_Note: post_pipeline populated on {populated_pipe}/{len(posts)} posts. post_type populated on {populated_type}/{len(posts)} posts (only journalism-pipeline posts carry post_type)._")
    P("")

    P("## 3. META Post Quality Audit (last 24h)")
    if not meta_posts_24h:
        P("_No META posts in the last 24 hours._")
    else:
        for p in meta_posts_24h:
            P(f"- {fmt_post_ref(p)}")
            P(f"  - Content: {(p.get('content') or '')[:400]}")
            P(f"  - Source article: {p.get('url')}")
            P(f"  - Rating: NEEDS_REVIEW (automated tone/accuracy review not included in this run)")
    P("")

    P("## 4. Bug & Improvement Detection")
    if not unique_bugs:
        P("_No issues detected._")
    else:
        high = [b for b in unique_bugs if b['severity'] == 'high']
        med = [b for b in unique_bugs if b['severity'] == 'med']
        low = [b for b in unique_bugs if b['severity'] == 'low']
        for label, group in (("High severity", high), ("Medium severity", med), ("Low severity", low)):
            if not group: continue
            P(f"**{label} ({len(group)}):**")
            for b in group:
                ref = ""
                if b["post"]:
                    ref = " — " + fmt_post_ref(b["post"])
                P(f"- [{b['type']}] {b['detail']}{ref}")
            P("")

    # Save bugs metadata for later gh issue creation
    issue_payload = [b for b in unique_bugs if b.get("open_issue")]

    # Write dated report to docs/reports/ for public site
    reports_dir = os.path.join(ROOT, "docs", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    date_slug = NOW.strftime("%Y-%m-%d")
    dated_path = os.path.join(reports_dir, f"{date_slug}.md")
    report_text = "\n".join(lines)

    with open(dated_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"WROTE {dated_path}")

    # Also write latest.md as a stable link target
    latest_path = os.path.join(reports_dir, "latest.md")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    # Write issues JSON
    issues_path = os.path.join(reports_dir, f"{date_slug}-issues.json")
    with open(issues_path, "w", encoding="utf-8") as f:
        json.dump(issue_payload, f, indent=2, default=str)

    # Rebuild the reports index page
    _rebuild_reports_index(reports_dir)

    print(report_text)


def _rebuild_reports_index(reports_dir):
    """Generate docs/reports/index.html listing all nightly reports."""
    import glob
    import html as html_mod

    md_files = sorted(glob.glob(os.path.join(reports_dir, "2*-*-*.md")), reverse=True)

    rows = []
    for path in md_files:
        fname = os.path.basename(path)
        date_str = fname.replace(".md", "")
        # Read first few lines to extract quick stats
        with open(path, "r", encoding="utf-8") as f:
            content = f.read(2000)
        # Extract quick stats line
        summary = ""
        for line in content.split("\n"):
            if line.startswith("- Posts (last 24h):"):
                summary = html_mod.escape(line.lstrip("- "))
                break
        safe_date = html_mod.escape(date_str)
        safe_fname = html_mod.escape(fname)
        rows.append(f'<tr><td><a href="./{safe_fname}">{safe_date}</a></td><td>{summary}</td></tr>')

    rows_html = "\n".join(rows) if rows else '<tr><td colspan="2">No reports yet.</td></tr>'

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nightly Reports — Walter Croncat</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      background: #0d1117;
      color: #e6edf3;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      padding: 2rem;
    }}
    .container {{ max-width: 800px; margin: 0 auto; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; }}
    .subtitle {{ color: #8b949e; margin-bottom: 2rem; }}
    a {{ color: #58a6ff; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 0.75rem 1rem; border-bottom: 1px solid #21262d; }}
    th {{ color: #8b949e; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; }}
    tr:hover {{ background: #161b22; }}
    .back {{ display: inline-block; margin-bottom: 1.5rem; color: #8b949e; }}
    .back:hover {{ color: #58a6ff; }}
  </style>
</head>
<body>
<div class="container">
  <a class="back" href="../">&larr; Back to Walter Croncat</a>
  <h1>Nightly Reports</h1>
  <p class="subtitle">Daily operational reports — posting stats, engagement metrics, pipeline health, and bug detection. Transparency FTW.</p>
  <table>
    <thead><tr><th>Date</th><th>Summary</th></tr></thead>
    <tbody>
{rows_html}
    </tbody>
  </table>
</div>
</body>
</html>"""

    with open(os.path.join(reports_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"WROTE {os.path.join(reports_dir, 'index.html')}")

if __name__ == "__main__":
    main()
