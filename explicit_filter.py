import json
import os
from pathlib import Path

_NORMALIZE = {"1": "i", "0": "o", "4": "a", "3": "e", "@": "a", "$": "s"}

_CONFIG_FILE = Path(__file__).parent / "ban_words.json"

def _load_config():
    try:
        data = json.loads(_CONFIG_FILE.read_text())
        return data
    except Exception:
        return {"enabled": True, "words": {}}

def normalize_text(text):
    result = text.lower()
    for digit, letter in _NORMALIZE.items():
        result = result.replace(digit, letter)
    return result

def check_explicit(transcript):
    config = _load_config()
    if not config.get("enabled", True):
        return False, "", "", ""
    explicit_terms = config.get("words", [])
    if not transcript or not transcript.strip():
        return False, "", "", ""
    normalized = normalize_text(transcript)
    words = normalized.split()
    for i, word in enumerate(words):
        clean_word = "".join(c for c in word if c.isalpha())
        if clean_word in explicit_terms:
            category = "banned word"
            position_pct = i / max(len(words), 1)
            timestamp_hint = "~" + str(int(position_pct * 100)) + "% through video"
            return True, clean_word, category, timestamp_hint
    return False, "", "", ""

