"""The gold set decides which model runs in production.

Spec §6c: a costlier model is adopted only where it wins measurably, and the
cheap tier is the incumbent. This scores the three criteria a machine can
check and refuses to pretend about the fourth.

    quote fidelity      does ``quote_fr`` appear verbatim in the source?
    axis agreement      does the model file a position under the axis a human did?
    empty discipline    does it return ``[]`` for a document with no AI position?
    contexte accuracy   NOT SCORED HERE — no lint protects this field, and a
                        machine cannot tell a true context note from a fluent
                        one. ``--show-contexte`` prints them for a human.

Empty discipline is the one to read first. Every other number rewards finding
things; only this one catches a model that invents a position because it was
asked to find one, and that is the failure this publication cannot survive.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .lint import check_quote_in_source
from .schema import Claim, Document, ExtractionResult, Status, Tier


def _norm(text: str) -> str:
    """Compare quotes the way a reader would, not the way bytes do.

    Typographic apostrophes, non-breaking spaces and accents composed two
    different ways are not disagreements about what was said.
    """
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.replace("’", "'").replace("ʼ", "'")
    return re.sub(r"\s+", " ", text).strip()


def same_quote(gold: str, predicted: str) -> bool:
    """Either span containing the other counts as the same passage.

    A model may select a longer or shorter run of words around the sentence a
    human marked. That is a different selection, not a different claim, and
    scoring it as a miss would punish models for a judgement call the schema
    does not constrain.
    """
    g, p = _norm(gold), _norm(predicted)
    return bool(g) and bool(p) and (g in p or p in g)


@dataclass
class Scorecard:
    model: str
    documents: int = 0
    # empty-array discipline
    expected_empty: int = 0
    stayed_empty: int = 0
    invented: list[str] = field(default_factory=list)
    # quote fidelity
    quotes: int = 0
    quotes_verbatim: int = 0
    # axis agreement
    gold_claims: int = 0
    found: int = 0
    axis_agreed: int = 0
    failures: list[str] = field(default_factory=list)
    # Collected, never scored. A machine cannot tell a true context note from
    # a fluent one, so the only honest thing to do is put it in front of a
    # human.
    contextes: list[str] = field(default_factory=list)

    @property
    def empty_discipline(self) -> float | None:
        return self.stayed_empty / self.expected_empty if self.expected_empty else None

    @property
    def quote_fidelity(self) -> float | None:
        return self.quotes_verbatim / self.quotes if self.quotes else None

    @property
    def recall(self) -> float | None:
        return self.found / self.gold_claims if self.gold_claims else None

    @property
    def axis_agreement(self) -> float | None:
        return self.axis_agreed / self.found if self.found else None

    def row(self) -> str:
        def pct(v: float | None) -> str:
            return "  n/a" if v is None else f"{v:5.0%}"
        return (f"{self.model:22}{pct(self.empty_discipline)}   {pct(self.quote_fidelity)}   "
                f"{pct(self.axis_agreement)}   {pct(self.recall)}   "
                f"{len(self.invented):>3}   {len(self.failures):>3}")


HEADER = (f"{'model':22}{'empty':>5}   {'quote':>5}   {'axis':>5}   {'recall':>5}   "
          f"{'inv':>3}   {'err':>3}")


def score(model: str, gold: list[dict], documents: dict[str, Document],
          predict) -> Scorecard:
    """Run ``predict`` over the gold documents and score what comes back.

    ``predict(document) -> dict | None``. ``None`` means the model returned
    something unusable, which is counted as an error rather than as an empty
    extraction — ``[]`` is the right answer for most documents, so folding a
    failure into one would flatter the model.
    """
    card = Scorecard(model=model)
    for entry in gold:
        doc = documents.get(entry["url_hash"])
        if doc is None:
            card.failures.append(f"{entry['url_hash']}: no such document in the corpus")
            continue
        card.documents += 1
        expected = entry.get("claims", [])
        card.gold_claims += len(expected)
        # Counted before the model is asked, so a document it fails on stays
        # in the denominator. Otherwise a model that errored on everything
        # except the documents it answered [] on would score 100% discipline.
        if not expected:
            card.expected_empty += 1

        raw = predict(doc)
        if raw is None:
            card.failures.append(f"{doc.url}: unusable answer")
            continue
        try:
            got = ExtractionResult.model_validate(raw).claims
        except Exception as e:
            card.failures.append(f"{doc.url}: {type(e).__name__}")
            continue

        if not expected:
            if got:
                # The failure that matters: a position asserted where a human
                # found none. Recorded in full so it can be read, not counted.
                card.invented.extend(f"{doc.url}: {c.quote_fr[:120]}" for c in got)
            else:
                card.stayed_empty += 1

        for c in got:
            card.quotes += 1
            card.contextes.append(f"{doc.url}\n    {c.quote_fr[:100]}\n    → {c.contexte_fr}")
            try:
                probe = Claim(**c.model_dump(), person=doc.person, party="",
                              tier=Tier(doc.tier), source_url=doc.url,
                              last_verified=doc.date or _today(), status=Status.PENDING)
            except Exception as e:
                # Provenance is attached here exactly as production attaches
                # it, so a claim that cannot survive that is a real failure.
                card.failures.append(f"{doc.url}: {type(e).__name__} building the claim")
                continue
            if not check_quote_in_source(probe, doc.text):
                card.quotes_verbatim += 1

        for want in expected:
            hit = next((c for c in got if same_quote(want["quote_fr"], c.quote_fr)), None)
            if hit is None:
                continue
            card.found += 1
            if str(hit.axis) == want["axis"]:
                card.axis_agreed += 1
    return card


def _today():
    from datetime import date
    return date.today()


def load(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["documents"]


if __name__ == "__main__":
    import argparse

    from .clients import OpenAISyncClient
    from .extract import MODEL, chunk
    from .prompt import system_prompt, user_prompt
    from .schema import llm_json_schema
    from .store import Store

    ap = argparse.ArgumentParser(description="Score models against the gold set.")
    ap.add_argument("--gold", default="gold/claims.json")
    ap.add_argument("--db", default="data/observatoire.db")
    ap.add_argument("--model", action="append", default=None,
                    help="repeatable; defaults to the incumbent, which a costlier "
                         "model has to beat measurably (spec §6c)")
    ap.add_argument("--show-contexte", action="store_true",
                    help="print every contexte for the human check no lint can do")
    args = ap.parse_args()

    gold = load(args.gold)
    store = Store(args.db)
    documents = {d.url_hash: d for d in store.documents()}
    store.close()
    client = OpenAISyncClient()

    def predictor(model: str):
        """Bound explicitly rather than closed over the loop variable."""
        def predict(doc: Document) -> dict | None:
            # Gold documents are single-chunk by construction, so this is the
            # production request for the whole document, not a sample of it.
            parts = chunk(doc.text)
            return client.complete({
                "custom_id": doc.url_hash, "model": model,
                "system": system_prompt(),
                "user": user_prompt(doc.person, doc.title or "", parts[0] if parts else doc.text),
                "schema": llm_json_schema(),
            })
        return predict

    print(HEADER)
    print("-" * len(HEADER))
    cards = []
    for model in (args.model or [MODEL]):
        card = score(model, gold, documents, predictor(model))
        cards.append(card)
        print(card.row())

    for card in cards:
        if card.invented:
            print(f"\n{card.model} asserted a position where a human found none:")
            for line in card.invented:
                print(f"  {line}")
        if card.failures:
            print(f"\n{card.model} errors:")
            for line in card.failures:
                print(f"  {line}")

    print("\ncontexte is not scored above: no lint protects it, and a machine "
          "cannot tell a true note from a fluent one.")
    if args.show_contexte:
        for card in cards:
            print(f"\n--- {card.model}: check these by hand ---")
            for line in card.contextes:
                print(f"  {line}")
    else:
        print("Pass --show-contexte to print them for the human check.")
