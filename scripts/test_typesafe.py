"""Live smoke test for TYPESAFE_API_KEY.

Hits TypeSafe's System One API with one tiny news-desk state and two
typed questions. Confirms the key authenticates and Jev returns values
this repo can branch on. Not part of pytest — those tests stay offline.

Usage:
    python scripts/test_typesafe.py

Exit codes:
    0  key works, answers came back typed
    2  TYPESAFE_API_KEY is missing
    1  auth failure or unexpected API response
"""
from __future__ import annotations

import os
import sys

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # optional; GitHub Actions injects the secret into the env
    load_dotenv = None

API_URL = "https://api.typesafe.ai/v1/systemone"
MODELS_URL = "https://api.typesafe.ai/v1/models"
TIMEOUT_S = 20


def _key_prefix(api_key: str) -> str:
    """Show enough to confirm the right secret loaded, never the secret."""
    if len(api_key) <= 8:
        return "(short key)"
    return f"{api_key[:4]}…{api_key[-4:]} ({len(api_key)} chars)"


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        print("[test_typesafe] TYPESAFE_API_KEY is not set.")
        print("  Local: add it to .env (see .env.example).")
        print("  GitHub: repo Settings → Secrets and variables → Actions.")
        return 2

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    print(f"[test_typesafe] using key {_key_prefix(api_key)}")

    models_resp = requests.get(MODELS_URL, headers=headers, timeout=TIMEOUT_S)
    if models_resp.status_code == 401:
        print("[test_typesafe] FAIL — 401 from /v1/models. Key is missing or invalid.")
        return 1
    if models_resp.status_code != 200:
        print(
            f"[test_typesafe] FAIL — /v1/models returned {models_resp.status_code}: "
            f"{models_resp.text[:240]}"
        )
        return 1

    models_body = models_resp.json()
    model_names = []
    if isinstance(models_body, dict):
        raw_models = models_body.get("models") or models_body.get("data") or []
        if isinstance(raw_models, list):
            for item in raw_models:
                if isinstance(item, dict) and item.get("name"):
                    model_names.append(item["name"])
                elif isinstance(item, str):
                    model_names.append(item)
    print(f"[test_typesafe] /v1/models OK — {', '.join(model_names) or 'listed'}")

    payload = {
        "state": {
            "headline": "Senate voted 68-32 tonight to pass the appropriations bill, averting a shutdown.",
            "already_covered": "Congress passes spending package to keep the government open.",
        },
        "model": "jev-latest",
        "questions": {
            "same_event": {
                "type": "noul",
                "instructions": (
                    "Is `headline` the same news event as `already_covered`, "
                    "regardless of wording or outlet?"
                ),
            },
            "newsworthy": {
                "type": "noul",
                "instructions": (
                    "Does `headline` describe a genuine, checkable change in "
                    "the world (a vote, ruling, or similar), not gossip or vibe?"
                ),
            },
        },
    }

    eval_resp = requests.post(API_URL, headers=headers, json=payload, timeout=TIMEOUT_S)
    if eval_resp.status_code == 401:
        print("[test_typesafe] FAIL — 401 from /v1/systemone. Key is missing or invalid.")
        return 1
    if eval_resp.status_code != 200:
        print(
            f"[test_typesafe] FAIL — /v1/systemone returned {eval_resp.status_code}: "
            f"{eval_resp.text[:240]}"
        )
        return 1

    body = eval_resp.json()
    answers = body.get("answers") or {}
    same_event = answers.get("same_event") or {}
    newsworthy = answers.get("newsworthy") or {}
    same_noul = same_event.get("noul")
    news_noul = newsworthy.get("noul")
    usage = body.get("usage") or {}
    model = body.get("model", "unknown")

    if not isinstance(same_noul, (int, float)) or not isinstance(news_noul, (int, float)):
        print(f"[test_typesafe] FAIL — missing noul values in answers: {answers!r}")
        return 1

    print(f"[test_typesafe] model={model}")
    print(f"[test_typesafe] same_event.noul={same_noul:.3f}")
    print(f"[test_typesafe] newsworthy.noul={news_noul:.3f}")
    print(
        f"[test_typesafe] usage input_tokens={usage.get('input_tokens')} "
        f"output_tokens={usage.get('output_tokens')}"
    )
    print("[test_typesafe] OK — key works and Jev returned typed answers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
