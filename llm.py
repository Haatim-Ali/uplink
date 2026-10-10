"""Thin wrapper for a cloud AI model. Works with Anthropic, OpenAI, or any
OpenAI-compatible endpoint (e.g. NVIDIA NIM via OPENAI_BASE_URL).

With no API key set, everything still runs: vision returns a demo result and
the agents use their rules-based reasoning.
"""
import json
import os
import re

import requests

TIMEOUT = 40


def provider():
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return None


def available():
    return provider() is not None


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def chat_json(system, user, image_b64=None, media_type="image/jpeg", max_tokens=400, model=None, retries=1):
    """Ask the model for a JSON object. Raises on failure (callers fall back)."""
    last = None
    for _ in range(retries + 1):
        try:
            text = _call(system, user, image_b64, media_type, max_tokens, model)
            return _extract_json(text)
        except Exception as e:  # noqa: BLE001 - we retry then re-raise
            last = e
    raise last


def _call(system, user, image_b64, media_type, max_tokens, model):
    p = provider()
    if p == "anthropic":
        content = []
        if image_b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}})
        content.append({"type": "text", "text": user})
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    if p == "openai":
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        if image_b64:
            content = [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
            ]
        else:
            content = user
        r = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={
                "model": model or os.getenv("OPENAI_MODEL", "gpt-4o"),
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("No API key set")
