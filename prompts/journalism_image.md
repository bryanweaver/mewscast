# Journalism Image Prompt — Post-Type-Aware

You are creating an image prompt for Walter Croncat, an AI news reporter cat. The image must match the POST TYPE — different types get different visual treatments, like a real news broadcast where the field reporter looks different from the anchor desk.

**Post type:** `{post_type}`
**Story topic:** {topic}
**The post says:** {draft_text}
{article_section}

---

## VISUAL DIRECTION BY POST TYPE

### If post_type is REPORT or BULLETIN — "Reporter on Location"

Walter IS the field reporter here. He's at the scene, filing from the ground.

- Walter in the FOREGROUND, filling the frame — "news anchor on location" energy
- Extract the MOST SPECIFIC visual detail from the story for the backdrop: the actual location, the actual building, the actual object central to the story
- Make it look like a wire photographer caught Walter working
- For BULLETIN specifically: add a sense of urgency — breaking news energy, red/amber accents, movement
- Think: the reporter IS the story's witness

### If post_type is META — "The News Desk"

Walter is NOT at the scene. He's back at the newsroom, reading every outlet's coverage and comparing them. This is the ANCHOR DESK format.

- Walter seated at a professional TV news desk — this is the Cronkite visual
- Horn-rimmed glasses (cat-sized), press badge reading "PRESS / Walter Croncat"
- Behind him: a wall of screens or monitors showing different outlet logos or headline fragments — visually says "we compared the coverage"
- Lighting that matches the story domain:
  - Foreign affairs / war: cool blue
  - Politics / domestic: warm gold
  - Crime / courts: dramatic contrast
  - Economy / business: green tints
  - Science / tech: clean white
- CALM, authoritative expression — not dramatic, not urgent. This is the analyst, not the reporter.
- The desk IS the brand. The mood IS the story.

### If post_type is ANALYSIS — "The Commentary Desk"

This is the RARE opinion post. The visual must signal "this is different from our usual reporting."

- Walter at a DIFFERENT desk — smaller, more personal, warmer wood tones
- Warmer lighting than META (golden, intimate)
- A slightly different camera angle — maybe three-quarter view instead of straight-on
- More expressive Walter — thoughtful, maybe one eyebrow raised
- NO screens/monitors behind him — this is personal judgment, not coverage comparison
- Think: the Sunday morning talk show set, not the weekday news desk

### If post_type is PRIMARY — "The Document"

Walter is examining the primary source. The DOCUMENT is the visual focus.

- Walter with a document, filing, or official paper visible nearby (NOT in his paws — beside him or on the desk)
- The document should look official — government seal, court stamp, congressional header
- Walter examining it closely, glasses on, focused expression
- Clean, well-lit, almost archival feel
- Think: the reporter who actually reads the court filing

### If post_type is CORRECTION — "The Correction"

Stark, honest, unmistakable.

- Simple composition: Walter at the desk with a bold "CORRECTION" graphic visible
- Sober expression — not dramatic, not apologetic, just honest
- Clean background, no clutter
- The visual equivalent of "we got it wrong and we're fixing it"

---

## ALWAYS APPLY (all post types)

**Cat anatomy:**
- Walter is a REALISTIC brown tabby cat — four paws, normal cat body, NO HUMAN HANDS
- NEVER "holding", "gripping", "clutching" objects — objects are NEAR him, BESIDE him, on the desk
- ALWAYS include "realistic cat anatomy" in the prompt
- Press badge reads "PRESS" and "Walter Croncat" ONLY — never other text

**Technical:**
- HORIZONTAL LANDSCAPE format — cinematic framing
- BOLD, SATURATED colors with HIGH CONTRAST
- DRAMATIC lighting appropriate to the post type
- Walter must be PROMINENT in frame — not tiny in the background

**Content moderation:**
- NO sick/injured people, especially children
- NO violence, weapons, or explicit imagery
- USE metaphors and symbols instead of literal depictions of harm

---

## OUTPUT

Return ONLY the image prompt (max 400 chars). No explanation, no quotes, no markdown. Just the prompt text that goes directly to the image generator.
