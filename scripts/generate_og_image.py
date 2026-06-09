"""Generate the landing-page OG image for mewscast.us.

Outputs docs/images/mewscast-og.png at 1200x630 (the standard OG/Twitter
summary-large-image size). Uses the existing Walter Croncat portrait as
a circular avatar and the site's dark palette (#0d1117 background,
#58a6ff accent, #e6edf3 / #8b949e text).
"""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
AVATAR_SRC = REPO / "docs" / "images" / "walter-croncat-profile-v2.png"
OUTPUT = REPO / "docs" / "images" / "mewscast-og.png"

W, H = 1200, 630
BG = (13, 17, 23)          # #0d1117
PANEL = (22, 27, 34)       # #161b22 (card background, used for subtle separator)
BORDER = (48, 54, 61)      # #30363d
FG = (230, 237, 243)       # #e6edf3
DIM = (139, 148, 158)      # #8b949e
ACCENT = (88, 166, 255)    # #58a6ff


def _font(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _circle_avatar(src: Path, diameter: int) -> Image.Image:
    img = Image.open(src).convert("RGBA")
    img = img.resize((diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter, diameter), fill=255)
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main() -> None:
    bold = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
    reg = ["/System/Library/Fonts/Supplemental/Arial.ttf",
           "/Library/Fonts/Arial Unicode.ttf"]

    title_font = _font(bold, 96)
    subtitle_font = _font(bold, 44)
    tagline_font = _font(reg, 28)
    url_font = _font(bold, 32)

    canvas = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(canvas)

    avatar_d = 440
    avatar_x = 70
    avatar_y = (H - avatar_d) // 2
    ring = avatar_d + 16
    draw.ellipse(
        (avatar_x - 8, avatar_y - 8, avatar_x - 8 + ring, avatar_y - 8 + ring),
        outline=BORDER,
        width=4,
    )
    avatar = _circle_avatar(AVATAR_SRC, avatar_d)
    canvas.paste(avatar, (avatar_x, avatar_y), avatar)

    text_x = avatar_x + avatar_d + 70
    text_right = W - 60
    text_w = text_right - text_x

    title = "Mewscast"
    subtitle = "Walter Croncat"
    tagline_lines = [
        "AI news reporter cat.",
        "Reads every wire. Compares",
        "every framing. Shows the receipts.",
    ]
    url = "mewscast.us"

    y = 110
    draw.text((text_x, y), title, font=title_font, fill=FG)
    y += 110

    accent_bar_h = 4
    draw.rectangle((text_x, y, text_x + 80, y + accent_bar_h), fill=ACCENT)
    y += 24

    draw.text((text_x, y), subtitle, font=subtitle_font, fill=FG)
    y += 70

    for line in tagline_lines:
        draw.text((text_x, y), line, font=tagline_font, fill=DIM)
        y += 38

    y = H - 90
    draw.text((text_x, y), url, font=url_font, fill=ACCENT)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT, "PNG", optimize=True)

    bbox = draw.textbbox((0, 0), title, font=title_font)
    print(f"wrote {OUTPUT} ({W}x{H}, title bbox {bbox})")


if __name__ == "__main__":
    main()
