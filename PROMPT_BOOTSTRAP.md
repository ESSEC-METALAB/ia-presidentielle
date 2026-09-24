# PROMPT_BOOTSTRAP.md — Instruction de démarrage pour Claude Code

Copier-coller le bloc ci-dessous dans Claude Code, à la racine d'un dépôt vide contenant
déjà `CLAUDE.md`.

---

## Prompt à donner

> Tu vas créer le squelette d'un projet Python. Lis d'abord `CLAUDE.md` : il contient les
> règles d'architecture et de style, et elles priment sur tes habitudes par défaut.
>
> **Objectif** : un POC fonctionnel de bout en bout en une semaine. Un squelette qui tourne
> vraiment sur un périmètre réduit vaut mieux qu'une architecture complète non exécutable.
> Chaque étape du pipeline doit exister, être branchée aux suivantes, et être testable.
>
> **Périmètre volontairement réduit du POC**
> - 5 candidats seulement, définis dans `config/candidates.yaml`
> - 3 dimensions seulement (regulation, sovereignty, environment), dans `config/taxonomy.yaml`
> - 5 sources RSS, définies dans `config/sources.yaml`
> - Stockage SQLite, pas de base externe
> - Deux implémentations du port LLM : `MistralClient` (réel) et `FakeLLMClient`
>   (déterministe, utilisé par défaut et dans tous les tests)
> - Rapport en Markdown et en HTML statique, pas de dashboard
>
> **Contrainte structurante** : `make demo` doit produire un rapport complet à partir des
> fixtures locales, **sans réseau ni clé API**, en moins de deux minutes. C'est le critère
> qui prouve que l'architecture tient debout.
>
> **Procède dans cet ordre**, en t'arrêtant après chaque étape pour que je valide :
>
> 1. Arborescence, `pyproject.toml`, `Makefile`, `.env.example`, `.gitignore`, README.
> 2. `domain/` : modèles Pydantic et Protocols. Aucune implémentation.
> 3. `application/` : les 4 cas d'usage, avec injection de dépendances, testés avec des fakes.
> 4. `adapters/` : RSS, extraction HTML, SQLite, FakeLLM, Mistral, rendu Markdown et HTML.
> 5. `cli.py` : composition root et commandes.
> 6. Tests, fixtures, et `make demo` qui passe.
>
> Ne génère pas de code métier « en avance ». Les fonctions non implémentées lèvent
> `NotImplementedError` avec un TODO explicite. Je préfère dix fichiers justes et vides à
> trois fichiers pleins et faux.

---

## Arborescence cible

```
observatoire-ia-2027/
├── CLAUDE.md
├── PROMPT_BOOTSTRAP.md
├── README.md
├── pyproject.toml
├── Makefile
├── .env.example
├── .gitignore
│
├── config/
│   ├── candidates.yaml        # registre des candidats et de leurs sources officielles
│   ├── sources.yaml           # sites et flux à collecter, avec niveau de confiance
│   ├── taxonomy.yaml          # dimensions, définitions, axes de positionnement
│   └── scoring.yaml           # pondérations et seuils de l'indicateur
│
├── src/observatoire/
│   ├── domain/                # aucune dépendance externe
│   │   ├── models.py          # Candidate, Source, RawDocument, Segment,
│   │   │                      # DimensionAnnotation, DimensionScore, RunReport
│   │   ├── ports.py           # Protocols : SourceReader, TextExtractor, CandidateMatcher,
│   │   │                      # DocumentRepository, LLMClient, Annotator,
│   │   │                      # ScoreCalculator, ReportRenderer, Clock, UsageTracker
│   │   ├── scoring.py         # fonctions pures : orientation, salience, concreteness,
│   │   │                      # consistency, tone, intervalle de confiance
│   │   └── errors.py
│   │
│   ├── application/
│   │   ├── collect_daily.py       # sources -> documents bruts dédoublonnés
│   │   ├── annotate_documents.py  # documents -> segments -> annotations
│   │   ├── compute_scores.py      # annotations -> scores par candidat et dimension
│   │   └── generate_report.py     # scores -> rapport
│   │
│   ├── adapters/
│   │   ├── sources/
│   │   │   ├── rss_reader.py
│   │   │   ├── html_page_reader.py
│   │   │   └── fixture_reader.py       # lit tests/fixtures, mode hors ligne
│   │   ├── extraction/
│   │   │   ├── trafilatura_extractor.py
│   │   │   └── llm_fallback_extractor.py
│   │   ├── llm/
│   │   │   ├── mistral_client.py
│   │   │   ├── fake_llm_client.py
│   │   │   └── prompts/                # prompts versionnés, un fichier par tâche
│   │   │       ├── classify_dimension.v1.md
│   │   │       ├── detect_stance.v1.md
│   │   │       └── extract_proposals.v1.md
│   │   ├── storage/
│   │   │   ├── sqlite_repository.py
│   │   │   └── schema.sql
│   │   └── reporting/
│   │       ├── markdown_renderer.py
│   │       └── html_renderer.py
│   │
│   ├── services/
│   │   ├── dedup.py               # hash de contenu, normalisation
│   │   ├── segmentation.py        # découpage en unités argumentatives
│   │   ├── candidate_matcher.py   # attribution d'un passage à un candidat
│   │   └── robots_policy.py       # robots.txt, débit, user-agent
│   │
│   ├── config/
│   │   ├── settings.py            # variables d'environnement, Pydantic Settings
│   │   └── registry.py            # chargement et validation des YAML
│   │
│   ├── observability/
│   │   ├── logging.py
│   │   └── usage_tracker.py       # compteur de tokens et estimation de coût
│   │
│   └── cli.py                     # composition root
│
├── tests/
│   ├── unit/                      # domaine et cas d'usage, avec fakes
│   ├── integration/               # pipeline complet sur fixtures
│   └── fixtures/                  # RSS, HTML et réponses LLM figées
│
├── data/                          # ignoré par git
│   ├── raw/  processed/  reports/
│
└── docs/
    ├── architecture.md
    ├── methodology.md             # codebook, axes, règles de scoring
    └── adr/                       # décisions d'architecture, une par fichier
```

---

## Ports à définir dans `domain/ports.py`

| Port | Signature attendue | Adapters du POC |
|---|---|---|
| `SourceReader` | `fetch(source, since) -> Iterable[RawDocument]` | RSS, page HTML, fixtures |
| `TextExtractor` | `extract(html) -> str` | Trafilatura, repli LLM |
| `CandidateMatcher` | `match(text) -> list[CandidateRef]` | règles + alias YAML |
| `DocumentRepository` | `save`, `exists`, `list_by_status` | SQLite |
| `LLMClient` | `complete(prompt, schema) -> LLMResponse` | Mistral, Fake |
| `Annotator` | `annotate(segment) -> list[DimensionAnnotation]` | LLM, Fake |
| `ScoreCalculator` | `compute(annotations) -> DimensionScore` | fonctions pures |
| `ReportRenderer` | `render(scores, metadata) -> str` | Markdown, HTML |
| `Clock` | `now() -> datetime` | système, figée |
| `UsageTracker` | `record(model, tokens_in, tokens_out)` | en mémoire, JSONL |

---

## Commandes CLI attendues

```bash
observatoire collect   --since 2026-09-01 [--source-id ...] [--offline]
observatoire annotate  --limit 100 [--llm fake|mistral]
observatoire score     --as-of 2026-09-25
observatoire report    --format md|html --out data/reports/
observatoire run-all   --offline          # le pipeline complet
observatoire usage                        # tokens consommés et coût estimé
```

---

## Plan sur cinq jours

| Jour | Livrable | Critère de fin |
|---|---|---|
| 1 | Squelette, config, domaine (modèles + ports) | `make check` passe, imports valides |
| 2 | Collecte : RSS, fixtures, dédup, SQLite | `collect --offline` remplit la base |
| 3 | Annotation : segmentation, FakeLLM, prompts v1 | `annotate` produit des annotations tracées |
| 4 | Scoring et rapport Markdown et HTML | `run-all --offline` produit un rapport lisible |
| 5 | Adapter Mistral réel, tests, README, compteur de tokens | `run-all` sur 5 sources réelles |

Marge des jours 6 et 7 : revue de code, correction, et première relecture humaine des
annotations sur un échantillon de 50 segments.

---

## Critères d'acceptation du POC

1. `make demo` produit un rapport complet hors ligne en moins de deux minutes.
2. `make check` passe : `ruff`, `mypy --strict`, `pytest`, couverture ≥ 80 % sur le domaine.
3. Chaque score du rapport affiche son nombre de segments sources et au moins une citation
   avec URL et date de collecte.
4. Ajouter une sixième source ne demande qu'une entrée dans `config/sources.yaml`, sans
   toucher au code.
5. Basculer de `FakeLLMClient` à `MistralClient` se fait par une variable d'environnement,
   sans modifier un cas d'usage.
6. La commande `usage` affiche les tokens consommés par étape.
7. Aucune requête n'est émise vers un domaine interdit par son `robots.txt`.
