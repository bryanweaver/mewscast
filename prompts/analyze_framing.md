# Analyze Media Framing Prompt
# Quick check to identify interesting framing angles in news articles

Quick check: Is there an interesting framing angle in this article worth noting?

HEADLINE: {title}
SOURCE: {source}
CONTENT: {content}

Look for ONE of these (pick the most notable):
- Headline vs reality gap (clickbait, buried lede, sensationalized)
- One-sided sourcing (only quotes one perspective)
- Missing context that changes the story
- Timing/placement that seems strategic
- Numbers used misleadingly

Return JSON:
{{
  "has_issues": true/false,
  "angle": "Brief 10-word description of the framing issue" or null
}}

Only flag if there's something genuinely interesting to point out. Most articles are fine.
Return ONLY JSON.
