"""Embed every library passage. Run this after build_library.py, since the two files must match."""
import json

import numpy
import torch

from library import EMBEDDINGS, LIBRARY, Embedder

passages = [json.loads(line) for line in open(LIBRARY, encoding="utf-8") if line.strip()]
embedder = Embedder("cuda" if torch.cuda.is_available() else "cpu")
chunks = []
for start in range(0, len(passages), 64):
    batch = passages[start : start + 64]
    chunks.append(embedder.encode([f"{p['title']}. {p['section']}. {p['text']}" for p in batch]))
vectors = numpy.concatenate(chunks)
numpy.save(EMBEDDINGS, vectors)
print(f"{vectors.shape[0]} passages, {vectors.shape[1]} dimensions, {EMBEDDINGS.stat().st_size / 1e6:.1f} MB")
