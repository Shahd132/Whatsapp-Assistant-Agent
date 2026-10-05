"""Whisper may guess any of ~99 languages for a short clip. The dashboard only needs Arabic or English."""


def pick_language(info) -> str:
    """info: faster-whisper's TranscriptionInfo (language, all_language_probs)."""
    if info.language in ("ar", "en"):
        return info.language
    probs = dict(getattr(info, "all_language_probs", None) or [])
    return "en" if probs.get("en", 0) > probs.get("ar", 0) else "ar"
