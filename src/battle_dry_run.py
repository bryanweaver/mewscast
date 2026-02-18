"""
Battle post dry run - tests the full pipeline without API keys or posting.
Finds real stories from Google News, mocks the AI generation parts.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from battle_post import BattlePostGenerator
from battle_image import BattleImageGenerator
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import random


def create_mock_battle_image(battle_data: dict, save_path: str = "/tmp/battle_dry_run.png"):
    """
    Create a mock split-screen image without Grok API.
    Uses Pillow to generate a stylized placeholder, then applies the real overlay.
    """
    width, height = 1200, 675
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    mid_x = width // 2

    # Left panel - blue tint
    for y in range(height):
        r = int(20 + (y / height) * 30)
        g = int(30 + (y / height) * 20)
        b = int(60 + (y / height) * 40)
        draw.line([(0, y), (mid_x - 2, y)], fill=(r, g, b))

    # Right panel - red tint
    for y in range(height):
        r = int(60 + (y / height) * 40)
        g = int(20 + (y / height) * 20)
        b = int(30 + (y / height) * 30)
        draw.line([(mid_x + 2, y), (width, y)], fill=(r, g, b))

    # Center divider
    draw.rectangle([mid_x - 2, 0, mid_x + 2, height], fill=(100, 100, 100))

    # Placeholder text on each side
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
        small_font = font

    # Left side placeholder
    draw.text((80, 250), "[Grok would generate:", fill=(150, 150, 180), font=small_font)
    draw.text((80, 275), "Cat scene reflecting", fill=(180, 180, 210), font=font)
    draw.text((80, 300), f"{battle_data['source_pair']['source_a']}'s", fill=(180, 180, 210), font=font)
    draw.text((80, 325), "framing of the story]", fill=(180, 180, 210), font=font)

    # Right side placeholder
    draw.text((mid_x + 80, 250), "[Grok would generate:", fill=(180, 150, 150), font=small_font)
    draw.text((mid_x + 80, 275), "Cat scene reflecting", fill=(210, 180, 180), font=font)
    draw.text((mid_x + 80, 300), f"{battle_data['source_pair']['source_b']}'s", fill=(210, 180, 180), font=font)
    draw.text((mid_x + 80, 325), "framing of the story]", fill=(210, 180, 180), font=font)

    # Center Walter placeholder
    draw.text((mid_x - 80, 400), "[Walter investigator", fill=(200, 200, 200), font=small_font)
    draw.text((mid_x - 60, 420), "close-up here]", fill=(200, 200, 200), font=small_font)

    img.save(save_path, "PNG")

    # Now apply the REAL overlay labels
    gen = BattleImageGenerator()
    gen._overlay_labels(
        save_path,
        battle_data['source_pair']['source_a'],
        battle_data['source_pair']['source_b']
    )

    return save_path


def main():
    topic = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None

    print(f"\n{'='*60}")
    print(f"BATTLE DRY RUN (no API keys, no posting)")
    print(f"{'='*60}\n")

    # Step 1: Find real matching stories from Google News RSS
    battle_gen = BattlePostGenerator()

    if topic:
        print(f"Topic: {topic}\n")
    else:
        print("Auto-selecting trending topic...\n")

    battle_data = battle_gen.find_matching_stories(topic)
    if not battle_data:
        print("\n❌ Could not find matching coverage. Try specifying a topic:")
        print("   python src/battle_dry_run.py \"tariffs\"")
        return

    article_a = battle_data['article_a']
    article_b = battle_data['article_b']
    pair = battle_data['source_pair']

    print(f"\n{'='*60}")
    print(f"BATTLE FOUND!")
    print(f"{'='*60}")
    print(f"\n  Source A: {pair['source_a']}")
    print(f"  Headline: {article_a['title']}")
    print(f"  URL: {article_a['url']}")
    print(f"\n  Source B: {pair['source_b']}")
    print(f"  Headline: {article_b['title']}")
    print(f"  URL: {article_b['url']}")

    # Step 2: Mock post text (would normally come from Claude)
    mock_post = (
        f"Same story. Two spins.\n\n"
        f"{pair['source_a']} and {pair['source_b']} covered the same mews "
        f"and somehow ended up in different litter boxes.\n\n"
        f"This cat read both. The truth is somewhere in between the scratching posts."
    )

    print(f"\n{'='*60}")
    print(f"MOCK POST TEXT ({len(mock_post)} chars):")
    print(f"{'='*60}")
    print(f"\n{mock_post}\n")

    # Step 3: Generate mock image with real overlays
    print(f"{'='*60}")
    print(f"GENERATING IMAGE (mock scene + real overlays)...")
    print(f"{'='*60}")

    image_path = create_mock_battle_image(battle_data)
    print(f"\nImage saved to: {image_path}")
    print(f"\nThe Grok-generated version would show:")
    print(f"  - LEFT: Cats in a scene reflecting {pair['source_a']}'s framing")
    print(f"  - CENTER: Walter (brown tabby) investigator close-up")
    print(f"  - RIGHT: Cats in a scene reflecting {pair['source_b']}'s framing")
    print(f"  - OVERLAYS: Source labels, VS badge, MEWSCAST branding (these are real)")

    print(f"\n{'='*60}")
    print(f"DRY RUN COMPLETE")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
