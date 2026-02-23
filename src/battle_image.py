"""
Split-screen battle image generator for Battle of the Political Sides posts.

Generates an AI image showing investigator Walter (brown tabby) in the center
with two different cat scenes on each side representing how each outlet framed
the story. Source name labels are overlaid with Pillow.
"""
import os
import textwrap
from typing import Dict, Optional

from content_generator import _strip_quotes
from prompt_loader import get_prompt_loader


class BattleImageGenerator:
    """Generates split-screen comparison images for battle posts"""

    # Text overlay settings
    LABEL_PADDING = 16
    LABEL_FONT_SIZE = 32
    LABEL_BG_OPACITY = 180  # 0-255

    # Font paths (DejaVu available on most Linux, Liberation as fallback)
    FONT_PATHS = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]

    def __init__(self):
        self.prompts = get_prompt_loader()

    def generate(self, battle_data: Dict, save_path: str = "temp_battle.png") -> Optional[str]:
        """
        Generate a split-screen battle image.

        1. Uses Claude to create a scene-specific split-screen image prompt
        2. Sends to Grok to generate the AI image
        3. Overlays source name labels with Pillow

        Args:
            battle_data: Dict with article_a, article_b, source_pair, topic
            save_path: Where to save the final image

        Returns:
            Path to saved image, or None if failed
        """
        try:
            article_a = battle_data['article_a']
            article_b = battle_data['article_b']
            pair = battle_data['source_pair']
            topic = battle_data.get('topic', 'Breaking News')

            # Step 1: Generate the image prompt using Claude
            print("   🎨 Generating battle image prompt...")
            image_prompt = self._generate_battle_prompt(
                topic=topic,
                source_a=pair['source_a'],
                headline_a=article_a['title'],
                content_a=article_a.get('article_content', '')[:500],
                source_b=pair['source_b'],
                headline_b=article_b['title'],
                content_b=article_b.get('article_content', '')[:500],
            )

            if not image_prompt:
                print("   ⚠️  Could not generate image prompt")
                return None

            print(f"   Prompt: {image_prompt[:100]}...")

            # Step 2: Generate image with Grok
            print("   🎨 Generating image with Grok...")
            from image_generator import ImageGenerator
            img_generator = ImageGenerator()
            raw_path = img_generator.generate_image(image_prompt, save_path=save_path)

            if not raw_path:
                print("   ⚠️  Grok image generation failed")
                return None

            # Step 3: Overlay source name labels
            print("   🏷️  Adding source labels...")
            self._overlay_labels(raw_path, pair['source_a'], pair['source_b'])

            print(f"   ✅ Battle image saved to: {save_path}")
            return save_path

        except Exception as e:
            print(f"   ⚠️  Battle image generation failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _generate_battle_prompt(self, topic: str, source_a: str, headline_a: str,
                                 content_a: str, source_b: str, headline_b: str,
                                 content_b: str) -> Optional[str]:
        """
        Use Claude to generate a tailored split-screen image prompt
        based on both articles' content and framing.
        """
        try:
            from anthropic import Anthropic
            import yaml

            config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)

            client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            model = config['content']['model']

            prompt = self.prompts.load("battle_image.md",
                topic=topic,
                source_a=source_a,
                headline_a=headline_a,
                content_a=content_a,
                source_b=source_b,
                headline_b=headline_b,
                content_b=content_b,
            )

            message = client.messages.create(
                model=model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )

            image_prompt = message.content[0].text.strip()

            # Clean up quotes
            image_prompt = _strip_quotes(image_prompt)

            # Enforce 200-char limit for Grok
            if len(image_prompt) > 200:
                image_prompt = image_prompt[:200]

            return image_prompt

        except Exception as e:
            print(f"   ⚠️  Image prompt generation failed: {e}")
            return None

    def _overlay_labels(self, image_path: str, source_a: str, source_b: str):
        """
        Overlay source name labels on the left and right sides of the image.
        Adds semi-transparent background bars with white text.
        """
        try:
            from PIL import Image, ImageDraw, ImageFont

            img = Image.open(image_path).convert("RGBA")
            width, height = img.size

            # Create overlay layer for semi-transparent backgrounds
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Load font
            font = self._load_font(self.LABEL_FONT_SIZE)
            small_font = self._load_font(16)

            mid_x = width // 2
            pad = self.LABEL_PADDING
            bar_height = self.LABEL_FONT_SIZE + pad * 2

            # --- Source A label (top-left) ---
            label_a = source_a.upper()
            bbox_a = draw.textbbox((0, 0), label_a, font=font)
            text_w_a = bbox_a[2] - bbox_a[0]

            # Semi-transparent black bar behind text
            draw.rectangle(
                [0, 0, text_w_a + pad * 3, bar_height],
                fill=(0, 0, 0, self.LABEL_BG_OPACITY)
            )
            draw.text((pad, pad), label_a, fill=(255, 255, 255, 255), font=font)

            # --- Source B label (top-right) ---
            label_b = source_b.upper()
            bbox_b = draw.textbbox((0, 0), label_b, font=font)
            text_w_b = bbox_b[2] - bbox_b[0]

            bar_x = width - text_w_b - pad * 3
            draw.rectangle(
                [bar_x, 0, width, bar_height],
                fill=(0, 0, 0, self.LABEL_BG_OPACITY)
            )
            draw.text((bar_x + pad, pad), label_b, fill=(255, 255, 255, 255), font=font)

            # --- "VS" badge in top center ---
            vs_text = "VS"
            vs_bbox = draw.textbbox((0, 0), vs_text, font=font)
            vs_w = vs_bbox[2] - vs_bbox[0]
            vs_h = vs_bbox[3] - vs_bbox[1]
            vs_pad = 12
            vs_x = mid_x - vs_w // 2
            vs_y = pad

            # Gold circle behind VS
            circle_r = max(vs_w, vs_h) // 2 + vs_pad
            circle_cx = mid_x
            circle_cy = vs_y + vs_h // 2
            draw.ellipse(
                [circle_cx - circle_r, circle_cy - circle_r,
                 circle_cx + circle_r, circle_cy + circle_r],
                fill=(0, 0, 0, 200), outline=(255, 215, 0, 255), width=3
            )
            draw.text((vs_x, vs_y - 2), vs_text, fill=(255, 215, 0, 255), font=font)

            # --- MEWSCAST branding (bottom center) ---
            brand = "MEWSCAST"
            brand_bbox = draw.textbbox((0, 0), brand, font=small_font)
            brand_w = brand_bbox[2] - brand_bbox[0]
            brand_h = brand_bbox[3] - brand_bbox[1]
            brand_bar_h = brand_h + 12

            draw.rectangle(
                [mid_x - brand_w // 2 - 20, height - brand_bar_h - 8,
                 mid_x + brand_w // 2 + 20, height],
                fill=(0, 0, 0, 180)
            )
            draw.text(
                (mid_x - brand_w // 2, height - brand_bar_h - 2),
                brand, fill=(180, 180, 195, 255), font=small_font
            )

            # Composite overlay onto original image
            result = Image.alpha_composite(img, overlay)
            result = result.convert("RGB")
            result.save(image_path, "PNG")

        except ImportError:
            print("   ⚠️  Pillow not available - posting image without labels")
        except Exception as e:
            print(f"   ⚠️  Label overlay failed (posting without labels): {e}")

    def _load_font(self, size: int):
        """Load a font with fallbacks"""
        from PIL import ImageFont

        for font_path in self.FONT_PATHS:
            try:
                return ImageFont.truetype(font_path, size)
            except (OSError, IOError):
                continue

        return ImageFont.load_default()
