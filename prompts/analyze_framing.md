# Analyze Media Framing Prompt
# Quick check to identify interesting framing angles in news articles

Quick check: Is there an OBVIOUS, CLEAR framing issue in this article?

HEADLINE: {title}
SOURCE: {source}
CONTENT: {content}

ONLY flag if you see something UNMISTAKABLY wrong - like:
- Headline that clearly contradicts the article content
- Numbers that are obviously misleading (e.g., "SOARING 0.2%!")
- A claim with zero sources when sources would be expected

DEFAULT TO "has_issues": false. Most articles are fine journalism.

CRITICAL RULES:
- Do NOT invent issues that aren't clearly there
- Do NOT claim something is "missing" unless you're 100% certain it's not in the content
- Do NOT speculate about attribution, wire services, or sourcing
- If you're not ABSOLUTELY SURE there's a real issue, return false

Return JSON:
{{
  "has_issues": true/false,
  "angle": "Brief 10-word description of the CLEAR issue" or null
}}

When in doubt, return {{"has_issues": false, "angle": null}}
Return ONLY JSON.
