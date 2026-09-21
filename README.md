# Observatoire IA & Présidentielle 2027

Tracks what candidates in the April 2027 French presidential election say about
artificial intelligence. Published by the **ESSEC Metalab Institute** in French
and English.

Two views of one dataset: **le fil** (reverse-chronological feed) and **la
grille** (candidates × six policy axes).

> **Not yet published.** Several pre-launch items are human deliverables, not
> code — see [§ Before launch](#before-launch).

---

## Start here

| Document | What it is |
|---|---|
| [`docs/superpowers/specs/2026-09-17-essec-ia-2027-design.md`](docs/superpowers/specs/2026-09-17-essec-ia-2027-design.md) | **The spec.** Governance, data model, sources with tested verdicts, axes, gates, legal basis. Read this first. |
| [`docs/IMPLEMENTATION-PLAN.md`](docs/IMPLEMENTATION-PLAN.md) | Build order, what was measured, what was ruled out and why. |
| [`CLAUDE.md`](CLAUDE.md) | Invariants that are easy to break. Read before changing anything. |
| `docs/chaine-publication.html` | Architecture diagrams: sources, the morning loop, anatomy of a claim. |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install yt-dlp          # CLI dependency, used by the video fetcher
.venv/bin/python -m pytest -q          # 146 tests, all should pass
```

## Running it

```bash
# One-off archive crawl of a domain's sitemap. Run once per domain; published
# archives do not change, so it is never repeated.
.venv/bin/python -m observatoire.fetch --backfill --only bruno-retailleau

# The daily pass: feeds, programmes, pages, video, press leads.
.venv/bin/python -m observatoire.fetch

# Build the bilingual static site into site/
.venv/bin/python -m observatoire.render
```

Extraction needs an API key and is not yet wired to a scheduler:

```bash
export OPENAI_API_KEY=...            # see § Blocked
```

## Layout

```
observatoire/
  schema.py       Pydantic models. One source of truth: the same object is the
                  model's structured-output contract AND the build-time gate.
  prompt.py       The extraction prompt, versioned and hashed.
  fetch.py        Source dispatch → documents (tier 1-2) and leads (tier 3).
  transcript.py   YouTube caption cleaning, quote→timestamp, AI prefilter.
  extract.py      Chunking, batch submit/collect, provenance artifacts.
  clients.py      Provider batch clients. Shapes read from current API docs.
  lint.py         The quality gates. Every one fails the build.
  store.py        SQLite: dedup, documents, leads, claims, source liveness.
  i18n.py         Locale paths and ~26 chrome strings.
  render.py       Static site: hreflang, sitemap, feeds, hashed assets.
sources.yaml      Every source, with its tier. Verified before being listed.
templates/        Jinja2. The grid is a real <table>, deliberately.
tests/            146 tests.
```

## How it works

A daily cron fetches configured sources, an LLM extracts structured claims with
verbatim quotes, CI gates prove the quotes are real, **a human reviews the
rendered preview**, and merging publishes.

The design rests on three ideas worth stating plainly:

1. **Tier is whose words, not who hosts.** A speech is tier 1 wherever it is
   published. Only tiers 1–2 become claims; tier 3 (press) becomes a *lead* — a
   question for the editor, never an auto-published claim.
2. **The empty answer is the correct one, most of the time.** Most documents
   contain no AI position. `claims: []` is expected, and the instruction saying
   so is the primary control against invented positions.
3. **Absence is data.** The grid renders *"aucune position identifiée"* rather
   than hiding a gap. Asymmetric coverage by an institution could be read as an
   in-kind campaign benefit under art. L. 52-8 du code électoral.

## Current state

| | |
|---|---|
| Corpus | 71 documents, 8 leads, 27 AI-bearing (38%) |
| Claims | 6 hand-built fixtures from real quotes, lint-clean |
| Tests | 146 |
| Site | Renders 24 pages, both locales |
| Cost to extract the whole corpus | ~$0.006 batched |

## Blocked

| Blocker | Unblocks |
|---|---|
| `OPENAI_API_KEY` | Extraction. 53 chunks are ready to submit. |
| A GitHub repository | The yt-dlp-in-CI spike — YouTube throttles datacenter IPs and this is **untested**. Also the Actions workflow. |
| X API key (~$90/mo) | The `x` fetcher, which raises `NotImplementedError` by design rather than shipping a guessed endpoint shape. |

## Known gaps

- **Claims should be committed as JSON, not only SQLite.** The editorial gate is
  a pull-request diff, and a binary SQLite file cannot be reviewed in one.
  `data/*.db` is currently gitignored as a local cache; a `data/claims.json`
  export is needed before the PR workflow is real.
- **Méthodologie and Mentions légales are placeholders.** Deliberately — that
  prose needs the *directeur de la publication* and legal review.
- **Gabriel Attal has no wired source.** Renaissance publishes no working feed
  and his France 2040 plan has no document; he is covered only via press leads.
- **`check_grid_complete` lives in the renderer, not `lint.py`** — the rule is a
  property of the rendered grid, so it is asserted in `tests/test_render.py`.

## Before launch

Non-code, and each blocks publication:

- [ ] *Directeur de la publication* named (LCEN art. 6)
- [ ] Editorial charter written and approved
- [ ] Mentions légales published
- [ ] Méthodologie page written
- [ ] Legal review of both
- [ ] Contact address live for *droit de réponse* (LCEN art. 6-IV: 3-month
      window, 3-day response)
- [ ] J-2 publication freeze wired into the cron (code électoral art. L. 49)
