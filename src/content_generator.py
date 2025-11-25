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

        # NEW: Check for media literacy issues first
        media_issues = None
        use_media_literacy_prompt = False

        if is_specific_story and story_metadata and story_metadata.get('article_content'):
            print("🔍 Analyzing article for media literacy issues...")
            media_issues = self.analyze_media_literacy(story_metadata)

            if media_issues.get('has_issues', False):
                severity = media_issues.get('severity', 'unknown')
                num_issues = len(media_issues.get('issues', []))

                # Only trigger media literacy response for medium or high severity issues
                if severity in ['medium', 'high']:
                    use_media_literacy_prompt = True
                    print(f"⚠️  Media literacy issues detected: {severity} severity, {num_issues} issue(s)")
                    print("   Will address these issues in the post")
                else:
                    print(f"INFO: Minor media literacy issues found ({severity} severity)")
                    print("   Using standard approach - issues not severe enough for media literacy response")
            else:
                print("✓ No significant media literacy issues found")
                print("   Using standard populist cat-snark approach")

        # Build appropriate prompt based on media literacy analysis
        if use_media_literacy_prompt:
            # Use media literacy prompt to address the issues
            prompt = self._build_media_literacy_prompt(
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
            # For media literacy posts, we may need to retry to get the right length
            max_retries = 3 if use_media_literacy_prompt else 1
            retry_count = 0

            while retry_count < max_retries:
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

                # Check length BEFORE adding source indicator
                source_indicator = " 📰↓"
                if is_specific_story:
                    max_content_length = self.max_length - len(source_indicator)
                else:
                    max_content_length = self.max_length

                # For media literacy posts, regenerate if too long
                if use_media_literacy_prompt and len(tweet) > max_content_length:
                    retry_count += 1
                    if retry_count < max_retries:
                        print(f"⚠️  Media literacy post too long ({len(tweet)} chars), regenerating (attempt {retry_count + 1}/{max_retries})...")
                        # Add stricter instruction to the prompt for retry
                        prompt = prompt.replace(
                            "STRICT LIMIT: 265 characters MAXIMUM (Twitter will cut you off!)",
                            f"STRICT LIMIT: {max_content_length} characters MAXIMUM - YOUR LAST ATTEMPT WAS {len(tweet)} CHARS (TOO LONG!). BE MORE CONCISE!"
                        )
                        continue
                    else:
                        print(f"⚠️  Failed to generate short enough media literacy post after {max_retries} attempts")
                        # Last resort: truncate but try to preserve complete thought
                        # Find last sentence boundary before limit
                        sentences = tweet.split('. ')
                        truncated = ""
                        for sentence in sentences:
                            if len(truncated + sentence + ". ") <= max_content_length:
                                truncated += sentence + ". "
                            else:
                                break
                        if truncated:
                            tweet = truncated.rstrip()
                        else:
                            # No complete sentence fits, have to truncate
                            tweet = tweet[:max_content_length - 3] + "..."

                # Length is good, proceed
                break

            # Add source indicator if this story will have a source reply
            if is_specific_story:
                # For regular posts, truncate if needed
                if not use_media_literacy_prompt and len(tweet) > max_content_length:
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
                               article_details: str = None, previous_posts: Optional[List[Dict]] = None) -> str:
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
        update_guidance = ""

        # Check if this is an update to previous coverage
        if previous_posts and len(previous_posts) > 0:
            # Format previous posts for context
            prev_context = []
            for i, prev in enumerate(previous_posts[:2], 1):  # Show up to 2 most recent
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

            update_guidance = f"""
🚨 CRITICAL - THIS IS AN UPDATE/DEVELOPMENT TO A PREVIOUS STORY 🚨

You have ALREADY posted about this story:
{prev_context_str}

MANDATORY REQUIREMENTS (WILL FAIL IF NOT FOLLOWED):
1. Your post MUST start with one of these labels:
   - "UPDATE:" (for new developments)
   - "DEVELOPING:" (for ongoing situations)
   - "REACTION:" (for responses to previous events)
   - "WALKBACK:" (for reversals/retractions)
   - "BREAKING UPDATE:" (for major new developments)

2. You MUST explicitly highlight what's NEW or DIFFERENT:
   - What changed since your last post?
   - What's the new development?
   - Who responded/reacted?
   - What contradicts or updates previous information?

3. You MUST make the progression clear:
   - Use phrases like "After [previous event], now..."
   - "Within 24 hours: [first thing], then [second thing]"
   - "First [X], now [Y]"

4. DO NOT just repeat the same information in different words
   - If there's nothing genuinely new, you should be blocked from posting
   - Find the actual development or change

EXAMPLES OF GOOD UPDATE POSTS:

"UPDATE: Trump says he wasn't threatening death after calling Dems' video "seditious behavior, punishable by death."

Within 24 hours: accusation, then walkback.

Watching humans move goalposts. This cat smells something fishy."

"DEVELOPING: MTG quits Congress effective Jan 5. Says she won't be "battered wife" after Trump fallout.

AOC pounces: Greene timed exit right after pension vests. Even this cat can smell the timing on that one."

"REACTION: After dropping ALL fossil fuel language, COP30 now claims progress.

Reality check: "voluntary agreement to begin discussions on a roadmap."

This cat's not impressed by a promise to talk about maybe planning something later."

BAD EXAMPLES (WILL BE REJECTED):
- Repeating the same story without highlighting what's new
- No UPDATE/DEVELOPING label when required
- Vague references to "developments" without specifying what changed
- Not acknowledging you already covered this story

Remember: Readers saw your first post. They need to know WHY you're posting again.
"""

        if is_specific_story and article_details:
            story_guidance = f"""
CRITICAL - Real Story Coverage (MUST FOLLOW):
- You are writing about this actual article:
  {article_details}

STRICT RULES - DO NOT BREAK THESE:
1. USE ONLY information explicitly stated in the article above
2. DO NOT invent names, locations, positions, titles, or facts
3. DO NOT guess at details not mentioned in the article
4. If a detail is unclear or missing, leave it out entirely
5. When mentioning people: Use ONLY the exact titles/positions stated in the article
6. When mentioning locations: Use ONLY the exact places stated in the article
7. Double-check every fact against the article before including it
8. NEVER mention that you can't read the article or don't have details
9. NEVER say "I don't have information" or similar phrases
10. If content is limited, focus on the headline and general topic only

ACCEPTABLE:
- General commentary on implications and significance
- Raising questions about what's stated in the article
- Expressing skepticism or analysis based on stated facts

NOT ACCEPTABLE (WILL CAUSE ERRORS):
- Saying "Virginia Dem" when article says "NYC Mayor-elect"
- Adding details about someone's position that aren't in the article
- Inventing context or background not provided
- Guessing at state/location if not explicitly mentioned

Remember: It's better to be vague than wrong. Stick to what's in the article.
A source citation will be added in a follow-up reply.
"""
        elif is_specific_story:
            story_guidance = """
CRITICAL - Real Story Coverage:
- This is a real trending topic, not commentary
- Provide objective analysis and context
- DO NOT fabricate ANY specific details (numbers, locations, titles, quotes, positions)
- DO NOT guess at information not provided
- Focus on general significance and implications only
- NEVER mention that you can't read or access the article
- NEVER say "I don't have details" or similar phrases
- If information is limited, comment on the general topic/trend only
- A source citation will be added in a follow-up reply
"""

        prompt = f"""You are a professional news reporter who happens to be a cat. Generate a single tweet reporting on: {topic}

{update_guidance}

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

FINAL REMINDER FOR REAL STORIES:
If you're writing about a specific article with provided content, you MUST use ONLY facts from that article. Do not add information from your training data or make assumptions. Accuracy is critical.

Just return the tweet text itself, nothing else."""

        return prompt

    def analyze_media_literacy(self, story_metadata: Dict) -> Dict:
        """
        Analyze a news story for media literacy issues

        Args:
            story_metadata: Dictionary with 'title', 'article_content', 'source', etc.

        Returns:
            Dictionary with:
                - 'has_issues': Boolean indicating if significant issues found
                - 'issues': List of identified issues
                - 'severity': 'high', 'medium', 'low', or None
        """
        if not story_metadata or not story_metadata.get('article_content'):
            return {'has_issues': False, 'issues': [], 'severity': None}

        title = story_metadata.get('title', '')
        content = story_metadata.get('article_content', '')
        source = story_metadata.get('source', '')

        # Build analysis prompt for Claude
        prompt = f"""Analyze this news article for media literacy issues. Look for misleading practices, bias, and manipulation tactics.

ARTICLE TITLE: {title}
SOURCE: {source}
ARTICLE CONTENT:
{content}

CRITICAL ANALYSIS TASKS:
1. HEADLINE vs CONTENT CHECK:
   - Does the headline accurately represent the article's content?
   - Is the headline clickbait or sensationalized?
   - Are there misleading implications in the headline?

2. TRUTHFULNESS & ACCURACY:
   - Are there factual errors or misleading claims?
   - Are sources properly cited and credible?
   - Is important context missing that changes the story's meaning?

3. BIAS & MANIPULATION:
   - Is there clear political or ideological bias?
   - Are emotional manipulation tactics being used?
   - Is fear-mongering or rage-baiting present?

4. JOURNALISTIC INTEGRITY:
   - Are both/all sides of the story presented?
   - Is opinion being presented as fact?
   - Are anonymous sources overused without corroboration?

5. STATISTICAL MANIPULATION:
   - Are statistics being misused or cherry-picked?
   - Is correlation being presented as causation?
   - Are sample sizes or methodologies questionable?

RESPONSE FORMAT:
Return a JSON object with:
{{
  "has_issues": true/false (true if ANY significant media literacy issues found),
  "severity": "high/medium/low" (high = egregious manipulation, medium = notable bias/issues, low = minor concerns),
  "issues": [
    "Issue 1 description (be specific)",
    "Issue 2 description (be specific)"
  ]
}}

IMPORTANT: Only flag SIGNIFICANT issues that mislead readers. Minor editorial choices or standard journalism practices are not issues.
Be specific in your descriptions - don't just say "misleading headline", explain HOW it misleads.

Focus on the most egregious issues first. Maximum 3 issues.

Return ONLY the JSON object, nothing else."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = message.content[0].text.strip()

            # Parse the JSON response
            try:
                # Try to extract JSON from the response if it's wrapped in code blocks
                if '```json' in response_text:
                    response_text = response_text.split('```json')[1].split('```')[0].strip()
                elif '```' in response_text:
                    response_text = response_text.split('```')[1].split('```')[0].strip()

                result = json.loads(response_text)
                print(f"📊 Media literacy analysis complete: {result.get('severity', 'no issues')} severity")
                return result
            except (json.JSONDecodeError, IndexError) as e:
                print(f"⚠️  Failed to parse media literacy analysis: {e}")
                print(f"   Response was: {response_text[:200]}..." if len(response_text) > 200 else f"   Response was: {response_text}")
                return {'has_issues': False, 'issues': [], 'severity': None}

        except Exception as e:
            print(f"✗ Error analyzing media literacy: {e}")
            return {'has_issues': False, 'issues': [], 'severity': None}

    def _build_media_literacy_prompt(self, story_metadata: Dict,
                                   media_issues: Dict) -> str:
        """Build a prompt for responding to media literacy issues"""

        title = story_metadata.get('title', '')
        source = story_metadata.get('source', '')
        issues_list = media_issues.get('issues', [])
        severity = media_issues.get('severity', 'medium')

        # Format issues for the prompt
        issues_str = "\n".join([f"- {issue}" for issue in issues_list])

        # Get cat vocabulary for the prompt
        cat_vocab_str = ", ".join(self.cat_vocabulary[:10])

        # Note: Time-of-day and editorial guidelines are currently omitted from this prompt
        # to keep it extremely concise and focused on the media literacy callout

        prompt = f"""You are a professional news reporter cat who SPECIALIZES in media literacy. You've identified serious issues with this article:

ARTICLE: {title}
SOURCE: {source}

MEDIA LITERACY ISSUES FOUND ({severity} severity):
{issues_str}

Your job is to CALL OUT these media manipulation tactics while maintaining your cat reporter persona.

CHARACTER:
- Professional media literacy cat who takes accuracy seriously
- You're a CAT reporter - include at least ONE cat reference/pun
- Cat wordplay should feel natural: {cat_vocab_str}
- Sharp, incisive media criticism with personality

CRITICAL REQUIREMENTS:
1. DIRECTLY ADDRESS the media literacy issues found
2. Call out the SPECIFIC manipulation tactics (don't be vague)
3. Educate readers on HOW they're being misled
4. Maintain skeptical, investigative tone
5. Include your signature cat personality

APPROACH OPTIONS (choose based on severity - keep it SHORT):
- HIGH: "#MediaLiteracy: [outlet] says X but facts show Y..."
- MEDIUM: "Fact check: [false claim]. Reality: [truth]..."
- LOW: "Missing context: [what's omitted]..."

STYLE:
- {self.style}
- PUNCHY and direct - call it out clearly
- Populist angle: Protect readers from media manipulation
- Question the narrative, expose the tactics
- Professional but BITING - don't pull punches
- Educational: Help readers spot these tactics themselves

FORMAT:
- STRICT LIMIT: 265 characters MAXIMUM (Twitter will cut you off!)
- BE CONCISE - every word must count
- Use line breaks between thoughts for clarity
- NO emojis (very rare exceptions)
- NO hashtags except #MediaLiteracy at START if appropriate
- If you go over 265 chars, your message WILL be truncated and ruined

CRITICAL: Your ENTIRE message must fit in 265 characters. Going over means:
- Your point gets cut off mid-sentence
- Readers miss the critical media literacy lesson
- The manipulation wins because you couldn't be concise

GOOD EXAMPLES (all under 265 chars):

For misleading headline (184 chars):
"#MediaLiteracy: Headline screams 'CRISIS' but article says 0.3% dip.

Classic fear-bait. Article itself calls it 'normal.' This cat's not buying the panic."

For missing context (201 chars):
"Story omits senator's own healthcare bill last week. Only quotes supporters, zero opposition.

That's not reporting, it's PR. This cat keeps receipts on the full story."

For statistical manipulation (189 chars):
"'100% SURGE!' = going from 2 to 4 burglaries. That's manipulation, not math.

When they bury actual numbers, this cat gets suspicious. Always check the data."

For bias/one-sided reporting (195 chars):
"Five experts quoted. All from same donor-funded think tank.

That's stenography, not journalism. Even this cat checks multiple sources before pouncing on a story."

Return ONLY the tweet text addressing the media literacy issues."""

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
