# Observatoire IA 2027 — Implementation Plan

## Context

ESSEC Metalab is publishing a bilingual public site tracking what 2027 French
presidential candidates say about AI. The design spec is at
`essec-metalab-ia2027/docs/superpowers/specs/2026-09-17-essec-ia-2027-design.md`.

Before building, the user asked whether a better stack existed — explicitly
opening the door to agents, consumer subscriptions and other providers. Three
research passes plus direct testing produced four substantive changes to the
spec and ruled several options out on evidence rather than taste. This plan
records the decisions and the build order.

**Decisions made by the user:** EU residency not a concern · Python + Pydantic +
Jinja2 · X stays in at the corrected ~$90/month · **the extraction model defaults
to the cheap tier and an expensive one must justify itself on measurement.**

---

## What testing settled

| Finding | Evidence |
|---|---|
| Jina Reader defeats **neither** wall | Le Monde: *"Il vous reste 60.87% de cet article à lire"*. Google News link → publisher's own consent wall |
| Google News bodies unreachable | 4/4 → same 1375-char `consent.google.com` page |
| trafilatura is CLI-drivable | `--json --with-metadata` → title, date, author, language, dedup fingerprint |
| Captions have no speakers | 43-min video, 1306 cues, 48,705 chars ≈ **323 tokens/min**, zero `<v>` tags |
| `nosdeputes.fr` is dead | HTTP 200 + `{"deputes":[]}` |
| **GDELT dropped** | Benchmarked 2026-09-18: HTTP 200 with 0 articles on every query, including the control `France sourcelang:french` over 24h; 429s at 2× its documented rate limit |

**Ruled out, with reasons:** Europresse/Factiva (Cision licence bans scripts and
TDM; art. L122-5-3 CPI covers analysis, not publication — quote under *courte
citation* L122-5 3°a instead) · Managed Agents and Agent SDK (context compaction
means the prompt sent to the model isn't one you wrote or can commit; Managed
Agents also forfeits the batch discount) · consumer subscriptions (Anthropic:
OAuth is for *"ordinary, individual usage"*, enforcement *"without prior
notice"*; OpenAI ToS prohibits programmatic extraction) · paid news APIs
(Perigon, NewsCatcher, NewsAPI.ai — none licenses paywalled French majors, and
verified RSS plus French open data covers discovery for €0).

---

## Stack

| Layer | Choice |
|---|---|
| Pipeline | **Python 3.12+**, shelling out to `trafilatura` and `yt-dlp` CLIs |
| Schema | **Pydantic** — `model_json_schema()` → the provider's structured-output contract; `model_validate()` → build gate. One source of truth, provider-neutral |
| Model | **`gpt-5.6-luna`** by default, via **Batch API**. Provider is a config value — `schema.py` is neutral. The models page publishes no dated snapshot for it (checked 2026-09-21), so there is nothing to pin to; the model id, prompt hash and text SHA-256 in every request line are what make a changed answer attributable |
| Site | **Jinja2** → static HTML, FR + EN |
| Orchestration | **GitHub Actions** cron at an odd minute + `workflow_dispatch` |
| Hosting | **Vercel** — solely for per-PR preview deployments, so the *directeur de la publication* reviews the rendered site rather than a diff |
| Storage | `data/claims.json` plus the batch JSONL artifacts committed to the repo; git is the audit trail. SQLite is the local working cache and is gitignored — a reviewer cannot read a binary file in a diff |

**Batch is chosen for provenance, not the 50%.** The submitted JSONL is one line
per document carrying the exact prompt, schema and model snapshot; the results
JSONL is the raw output. Commit both and every published claim has byte-exact
provenance. Results expire after 29 days — download and commit, never link.

---

## Build order

### Phase 0 — Spikes (do first; these are load-bearing and untested)

1. **yt-dlp from a GitHub Actions runner.** My test ran on the user's laptop.
   Runners use datacenter IPs, which YouTube throttles for transcripts.
   → *Verify:* a workflow run downloads a French VTT. If it fails, fall back to
   yt-dlp audio + local `faster-whisper`, and mark ASR quotes as machine-
   transcribed pending human confirmation.
2. ~~**GDELT French benchmark.**~~ **DONE 2026-09-18 — dropped.** 12 queries
   across 3 operator variants plus a control all returned HTTP 200 with zero
   articles. Same failure signature as `nosdeputes.fr`. Discovery falls back to
   vie-publique + AN + nosparlementaires + verified RSS, all of which tested clean.
3. **X API** — one key, one timeline fetch, measure real posts/day per candidate.
   → *Verify:* actual monthly cost against the ~$90 estimate.

### Phase 1 — Schema and extraction (run by hand first)

`schema.py` · `extract.py` · `gold/`

- Pydantic `Claim` model per spec §3, including `speakers`, `tier`, `timestamp_s`
- Hand-collect ~30 real documents; build a **50-claim gold set** by hand
- Extraction prompt; the empty-array rule (`claims: []` is valid and expected)
  is the primary hallucination control
- Cache the shared preamble (identical across all documents)

**The gold set decides the model, and the cheap tier is the incumbent.** Score
`gpt-5.6-luna` first, then `gpt-5-mini`, `claude-haiku-4-5`, `gpt-5.6-terra`,
`claude-sonnet-5`, `claude-opus-5` — on French quote fidelity, axis agreement,
`contexte` factual accuracy (the one field no lint protects), and empty-array
discipline. Adopt a costlier model only where it wins measurably. Opus 5 is
**29× the default's price** ($41 vs $1.45/month); that gap needs evidence, not
a default.

→ *Verify:* quote-in-source passes 100% · human agrees with the axis on ≥90% ·
the model returns `[]` on a pensions article with no AI content · a scored
comparison table exists before any model is committed to.

### Phase 2 — Fetch

`sources.yaml` · `fetch.py`

- **Curated tier-1** (stable, cannot be discovered semantically): programme PDFs,
  candidate YouTube channels, X handles, party feeds
- **Discovered tier-3**: vie-publique daily metadata JSON, AN bulk diffs,
  `nosparlementaires.fr` (free key, 60 req/min), ~15 verified RSS
- Dispatch on `type` → normalise all to `{text, url, date, tier}`
- **documents/** (tier 1–2, extractable) vs **leads/** (tier 3, editor question)
- YouTube discovery via `playlistItems.list` (**1 quota unit**), never
  `search.list` (100 units, and new projects get only 100/day)
- Wayback snapshot at ingest · dedup on trafilatura `fingerprint` · per-source
  item counts

→ *Verify:* a real run produces documents and leads with non-zero per-source
counts; deliberately point a source at a dead URL and confirm the liveness
assert fires.

### Phase 3 — Gates, batch, PR

`lint.py` · `.github/workflows/daily.yml`

- Gates per spec §7: quote-in-source · banned evaluative adjectives · archive
  present · **source liveness** (`count > 0 and newest_date > now - 7d`)
- Batch submit at T, collect at T+2h, retry expired `custom_id`s — never block
- Commit request + response JSONL alongside claims
- PR via `peter-evans/create-pull-request`; pin action SHAs
- **Dead-man's switch**: ping a healthcheck on success, alert on absence.
  GitHub gives *no* notification when a scheduled workflow silently stops.

→ *Verify:* end-to-end dry run opens a PR with real claims; inject a fabricated
quote and confirm the build goes red.

### Phase 4 — Site

`render.py` · `templates/` · `tests/test_seo.py`

Pages per spec §9: le fil · la grille · per-person · méthodologie · corrections ·
mentions légales — each in FR and EN.

Hand-rolled because we're not using a framework — sizes are honest:

| Piece | Effort | Trap |
|---|---|---|
| Locale routing | ~20 lines | Trivial loop over `['fr','en']` |
| hreflang | ~15 lines | **31% of international sites get this wrong** — needs a test |
| sitemap + `xhtml:link` | ~40 lines | Same data as hreflang, one function |
| RSS/Atom | ~30 lines | Use `feedgen`; RFC 822 vs 3339 date formats |
| Asset pipeline | ~10 lines | Content-hash the one CSS file; skip minification |

**Accessibility — build to WCAG 2.1 AA regardless of RGAA scope** (ESSEC is an
EESC, a legal grey zone; ask the DPO). Two things that are easy to miss:
- La grille must be a real `<table>` with `<th scope>` and `<caption>`, **not**
  CSS-grid divs. Horizontal scroll needs `tabindex="0"` + `role="region"` + name.
- French verbatim quotes on English pages need `lang="fr"` — RGAA 8.4/8.7.

→ *Verify:* both locales build · hreflang test asserts self-reference,
bidirectionality and `x-default` · grid contains every person × axis cell ·
`axe` clean · Lighthouse ≥95.

### Phase 5 — Pre-launch (non-code, blocks publication)

DP named · editorial charter approved · mentions légales · méthodologie page ·
legal review of both · contact address live for *droit de réponse* ·
J-2 publication freeze condition wired into the cron (code électoral art. L. 49).

---

## Costs

| Item | Monthly |
|---|---|
| X API (~20 candidates × ~30 posts/day @ $0.005/read) | ~$90 |
| Extraction, batched (`gpt-5.6-luna`) | ~$1.45 |
| Everything else (vie-publique, AN, nosparlementaires, Vercel, Actions) | $0 |
| **Total** | **~$92** |

Output is ~68% of the model bill because the schema is bilingual, so output
price is the lever. Claude 4.7-and-later models carry a documented ~30%
tokenizer penalty, which is included in the $41/month Opus 5 comparison.

**Correction worth recording:** an earlier version of this plan defaulted to
Opus 5 on the reasoning that "cost is not a constraint." That rested on a
text-only estimate of $1.25/week which later grew ~25× once video transcripts
and bilingual output were counted. The number was updated; the conclusion
resting on it was not. Hence the flip.

---

## Spec status — APPLIED 2026-09-18

`docs/superpowers/specs/2026-09-17-essec-ia-2027-design.md` is now 485 lines and
carries all of it: §4 source table with tested verdicts (nosparlementaires in,
GDELT and Jina out with evidence) · §6 batch execution, snapshot pinning, and the
cheap-tier default with the cost table · §6b provenance artifacts · §6c the gold
set that decides the model · §12 costs at ~$92/month.

**Wording for the méthodologie page** — accurate rather than overclaiming:
*"The exact inputs, prompts, model version and raw model outputs behind every
published claim are archived and publicly inspectable. LLM sampling is not
bit-reproducible, so re-running may yield semantically equivalent but
non-identical output."*

---

## Verification (end to end)

1. `python -m pytest` — schema, lints, hreflang, grid completeness
2. `python fetch.py --dry-run` — per-source counts, liveness asserts
3. `python extract.py --gold` — quote fidelity and axis agreement against the 50-claim gold set
4. Trigger the workflow via `workflow_dispatch` — confirm PR opens with a Vercel preview URL
5. Open the preview, verify a video claim by its `?t=` deep link
6. `axe` + Lighthouse on both locales
7. Inject a fabricated quote → confirm red build
