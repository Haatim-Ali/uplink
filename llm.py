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
            if line.startswith("sk-ant-") and "=" not in line:   # a bare Anthropic key pasted on its own
                os.environ.setdefault("ANTHROPIC_API_KEY", line)
                continue
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


# Was the key set in the terminal (or ~/.zshrc) before .env was read? That one wins over .env.
KEY_FROM_SHELL = "ANTHROPIC_API_KEY" in os.environ
_load_env_file()
_auth_error = None   # set once a provider rejects the key; then we stop calling it and fall back


def _is_auth_error(e):
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    return status in (401, 403) or type(e).__name__ in ("AuthenticationError", "PermissionDeniedError")


def key_hint():
    """'sk-ant-…a1b2 (from .env)' so you can tell which key is being used without printing it."""
    k = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    if not k:
        return "no key"
    src = "from your terminal or ~/.zshrc, which wins over .env" if (os.getenv("ANTHROPIC_API_KEY") and KEY_FROM_SHELL) else "from .env"
    return f"{k[:7]}…{k[-4:]} ({src})"


def auth_error():
    return _auth_error


def check_key():
    """One cheap call at startup so a bad key shows up immediately, not as silent fallbacks."""
    global _auth_error
    if provider() != "anthropic":
        return "no Claude key" if not os.getenv("OPENAI_API_KEY") else "OpenAI-compatible key set"
    try:
        _claude().models.list(limit=1)
        return f"Claude key OK: {key_hint()}"
    except Exception as e:  # noqa: BLE001
        if _is_auth_error(e):
            _auth_error = f"Claude rejected the key {key_hint()}"
            return _auth_error + ". Paste a valid key into .env (ANTHROPIC_API_KEY=...) and restart."
        return f"Couldn't check the Claude key ({type(e).__name__}); will try when needed"


def provider():
    if _auth_error:
        return None   # the key was rejected: behave as if there were no key (rules agents, demo vision)
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
    global _auth_error
    if _auth_error:
        raise RuntimeError(_auth_error)
    last = None
    for _ in range(retries + 1):
        try:
            text = _call(system, user, image_b64, media_type, max_tokens, model, effort)
            return _extract_json(text)
        except Exception as e:  # noqa: BLE001 - we retry then re-raise
            last = e
            if _is_auth_error(e):   # a bad key won't fix itself: stop calling, say so once
                if not _auth_error:
                    _auth_error = f"Claude rejected the key {key_hint()}"
                    print(f"!! {_auth_error}. Falling back to rules agents and demo vision. "
                          "Paste a valid key into .env (ANTHROPIC_API_KEY=...) and restart.", flush=True)
                break
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
