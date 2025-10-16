"""
AI-powered content generation using Anthropic Claude
"""
import os
from anthropic import Anthropic
from typing import Optional, List
import yaml


class ContentGenerator:
    """Generates tweet content using Claude AI"""

    def __init__(self, config_path: str = None):
        """Initialize content generator with configuration"""
        # Load configuration from parent directory if not specified
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')

        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Initialize Anthropic client
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Missing ANTHROPIC_API_KEY. Check your .env file.")

        self.client = Anthropic(api_key=api_key)
        self.model = self.config['content']['model']
        self.topics = self.config['content']['topics']
        self.style = self.config['content']['style']
        self.max_length = self.config['content']['max_length']
        self.avoid_topics = self.config['safety']['avoid_topics']

    def generate_tweet(self, topic: Optional[str] = None) -> str:
        """
        Generate a single tweet using Claude

        Args:
            topic: Specific topic to tweet about (optional, uses random if not provided)

        Returns:
            Generated tweet text
        """
        if topic is None:
            import random
            topic = random.choice(self.topics)

        prompt = self._build_prompt(topic)

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            tweet = message.content[0].text.strip()

            # Ensure it fits within character limit
            if len(tweet) > self.max_length:
                tweet = tweet[:self.max_length - 3] + "..."

            print(f"✓ Generated tweet ({len(tweet)} chars): {tweet[:50]}...")
            return tweet

        except Exception as e:
            print(f"✗ Error generating content: {e}")
            # Fallback tweet
            return f"Just thinking about {topic} today... #dev"

    def _build_prompt(self, topic: str) -> str:
        """Build the prompt for Claude"""
        avoid_str = ", ".join(self.avoid_topics)

        prompt = f"""Generate a single engaging tweet about: {topic}

Requirements:
- Maximum {self.max_length} characters (this is strict!)
- Tone: {self.style}
- Make it interesting, authentic, and valuable to readers
- Do NOT include hashtags unless they feel natural
- Avoid topics like: {avoid_str}
- Don't use quotes around the tweet - just return the raw text
- Make it sound like a real person, not a bot

Just return the tweet text itself, nothing else."""

        return prompt

    def generate_reply(self, original_tweet: str, context: Optional[str] = None) -> str:
        """
        Generate a reply to a tweet

        Args:
            original_tweet: The tweet to reply to
            context: Additional context (optional)

        Returns:
            Generated reply text
        """
        prompt = f"""Generate a helpful, friendly reply to this tweet:

"{original_tweet}"

Requirements:
- Maximum {self.max_length} characters
- Tone: {self.style}
- Be helpful and add value
- Don't be spammy or promotional
- Keep it conversational
{f"- Context: {context}" if context else ""}

Just return the reply text itself, nothing else."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            reply = message.content[0].text.strip()

            if len(reply) > self.max_length:
                reply = reply[:self.max_length - 3] + "..."

            print(f"✓ Generated reply ({len(reply)} chars)")
            return reply

        except Exception as e:
            print(f"✗ Error generating reply: {e}")
            return "Thanks for sharing! 👍"
