# Observatoire IA — French Presidential Election 2027

*[Version française](README.md). The French README is the reference; this is a translation.*

A tool for analysing the positions of candidates in the 2027 French presidential election
on issues related to artificial intelligence.

The pipeline collects public content, attributes it to a candidate, annotates it by
dimension, computes a positioning indicator from it and produces a traceable report.

> **Status: POC.** Scope limited to 5 candidates, 3 dimensions and 5 sources.
> No figure produced at this stage is intended for publication.

---

## Principles

1. **Traceability first.** No score without the passages that justify it, with URL and
   collection date.
2. **Neutrality.** Positioning axes are descriptive, never normative. All candidates are
   treated with the same sources and the same rules.
3. **Statistical caution.** Below a segment threshold, the report shows *« données
   insuffisantes »* (insufficient data) rather than a figure.
4. **The LLM assists, it does not decide.** A sample of the annotations is reviewed by
   people with differing political sensibilities.

---

## Architecture

Hexagonal architecture. Dependencies always point inwards: the adapters know the domain,
the domain knows no one.

```
┌──────────────────────────────────────────────────────────────────┐
│                          ADAPTERS                                │
│  RSS · HTML · Trafilatura · SQLite · Mistral · Fake · Rendering  │
└───────────────────────────┬──────────────────────────────────────┘
                            │ implement the Protocols
┌───────────────────────────▼──────────────────────────────────────┐
│                        APPLICATION                               │
│  collect_daily → annotate_documents → compute_scores → report    │
└───────────────────────────┬──────────────────────────────────────┘
                            │ depend on the Protocols
┌───────────────────────────▼──────────────────────────────────────┐
│                          DOMAIN                                  │
│  Models · Ports · Scoring (pure functions) · Errors              │
│  No external dependency                                          │
└──────────────────────────────────────────────────────────────────┘
```

### The pipeline

```
 Sources          Collection         Processing          Analysis           Reporting
┌─────────┐     ┌───────────┐     ┌─────────────┐     ┌────────────┐     ┌───────────┐
│ RSS     │     │ fetch     │     │ extraction  │     │ dimension  │     │ scores    │
│ Sites   │ ──► │ robots    │ ──► │ segmentation│ ──► │ position   │ ──► │ report    │
│ Official│     │ dedup     │     │ attribution │     │ sentiment  │     │ md / html │
└─────────┘     └───────────┘     └─────────────┘     └────────────┘     └───────────┘
                      │                   │                  │                 │
                      └─────────── SQLite (traceability, hash, timestamps) ────┘
```

### Source levels

| Level | Content | Use |
|---|---|---|
| 1 | The candidate's own words (programme, speeches, official accounts) | Feeds the scores |
| 2 | Party and campaign team | Feeds the scores, with reduced weight |
| 3 | Media, when the quote is direct and attributed | Feeds the scores under that condition |
| 4 | Third-party analysis and commentary | Context only |

---

## Folder structure

```
observatoire-ia-2027/
├── CLAUDE.md                   # coding rules for Claude Code
├── PROMPT_BOOTSTRAP.md         # instructions for generating the skeleton
├── pyproject.toml
├── Makefile
├── .env.example
│
├── config/                     # all business settings, no code
│   ├── candidates.yaml         # candidates, aliases, official sources
│   ├── sources.yaml            # feeds and sites, with trust level
│   ├── taxonomy.yaml           # dimensions, definitions, axes
│   └── scoring.yaml            # weights, thresholds
│
├── src/observatoire/
│   ├── domain/                 # models, ports, pure scoring, errors
│   ├── application/            # the 4 use cases
│   ├── adapters/
│   │   ├── sources/            # rss, html page, fixtures
│   │   ├── extraction/         # trafilatura, LLM fallback
│   │   ├── llm/                # mistral, fake, versioned prompts
│   │   ├── storage/            # sqlite
│   │   └── reporting/          # markdown, html
│   ├── services/               # dedup, segmentation, matcher, robots
│   ├── config/                 # settings, YAML loading
│   ├── observability/          # logs, token counter
│   └── cli.py                  # composition root
│
├── tests/
│   ├── unit/                   # domain and use cases, no network
│   ├── integration/            # full pipeline on fixtures
│   └── fixtures/               # RSS, HTML, frozen LLM responses
│
├── data/                       # ignored by git
│   ├── raw/ processed/ reports/
│
└── docs/
    ├── architecture.md
    ├── methodology.md          # codebook and scoring rules
    └── adr/                    # architecture decision records
```

---

## Quick start

```bash
git clone <repo> && cd observatoire-ia-2027
make install                 # environment and dependencies
cp .env.example .env         # the Mistral key is not needed for the demo
make demo                    # full offline pipeline on fixtures
open data/reports/latest.html
```

With real sources:

```bash
export MISTRAL_API_KEY=...
export LLM_PROVIDER=mistral
observatoire run-all --since 2026-09-01
observatoire usage           # tokens used and estimated cost
```

---

## Commands

| Command | Role |
|---|---|
| `observatoire collect` | Fetches content, deduplicates it, stores it with its provenance |
| `observatoire annotate` | Segments and annotates by dimension, position and sentiment |
| `observatoire score` | Computes the indicator per candidate and per dimension |
| `observatoire report` | Produces the Markdown or HTML report |
| `observatoire run-all` | Runs the four steps in sequence |
| `observatoire usage` | Tokens used per step |
| `make check` | ruff, mypy strict, pytest, coverage |

---

## The indicator

Five components, published separately rather than aggregated into a single opaque figure:

| Component | Question | Measure |
|---|---|---|
| Orientation | Where does the candidate stand on the axis? | Weighted mean of positions, from −2 to +2 |
| Salience | Do they talk about it? | Share of speech, normalised |
| Concreteness | Are they specific? | Share of quantified or dated proposals |
| Consistency | Do they hold the same line? | Inverse of the variance over time |
| Tone | In what tone? | Mean sentiment |

The computation lives in `domain/scoring.py`, as pure and deterministic functions, and the
weights in `config/scoring.yaml`.

---

## Compliance

- `robots.txt` is respected, the user-agent is identifiable, and the request rate is
  limited per domain.
- RSS feeds and official APIs take priority over page crawling.
- Collection is limited to statements by the candidates and their parties. No user
  comments, no personal data about third parties.
- Political opinions are sensitive data under the GDPR: the legal framework must be
  validated by a lawyer before any publication.
- The methodology and codebook are published with the report.

---

## Roadmap after the POC

1. Expand to 10 candidates, 9 to 11 dimensions and 40 sources.
2. Add audio and video transcription, and OCR of programmes published as PDF.
3. Set up human annotation and measure inter-annotator agreement.
4. Scheduled daily orchestration and monitoring.
5. Bias audit, pluralist review, then publication.
