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
uv sync --all-extras --group dev      # creates .venv from uv.lock
uv tool install yt-dlp                # CLI dependency, used by the video fetcher
uv run python -m pytest -q            # 210 tests, all should pass
```

`uv.lock` pins every transitive dependency, not just the eleven direct ones.
For a publication whose claim is byte-exact provenance, a rebuild that quietly
resolved different versions would undercut the point. CI installs with
`--frozen`, which fails rather than re-resolving.

Dependencies are split by what each command actually needs. The base set is
what *renders* — four packages — so Vercel builds a preview without installing
a PDF parser and a model SDK to produce static HTML:

| Install | Gets you |
|---|---|
| `uv sync --no-dev` | render the site (what Vercel runs) |
| `uv sync --extra fetch` | + fetching sources |
| `uv sync --all-extras --group dev` | + extraction, + tests |

## Running it

```bash
# One-off archive crawl of a domain's sitemap. Run once per domain; published
# archives do not change, so it is never repeated.
uv run python -m observatoire.fetch --backfill --only bruno-retailleau

# The daily pass: feeds, programmes, pages, video, press leads.
uv run python -m observatoire.fetch

# Extract. Submit at T, collect when the batch is done — never blocking on it.
# --dry-run exercises the whole path against a fake client and spends nothing.
export OPENAI_API_KEY=...
uv run python -m observatoire.extract submit
uv run python -m observatoire.extract collect

# Build the bilingual static site into site/, from data/claims.json
uv run python -m observatoire.render
```

`collect` writes new claims into `data/claims.json`, which is the published
record and the thing reviewed in the pull request. It never overwrites a claim
the file already carries — once a claim is in there a human has been through
it. `render` builds from that file and never opens the database, so CI needs
no SQLite at all.

Extraction is not yet wired to a scheduler — see [§ Before launch](#before-launch).

## Seeing it end to end

`docs/chaine-publication.html` has the architecture: the sources, the morning
loop, and the anatomy of a claim.

To watch the whole thing actually run, `--dry-run` exercises every step against
a fake model — no key, no spend, real artifacts written:

```bash
uv run python -m observatoire.fetch --no-archive   # sources → documents + leads
uv run python -m observatoire.extract submit  --dry-run --artifacts /tmp/a
uv run python -m observatoire.extract collect --dry-run --artifacts /tmp/a --claims /tmp/claims.json
uv run python -m observatoire.lint                 # the gates, over what is published
uv run python -m observatoire.render               # → site/, then open site/fr/
```

The fake client answers `[]` for every chunk, which is the *correct* answer for
most documents — so this shows you the machinery and the provenance artifacts,
not claims. Real claims need a key and an account under its billing limit.

`--no-archive` skips Wayback. Leave it off for a real run: the snapshot is
taken at ingest and a claim without one cannot pass the gates. With it on,
expect roughly a second per document.

## Reading the data locally

Everything the pipeline holds is one SQLite file, and every record is stored as
JSON in a `payload` column — right for the pipeline, unreadable by eye. The
database therefore carries four views that unpack it, so no one has to write
`json_extract` by hand:

```bash
uvx datasette data/observatoire.db      # browsable, faceted, no install
```

| View | What it answers |
|---|---|
| `v_documents` | what was fetched and kept: person, kind, tier, date, size, whether it is archived |
| `v_leads` | tier 3, never published as a claim — the editor's queue |
| `v_claims` | quote, position, contexte, axis, tier, source and archive links |
| `v_sources` | per-source run counts. `fetched` is the liveness signal, not `kept` |

Two things worth knowing while reading:

- **`v_documents.kind = 'an'` is the Assemblée nationale**, and those rows have
  `tier_confirmed = 1`. Every other source defaults its tier, because a party
  site cannot distinguish its own communiqué from the candidate's speech.
- **An empty extraction is the expected result.** Most documents carry no AI
  position, so a document with no claim against it is the normal case, not a
  gap.

The claims themselves are also plain text in `data/claims.json` — that file is
the published record and what the pull request diff shows — and the rendered
site in `site/` is the same data as a reader sees it.

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
  store.py        SQLite working cache, plus the claims.json the site is built
                  from — the published record, reviewed as a diff.
  i18n.py         Locale paths and ~26 chrome strings.
  render.py       Static site: hreflang, sitemap, feeds, hashed assets.
  gold.py         Scores candidate models against the gold set. Refuses to
                  score contexte, which no machine can check.
pyproject.toml    Dependencies, split by what each command needs. uv.lock pins
                  every transitive version.
sources.yaml      Every source, with its tier. Verified before being listed.
templates/        Jinja2. The grid is a real <table>, deliberately.
data/claims.json  Published claims. In git; the database is not.
data/artifacts/   Batch request and response JSONL: byte-exact provenance.
gold/claims.json  Labelled documents that decide which model runs.
tests/            209 tests.
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
| Corpus on `main` | 71 documents, 8 leads, 27 AI-bearing (38%) |
| Claims | 6 hand-built fixtures from real quotes, lint-clean |
| Tests | 209 |
| Site | Renders 24 pages, both locales |
| Cost to extract the whole corpus | ~$0.006 batched |

The pipeline is live: the daily workflow ran green end to end on 2026-09-21 and
submitted its first real batch. Counts above describe `main`; the morning's work
accumulates on the `daily` review branch until it is merged, so that branch is
ahead. **No model-extracted claim has been reviewed yet** — the six in
`data/claims.json` were built by hand to exercise the gates and the renderer.

## Blocked

| Blocker | Unblocks |
|---|---|
| X API key (~$90/mo) | The `x` fetcher, which raises `NotImplementedError` by design rather than shipping a guessed endpoint shape. Also Phase 0 spike 3, which measures the real posts/day behind the ~$90 estimate. |

## Known gaps

- **No model has been chosen on evidence yet.** Spec §6c requires a scored
  comparison before committing to one, with the cheap tier as the incumbent.
  The harness exists — `python -m observatoire.gold --model A --model B` scores
  quote fidelity, axis agreement and empty-array discipline, and prints every
  `contexte` for the human check no lint can do. What is missing is the labels:
  `gold/claims.json` carries **6** of the 50 claims the spec asks for, so the
  empty-discipline column is the only trustworthy one today. Label what the
  pipeline produces and add it. No comparison has been run.
- **YouTube extraction does not work from CI.** Measured 2026-09-21 on a
  runner, twice, and via two independent endpoints: both answer *"Sign in to
  confirm you're not a bot"* / `RequestBlocked`. Listing still works, so video
  leads are unaffected; timestamped video claims are not reachable from CI.
- **Méthodologie and Mentions légales are placeholders.** Deliberately — that
  prose needs the *directeur de la publication* and legal review.
- **Link rot warns rather than fails, deliberately.** Spec §7 asks that every
  `source_url` resolves. Read literally that gate would fail the build the day
  a candidate deletes a page — the precise event the Wayback snapshot exists to
  survive, on a citation that still works. `lint --check-links` therefore only
  turns fatal when the original is gone *and* no capture stands behind it, so
  the quote cannot be checked by anyone. It runs in the morning job, not in the
  pull-request gate, which is deliberately offline.
- **Accessibility has never been measured.** The structural rules are asserted
  in `tests/test_render.py`, but `axe` and Lighthouse have not been run once.
- **One of seven candidates has no wired source** — Jordan Bardella. He has
  zero turns in the Assemblée because he sits in the European Parliament, whose
  verbatim reports need their own fetcher. The grid says so: *Non suivi*, not
  *aucune position*. Attal and Le Pen were in this list until the `an` fetcher;
  Mélenchon and Philippe hold no seat anywhere and stay on press/site sourcing.
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

Code:

- [x] `.github/workflows/daily.yml` — the morning pass. Verified green end to
      end 2026-09-21: 10 new documents, 110 chunks submitted, gates clean,
      24 pages rendered, review branch pushed.
- [x] `.github/workflows/checks.yml` — the gates on the pull request, required
      by branch protection on `main`. The daily workflow runs on a schedule,
      so its result never attached to the review branch's head commit.
- [ ] Dead-man's switch: the step exists but is skipped until a
      `HEALTHCHECK_URL` secret is set. GitHub gives *no* notification when a
      scheduled workflow silently stops — the `nosdeputes.fr` failure again.
- [ ] Opening the review is manual. It needs "Allow GitHub Actions to create
      and approve pull requests", and that same setting lets a workflow
      *approve* one, which is the opposite of the editorial premise. The
      branch is pushed either way; someone clicks once per cycle.
- [ ] J-2 publication freeze wired into the cron (code électoral art. L. 49),
      with the election dates in config rather than in the workflow
- [ ] A gold set, and a model chosen against it (spec §6c)
- [ ] Required review on merge, once the *directeur de la publication* has an
      account — GitHub forbids approving your own pull request, so requiring
      an approval with a single maintainer deadlocks every review.
