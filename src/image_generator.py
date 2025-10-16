"""
AI-powered image generation using xAI Grok
"""
import os
import requests
from openai import OpenAI
from typing import Optional


class ImageGenerator:
    """Generates images using xAI Grok API"""

    def __init__(self):
        """Initialize xAI Grok client"""
        api_key = os.getenv("X_AI_API_KEY")
        if not api_key:
            raise ValueError("Missing X_AI_API_KEY. Check your .env file.")

        # xAI uses OpenAI-compatible API
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1"
        )
        self.model = "grok-2-image-1212"

    def generate_image(self, prompt: str, save_path: str = "temp_image.png") -> Optional[str]:
        """
        Generate an image using Grok API

        Args:
            prompt: Text description of image to generate
            save_path: Where to save the generated image

        Returns:
            Path to saved image file, or None if failed
        """
        try:
            print(f"🎨 Generating image with Grok...")
            print(f"   Prompt: {prompt[:80]}...")

            # Call Grok image generation API
            # Note: Grok doesn't support size parameter, use prompt engineering for landscape
            # Add explicit widescreen/landscape instructions
            landscape_prompt = f"{prompt}, wide angle shot, cinematic widescreen composition, horizontal landscape format"

            response = self.client.images.generate(
                model=self.model,
                prompt=landscape_prompt,
                n=1  # Generate 1 image
            )

            # Get image URL from response
            image_url = response.data[0].url

            print(f"✓ Image generated: {image_url[:60]}...")

            # Download the image
            print(f"⬇️  Downloading image...")
            img_response = requests.get(image_url, timeout=30)
            img_response.raise_for_status()

            # Save to file
            with open(save_path, 'wb') as f:
                f.write(img_response.content)

            print(f"✓ Image saved to: {save_path}")
            return save_path

        except Exception as e:
            print(f"✗ Image generation failed: {e}")
            return None
