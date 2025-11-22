"""
Filter posts_history.json to only @mewscast bot posts

Usage: python scripts/filter_history.py
(Run from repository root)
"""
import json
import os

# Construct path to posts_history.json (in repo root)
history_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'posts_history.json')

# Load current history
with open(history_path, 'r') as f:
    data = json.load(f)

# Filter to only posts with 📰↓ indicator (mewscast bot posts)
bot_posts = [post for post in data['posts'] if '📰↓' in post.get('content', '')]

print(f"Before filtering: {len(data['posts'])} posts")
print(f"After filtering: {len(bot_posts)} posts (with 📰↓)")

# Save filtered history
data['posts'] = bot_posts
with open(history_path, 'w') as f:
    json.dump(data, f, indent=2)

print(f"\n✅ Filtered history saved to {history_path}")
