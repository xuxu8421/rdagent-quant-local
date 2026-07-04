from __future__ import annotations

import hashlib
import math
import re


def local_embedding(text: str, dimensions: int = 512) -> list[float]:
    """Deterministic lexical embedding for code and factor-description retrieval."""
    vector = [0.0] * dimensions
    normalized = text.lower()
    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalized)
    features = tokens + [normalized[idx : idx + 3] for idx in range(max(0, len(normalized) - 2))]
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        index = value % dimensions
        vector[index] += -1.0 if value & (1 << 63) else 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector

