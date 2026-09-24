# Observatoire IA — Présidentielle 2027

Outil d'analyse des positions des candidats à l'élection présidentielle française de 2027
sur les sujets liés à l'intelligence artificielle.

Le pipeline collecte des contenus publics, les attribue à un candidat, les annote par
dimension, en calcule un indicateur de positionnement et produit un rapport traçable.

> **Statut : POC.** Périmètre réduit à 5 candidats, 3 dimensions et 5 sources.
> Aucun chiffre produit à ce stade n'a vocation à être publié.

---

## Principes

1. **Traçabilité avant tout.** Aucun score sans les passages qui le justifient, avec URL et
   date de collecte.
2. **Neutralité.** Les axes de positionnement sont descriptifs, jamais normatifs. Tous les
   candidats sont traités avec les mêmes sources et les mêmes règles.
3. **Prudence statistique.** En dessous d'un seuil de segments, on affiche « données
   insuffisantes » plutôt qu'un chiffre.
4. **Le LLM assiste, il ne décide pas.** Un échantillon des annotations est relu par des
   humains de sensibilités différentes.

---

## Architecture

Architecture hexagonale. Les dépendances pointent toujours vers l'intérieur : les adapters
connaissent le domaine, le domaine ne connaît personne.

```
┌──────────────────────────────────────────────────────────────────┐
│                          ADAPTERS                                │
│  RSS · HTML · Trafilatura · SQLite · Mistral · Fake · Rendu      │
└───────────────────────────┬──────────────────────────────────────┘
                            │ implémentent les Protocols
┌───────────────────────────▼──────────────────────────────────────┐
│                        APPLICATION                               │
│  collect_daily → annotate_documents → compute_scores → report    │
└───────────────────────────┬──────────────────────────────────────┘
                            │ dépendent des Protocols
┌───────────────────────────▼──────────────────────────────────────┐
│                          DOMAIN                                  │
│  Modèles · Ports · Scoring (fonctions pures) · Erreurs           │
│  Aucune dépendance externe                                       │
└──────────────────────────────────────────────────────────────────┘
```

### Le pipeline

```
 Sources          Collecte           Traitement          Analyse            Restitution
┌─────────┐     ┌───────────┐     ┌─────────────┐     ┌────────────┐     ┌───────────┐
│ RSS     │     │ fetch     │     │ extraction  │     │ dimension  │     │ scores    │
│ Sites   │ ──► │ robots    │ ──► │ segmentation│ ──► │ position   │ ──► │ rapport   │
│ Officiel│     │ dédup     │     │ attribution │     │ sentiment  │     │ md / html │
└─────────┘     └───────────┘     └─────────────┘     └────────────┘     └───────────┘
                      │                   │                  │                 │
                      └─────────── SQLite (traçabilité, hash, horodatage) ─────┘
```

### Niveaux de source

| Niveau | Contenu | Usage |
|---|---|---|
| 1 | Paroles propres du candidat (programme, discours, comptes officiels) | Alimente les scores |
| 2 | Parti et équipe de campagne | Alimente, pondération réduite |
| 3 | Médias, si citation directe attribuée | Alimente sous condition |
| 4 | Analyses et commentaires de tiers | Contexte seulement |

---

## Structure des dossiers

```
observatoire-ia-2027/
├── CLAUDE.md                   # règles de codage pour Claude Code
├── PROMPT_BOOTSTRAP.md         # instruction de génération du squelette
├── pyproject.toml
├── Makefile
├── .env.example
│
├── config/                     # tout le paramétrage métier, aucun code
│   ├── candidates.yaml         # candidats, alias, sources officielles
│   ├── sources.yaml            # flux et sites, avec niveau de confiance
│   ├── taxonomy.yaml           # dimensions, définitions, axes
│   └── scoring.yaml            # pondérations, seuils
│
├── src/observatoire/
│   ├── domain/                 # modèles, ports, scoring pur, erreurs
│   ├── application/            # les 4 cas d'usage
│   ├── adapters/
│   │   ├── sources/            # rss, page html, fixtures
│   │   ├── extraction/         # trafilatura, repli LLM
│   │   ├── llm/                # mistral, fake, prompts versionnés
│   │   ├── storage/            # sqlite
│   │   └── reporting/          # markdown, html
│   ├── services/               # dédup, segmentation, matcher, robots
│   ├── config/                 # settings, chargement des YAML
│   ├── observability/          # logs, compteur de tokens
│   └── cli.py                  # composition root
│
├── tests/
│   ├── unit/                   # domaine et cas d'usage, sans réseau
│   ├── integration/            # pipeline complet sur fixtures
│   └── fixtures/               # RSS, HTML, réponses LLM figées
│
├── data/                       # ignoré par git
│   ├── raw/ processed/ reports/
│
└── docs/
    ├── architecture.md
    ├── methodology.md          # codebook et règles de scoring
    └── adr/                    # décisions d'architecture
```

---

## Démarrage rapide

```bash
git clone <repo> && cd observatoire-ia-2027
make install                 # environnement et dépendances
cp .env.example .env         # la clé Mistral n'est pas requise pour la démo
make demo                    # pipeline complet hors ligne sur fixtures
open data/reports/latest.html
```

Avec des sources réelles :

```bash
export MISTRAL_API_KEY=...
export LLM_PROVIDER=mistral
observatoire run-all --since 2026-09-01
observatoire usage           # tokens consommés et coût estimé
```

---

## Commandes

| Commande | Rôle |
|---|---|
| `observatoire collect` | Récupère les contenus, dédoublonne, stocke avec provenance |
| `observatoire annotate` | Segmente et annote par dimension, position, sentiment |
| `observatoire score` | Calcule l'indicateur par candidat et par dimension |
| `observatoire report` | Produit le rapport Markdown ou HTML |
| `observatoire run-all` | Enchaîne les quatre étapes |
| `observatoire usage` | Consommation de tokens par étape |
| `make check` | ruff, mypy strict, pytest, couverture |

---

## L'indicateur

Cinq composantes, publiées séparément plutôt qu'agrégées en un chiffre unique opaque :

| Composante | Question | Mesure |
|---|---|---|
| Orientation | Où se situe le candidat sur l'axe ? | Moyenne pondérée des positions, de −2 à +2 |
| Saillance | En parle-t-il ? | Part de la parole, normalisée |
| Concrétude | Est-il précis ? | Part de propositions chiffrées ou datées |
| Cohérence | Tient-il la même ligne ? | Inverse de la variance dans le temps |
| Tonalité | Sur quel ton ? | Sentiment moyen |

Le calcul vit dans `domain/scoring.py`, en fonctions pures et déterministes, et les
pondérations dans `config/scoring.yaml`.

---

## Conformité

- Respect de `robots.txt`, user-agent identifiable, limitation de débit par domaine.
- Priorité aux flux RSS et aux API officielles sur le crawl de pages.
- Collecte limitée aux prises de parole des candidats et de leurs partis. Aucun
  commentaire d'internaute, aucune donnée personnelle de tiers.
- Les opinions politiques relèvent des données sensibles au sens du RGPD : le cadre
  juridique doit être validé par un juriste avant toute publication.
- Méthodologie et codebook publiés avec le rapport.

---

## Feuille de route après le POC

1. Élargir à 10 candidats, 9 à 11 dimensions, 40 sources.
2. Ajouter la transcription audio et vidéo, et l'OCR des programmes en PDF.
3. Mettre en place l'annotation humaine et la mesure d'accord inter-annotateurs.
4. Orchestration quotidienne planifiée et supervision.
5. Audit de biais, relecture pluraliste, puis publication.
