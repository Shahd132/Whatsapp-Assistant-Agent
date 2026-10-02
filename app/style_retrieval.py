"""Retrieve similar past exchanges, used only to show the model how you really reply.

Small data (thousands of pairs), so a numpy dot product is enough: no FAISS,
no BM25. Missing index or any failure means "no examples", never a crash.
Turn it off for A/B comparisons with STYLE_RETRIEVAL=false in .env.
"""
import json
import os
from pathlib import Path

import numpy as np

INDEX_DIR = Path(__file__).resolve().parent.parent / "data" / "style_index"

_pairs: list[dict] | None = None
_vectors = None
_embedder = None


def model_name() -> str:
    return os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")


def _load() -> bool:
    global _pairs, _vectors, _embedder
    if _pairs is not None:
        return bool(_pairs)
    pairs_file, vectors_file = INDEX_DIR / "pairs.json", INDEX_DIR / "vectors.npy"
    if not (pairs_file.exists() and vectors_file.exists()):
        _pairs = []
        return False
    from sentence_transformers import SentenceTransformer

    _pairs = json.loads(pairs_file.read_text(encoding="utf-8"))
    _vectors = np.load(vectors_file)
    _embedder = SentenceTransformer(model_name())
    return True


def retrieve_examples(text: str, k: int = 5) -> list[dict]:
    if os.getenv("STYLE_RETRIEVAL", "true").lower() != "true" or not text.strip() or not _load():
        return []
    query = _embedder.encode([f"query: {text}"], normalize_embeddings=True)[0]
    best = np.argsort(_vectors @ query)[::-1][:k]
    return [_pairs[i] for i in best]