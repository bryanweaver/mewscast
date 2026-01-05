"""
Bluesky engagement script - likes posts that mention @mewscast.bsky.social
"""
import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from dotenv import load_dotenv


def main():
    """Like posts that mention us on Bluesky"""
    print(f"\n{'='*60}")
    print(f"Bluesky Engagement - Auto-like Mentions")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}\n")

    # Load environment variables
    load_dotenv()

    try:
        from bluesky_bot import BlueskyBot

        # Load history to get previously liked URIs
        history_path = Path(__file__).parent.parent / 'bluesky_engagement_history.json'

        if history_path.exists():
            with open(history_path, 'r') as f:
                history = json.load(f)
        else:
            history = {}

        # Ensure required keys exist
        if 'sessions' not in history:
            history['sessions'] = []
        if 'liked_uris' not in history:
            history['liked_uris'] = []

        # Also pull URIs from existing liked_posts if present (old format)
        if 'liked_posts' in history:
            for post in history['liked_posts']:
                if 'uri' in post and post['uri'] not in history['liked_uris']:
                    history['liked_uris'].append(post['uri'])

        # Build cache of already-liked URIs
        liked_cache = set(history.get('liked_uris', []))
        print(f"📚 Loaded {len(liked_cache)} previously liked URIs from cache")

        print("🦋 Connecting to Bluesky...")
        bot = BlueskyBot()

        print("📬 Checking notifications for mentions...")
        result = bot.like_mentions(limit=50, liked_cache=liked_cache)

        print(f"\n{'='*60}")
        print(f"✅ Engagement complete: {result['liked']} new posts liked")
        print(f"{'='*60}\n")

        # Update history
        history['sessions'].append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'liked': result['liked'],
            'skipped': result['skipped'],
            'already_cached': result.get('already_cached', 0)
        })

        # Add newly liked URIs to cache
        history['liked_uris'].extend(result.get('liked_uris', []))

        # Dedupe URIs
        history['liked_uris'] = list(set(history['liked_uris']))

        # Keep only last 90 days of sessions
        cutoff = datetime.now(timezone.utc).timestamp() - (90 * 24 * 60 * 60)
        history['sessions'] = [
            s for s in history['sessions']
            if datetime.fromisoformat(s['timestamp'].replace('Z', '+00:00')).timestamp() > cutoff
        ]

        # Keep only last 1000 liked URIs (to prevent file bloat)
        if len(history['liked_uris']) > 1000:
            history['liked_uris'] = history['liked_uris'][-1000:]

        with open(history_path, 'w') as f:
            json.dump(history, f, indent=2)

        return True

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print(f"{'='*60}\n")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
