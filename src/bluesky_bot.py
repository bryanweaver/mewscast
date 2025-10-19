"""
Bluesky integration using atproto
"""
import os
from atproto import Client
from typing import Optional


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
                text = text[:297] + "..."

            response = self.client.send_post(text=text)
            print(f"✓ Skeet posted successfully! URI: {response.uri}")
            return {
                'uri': response.uri,
                'cid': response.cid
            }
        except Exception as e:
            print(f"✗ Error posting skeet: {e}")
            return None

    def post_skeet_with_image(self, text: str, image_path: str) -> Optional[dict]:
        """
        Post a skeet with an attached image

        Args:
            text: The post content (max 300 characters, we use 280 for compatibility)
            image_path: Path to the image file to attach

        Returns:
            Post data if successful, None if failed
        """
        try:
            if len(text) > 300:
                print(f"Warning: Post too long ({len(text)} chars). Truncating...")
                text = text[:297] + "..."

            # Read image file
            with open(image_path, 'rb') as f:
                image_data = f.read()

            print(f"📤 Uploading image: {image_path}")

            # Post with image using atproto
            response = self.client.send_image(
                text=text,
                image=image_data,
                image_alt="News reporter cat illustration"
            )

            print(f"✓ Skeet with image posted successfully! URI: {response.uri}")
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

    def reply_to_skeet(self, parent_uri: str, text: str) -> Optional[dict]:
        """
        Reply to a specific skeet

        Args:
            parent_uri: URI of the post to reply to
            text: Reply content

        Returns:
            Post data if successful, None if failed
        """
        try:
            if len(text) > 300:
                text = text[:297] + "..."

            # Get the parent post to build reply reference
            parent_post = self.client.get_post(parent_uri)

            # Create reply reference
            from atproto import models

            reply_ref = models.AppBskyFeedPost.ReplyRef(
                parent=models.create_strong_ref(parent_post),
                root=models.create_strong_ref(parent_post)
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
