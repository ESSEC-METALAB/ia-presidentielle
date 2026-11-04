"""Text normalisation and SHA-256 content hash, the deduplication key (CLAUDE.md §4).

The hash catches exact copies. `text_similarity` catches the same text extracted twice
with small differences (a PDF read by another library, a page re-read with one more
space), which the hash sees as new.
"""

import hashlib
import re
import unicodedata

_WORD = re.compile(r"\w+")
_SHINGLE_WORDS = 5


def normalize_text(text: str) -> str:
    """Unicode NFKC and collapsed whitespace: layout changes do not make a text new."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def text_similarity(first: str, second: str) -> float:
    """Jaccard index of the two texts' five-word shingles, case and punctuation aside.

    1.0 for the same words in the same order; a rewritten page scores far lower than
    the same page extracted twice.
    """
    left, right = _shingles(first), _shingles(second)
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = _WORD.findall(unicodedata.normalize("NFKC", text).casefold())
    if len(words) < _SHINGLE_WORDS:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + _SHINGLE_WORDS]) for i in range(len(words) - _SHINGLE_WORDS + 1)}
