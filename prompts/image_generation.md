# Image Generation Prompt

You are helping create an engaging, visually striking image for a news cat reporter bot on X/Twitter.

The news topic is: {topic}

The tweet says: {tweet_text}
{article_section}
Generate an image prompt (max 400 chars) for an AI image generator that captures this story visually.

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

## ANATOMY RULES - ABSOLUTELY CRITICAL
- Walter is a REALISTIC cat — four paws, normal cat body, NO HUMAN HANDS
- NEVER say Walter is "holding", "gripping", "clutching", or "carrying" objects
- Instead: objects should be NEAR Walter, BESIDE him, IN FRONT of him, or in the BACKGROUND
- Use: "standing beside", "next to", "in front of", "with [object] nearby", "paws on"
- Walter can WEAR things (press badge, hat) but NOT hold things in his paws
- NO object-limb fusion — a gavel is next to him, not in his paw
- ALWAYS include: "realistic cat anatomy" somewhere in the prompt

## MAKE IT SCROLL-STOPPING
- Use BOLD, SATURATED colors — not muted or washed out
- HIGH CONTRAST between Walter and the background
- DRAMATIC angles — low angle looking up at Walter, or dynamic diagonal compositions
- STRONG LIGHTING — golden hour, dramatic shadows, neon glow, spotlights
- EMOTION in Walter's expression — determined, concerned, curious, stunned
- Think movie poster or magazine cover, not stock photo

## CONTENT MODERATION - AVOID THESE (will be rejected by AI)
- NO sick/injured people, especially children
- NO violence, weapons, or explicit medical imagery
- NO graphic suffering or disturbing content
- USE metaphors and symbols instead of literal depictions

## GOOD vs BAD EXAMPLES

Hong Kong high-rise fire story:
BAD: "Wide shot of city with tiny cat on distant rooftop" (Walter too small)
BAD: "Brown tabby cat holding fire hose on rooftop" (cats don't hold things!)
GOOD: "Close-up: Brown tabby reporter cat on rooftop railing, blazing bamboo scaffolding on high-rise behind him, orange glow reflected in eyes, realistic cat anatomy, dramatic low angle"

Courthouse story:
BAD: "Brown tabby cat holding gavel at courthouse" (object-limb fusion!)
GOOD: "Brown tabby reporter cat in foreground of courthouse steps, gavel and scales of justice beside him, dramatic sunset lighting, realistic cat anatomy, press badge visible"

Climate summit story:
BAD: "Cat with globe" (generic environmental)
GOOD: "Brown tabby reporter cat close-up at conference podium, oil barrel vs wind turbine clashing behind him, bold lighting, realistic cat anatomy, intense expression"

REMEMBER: Walter is a BROWN TABBY cat with REALISTIC ANATOMY (four paws, no human hands, never holding objects). He should be LARGE and PROMINENT in frame. Make it BOLD and SCROLL-STOPPING. Extract what's UNIQUE about THIS story as his BACKDROP.

Just return the image prompt itself (max 400 chars), nothing else.
