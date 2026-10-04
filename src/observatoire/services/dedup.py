"""Text normalisation and SHA-256 content hash, the deduplication key (CLAUDE.md §4)."""

import hashlib
import unicodedata


def normalize_text(text: str) -> str:
    """Unicode NFKC and collapsed whitespace: layout changes do not make a text new."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
