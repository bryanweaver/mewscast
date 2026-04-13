# Headline vs Reality — Mismatch Analysis

You are analyzing a news article to determine whether its headline accurately represents
what the article body actually says.

## ⚠️ CRITICAL: READ BEFORE ANALYZING

Your training data is OUTDATED. The article below was published recently and describes
CURRENT events. Apply these rules without exception:

- **ONLY** make claims that are directly stated in the article text provided below.
- If something is not explicitly stated in the article, it does not exist for this analysis.
- **NEVER** fill in details, context, or background from your general knowledge.
- **NEVER** comment on dates, timelines, or whether events "could have" happened.
- **NEVER** dispute or fact-check the article content itself — only compare headline to body.
- Treat every factual claim in the article as TRUE and CURRENT.
- If the article says X happened, X happened. Do not contradict it.

## ARTICLE TO ANALYZE

HEADLINE: {headline}

ARTICLE TEXT:
{article_text}

## WHAT TO CHECK

Compare what the HEADLINE claims or implies against what the ARTICLE BODY actually says.
Look for these specific gaps:

1. **Overstated certainty** — headline presents as definite something the article calls tentative, preliminary, or possible
2. **Missing qualifiers** — headline drops a word that fundamentally changes the meaning (e.g., "expected", "proposed", "claimed", "may")
3. **Attribution error** — headline treats one person's claim as established fact
4. **Scope inflation** — headline implies broader agreement, impact, or consensus than the article shows
5. **False conclusion** — headline states a result or outcome that the article describes as still in progress
6. **Selective emphasis** — headline buries a critical caveat the article leads with, or vice versa

Do NOT flag:
- Minor word choice differences that don't change meaning
- Standard journalistic shorthand
- Stylistic compression that is accurate in substance
- Issues you're not completely certain about

Default to NO mismatch unless the gap is clear and specific.

## OUTPUT FORMAT

Return ONLY valid JSON. No commentary before or after. No code fences. Just the JSON:

{{
  "has_mismatch": true,
  "headline_claims": "One to two sentences describing what the headline says or implies.",
  "article_actually_says": "- Bullet point one\n- Bullet point two\n- Bullet point three",
  "mismatch_description": "One to two sentences describing the specific gap between headline and article.",
  "severity": "minor"
}}

Severity levels:
- **"minor"**: Slightly overstated but the core claim is supportable
- **"moderate"**: Headline implies something the article does not fully support
- **"major"**: Headline directly contradicts or grossly overstates what the article says

If the headline is ACCURATE and matches the article, return:

{{
  "has_mismatch": false,
  "headline_claims": "What the headline says.",
  "article_actually_says": "What the article says (which matches the headline).",
  "mismatch_description": null,
  "severity": null
}}

Return ONLY JSON. Nothing else.
