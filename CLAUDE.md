# Working on this project

Read [`README.md`](README.md) for what it is, and
[`docs/superpowers/specs/2026-09-17-essec-ia-2027-design.md`](docs/superpowers/specs/2026-09-17-essec-ia-2027-design.md)
for why. This file lists the things that look like bugs but are not, and the
things that look safe to change but are not.

This is a **publication under a named institution's byline**, during a French
election. Credibility is the product. Most rules below trade convenience for
defensibility on purpose.

---

## Invariants — do not "fix" these

**`quote_fr` is never edited, translated, tidied or censored.**
The neutrality lint (`lint.check_no_evaluative_language`) checks
`position_*` and `contexte_*` and **deliberately skips the quote**. If a
candidate calls his own plan *ambitieux*, that is his word and it is evidence.
Applying the filter "everywhere" would corrupt the record.
`tests/test_lint.py::test_the_candidates_own_judgement_words_are_never_censored`
pins this.

**An empty extraction is a correct extraction.**
`ExtractionResult.claims == []` is the expected answer for most documents and is
the primary control against invented positions. Do not add retries, coaxing, or
a "try harder" second pass when a document yields nothing.

**The model never reports provenance.**
`person`, `tier`, `source_url`, `archive_url` are attached by `extract.to_claims`
from the fetch context. `ExtractedClaim` uses `extra="forbid"` precisely so a
model cannot inject them. Never widen that.

**Tier from a source is a conservative DEFAULT, not a finding.**
A party site publishes both its own communiqués and the candidate's own
speeches, and no per-source setting can tell them apart. `tier_confirmed` is
False until an editor decides at review, and the site marks unconfirmed tiers
with an asterisk. Do not "fix" this by having the model classify tier, which
would break the rule that the model never reports provenance.

**Never invent a date.** trafilatura's default `extensive_search` guesses when a
page carries none, with the signature 1 January. `fetch.NO_DATE_GUESSING` turns
it off, `Claim.date` is nullable, and the site prints *date non précisée*. A
date is part of the evidence.

**An unmonitored candidate is not a candidate without policy.**
`Person.monitored` is False when no source is configured, and the grid renders
*Non suivi* on a hatched cell, distinct from *aucune position identifiée*. The
pluralism gate guarantees a row per configured person, it does NOT guarantee
the roster is fairly monitored, so the grid states its own coverage.

**Tier is whose words, not who hosts.**
A speech is tier 1 wherever it is published. Tier 3 (press) can never become a
claim, however cleanly the body extracted — `fetch.route()` demotes it to a
lead. This is enforced centrally; do not re-implement it per fetcher (it was a
bug that only two of four fetchers applied it).

**The grid renders every person × every axis.**
Empty cells show *aucune position identifiée*. Absence is data. Hiding a gap
would produce asymmetric coverage, which for an institution risks reading as an
in-kind campaign benefit (code électoral art. L. 52-8).

**`schema.py` stays provider-neutral.**
One Pydantic model drives OpenAI's `strict: true` and Claude's
`output_config.format`. The model is a config value. Keep it that way — it is
what made switching providers cost zero code.

---

## Gotchas with a reason behind them

**`site` sources only run with `--backfill`.**
Published archives do not change, so a sitemap crawl is one-off; RSS carries the
delta. Re-crawling hundreds of unchanged pages every morning is wasteful and
impolite. `fetch.BACKFILL_ONLY`.

**Liveness counts items *fetched*, not items *kept*.**
A tech feed returning 25 articles that name no candidate is healthy. Alerting on
it trains people to ignore alerts. What this catches is the `nosdeputes.fr`
failure: HTTP 200 with an empty array, indefinitely.

**The AI prefilter is two-tier (one strong term, or two distinct weak ones).**
A flat keyword list passed a pensions debate on *« c'est des calculs »* and a tax
discussion on one stray *données*. Measured, not theoretical.

**`Document.url_hash` includes the content fingerprint.**
So a standing page that gets rewritten is re-read rather than skipped forever.
trafilatura fingerprints extracted text, not boilerplate, so it does not churn.

**Video sources require `speakers:`.**
Auto-captions carry **no speaker labels**. On an interview, a journalist's
question is indistinguishable from the candidate's answer, and the
quote-in-source lint cannot catch it — the quote really is in the transcript, it
is simply not his. `single` → documents, `multi` → leads.

**No `computed_field` on models that round-trip through JSON.**
Pydantic serialises computed fields, then `extra="forbid"` rejects them on
read-back. `Claim.id` and `Document.url_hash` are plain properties for this
reason.

**Archiving is two calls, and the lint checks the shape.**
Save-page-now is asynchronous and does not hand back the snapshot URL, so
`fetch.archive` requests a capture and then resolves what exists via
`/web/2/<url>`. A real capture redirects to a 14-digit timestamp path. The
dated-query form `/web/2026/<url>` is only a *request* for the nearest capture,
and Wayback answers HTTP 200 with a "not archived" page when there is none.
`lint.check_archive_present` therefore matches on the timestamp, not on the
field being non-empty. An earlier version checked presence alone and waved
through six fabricated URLs.

**No i18n library.** 26 chrome strings in `i18n.py`. The *content* is already
bilingual on each claim record.

---

## Ruled out — with evidence. Do not re-add without new measurement.

| Rejected | Why |
|---|---|
| **GDELT DOC 2.0** | Benchmarked 2026-09-18: HTTP 200 with **0 articles** on every query including the control `France sourcelang:french` over 24h; 429s at 2× its documented rate limit |
| **vie-publique.fr** | 2,876 speeches over 17 months, 188 AI-related — but **1 of 7 candidates**, 0 AI speeches. It is the *government* discourse archive; our subjects are opposition figures |
| **Europresse / Factiva** | Cision's licence forbids scripts and TDM. Art. L122-5-3 CPI covers analysis, **not publication**. Quote from the teaser under *courte citation* (L122-5 3°a) instead |
| **Jina Reader / Firecrawl** | Defeat **neither** wall. Le Monde via Jina: *"Il vous reste 60.87% de cet article à lire"* |
| **Google News article bodies** | 4/4 redirect to `consent.google.com` |
| **numerama, usine-digitale** | `robots.txt` disallows this crawler |
| **Managed Agents / Agent SDK** | Context compaction means the prompt that reached the model is not one you wrote or can commit. Reproducibility is the requirement |
| **Consumer Claude/ChatGPT subscriptions** | Anthropic: OAuth is for *"ordinary, individual usage"*, enforced *"without prior notice"*. OpenAI's ToS prohibits programmatic extraction |
| **Open-web crawling** | An arbitrary page cannot tell you whose words it carries, and tier is the whole design. *Domain-scoped* sitemap crawling is fine and is implemented |

---

## Operational

**Never delete `data/observatoire.db` while a process holds it open.**
Doing so, then starting a second writer on the same path, cost ~40 minutes and
produced `sqlite3.OperationalError: disk I/O error` plus orphaned `seen` rows.
`PRAGMA integrity_check` reported `ok` — that is a statement about file
structure, not logical state.

**Verify a URL before adding it to `sources.yaml`.** Fetch it, check
`robots.txt`, confirm it extracts. Seven of twelve candidate feeds probed were
usable; the rest are documented in the file as rejected, with reasons.

**Do not guess API shapes.** `clients.py` was written against current provider
documentation. `fetch_x` raises `NotImplementedError` rather than ship a guessed
endpoint. A wrong shape fails on first contact, after you have paid for a key.

**Long crawls commit per source** (`fetch.run`), so a crash partway keeps the
work. This earned itself immediately.
