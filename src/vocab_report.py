#!/usr/bin/env python3
"""
Vocab diagnostic report for Mewscast.

Run: python -m src.vocab_report
  or: python src/vocab_report.py

Shows which cat phrases are overused, underused, and what the anti-repetition
system is currently filtering out.
"""
import json
import os
import sys
import yaml
from collections import Counter


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def load_posts():
    history_path = os.path.join(os.path.dirname(__file__), '..', 'posts_history.json')
    if not os.path.exists(history_path):
        return []
    with open(history_path, 'r') as f:
        data = json.load(f)
        return data.get('posts', [])


def load_recent_phrases():
    recent_path = os.path.join(os.path.dirname(__file__), '..', 'recent_vocab.json')
    if not os.path.exists(recent_path):
        return []
    try:
        with open(recent_path, 'r') as f:
            data = json.load(f)
            return data.get('recent_phrases', [])
    except (json.JSONDecodeError, IOError):
        return []


def get_all_phrases(config):
    """Get all phrases from all categories + universal."""
    phrases = []
    vocab_by_topic = config['content'].get('cat_vocabulary_by_topic', {})
    for cat, data in vocab_by_topic.items():
        for phrase in data.get('phrases', []):
            phrases.append((cat, phrase))

    universal = config['content'].get('cat_vocabulary_universal', [])
    for phrase in universal:
        phrases.append(('universal', phrase))

    return phrases


def run_report():
    config = load_config()
    posts = load_posts()
    recent = load_recent_phrases()
    all_phrases = get_all_phrases(config)

    # Extract post texts
    texts = [p.get('content', '') for p in posts if p.get('content')]
    total_posts = len(texts)

    print("=" * 60)
    print("  MEWSCAST VOCAB DIAGNOSTIC REPORT")
    print("=" * 60)
    print(f"\n  Total posts analyzed: {total_posts}")
    print(f"  Total phrases in vocab: {len(all_phrases)}")
    print(f"  Phrases in anti-repetition filter: {len(recent)}")

    # Count phrase usage across all posts
    phrase_counts = Counter()
    for category, phrase in all_phrases:
        phrase_lower = phrase.lower()
        for text in texts:
            if phrase_lower in text.lower():
                phrase_counts[phrase] += 1

    # --- OVERUSED ---
    print(f"\n{'=' * 60}")
    print("  OVERUSED (appeared in 5%+ of posts)")
    print(f"{'=' * 60}")
    overused = [(p, c) for p, c in phrase_counts.most_common() if c / max(total_posts, 1) >= 0.05]
    if overused:
        for phrase, count in overused:
            pct = count / total_posts * 100
            cat = next((c for c, p in all_phrases if p == phrase), '?')
            bar = "#" * min(int(pct), 40)
            print(f"  {count:3d}x ({pct:4.1f}%) [{cat:>14s}] {phrase}")
            print(f"         {bar}")
    else:
        print("  None! Great variety.")

    # --- NEVER USED ---
    print(f"\n{'=' * 60}")
    print("  NEVER USED (available but never appeared in posts)")
    print(f"{'=' * 60}")
    never_used = [(cat, phrase) for cat, phrase in all_phrases if phrase_counts[phrase] == 0]
    if never_used:
        by_category = {}
        for cat, phrase in never_used:
            by_category.setdefault(cat, []).append(phrase)
        for cat in sorted(by_category):
            print(f"\n  [{cat}]")
            for phrase in by_category[cat]:
                print(f"    - {phrase}")
    else:
        print("  All phrases have been used at least once!")

    # --- CATEGORY BREAKDOWN ---
    print(f"\n{'=' * 60}")
    print("  USAGE BY CATEGORY")
    print(f"{'=' * 60}")
    vocab_by_topic = config['content'].get('cat_vocabulary_by_topic', {})
    for cat_name in sorted(vocab_by_topic):
        cat_phrases = vocab_by_topic[cat_name].get('phrases', [])
        total_in_cat = len(cat_phrases)
        used_in_cat = sum(1 for p in cat_phrases if phrase_counts[p] > 0)
        total_uses = sum(phrase_counts[p] for p in cat_phrases)
        print(f"\n  {cat_name:>15s}: {used_in_cat}/{total_in_cat} phrases used, {total_uses} total appearances")
        # Show keywords for reference
        keywords = vocab_by_topic[cat_name].get('keywords', [])[:5]
        print(f"                   keywords: {', '.join(keywords)}...")

    # --- ANTI-REPETITION FILTER ---
    print(f"\n{'=' * 60}")
    print("  ANTI-REPETITION FILTER (currently blocked)")
    print(f"{'=' * 60}")
    if recent:
        for i, phrase in enumerate(recent, 1):
            print(f"  {i:2d}. {phrase}")
        print(f"\n  These {len(recent)} phrases will be excluded from the next post's prompt.")
    else:
        print("  Filter is empty - all phrases available.")

    print(f"\n{'=' * 60}")
    print()


if __name__ == '__main__':
    run_report()
