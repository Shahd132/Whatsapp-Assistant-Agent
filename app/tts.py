import base64
import tempfile

import edge_tts

DEFAULT_VOICE = "en-US-AriaNeural"


async def synthesize_to_base64(text: str, voice: str = DEFAULT_VOICE) -> str:
    with tempfile.NamedTemporaryFile(suffix=".ogg") as f:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(f.name)
        f.seek(0)
        return base64.b64encode(f.read()).decode("utf-8")