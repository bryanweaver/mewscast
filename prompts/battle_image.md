# Battle Post Image Generation Prompt

You are creating a SPLIT-SCREEN comparison image for a cat news reporter bot. Two news outlets covered the SAME story very differently. The image should visually represent both sides.

## THE STORY
Topic: {topic}

## SOURCE A: {source_a}
Headline: {headline_a}
Key content: {content_a}

## SOURCE B: {source_b}
Headline: {headline_b}
Key content: {content_b}

## IMAGE REQUIREMENTS

Create a SHORT image prompt (max 200 chars) for an AI image generator that shows:

**COMPOSITION: Split-screen / triptych layout**
- LEFT SIDE: A cat scene that captures how {source_a} frames this story (their angle, tone, emphasis)
- CENTER: Close-up of a brown tabby cat investigator (Walter) looking between both sides, skeptical expression, maybe holding a magnifying glass or notepad
- RIGHT SIDE: A different cat scene that captures how {source_b} frames this story (their angle, tone, emphasis)

**KEY RULES:**
- The two side scenes should feel DIFFERENT from each other - different cats, different moods, different visual tones
- Left and right cats should be DIFFERENT breeds/colors to visually distinguish the sides
- Walter (brown tabby) is the CENTRAL investigator figure - close-up, facing camera
- The scenes should reflect the ACTUAL FRAMING differences between the outlets
- Horizontal landscape format, cinematic lighting
- Clear visual divide between the two sides

## CONTENT MODERATION - AVOID THESE
- NO sick/injured people or animals
- NO violence, weapons, or graphic content
- USE metaphors and symbols instead of literal depictions

## GOOD EXAMPLES

Story: Economy coverage (one outlet says booming, other says struggling)
"Split-screen: Left - sleek Siamese cat in luxury penthouse celebrating. Right - scrappy orange tabby in working kitchen worried. Center - brown tabby investigator with magnifying glass comparing both scenes"

Story: Political bill (one outlet praises, other criticizes)
"Triptych: Left - white Persian cat triumphantly waving documents. Right - black cat skeptically examining same papers. Center foreground - brown tabby reporter with notepad, raised eyebrow"

## BAD EXAMPLES
- "Cat at desk reading two newspapers" (boring, generic)
- "Two cats fighting" (too simple, no story connection)
- "Cat with split background" (vague, no narrative)

REMEMBER: Brown tabby (Walter) is ALWAYS center. Two DIFFERENT cat breeds on each side. Scenes must connect to the ACTUAL story framing differences.

Just return the SHORT image prompt itself (max 200 chars), nothing else.
