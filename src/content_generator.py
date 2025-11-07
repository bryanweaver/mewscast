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

        # Calculate actual max length for the prompt
        # If specific story, we'll add " 📰↓" (4 chars) after, so reduce limit
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
- You're a CAT reporter - include at least ONE cat reference/pun per tweet
- Cat wordplay should feel natural but be PRESENT in most tweets
- Context-specific phrases available: {cat_vocab_str}
- Goal: Sharp, engaging reporting with personality that readers trust

CONTENT GUIDELINES:
- {guidelines_str}
{story_guidance}
STYLE & VOICE:
- {self.style}
- PUNCHY over polite - tight, declarative sentences
- VERY POPULIST: Regular people vs. elites/establishment - always
- Center politically, not left or right
- Question power and official narratives - spare the spin
- Follow the money - who's getting paid?
- Fact-based with EDGE - call it what it is
- Make ONE sharp point - don't scatter
- Strong verbs, cut fluff, impact over explanation
- Point out subtext - what they're NOT saying matters
- Professional with BITE - not milquetoast
- Let readers connect dots themselves

TIME CONTEXT:
- It's currently {time_period}
- Optional {time_period} phrases: {time_phrases_str}
- Use naturally if appropriate, or skip entirely

CAT VOICE FEATURES (use frequently to show personality):
- Cat observer angle: "Watching humans [do thing]. Here's what this cat sees..." (use often)
- Self-aware humor: {cat_humor_str} (use regularly)
- Cat perspective: Reference being a cat, having nine lives, perching, etc.
- Natural wordplay: Work in one pun naturally per tweet when possible
- Engagement hooks at end: {engagement_str} (occasional)

FORMAT:
- Maximum {prompt_max_length} characters (STRICT - this is the HARD LIMIT)
- Use ACTUAL line breaks between distinct thoughts/sentences for readability
- Be clever but make sure it fits - don't get cut off mid-thought
- NO emojis (very rare exceptions only)
- NO hashtags EXCEPT #BreakingMews at the START for actual breaking news only
- Don't use quotes around the tweet
- Write as if filing a news report
- IMPORTANT: Use real line breaks, not \\n escape sequences
- Must fit completely within {prompt_max_length} chars - NO EXCEPTIONS

EXAMPLES OF GOOD STRUCTURE (note cat references in each):

Breaking news with cat voice:
"#BreakingMews: Senate passes bill 68-32.

Rare bipartisan moment. Even this cat is surprised. Pressure from regular folks works."

Regular news with subtle pun:
"GOP caves on shutdown. Again.

Chaos works for the loudest voice in the room. Fat cats always land on their feet."

Sharp populist angle with cat observer:
"New $2B program announced. Watch who gets contracts.

Follow the money. This reporter's seen enough to know how it ends."

Investigative tone with cat wordplay:
"Senate bill passes at midnight. Zero public hearings.

Timing smells fishy to this cat. Who benefits from the rush?"

Calling out subtext with cat perspective:
"Three days of headlines about AI video.

Translation: Real policy buried on page 6. From my perch, pattern's clear."

Skeptical/critical with natural pun:
"Administration promises 'transparency' on classified docs.

This cat's not buying the catnip. Watch what they do, not what they say."

Economic news with cat reference:
"Debt hits $38 trillion. Fastest climb since pandemic.

Someone's spending their nine lives worth of money. Guess who pays?"

AVOID:
- {avoid_str}
- Using any hashtags except #BreakingMews at the start
- Using #BreakingMews for non-breaking stories or commentary
- Putting hashtags at the end of posts
- Milquetoast, wishy-washy commentary
- Over-explaining - let readers connect dots
- Cramming sentences together without line breaks
- Clickbait or engagement farming
- Being TOO serious - you're a cat! Show some personality
- Zero cat references in a tweet - you're a CAT reporter, act like it
- Overusing the same puns (vary your wordplay)
- Being left or right partisan (center/populist is good)
- Fabricating specific details like exact numbers, times, locations
- Making multiple scattered points that don't connect coherently
- Hedging when you should call it out
- Going over the character limit - make it fit!

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
- NO hashtags
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
            prompt_request = f"""You are helping create an engaging, visually striking image for a news cat reporter bot on X/Twitter.

The news topic is: {topic}

The tweet says: {tweet_text}

Generate a SHORT image prompt (max 200 chars) for an AI image generator that captures this story visually.

CRITICAL REQUIREMENTS:
- **WIDESCREEN LANDSCAPE format** - cinematic, horizontal composition
- **CAT MUST BE IN EVERY IMAGE** - MANDATORY, non-negotiable, always visible
- Image MUST be directly relevant to the story content (not generic)
- Capture the EMOTION and ESSENCE of the story, not just literal elements
- Think: What visual would make someone stop scrolling?
- Cat can be protagonist (center) or observer (background), but MUST be present

CONTENT MODERATION - AVOID THESE (will be rejected by AI):
- NO sick/injured people, especially children
- NO violence, weapons, or explicit medical imagery
- NO graphic suffering or disturbing content
- USE metaphors and symbols instead of literal depictions
- FOCUS on broader context (empty vaccine bottles, warning signs) not trauma
- For health stories: show prevention/consequences symbolically, not suffering

CAT REPORTER PRESENCE (MANDATORY - EVERY IMAGE MUST HAVE A CAT):
- 60% CAT AS PROTAGONIST: Front and center, actively investigating/reporting (rifling files, confronting subjects, dramatic action)
- 40% CAT AS OBSERVER: Present but background (watching from newsdesk, perched above, corner of scene, witnessing)
- 0% NO CAT: NEVER acceptable - this is a cat news reporter, cat MUST be visible in every image

VISUAL STYLE ROTATION (match to story tone - CAT ALWAYS PRESENT):
- **Political scandal/investigation** → Dramatic noir thriller with detective cat (smoke, shadows, tension, cat investigating)
- **Breaking political news** → Raw photojournalism with reporter cat on scene (chaos, urgency, cat witnessing history)
- **Power plays/corruption** → Bold satirical editorial with cat exposing truth (exaggerated, striking, cat as truth-teller)
- **Human interest** → Powerful documentary with empathetic cat observer (intimate, cat connecting with subjects)
- **Major events** → Epic blockbuster poster with cat protagonist (massive scale, cat in action, cinematic)
- **Tech/innovation** → Cyberpunk futuristic with tech-savvy cat (neon, dramatic, cat with future tech)
- **UFO/mysteries** → Cinematic sci-fi thriller with cat investigating (eerie lighting, cat witnessing unexplained)
- **Economic** → Striking infographic art with cat analyzing data (bold visual, cat making connections)
- **Celebrity/Entertainment** → Paparazzi aesthetic with reporter cat on scene (flashy, bold, cat getting the scoop)
- **Crisis/Breaking** → Apocalyptic cinematic with brave reporter cat (dramatic scale, cat documenting crisis)

EXAMPLES BY STORY TYPE:

Scandal/investigation (noir style with cat):
"Film noir: Tabby detective cat in trench coat examining documents under desk lamp, smoke and shadows, high contrast, 1940s detective aesthetic"

Political news (photojournalism, cat in scene):
"Documentary photo: Small cat reporter dwarfed by massive Capitol building, lone figure facing power, dramatic sunset, David vs Goliath"

Corruption story (political cartoon, cat as protagonist):
"Bold editorial illustration: Cat reporter following trail of money from Capitol to fat cats in suits, satirical style, high contrast colors"

Human interest (cat as empathetic observer):
"Intimate documentary: Tabby cat reporter observing from windowsill as elderly person embraces child, warm golden hour lighting, cat's reflective expression, hope and connection"

UFO story (atmospheric with cat):
"Cinematic wide shot: Tabby reporter observing glowing UFO over desert at night, eerie atmospheric lighting, X-Files aesthetic, mysterious"

Economic news (cat analyzing data):
"Bold infographic art: Tabby reporter cat pointing at massive rising debt chart, dramatic scale showing tiny people vs huge numbers, stark contrast, visual metaphor"

Health/medical news (symbolic, NO sick people):
"Cinematic shot: Tabby reporter cat examining empty vaccine vials and warning signs, dramatic lighting emphasizing consequences, metaphorical approach"

Analyze the tweet and topic. Choose style that matches the story's TONE. Make it visually compelling and story-specific.

REMEMBER: Cat reporter MUST be in the image. No exceptions. Every single image needs the cat visible.

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
            # Fallback to dramatic prompt with cat reporter ALWAYS
            return f"Dramatic film noir: Tabby detective cat investigating {topic[:60]}, cinematic lighting, widescreen landscape, press badge visible"
