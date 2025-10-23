"""
Cat community engagement automation
Finds and follows cat accounts, likes cat posts
"""
import os
import random
import json
from datetime import datetime, timedelta
from pathlib import Path
from twitter_bot import TwitterBot


class EngagementBot:
    """Automates engagement with cat community on X"""

    def __init__(self):
        """Initialize engagement bot"""
        self.bot = TwitterBot()
        self.engagement_log_path = Path(__file__).parent.parent / "engagement_history.json"
        self.engagement_history = self._load_engagement_history()

    def _load_engagement_history(self) -> dict:
        """Load engagement history to avoid duplicates"""
        if self.engagement_log_path.exists():
            with open(self.engagement_log_path, 'r') as f:
                return json.load(f)
        return {
            'followed_users': [],
            'liked_tweets': [],
            'last_cleanup': datetime.now().isoformat()
        }

    def _save_engagement_history(self):
        """Save engagement history"""
        with open(self.engagement_log_path, 'w') as f:
            json.dump(self.engagement_history, f, indent=2)
        print(f"✓ Saved engagement history")

    def _cleanup_old_history(self):
        """Remove entries older than 90 days to keep file manageable"""
        last_cleanup = datetime.fromisoformat(self.engagement_history.get('last_cleanup', datetime.now().isoformat()))

        # Only cleanup once per week
        if datetime.now() - last_cleanup < timedelta(days=7):
            return

        print("🧹 Cleaning up old engagement history...")
        cutoff_date = datetime.now() - timedelta(days=90)

        # Keep only recent follows (with timestamps)
        if self.engagement_history.get('followed_users'):
            original_count = len(self.engagement_history['followed_users'])
            self.engagement_history['followed_users'] = [
                entry for entry in self.engagement_history['followed_users']
                if datetime.fromisoformat(entry.get('timestamp', datetime.now().isoformat())) > cutoff_date
            ]
            removed = original_count - len(self.engagement_history['followed_users'])
            if removed > 0:
                print(f"   Removed {removed} old follow records")

        # Keep only recent likes (with timestamps)
        if self.engagement_history.get('liked_tweets'):
            original_count = len(self.engagement_history['liked_tweets'])
            self.engagement_history['liked_tweets'] = [
                entry for entry in self.engagement_history['liked_tweets']
                if datetime.fromisoformat(entry.get('timestamp', datetime.now().isoformat())) > cutoff_date
            ]
            removed = original_count - len(self.engagement_history['liked_tweets'])
            if removed > 0:
                print(f"   Removed {removed} old like records")

        self.engagement_history['last_cleanup'] = datetime.now().isoformat()
        self._save_engagement_history()

    def find_and_follow_cat_account(self) -> bool:
        """
        Find and follow one cat-related account

        Returns:
            True if successfully followed, False otherwise
        """
        print("\n🐱 Searching for cat accounts to follow...")

        # Rotate through different cat-related search terms
        search_terms = [
            "cat owner -bot -spam",
            "cat dad -bot -spam",
            "cat mom -bot -spam",
            "cats -bot -spam lang:en",
            "kitty -bot -spam lang:en",
            "feline -bot -spam lang:en",
            "#catsoftwitter -bot -spam",
            "#catsofinstagram -bot -spam",
            "my cat -bot -spam lang:en"
        ]

        search_query = random.choice(search_terms)

        try:
            # Search for tweets from cat accounts
            response = self.bot.client.search_recent_tweets(
                query=search_query,
                max_results=10,
                tweet_fields=['author_id', 'public_metrics'],
                user_fields=['username', 'public_metrics', 'description', 'verified'],
                expansions=['author_id']
            )

            if not response.data:
                print(f"   No results for '{search_query}'")
                return False

            # Get user data from response
            users = {user.id: user for user in response.includes.get('users', [])}

            # Filter for quality accounts
            candidate_accounts = []
            for tweet in response.data:
                author_id = tweet.author_id
                user = users.get(author_id)

                if not user:
                    continue

                # Skip if already followed
                followed_ids = [entry['user_id'] for entry in self.engagement_history.get('followed_users', [])]
                if author_id in followed_ids:
                    continue

                # Filter criteria:
                # - Has reasonable follower count (100-100K to avoid bots and mega-accounts)
                # - Not verified (verified accounts less likely to follow back)
                # - Bio mentions cats
                followers = user.public_metrics['followers_count']
                following = user.public_metrics['following_count']
                bio = user.description.lower() if user.description else ""

                # Quality checks
                if followers < 100 or followers > 100000:
                    continue  # Too small (bot) or too big (won't follow back)

                if user.verified:
                    continue  # Verified accounts rarely follow back

                # Check if actually cat-related
                cat_keywords = ['cat', 'kitten', 'feline', 'meow', 'kitty', 'tabby']
                if not any(keyword in bio for keyword in cat_keywords):
                    continue

                # Prefer accounts with good follow ratio (not follow-spammers)
                follow_ratio = following / followers if followers > 0 else 999
                if follow_ratio > 5:  # Following way more than followers = spammer
                    continue

                candidate_accounts.append({
                    'user_id': author_id,
                    'username': user.username,
                    'followers': followers,
                    'bio': bio[:100]
                })

            if not candidate_accounts:
                print(f"   No quality cat accounts found in results")
                return False

            # Pick random account from candidates
            account = random.choice(candidate_accounts)

            print(f"\n👤 Following: @{account['username']}")
            print(f"   Followers: {account['followers']}")
            print(f"   Bio: {account['bio']}...")

            # Follow the account
            self.bot.client.follow_user(target_user_id=account['user_id'])

            # Log the follow
            self.engagement_history.setdefault('followed_users', []).append({
                'user_id': account['user_id'],
                'username': account['username'],
                'timestamp': datetime.now().isoformat()
            })
            self._save_engagement_history()

            print(f"✓ Followed @{account['username']}")
            return True

        except Exception as e:
            print(f"✗ Error finding/following cat account: {e}")
            return False

    def find_and_like_cat_post(self) -> bool:
        """
        Find and like one cat-related post

        Returns:
            True if successfully liked, False otherwise
        """
        print("\n🐱 Searching for cat posts to like...")

        # Rotate through different cat content search terms
        search_terms = [
            "cute cat -bot lang:en",
            "my cat -bot lang:en",
            "look at my cat -bot lang:en",
            "#catsoftwitter -bot",
            "#caturday -bot",
            "adopted a cat -bot lang:en",
            "cat doing -bot lang:en",
            "this cat -bot lang:en",
            "cat photo -bot lang:en"
        ]

        search_query = random.choice(search_terms)

        try:
            # Search for cat posts with some engagement
            response = self.bot.client.search_recent_tweets(
                query=search_query,
                max_results=10,
                tweet_fields=['author_id', 'public_metrics', 'created_at'],
                user_fields=['username'],
                expansions=['author_id']
            )

            if not response.data:
                print(f"   No results for '{search_query}'")
                return False

            # Get user data
            users = {user.id: user for user in response.includes.get('users', [])}

            # Filter for quality posts
            candidate_posts = []
            for tweet in response.data:
                # Skip if already liked
                liked_ids = [entry['tweet_id'] for entry in self.engagement_history.get('liked_tweets', [])]
                if tweet.id in liked_ids:
                    continue

                # Filter criteria:
                # - Has some engagement (10-10000 likes = quality but not mega-viral)
                # - Recent (within last 24 hours)
                likes = tweet.public_metrics['like_count']
                retweets = tweet.public_metrics['retweet_count']

                if likes < 5 or likes > 10000:
                    continue  # Too little engagement or mega-viral (already saturated)

                # Check recency
                created_at = tweet.created_at
                if datetime.now(created_at.tzinfo) - created_at > timedelta(hours=24):
                    continue  # Too old

                author = users.get(tweet.author_id)

                candidate_posts.append({
                    'tweet_id': tweet.id,
                    'author': author.username if author else 'unknown',
                    'text': tweet.text[:100],
                    'likes': likes,
                    'retweets': retweets
                })

            if not candidate_posts:
                print(f"   No quality cat posts found in results")
                return False

            # Pick random post from candidates
            post = random.choice(candidate_posts)

            print(f"\n❤️  Liking post from @{post['author']}")
            print(f"   Text: {post['text']}...")
            print(f"   Engagement: {post['likes']} likes, {post['retweets']} retweets")

            # Like the post
            self.bot.client.like(tweet_id=post['tweet_id'])

            # Log the like
            self.engagement_history.setdefault('liked_tweets', []).append({
                'tweet_id': post['tweet_id'],
                'author': post['author'],
                'timestamp': datetime.now().isoformat()
            })
            self._save_engagement_history()

            print(f"✓ Liked post from @{post['author']}")
            return True

        except Exception as e:
            print(f"✗ Error finding/liking cat post: {e}")
            return False

    def run_engagement_cycle(self):
        """
        Run one engagement cycle: follow 1 account, like 1 post
        This should be called every 30 minutes
        """
        print("\n" + "="*80)
        print("🐱 CAT COMMUNITY ENGAGEMENT CYCLE")
        print("="*80)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Cleanup old history periodically
        self._cleanup_old_history()

        # Track success
        follow_success = False
        like_success = False

        # Try to follow a cat account
        try:
            follow_success = self.find_and_follow_cat_account()
        except Exception as e:
            print(f"✗ Follow attempt failed: {e}")

        # Try to like a cat post
        try:
            like_success = self.find_and_like_cat_post()
        except Exception as e:
            print(f"✗ Like attempt failed: {e}")

        # Summary
        print("\n" + "="*80)
        print("ENGAGEMENT SUMMARY")
        print("="*80)
        print(f"✓ Followed: {1 if follow_success else 0} account")
        print(f"✓ Liked: {1 if like_success else 0} post")
        print(f"Total followed: {len(self.engagement_history.get('followed_users', []))} accounts")
        print(f"Total liked: {len(self.engagement_history.get('liked_tweets', []))} posts")
        print("="*80)

        return follow_success or like_success


if __name__ == "__main__":
    """Run engagement cycle when called directly"""
    bot = EngagementBot()
    bot.run_engagement_cycle()
