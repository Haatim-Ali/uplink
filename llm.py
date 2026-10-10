"""Thin wrapper for a cloud AI model. Works with Anthropic (official SDK), OpenAI, or any
OpenAI-compatible endpoint (e.g. vLLM on a Brev GPU, NVIDIA NIM) via OPENAI_BASE_URL.

Keys come from the environment or from a .env file in the repo root (git-ignored):
    ANTHROPIC_API_KEY=sk-ant-...
With no key set, everything still runs: vision returns a labeled demo result and
the agents use their rules-based reasoning.
"""
import json
import os
import re

import requests

TIMEOUT = 60
HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_MODEL = "claude-opus-5-5"


def _load_env_file(path=os.path.join(HERE, ".env")):
    """Read KEY=VALUE lines from .env without overriding anything already set in the shell."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env_file()


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


def chat_json(system, user, image_b64=None, media_type="image/jpeg", max_tokens=400, model=None, retries=1,
              effort="medium"):
    """Ask the model for a JSON object. Raises on failure (callers fall back).
    effort (Claude only): "low" for quick agent votes, "high" for careful photo counting."""
    last = None
    for _ in range(retries + 1):
        try:
            text = _call(system, user, image_b64, media_type, max_tokens, model, effort)
            return _extract_json(text)
        except Exception as e:  # noqa: BLE001 - we retry then re-raise
            last = e
    raise last


_client = None


def _claude():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(timeout=TIMEOUT)  # reads ANTHROPIC_API_KEY; retries 429/5xx itself
    return _client


def _call(system, user, image_b64, media_type, max_tokens, model, effort):
    p = provider()
    if p == "anthropic":
        content = []
        if image_b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}})
        content.append({"type": "text", "text": user})
        # Claude thinks before answering and that counts toward max_tokens, so callers' small
        # limits (sized for the open model) would cut the answer off. Give it room.
        r = _claude().beta.messages.create(
            model=model or os.getenv("ANTHROPIC_MODEL", CLAUDE_MODEL),
            max_tokens=max(max_tokens, 16000),
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # if a request is declined by a safety filter, retry on a fallback model
        )
        if r.stop_reason == "refusal":
            raise RuntimeError("model declined the request")
        return "".join(b.text for b in r.content if b.type == "text")
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
