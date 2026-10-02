"""Speech-to-text using faster-whisper. Runs locally, no API key needed."""
import base64
import os
import tempfile

from faster_whisper import WhisperModel

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        size = os.getenv("WHISPER_MODEL_SIZE", "small")
        _model = WhisperModel(size, device="cpu", compute_type="int8")
    return _model


# def transcribe_base64_audio(media_base64: str) -> str:
#     audio_bytes = base64.b64decode(media_base64)
#     with tempfile.NamedTemporaryFile(suffix=".ogg") as f:
#         f.write(audio_bytes)
#         f.flush()
#         segments, _ = _get_model().transcribe(f.name, language="ar")
#         return " ".join(seg.text.strip() for seg in segments)

def transcribe_base64_audio(media_base64: str) -> str:
    audio_bytes = base64.b64decode(media_base64)

    # delete=False + close before use: Windows can't reopen a temp file
    # that is still open in this process
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(audio_bytes)
        path = f.name

    try:
        segments, _ = _get_model().transcribe(path, language="ar")
        return " ".join(seg.text.strip() for seg in segments)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass