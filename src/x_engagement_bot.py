"""
Cat community engagement automation for X/Twitter.
Finds and follows cat accounts, likes cat posts, quote-reposts cat-rescue
posts, and replies to cute kitten posts.

Per-cycle actions (each runs once per cycle, 3 cycles/day):
  - find_and_follow_cat_account      — search + quality filters + ratio gate
  - find_and_like_cat_post           — search + auto-follow author
  - find_and_quote_repost_rescue     — quote-retweet rescue/adoption posts
  - find_and_reply_cute_kitten       — reply with short emoji message

Safety invariants preserved across platforms:
  - Follow ratio safety check before any follow (target <2.5:1)
  - Auto-follow post authors when no cat account was found via search
  - 90-day history cleanup (weekly cadence)
  - One action per type per cycle (structurally enforced)

API usage: Pay-per-use (default as of Feb 2026). All endpoints used
(search_recent_tweets, like, follow_user, create_tweet) are billable per
call. Rough envelope: ~$0.06/cycle × 3 cycles/day ≈ $5.50/month. Set a
hard spending cap in the X developer portal before running live.
"""
import random
import json
from datetime import datetime, timedelta
from pathlib import Path
from twitter_bot import TwitterBot

CAT_KEYWORDS = ['cat', 'kitten', 'feline', 'meow', 'kitty', 'tabby', 'cats', 'kittens']

# Follow ratio safety threshold: don't let following:followers exceed this
FOLLOW_RATIO_LIMIT = 2.5
# Bootstrap limit when account has 0 followers
BOOTSTRAP_FOLLOW_LIMIT = 50


class XEngagementBot:
    """Automates engagement with cat community on X/Twitter"""

    def __init__(self):
        self.bot = TwitterBot()
        self.engagement_log_path = Path(__file__).parent.parent / "x_engagement_history.json"
        self.engagement_history = self._load_engagement_history()

    def _load_engagement_history(self) -> dict:
        """Load engagement history to avoid duplicates"""
        if self.engagement_log_path.exists():
            with open(self.engagement_log_path, 'r') as f:
                return json.load(f)
        return {
            'followed_users': [],
            'liked_tweets': [],
            'reposted_tweets': [],
            'replied_tweets': [],
            'last_cleanup': datetime.now().isoformat()
        }

    def _save_engagement_history(self):
        """Save engagement history"""
        with open(self.engagement_log_path, 'w') as f:
            json.dump(self.engagement_history, f, indent=2)
        print("✓ Saved X engagement history")

    def _cleanup_old_history(self):
        """Remove entries older than 90 days to keep file manageable"""
        last_cleanup = datetime.fromisoformat(
            self.engagement_history.get('last_cleanup', datetime.now().isoformat())
        )

        # Only cleanup once per week
        if datetime.now() - last_cleanup < timedelta(days=7):
            return

        print("🧹 Cleaning up old X engagement history...")
        cutoff_date = datetime.now() - timedelta(days=90)

        for key in ('followed_users', 'liked_tweets', 'reposted_tweets', 'replied_tweets'):
            if self.engagement_history.get(key):
                original_count = len(self.engagement_history[key])
                self.engagement_history[key] = [
                    entry for entry in self.engagement_history[key]
                    if datetime.fromisoformat(entry.get('timestamp', '2000-01-01T00:00:00')) > cutoff_date
                ]
                removed = original_count - len(self.engagement_history[key])
                if removed > 0:
                    print(f"   Removed {removed} old {key} records")

        self.engagement_history['last_cleanup'] = datetime.now().isoformat()
        self._save_engagement_history()

    def _check_follow_ratio_safe(self) -> bool:
        """
        Check if our follow ratio is safe before following more accounts.

        Returns:
            True if safe to follow, False if ratio too high
        """
        try:
            response = self.bot.client.get_me(user_fields=['public_metrics'])
            if not response.data:
                print("✗ Could not retrieve account metrics")
                return False

            metrics = response.data.public_metrics
            my_followers = metrics['followers_count']
            my_following = metrics['following_count']

            if my_followers == 0:
                # Bootstrap: allow limited follows to get started
                if my_following >= BOOTSTRAP_FOLLOW_LIMIT:
                    print(f"⚠️  Have 0 followers and already following {my_following} accounts.")
                    print("   Pausing follows until people follow back.")
                    return False
                return True

            ratio = my_following / my_followers

            if ratio > FOLLOW_RATIO_LIMIT:
                print(f"⚠️  Follow ratio too high: {ratio:.1f}:1 (following {my_following}, followers {my_followers})")
                print(f"   Pausing follows until more people follow back (target: <{FOLLOW_RATIO_LIMIT}:1)")
                return False

            print(f"✓ Follow ratio healthy: {ratio:.1f}:1 (following {my_following}, followers {my_followers})")
            return True

        except Exception as e:
            print(f"✗ Could not check follow ratio: {e}")
            # Err on the side of caution
            return False

    def _follow_account(self, user_id: str, username: str) -> bool:
        """
        Follow an account and record it in engagement history.

        Args:
            user_id: The X user ID to follow
            username: The username (for logging)

        Returns:
            True if successfully followed, False otherwise
        """
        try:
            self.bot.client.follow_user(target_user_id=user_id)

            self.engagement_history.setdefault('followed_users', []).append({
                'user_id': user_id,
                'username': username,
                'timestamp': datetime.now().isoformat()
            })
            self._save_engagement_history()

            print(f"✓ Followed @{username}")
            return True
        except Exception as e:
            print(f"✗ Could not follow @{username}: {e}")
            return False

    def find_and_follow_cat_account(self) -> bool:
        """
        Find and follow one cat-related account on X.

        Returns:
            True if successfully followed, False otherwise
        """
        print("\n🐱 Searching for cat accounts to follow on X...")

        # SAFETY CHECK: Verify our follow ratio is healthy before following
        if not self._check_follow_ratio_safe():
            print("   → Skipping follow attempt (ratio check failed)")
            return False

        search_terms = [
            "cat owner -bot -spam",
            "cat dad -bot -spam",
            "cat mom -bot -spam",
            "cats -bot -spam lang:en",
            "kitty -bot -spam lang:en",
            "feline -bot -spam lang:en",
            "#catsoftwitter -bot -spam",
            "#caturday -bot",
            "my cat -bot lang:en",
            "cat lover -bot lang:en"
        ]

        search_query = random.choice(search_terms)

        try:
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

            users = {user.id: user for user in response.includes.get('users', [])}
            followed_ids = {entry['user_id'] for entry in self.engagement_history.get('followed_users', [])}

            candidate_accounts = []
            seen_ids = set()

            for tweet in response.data:
                user = users.get(tweet.author_id)
                if not user:
                    continue

                # Skip if already followed or duplicate in this result set
                if tweet.author_id in followed_ids or tweet.author_id in seen_ids:
                    continue
                seen_ids.add(tweet.author_id)

                followers = user.public_metrics['followers_count']
                following = user.public_metrics['following_count']
                bio = user.description.lower() if user.description else ""

                # Quality checks:
                # - Reasonable follower count (100-100K) — avoids bots and mega-accounts
                # - Not verified (verified accounts rarely follow back)
                # - Bio mentions cats
                if followers < 100 or followers > 100000:
                    continue
                if user.verified:
                    continue
                if not any(keyword in bio for keyword in CAT_KEYWORDS):
                    continue

                # Prefer accounts with good follow ratio (not follow-spammers)
                follow_ratio = following / followers if followers > 0 else 999
                if follow_ratio > 5:
                    continue

                candidate_accounts.append({
                    'user_id': tweet.author_id,
                    'username': user.username,
                    'followers': followers,
                    'bio': bio[:100]
                })

            if not candidate_accounts:
                print("   No quality cat accounts found in results")
                return False

            account = random.choice(candidate_accounts)

            print(f"\n👤 Following: @{account['username']}")
            print(f"   Followers: {account['followers']}")
            print(f"   Bio: {account['bio']}...")

            return self._follow_account(account['user_id'], account['username'])

        except Exception as e:
            print(f"✗ Error finding/following cat account on X: {e}")
            return False

    def find_and_like_cat_post(self, already_followed_account: bool = False) -> bool:
        """
        Find and like one cat-related post on X.

        Args:
            already_followed_account: Whether we already followed a cat account this cycle.
                Controls auto-follow behavior:
                - False → always try to follow the post author (guaranteed follow)
                - True  → only follow the post author if they pass quality checks

        Returns:
            True if successfully liked, False otherwise
        """
        print("\n🐱 Searching for cat posts to like on X...")

        search_terms = [
            "cute cat -bot lang:en",
            "my cat -bot lang:en",
            "look at my cat -bot lang:en",
            "#catsoftwitter -bot",
            "#caturday -bot",
            "adopted a cat -bot lang:en",
            "cat doing -bot lang:en",
            "this cat -bot lang:en",
            "cat photo -bot lang:en",
            "cats of twitter -bot lang:en"
        ]

        search_query = random.choice(search_terms)

        try:
            response = self.bot.client.search_recent_tweets(
                query=search_query,
                max_results=25,
                tweet_fields=['author_id', 'public_metrics', 'created_at'],
                user_fields=['username', 'public_metrics', 'description'],
                expansions=['author_id']
            )

            if not response.data:
                print(f"   No results for '{search_query}'")
                return False

            users = {user.id: user for user in response.includes.get('users', [])}
            liked_ids = {entry['tweet_id'] for entry in self.engagement_history.get('liked_tweets', [])}
            followed_ids = {entry['user_id'] for entry in self.engagement_history.get('followed_users', [])}

            candidate_posts = []
            for tweet in response.data:
                # Skip if already liked
                if tweet.id in liked_ids:
                    continue

                likes = tweet.public_metrics['like_count']

                # At least 1 like (real post) but not mega-viral (already saturated)
                if likes < 1 or likes > 10000:
                    continue

                # Must be recent (within last 48 hours — X API skews older)
                created_at = tweet.created_at
                if datetime.now(created_at.tzinfo) - created_at > timedelta(hours=48):
                    continue

                author = users.get(tweet.author_id)

                candidate_posts.append({
                    'tweet_id': tweet.id,
                    'author_id': tweet.author_id,
                    'author': author.username if author else 'unknown',
                    'author_obj': author,
                    'text': tweet.text[:100],
                    'likes': likes,
                    'retweets': tweet.public_metrics['retweet_count']
                })

            if not candidate_posts:
                print("   No quality cat posts found in results")
                return False

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

            # AUTO-FOLLOW: Follow the author of this liked post
            author = post['author_obj']
            if post['author_id'] and post['author_id'] not in followed_ids:
                if not already_followed_account:
                    # Didn't find a proper cat account via search — always follow post author
                    if not self._check_follow_ratio_safe():
                        print(f"   → Skipping auto-follow of @{post['author']} (ratio check failed)")
                    else:
                        print(f"\n👤 Auto-follow: @{post['author']} (no cat account found, following post author)")
                        self._follow_account(post['author_id'], post['author'])
                else:
                    # Already followed a cat account — use quality checks for bonus follow
                    should_follow = True

                    if author:
                        followers = author.public_metrics['followers_count']
                        following = author.public_metrics['following_count']

                        if followers < 100 or followers > 100000:
                            should_follow = False
                            print(f"   → Skipping bonus follow (followers: {followers})")
                        elif following > 0 and followers > 0:
                            follow_ratio = following / followers
                            if follow_ratio > 5:
                                should_follow = False
                                print(f"   → Skipping bonus follow (bad ratio: {follow_ratio:.1f})")

                    if should_follow:
                        if not self._check_follow_ratio_safe():
                            print(f"   → Skipping bonus follow of @{post['author']} (ratio check failed)")
                        else:
                            print(f"\n👤 Bonus follow: @{post['author']} (author of liked post)")
                            self._follow_account(post['author_id'], post['author'])

            return True

        except Exception as e:
            print(f"✗ Error finding/liking cat post on X: {e}")
            return False

    def find_and_quote_repost_rescue(self) -> bool:
        """
        Find a cat rescue/adoption post and quote-retweet it with a short
        message urging people to adopt, share, or help.

        Strategy:
          - Search for "cat rescue please share" style queries
          - Post must mention cat keywords AND rescue keywords
          - Quote-retweet with a short, warm call to action
          - Must be within 72 hours (rescue posts stay relevant longer)
          - Prefer higher-engagement candidates (more likely legitimate)

        Returns:
            True if successfully quote-reposted, False otherwise.
        """
        print("\n🐱 Searching for cat rescue posts to quote-repost on X...")

        search_terms = [
            "cat rescue please share -is:retweet lang:en",
            "cats need homes please share -is:retweet lang:en",
            "cat adoption help -is:retweet lang:en",
            "kitten rescue please share -is:retweet lang:en",
            "foster cats help -is:retweet lang:en",
            "adopt cat please -is:retweet lang:en",
            "cat shelter help share -is:retweet lang:en",
            "stray cats need home -is:retweet lang:en",
            "rescue kittens please -is:retweet lang:en",
            "cat needs forever home -is:retweet lang:en",
        ]

        search_query = random.choice(search_terms)

        try:
            response = self.bot.client.search_recent_tweets(
                query=search_query,
                max_results=25,
                tweet_fields=['author_id', 'public_metrics', 'created_at'],
                user_fields=['username'],
                expansions=['author_id'],
            )

            if not response.data:
                print(f"   No results for '{search_query}'")
                return False

            users = {user.id: user for user in response.includes.get('users', [])}
            reposted_ids = {
                entry['tweet_id']
                for entry in self.engagement_history.get('reposted_tweets', [])
            }

            rescue_keywords = [
                'need home', 'needs home', 'needs a home', 'need a home',
                'looking for home', 'looking for a home', 'needs foster',
                'need foster', 'adopt', 'rescue', 'rehome', 'shelter',
                'forever home', 'foster', 'stray', 'abandoned',
            ]
            cat_keywords = [
                'cat', 'cats', 'kitten', 'kittens', 'kitty', 'kitties', 'feline',
            ]

            candidate_posts = []
            for tweet in response.data:
                if tweet.id in reposted_ids:
                    continue

                author = users.get(tweet.author_id)
                if not author:
                    continue

                tweet_text = (tweet.text or '').lower()

                if not any(kw in tweet_text for kw in rescue_keywords):
                    continue
                if not any(kw in tweet_text for kw in cat_keywords):
                    continue

                created_at = tweet.created_at
                if datetime.now(created_at.tzinfo) - created_at > timedelta(hours=72):
                    continue

                likes = tweet.public_metrics['like_count']
                retweets = tweet.public_metrics['retweet_count']

                candidate_posts.append({
                    'tweet_id': tweet.id,
                    'author_id': tweet.author_id,
                    'author': author.username,
                    'text': tweet.text[:150] if tweet.text else '',
                    'likes': likes,
                    'retweets': retweets,
                })

            if not candidate_posts:
                print("   No qualifying cat rescue posts found")
                return False

            # Prefer candidates with more engagement (more likely legitimate)
            candidate_posts.sort(key=lambda p: p['likes'] + p['retweets'], reverse=True)
            post = candidate_posts[0]

            print(f"\n🔁 Quote-reposting rescue post from @{post['author']}")
            print(f"   Text: {post['text']}...")
            print(f"   Engagement: {post['likes']} likes, {post['retweets']} retweets")

            # Pick a short, warm quote message
            quote_messages = [
                "Every cat deserves a loving home 🐾 Please share and help if you can!",
                "Please consider adopting or sharing 🐱 These cats need our help!",
                "If you can't adopt, please share! Every repost helps 🐾",
                "Let's help these cats find their forever homes 🐱 Share, adopt, donate — every bit helps!",
                "Sharing because every cat deserves a chance 🐾 Please help spread the word!",
                "Adopt, foster, or share — any help makes a difference 🐱",
                "These babies need homes 🐾 Please share and help if you're able!",
                "Signal boosting for these cats in need 🐱 Adopt or share to help!",
            ]
            quote_text = random.choice(quote_messages)

            result = self.bot.quote_tweet(tweet_id=post['tweet_id'], text=quote_text)

            if not result:
                print("✗ Quote-repost failed")
                return False

            # Log the repost
            self.engagement_history.setdefault('reposted_tweets', []).append({
                'tweet_id': post['tweet_id'],
                'author': post['author'],
                'text': post['text'][:100],
                'quote_text': quote_text,
                'timestamp': datetime.now().isoformat(),
            })
            self._save_engagement_history()

            print(f"✓ Quote-reposted rescue post from @{post['author']}")
            return True

        except Exception as e:
            print(f"✗ Error finding/quote-reposting rescue post on X: {e}")
            return False

    def find_and_reply_cute_kitten(self) -> bool:
        """
        Find a cute kitten post and reply with a short, sweet message
        with cat/paw emoji for engagement.

        Returns:
            True if successfully replied, False otherwise.
        """
        print("\n🐱 Searching for cute kitten posts to reply to on X...")

        search_terms = [
            "cute kitten -is:retweet lang:en",
            "adorable kitten -is:retweet lang:en",
            "cute kittens -is:retweet lang:en",
            "little kitten -is:retweet lang:en",
            "baby kitten -is:retweet lang:en",
        ]

        search_query = random.choice(search_terms)

        try:
            response = self.bot.client.search_recent_tweets(
                query=search_query,
                max_results=25,
                tweet_fields=['author_id', 'public_metrics', 'created_at'],
                user_fields=['username'],
                expansions=['author_id'],
            )

            if not response.data:
                print(f"   No results for '{search_query}'")
                return False

            users = {user.id: user for user in response.includes.get('users', [])}
            replied_ids = {
                entry['tweet_id']
                for entry in self.engagement_history.get('replied_tweets', [])
            }

            candidate_posts = []
            for tweet in response.data:
                if tweet.id in replied_ids:
                    continue

                author = users.get(tweet.author_id)
                if not author:
                    continue

                created_at = tweet.created_at
                if datetime.now(created_at.tzinfo) - created_at > timedelta(hours=48):
                    continue

                likes = tweet.public_metrics['like_count']

                # At least 1 like (real post) but not mega-viral
                if likes < 1 or likes > 50000:
                    continue

                candidate_posts.append({
                    'tweet_id': tweet.id,
                    'author_id': tweet.author_id,
                    'author': author.username,
                    'text': tweet.text[:100] if tweet.text else '',
                    'likes': likes,
                })

            if not candidate_posts:
                print("   No cute kitten posts found to reply to")
                return False

            post = random.choice(candidate_posts)

            print(f"\n💬 Replying to cute kitten post from @{post['author']}")
            print(f"   Text: {post['text']}...")

            reply_messages = [
                "Absolutely adorable! 🐱🐾",
                "So precious! 🐾😻",
                "What a little cutie! 🐱🐾",
                "Too cute! 😻🐾",
                "That face! 🐱🐾",
                "Pawsitively adorable! 🐾😻",
                "Heart officially melted 🐱🐾",
                "Those little paws! 😻🐾",
                "Cuteness overload! 🐱🐾",
                "What a sweet little baby! 😻🐾",
            ]
            reply_text = random.choice(reply_messages)

            result = self.bot.reply_to_tweet(tweet_id=post['tweet_id'], text=reply_text)

            if not result:
                print("✗ Reply failed")
                return False

            # Log the reply
            self.engagement_history.setdefault('replied_tweets', []).append({
                'tweet_id': post['tweet_id'],
                'author': post['author'],
                'reply_text': reply_text,
                'timestamp': datetime.now().isoformat(),
            })
            self._save_engagement_history()

            print(f"✓ Replied to @{post['author']}: {reply_text}")
            return True

        except Exception as e:
            print(f"✗ Error finding/replying to cute kitten post on X: {e}")
            return False

    def run_engagement_cycle(self):
        """
        Run one engagement cycle:
        1. Try to find and follow a cat account (with ratio safety check)
        2. Try to find and like a cat post (auto-follow logic included)
        3. Try to quote-repost a cat rescue/adoption post
        4. Try to reply to a cute kitten post
        """
        print("\n" + "=" * 80)
        print("🐦 X/TWITTER CAT COMMUNITY ENGAGEMENT CYCLE")
        print("=" * 80)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Cleanup old history periodically
        self._cleanup_old_history()

        follow_success = False
        like_success = False
        quote_repost_success = False
        reply_success = False

        # Try to follow a cat account
        try:
            follow_success = self.find_and_follow_cat_account()
        except Exception as e:
            print(f"✗ Follow attempt failed: {e}")

        # Try to like a cat post (pass follow status for auto-follow logic)
        try:
            like_success = self.find_and_like_cat_post(already_followed_account=follow_success)
        except Exception as e:
            print(f"✗ Like attempt failed: {e}")

        # Try to quote-repost a cat rescue/adoption post
        try:
            quote_repost_success = self.find_and_quote_repost_rescue()
        except Exception as e:
            print(f"✗ Quote-repost attempt failed: {e}")

        # Try to reply to a cute kitten post
        try:
            reply_success = self.find_and_reply_cute_kitten()
        except Exception as e:
            print(f"✗ Reply attempt failed: {e}")

        # Summary
        print("\n" + "=" * 80)
        print("X ENGAGEMENT SUMMARY")
        print("=" * 80)
        print(f"✓ Followed: {1 if follow_success else 0} account")
        print(f"✓ Liked: {1 if like_success else 0} tweet")
        print(f"✓ Quote-reposted: {1 if quote_repost_success else 0} rescue post")
        print(f"✓ Replied: {1 if reply_success else 0} cute kitten post")
        print(f"Total followed: {len(self.engagement_history.get('followed_users', []))} accounts")
        print(f"Total liked: {len(self.engagement_history.get('liked_tweets', []))} tweets")
        print(f"Total quote-reposted: {len(self.engagement_history.get('reposted_tweets', []))} rescue posts")
        print(f"Total replied: {len(self.engagement_history.get('replied_tweets', []))} posts")
        print("=" * 80)

        return follow_success or like_success or quote_repost_success or reply_success


if __name__ == "__main__":
    bot = XEngagementBot()
    bot.run_engagement_cycle()
