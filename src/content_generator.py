"""
AI-powered content generation using Anthropic Claude
"""
import os
from anthropic import Anthropic
from typing import Optional, List, Dict
import yaml
import random


class ContentGenerator:
    """Generates news cat reporter tweet content using Claude AI"""

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
        self.persona = self.config['content'].get('persona', 'news reporter')
        self.cat_vocabulary = self.config['content'].get('cat_vocabulary', [])
        self.editorial_guidelines = self.config['content'].get('editorial_guidelines', [])
        self.max_length = self.config['content']['max_length']
        self.avoid_topics = self.config['safety']['avoid_topics']

    def generate_tweet(self, topic: Optional[str] = None, trending_topic: Optional[str] = None,
                      story_metadata: Optional[Dict] = None) -> Dict:
        """
        Generate a news cat reporter tweet

        Args:
            topic: General news category (optional, uses random if not provided)
            trending_topic: Specific trending topic from X (takes priority)
            story_metadata: Dictionary with 'title', 'context', 'source' for real trending stories

        Returns:
            Dictionary with:
                - 'tweet': Generated tweet text
                - 'needs_source_reply': Boolean indicating if source reply needed
                - 'story_metadata': Original story metadata (if provided)
        """
        # Prefer trending topic, fallback to general topic
        if trending_topic:
            selected_topic = trending_topic
            print(f"📰 Generating cat news about trending topic: {trending_topic}")
        elif topic:
            selected_topic = topic
        else:
            selected_topic = random.choice(self.topics)
            print(f"📰 Generating cat news about: {selected_topic}")

        # Determine if this is a specific story that needs sourcing
        is_specific_story = story_metadata is not None and story_metadata.get('source') != 'Fallback'

        prompt = self._build_news_cat_prompt(selected_topic, is_specific_story=is_specific_story)

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=350,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            tweet = message.content[0].text.strip()

            # Remove any quotes around the tweet if Claude added them
            if tweet.startswith('"') and tweet.endswith('"'):
                tweet = tweet[1:-1]
            if tweet.startswith("'") and tweet.endswith("'"):
                tweet = tweet[1:-1]

            # Ensure it fits within character limit
            if len(tweet) > self.max_length:
                tweet = tweet[:self.max_length - 3] + "..."

            print(f"✓ Generated cat news ({len(tweet)} chars): {tweet[:60]}...")

            return {
                'tweet': tweet,
                'needs_source_reply': is_specific_story,
                'story_metadata': story_metadata
            }

        except Exception as e:
            print(f"✗ Error generating content: {e}")
            # Fallback tweet in cat reporter style
            return {
                'tweet': f"Breaking mews: Updates on {selected_topic}. Stay tuned for fur-ther details. #BreakingMews",
                'needs_source_reply': False,
                'story_metadata': None
            }

    def _build_news_cat_prompt(self, topic: str, is_specific_story: bool = False) -> str:
        """Build the news cat reporter prompt for Claude"""
        avoid_str = ", ".join(self.avoid_topics)
        cat_vocab_str = ", ".join(self.cat_vocabulary[:8])  # Show examples
        guidelines_str = "\n- ".join(self.editorial_guidelines)

        # Add specific guidance for real trending stories
        story_guidance = ""
        if is_specific_story:
            story_guidance = """
IMPORTANT - Real Story Coverage:
- This is a real trending topic, not commentary
- Provide objective analysis and context
- Avoid fabricating specific details (numbers, locations, quotes)
- Focus on general significance and implications
- A source citation will be added in a follow-up reply
"""

        prompt = f"""You are a professional news reporter who happens to be a cat. Generate a single tweet reporting on: {topic}

CHARACTER:
- Professional journalist cat who takes news seriously
- Use cat-themed wordplay naturally (not forced)
- Examples: "{cat_vocab_str}"
- Goal: Be the most respected feline in news

CONTENT GUIDELINES:
- {guidelines_str}
{story_guidance}
STYLE:
- {self.style}
- Fact-based reporting with context
- Center-right/populist perspective where relevant
- Human interest angle
- Professional but with occasional cheeky cat phrases

FORMAT:
- Maximum {self.max_length} characters (strict!)
- NO emojis (very rare exceptions only)
- Hashtags are good (especially #BreakingMews for branding)
- Add relevant trending hashtags when appropriate
- Don't use quotes around the tweet
- Write as if filing a news report

AVOID:
- {avoid_str}
- Clickbait or engagement farming
- Forced cat puns that don't fit
- Being overly partisan (populist lean is OK)
- Fabricating specific details like exact numbers, times, locations

Just return the tweet text itself, nothing else."""

        return prompt

    def generate_source_reply(self, original_tweet: str, story_metadata: Dict) -> str:
        """
        Generate a source citation reply to the original tweet

        Args:
            original_tweet: The tweet to reply to with source
            story_metadata: Dictionary with 'title', 'context', 'source'

        Returns:
            Source citation tweet text
        """
        title = story_metadata.get('title', 'Story')
        context = story_metadata.get('context', '')
        source = story_metadata.get('source', 'Google Trends')

        # Build source reply
        reply = f"Source: {title}\n{context}\nVia {source}"

        # Ensure it fits
        if len(reply) > self.max_length:
            reply = reply[:self.max_length - 3] + "..."

        print(f"✓ Generated source reply ({len(reply)} chars)")
        return reply

    def generate_reply(self, original_tweet: str, context: Optional[str] = None) -> str:
        """
        Generate a cat reporter reply to a tweet

        Args:
            original_tweet: The tweet to reply to
            context: Additional context (optional)

        Returns:
            Generated reply text in cat reporter style
        """
        cat_vocab_str = ", ".join(self.cat_vocabulary[:5])

        prompt = f"""You are a professional news reporter cat replying to this tweet:

"{original_tweet}"

Reply as the news cat reporter:
- {self.style}
- Use cat wordplay naturally: {cat_vocab_str}
- Add value to the conversation
- Stay on-brand as a news reporter
- Be engaging but professional
- Maximum {self.max_length} characters
- NO emojis (rare exceptions)
- Hashtags OK if relevant
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

            # Remove quotes if present
            if reply.startswith('"') and reply.endswith('"'):
                reply = reply[1:-1]

            if len(reply) > self.max_length:
                reply = reply[:self.max_length - 3] + "..."

            print(f"✓ Generated cat reply ({len(reply)} chars)")
            return reply

        except Exception as e:
            print(f"✗ Error generating reply: {e}")
            return "Thanks for sharing! This reporter is taking notes. #BreakingMews"
