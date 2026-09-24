# CLAUDE.md — Règles de travail sur ce dépôt

Ce fichier est lu automatiquement par Claude Code. Il définit **comment** on code ici.
Le quoi (le périmètre du POC) est dans `PROMPT_BOOTSTRAP.md`.

---

## 1. Contexte du projet

Observatoire des positions des candidats à l'élection présidentielle française de 2027
sur les sujets liés à l'intelligence artificielle.

Le pipeline : collecter chaque matin des contenus publics → les attribuer à un candidat →
les annoter par dimension (régulation, souveraineté, environnement, emploi, formation,
services publics, surveillance et libertés, financement, sécurité de l'IA) → calculer un
indicateur par candidat et par dimension → produire un rapport.

**Exigence non négociable : neutralité et traçabilité.** Toute donnée affichée dans un
rapport doit pouvoir être remontée jusqu'à son URL source, sa date de collecte et le
passage exact qui la justifie. Pas de score sans preuve.

---

## 2. Architecture : hexagonale (ports & adapters)

Trois couches, dépendances **toujours** dirigées vers l'intérieur :

```
adapters  ──dépend de──►  application  ──dépend de──►  domain
(monde extérieur)         (cas d'usage)                (règles métier)
```

- `domain/` : entités et **interfaces** (`typing.Protocol`). Aucune dépendance externe.
  Interdit d'y importer `requests`, `mistralai`, `sqlite3`, `feedparser`, etc.
- `application/` : les cas d'usage. Orchestrent le domaine. Reçoivent leurs dépendances
  par injection dans le constructeur. Ne connaissent aucune implémentation concrète.
- `adapters/` : tout ce qui touche au monde réel (HTTP, LLM, base, fichiers, rendu).
  Chaque adapter implémente un Protocol du domaine.
- `cli.py` est le **composition root** : c'est le seul endroit où l'on instancie les
  implémentations concrètes et où on les câble.

---

## 3. SOLID, appliqué concrètement ici

**S — Responsabilité unique.**
Un module = une raison de changer. Un collecteur collecte, il n'annote pas. Un annotateur
annote, il n'écrit pas en base. Si une classe a « et » dans sa description, la scinder.

**O — Ouvert/fermé.**
Ajouter une nouvelle source (RSS, sitemap, API, PDF) ou un nouveau fournisseur de LLM doit
se faire en **ajoutant** un fichier dans `adapters/`, jamais en modifiant un cas d'usage.
Si tu te retrouves à ajouter un `if source_type == "..."` dans `application/`, c'est un
signal : il faut un nouvel adapter et une entrée dans le registre.

**L — Substitution de Liskov.**
`FakeLLMClient` doit être interchangeable avec `MistralClient` sans changer un seul test
du domaine. Les tests unitaires tournent **sans réseau et sans clé API**.

**I — Ségrégation des interfaces.**
Des Protocols petits et ciblés : `SourceReader`, `DocumentRepository`, `LLMClient`,
`Annotator`, `ScoreCalculator`, `ReportRenderer`. Jamais un `IService` fourre-tout.
Un consommateur ne doit pas dépendre de méthodes qu'il n'appelle pas.

**D — Inversion des dépendances.**
Les cas d'usage dépendent des Protocols, pas des classes concrètes. Toute dépendance
arrive par le constructeur. Aucun `import` d'adapter dans `application/`.

---

## 4. Règles de clean code

**Typage.** Tout est annoté. `mypy --strict` doit passer. Modèles de données en Pydantic v2,
frozen quand c'est possible. Pas de `dict[str, Any]` qui traverse les couches : on parse
tôt, on valide tôt.

**Fonctions.** Courtes (viser moins de 30 lignes), un seul niveau d'abstraction par
fonction, maximum 4 paramètres positionnels. Retour anticipé plutôt qu'imbrication.

**Nommage.** Code, identifiants, docstrings et commentaires **en anglais**.
Contenu destiné aux utilisateurs (rapports, libellés, documentation) **en français**.
Noms explicites : `fetch_articles_since`, pas `get_data`. Pas d'abréviations maison.

**Pureté.** Le calcul des scores est composé de fonctions pures et déterministes :
mêmes annotations en entrée = mêmes scores en sortie. Aucun appel réseau, aucune horloge
implicite. Le temps arrive par un port `Clock`.

**Configuration.** Zéro valeur magique dans le code. Les seuils, pondérations, listes de
sources, candidats et dimensions vivent dans `config/*.yaml`. Les secrets dans `.env`,
jamais commités, chargés via `settings.py`.

**Erreurs.** Exceptions métier dans `domain/errors.py`. Une source qui échoue ne fait
jamais tomber le run entier : on log, on marque la source en échec, on continue.
Pas de `except Exception: pass`.

**Logs.** `structlog`, format JSON, un event par étape avec `run_id`, `source_id`,
`document_id`, `duration_ms`. Chaque appel LLM logue les tokens consommés en entrée et en
sortie. Jamais de secret ni de contenu intégral dans les logs.

**Idempotence.** Relancer la collecte du même jour ne doit pas créer de doublons.
Clé de déduplication = SHA-256 du texte normalisé. Chaque document stocke `source_url`,
`fetched_at`, `content_hash`.

---

## 5. Tests

- `pytest`, arrangement AAA (arrange / act / assert), un comportement testé par test.
- Le domaine et les cas d'usage se testent avec des fakes, **sans réseau**.
- Les fixtures HTML/RSS/JSON vivent dans `tests/fixtures/`, figées, versionnées.
- Couverture minimale : 80 % sur `domain/` et `application/`.
- Un test d'intégration de bout en bout qui rejoue le pipeline complet sur fixtures.
- Pas de test qui dépend de la date du jour : injecter `FrozenClock`.

---

## 6. Qualité et outillage

- Formatage et lint : `ruff format` + `ruff check`.
- Types : `mypy --strict`.
- Tout doit passer via `make check` avant de considérer une tâche terminée.
- Commits conventionnels : `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
- Python 3.11+, gestion des dépendances avec `uv` (fallback `pip` documenté).

---

## 7. Conformité — contraintes à respecter dans le code

Ces points ne sont pas décoratifs, ils doivent être **implémentés** :

1. Respect de `robots.txt` avant toute requête, via un `RobotsPolicy` centralisé.
2. User-Agent explicite et identifiable, avec une adresse de contact.
3. Limitation de débit : un délai minimal configurable entre deux requêtes sur un même
   domaine.
4. Priorité aux flux RSS et aux API officielles sur le crawl de pages HTML.
5. Aucun stockage de données personnelles de tiers : on ne collecte que les prises de
   parole des candidats et de leurs partis, pas les commentaires d'internautes.
6. Chaque score exposé porte son nombre de segments sources. En dessous du seuil configuré,
   on affiche « données insuffisantes » au lieu d'un chiffre.

---

## 8. Ce qu'il ne faut pas faire

- Ne pas mettre d'appel LLM dans la boucle de collecte : la collecte est déterministe
  (RSS, sélecteurs). Le LLM n'intervient qu'en extraction de repli, derrière un port dédié.
- Ne pas inventer d'URL, de compte social ou d'identifiant de candidat. Tout vient de
  `config/candidates.yaml` et `config/sources.yaml`.
- Ne pas coder en dur une liste de candidats dans le Python.
- Ne pas mélanger sentiment et positionnement : ce sont deux champs distincts du modèle.
- Ne pas faire remonter dans un score une information de niveau 3 ou 4 (analyse de tiers)
  sans citation directe attribuée au candidat.
- Ne pas ajouter de dépendance lourde sans nécessité (pas de framework web, pas d'ORM
  complet pour le POC).
