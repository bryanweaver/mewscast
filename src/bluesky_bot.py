"""
Bluesky integration using atproto
"""
import os
import io
from atproto import Client
from atproto import models
from typing import Optional
import re
from PIL import Image
from content_generator import _truncate_at_sentence

# Bluesky hard limit: 1,000,000 bytes for image uploads
BLUESKY_MAX_IMAGE_BYTES = 1_000_000


class BlueskyBot:
    """Handles all Bluesky API interactions"""

    def __init__(self):
        """Initialize Bluesky client with credentials from environment"""
        self.username = os.getenv("BLUESKY_USERNAME")
        self.password = os.getenv("BLUESKY_PASSWORD")

        # Validate credentials
        if not all([self.username, self.password]):
            raise ValueError("Missing Bluesky credentials. Check your .env file.")

        # Initialize atproto client
        self.client = Client()

        try:
            self.client.login(self.username, self.password)
            print(f"✓ Logged into Bluesky as @{self.username}")
        except Exception as e:
            raise ValueError(f"Failed to authenticate with Bluesky: {e}")

    def post_skeet(self, text: str) -> Optional[dict]:
        """
        Post a skeet to your timeline

        Args:
            text: The post content (max 300 characters, we use 280 for compatibility)

        Returns:
            Post data if successful, None if failed
        """
        try:
            if len(text) > 300:
                print(f"Warning: Post too long ({len(text)} chars). Truncating...")
                text = _truncate_at_sentence(text, 300)

            response = self.client.send_post(text=text)
            print(f"✓ Skeet posted successfully! URI: {response.uri}")
            return {
                'uri': response.uri,
                'cid': response.cid
            }
        except Exception as e:
            print(f"✗ Error posting skeet: {e}")
            return None

    def _optimize_image_for_bluesky(self, image_path: str) -> tuple:
        """
        Optimize an image for Bluesky: read dimensions for aspect ratio,
        compress to JPEG if needed to fit under 1MB limit.

        Returns:
            (image_bytes, width, height) tuple
        """
        img = Image.open(image_path)
        width, height = img.size
        print(f"   Original image: {width}x{height}")

        # Convert to RGB if necessary (e.g. RGBA PNGs)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # First try: read raw file bytes to see if already small enough
        with open(image_path, 'rb') as f:
            raw_bytes = f.read()

        if len(raw_bytes) <= BLUESKY_MAX_IMAGE_BYTES and image_path.lower().endswith(('.jpg', '.jpeg')):
            print(f"   Image already under 1MB ({len(raw_bytes):,} bytes), using as-is")
            return raw_bytes, width, height

        # Compress as JPEG, starting at quality 90 and reducing until under 1MB
        for quality in (90, 80, 70, 60, 50):
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            image_data = buffer.getvalue()
            if len(image_data) <= BLUESKY_MAX_IMAGE_BYTES:
                print(f"   Compressed to JPEG quality={quality} ({len(image_data):,} bytes)")
                return image_data, width, height

        # Last resort: resize down to fit
        scale = 0.75
        while scale > 0.25:
            new_w, new_h = int(width * scale), int(height * scale)
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            buffer = io.BytesIO()
            resized.save(buffer, format='JPEG', quality=70, optimize=True)
            image_data = buffer.getvalue()
            if len(image_data) <= BLUESKY_MAX_IMAGE_BYTES:
                print(f"   Resized to {new_w}x{new_h} + JPEG q=70 ({len(image_data):,} bytes)")
                return image_data, new_w, new_h
            scale -= 0.1

        # Fallback: return whatever we have at smallest scale
        print(f"   Warning: Could not compress under 1MB, using best effort ({len(image_data):,} bytes)")
        return image_data, new_w, new_h

    def post_skeet_with_image(self, text: str, image_path: str) -> Optional[dict]:
        """
        Post a skeet with an attached image, optimized for Bluesky display.
        Automatically compresses images under 1MB and sends aspect ratio metadata.

        Args:
            text: The post content (max 300 characters, we use 280 for compatibility)
            image_path: Path to the image file to attach

        Returns:
            Post data if successful, None if failed
        """
        try:
            if len(text) > 300:
                print(f"Warning: Post too long ({len(text)} chars). Truncating...")
                text = _truncate_at_sentence(text, 300)

            print(f"📤 Optimizing image for Bluesky: {image_path}")
            image_data, width, height = self._optimize_image_for_bluesky(image_path)

            # Build aspect ratio metadata so Bluesky renders correctly
            aspect_ratio = models.AppBskyEmbedDefs.AspectRatio(
                width=width,
                height=height
            )

            # Post with image and aspect ratio
            response = self.client.send_image(
                text=text,
                image=image_data,
                image_alt="News reporter cat illustration",
                image_aspect_ratio=aspect_ratio
            )

            print(f"✓ Skeet with image posted successfully! URI: {response.uri}")
            print(f"   Aspect ratio sent: {width}:{height}")
            return {
                'uri': response.uri,
                'cid': response.cid
            }

        except FileNotFoundError:
            print(f"✗ Error: Image file not found: {image_path}")
            return None
        except Exception as e:
            print(f"✗ Error posting skeet with image: {e}")
            return None

    def reply_to_skeet_with_link(self, parent_uri: str, url: str) -> Optional[dict]:
        """
        Reply to a skeet with a URL that shows a link preview card

        Args:
            parent_uri: URI of the post to reply to
            url: URL to post as a link card

        Returns:
            Post data if successful, None if failed
        """
        try:
            # Bluesky has a 300 character limit on post text
            # If URL is too long, skip the reply (shouldn't happen with decoded URLs)
            if len(url) > 300:
                print(f"⚠️  URL too long for Bluesky ({len(url)} chars > 300)")
                # Check if it's a Google News URL that failed to decode
                if 'news.google.com' in url:
                    print(f"   Google News URL not decoded - skipping Bluesky source reply")
                else:
                    print(f"   Article URL unexpectedly long - skipping Bluesky source reply")
                return None

            # Parse AT URI to get components
            parts = parent_uri.replace('at://', '').split('/')
            if len(parts) != 3:
                raise ValueError(f"Invalid AT URI format: {parent_uri}")

            # Get the post thread to fetch parent CID
            post_thread = self.client.app.bsky.feed.get_post_thread({'uri': parent_uri})
            parent_cid = post_thread.thread.post.cid

            # Create parent reference
            parent_ref = models.ComAtprotoRepoStrongRef.Main(
                uri=parent_uri,
                cid=parent_cid
            )

            # Create reply reference
            reply_ref = models.AppBskyFeedPost.ReplyRef(
                parent=parent_ref,
                root=parent_ref
            )

            # Create link card embed using atproto models
            # Fetch URL metadata
            print(f"📎 Creating link card for: {url[:60]}...")

            # Use atproto to create external embed with link metadata
            import requests
            from bs4 import BeautifulSoup

            # Fetch page metadata
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                page_response = requests.get(url, headers=headers, timeout=5)
                soup = BeautifulSoup(page_response.content, 'html.parser')

                # Extract metadata
                title = soup.find('meta', property='og:title')
                description = soup.find('meta', property='og:description')
                image = soup.find('meta', property='og:image')

                external = models.AppBskyEmbedExternal.External(
                    uri=url,
                    title=(title['content'] if title else url)[:300],
                    description=(description['content'] if description else '')[:300],
                    thumb=None  # Could upload image here if needed
                )

                embed = models.AppBskyEmbedExternal.Main(external=external)

                response = self.client.send_post(
                    text=url,
                    reply_to=reply_ref,
                    embed=embed
                )

                print(f"✓ Reply with link card posted! URI: {response.uri}")
                return {
                    'uri': response.uri,
                    'cid': response.cid
                }

            except Exception as embed_error:
                print(f"⚠️  Link card creation failed: {embed_error}")
                # Fall back to simple post without embed
                response = self.client.send_post(
                    text=url,
                    reply_to=reply_ref
                )

                print(f"✓ Reply posted (text only): {response.uri}")
                return {
                    'uri': response.uri,
                    'cid': response.cid
                }

        except Exception as e:
            print(f"✗ Error posting reply with link: {e}")
            # Fall back to regular reply
            print(f"   Trying fallback to text-only reply...")
            return self.reply_to_skeet(parent_uri, url)

    def reply_to_skeet(self, parent_uri: str, text: str) -> Optional[dict]:
        """
        Reply to a specific skeet

        Args:
            parent_uri: URI of the post to reply to (format: at://did/collection/rkey)
            text: Reply content

        Returns:
            Post data if successful, None if failed
        """
        try:
            if len(text) > 300:
                text = _truncate_at_sentence(text, 300)

            # Parse AT URI: at://did:plc:xxx/app.bsky.feed.post/rkey
            # Extract repo (DID) and rkey
            parts = parent_uri.replace('at://', '').split('/')
            if len(parts) != 3:
                raise ValueError(f"Invalid AT URI format: {parent_uri}")

            repo_did = parts[0]  # did:plc:xxx
            collection = parts[1]  # app.bsky.feed.post
            rkey = parts[2]  # post ID

            # Get the parent post using repo and rkey
            from atproto import models

            parent_ref = models.ComAtprotoRepoStrongRef.Main(
                uri=parent_uri,
                cid=''  # We'll let atproto fetch the CID
            )

            # Get the actual post to get its CID
            post_thread = self.client.app.bsky.feed.get_post_thread({'uri': parent_uri})
            parent_cid = post_thread.thread.post.cid

            # Create proper references with CIDs
            parent_ref_with_cid = models.ComAtprotoRepoStrongRef.Main(
                uri=parent_uri,
                cid=parent_cid
            )

            reply_ref = models.AppBskyFeedPost.ReplyRef(
                parent=parent_ref_with_cid,
                root=parent_ref_with_cid  # Same as parent since it's direct reply
            )

            # Post reply
            response = self.client.send_post(
                text=text,
                reply_to=reply_ref
            )

            print(f"✓ Reply posted successfully! URI: {response.uri}")
            return {
                'uri': response.uri,
                'cid': response.cid
            }
        except Exception as e:
            print(f"✗ Error posting reply: {e}")
            return None

    def is_post_liked(self, uri: str) -> bool:
        """
        Check if we have already liked a post.

        Args:
            uri: AT URI of the post to check

        Returns:
            True if already liked, False otherwise
        """
        try:
            response = self.client.app.bsky.feed.get_posts({'uris': [uri]})
            if response.posts:
                post = response.posts[0]
                # viewer.like contains the URI of our like record if we've liked it
                if hasattr(post, 'viewer') and post.viewer and hasattr(post.viewer, 'like') and post.viewer.like:
                    return True
            return False
        except Exception as e:
            print(f"✗ Error checking if post liked: {e}")
            # If we can't check, assume not liked to avoid blocking legitimate likes
            return False

    def like_post(self, uri: str, cid: str) -> bool:
        """
        Like a post on Bluesky (only if not already liked)

        Args:
            uri: AT URI of the post to like
            cid: CID of the post to like

        Returns:
            True if successfully liked, False if already liked or failed
        """
        try:
            # Check if we've already liked this post
            if self.is_post_liked(uri):
                print(f"⏭ Already liked post: {uri}")
                return False

            self.client.like(uri, cid)
            print(f"✓ Liked post: {uri}")
            return True
        except Exception as e:
            print(f"✗ Error liking post: {e}")
            return False

    def get_notifications(self, limit: int = 50) -> list:
        """
        Get recent notifications (mentions, replies, likes, reposts, follows)

        Args:
            limit: Maximum notifications to fetch

        Returns:
            List of notification objects
        """
        try:
            response = self.client.app.bsky.notification.list_notifications(
                {'limit': limit}
            )
            return response.notifications if response.notifications else []
        except Exception as e:
            print(f"✗ Error fetching notifications: {e}")
            return []

    def get_mentions(self, limit: int = 50) -> list:
        """
        Get posts that mention us (filtered from notifications)

        Args:
            limit: Maximum notifications to check

        Returns:
            List of posts that mention us
        """
        notifications = self.get_notifications(limit)
        mentions = []

        for notif in notifications:
            # Filter for mentions and replies
            if notif.reason in ['mention', 'reply']:
                mentions.append({
                    'uri': notif.uri,
                    'cid': notif.cid,
                    'author': notif.author.handle,
                    'reason': notif.reason,
                    'indexed_at': notif.indexed_at,
                    'is_read': notif.is_read
                })

        return mentions

    def like_mentions(self, limit: int = 50, liked_cache: set = None) -> dict:
        """
        Like all posts that mention us (that we haven't already liked)

        Args:
            limit: Maximum notifications to check
            liked_cache: Set of URIs we've already liked (to avoid duplicates)

        Returns:
            Dict with counts of liked and skipped posts, and URIs liked
        """
        mentions = self.get_mentions(limit)
        liked = 0
        skipped = 0
        already_liked = 0
        liked_uris = []

        if liked_cache is None:
            liked_cache = set()

        for mention in mentions:
            uri = mention['uri']

            # Skip if we've already liked this
            if uri in liked_cache:
                already_liked += 1
                continue

            # Try to like the post
            if self.like_post(uri, mention['cid']):
                liked += 1
                liked_uris.append(uri)
            else:
                # Likely already liked or error
                skipped += 1

        print(f"📊 Liked {liked} mentions, skipped {skipped}, already in cache {already_liked}")
        return {'liked': liked, 'skipped': skipped, 'already_cached': already_liked, 'liked_uris': liked_uris}

    def delete_post(self, post_uri: str) -> bool:
        """
        Delete a post

        Args:
            post_uri: URI of the post to delete (format: at://did/collection/rkey)

        Returns:
            True if successful, False if failed
        """
        try:
            # Parse AT URI to get repo and rkey
            parts = post_uri.replace('at://', '').split('/')
            if len(parts) != 3:
                raise ValueError(f"Invalid AT URI format: {post_uri}")

            repo_did = parts[0]
            collection = parts[1]
            rkey = parts[2]

            # Delete the post
            self.client.com.atproto.repo.delete_record(
                models.ComAtprotoRepoDeleteRecord.Data(
                    repo=repo_did,
                    collection=collection,
                    rkey=rkey
                )
            )

            print(f"✓ Post deleted successfully! URI: {post_uri}")
            return True
        except Exception as e:
            print(f"✗ Error deleting post: {e}")
            return False
