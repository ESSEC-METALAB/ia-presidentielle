"""Light, deterministic segmentation: documents -> passages that can be read on their own.

No model is involved. The rules run in this order, and every exclusion is recorded
with its reason, never dropped silently:

1. Lines that are page furniture rather than text: page and section numbers, short
   lines repeated within a document (running headers) or across a source's documents
   (signatures, labels), lines
   opening with configured interface phrases (consent banners), and everything after
   a "related articles" marker.
2. Stage directions of a parliamentary record, "(Applaudissements…)": the
   stenographers' words, not the speaker's.
3. What remains becomes paragraphs: one per line, or, for wrapped layouts (PDF), one
   per block between blank lines. A short line is merged into the next line of the
   same block (headings, labels); blank lines are never crossed.
4. Paragraphs longer than `max_chars` are cut between sentences, never inside one.
5. Passages still shorter than `min_chars` are excluded as too short ("Bravo !").

A segment's text is the document's text over its spans with whitespace collapsed,
so each segment points at its exact source passage.
"""

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, model_validator

from observatoire.domain.models import (
    DocumentSegmentation,
    ExcludedPassage,
    ExclusionReason,
    RawDocument,
    Segment,
    Source,
    Span,
)

# Bump when the rules below change: every document is then segmented again.
_REVISION = 4

# Up to three digits: a year alone on a wrapped line ("2030") is text, not a page number.
_PAGE_NUMBER = re.compile(r"^\d{1,3}$")
_LETTER = re.compile(r"[^\W\d_]")
_TERMINAL = re.compile(r"[.!?…]$")
_SENTENCE_END = re.compile(r"[.!?…]+$")
# Closing and opening punctuation around a sentence boundary (guillemets, quotes, brackets).
_CLOSERS = '\u00bb"\u201d\u2019)]'
_OPENERS = '\u00ab"\u201c([\u00bf\u00a1'
_INITIALS = re.compile(r"^(?:[A-ZÀ-Ý]\.-?)+$")


class SegmentationSettings(BaseModel):
    """config/segmentation.yaml. Its fingerprint is part of the segmenter version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_chars: int = Field(ge=1)
    max_chars: int = Field(ge=1)
    wrapped_kinds: tuple[str, ...] = ()
    repeated_line_max_chars: int = Field(ge=1)
    repeated_in_document_min: int = Field(ge=2)
    repeated_in_document_min_words: int = Field(ge=1)
    repeated_in_source_min_documents: int = Field(ge=2)
    section_cut_markers: tuple[str, ...] = ()
    interface_line_prefixes: tuple[str, ...] = ()
    stage_direction_patterns: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    abbreviations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "SegmentationSettings":
        if self.max_chars < self.min_chars:
            raise ValueError("max_chars must be at least min_chars")
        for patterns in self.stage_direction_patterns.values():
            for pattern in patterns:
                re.compile(pattern)
        return self

    @property
    def fingerprint(self) -> str:
        payload = f"{_REVISION}:{self.model_dump_json()}".encode()
        return hashlib.sha256(payload).hexdigest()[:12]


@dataclass(frozen=True)
class _Word:
    start: int
    end: int
    range_index: int  # words of one kept range share a span


@dataclass
class _Paragraph:
    block: int
    words: list[_Word] = field(default_factory=list)

    def length(self, text: str) -> int:
        return len(" ".join(text[w.start : w.end] for w in self.words))


@dataclass
class _Line:
    span: Span
    block: int
    kept: list[Span] = field(default_factory=list)


class ParagraphSegmenter:
    def __init__(self, settings: SegmentationSettings) -> None:
        self._settings = settings
        self._version = f"r{_REVISION}-{settings.fingerprint}"
        self._markers = {_key(marker) for marker in settings.section_cut_markers}
        self._prefixes = tuple(prefix.casefold() for prefix in settings.interface_line_prefixes)
        self._directions = {
            kind: [re.compile(pattern) for pattern in patterns]
            for kind, patterns in settings.stage_direction_patterns.items()
        }
        self._abbreviations = {a.casefold() for a in settings.abbreviations}

    @property
    def version(self) -> str:
        return self._version

    def segment(
        self, source: Source, documents: Sequence[RawDocument]
    ) -> list[DocumentSegmentation]:
        repeated = self._repeated_in_source(documents)
        return [self._segment_document(source, document, repeated) for document in documents]

    # --- 1. page furniture --------------------------------------------------------------

    def _repeated_in_source(self, documents: Sequence[RawDocument]) -> set[str]:
        counts: Counter[str] = Counter()
        for document in documents:
            counts.update(set(self._furniture_keys(document.text, min_words=1)))
        threshold = self._settings.repeated_in_source_min_documents
        return {key for key, count in counts.items() if count >= threshold}

    def _furniture_keys(self, text: str, *, min_words: int) -> Iterator[str]:
        """Lines that could be furniture: short, unpunctuated, made of words.

        `min_words` keeps sentence fragments out: a wrapped PDF leaves "la" or "de" alone
        on a line many times over, and those are text, not a header.
        """
        for span in filter(None, _line_spans(text)):
            line = text[span[0] : span[1]]
            words = sum(1 for word in line.split() if _LETTER.search(word))
            short = len(line) <= self._settings.repeated_line_max_chars
            if short and words >= min_words and not _TERMINAL.search(line):
                yield _key(line)

    def _keep_lines(
        self, text: str, repeated: set[str], excluded: list[ExcludedPassage]
    ) -> list[_Line]:
        min_words = self._settings.repeated_in_document_min_words
        in_document = Counter(self._furniture_keys(text, min_words=min_words))
        lines: list[_Line] = []
        block = 0
        spans = _line_spans(text)
        for position, span in enumerate(spans):
            if span is None:
                block += 1
                continue
            if _key(text[span[0] : span[1]]) in self._markers:
                last = max(s[1] for s in spans[position:] if s is not None)
                excluded.append(
                    ExcludedPassage(span=(span[0], last), reason=ExclusionReason.RELATED_LINKS)
                )
                break
            reason = self._line_reason(text[span[0] : span[1]], in_document, repeated)
            if reason is None:
                lines.append(_Line(span=span, block=block, kept=[span]))
            else:
                excluded.append(ExcludedPassage(span=span, reason=reason))
        return lines

    def _line_reason(
        self, line: str, in_document: Counter[str], repeated: set[str]
    ) -> ExclusionReason | None:
        key = _key(line)
        if _PAGE_NUMBER.match(line):
            return ExclusionReason.PAGE_NUMBER
        if key.startswith(self._prefixes):
            return ExclusionReason.INTERFACE_TEXT
        if in_document[key] >= self._settings.repeated_in_document_min:
            return ExclusionReason.REPEATED_IN_DOCUMENT
        if key in repeated:
            return ExclusionReason.REPEATED_IN_SOURCE
        return None

    # --- 2. stage directions ------------------------------------------------------------

    def _remove_stage_directions(
        self, kind: str, text: str, lines: list[_Line], excluded: list[ExcludedPassage]
    ) -> None:
        patterns = self._directions.get(kind, [])
        for line in lines if patterns else []:
            start, end = line.span
            found = _union(
                m.span()  # already absolute: finditer's pos/endpos do not re-base offsets
                for pattern in patterns
                for m in pattern.finditer(text, start, end)
            )
            line.kept = _subtract(line.span, found)
            excluded.extend(
                ExcludedPassage(span=s, reason=ExclusionReason.STAGE_DIRECTION) for s in found
            )

    # --- 3. paragraphs ------------------------------------------------------------------

    def _paragraphs(self, kind: str, text: str, lines: list[_Line]) -> list[_Paragraph]:
        wrapped = kind in self._settings.wrapped_kinds
        paragraphs: list[_Paragraph] = []
        range_index = 0
        for line in lines:
            if not paragraphs or not wrapped or not _continues(text, paragraphs[-1], line):
                paragraphs.append(_Paragraph(block=line.block))
            paragraphs[-1].block = line.block
            for start, end in line.kept:
                paragraphs[-1].words.extend(_words(text, (start, end), range_index))
                range_index += 1
        merged = paragraphs if wrapped else self._merge_short(text, paragraphs)
        return [p for p in merged if p.words]

    def _merge_short(self, text: str, paragraphs: list[_Paragraph]) -> list[_Paragraph]:
        """A short line joins the next line of its block: headings, labels, list items."""
        result: list[_Paragraph] = []
        pending: _Paragraph | None = None  # a short line waiting for the next one
        for paragraph in paragraphs:
            if pending is not None:
                joined = _Paragraph(block=paragraph.block, words=pending.words + paragraph.words)
                same_block = pending.block == paragraph.block
                if same_block and joined.length(text) <= self._settings.max_chars:
                    paragraph = joined
                else:
                    result.append(pending)
            pending = paragraph if paragraph.length(text) < self._settings.min_chars else None
            if pending is None:
                result.append(paragraph)
        if pending is not None:
            result.append(pending)
        return result

    # --- 4 and 5. size ------------------------------------------------------------------

    def _chunks(self, text: str, paragraph: _Paragraph) -> list[list[_Word]]:
        if paragraph.length(text) <= self._settings.max_chars:
            return [paragraph.words]
        chunks: list[list[_Word]] = [[]]
        for sentence in self._sentences(text, paragraph.words):
            candidate = chunks[-1] + sentence
            if chunks[-1] and _length(text, candidate) > self._settings.max_chars:
                chunks.append(list(sentence))
            else:
                chunks[-1] = candidate
        return chunks

    def _sentences(self, text: str, words: list[_Word]) -> Iterator[list[_Word]]:
        current: list[_Word] = []
        for word, following in zip(words, [*words[1:], None], strict=True):
            current.append(word)
            if following is None or self._ends_sentence(text, word, following):
                yield current
                current = []

    def _ends_sentence(self, text: str, word: _Word, following: _Word) -> bool:
        core = text[word.start : word.end].rstrip(_CLOSERS)
        if not _SENTENCE_END.search(core) or core.casefold() in self._abbreviations:
            return False
        if _INITIALS.match(core):
            return False
        opener = text[following.start : following.end].lstrip(_OPENERS)
        return bool(opener) and (opener[0].isupper() or opener[0].isdigit())

    def _segment_document(
        self, source: Source, document: RawDocument, repeated: set[str]
    ) -> DocumentSegmentation:
        text = document.text
        excluded: list[ExcludedPassage] = []
        lines = self._keep_lines(text, repeated, excluded)
        self._remove_stage_directions(source.kind, text, lines, excluded)
        segments: list[Segment] = []
        for paragraph in self._paragraphs(source.kind, text, lines):
            for words in self._chunks(text, paragraph):
                if _length(text, words) < self._settings.min_chars:
                    excluded.extend(
                        ExcludedPassage(span=s, reason=ExclusionReason.TOO_SHORT)
                        for s in _spans(words)
                    )
                    continue
                segments.append(_segment(document, len(segments), text, words))
        return DocumentSegmentation(
            document_hash=document.content_hash,
            segmenter_version=self._version,
            segments=tuple(segments),
            excluded=tuple(sorted(excluded, key=lambda passage: passage.span)),
        )


def _continues(text: str, paragraph: _Paragraph, line: _Line) -> bool:
    """Wrapped layouts: the same block, or a sentence carried over a page break."""
    if paragraph.block == line.block:
        return True
    if not paragraph.words or not line.kept:
        return False
    last = paragraph.words[-1]
    first = text[line.kept[0][0] : line.kept[0][1]].lstrip(_OPENERS)
    unfinished = not _TERMINAL.search(text[last.start : last.end].rstrip(_CLOSERS))
    return unfinished and bool(first) and first[0].islower()


def _key(line: str) -> str:
    return " ".join(line.split()).casefold()


def _line_spans(text: str) -> list[Span | None]:
    """One entry per line: its span without surrounding whitespace, or None if blank."""
    spans: list[Span | None] = []
    offset = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            start = offset + len(line) - len(line.lstrip())
            spans.append((start, start + len(stripped)))
        else:
            spans.append(None)
        offset += len(line) + 1
    return spans


def _union(spans: Iterable[Span]) -> list[Span]:
    """Overlapping matches of several patterns become one passage."""
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract(span: Span, holes: list[Span]) -> list[Span]:
    kept, cursor = [], span[0]
    for start, end in holes:
        if start > cursor:
            kept.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < span[1]:
        kept.append((cursor, span[1]))
    return kept


def _words(text: str, span: Span, range_index: int) -> list[_Word]:
    start = span[0]
    return [
        _Word(start + m.start(), start + m.end(), range_index)
        for m in re.finditer(r"\S+", text[span[0] : span[1]])
    ]


def _length(text: str, words: list[_Word]) -> int:
    return sum(w.end - w.start for w in words) + max(len(words) - 1, 0)


def _spans(words: list[_Word]) -> tuple[Span, ...]:
    spans: list[Span] = []
    for index, word in enumerate(words):
        if index and words[index - 1].range_index == word.range_index:
            spans[-1] = (spans[-1][0], word.end)
        else:
            spans.append((word.start, word.end))
    return tuple(spans)


def _segment(document: RawDocument, index: int, text: str, words: list[_Word]) -> Segment:
    return Segment(
        document_hash=document.content_hash,
        index=index,
        text=" ".join(text[w.start : w.end] for w in words),
        spans=_spans(words),
    )
