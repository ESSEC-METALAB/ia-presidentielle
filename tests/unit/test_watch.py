"""The daily watch: candidate leads from an outside list, topic signals, passage state.

Fictional people, parties and texts; the roster is a fake or a mock HTTP transport.
"""

from datetime import date

import httpx
import pytest

from observatoire.adapters.reporting.watch_markdown import WatchMarkdown
from observatoire.adapters.sources.http_client import PoliteHttpClient, robots_fetcher
from observatoire.adapters.sources.mieuxvoter_roster import MieuxVoterRoster
from observatoire.application.watch_changes import WatchChanges
from observatoire.domain.annotation import DimensionAnnotation, SegmentAnnotation
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import (
    Candidacy,
    CandidacyStatus,
    Candidate,
    DocumentSegmentation,
    RawDocument,
    Segment,
)
from observatoire.domain.watch import LeadKind, RosterEntry, WatchedTopic, WatchReport
from observatoire.services.ai_relevance import RelevanceSettings, TermRelevanceFilter
from observatoire.services.dedup import content_hash
from observatoire.services.robots_policy import RobotsPolicy
from support import T0, FrozenClock, InMemoryStore, candidate, document, source

RELEVANCE = TermRelevanceFilter(RelevanceSettings(strong_patterns=(r"\bIA\b",)))
RESEARCH = WatchedTopic(id="recherche", label_fr="Recherche", patterns=(r"\bchercheu",))
CSV_URL = "https://liste.test/candidats.csv"


class FakeRoster:
    label = "Liste fictive"

    def __init__(self, entries: list[RosterEntry] | None = None, *, fails: bool = False) -> None:
        self._entries = entries or []
        self._fails = fails

    def fetch(self) -> list[RosterEntry]:
        if self._fails:
            raise SourceUnavailableError(CSV_URL, "HTTP 503")
        return self._entries


def _withdrawn(cid: str, name: str) -> Candidate:
    return Candidate(
        id=cid,
        name=name,
        party="Parti Témoin",
        candidacy=Candidacy(
            status=CandidacyStatus.WITHDRAWN,
            checked_on=date(2026, 10, 14),
            sources=("https://exemple.test/retrait",),
        ),
    )


def _segmented(store: InMemoryStore, doc: RawDocument, *texts: str) -> list[Segment]:
    segments = [
        Segment(document_hash=doc.content_hash, index=i, text=t, spans=((0, len(t)),))
        for i, t in enumerate(texts)
    ]
    store.save(doc)
    store.replace(
        [
            DocumentSegmentation(
                document_hash=doc.content_hash,
                segmenter_version="s1",
                segments=tuple(segments),
                excluded=(),
            )
        ]
    )
    return segments


def _run(
    store: InMemoryStore,
    roster: FakeRoster,
    people: list[Candidate] | None = None,
    *,
    min_candidates: int = 1,
) -> WatchReport:
    use_case = WatchChanges(
        roster=roster,
        corpus=store,
        segments=store,
        annotations=store,
        relevance=RELEVANCE,
        clock=FrozenClock(),
    )
    return use_case.run(
        people or [candidate()],
        [source()],
        [RESEARCH],
        threshold=2,
        min_candidates=min_candidates,
        since=date(2026, 7, 1),
    )


def test_a_declared_candidate_missing_from_the_roster_is_a_lead_not_an_addition() -> None:
    roster = FakeRoster(
        [
            RosterEntry(name="Dominique Nouvel", party="Parti Neuf", declared_on=date(2026, 9, 1)),
            RosterEntry(name="CAMILLE EXEMPLE", declared_on=date(2026, 5, 1)),
            RosterEntry(name="Alex Rumeur"),  # neither declared nor withdrawn: nothing to say
        ]
    )

    report = _run(InMemoryStore(), roster)

    (lead,) = report.candidate_leads
    assert (lead.kind, lead.name, lead.on) == (
        LeadKind.DECLARED_NOT_LISTED,
        "Dominique Nouvel",
        date(2026, 9, 1),
    )


def test_a_withdrawal_reported_elsewhere_is_a_lead_only_for_someone_still_running() -> None:
    roster = FakeRoster(
        [
            RosterEntry(name="Camille Exemple", withdrawn_on=date(2026, 10, 2)),
            RosterEntry(name="Dominique Témoin", withdrawn_on=date(2026, 10, 2)),
        ]
    )
    people = [candidate(), _withdrawn("dominique-temoin", "Dominique Témoin")]

    report = _run(InMemoryStore(), roster, people)

    assert [(lead.kind, lead.name) for lead in report.candidate_leads] == [
        (LeadKind.WITHDRAWN_BUT_LISTED, "Camille Exemple")
    ]


def test_an_unreadable_outside_list_is_reported_and_the_rest_still_runs() -> None:
    store = InMemoryStore()
    _segmented(store, document("IA et chercheurs."), "Former des chercheurs en IA.")

    report = _run(store, FakeRoster(fails=True))

    assert report.roster_error is not None
    assert "503" in report.roster_error
    assert report.topic_signals[0].passages == 1


def test_a_topic_is_counted_only_in_passages_about_ai() -> None:
    store = InMemoryStore()
    _segmented(
        store,
        document("Texte."),
        "Nous recruterons des chercheurs en IA.",
        "Nous recruterons des chercheurs en biologie.",
    )

    (signal,) = _run(store, FakeRoster()).topic_signals

    assert (signal.passages, signal.candidates) == (1, ("camille-exemple",))
    assert "chercheurs en IA" in signal.examples[0].excerpt


def test_one_long_programme_alone_does_not_make_a_topic_worth_an_axis() -> None:
    store = InMemoryStore()
    _segmented(store, document("Texte."), "Des chercheurs en IA.", "Encore des chercheurs, IA.")

    report = _run(store, FakeRoster(), min_candidates=2)
    note = WatchMarkdown().render(report)

    assert report.topic_signals[0].passages == 2
    assert "à examiner" not in note.split("## Sujets à examiner")[1].split("## Passages")[0]


def _annotate(store: InMemoryStore, passage: Segment, *, with_statement: bool) -> None:
    statements = (
        DimensionAnnotation(
            segment_id=passage.id,
            index=0,
            dimension="regulation",
            quote=passage.text,
            quote_span=(0, len(passage.text)),
            summary_fr="Propose.",
            summary_en="Proposes.",
            context_fr="Texte fictif.",
            context_en="Fictional.",
            gloss_en="A gloss.",
        ),
    )
    store.save_annotation(
        SegmentAnnotation(
            segment_id=passage.id,
            segment_hash=content_hash(passage.text),
            annotator_version="v1",
            annotated_at=T0,
            annotations=statements if with_statement else (),
        )
    )


def test_pending_and_empty_passages_are_counted_against_the_current_annotator() -> None:
    store = InMemoryStore()
    done, empty, _pending = _segmented(
        store, document("Texte."), "Mesure sur l'IA.", "Mention de l'IA.", "Autre IA."
    )
    _annotate(store, done, with_statement=True)
    _annotate(store, empty, with_statement=False)

    report = _run(store, FakeRoster())

    assert (report.ai_passages, report.pending_passages) == (3, 1)
    assert [e.excerpt for e in report.empty_passages] == ["Mention de l'IA."]


def test_the_note_says_nothing_was_changed_and_lists_each_lead() -> None:
    roster = FakeRoster([RosterEntry(name="Dominique Nouvel", declared_on=date(2026, 9, 1))])

    note = WatchMarkdown().render(_run(InMemoryStore(), roster))

    assert "Rien n'a été modifié automatiquement" in note
    assert "**Dominique Nouvel**" in note
    assert "2026-09-01" in note


def test_the_note_says_when_the_outside_list_was_unreadable() -> None:
    note = WatchMarkdown().render(_run(InMemoryStore(), FakeRoster(fails=True)))

    assert "illisible" in note


def test_a_long_list_of_empty_passages_is_shortened_in_the_note() -> None:
    store = InMemoryStore()
    texts = [f"Mention {n} de l'IA." for n in range(17)]
    for passage in _segmented(store, document("Texte."), *texts):
        _annotate(store, passage, with_statement=False)

    note = WatchMarkdown().render(_run(store, FakeRoster()))

    assert "… et 2 autre(s)" in note


def _http(body: str, status: int = 200) -> PoliteHttpClient:
    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == CSV_URL:
            return httpx.Response(status, text=body)
        return httpx.Response(404)

    raw = httpx.Client(transport=httpx.MockTransport(handle))
    return PoliteHttpClient(raw, RobotsPolicy("Test/1.0", 0.0, robots_fetcher(raw)), 3)


def test_the_community_csv_becomes_roster_entries() -> None:
    body = (
        "candidate_id,complete_name,name,surname,parti,annonce_candidature,"
        "retrait_candidature,second_round\n"
        "DN,Dominique Nouvel,Dominique,Nouvel,Parti Neuf,2026-09-01,,\n"
        "CE,Camille Exemple,Camille,Exemple,,2026-05-01,2026-10-02,\n"
        ",,,,,,,\n"
    )

    entries = MieuxVoterRoster(_http(body), CSV_URL, "Liste").fetch()

    assert [(e.name, e.party, e.declared_on, e.withdrawn_on) for e in entries] == [
        ("Dominique Nouvel", "Parti Neuf", date(2026, 9, 1), None),
        ("Camille Exemple", None, date(2026, 5, 1), date(2026, 10, 2)),
    ]


@pytest.mark.parametrize(("body", "status"), [("name,party\nA,B\n", 200), ("", 503)])
def test_an_unexpected_or_unreachable_csv_fails_the_roster(body: str, status: int) -> None:
    roster = MieuxVoterRoster(_http(body, status), CSV_URL, "Liste")

    with pytest.raises(SourceUnavailableError):
        roster.fetch()
    assert roster.label == "Liste"


def test_documents_outside_the_window_or_unconfigured_are_not_watched() -> None:
    store = InMemoryStore()
    _segmented(store, document("Ancien.", published_on=date(2026, 5, 1)), "Des chercheurs en IA.")
    _segmented(store, document("Ailleurs.", source_id="x/rss/y"), "D'autres chercheurs, IA.")

    report = _run(store, FakeRoster())

    assert (report.ai_passages, report.topic_signals[0].passages) == (0, 0)
