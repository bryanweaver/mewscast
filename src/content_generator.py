"""
AI-powered content generation using Anthropic Claude
"""
import os
import json
from anthropic import Anthropic
from typing import Optional, List, Dict
import yaml
import random
from datetime import datetime
from prompt_loader import get_prompt_loader


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

        # Post angle settings (populist vs framing)
        post_angles = self.config.get('post_angles', {})
        self.framing_chance = post_angles.get('framing_chance', 0.5)

        # Initialize prompt loader
        self.prompts = get_prompt_loader()

    def generate_tweet(self, topic: Optional[str] = None, trending_topic: Optional[str] = None,
                      story_metadata: Optional[Dict] = None, previous_posts: Optional[List[Dict]] = None) -> Dict:
        """
        Generate a news cat reporter tweet

        Args:
            topic: General news category (optional, uses random if not provided)
            trending_topic: Specific trending topic from X (takes priority)
            story_metadata: Dictionary with 'title', 'context', 'source' for real trending stories
            previous_posts: List of previous related posts (for updates/developing stories)

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

        # Randomly choose post angle: populist vs framing
        # Both are catty and punny, just different focus
        use_framing_angle = False
        media_issues = None

        if is_specific_story and story_metadata and story_metadata.get('article_content'):
            # Coin flip to decide if we try framing angle
            if random.random() < self.framing_chance:
                # Try framing angle - analyze how media presents the story
                media_issues = self.analyze_media_framing(story_metadata)
                # Only use framing if there's actually something to call out
                if media_issues and media_issues.get('has_issues', False):
                    use_framing_angle = True
                # Otherwise fall through to populist angle

        # Build appropriate prompt based on chosen angle
        if use_framing_angle and media_issues:
            # Framing angle - how media spins/frames the story
            prompt = self._build_framing_prompt(
                story_metadata,
                media_issues
            )
        else:
            # Use regular news cat prompt (existing behavior)
            # Build article details string if we have metadata
            # CRITICAL: Require article_content for specific stories to prevent "can't read" tweets
            article_details = None
            if is_specific_story and story_metadata:
                # Validate we have actual content (not just title/description)
                if not story_metadata.get('article_content'):
                    print("⚠️  WARNING: No article content available - should not generate tweet")
                    print("   (This prevents 'can't read the article' tweets)")
                    # Still generate but with extra safeguards in prompt

                article_details = f"Title: {story_metadata.get('title', '')}\n"
                article_details += f"Source: {story_metadata.get('source', '')}\n"
                if story_metadata.get('article_content'):
                    article_details += f"Article Content:\n{story_metadata.get('article_content', '')}\n"
                elif story_metadata.get('context'):
                    article_details += f"Summary: {story_metadata.get('context', '')}"

            prompt = self._build_news_cat_prompt(selected_topic, is_specific_story=is_specific_story,
                                                 article_details=article_details, previous_posts=previous_posts)

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

            # Calculate target length (reserve space for source indicator if needed)
            source_indicator = " 📰↓"
            if is_specific_story:
                max_content_length = self.max_length - len(source_indicator)
            else:
                max_content_length = self.max_length

            # Retry mechanism: if too long, ask Claude to shorten (up to 3 attempts)
            max_retries = 3
            for attempt in range(max_retries):
                if len(tweet) <= max_content_length:
                    break  # Fits within limit, we're done

                if attempt < max_retries - 1:
                    # Ask Claude to shorten
                    print(f"⚠️  Tweet too long ({len(tweet)} chars > {max_content_length}). Asking Claude to shorten (attempt {attempt + 1})...")
                    tweet = self._shorten_tweet(tweet, max_content_length)
                else:
                    # Final attempt failed, truncate at word boundary as last resort
                    print(f"⚠️  Still too long after retries. Truncating at word boundary...")
                    cutoff = max_content_length - 3
                    last_space = tweet.rfind(' ', 0, cutoff)
                    if last_space > cutoff // 2:
                        tweet = tweet[:last_space] + "..."
                    else:
                        tweet = tweet[:cutoff] + "..."

            # Add source indicator if this story will have a source reply
            if is_specific_story:
                tweet += source_indicator

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

    def _shorten_tweet(self, tweet: str, max_length: int) -> str:
        """
        Ask Claude to shorten a tweet that exceeds the character limit.

        Args:
            tweet: The tweet text that's too long
            max_length: Maximum allowed characters

        Returns:
            Shortened tweet text
        """
        prompt = self.prompts.load_shorten_tweet(
            current_length=len(tweet),
            max_length=max_length,
            tweet=tweet
        )

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            shortened = message.content[0].text.strip()

            # Remove quotes if Claude added them
            if shortened.startswith('"') and shortened.endswith('"'):
                shortened = shortened[1:-1]
            if shortened.startswith("'") and shortened.endswith("'"):
                shortened = shortened[1:-1]

            print(f"   ✓ Shortened to {len(shortened)} chars")
            return shortened

        except Exception as e:
            print(f"   ✗ Error shortening: {e}")
            return tweet  # Return original if shortening fails

    def _build_news_cat_prompt(self, topic: str, is_specific_story: bool = False,
                               article_details: str = None, previous_posts: Optional[List[Dict]] = None) -> str:
        """Build the news cat reporter prompt for Claude using prompt templates"""
        # Prepare config-based values
        avoid_str = ", ".join(self.avoid_topics)
        cat_vocab_str = ", ".join(self.cat_vocabulary[:10])
        guidelines_str = "\n- ".join(self.editorial_guidelines)

        # Calculate actual max length for the prompt
        source_indicator_length = 4  # " 📰↓"
        if is_specific_story:
            prompt_max_length = self.max_length - source_indicator_length
        else:
            prompt_max_length = self.max_length

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

        engagement_str = ", ".join(self.engagement_hooks[:3]) if self.engagement_hooks else ""
        cat_humor_str = ", ".join(self.cat_humor) if self.cat_humor else ""

        # Build conditional sections
        story_guidance = ""
        update_guidance = ""

        # Check if this is an update to previous coverage
        if previous_posts and len(previous_posts) > 0:
            prev_context = []
            for i, prev in enumerate(previous_posts[:2], 1):
                prev_post = prev.get('post', {})
                prev_content = prev_post.get('content', '')
                prev_title = prev_post.get('topic', '')
                prev_time = prev_post.get('timestamp', '')
                if prev_time:
                    try:
                        dt = datetime.fromisoformat(prev_time.replace('Z', '+00:00'))
                        time_str = dt.strftime('%b %d at %I:%M%p')
                    except:
                        time_str = 'recently'
                else:
                    time_str = 'recently'
                prev_context.append(f"Post #{i} ({time_str}):\n   Title: {prev_title}\n   Content: {prev_content}")

            prev_context_str = "\n\n".join(prev_context)
            update_guidance = self.prompts.load_update_guidance(prev_context_str=prev_context_str)

        # Build story guidance based on what info we have
        if is_specific_story and article_details:
            story_guidance = self.prompts.load_story_guidance_with_article(article_details=article_details)
        elif is_specific_story:
            story_guidance = self.prompts.load_story_guidance_generic()

        # Load main prompt template and fill in values
        return self.prompts.load_tweet_prompt(
            topic=topic,
            update_guidance=update_guidance,
            cat_vocab_str=cat_vocab_str,
            guidelines_str=guidelines_str,
            story_guidance=story_guidance,
            style=self.style,
            time_period=time_period,
            time_phrases_str=time_phrases_str,
            cat_humor_str=cat_humor_str,
            engagement_str=engagement_str,
            prompt_max_length=prompt_max_length,
            avoid_str=avoid_str
        )

    def analyze_media_framing(self, story_metadata: Dict) -> Dict:
        """
        Quick check for interesting framing angles in a news story

        Returns:
            Dictionary with 'has_issues', 'angle' (brief description of framing to note)
        """
        if not story_metadata or not story_metadata.get('article_content'):
            return {'has_issues': False, 'angle': None}

        title = story_metadata.get('title', '')
        content = story_metadata.get('article_content', '')
        source = story_metadata.get('source', '')

        prompt = self.prompts.load_framing_analysis(
            title=title,
            source=source,
            content=content
        )

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()

            # Parse JSON
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0].strip()
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0].strip()

            return json.loads(response_text)

        except Exception:
            return {'has_issues': False, 'angle': None}

    def _build_framing_prompt(self, story_metadata: Dict,
                               media_issues: Dict) -> str:
        """Build a prompt noting how media frames the story - same catty tone, different angle"""

        title = story_metadata.get('title', '')
        source = story_metadata.get('source', '')
        content = story_metadata.get('article_content', '')[:800]  # Truncate for prompt
        framing_angle = media_issues.get('angle', '')

        cat_vocab_str = ", ".join(self.cat_vocabulary[:10])
        cat_humor_str = ", ".join(self.cat_humor) if self.cat_humor else ""

        return self.prompts.load_framing_tweet(
            title=title,
            source=source,
            framing_angle=framing_angle,
            content=content,
            cat_vocab_str=cat_vocab_str,
            cat_humor_str=cat_humor_str,
            style=self.style
        )

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
        context_line = f"- Context: {context}" if context else ""

        prompt = self.prompts.load_reply(
            original_tweet=original_tweet,
            style=self.style,
            cat_vocab_str=cat_vocab_str,
            max_length=self.max_length,
            context_line=context_line
        )

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

    def generate_image_prompt(self, topic: str, tweet_text: str, article_content: str = None) -> str:
        """
        Generate an image prompt for Grok based on the news topic

        Args:
            topic: The news topic
            tweet_text: The generated tweet text
            article_content: Full article content for extracting visual details

        Returns:
            Image generation prompt for Grok
        """
        try:
            # Build article context section if available
            article_section = ""
            if article_content:
                truncated_content = article_content[:1500] if len(article_content) > 1500 else article_content
                article_section = f"""
FULL ARTICLE CONTENT (extract visual details from this):
{truncated_content}

"""

            prompt_request = self.prompts.load_image_prompt(
                topic=topic,
                tweet_text=tweet_text,
                article_section=article_section
            )

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
            # Fallback to dramatic prompt with cat reporter ALWAYS
            return f"Dramatic film noir: Tabby detective cat investigating {topic[:60]}, cinematic lighting, widescreen landscape, press badge visible"
