# Image Generation Prompt

You are helping create an engaging, visually striking image for a news cat reporter bot on X/Twitter.

The news topic is: {topic}

The tweet says: {tweet_text}
{article_section}
Generate a SHORT image prompt (max 200 chars) for an AI image generator that captures this story visually.

## CRITICAL - STORY-SPECIFIC IMAGERY
Your #1 job is to extract SPECIFIC visual details from the article that make THIS story unique.
- What LOCATION is mentioned? (Hong Kong skyline, Capitol building, Brazilian conference hall, etc.)
- What OBJECTS are central to the story? (bamboo scaffolding, pension documents, oil barrels, etc.)
- What SCENE is described? (high-rise fire, resignation announcement, climate summit, etc.)
- What makes this story VISUALLY DISTINCT from others?

## AVOID GENERIC IMAGERY
- DON'T default to "cat examining papers under desk lamp" - that's lazy
- DON'T use generic "noir detective" unless the story actually involves investigation
- DON'T ignore specific locations/objects mentioned in the article
- DO create a scene that could ONLY belong to THIS specific story

## CRITICAL REQUIREMENTS
- **HORIZONTAL LANDSCAPE format** - cinematic, but NOT ultra-wide or panoramic
- **BROWN TABBY CAT (Walter) MUST BE PROMINENT** - medium shot or closer, filling a significant portion of the frame
- Walter should be in the FOREGROUND, large and clearly visible — NOT tiny in the background
- Think "news anchor on location" framing — Walter is the STAR, the scene is the backdrop
- Image MUST be directly relevant to the SPECIFIC story content
- Extract the most visually striking element from the article

## CONTENT MODERATION - AVOID THESE (will be rejected by AI)
- NO sick/injured people, especially children
- NO violence, weapons, or explicit medical imagery
- NO graphic suffering or disturbing content
- USE metaphors and symbols instead of literal depictions

## GOOD vs BAD EXAMPLES

Hong Kong high-rise fire story:
BAD: "Wide shot of city with tiny cat on distant rooftop" (Walter too small)
GOOD: "Close-up: Brown tabby reporter cat gripping rooftop railing, blazing bamboo scaffolding on high-rise reflected in his eyes, orange glow, dramatic"

MTG resignation story:
BAD: "Wide shot: cat far away on Capitol steps" (Walter lost in scene)
GOOD: "Brown tabby reporter cat foreground holding microphone at Capitol steps, lone figure walking away in background, papers in wind, sunset"

Climate summit story:
BAD: "Cat with globe" (generic environmental)
GOOD: "Brown tabby reporter cat close-up at conference podium, oil barrel vs wind turbine clashing behind him, delegates arguing in background"

Ukraine peace plan story:
BAD: "Cat looking at map from far away" (Walter too distant)
GOOD: "Brown tabby reporter cat holding peace document, Kyiv skyline behind left shoulder, dramatic lighting, determined expression"

REMEMBER: Walter is a BROWN TABBY cat. He should be LARGE and PROMINENT in frame — think TV news correspondent on location. Extract what's UNIQUE about THIS story as his BACKDROP.

Just return the SHORT image prompt itself (max 200 chars), nothing else.
