"""Speech-to-text using faster-whisper. Runs locally, no API key needed."""
import base64
import os
import tempfile

from faster_whisper import WhisperModel

_models: dict[str, WhisperModel] = {}


def _get_model(size: str | None = None) -> WhisperModel:
    """One cached model per size, so WhatsApp voice notes can use 'small' while
    the dashboard uses a bigger one (DASHBOARD_WHISPER_SIZE=medium)."""
    size = size or os.getenv("WHISPER_MODEL_SIZE", "small")
    if size not in _models:
        _models[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _models[size]


def transcribe_bytes(audio: bytes, language: str = "ar", model_size: str | None = None, vad: bool = False) -> str:
    # delete=False + close before use: Windows can't reopen a temp file
    # that is still open in this process. The suffix doesn't matter: ffmpeg
    # (via PyAV) detects the real format from the content, so webm/mp4/ogg all work.
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as f:
        f.write(audio)
        path = f.name

    try:
        segments, _ = _get_model(model_size).transcribe(path, language=language, vad_filter=vad)
        return " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def transcribe_base64_audio(media_base64: str) -> str:
    return transcribe_bytes(base64.b64decode(media_base64), language="ar")
