"""
AI-powered content generation using Anthropic Claude
"""
import os
from anthropic import Anthropic
from typing import Optional, List, Dict
import yaml
import random
from datetime import datetime


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
        self.engagement_hooks = self.config['content'].get('engagement_hooks', [])
        self.time_of_day = self.config['content'].get('time_of_day', {})
        self.cat_humor = self.config['content'].get('cat_humor', [])
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
        # ALWAYS post source reply if we have story metadata
        is_specific_story = story_metadata is not None

        # Build article details string if we have metadata
        article_details = None
        if is_specific_story and story_metadata:
            article_details = f"Title: {story_metadata.get('title', '')}\n"
            if story_metadata.get('context'):
                article_details += f"Summary: {story_metadata.get('context', '')}"

        prompt = self._build_news_cat_prompt(selected_topic, is_specific_story=is_specific_story,
                                             article_details=article_details)

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

            # Add source indicator if this story will have a source reply
            source_indicator = " 📰↓"
            if is_specific_story:
                # Reserve space for source indicator
                max_content_length = self.max_length - len(source_indicator)
                if len(tweet) > max_content_length:
                    tweet = tweet[:max_content_length - 3] + "..."
                tweet += source_indicator
            else:
                # No source reply, use full character limit
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
                'tweet': f"This reporter is looking into {selected_topic}.\n\nFur-ther details coming soon from my perch.",
                'needs_source_reply': False,
                'story_metadata': None
            }

    def _build_news_cat_prompt(self, topic: str, is_specific_story: bool = False,
                               article_details: str = None) -> str:
        """Build the news cat reporter prompt for Claude"""
        avoid_str = ", ".join(self.avoid_topics)
        cat_vocab_str = ", ".join(self.cat_vocabulary[:10])  # Show examples
        guidelines_str = "\n- ".join(self.editorial_guidelines)

        # Determine time of day for context
        hour = datetime.now().hour
        if 5 <= hour < 12:
            time_period = "morning"
        elif 12 <= hour < 18:
            time_period = "afternoon"
        else:
            time_period = "evening"

        time_phrases = self.time_of_day.get(time_period, [])
        time_phrases_str = ", ".join(time_phrases) if time_phrases else ""

        # Get examples of new features
        engagement_str = ", ".join(self.engagement_hooks[:3]) if self.engagement_hooks else ""
        cat_humor_str = ", ".join(self.cat_humor) if self.cat_humor else ""

        # Add specific guidance for real trending stories
        story_guidance = ""
        if is_specific_story and article_details:
            story_guidance = f"""
IMPORTANT - Real Story Coverage:
- You are writing about this actual article:
  {article_details}

- Write cat news commentary based on the article above
- Provide objective analysis and context from the article
- Do NOT fabricate specific details not in the article
- Focus on significance and implications
- A source citation will be added in a follow-up reply
"""
        elif is_specific_story:
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
STYLE & VOICE:
- {self.style}
- Fact-based reporting with context
- Populist/skeptical perspective: Question power, follow the money, focus on regular people
- Human interest angle first
- Professional but with occasional cheeky cat phrases

TIME CONTEXT:
- It's currently {time_period}
- Optional {time_period} phrases: {time_phrases_str}
- Use naturally if appropriate, or skip entirely

NEW VOICE FEATURES (use occasionally, not every tweet):
- Cat observer angle: "Watching humans [do thing]. Here's what this cat sees..."
- Self-aware humor (can extend slightly past {self.max_length}): {cat_humor_str}
- Engagement hooks at end: {engagement_str}

FORMAT:
- Maximum {self.max_length} characters (can extend slightly for self-aware humor)
- Use ACTUAL line breaks between distinct thoughts/sentences for readability
- NO emojis (very rare exceptions only)
- Hashtags: place at the end, never repeat the same hashtag
- For ACTUAL breaking news: can start with "#BreakingMews: [content]"
- For commentary/trends: skip "Breaking mews" phrase entirely - it's not breaking
- Don't use quotes around the tweet
- Write as if filing a news report
- IMPORTANT: Use real line breaks, not \\n escape sequences

EXAMPLES OF GOOD STRUCTURE:
Breaking news:
"#BreakingMews: Senate passes bill 68-32

Bipartisan wins happen when pressure mounts. #Politics"

Commentary:
"Gen Z trends shifting again.

Paws for thought—cycles repeat. #Culture"

Skeptical populist angle:
"White House announces new program. Interesting timing.

Follow the money—who benefits? #Politics"

Cat observer angle:
"Watching humans debate this for weeks.

Even this cat can see the real issue is [X]. Thoughts?"

AVOID:
- {avoid_str}
- Using "Breaking mews" for non-urgent stories or commentary
- Cramming sentences together without line breaks
- Repeating hashtags (especially #BreakingMews at start AND end)
- Clickbait or engagement farming
- Forced cat puns that don't fit
- Being overly partisan (populist lean is OK)
- Fabricating specific details like exact numbers, times, locations
- Overusing new features—mix them naturally with standard reporting

Just return the tweet text itself, nothing else."""

        return prompt

    def generate_source_reply(self, original_tweet: str, story_metadata: Dict) -> str:
        """
        Generate a source citation reply to the original tweet

        Args:
            original_tweet: The tweet to reply to with source
            story_metadata: Dictionary with 'title', 'context', 'source', 'url' (optional)

        Returns:
            Source citation tweet text
        """
        title = story_metadata.get('title', 'Story')
        url = story_metadata.get('url')
        source = story_metadata.get('source', 'Google Trends')

        # Build source reply with URL if available
        if url:
            # X/Twitter only shows full link preview cards when posting JUST the URL
            # Any text before URL prevents preview from showing
            reply = url
        else:
            # Fallback format without URL
            context = story_metadata.get('context', '')
            reply = f"Source: {title}\n{context}\nVia {source}"

            # Ensure it fits (only needed for non-URL fallback)
            if len(reply) > self.max_length:
                reply = reply[:self.max_length - 3] + "..."

        print(f"✓ Generated source reply (URL only for full link preview card)")
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

    def generate_image_prompt(self, topic: str, tweet_text: str) -> str:
        """
        Generate an image prompt for Grok based on the news topic

        Args:
            topic: The news topic
            tweet_text: The generated tweet text

        Returns:
            Image generation prompt for Grok
        """
        try:
            prompt_request = f"""You are helping create an image for a news cat reporter bot on X/Twitter.

The news topic is: {topic}

The tweet says: {tweet_text}

Generate a SHORT image prompt (max 200 chars) for an AI image generator that would create a professional, editorial-style illustration for this news story.

Requirements:
- **WIDESCREEN LANDSCAPE format** - think cinematic, horizontal, wide angle
- Professional news/editorial illustration style
- Bold, clean, modern digital art aesthetic
- MUST visually represent the MAIN IDEA of the story (not just the surface topic)
- Show people/action relevant to the story (e.g., if about "choosing intimacy," show friends together, not isolation)
- **IMPORTANT: Include a professional news reporter cat in the scene MOST OF THE TIME** (80%+ of images should feature the cat reporter)
- The cat should be: anthropomorphic tabby cat in reporter attire (press badge, notepad), serious professional demeanor
- Cat can be: reporting on scene, interviewing subjects, observing from newsdesk, etc.
- Suitable for social media (no text in image)
- Think about what SCENE or IMAGE best captures the story's meaning
- Avoid generic or contradictory imagery

Examples WITH cat reporter (PREFERRED):
- Story about "Gen Z choosing intimacy over influencers" → "Orange tabby cat reporter with press badge interviewing diverse group of young friends in cozy cafe, notepad in paw, warm lighting, modern editorial photography"
- Story about "Senate infrastructure bill" → "Professional cat reporter in suit broadcasting from US Capitol with construction cranes, holding microphone, bold patriotic colors, breaking news style"
- Story about "economic growth" → "Tabby cat news anchor at desk with upward trending charts behind, wearing glasses and press badge, celebratory business scene, clean illustration"

Examples WITHOUT cat (use sparingly for very specific stories):
- Story about "intimate moment" where cat would detract → "Close-up of hands holding, warm lighting, authentic human connection"

Analyze the tweet carefully and create a prompt that captures the ESSENCE and EMOTION of the story. INCLUDE THE CAT REPORTER unless it would significantly harm the story's message.

Just return the SHORT image prompt itself, nothing else."""

            message = self.client.messages.create(
                model=self.model,
                max_tokens=200,  # Increased for more detailed, contextual prompts
                messages=[
                    {"role": "user", "content": prompt_request}
                ]
            )

            image_prompt = message.content[0].text.strip()

            # Remove quotes if Claude added them
            if image_prompt.startswith('"') and image_prompt.endswith('"'):
                image_prompt = image_prompt[1:-1]

            # Limit to 200 chars for Grok
            if len(image_prompt) > 200:
                image_prompt = image_prompt[:200]

            print(f"✓ Generated image prompt: {image_prompt}")
            return image_prompt

        except Exception as e:
            print(f"✗ Error generating image prompt: {e}")
            # Fallback to simple prompt with cat reporter
            return f"Professional tabby cat news reporter covering {topic[:80]}, landscape editorial illustration, 16:9 format"
