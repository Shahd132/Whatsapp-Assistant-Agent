"""Image captioning with BLIP."""
import base64
import io

from PIL import Image
from transformers import BlipForConditionalGeneration, BlipProcessor

_processor: BlipProcessor | None = None
_model: BlipForConditionalGeneration | None = None


def _load():
    global _processor, _model
    if _model is None:
        _processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        _model = BlipForConditionalGeneration.from_pretrained(
            "Salesforce/blip-image-captioning-base"
        )


def caption_base64_image(media_base64: str) -> str:
    _load()
    image = Image.open(io.BytesIO(base64.b64decode(media_base64))).convert("RGB")
    inputs = _processor(image, return_tensors="pt")
    out = _model.generate(**inputs, max_new_tokens=30)
    return _processor.decode(out[0], skip_special_tokens=True)