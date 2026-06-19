# Journalism Image Prompt — Post-Type-Aware

You are creating an image prompt for Walter Croncat, an AI news reporter cat. The image must match the POST TYPE — different types get different visual treatments, like a real news broadcast where the field reporter looks different from the anchor desk.

**Post type:** `{post_type}`
**Shot type:** `{shot_type}`
**Story topic:** {topic}
**The post says:** {draft_text}
{article_section}

---

## NON-NEGOTIABLE CYCLE INPUTS

These four inputs were rolled *before* you saw this story. They are not suggestions, they are constraints — bake all four into your output prompt or the output is wrong.

**Cat behavior (Walter MUST be doing this):**
{cat_behavior}

**Press badge:**
{badge_instruction}

**Chyron:**
{chyron_instruction}

Treat the cat-behavior instruction as the spine of the image — pick the shot framing, environment, and story object around what Walter is actively doing. A static "Walter standing in front of X" prompt is wrong; the behavior is the verb of the image.

---

## SHOT TYPE — applies to all post types

The shot type controls **camera angle, framing, and what's actually in frame**. It is independent of post type. Where the post type sets the *vibe* (field reporter vs anchor desk vs commentary), the shot type sets the *composition*. Both must be honored — don't let one override the other.

**Even within a single shot type, vary Walter's pose and behavior.** The shot type defines the *framing*, not what Walter is *doing*. The same shot type should produce a different Walter every time — sniffing, batting, perched, turned away, mid-reaction (see "WALTER IS A CAT" below). Two posts that draw the same shot type must not look like the same photo with a new backdrop.

**This cycle's shot type instruction:**

{shot_type_description}

If the shot type and post type seem to conflict (e.g. a META anchor-desk post drawing a WIDE_ESTABLISHING shot type), reconcile by keeping the post-type vibe but applying the shot-type composition — for the example, a wide establishing shot of the *newsroom itself*, with Walter small at his anchor desk in the corner of the frame, monitors filling the wall behind. The location/setting still matches the post type; only the camera angle and crop change.

---

## TELL THE STORY, NOT THE SETTING — this is the #1 rule

The most common failure is a generic "Walter standing in front of a famous building" image. A SCOTUS story about weed smokers being allowed to own guns should NOT produce "Walter in front of the Supreme Court." That image could illustrate ANY court story — it tells the viewer nothing.

**Core rules:**
- The image should tell the STORY, not show the SETTING. A viewer should be able to guess what the article is about from the image alone.
- Focus on the OBJECTS, EVIDENCE, and STAKES of the story — documents, weapons, money, substances, technology, people affected.
- Avoid exterior establishing shots of famous buildings. Go INSIDE. Show the specific scene where the story's tension lives.
- If the story involves a policy change or ruling, show the IMPACT on real people/objects, not the institution that made the ruling.

**The test:** strip the caption away. Could someone see the image alone and roughly guess the headline? If the answer is "it's some court/political/tech story" — you picked the lazy setting. If the answer is "it's about guns and cannabis being legally linked" — you nailed the story.

### Category examples — find the OBJECTS and CONFLICT of THIS story

**Court / Legal stories:**
- BAD: Walter in front of the Supreme Court building.
- GOOD: Walter at a judge's bench examining a cannabis leaf next to a holstered firearm, with a constitutional document unfurled behind them.
- GOOD: Walter studying a court opinion document with key phrases visible, dramatic side-lighting.

**Political stories:**
- BAD: Walter in front of the Capitol / White House.
- GOOD: Walter in a smoke-filled back room with lobbyists' briefcases and a wall of campaign donation charts.
- GOOD: Walter at a podium surrounded by microphones, flashbulbs popping, with protest signs visible in the background.

**Economic / Finance stories:**
- BAD: Walter in front of Wall Street or a bank.
- GOOD: Walter on a trading floor staring at plummeting red ticker screens, papers flying.
- GOOD: Walter at a kitchen table surrounded by bills and an overdue notice, warm lamplight.

**Crime / Justice stories:**
- BAD: Walter in front of a police station or courthouse.
- GOOD: Walter in an evidence room examining tagged items under harsh fluorescent light.
- GOOD: Walter behind crime scene tape with forensic markers visible.

**Tech stories:**
- BAD: Walter in front of a tech company HQ.
- GOOD: Walter at a cluttered dev workstation with multiple monitors showing code and a cracked phone screen.
- GOOD: Walter inside a server room with blinking lights and dangling ethernet cables.

**Military / International stories:**
- BAD: Walter in front of a military base or embassy.
- GOOD: Walter in a press vest at a checkpoint with sandbags, looking through binoculars at a distant horizon.
- GOOD: Walter at a diplomatic table with flags and untouched coffee cups, tense body language.

These categories are illustrative, not exhaustive — apply the same instinct to health, sports, science, climate, and any other beat: find the specific objects, evidence, and human stakes of THIS story and build the scene around them.

---

## WALTER IS A CAT — LET HIM ACT LIKE ONE

The second-most-common failure is sameness: Walter centered in frame, facing the camera, the lens looking heroically up at him, every single time. It reads as a stiff mascot pose, not a photograph. Walter is a CAT — the most engaging images let him behave like one and catch him candidly.

**Walter doesn't have to be centered.** He can be off to the side, in the background, partially obscured behind an object, or reduced to a single telling detail — just his paw on a document, or his tail curling out of frame.

**Walter doesn't have to face the camera.** He can be turned away, looking at something, sniffing something, batting at something. A cat absorbed in his own world is more natural than one posing for a portrait.

**Use CAT BEHAVIORS to interact with the story's objects:**
- Sniffing a suspicious document or piece of evidence
- Batting at a gavel or a microphone
- Sitting ON TOP OF important papers or a laptop
- Peering around a corner at a crime scene
- Knocking something off a desk (classic cat move)
- Grooming himself while chaos unfolds behind him (pure feline indifference)
- Curled up asleep on a pile of classified documents
- Stalking / hunting a piece of evidence like prey
- Pawing at a screen showing stock prices or election results

**Vary the camera relationship — NOT always a low-angle hero shot looking up:**
- Overhead / bird's-eye looking DOWN at Walter examining something on a desk
- Eye-level candid, as if a photojournalist caught him mid-action
- Over-the-shoulder, seeing what Walter sees
- Wide shot where Walter is small in frame and the environment tells the story
- Close-up on Walter's face reacting to something off-camera
- Dutch angle (tilted horizon) for tension or unease

**Why this matters for engagement:** the cat behaviors make images MORE shareable because they're funny and relatable. A cat sitting smugly on top of a stack of classified documents is inherently more engaging — and more on-brand — than a cat standing heroically in front of a building. Lean into the humor and the candor; that's what makes people stop and share.

(Anatomy still applies: Walter is a realistic four-paw cat with no human hands — see ALWAYS APPLY below. "Batting at" and "pawing at" use his actual paws; he never grips or holds.)

---

## VISUAL DIRECTION BY POST TYPE

### If post_type is REPORT or BULLETIN — "Reporter on Location"

Walter IS the field reporter here. He's at the scene, filing from the ground.

- Walter in the FOREGROUND, filling the frame — "news anchor on location" energy
- Extract the MOST SPECIFIC visual detail from the story for the backdrop: the actual location, the actual building, the actual object central to the story
- Make it look like a wire photographer caught Walter working
- For BULLETIN specifically: add a sense of urgency — breaking news energy, red/amber accents, movement
- Think: the reporter IS the story's witness

**Backdrop selection — push past the obvious.** Reach for the SPECIFIC SCENE inside the story, not the generic landmark associated with the institution. Wire photographers go INSIDE the event, not outside the building.

- BAD (lazy generic): a Congress story → Walter in front of the Capitol dome. A Pentagon story → Walter in front of the Pentagon. A SCOTUS story → Walter in front of the Supreme Court steps. A White House story → Walter in front of the West Wing.
- GOOD (story-specific): a Congress vote story → press gallery overlooking the House floor with the vote tally board visible. A Pentagon UFO-video release → a darkened briefing room with a declassified infrared video frozen on the screen, or a cockpit-view monitor showing the UAP footage. A SCOTUS decision → the marble courtroom interior with bench and seal, OR a stack of bound opinions on a clerk's desk. A White House diplomatic story → the press briefing room lectern with the relevant flag, or the Oval Office viewed past Walter's shoulder.

The test: would a reader who already knows the story (Pentagon UFO release, congressional vote, court ruling) learn anything from the backdrop, or could it be ANY story about that institution? If the latter, you picked the lazy backdrop. Reach for the INTERIOR, the EVENT, the OBJECT — not the EXTERIOR of the headquarters.

Other backdrop angles to consider when the institutional exterior is the default temptation:
- The room where the news actually happened (briefing room, hearing room, situation room, press pool)
- The artifact at the center of the story (document with seal, video frame, evidence display, the weapon system or vehicle that's the subject)
- The audience or counterpart (witnesses being sworn in, press corps raising hands, a foreign counterpart at a podium)
- The aftermath or evidence (impact site, evidence locker, crowd, crime-scene tape — IF appropriate to the story's gravity)
- An over-the-shoulder or oblique frame that catches the building only as context, not centerpiece

### If post_type is META — "The News Desk"

Walter is NOT at the scene. He's back at the newsroom, reading every outlet's coverage and comparing them. This is the ANCHOR DESK format.

- Walter seated at a professional TV news desk — classic anchor visual
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

**Cat anatomy (still your job — anchor doesn't enforce this hard enough):**
- Walter is a REALISTIC brown tabby cat — four paws, normal cat body, NO HUMAN HANDS
- NEVER "holding", "gripping", "clutching" objects — objects are NEAR him, BESIDE him, on the desk
- Defer to the press-badge instruction above — do not add badge language on your own

**Frame:**
- Walter's prominence in frame is set by the SHOT TYPE — don't override it
- Don't lock Walter to dead-center on every prompt; respect the shot-type composition

**Content moderation:**
- NO sick/injured people, especially children
- NO violence, weapons, or explicit imagery
- USE metaphors and symbols instead of literal depictions of harm

**Token discipline — the locked style anchor handles these, DO NOT repeat them:**
The image generator prepends a fixed style anchor that already specifies cinematic lighting, high contrast, saturated colors, scroll-stopping editorial composition, photographic lens treatment (85mm / shallow DoF / three-point), realistic brown-tabby anatomy, and horizontal landscape format. If you repeat these tokens in your output prompt, the model overweights them and every image starts to look the same. **Do not include the words "cinematic," "high contrast," "saturated colors," "realistic cat anatomy," "horizontal landscape," "dramatic lighting," "85mm," "scroll-stopping" in your output.** Spend your token budget on the scene, the objects, the behavior, the badge instruction (relay it verbatim if a badge is specified), and the chyron — the only things this dynamic prompt actually contributes. (The press-badge instruction above is per-cycle; relay it as given, don't override it.)

---

## OUTPUT

Return ONLY the image prompt (max 400 chars). No explanation, no quotes, no markdown. Just the prompt text that goes directly to the image generator.
