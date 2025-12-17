# Shorten Tweet Prompt
# Used when a generated tweet exceeds the character limit

CRITICAL: This tweet is {current_length} characters but MUST be {max_length} characters or LESS.

## CURRENT TWEET (TOO LONG):
{tweet}

## YOUR TASK
Rewrite this to fit in **{max_length} characters MAX** (aim for {target_length} to be safe).

## RULES
1. COMPLETE THE THOUGHT - never end mid-sentence with "..." or trailing words
2. Cut less important details, keep the core news point
3. Preserve cat personality and any puns if possible
4. Keep line breaks for readability
5. Every word must serve the story - cut filler ruthlessly

## COMMON MISTAKES TO AVOID
- Ending with "Call it what..." or "Where's the..." - FINISH YOUR SENTENCE
- Adding new content instead of cutting
- Keeping all details when some can go

COUNT YOUR CHARACTERS. If it doesn't fit, cut more.

Return ONLY the shortened tweet, nothing else.
