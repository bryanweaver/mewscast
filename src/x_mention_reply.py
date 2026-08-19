"""
X mention reply bot — replies to mentions and replies on our own posts.

Scope:
  - Mentions of @mewscast
  - Replies to OUR journalism tweets (people who summoned us)

Voice rules:
  - Drive-by bait ("Slop", one-word dunk, empty, "lol"): ONE Walter Grok meme,
    almost no caption. No second meme ever.
  - Serious question: Straight Cronkite text from that episode's dossier.
    No hashtags, no sign-off.
  - Second touch in same thread: only if they ask a real question the dossier
    can answer. More slop → silence.

NOT in scope:
  - Cold outlet replies (X blocked those in API v2, 2026-02-23)
  - Likes, follows, quotes (X removed like writes from self-serve April 2026)
  - AP/Reuters drafts (Bryan taps those by hand)

Safety:
  - One reply per person per first touch (dedup)
  - Second touch allowed ONLY for dossier-text after a meme (not a second meme)
  - Caps: 3 replies per run, 5 per day
  - Skip our own tweets/replies
  - Skip anything that fails Cronkite standard
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup for sibling imports
# ---------------------------------------------------------------------------
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HISTORY_FILENAME = "x_mention_reply_history.json"
MAX_REPLIES_PER_RUN = 3
MAX_REPLIES_PER_DAY = 5

# Bait patterns — one-word dunks, slop, empty engagement
BAIT_PATTERNS = [
    r"^\s*slop\s*[.!?]*\s*$",
    r"^\s*lol\s*[.!?]*\s*$",
    r"^\s*lmao\s*[.!?]*\s*$",
    r"^\s*ratio\s*[.!?]*\s*$",
    r"^\s*mid\s*[.!?]*\s*$",
    r"^\s*cope\s*[.!?]*\s*$",
    r"^\s*fake\s*[.!?]*\s*$",
    r"^\s*bot\s*[.!?]*\s*$",
    r"^\s*ai\s+slop\s*[.!?]*\s*$",
    r"^\s*trash\s*[.!?]*\s*$",
    r"^\s*🗑️\s*$",
    r"^\s*💩\s*$",
    r"^\s*🤖\s*$",
    r"^\s*l\s*$",
    r"^\s*w\s*$",
    r"^\s*ok\s*[.!?]*\s*$",
    r"^\s*k\s*[.!?]*\s*$",
    r"^\s*no\s*[.!?]*\s*$",
    r"^\s*yes\s*[.!?]*\s*$",
    r"^\s*nah\s*[.!?]*\s*$",
    r"^\s*meh\s*[.!?]*\s*$",
    r"^\s*bruh\s*[.!?]*\s*$",
    r"^\s*bro\s*[.!?]*\s*$",
    r"^\s*oof\s*[.!?]*\s*$",
    r"^\s*yikes\s*[.!?]*\s*$",
    r"^\s*cringe\s*[.!?]*\s*$",
    r"^\s*based\s*[.!?]*\s*$",
    r"^\s*cap\s*[.!?]*\s*$",
    r"^\s*facts\s*[.!?]*\s*$",
    r"^\s*dead\s*[.!?]*\s*$",
    r"^\s*rip\s*[.!?]*\s*$",
    r"^\s*💀\s*$",
    r"^\s*😂\s*$",
    r"^\s*🤣\s*$",
    r"^\s*👎\s*$",
    r"^\s*$",  # empty
]
BAIT_REGEX = re.compile("|".join(BAIT_PATTERNS), re.IGNORECASE)

# Question patterns — indicates a real question worth answering
QUESTION_PATTERNS = [
    r"\?",  # contains question mark
    r"\b(what|why|how|when|where|who|which|can you|could you|is it|are you)\b",
    r"\b(explain|source|citation|evidence|proof|link)\b",
]
QUESTION_REGEX = re.compile("|".join(QUESTION_PATTERNS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pure helpers (testable without API)
# ---------------------------------------------------------------------------

def is_bait(text: str) -> bool:
    """Return True if text is drive-by bait (one-word dunk, slop, empty)."""
    if not text or not text.strip():
        return True
    return bool(BAIT_REGEX.match(text.strip()))


def is_serious_question(text: str) -> bool:
    """Return True if text appears to be a real question worth answering."""
    if not text or not text.strip():
        return False
    if is_bait(text):
        return False
    return bool(QUESTION_REGEX.search(text))


def compose_meme_caption(bait_text: str) -> str:
    """Compose a minimal meme caption for drive-by bait.
    
    Almost no caption — just enough to make the meme land.
    """
    # Most of the time: no caption at all, let the image speak
    return ""


def compose_meme_prompt(bait_text: str) -> str:
    """Compose a Grok image prompt for a Walter meme response to bait.
    
    Uses the "HOW DARE YOU" / indignant reaction meme template with Walter.
    """
    return (
        "Photorealistic brown tabby cat with an intense, indignant expression, "
        "sitting in a professional news anchor chair at a microphone, dramatic "
        "studio lighting. The cat's expression conveys dignified outrage — "
        "eyebrows raised, ears slightly back, mouth slightly open as if about "
        "to speak. Think Greta Thunberg 'HOW DARE YOU' energy but with feline "
        "gravitas. Professional news studio setting, dramatic lighting, "
        "cinematic composition. The cat is the star. No text overlays."
    )


def compose_cronkite_reply(question: str, dossier_data: dict) -> Optional[str]:
    """Compose a straight Cronkite-voice reply from dossier data.
    
    No hashtags, no sign-off, no puns. Just the facts.
    Returns None if the dossier can't answer the question.
    """
    if not dossier_data:
        return None
    
    brief = dossier_data.get("brief", {})
    dossier = dossier_data.get("dossier", {})
    
    # Extract key facts
    consensus = brief.get("consensus_facts", [])
    headline = dossier.get("headline_seed", "")
    articles = dossier.get("articles", [])
    outlet_count = len(articles)
    
    if not consensus and not headline:
        return None
    
    # Build a factual reply
    parts = []
    
    # Lead with the headline context
    if headline:
        parts.append(f"On this story:")
    
    # Add consensus facts (first 2-3)
    if consensus:
        for fact in consensus[:3]:
            if isinstance(fact, str):
                parts.append(f"• {fact}")
            elif isinstance(fact, dict) and fact.get("fact"):
                parts.append(f"• {fact['fact']}")
    
    # Add sourcing note
    if outlet_count > 1:
        parts.append(f"({outlet_count} outlets reporting)")
    
    reply = "\n".join(parts)
    
    # Ensure it fits in 280 chars
    if len(reply) > 280:
        reply = reply[:277] + "..."
    
    return reply if reply.strip() else None


def has_hashtags(text: str) -> bool:
    """Return True if text contains hashtags."""
    return bool(re.search(r"#\w+", text))


def has_sign_off(text: str) -> bool:
    """Return True if text contains a sign-off pattern."""
    sign_offs = [
        r"—\s*Walter",
        r"-\s*Walter",
        r"Walter\s+Croncat",
        r"🐱",
        r"🐾",
        r"📰",
        r"meow",
        r"purr",
    ]
    pattern = "|".join(sign_offs)
    return bool(re.search(pattern, text, re.IGNORECASE))


def validate_reply_text(text: str) -> tuple[bool, str]:
    """Validate that reply text meets Cronkite standards.
    
    Returns (is_valid, reason).
    """
    if not text or not text.strip():
        return False, "empty reply"
    
    if has_hashtags(text):
        return False, "contains hashtags"
    
    if has_sign_off(text):
        return False, "contains sign-off"
    
    # Check for dunk patterns
    dunk_patterns = [
        r"\bown(ed)?\b",
        r"\bratio\b",
        r"\bclown\b",
        r"\bidiot\b",
        r"\bstupid\b",
        r"\bdumb\b",
        r"\bmoron\b",
    ]
    for pattern in dunk_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return False, f"contains dunk language: {pattern}"
    
    return True, "ok"


# ---------------------------------------------------------------------------
# History management
# ---------------------------------------------------------------------------

def load_history(history_path: Path) -> dict:
    """Load reply history from JSON file."""
    if history_path.exists():
        try:
            with open(history_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Could not load history: {e}")
    return {
        "replies": [],
        "memes_by_thread": {},  # thread_id -> meme_image_path (reuse, don't mint new)
        "last_cleanup": datetime.now(timezone.utc).isoformat(),
    }


def save_history(history: dict, history_path: Path) -> None:
    """Save reply history to JSON file."""
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)
    print(f"✓ Saved history to {history_path}")


def daily_reply_count(history: dict) -> int:
    """Count replies in the last 24 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    count = 0
    for r in history.get("replies", []):
        try:
            ts = datetime.fromisoformat(r.get("timestamp", "2000-01-01T00:00:00+00:00"))
            if ts > cutoff:
                count += 1
        except ValueError:
            continue
    return count


def has_replied_to_user(history: dict, user_id: str) -> bool:
    """Check if we've already replied to this user (first-touch dedup)."""
    for r in history.get("replies", []):
        if r.get("author_id") == user_id and r.get("reply_type") != "dossier_followup":
            return True
    return False


def has_memed_in_thread(history: dict, conversation_id: str) -> bool:
    """Check if we've already sent a meme in this thread."""
    return conversation_id in history.get("memes_by_thread", {})


def get_meme_for_thread(history: dict, conversation_id: str) -> Optional[str]:
    """Get the meme image path we used in this thread (for reuse)."""
    return history.get("memes_by_thread", {}).get(conversation_id)


def has_dossier_replied_in_thread(history: dict, conversation_id: str, user_id: str) -> bool:
    """Check if we've already sent a dossier reply to this user in this thread."""
    for r in history.get("replies", []):
        if (r.get("conversation_id") == conversation_id and 
            r.get("author_id") == user_id and
            r.get("reply_type") == "dossier_followup"):
            return True
    return False


def cleanup_old_history(history: dict) -> None:
    """Remove reply records older than 90 days."""
    last = datetime.fromisoformat(
        history.get("last_cleanup", "2000-01-01T00:00:00+00:00")
    )
    now = datetime.now(timezone.utc)
    if now - last < timedelta(days=7):
        return
    
    cutoff = now - timedelta(days=90)
    replies = history.get("replies", [])
    n_before = len(replies)
    history["replies"] = [
        r for r in replies
        if datetime.fromisoformat(r.get("timestamp", "2000-01-01T00:00:00+00:00")) > cutoff
    ]
    removed = n_before - len(history["replies"])
    if removed:
        print(f"🧹 Removed {removed} old reply records")
    history["last_cleanup"] = now.isoformat()


# ---------------------------------------------------------------------------
# Journalism post lookup
# ---------------------------------------------------------------------------

def get_recent_journalism_tweets(hours: int = 48) -> list[dict]:
    """Get recent journalism posts from posts_history.json with x_tweet_id."""
    history_path = Path(__file__).parent.parent / "posts_history.json"
    try:
        with open(history_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, FileNotFoundError) as e:
        print(f"⚠️  Could not load posts_history.json: {e}")
        return []
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    eligible = []
    
    for post in data.get("posts", []):
        # Must be journalism pipeline with X tweet ID
        if post.get("post_pipeline") != "journalism":
            continue
        if not post.get("x_tweet_id"):
            continue
        
        try:
            ts = datetime.fromisoformat(post["timestamp"].replace("Z", "+00:00"))
            if ts >= cutoff:
                eligible.append(post)
        except (ValueError, KeyError):
            continue
    
    return eligible


def load_dossier_data(dossier_id: str) -> Optional[dict]:
    """Load dossier data for Cronkite replies."""
    if not dossier_id:
        return None
    
    # Try brief sidecar first (smaller, available in CI)
    brief_path = Path(__file__).parent.parent / "docs" / "dossiers" / f"{dossier_id}.brief.json"
    try:
        with open(brief_path, "r", encoding="utf-8") as f:
            sidecar = json.load(f)
        return {
            "brief": sidecar.get("brief", {}),
            "dossier": {
                "headline_seed": sidecar.get("headline_seed", ""),
                "articles": sidecar.get("articles", []),
            },
        }
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️  Could not load dossier brief: {e}")
    
    return None


def find_parent_journalism_post(tweet_id: str, journalism_tweets: list[dict]) -> Optional[dict]:
    """Find the journalism post that this tweet is replying to."""
    for post in journalism_tweets:
        if post.get("x_tweet_id") == tweet_id:
            return post
        if post.get("x_reply_tweet_id") == tweet_id:
            return post
    return None


# ---------------------------------------------------------------------------
# Main bot class
# ---------------------------------------------------------------------------

class XMentionReplyBot:
    """Handles mention replies on X."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.history_path = Path(__file__).parent.parent / HISTORY_FILENAME
        self.history = load_history(self.history_path)
        self.twitter_bot = None
        self.image_generator = None
        self.replies_this_run = 0
    
    def _init_twitter(self):
        """Lazy-init Twitter bot."""
        if self.twitter_bot is None:
            from twitter_bot import TwitterBot
            self.twitter_bot = TwitterBot()
    
    def _init_image_generator(self):
        """Lazy-init image generator."""
        if self.image_generator is None:
            from image_generator import ImageGenerator
            self.image_generator = ImageGenerator()
    
    def _get_our_user_id(self) -> Optional[str]:
        """Get our own user ID to skip self-replies."""
        self._init_twitter()
        try:
            me = self.twitter_bot.client.get_me()
            return str(me.data.id) if me and me.data else None
        except Exception as e:
            print(f"⚠️  Could not get our user ID: {e}")
            return None
    
    def _fetch_mentions(self) -> list[dict]:
        """Fetch recent mentions."""
        self._init_twitter()
        try:
            mentions = self.twitter_bot.client.get_users_mentions(
                id=self._get_our_user_id(),
                max_results=20,
                tweet_fields=["conversation_id", "author_id", "in_reply_to_user_id", "created_at"],
                expansions=["author_id"],
            )
            if not mentions or not mentions.data:
                return []
            
            result = []
            for tweet in mentions.data:
                result.append({
                    "id": str(tweet.id),
                    "text": tweet.text or "",
                    "author_id": str(tweet.author_id) if tweet.author_id else "",
                    "conversation_id": str(tweet.conversation_id) if tweet.conversation_id else str(tweet.id),
                    "in_reply_to_user_id": str(tweet.in_reply_to_user_id) if tweet.in_reply_to_user_id else None,
                })
            return result
        except Exception as e:
            print(f"⚠️  Could not fetch mentions: {e}")
            return []
    
    def _generate_meme_image(self, bait_text: str, save_path: str) -> Optional[str]:
        """Generate a Walter meme image for bait response."""
        self._init_image_generator()
        prompt = compose_meme_prompt(bait_text)
        
        if self.dry_run:
            print(f"   [DRY RUN] Would generate meme with prompt: {prompt[:80]}...")
            return "[dry-run-meme-path]"
        
        try:
            path, _ = self.image_generator.generate_image(
                prompt=prompt,
                save_path=save_path,
                post_type=None,  # No post-type anchor for memes
            )
            return path
        except Exception as e:
            print(f"⚠️  Meme generation failed: {e}")
            return None
    
    def _post_meme_reply(self, tweet_id: str, image_path: str, caption: str) -> Optional[dict]:
        """Post a meme reply to a tweet."""
        self._init_twitter()
        
        if self.dry_run:
            print(f"   [DRY RUN] Would reply to {tweet_id} with meme")
            return {"id": "dry-run-reply-id"}
        
        try:
            if caption:
                return self.twitter_bot.reply_to_tweet_with_image(tweet_id, caption, image_path)
            else:
                return self.twitter_bot.reply_to_tweet_with_image(tweet_id, ".", image_path)
        except Exception as e:
            print(f"⚠️  Meme reply failed: {e}")
            return None
    
    def _post_text_reply(self, tweet_id: str, text: str) -> Optional[dict]:
        """Post a text reply to a tweet."""
        self._init_twitter()
        
        if self.dry_run:
            print(f"   [DRY RUN] Would reply to {tweet_id} with: {text[:100]}...")
            return {"id": "dry-run-reply-id"}
        
        try:
            return self.twitter_bot.reply_to_tweet(tweet_id, text)
        except Exception as e:
            print(f"⚠️  Text reply failed: {e}")
            return None
    
    def _handle_mention(self, mention: dict, journalism_tweets: list[dict], our_user_id: str) -> bool:
        """Handle a single mention. Returns True if we replied."""
        tweet_id = mention["id"]
        text = mention["text"]
        author_id = mention["author_id"]
        conversation_id = mention["conversation_id"]
        
        print(f"\n📨 Processing mention {tweet_id}")
        print(f"   Author: {author_id}")
        print(f"   Text: {text[:80]}...")
        
        # Skip our own tweets
        if author_id == our_user_id:
            print("   ⏭  Skipping (our own tweet)")
            return False
        
        # Check if this is a reply to our journalism tweet
        parent_post = None
        for post in journalism_tweets:
            if conversation_id == post.get("x_tweet_id"):
                parent_post = post
                break
        
        # First-touch dedup: have we replied to this user before?
        if has_replied_to_user(self.history, author_id):
            # Check if this is a follow-up in a thread where we memed
            if has_memed_in_thread(self.history, conversation_id):
                # They're following up after our meme
                if is_bait(text):
                    # More slop → silence
                    print("   ⏭  Skipping (more slop after meme, silence)")
                    return False
                
                if is_serious_question(text) and parent_post:
                    # Real question → dossier reply (if not already done)
                    if has_dossier_replied_in_thread(self.history, conversation_id, author_id):
                        print("   ⏭  Skipping (already dossier-replied in thread)")
                        return False
                    
                    # Load dossier and reply
                    dossier_id = parent_post.get("dossier_id")
                    dossier_data = load_dossier_data(dossier_id)
                    reply_text = compose_cronkite_reply(text, dossier_data)
                    
                    if reply_text:
                        is_valid, reason = validate_reply_text(reply_text)
                        if not is_valid:
                            print(f"   ⏭  Skipping (reply validation failed: {reason})")
                            return False
                        
                        result = self._post_text_reply(tweet_id, reply_text)
                        if result:
                            self.history.setdefault("replies", []).append({
                                "tweet_id": tweet_id,
                                "author_id": author_id,
                                "conversation_id": conversation_id,
                                "reply_type": "dossier_followup",
                                "reply_id": result.get("id"),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                            self.replies_this_run += 1
                            print(f"   ✓ Dossier follow-up reply posted")
                            return True
                    else:
                        print("   ⏭  Skipping (no dossier answer available)")
                        return False
                else:
                    print("   ⏭  Skipping (not a serious question after meme)")
                    return False
            else:
                print("   ⏭  Skipping (already replied to user)")
                return False
        
        # First touch: classify and respond
        if is_bait(text):
            # Drive-by bait → meme
            print("   🎭 Detected bait, generating meme...")
            
            # Check if we already have a meme for this thread
            existing_meme = get_meme_for_thread(self.history, conversation_id)
            if existing_meme:
                print(f"   📎 Reusing existing meme: {existing_meme}")
                meme_path = existing_meme
            else:
                # Generate new meme
                safe_id = re.sub(r"[^\w\-]", "_", tweet_id)
                meme_path = f"temp_meme_{safe_id}.png"
                meme_path = self._generate_meme_image(text, meme_path)
                if not meme_path:
                    print("   ⚠️  Meme generation failed, skipping")
                    return False
            
            caption = compose_meme_caption(text)
            result = self._post_meme_reply(tweet_id, meme_path, caption)
            
            if result:
                self.history.setdefault("replies", []).append({
                    "tweet_id": tweet_id,
                    "author_id": author_id,
                    "conversation_id": conversation_id,
                    "reply_type": "meme",
                    "reply_id": result.get("id"),
                    "meme_path": meme_path,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                self.history.setdefault("memes_by_thread", {})[conversation_id] = meme_path
                self.replies_this_run += 1
                print(f"   ✓ Meme reply posted")
                return True
            return False
        
        elif is_serious_question(text) and parent_post:
            # Serious question on our journalism tweet → Cronkite reply
            print("   📝 Serious question, composing Cronkite reply...")
            
            dossier_id = parent_post.get("dossier_id")
            dossier_data = load_dossier_data(dossier_id)
            reply_text = compose_cronkite_reply(text, dossier_data)
            
            if reply_text:
                is_valid, reason = validate_reply_text(reply_text)
                if not is_valid:
                    print(f"   ⏭  Skipping (reply validation failed: {reason})")
                    return False
                
                result = self._post_text_reply(tweet_id, reply_text)
                if result:
                    self.history.setdefault("replies", []).append({
                        "tweet_id": tweet_id,
                        "author_id": author_id,
                        "conversation_id": conversation_id,
                        "reply_type": "cronkite",
                        "reply_id": result.get("id"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    self.replies_this_run += 1
                    print(f"   ✓ Cronkite reply posted")
                    return True
            else:
                print("   ⏭  Skipping (no dossier available for this question)")
                return False
        
        else:
            # Not bait, not a question we can answer → skip
            print("   ⏭  Skipping (not bait, not a serious question we can answer)")
            return False
        
        return False
    
    def run(self) -> int:
        """Main entry point. Returns number of replies posted."""
        print("=" * 80)
        print("🐱 X Mention Reply Bot")
        print(f"   Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print("=" * 80)
        
        # Cleanup old history
        cleanup_old_history(self.history)
        
        # Check daily cap
        today_count = daily_reply_count(self.history)
        print(f"✓ Daily replies: {today_count}/{MAX_REPLIES_PER_DAY}")
        if today_count >= MAX_REPLIES_PER_DAY:
            print("   Daily cap reached, exiting")
            return 0
        
        # Get our user ID
        our_user_id = self._get_our_user_id()
        if not our_user_id:
            print("⚠️  Could not determine our user ID")
            return 0
        print(f"✓ Our user ID: {our_user_id}")
        
        # Fetch recent journalism tweets (for context)
        journalism_tweets = get_recent_journalism_tweets(hours=72)
        print(f"✓ Found {len(journalism_tweets)} recent journalism tweets")
        
        # Fetch mentions
        mentions = self._fetch_mentions()
        print(f"✓ Found {len(mentions)} mentions")
        
        if not mentions:
            print("\n   No mentions to process")
            if not self.dry_run:
                save_history(self.history, self.history_path)
            return 0
        
        # Process mentions
        for mention in mentions:
            # Check caps
            if self.replies_this_run >= MAX_REPLIES_PER_RUN:
                print(f"\n⏹  Per-run cap reached ({MAX_REPLIES_PER_RUN})")
                break
            
            if daily_reply_count(self.history) >= MAX_REPLIES_PER_DAY:
                print(f"\n⏹  Daily cap reached ({MAX_REPLIES_PER_DAY})")
                break
            
            self._handle_mention(mention, journalism_tweets, our_user_id)
        
        # Save history
        if not self.dry_run:
            save_history(self.history, self.history_path)
        
        print("\n" + "=" * 80)
        print(f"✓ Complete. Replies this run: {self.replies_this_run}")
        print("=" * 80)
        
        return self.replies_this_run


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reply to X mentions and replies on our posts"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan without posting",
    )
    args = parser.parse_args(argv)
    
    bot = XMentionReplyBot(dry_run=args.dry_run)
    bot.run()
    
    # Never fail the GHA on "no replies" — that's normal
    return 0


if __name__ == "__main__":
    sys.exit(main())
