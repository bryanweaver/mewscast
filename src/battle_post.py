"""
Battle of the Political Sides - Special Edition Post

Finds the same news story covered by a left-leaning and right-leaning publication,
compares their framing, and generates Walter Croncat's centrist verdict.

Usage:
    python src/main.py special battle              # Auto-picks a trending topic
    python src/main.py special battle "topic here"  # Search for a specific topic
"""
import os
import random
import time
import re
import yaml
import feedparser
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple

from news_fetcher import NewsFetcher
from content_generator import ContentGenerator
from prompt_loader import get_prompt_loader


class BattlePostGenerator:
    """Generates 'Battle of the Political Sides' comparison posts"""

    def __init__(self):
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        battle_config = self.config.get('special_posts', {}).get('battle', {})
        self.source_pairs = battle_config.get('source_pairs', [])
        self.source_domains = battle_config.get('source_domains', {})
        self.max_length = battle_config.get('max_length', 280)
        self.news_fetcher = NewsFetcher()
        self.content_generator = ContentGenerator()
        self.prompts = get_prompt_loader()

    def find_matching_stories(self, topic: str = None) -> Optional[Dict]:
        """
        Find the same news story from both a left and right source.

        Args:
            topic: Optional specific topic to search for.
                   If None, uses current top stories to find a match.

        Returns:
            Dict with 'left_article', 'right_article', 'source_pair', 'topic'
            or None if no match found.
        """
        # If no topic given, grab trending topics from top stories
        if not topic:
            print("🔍 No topic specified - scanning top stories for battle-worthy topics...")
            top_stories = self.news_fetcher.get_top_stories(max_stories=10)
            trending = self.news_fetcher.extract_trending_topics(top_stories)

            if not trending:
                # Fallback: use top story headlines directly
                trending = [s['title'].split(' - ')[0] for s in top_stories[:5]]

            if not trending:
                print("❌ Could not find any trending topics")
                return None

            # Try each trending topic
            for trend in trending[:5]:
                print(f"\n🥊 Trying topic: '{trend}'")
                result = self._search_pair_for_topic(trend)
                if result:
                    return result

            print("❌ Could not find matching left/right coverage for any trending topic")
            return None
        else:
            print(f"🥊 Searching for battle on: '{topic}'")
            return self._search_pair_for_topic(topic)

    def _search_pair_for_topic(self, topic: str) -> Optional[Dict]:
        """
        Search source pairs for articles on the given topic from both outlets.

        Tries each configured source pair until it finds one where both
        outlets have coverage.
        """
        # Shuffle pairs so we don't always use the same one
        pairs = list(self.source_pairs)
        random.shuffle(pairs)

        for pair in pairs:
            name_a = pair['source_a']
            name_b = pair['source_b']
            domain_a = self.source_domains.get(name_a)
            domain_b = self.source_domains.get(name_b)

            if not domain_a or not domain_b:
                continue

            print(f"   Checking {name_a} vs {name_b}...")

            # Search Google News for this topic filtered by source domain
            article_a = self._search_source(topic, name_a, domain_a)
            if not article_a:
                print(f"   ✗ No {name_a} coverage found")
                continue

            article_b = self._search_source(topic, name_b, domain_b)
            if not article_b:
                print(f"   ✗ No {name_b} coverage found")
                continue

            # Fetch full article content for both
            print(f"   ✓ Found both sides! Fetching full articles...")

            content_a = self.news_fetcher.fetch_article_content(article_a['url'])
            if not content_a:
                print(f"   ✗ Could not fetch {name_a} article content")
                continue

            content_b = self.news_fetcher.fetch_article_content(article_b['url'])
            if not content_b:
                print(f"   ✗ Could not fetch {name_b} article content")
                continue

            article_a['article_content'] = content_a
            article_b['article_content'] = content_b

            print(f"   ✅ Battle ready: {name_a} ({len(content_a)} chars) vs {name_b} ({len(content_b)} chars)")

            return {
                'article_a': article_a,
                'article_b': article_b,
                'source_pair': pair,
                'topic': topic
            }

        return None

    def _search_source(self, topic: str, source_name: str, domain: str) -> Optional[Dict]:
        """
        Search Google News RSS for a topic from a specific source domain.
        """
        try:
            search_query = f"{topic} site:{domain}".replace(' ', '+')
            rss_url = f"https://news.google.com/rss/search?q={search_query}&hl=en-US&gl=US&ceid=US:en"

            feed = feedparser.parse(rss_url)

            if not feed.entries:
                return None

            # Only consider recent articles (last 3 days)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=3)

            for entry in feed.entries[:5]:
                published_str = entry.get('published', '')
                if published_str:
                    try:
                        published_date = parsedate_to_datetime(published_str)
                        if published_date < cutoff_date:
                            continue
                    except Exception:
                        continue

                source = entry.get('source', {}).get('title', source_name)

                # Resolve Google News URL
                actual_url = self.news_fetcher.resolve_google_news_url(entry.link)

                return {
                    'title': entry.title,
                    'description': entry.get('summary', ''),
                    'url': actual_url,
                    'source': source,
                    'published': published_str
                }

            return None

        except Exception as e:
            print(f"   ⚠️  Error searching {source_name}: {e}")
            return None

    def _check_article_consistency(self, client, model: str,
                                     source_a: str, title_a: str, content_a: str,
                                     source_b: str, title_b: str, content_b: str,
                                     topic: str) -> Dict:
        """
        Pre-check whether two articles are actually about the same story/event.

        Returns dict with 'is_consistent' bool and 'reason' string.
        Articles about different people, events, or topics should not be compared.
        """
        consistency_prompt = (
            f"You are checking whether two news articles cover the SAME story or event, "
            f"making them suitable for a side-by-side media comparison.\n\n"
            f"Search topic: {topic}\n\n"
            f"## ARTICLE A: {source_a}\n"
            f"Headline: {title_a}\n"
            f"Content preview: {content_a[:500]}\n\n"
            f"## ARTICLE B: {source_b}\n"
            f"Headline: {title_b}\n"
            f"Content preview: {content_b[:500]}\n\n"
            f"## CHECK:\n"
            f"1. Are these articles about the SAME specific event, person, or news story?\n"
            f"2. Or are they about DIFFERENT stories that merely share a general topic?\n"
            f"   (e.g., two different people both involved in 'politics' is NOT a match)\n\n"
            f"Respond in this exact format:\n"
            f"SAME_STORY: yes/no\n"
            f"REASON: [brief explanation]\n"
        )

        try:
            message = client.messages.create(
                model=model,
                max_tokens=200,
                messages=[{"role": "user", "content": consistency_prompt}]
            )

            response = message.content[0].text.strip().lower()
            is_consistent = 'same_story: yes' in response or 'same_story:yes' in response
            reason = ''
            if 'reason:' in response:
                reason = response.split('reason:', 1)[1].strip()

            return {'is_consistent': is_consistent, 'reason': reason}

        except Exception as e:
            print(f"   ⚠️  Consistency check failed: {e}")
            # If the check fails, allow it to proceed (fail-open for API errors only)
            return {'is_consistent': True, 'reason': 'consistency check unavailable'}

    def generate_battle_post(self, battle_data: Dict) -> Optional[Dict]:
        """
        Generate Walter Croncat's comparison post from both articles.

        Uses a multi-pass approach:
        0. Pre-check that articles are about the same story
        1. Generate initial comparison post
        2. Verify claims against both source articles
        3. If verification finds issues, regenerate with corrections
        4. If still inconsistent after correction, FAIL (return None)

        Returns dict with 'post_text' and 'sources_text' for thread format,
        or None if articles are inconsistent or generation fails verification.
        """
        article_a = battle_data['article_a']
        article_b = battle_data['article_b']
        pair = battle_data['source_pair']
        topic = battle_data['topic']

        # Get topic-matched vocab
        combined_text = f"{article_a['title']} {article_b['title']}"
        combined_content = f"{article_a.get('article_content', '')[:300]} {article_b.get('article_content', '')[:300]}"
        cat_vocab_str = self.content_generator._select_vocab_for_story(combined_text, combined_content)

        content_a = article_a.get('article_content', '')[:800]
        content_b = article_b.get('article_content', '')[:800]

        # === PASS 0: Pre-check article consistency ===
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            model = self.config['content']['model']
        except Exception as e:
            print(f"❌ Error initializing API client: {e}")
            return None

        print("   🔍 Pass 0: Checking if articles cover the same story...")
        consistency = self._check_article_consistency(
            client, model,
            pair['source_a'], article_a['title'], content_a,
            pair['source_b'], article_b['title'], content_b,
            topic
        )

        if not consistency['is_consistent']:
            print(f"   ❌ Articles are NOT about the same story: {consistency['reason']}")
            print(f"   Skipping this pair - need articles covering the same event.")
            return None

        print(f"   ✅ Articles confirmed to be about the same story")

        # Build the battle prompt — uses source_a/source_b, no left/right labels
        prompt = self.prompts.load("battle_comparison.md",
            topic=topic,
            left_source=pair['source_a'],
            left_title=article_a['title'],
            left_content=content_a,
            right_source=pair['source_b'],
            right_title=article_b['title'],
            right_content=content_b,
            cat_vocab_str=cat_vocab_str,
            max_length=self.max_length
        )

        try:
            # === PASS 1: Generate initial comparison ===
            print("   📝 Pass 1: Generating initial comparison...")
            message = client.messages.create(
                model=model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            post_text = message.content[0].text.strip()

            # Clean up quotes if present
            if post_text.startswith('"') and post_text.endswith('"'):
                post_text = post_text[1:-1]
            if post_text.startswith("'") and post_text.endswith("'"):
                post_text = post_text[1:-1]

            print(f"   Draft ({len(post_text)} chars): {post_text[:80]}...")

            # === Self-reference check: detect AI meta-commentary ===
            if self._has_self_referential_content(post_text):
                print(f"   ❌ Generated text contains AI meta-commentary instead of a real comparison.")
                print(f"   Refusing to post self-referential content.")
                return None

            # === PASS 2: Verify accuracy against sources ===
            print("   🔍 Pass 2: Verifying claims against source articles...")
            verification = self._verify_battle_post(
                client, model, post_text,
                pair['source_a'], article_a['title'], content_a,
                pair['source_b'], article_b['title'], content_b
            )

            if verification['has_issues']:
                print(f"   ⚠️  Verification found issues: {verification['issues']}")
                print(f"   📝 Pass 3: Regenerating with corrections...")

                # === PASS 3: Regenerate with verification feedback ===
                corrected_prompt = (
                    f"{prompt}\n\n"
                    f"## IMPORTANT CORRECTIONS FROM FACT-CHECK\n"
                    f"A previous draft had these problems:\n"
                    f"Draft: {post_text}\n"
                    f"Issues found: {verification['issues']}\n\n"
                    f"Fix these issues in your new version. Be accurate about what each source actually says."
                )

                message = client.messages.create(
                    model=model,
                    max_tokens=500,
                    messages=[{"role": "user", "content": corrected_prompt}]
                )

                post_text = message.content[0].text.strip()
                if post_text.startswith('"') and post_text.endswith('"'):
                    post_text = post_text[1:-1]
                if post_text.startswith("'") and post_text.endswith("'"):
                    post_text = post_text[1:-1]

                print(f"   Corrected ({len(post_text)} chars): {post_text[:80]}...")

                # Check corrected version for self-reference too
                if self._has_self_referential_content(post_text):
                    print(f"   ❌ Corrected text still contains AI meta-commentary.")
                    print(f"   Refusing to post self-referential content.")
                    return None

                # === PASS 4: Final verification ===
                print("   🔍 Pass 4: Final verification...")
                final_check = self._verify_battle_post(
                    client, model, post_text,
                    pair['source_a'], article_a['title'], content_a,
                    pair['source_b'], article_b['title'], content_b
                )

                if final_check['has_issues']:
                    print(f"   ❌ Still has issues after correction: {final_check['issues']}")
                    print(f"   Refusing to post inconsistent content.")
                    return None
                else:
                    print(f"   ✅ Final verification passed!")
            else:
                print(f"   ✅ Verification passed - claims are accurate!")

            # Enforce length
            if len(post_text) > self.max_length:
                from content_generator import _truncate_at_sentence
                post_text = _truncate_at_sentence(post_text, self.max_length)

            # Track vocab usage
            self.content_generator._record_used_phrase(post_text)

            # Build source citation reply
            sources_text = (
                f"Sources:\n"
                f"{pair['source_a']}: {article_a['url']}\n"
                f"{pair['source_b']}: {article_b['url']}"
            )

            print(f"✅ Battle post generated ({len(post_text)} chars)")

            return {
                'post_text': post_text,
                'sources_text': sources_text,
                'article_a': article_a,
                'article_b': article_b,
                'source_pair': pair,
                'topic': topic
            }

        except Exception as e:
            print(f"❌ Error generating battle post: {e}")
            return None

    def _has_self_referential_content(self, post_text: str) -> bool:
        """
        Detect if the AI generated meta-commentary about the articles
        instead of an actual comparison post.

        Catches outputs like "these articles are about different people",
        "I notice these cover different subjects", etc.
        """
        text_lower = post_text.lower()

        # Patterns that indicate the AI is talking ABOUT the articles
        # rather than writing a comparison AS Walter Croncat
        self_ref_patterns = [
            "different people",
            "different person",
            "different subject",
            "different stor",
            "not the same story",
            "not the same event",
            "not about the same",
            "don't cover the same",
            "don't actually cover",
            "aren't about the same",
            "these articles are about",
            "these articles aren't",
            "these articles don't",
            "i notice",
            "i can't compare",
            "i cannot compare",
            "unable to compare",
            "not comparable",
            "apples and oranges",
            "two different",
            "two entirely different",
            "not related",
            "unrelated stories",
        ]

        for pattern in self_ref_patterns:
            if pattern in text_lower:
                print(f"   Detected self-referential pattern: '{pattern}'")
                return True

        return False

    def _verify_battle_post(self, client, model: str, post_text: str,
                            left_source: str, left_title: str, left_content: str,
                            right_source: str, right_title: str, right_content: str) -> Dict:
        """
        Verify a battle post's claims against the source articles.

        Checks that:
        - Any claims attributed to the left source actually appear in that article
        - Any claims attributed to the right source actually appear in that article
        - The comparison is fair and not misrepresenting either side
        - No fabricated details

        Returns dict with 'has_issues' bool and 'issues' string.
        """
        verification_prompt = (
            f"You are a fact-checker reviewing a social media post that compares two news sources' "
            f"coverage of the same story. Check whether the post accurately represents what each "
            f"source actually says.\n\n"
            f"## THE POST TO VERIFY:\n{post_text}\n\n"
            f"## SOURCE A: {left_source}\n"
            f"Headline: {left_title}\n"
            f"Content: {left_content}\n\n"
            f"## SOURCE B: {right_source}\n"
            f"Headline: {right_title}\n"
            f"Content: {right_content}\n\n"
            f"## CHECK FOR:\n"
            f"1. Does the post accurately describe what each source says or emphasizes?\n"
            f"2. Does the post attribute claims to the correct source?\n"
            f"3. Does the post fabricate any details not in either article?\n"
            f"4. Is the comparison fair, or does it misrepresent one side?\n"
            f"5. Are any facts stated in the post contradicted by either article?\n\n"
            f"Respond in this exact format:\n"
            f"ACCURATE: yes/no\n"
            f"ISSUES: [describe specific issues, or 'none' if accurate]\n"
        )

        try:
            message = client.messages.create(
                model=model,
                max_tokens=300,
                messages=[{"role": "user", "content": verification_prompt}]
            )

            response = message.content[0].text.strip().lower()

            has_issues = 'accurate: no' in response or 'accurate:no' in response
            issues = ''
            if 'issues:' in response:
                issues = response.split('issues:', 1)[1].strip()
                if issues == 'none' or issues == 'none.':
                    has_issues = False
                    issues = ''

            return {'has_issues': has_issues, 'issues': issues}

        except Exception as e:
            print(f"   ⚠️  Verification call failed: {e}")
            # If verification fails, proceed cautiously
            return {'has_issues': False, 'issues': 'verification unavailable'}
