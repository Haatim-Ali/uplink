"""ElevenLabs voice: each agent speaks with its own voice, and shelters can answer requests out loud.

- speak(who, text)      -> mp3 bytes (text to speech), cached so a replay costs nothing
- transcribe(audio)     -> what the shelter said (speech to text, ElevenLabs Scribe)
- parse_answer(text, n) -> {"accept": bool, "servings": int|None} or None if unclear

With no ELEVENLABS_API_KEY, available() is False and the browser falls back to its built-in voice.
"""
import hashlib
import os
import re

import requests

API = "https://api.elevenlabs.io/v1"
TIMEOUT = 30
WHO = ["Speed", "Cost", "Need", "Dispatch", "Shelter"]
# ElevenLabs' default voices: they work on every plan, including free keys that can't use library voices or list
# the account's voices. Override any of them with ELEVEN_VOICE_<SPEAKER> in .env.
DEFAULTS = {"Speed": "TX3LPaxmHKxFdv7VOQHJ",      # Liam: energetic, young
            "Cost": "nPczCjzI2devNBz1zQrb",       # Brian: deep, measured
            "Need": "EXAVITQu4vr4xnSDxMaL",       # Sarah: warm
            "Dispatch": "cgSgspJ2msm6clMCkdW9",   # Jessica: friendly, conversational
            "Shelter": "iP95p4xoKVk53GoZ742B"}    # Chris: casual
MODEL = "eleven_v3"   # the most expressive model; reads cues like [excited] or [sighs] written in the text
TAG = re.compile(r"\[[^\]]*\]\s*")

_cache = {}
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tts_cache")


def key():
    return os.getenv("ELEVENLABS_API_KEY", "")


def available():
    return bool(key())


def _headers():
    return {"xi-api-key": key()}


def voices():
    """Speaker -> voice id: .env overrides, else ElevenLabs' default voices."""
    return {w: os.getenv(f"ELEVEN_VOICE_{w.upper()}") or DEFAULTS[w] for w in WHO}


def delivery(text, model):
    """ElevenLabs v3 reads cues like [excited] or [sighs] written in the text; other models would say them out loud."""
    return text if model.startswith("eleven_v3") else TAG.sub("", text)


def speak(who, text):
    """Text -> mp3 bytes in this speaker's voice. Raises on failure (the browser falls back)."""
    who = who if who in WHO else "Dispatch"
    text = (text or "").strip()[:600]
    if not text:
        raise ValueError("empty text")
    vid = voices()[who]
    model = os.getenv("ELEVEN_MODEL", MODEL)
    text = delivery(text, model)
    h = hashlib.sha1(f"{vid}|{model}|{text}".encode()).hexdigest()
    if h in _cache:
        return _cache[h]
    path = os.path.join(CACHE_DIR, h + ".mp3")
    if os.path.exists(path):
        with open(path, "rb") as f:
            _cache[h] = f.read()
        return _cache[h]
    r = requests.post(f"{API}/text-to-speech/{vid}", headers={**_headers(), "accept": "audio/mpeg"},
                      params={"output_format": "mp3_44100_64"},
                      json={"text": text, "model_id": model,
                            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
                      timeout=TIMEOUT)
    r.raise_for_status()
    _cache[h] = r.content
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "wb") as f:
            f.write(r.content)
    except OSError:
        pass
    return r.content


def transcribe(audio_bytes, filename="answer.webm", mimetype="audio/webm"):
    """Shelter's spoken answer -> text, with ElevenLabs Scribe."""
    r = requests.post(f"{API}/speech-to-text", headers=_headers(),
                      data={"model_id": os.getenv("ELEVEN_STT_MODEL", "scribe_v1"), "language_code": "en"},
                      files={"file": (filename, audio_bytes, mimetype)}, timeout=TIMEOUT)
    r.raise_for_status()
    return (r.json().get("text") or "").strip()


# ---------- understanding the answer ----------

_ONES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_NO = r"\b(no|nope|full|can't|cannot|can not|won't|decline|pass|not today|unable|no room|don't have room|don't need|sorry)\b"
_YES = r"\b(yes|yeah|yep|sure|ok|okay|accept|absolutely|definitely|send it|we'll take|we will take|take it all|all of it|sounds good)\b"
_PART = r"\b(only|just|some|part|half|up to|at most|about|more than)\b"


def _numbers(text):
    """All numbers in the text, digits or words ('twenty five' -> 25, 'a dozen' -> 12)."""
    t = text.lower().replace("-", " ")
    out = [int(x) for x in re.findall(r"\b\d+\b", t)]
    words = re.findall(r"[a-z']+", t)
    i = 0
    while i < len(words):
        w = words[i]
        if w in _TENS:
            n = _TENS[w]
            if i + 1 < len(words) and words[i + 1] in _ONES and _ONES[words[i + 1]] < 10:
                n += _ONES[words[i + 1]]
                i += 1
            out.append(n)
        elif w in _ONES and w != "zero":
            out.append(_ONES[w])
        elif w == "dozen":
            out.append(12)
        i += 1
    return out


def parse_answer(text, offered):
    """'Yes we can take it' -> all; 'we can only take 20' -> 20; 'sorry we're full' -> decline; else None."""
    t = (text or "").lower().replace("’", "'")
    if not t.strip():
        return None
    nums = [n for n in _numbers(t) if 0 < n]
    if "half" in t and not nums:
        nums = [offered // 2]
    no = re.search(_NO, t)
    if nums:
        n = nums[0]
        if n >= offered:
            return {"accept": True, "servings": None}
        if re.search(r"\b(can't|cannot|can not|don't|won't)\b", t) and not re.search(_PART, t) and not re.search(_YES, t):
            return {"accept": False, "servings": None}
        return {"accept": True, "servings": n}
    if no and not re.search(_YES, t):
        return {"accept": False, "servings": None}
    if re.search(_YES, t):
        return {"accept": True, "servings": None}
    if no:
        return {"accept": False, "servings": None}
    return None


def ask_text(nonprofit_name, ask):
    """What the dispatcher says to the shelter when it asks."""
    f = ask["food"]
    extra = []
    if f.get("needs_cold"):
        extra.append("it has to stay cold")
    if f.get("allergens"):
        extra.append("it contains " + ", ".join(f["allergens"]))
    return (f"Hi {nonprofit_name}, this is Uplink. {ask['business']} has {f['servings']} servings of "
            f"{', '.join(f['items'])}" + (f", and {' and '.join(extra)}" if extra else "") +
            f". {ask['driver']} can bring it by {ask['arrive']}. Can you take it? "
            "Say yes, no, or how many servings you can take.")
