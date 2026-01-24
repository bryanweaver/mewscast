"""
Prompt loader utility for loading and formatting prompt templates from files
"""
import os
from typing import Dict, Optional
from functools import lru_cache


class PromptLoader:
    """Loads prompt templates from the prompts/ directory"""

    def __init__(self, prompts_dir: str = None):
        """
        Initialize prompt loader

        Args:
            prompts_dir: Path to prompts directory (defaults to ../prompts from src/)
        """
        if prompts_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            prompts_dir = os.path.join(os.path.dirname(script_dir), "prompts")

        self.prompts_dir = prompts_dir
        self._cache: Dict[str, str] = {}

    @lru_cache(maxsize=20)
    def _load_raw(self, filename: str) -> str:
        """Load raw prompt template from file (cached)"""
        filepath = os.path.join(self.prompts_dir, filename)

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Prompt file not found: {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    def load(self, filename: str, **kwargs) -> str:
        """
        Load a prompt template and format it with provided values

        Args:
            filename: Name of the prompt file (e.g., 'tweet_generation.md')
            **kwargs: Values to substitute into the template

        Returns:
            Formatted prompt string
        """
        template = self._load_raw(filename)

        # Use safe formatting that ignores missing keys
        # This allows partial formatting when some placeholders aren't needed
        try:
            return template.format(**kwargs)
        except KeyError as e:
            # If a key is missing, return template with that placeholder intact
            # This allows for optional sections
            return self._safe_format(template, kwargs)

    def _safe_format(self, template: str, kwargs: Dict) -> str:
        """
        Format template, leaving unmatched placeholders as-is

        Args:
            template: Template string with {placeholders}
            kwargs: Values to substitute

        Returns:
            Partially formatted string
        """
        result = template
        for key, value in kwargs.items():
            placeholder = "{" + key + "}"
            result = result.replace(placeholder, str(value))
        return result

    def load_tweet_prompt(self, platform: str = None, **kwargs) -> str:
        """Load the tweet generation prompt

        Args:
            platform: 'x', 'bluesky', or None (all use same prompt now)
            **kwargs: Values to substitute into the template
        """
        # Use unified Bluesky prompt for all platforms
        # X-specific version was retired since engagement didn't improve
        return self.load("tweet_generation_bluesky.md", **kwargs)

    def load_image_prompt(self, **kwargs) -> str:
        """Load the image generation prompt"""
        return self.load("image_generation.md", **kwargs)

    def load_update_guidance(self, **kwargs) -> str:
        """Load the update guidance section"""
        return self.load("tweet_update_guidance.md", **kwargs)

    def load_story_guidance_with_article(self, **kwargs) -> str:
        """Load story guidance for articles with content"""
        return self.load("tweet_story_guidance_with_article.md", **kwargs)

    def load_story_guidance_generic(self) -> str:
        """Load generic story guidance"""
        return self.load("tweet_story_guidance_generic.md")

    def load_framing_analysis(self, **kwargs) -> str:
        """Load the framing analysis prompt"""
        return self.load("analyze_framing.md", **kwargs)

    def load_framing_tweet(self, **kwargs) -> str:
        """Load the framing tweet prompt"""
        return self.load("tweet_framing.md", **kwargs)

    def load_shorten_tweet(self, **kwargs) -> str:
        """Load the shorten tweet prompt"""
        return self.load("shorten_tweet.md", **kwargs)

    def load_reply(self, **kwargs) -> str:
        """Load the reply prompt"""
        return self.load("reply.md", **kwargs)


# Singleton instance for easy import
_loader: Optional[PromptLoader] = None

def get_prompt_loader() -> PromptLoader:
    """Get the singleton prompt loader instance"""
    global _loader
    if _loader is None:
        _loader = PromptLoader()
    return _loader
