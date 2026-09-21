# Observatoire IA & Présidentielle 2027 — Design

**Publisher:** ESSEC Metalab Institute for Artificial Intelligence, Data and Society
**Date:** 2026-09-17
**Status:** Design, pending review

---

## 1. Purpose

Track, centralise and explain what candidates in the April 2027 French
presidential election say about artificial intelligence.

Two views of one dataset:

- **La grille** — candidates × six AI policy axes. Where everyone stands.
- **Le fil** — reverse-chronological feed of claims as they land. What's new.

Bilingual FR/EN from day one.

### Why it should exist

`lespresidentielles.ai` and `comparateurpresident.com` compare *all* policy
themes and use AI as the tool. Nobody treats **AI policy as the subject**.
Metalab has domain authority there and none on pensions or immigration.

The gap is real and current: in the same week of September 2026 the French
press published both *"la surenchère des candidats sur l'IA"* (Capital) and
*"la révolution que les candidats à la présidentielle ignorent"* (TF1). No
one — including the press — has a clear picture of what candidates actually
say about AI.

Secondary gap: `lespresidentielles.ai` draws on "official programmes" and
names no individual operator. Most candidates have no programme yet, and a
named *directeur de publication* plus a published methodology is credibility
they cannot match.

### Non-goals

No chatbot. No user accounts, comments or forum. No
search. No public API. No scoring, ranking or endorsement of candidates. No
sentiment analysis. No coverage of non-AI policy topics.

---

## 2. Governance

| Role | Holder |
|---|---|
| Publisher | ESSEC Metalab Institute |
| Directeur de la publication | Named Metalab faculty member (required before launch) |
| Editorial team | IDEAS student think tank, faculty-mentored |
| Editorial charter | Approved once by the DP; governs all subsequent output |

The DP owns the charter and correction authority, not per-claim review — as
in any publication. Per-claim review is the editorial team's job.

### Pre-launch checklist (non-code)

- [ ] DP named
- [ ] Editorial charter written and approved
- [ ] Mentions légales published (LCEN art. 6)
- [ ] Méthodologie page published
- [ ] Legal review of charter + méthodologie
- [ ] Contact address live for droit de réponse

---

## 3. Data model

One table. Both views are renderings of it.

```
claim
  id              stable hash(source_url, quote_fr)
  person          person slug — NOT "candidate" (see below)
  party
  date            date of the statement, not of ingest
  axis            one of the six (§5)
  claim_type      programme | discours | vote | interview | video | post
  tier            whose words, not who hosts:
                  1 the person's own words (programme, speech, interview,
                    own post) — including when hosted on a party channel
                  2 party or staff speaking for them
                  3 press reporting what they said
  source_url
  archive_url     Wayback snapshot, captured at ingest
  timestamp_s     video sources only — deep-links the citation
  quote_fr        VERBATIM. Never edited, never translated.
  quote_gloss_en  marked translation, shown beside quote_fr on /en/
  position_fr/en  one neutral sentence: what was committed to
  contexte_fr/en  short explanation — Metalab editorial, labelled as such
  last_verified
  status          pending | published | corrected | retracted
```

**`person`, not `candidate`.** Seven months out the field churns —
primaries, withdrawals, entries. Sixteen candidates had declared as of
September 2026; the Conseil constitutionnel list lands ~March 2027.
Candidacy is a mutable attribute, not an identity.

**Three separated text layers.** `quote_fr` is the candidate's words.
`position_fr` restates them neutrally. `contexte_fr` is Metalab explaining
what they mean. Rendered visually distinct so a reader always knows whose
words they are reading. `contexte` is where Metalab's expertise earns its
place — *"cloud souverain certifié = SecNumCloud, label ANSSI"* is
explanation; *"une proposition ambitieuse"* is evaluation and is rejected by
lint (§7).

Storage: SQLite, committed to the repo. Git is the audit trail and the
correction log.

---

## 4. Sources

Configured per person in `sources.yaml`. Adding a source is one line;
adding a source *type* is one function plus a dict entry.

```yaml
- person: bruno-retailleau
  party: LR
  an_id: ...
  sources:
    - {type: pdf,     url: "…/programme-ia-2026.pdf", tier: 1}
    - {type: youtube, channel: "@lesrepublicains",    tier: 1, speakers: single}
    - {type: rss,     url: "https://republicains.fr/feed", tier: 2}
    - {type: x,       handle: "BrunoRetailleau",      tier: 2}
    - {type: news,    query: '"Retailleau" intelligence artificielle', tier: 3}
```

### Verified 2026-09-17

| Source | Status | Role |
|---|---|---|
| Google News RSS (FR) | 200, 167 KB, relevant | Discovery. Free, no auth |
| AN open data — scrutins, lég. 17 | 200, 26 MB zip | Hard vote evidence |
| vie-publique.fr | 200 | Speech archive |
| trafilatura 2.2.0 | Clean text + auto date/author | Extraction for all HTML |
| yt-dlp 2026.07.04 | FR auto-captions confirmed | Video |
| X API | Pay-per-use, $0.005/read, no free tier | Timeliness |
| **nosparlementaires.fr** | Free key, 60 req/min, Licence Ouverte, regenerated daily | **Votes — replaces nosdeputes** |
| vie-publique metadata JSON (data.gouv.fr) | Licence Ouverte, updated daily | **Change feed for speeches** |
| Assemblée nationale bulk XML/JSON | 200, 26 MB zip | Scrutins + comptes rendus |
| **nosdeputes.fr** | **200 but empty array — dead** | **Excluded** |
| **GDELT DOC 2.0** | **Benchmarked 2026-09-18: HTTP 200 with 0 articles on every query, including the control `France sourcelang:french` over 24h; 429s at 2× the documented rate limit** | **Excluded** |
| **Jina Reader** | Tested: Le Monde → *"Il vous reste 60.87% … réservée aux abonnés"*; Google News → publisher's own consent wall | **Fallback only — defeats neither wall** |

**Excluded and why.** Academic papers: contain no candidate positions.
Bluesky / Mastodon: free and easy, but French candidates are not
meaningfully present (`searchPosts` also 403s; only `getAuthorFeed` is
open). TikTok / Instagram: largest audience, no lawful automated access, and
short-form video carries personality rather than policy. LinkedIn: no API.

### Two outputs: documents and leads

`fetch.py` writes to **two** destinations, not one.

```
documents/   full text → extracted into claims
leads/       headline + publisher + date + link → a question for the editor
```

A **lead is not a claim**. It surfaces in the PR as *"Capital, 15 Sept —
«200 milliards, 100 000 ingénieurs». Do we have this from a primary source?"*

This is enforced by the technology, not just by policy. **Google News RSS
links redirect to `consent.google.com`** — all four articles tested returned
the same 1375-character consent page rather than the article. Paywalled
majors behave similarly (Le Monde: link resolves, 286 characters of teaser).
Open specialist outlets work fully (Next.ink: 50 items, 3178 characters).

So press cannot be auto-ingested as claims even if we wanted to. The
constraint matches the editorial principle already chosen: tier 3 is
discovery. Circumventing a consent wall is not an option for an
institutional publisher.

### Hard rule (social media only): own timelines, never post search

On X and any other social platform, fetch **only a named person's own
timeline**. Their posts are GDPR art. 9(2)(e) — *data manifestly made public
by the data subject*. A post search sweeps in private individuals' political
opinions, which is sensitive data on non-public figures.

This does not restrict the `news` source type: a Google News RSS query
searches press coverage, not individuals' posts.

### Video-specific rules: no speaker diarization

YouTube auto-captions carry **zero speaker labels** — no `<v>` voice tags, no
turn markers. Verified on a 43-minute Public Sénat programme: 10,584 VTT
lines, 1,306 cues after cleaning, 48,705 characters (~13,900 tokens;
calibration ≈ **323 tokens per minute** of French speech), and not one
indication of who is talking. The file opens with the *presenter*, unmarked.

An interviewer asking *"Vous proposez 200 milliards, ce n'est pas irréaliste ?"*
would be extracted as the candidate's words. **The quote-in-source lint
cannot catch this** — the quote really is in the transcript; it is simply not
his. That is a retraction under ESSEC's name.

Therefore `speakers` is required on every video source:

- `single` → **documents.** Speeches, conference talks, programme launches.
  One voice, no attribution risk. This is where programmes get announced.
- `multi` → **leads.** The transcript tells the editor *"AI discussed at
  23:14"*; a human listens and writes the claim.

Per-channel default is sufficient; review catches the exceptions and the
editor may promote a lead by hand. Real diarization (pyannote, WhisperX) is
rejected: GPU dependency, unreliable on French political crosstalk, and the
lead route captures ~90% of the value for none of the cost.

**Quote → timestamp is the same operation as the anti-fabrication lint.**
`transcript.find(quote)` then walking the cues returns the citation second,
or `None` if the quote is absent. Verified both ways. Video needs no separate
quote lint.

### X-specific rules

X posts are deleted and 280 characters can misrepresent a nuanced position.
Therefore: archive text + Wayback at ingest (mandatory, unlike other
sources), and **a post is sufficient for le fil but not for a grille cell** —
grid cells prefer programme and speech sources. X sits behind a config flag
so a pricing change disables it in one line.

---

## 5. Axes

1. Régulation
2. Souveraineté & infrastructure
3. Emploi & formation
4. IA dans les services publics
5. Surveillance & libertés
6. Financement

Validated against observed 2026 material: Retailleau (125 000 civil servants
redeployed, 15 Md€/an savings for 23 Md€ investment, *« pourcentage de
souveraineté »*, GAFAM audit, certified sovereign clouds, explicit EU
deregulation stance); Attal (200 Md€ "France 2040", 50/50 public-private,
10 M workers trained in 3 years); Philippe (100 000 engineers/year, double
compute capacity). Every one maps cleanly onto an axis.

The list is versioned config. Adding a seventh axis later is a config change
plus a backfill pass over stored claims.

---

## 6. Extraction

**Execution: Message Batches API**, submit at T and collect at T+2h, retrying
expired `custom_id`s; never block on the batch. Chosen for provenance rather
than the 50% discount — see §6b. Model IDs are pinned to dated snapshots, never
floating aliases, because an alias moves under you silently.

**Model: decided by measurement, defaulting to the cheap tier.** The burden of
proof sits on the expensive model, not the cheap one.

This is not frontier work. Four of the five generated fields are verbatim
copying, a 6-way classification, one neutral sentence and a short FR→EN
translation. A plainer model is arguably *safer* at `quote_fr`, being less
inclined to tidy the French — and a botched quote is caught mechanically by the
quote-in-source lint, so it costs a claim, not credibility. Only `contexte`
demands French policy knowledge, and it is the one generative field no lint
checks.

**Default: `gpt-5.6-luna`** (or `gpt-5-mini`). Measured monthly cost at 4.11M
input / 1.73M output tokens, batched:

| Model | Batch in/out per MTok | $/month |
|---|---|---|
| **gpt-5.6-luna (default)** | $0.10 / $0.60 | **$1.45** |
| gpt-5-mini | $0.125 / $1.00 | $2.24 |
| Claude Haiku 4.5 | $0.50 / $2.50 | $6.40 |
| gpt-5.6-terra | $1.00 / $6.00 | $14 |
| Claude Sonnet 5 | $1.00 / $5.00 | $17 † |
| Claude Opus 5 | $2.50 / $12.50 | $41 † |

† Includes the 1.3× tokenizer penalty Anthropic documents for Claude 4.7-and-later
models ("approximately 30% more tokens for the same text").

Output is ~68% of the bill, because the schema is bilingual — five generated text
fields per claim. **Output price is therefore the lever**, and that is where the
spread is widest ($0.60 vs $12.50).

**The provider is a config value, not an architecture.** `schema.py` is
provider-neutral: the same Pydantic model feeds OpenAI's `strict: true`
Structured Outputs and Claude's `output_config.format`. Both offer a 50% batch
discount and JSONL request/response artifacts. Switching is one line and a
different client, so the decision is reversible and should be made on evidence.

### 6c. The gold set decides

50 hand-labelled claims drawn from real documents. Every candidate model is
scored on:

1. **French quote fidelity** — does `quote_fr` survive the quote-in-source lint?
2. **Axis agreement** — does a human agree with the classification?
3. **`contexte` factual accuracy** — the field no lint protects, checked by hand.
4. **Empty-array discipline** — does it correctly return `[]` on a document with
   no AI content?

A costlier model is adopted only where it wins measurably. If the gap turns out
to be confined to `contexte`, the fix is a second model on that one field — not
a 29× markup across the whole pipeline.

**The model must be allowed to return nothing.** `claims: []` is a valid,
expected answer and the prompt says so explicitly. Most fetched documents
contain no AI content. A model asked to find AI positions in an article
about pensions will find one — this instruction is the primary hallucination
control, and the quote-in-source lint cannot catch a real quote bent into a
claim it does not support.

**Prefilter policy, decided by arithmetic.**

| | Volume/week | Tokens | Cost |
|---|---|---|---|
| Text | ~100 docs × 2K | 200K | ~$1 |
| Video | ~50 vids × 19K | ~950K | ~$5 |

Text: **no prefilter** — saving $1/week is not worth the false-negative risk
(a candidate can discuss *souveraineté numérique*, Mistral or data centres
without saying "IA"). Video: **keyword prefilter on the VTT** — 10× the
tokens per document, and over 90 minutes anyone discussing AI will say the
words, so the check is reliable.

**No sentiment analysis, no published EDA.** Sentiment outputs a score; a
score is an evaluation; an evaluation of a candidate published under ESSEC's
name is the exact neutrality risk this design exists to avoid. Stance on
regulation is captured as a *quoted position classified into an axis*, never
as inferred tone. EDA has one internal use only: coverage counts per person ×
axis, to catch asymmetry before publication.

**Video transcripts are a discovery layer, never a quote source.** Auto-
captions are machine transcription; an error in a figure published under
ESSEC's name is a correction and a credibility hit. The transcript locates
the passage; a human verifies the quote against the audio at that timestamp.
~2 min/claim, ~5 claims/week.

---

### 6b. Provenance artifacts

The submitted batch JSONL carries one line per document with its `custom_id`,
the exact prompt, the exact schema and the pinned model snapshot. The results
JSONL carries the raw model output. **Both are committed to the repo beside the
claims they produced**, so every published claim has byte-exact provenance.
Batch results are retained by the API for only 29 days — download and commit,
never link.

Also recorded per run: prompt hash, schema hash, source-document SHA-256, the
`usage` block, and the timestamp.

**The claim made on the méthodologie page is deliberately accurate rather than
flattering:**

> The exact inputs, prompts, model version and raw model outputs behind every
> published claim are archived and publicly inspectable. LLM sampling is not
> bit-reproducible, so re-running may yield semantically equivalent but
> non-identical output.

Temperature 0 is not deterministic on any hosted API — floating-point
non-associativity and batch-shape-dependent kernel scheduling flip near-tied
tokens. Claiming a reproducibility we cannot deliver would be exactly the
credibility failure this design exists to prevent.

## 7. Quality gates (CI)

Every gate fails the build. No claim reaches the site without passing all of
them plus human review.

| Gate | Implementation |
|---|---|
| Anti-fabrication | `assert quote_fr in source_text` — mechanically impossible to publish an invented quote |
| Neutrality | Reject an evaluative-adjective list in `position` and `contexte` (*ambitieux, flou, réaliste, timide*, …) |
| Pluralism (structural) | The rendered grille must contain a cell for **every** person × **every** axis. An *empty* cell reading *"aucune position identifiée"* is valid output; a *missing* cell is a bug and fails the build. Absence is data and must be shown |
| Link integrity | Every `source_url` resolves; `archive_url` present |
| Schema | Structured-output validation |
| Source liveness | Per-source item counts are logged each run. Zero items for 3 consecutive runs fails the build. A silently dead feed is indistinguishable from "nothing happened" — `nosdeputes.fr` returned HTTP 200 with an empty array throughout our research |

The pluralism gate is also the legal defence: asymmetric coverage by an
institution could be read as an in-kind campaign benefit under art. L. 52-8
du code électoral. Mechanically enforced symmetry answers that.

---

## 8. Pipeline

```
sources.yaml     per person: name, party, sources with type + tier + speakers
fetch.py         httpx · trafilatura · feedparser · yt-dlp · X API
                 → documents/  full text, extractable   (tier 1-2)
                 → leads/      headline only, for the editor (tier 3)
                 URL-hash dedup · Wayback save at ingest · per-source counts
prefilter.py     video only: AI terms in cleaned transcript, else drop
extract.py       claude-opus-5, structured output → pending/  (may be [])
lint.py          §7 gates
render.py        Jinja2 → site/  (built by Vercel, not by the cron)
```

```
daily cron → fetch → extract → PR opened
           → Vercel preview deploy → editorial review → merge → production
```

**The PR is the editorial workflow.** Free review UI, free audit trail, free
record of who approved what, free rollback. The preview deployment lets the
DP see the site as it will look rather than read a diff.

**Vercel over GitHub Pages** solely for per-PR preview deployments. Pages
works if ESSEC IT requires it; you lose the preview link.

~350–400 lines total. No backend, no CMS, no accounts, no framework.

---

## 9. Rendering

| Page | Content |
|---|---|
| `/fr/` `/en/` — le fil | Reverse-chronological claims. Each post: quote → position → contexte → source link, date, tier |
| `/fr/grille` | Persons × six axes. Cells show position + receipt, or *"aucune position identifiée"* |
| `/fr/personne/<slug>` | All claims for one person, by axis |
| `/fr/methodologie` | Sources, classification rules, exclusions, cadence, GDPR basis |
| `/fr/corrections` | Public dated correction log |
| `/fr/mentions-legales` | DP, publisher, host, contact, droit de réponse procedure |

Every claim shows `last_verified`. Position changes append rather than
overwrite, so *"position on compute sovereignty changed in Nov 2026"* is
free by April 2027 — likely the most valuable output of the project.

### Bilingual rules

`quote_fr` is never translated. On `/en/` it is shown in French with
`quote_gloss_en` beside it, explicitly marked as a translation:

> « un pourcentage de souveraineté applicable à tout logiciel »
> *[trans.] a sovereignty percentage applicable to any software*

Receipt preserved, still readable. `hreflang` on every page.

---

## 10. Legal

| Requirement | Basis | Implementation |
|---|---|---|
| Mentions légales, named DP | LCEN art. 6 | Static page |
| Lawful basis for political opinions | GDPR art. 9(2)(e) — manifestly made public | Stated in méthodologie; own-timelines-only rule |
| Droit de réponse | LCEN art. 6-IV, décret 2007-1527 — 3-month window, 3-day response | Contact address + documented procedure |
| No propaganda from the eve of the vote | Code électoral art. L. 49 | **Publication freeze J-2 → close of polls, both rounds.** One cron condition |
| Press copyright | — | Short quote + link, never republication |

---

## 11. Cadence

Daily fetch. Review each morning. Publish on merge.

**Publication cadence is bounded by editorial review, not by the cron.**
Going faster means dropping the human gate, which is the credibility
premise. The bottleneck is the feature.

---

## 12. Costs

| Item | Cost |
|---|---|
| Extraction, batched (`gpt-5.6-luna` default; Opus 5 would be ~$41) | ~$1.45/month |
| X API (~20 people × ~30 posts/day @ $0.005/read) | ~$90/month |
| Hosting (Vercel), GitHub Actions | Free tier |
| Human verification of video quotes | ~10 min/week |
| **Total** | **~$92/month** |

---

## 13. Deferred

- **Chatbot.** Explicitly out of scope. The claims table with per-claim
  source links is exactly the corpus a RAG chatbot would need, so nothing
  here forecloses it — it stays unbuilt until asked for.
- Seventh axis (*IA & enseignement supérieur*) if the material warrants it.
- Programme PDFs at scale — most land Jan–Mar 2027; the `pdf` source type
  ships now and absorbs them without change.
