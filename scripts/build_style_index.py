"""Build the style index from WhatsApp exports in raw_exports/*.txt.

Run from the project root:
    python -m scripts.build_style_index

Needs EXPORT_OWNER_NAME in .env: your name exactly as it appears in the exports.
Everything stays on this machine: a local embedding model, and files in
data/style_index/ (keep that folder and raw_exports/ out of git).
"""
import json
import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from sentence_transformers import SentenceTransformer  # noqa: E402

from app.export_parser import build_pairs, parse_messages  # noqa: E402
from app.style_retrieval import INDEX_DIR, model_name  # noqa: E402

owner = os.getenv("EXPORT_OWNER_NAME", "").strip()
if not owner:
    raise SystemExit("Set EXPORT_OWNER_NAME in .env to your name as it appears in the exports.")

root = Path(__file__).resolve().parent.parent
pairs: dict[tuple, dict] = {}
for path in sorted((root / "raw_exports").glob("*.txt")):
    found = build_pairs(parse_messages(path.read_text(encoding="utf-8")), owner)
    print(f"{path.name}: {len(found)} pairs")
    for p in found:
        pairs[(p["incoming"], p["reply"])] = p

if not pairs:
    raise SystemExit("No pairs found. Check EXPORT_OWNER_NAME and the export format.")

items = list(pairs.values())
model = SentenceTransformer(model_name())
vectors = model.encode([f"passage: {p['incoming']}" for p in items], normalize_embeddings=True, show_progress_bar=True)

INDEX_DIR.mkdir(parents=True, exist_ok=True)
np.save(INDEX_DIR / "vectors.npy", np.asarray(vectors, dtype="float32"))
(INDEX_DIR / "pairs.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
print(f"Saved {len(items)} pairs to {INDEX_DIR}")