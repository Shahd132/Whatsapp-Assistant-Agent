"""Text-to-speech with edge-tts (free, no API key, needs internet).

edge_tts is imported lazily so the rest of the app (and the tests) don't need it.
"""
import asyncio
import base64
import os
import re
import tempfile

from app.log import log_event

DEFAULT_VOICE = "en-US-AriaNeural"
MAX_SPEECH_CHARS = 500   # keeps a spoken reply short and fast to generate

EGYPTIAN_STYLE = ("Speak in a natural, casual Egyptian Arabic accent (Cairo), like a friendly young woman chatting "
                  "with a close friend. Relaxed, warm, conversational pace. If the text is English, speak clear natural English.")
_ARABIC = re.compile(r"[\u0600-\u06FF]")
_LATIN = re.compile(r"[A-Za-z]")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]")


def pick_voice(text: str) -> str:
    """Egyptian Arabic voice when the text is mostly Arabic letters, English otherwise.
    Override with DASHBOARD_VOICE_AR / DASHBOARD_VOICE_EN (e.g. ar-EG-ShakirNeural for a male voice)."""
    arabic = os.getenv("DASHBOARD_VOICE_AR", "ar-EG-SalmaNeural")
    english = os.getenv("DASHBOARD_VOICE_EN", DEFAULT_VOICE)
    return arabic if len(_ARABIC.findall(text)) > len(_LATIN.findall(text)) else english


def clean_for_speech(text: str) -> str:
    """Drop emoji and markdown symbols the voice would read out, and cap the length."""
    text = _EMOJI.sub(" ", text).replace("\u0640", "")   # tatweel (ـ) is only for looks
    text = re.sub(r"[*_`#>~|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_SPEECH_CHARS:
        cut = text[:MAX_SPEECH_CHARS]
        text = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return text


def _openai_speech(text: str) -> bytes:
    from app.llm import _get_client   # lazy: same OpenAI key as the chat model

    resp = _get_client().audio.speech.create(
        model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        voice=os.getenv("OPENAI_TTS_VOICE", "coral"),
        input=text,
        instructions=os.getenv("OPENAI_TTS_STYLE", EGYPTIAN_STYLE),
        response_format="mp3",
    )
    return resp.content


def provider() -> str:
    return os.getenv("TTS_PROVIDER", "edge").strip().lower()


async def synthesize_bytes(text: str, voice: str | None = None) -> bytes:
    """MP3 bytes for the dashboard player. TTS_PROVIDER=openai uses an instructable
    voice (Egyptian accent); if it fails the free edge voice is used instead."""
    import edge_tts

    text = clean_for_speech(text)
    if not text:
        raise ValueError("nothing to say")
    if provider() == "openai":
        try:
            return await asyncio.to_thread(_openai_speech, text)
        except Exception as err:   # no key, quota, or an old openai package: fall back
            log_event("openai_tts_failed", level="warning", error=type(err).__name__)
    chunks = []
    async for chunk in edge_tts.Communicate(text, voice or pick_voice(text)).stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    audio = b"".join(chunks)
    if not audio:
        raise RuntimeError("no audio returned")
    return audio


async def synthesize_to_base64(text: str, voice: str = DEFAULT_VOICE) -> str:
    """For WhatsApp voice replies (REPLY_WITH_VOICE). delete=False + close before
    use: Windows can't reopen a temp file that is still open in this process."""
    import edge_tts

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        path = f.name
    try:
        await edge_tts.Communicate(text, voice).save(path)
        with open(path, "rb") as audio:
            return base64.b64encode(audio.read()).decode("utf-8")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
