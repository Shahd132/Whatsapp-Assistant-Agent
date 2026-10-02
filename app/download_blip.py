import os

os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "120"

from transformers import BlipForConditionalGeneration, BlipProcessor

name = "Salesforce/blip-image-captioning-base"
print("Downloading processor...")
BlipProcessor.from_pretrained(name)
print("Downloading model (about 1 GB, this can take a while)...")
BlipForConditionalGeneration.from_pretrained(name)
print("DONE - the model is saved on your computer")