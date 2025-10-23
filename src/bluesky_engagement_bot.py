"""
Cat community engagement automation for Bluesky
Finds and follows cat accounts, likes cat posts
"""
import os
import random
import json
from datetime import datetime, timedelta
from pathlib import Path
from atproto import Client


class BlueskyEngagementBot:
    """Automates engagement with cat community on Bluesky"""

    def __init__(self):
        """Initialize Bluesky engagement bot"""
        self.username = os.getenv("BLUESKY_USERNAME")
        self.password = os.getenv("BLUESKY_PASSWORD")

        if not all([self.username, self.password]):
            raise ValueError("Missing Bluesky credentials. Check your .env file.")

        # Initialize atproto client
        self.client = Client()
        self.client.login(self.username, self.password)
        print(f"✓ Logged into Bluesky as @{self.username}")

        self.engagement_log_path = Path(__file__).parent.parent / "bluesky_engagement_history.json"
        self.engagement_history = self._load_engagement_history()

    def _load_engagement_history(self) -> dict:
        """Load engagement history to avoid duplicates"""
        if self.engagement_log_path.exists():
            with open(self.engagement_log_path, 'r') as f:
                return json.load(f)
        return {
            'followed_users': [],
            'liked_posts': [],
            'last_cleanup': datetime.now().isoformat()
        }

    def _save_engagement_history(self):
        """Save engagement history"""
        with open(self.engagement_log_path, 'w') as f:
            json.dump(self.engagement_history, f, indent=2)
        print(f"✓ Saved Bluesky engagement history")

    def _check_follow_ratio_safe(self) -> bool:
        """
        Check if our follow ratio is safe before following more accounts

        Returns:
            True if safe to follow, False if ratio too high
        """
        try:
            # Get our own profile stats
            profile = self.client.app.bsky.actor.get_profile({'actor': self.client.me.did})
            my_followers = profile.followers_count if hasattr(profile, 'followers_count') else 0
            my_following = profile.follows_count if hasattr(profile, 'follows_count') else 0

            # Calculate ratio
            if my_followers == 0:
                # If we have 0 followers, allow following up to 50 accounts to get started
                if my_following >= 50:
                    print(f"⚠️  Have 0 followers and already following {my_following} accounts.")
                    print(f"   Pausing follows until people follow back.")
                    return False
                return True

            ratio = my_following / my_followers

            # Safety threshold: Don't let ratio exceed 2.5:1
            if ratio > 2.5:
                print(f"⚠️  Follow ratio too high: {ratio:.1f}:1 (following {my_following}, followers {my_followers})")
                print(f"   Pausing follows until more people follow back (target: <2.5:1)")
                return False

            print(f"✓ Follow ratio healthy: {ratio:.1f}:1 (following {my_following}, followers {my_followers})")
            return True

        except Exception as e:
            print(f"✗ Could not check follow ratio: {e}")
            # If we can't check, err on the side of caution
            return False

    def _cleanup_old_history(self):
        """Remove entries older than 90 days to keep file manageable"""
        last_cleanup = datetime.fromisoformat(self.engagement_history.get('last_cleanup', datetime.now().isoformat()))

        # Only cleanup once per week
        if datetime.now() - last_cleanup < timedelta(days=7):
            return

        print("🧹 Cleaning up old Bluesky engagement history...")
        cutoff_date = datetime.now() - timedelta(days=90)

        # Keep only recent follows
        if self.engagement_history.get('followed_users'):
            original_count = len(self.engagement_history['followed_users'])
            self.engagement_history['followed_users'] = [
                entry for entry in self.engagement_history['followed_users']
                if datetime.fromisoformat(entry.get('timestamp', datetime.now().isoformat())) > cutoff_date
            ]
            removed = original_count - len(self.engagement_history['followed_users'])
            if removed > 0:
                print(f"   Removed {removed} old follow records")

        # Keep only recent likes
        if self.engagement_history.get('liked_posts'):
            original_count = len(self.engagement_history['liked_posts'])
            self.engagement_history['liked_posts'] = [
                entry for entry in self.engagement_history['liked_posts']
                if datetime.fromisoformat(entry.get('timestamp', datetime.now().isoformat())) > cutoff_date
            ]
            removed = original_count - len(self.engagement_history['liked_posts'])
            if removed > 0:
                print(f"   Removed {removed} old like records")

        self.engagement_history['last_cleanup'] = datetime.now().isoformat()
        self._save_engagement_history()

    def find_and_follow_cat_account(self) -> bool:
        """
        Find and follow one cat-related account on Bluesky

        Returns:
            True if successfully followed, False otherwise
        """
        print("\n🐱 Searching for cat accounts to follow on Bluesky...")

        # SAFETY CHECK: Verify our follow ratio is healthy before following
        if not self._check_follow_ratio_safe():
            print("   → Skipping follow attempt (ratio check failed)")
            return False

        # Bluesky search terms (different from X - simpler queries work better)
        search_terms = [
            "cat owner",
            "cat dad",
            "cat mom",
            "cats",
            "my cat",
            "kitty",
            "feline",
            "caturday",
            "cat lover"
        ]

        search_query = random.choice(search_terms)

        try:
            # Search for posts about cats
            response = self.client.app.bsky.feed.search_posts({
                'q': search_query,
                'limit': 25  # Get more results for better filtering
            })

            if not response.posts:
                print(f"   No results for '{search_query}'")
                return False

            # Extract unique authors from posts
            candidate_accounts = []
            followed_dids = [entry['did'] for entry in self.engagement_history.get('followed_users', [])]

            for post in response.posts:
                author = post.author

                # Skip if already followed
                if author.did in followed_dids:
                    continue

                # Skip if it's our own account
                if author.handle == self.username.replace('.bsky.social', ''):
                    continue

                # Filter criteria for Bluesky:
                # - Has reasonable follower count (50-50K)
                # - Bio mentions cats
                followers = author.followers_count if hasattr(author, 'followers_count') else 0
                following = author.follows_count if hasattr(author, 'follows_count') else 0
                bio = author.description.lower() if hasattr(author, 'description') and author.description else ""

                # Quality checks
                if followers < 50 or followers > 50000:
                    continue  # Too small (likely inactive) or too big (won't follow back)

                # Check if actually cat-related
                cat_keywords = ['cat', 'kitten', 'feline', 'meow', 'kitty', 'tabby', 'cats']
                if not any(keyword in bio for keyword in cat_keywords):
                    # Also check if their post is actually about cats
                    post_text = post.record.text.lower() if hasattr(post.record, 'text') else ""
                    if not any(keyword in post_text for keyword in cat_keywords):
                        continue

                # Prefer accounts with good follow ratio (not follow-spammers)
                follow_ratio = following / followers if followers > 0 else 999
                if follow_ratio > 5:  # Following way more than followers = spammer
                    continue

                candidate_accounts.append({
                    'did': author.did,
                    'handle': author.handle,
                    'display_name': author.display_name if author.display_name else author.handle,
                    'followers': followers,
                    'bio': bio[:100]
                })

            # Remove duplicates by DID
            seen_dids = set()
            unique_candidates = []
            for account in candidate_accounts:
                if account['did'] not in seen_dids:
                    seen_dids.add(account['did'])
                    unique_candidates.append(account)

            if not unique_candidates:
                print(f"   No quality cat accounts found in results")
                return False

            # Pick random account from candidates
            account = random.choice(unique_candidates)

            print(f"\n👤 Following: @{account['handle']}")
            print(f"   Name: {account['display_name']}")
            print(f"   Followers: {account['followers']}")
            print(f"   Bio: {account['bio']}...")

            # Follow the account
            # Format datetime in ISO 8601 format with 'Z' suffix for UTC
            created_at = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            self.client.app.bsky.graph.follow.create(
                self.client.me.did,
                {
                    'subject': account['did'],
                    'createdAt': created_at
                }
            )

            # Log the follow
            self.engagement_history.setdefault('followed_users', []).append({
                'did': account['did'],
                'handle': account['handle'],
                'timestamp': datetime.now().isoformat()
            })
            self._save_engagement_history()

            print(f"✓ Followed @{account['handle']}")
            return True

        except Exception as e:
            print(f"✗ Error finding/following cat account on Bluesky: {e}")
            return False

    def find_and_like_cat_post(self, already_followed_account: bool = False) -> bool:
        """
        Find and like one cat-related post on Bluesky

        Args:
            already_followed_account: Whether we already followed a cat account this cycle

        Returns:
            True if successfully liked, False otherwise
        """
        print("\n🐱 Searching for cat posts to like on Bluesky...")

        # Search terms optimized for Bluesky
        search_terms = [
            "cute cat",
            "my cat",
            "look at my cat",
            "caturday",
            "adopted a cat",
            "cat doing",
            "this cat",
            "cat photo",
            "cats of bluesky"
        ]

        search_query = random.choice(search_terms)

        try:
            # Search for cat posts
            response = self.client.app.bsky.feed.search_posts({
                'q': search_query,
                'limit': 25  # Get more results for better filtering
            })

            if not response.posts:
                print(f"   No results for '{search_query}'")
                return False

            # Filter for quality posts
            candidate_posts = []
            liked_uris = [entry['uri'] for entry in self.engagement_history.get('liked_posts', [])]

            for post in response.posts:
                # Skip if already liked
                if post.uri in liked_uris:
                    continue

                # Skip our own posts
                if post.author.handle == self.username.replace('.bsky.social', ''):
                    continue

                # Filter criteria:
                # - Has some engagement (5-5000 likes = quality but not mega-viral)
                # - Recent (within last 48 hours - Bluesky moves slower than X)
                likes = post.like_count if hasattr(post, 'like_count') else 0
                reposts = post.repost_count if hasattr(post, 'repost_count') else 0

                if likes < 3 or likes > 5000:
                    continue  # Too little engagement or mega-viral

                # Check recency - Bluesky posts have indexed_at timestamp
                created_at = datetime.fromisoformat(post.indexed_at.replace('Z', '+00:00'))
                if datetime.now(created_at.tzinfo) - created_at > timedelta(hours=48):
                    continue  # Too old

                candidate_posts.append({
                    'uri': post.uri,
                    'cid': post.cid,
                    'author': post.author.handle,
                    'author_did': post.author.did,
                    'author_obj': post.author,  # Store full author object for follow check
                    'text': post.record.text[:100] if hasattr(post.record, 'text') else '',
                    'likes': likes,
                    'reposts': reposts
                })

            if not candidate_posts:
                print(f"   No quality cat posts found in results")
                return False

            # Pick random post from candidates
            post = random.choice(candidate_posts)

            print(f"\n❤️  Liking post from @{post['author']}")
            print(f"   Text: {post['text']}...")
            print(f"   Engagement: {post['likes']} likes, {post['reposts']} reposts")

            # Like the post
            # Format datetime in ISO 8601 format with 'Z' suffix for UTC
            created_at = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            self.client.app.bsky.feed.like.create(
                self.client.me.did,
                {
                    'subject': {
                        'uri': post['uri'],
                        'cid': post['cid']
                    },
                    'createdAt': created_at
                }
            )

            # Log the like
            self.engagement_history.setdefault('liked_posts', []).append({
                'uri': post['uri'],
                'author': post['author'],
                'timestamp': datetime.now().isoformat()
            })
            self._save_engagement_history()

            print(f"✓ Liked post from @{post['author']}")

            # AUTO-FOLLOW: Follow the author of this post
            followed_dids = [entry['did'] for entry in self.engagement_history.get('followed_users', [])]
            author = post['author_obj']

            # Check if we should follow this author
            if post['author_did'] not in followed_dids:
                # Check if they're a good account to follow
                followers = author.followers_count if hasattr(author, 'followers_count') else 0
                following = author.follows_count if hasattr(author, 'follows_count') else 0

                # NEW RULE: If we didn't follow a proper cat account, ALWAYS follow this author
                if not already_followed_account:
                    # Check ratio before guaranteed follow
                    if not self._check_follow_ratio_safe():
                        print(f"   → Skipping auto-follow of @{post['author']} (ratio check failed)")
                    else:
                        # Guaranteed follow since we didn't find a proper cat account
                        try:
                            print(f"\n👤 Auto-follow: @{post['author']} (no cat account found, following post author)")
                            print(f"   Followers: {followers}")

                            # Follow the account
                            created_at_follow = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                            self.client.app.bsky.graph.follow.create(
                                self.client.me.did,
                                {
                                    'subject': post['author_did'],
                                    'createdAt': created_at_follow
                                }
                            )

                            # Log the follow
                            self.engagement_history.setdefault('followed_users', []).append({
                                'did': post['author_did'],
                                'handle': post['author'],
                                'timestamp': datetime.now().isoformat()
                            })
                            self._save_engagement_history()

                            print(f"✓ Followed @{post['author']}")
                        except Exception as e:
                            print(f"✗ Could not follow @{post['author']}: {e}")
                else:
                    # Already followed a proper cat account, use quality checks
                    should_follow = True

                    if followers < 50 or followers > 50000:
                        should_follow = False  # Outside ideal range
                        print(f"   → Skipping bonus follow (followers: {followers})")
                    elif following > 0 and followers > 0:
                        follow_ratio = following / followers
                        if follow_ratio > 5:
                            should_follow = False  # Follow spammer
                            print(f"   → Skipping bonus follow (bad ratio: {follow_ratio:.1f})")

                    if should_follow:
                        # Check ratio before bonus follow
                        if not self._check_follow_ratio_safe():
                            print(f"   → Skipping bonus follow of @{post['author']} (ratio check failed)")
                        else:
                            try:
                                print(f"\n👤 Bonus follow: @{post['author']} (author of liked post)")
                                print(f"   Followers: {followers}")

                                # Follow the account
                                created_at_follow = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                                self.client.app.bsky.graph.follow.create(
                                    self.client.me.did,
                                    {
                                        'subject': post['author_did'],
                                        'createdAt': created_at_follow
                                    }
                                )

                                # Log the follow
                                self.engagement_history.setdefault('followed_users', []).append({
                                    'did': post['author_did'],
                                    'handle': post['author'],
                                    'timestamp': datetime.now().isoformat()
                                })
                                self._save_engagement_history()

                                print(f"✓ Followed @{post['author']}")
                            except Exception as e:
                                print(f"✗ Could not follow @{post['author']}: {e}")

            return True

        except Exception as e:
            print(f"✗ Error finding/liking cat post on Bluesky: {e}")
            return False

    def run_engagement_cycle(self):
        """
        Run one engagement cycle:
        1. Try to find cat account to follow (from search)
        2. Try to find cat post to like
        3. Auto-follow rules:
           - If we didn't follow a cat account: ALWAYS follow the post author
           - If we did follow a cat account: Try to follow post author (if they qualify)

        This guarantees we follow at least 1 account per cycle (if we like a post)

        This should be called every 30 minutes
        """
        print("\n" + "="*80)
        print("🦋 BLUESKY CAT COMMUNITY ENGAGEMENT CYCLE")
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

        # Try to like a cat post (pass follow status so we know if we need guaranteed follow)
        try:
            like_success = self.find_and_like_cat_post(already_followed_account=follow_success)
        except Exception as e:
            print(f"✗ Like attempt failed: {e}")

        # Summary
        print("\n" + "="*80)
        print("BLUESKY ENGAGEMENT SUMMARY")
        print("="*80)
        print(f"✓ Followed: {1 if follow_success else 0} account")
        print(f"✓ Liked: {1 if like_success else 0} post")
        print(f"Total followed: {len(self.engagement_history.get('followed_users', []))} accounts")
        print(f"Total liked: {len(self.engagement_history.get('liked_posts', []))} posts")
        print("="*80)

        return follow_success or like_success


if __name__ == "__main__":
    """Run engagement cycle when called directly"""
    bot = BlueskyEngagementBot()
    bot.run_engagement_cycle()
