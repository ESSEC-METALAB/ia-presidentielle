"""Fakes and builders shared by the tests. Every person and text here is fictional."""

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from observatoire.domain.models import (
    Candidate,
    DocumentSegmentation,
    RawDocument,
    Source,
    SourceOutcome,
    TrustLevel,
)
from observatoire.services.dedup import content_hash

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 10, 4, 6, 0, tzinfo=UTC)


class FrozenClock:
    """Returns `start`, then advances by `step` on every call."""

    def __init__(self, start: datetime = T0, step: timedelta = timedelta(0)) -> None:
        self._now = start
        self._step = step

    def now(self) -> datetime:
        current = self._now
        self._now += self._step
        return current


class InMemoryStore:
    """Every storage port in memory: documents, run outcomes, segmentations."""

    def __init__(self, documents: Iterable[RawDocument] = ()) -> None:
        self.documents = {d.content_hash: d for d in documents}
        self.outcomes: list[SourceOutcome] = []
        self.segmentations: dict[str, DocumentSegmentation] = {}
        self.replace_calls = 0

    def segmented_versions(self) -> dict[str, str]:
        return {h: s.segmenter_version for h, s in self.segmentations.items()}

    def replace(self, segmentations: Sequence[DocumentSegmentation]) -> None:
        self.replace_calls += 1
        self.segmentations.update({s.document_hash: s for s in segmentations})

    def list_segmentations(self) -> list[DocumentSegmentation]:
        return list(self.segmentations.values())

    def exists(self, content_hash: str) -> bool:
        return content_hash in self.documents

    def save(self, document: RawDocument) -> None:
        self.documents.setdefault(document.content_hash, document)

    def list_documents(self) -> list[RawDocument]:
        return list(self.documents.values())

    def record(self, outcome: SourceOutcome) -> None:
        self.outcomes.append(outcome)

    def latest_by_source(self) -> dict[str, SourceOutcome]:
        latest: dict[str, SourceOutcome] = {}
        for outcome in sorted(self.outcomes, key=lambda o: o.started_at):
            latest[outcome.source_id] = outcome
        return latest


def candidate(cid: str = "camille-exemple", name: str = "Camille Exemple") -> Candidate:
    return Candidate(id=cid, name=name, party="Parti Exemple", aliases=(name,))


def source(
    sid: str = "camille-exemple/rss/parti",
    *,
    kind: str = "rss",
    candidate_id: str = "camille-exemple",
    trust_level: TrustLevel = TrustLevel.PARTY,
    options: dict[str, str] | None = None,
) -> Source:
    return Source(
        id=sid,
        candidate_id=candidate_id,
        kind=kind,
        url="https://parti-exemple.test/feed/",
        trust_level=trust_level,
        label="Parti Exemple — fil RSS",
        options=options or {},
    )


def document(
    text: str = "Texte fictif.",
    *,
    source_id: str = "camille-exemple/rss/parti",
    candidate_id: str = "camille-exemple",
    published_on: date | None = date(2026, 9, 15),
    fetched_at: datetime = T0,
    trust_level: TrustLevel = TrustLevel.PARTY,
) -> RawDocument:
    return RawDocument(
        source_id=source_id,
        candidate_id=candidate_id,
        url=f"https://parti-exemple.test/{content_hash(text)[:8]}",
        title="Titre fictif",
        text=text,
        published_on=published_on,
        fetched_at=fetched_at,
        trust_level=trust_level,
        content_hash=content_hash(text),
    )


def minimal_pdf(text: str) -> bytes:
    """A valid one-page PDF whose text layer is `text` (ASCII only)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body, offsets = b"%PDF-1.4\n", []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + content + b"\nendobj\n"
    xref_at = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return body
