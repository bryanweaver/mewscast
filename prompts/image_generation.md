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
- **WIDESCREEN LANDSCAPE format** - cinematic, horizontal composition
- **BROWN TABBY CAT MUST BE IN EVERY IMAGE** - Walter is a brown tabby reporter cat
- The cat MUST be visible - MANDATORY, non-negotiable
- Image MUST be directly relevant to the SPECIFIC story content
- Extract the most visually striking element from the article
- Cat can be protagonist (center) or observer (background), but MUST be present

## CONTENT MODERATION - AVOID THESE (will be rejected by AI)
- NO sick/injured people, especially children
- NO violence, weapons, or explicit medical imagery
- NO graphic suffering or disturbing content
- USE metaphors and symbols instead of literal depictions

## GOOD vs BAD EXAMPLES

Hong Kong high-rise fire story:
BAD: "Noir detective cat examining documents under desk lamp" (generic, ignores story)
GOOD: "Cinematic: Brown tabby reporter cat on Hong Kong rooftop, bamboo scaffolding ablaze on high-rise behind, orange glow, dramatic night scene"

MTG resignation story:
BAD: "Cat at desk looking at papers" (generic)
GOOD: "Wide shot: Brown tabby reporter at Capitol steps watching lone figure walk away, pension papers scattered in wind, dramatic sunset"

Climate summit story:
BAD: "Cat with globe" (generic environmental)
GOOD: "Brown tabby reporter cat in Brazil conference hall, delegates arguing, oil barrel vs wind turbine symbols clashing, tense atmosphere"

Ukraine peace plan story:
BAD: "Cat looking at map" (generic)
GOOD: "Split screen: Brown tabby reporter between Kyiv skyline and Thanksgiving dinner table, peace document floating between, surreal juxtaposition"

REMEMBER: Walter is a BROWN TABBY cat. Extract what's UNIQUE about THIS story. The cat witnesses/investigates the SPECIFIC scene described.

Just return the SHORT image prompt itself (max 200 chars), nothing else.
