import hashlib
import math
import re


TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def embed_text(text: str, dim: int = 384) -> list[float]:
    value = (text or "").strip()
    if not value:
        return []

    vector = [0.0] * dim
    for token in TOKEN_RE.findall(value.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        idx = int(digest, 16) % dim
        vector[idx] += 1.0

    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]
