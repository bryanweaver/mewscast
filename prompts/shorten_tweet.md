# Shorten Tweet Prompt
# Used when a generated tweet exceeds the character limit

This tweet is {current_length} characters but must be {max_length} characters MAXIMUM.

CURRENT TWEET:
{tweet}

Shorten it to fit in {max_length} characters while:
1. Keeping the core news point and cat personality
2. Preserving any cat puns/wordplay if possible
3. Maintaining line breaks for readability
4. NOT cutting off words mid-way

Return ONLY the shortened tweet, nothing else.
