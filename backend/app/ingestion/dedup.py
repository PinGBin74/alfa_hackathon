import hashlib
import re


def normalize(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def dedup_hash(title: str, body: str = "") -> str:
    """Точные дубликаты. TODO: нечёткие (MinHash/эмбеддинги) для перепечаток."""
    return hashlib.sha256(normalize(title).encode()).hexdigest()
