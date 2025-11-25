# Update Detection System

## Problem

The bot was posting similar stories multiple times without clearly differentiating what was new. For example:

- **Trump sedition story** - posted 3 times with same information
- **MTG resignation** - posted 2 times without indicating the second was reactions
- **COP30 climate** - posted 2 times with contradictory-seeming information

This made the bot appear repetitive and confusing to readers.

## Solution

Added an intelligent update detection system that:

1. **Detects story clusters** - Groups related articles by shared entities and keywords
2. **Identifies updates** - Uses keyword matching to detect when articles are updates vs duplicates
3. **Provides context** - Passes previous posts to content generator
4. **Requires labels** - Enforces UPDATE:/DEVELOPING:/REACTION: prefixes for follow-ups
5. **Highlights differences** - Prompts emphasize what's NEW or DIFFERENT

## How It Works

### 1. Story Clustering (`PostTracker._find_story_cluster`)

When checking a new article:
- Extracts proper nouns (Trump, Greene, etc.) and keywords
- Compares with recent posts (last 48 hours)
- Calculates similarity with bonuses for matching entities:
  - 2+ entities match = 80% similarity (strong signal)
  - 1 entity matches = +20% boost
  - Includes stem matching (seditious/sedition)
- Threshold: 25% similarity to be considered related

### 2. Update Detection (`PostTracker._is_update_story`)

Checks title for update keywords:
- `update`, `breaking`, `developing`
- `reaction`, `responds`, `response`
- `says`, `claims`, `denies`
- `walkback`, `reversal`
- `shocked`, `surprise`
- `announces`, `announcement`

### 3. Decision Flow (`PostTracker.check_story_status`)

```
Check article → Find related posts
                     ↓
            Has update keywords?
               ↙         ↘
            YES          NO
             ↓            ↓
      Allow as UPDATE   Check similarity
                             ↓
                        > 40% similar?
                           ↙    ↘
                         YES    NO
                          ↓      ↓
                       BLOCK   ALLOW
```

Returns:
- `is_duplicate`: Block (exact URL or too similar)
- `is_update`: Allow with context (related + update keywords)
- `previous_posts`: Context for content generation

### 4. Content Generation (`ContentGenerator`)

When `is_update = True`:
- Receives previous related posts
- Prompt includes:
  - Previous post content and timestamps
  - **MANDATORY** requirement for UPDATE/DEVELOPING/REACTION labels
  - Instructions to highlight what's NEW
  - Examples of good vs bad update posts

Example prompt addition:
```
🚨 THIS IS AN UPDATE TO A PREVIOUS STORY 🚨

You have ALREADY posted about this story:
Post #1 (Nov 21 at 07:02PM):
   Title: Trump: Democrats' message to troops seditious behavior...
   Content: Trump says Dems' troop message is "seditious"...

MANDATORY:
1. Start with UPDATE:/DEVELOPING:/REACTION: label
2. Highlight what's NEW or DIFFERENT
3. Make progression clear ("After [X], now...")
```

## Configuration

In `config.yaml` (optional):

```yaml
deduplication:
  enabled: true
  topic_cooldown_hours: 48          # How far back to look for clusters
  topic_similarity_threshold: 0.40  # Block threshold for non-updates
  content_cooldown_hours: 72        # Content similarity window
  content_similarity_threshold: 0.65 # Block threshold for similar content
  update_keywords:                   # Custom update keywords
    - update
    - breaking
    # ... etc
```

## Testing

Run the test suite:

```bash
uv run python test_update_detection.py
```

Tests verify:
- Trump sedition story (3 posts) - walkback detected as UPDATE
- MTG resignation (2 posts) - reactions detected as UPDATE

## Results

**Before:**
```
Post 1: Trump says Dems' message is seditious...
Post 2: Trump says Dems' message is seditious... (slightly different words)
Post 3: Trump says Dems' message is seditious... (readers confused)
```

**After:**
```
Post 1: Trump says Dems' message is seditious...
[System detects Post 2 is related + has "responds" keyword]
Post 2: REACTION: Rep. Crow responds to Trump's sedition threat...
[System detects Post 3 is related + has "says" keyword]
Post 3: UPDATE: Trump says he wasn't threatening after calling Dems' video "seditious."
        Within 24 hours: accusation, then walkback.
```

## Files Modified

- `src/post_tracker.py` - Added `check_story_status()`, `_find_story_cluster()`, improved entity extraction
- `src/content_generator.py` - Added `previous_posts` parameter, update detection prompts
- `src/main.py` - Use `check_story_status()` instead of `is_duplicate()`, pass context to generator
- `test_update_detection.py` - Test suite for clustering logic

## Future Improvements

1. **ML-based clustering** - Use embeddings for better semantic matching
2. **Story lifecycle tracking** - Track stories over longer periods (days/weeks)
3. **Automatic label selection** - Use LLM to choose best label (UPDATE vs REACTION vs DEVELOPING)
4. **Cross-topic detection** - Detect when different-seeming stories are actually related
