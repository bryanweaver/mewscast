"""Filter posts_history.json to only @mewscast bot posts"""
import json

# Load current history
with open('posts_history.json', 'r') as f:
    data = json.load(f)

# Filter to only posts with 📰↓ indicator (mewscast bot posts)
bot_posts = [post for post in data['posts'] if '📰↓' in post.get('content', '')]

print(f"Before filtering: {len(data['posts'])} posts")
print(f"After filtering: {len(bot_posts)} posts (with 📰↓)")

# Save filtered history
data['posts'] = bot_posts
with open('posts_history.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f"\n✅ Filtered history saved to posts_history.json")
