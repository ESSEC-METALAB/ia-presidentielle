# Architecture

Architecture hexagonale (ports et adapters). Les règles sont dans [`CLAUDE.md`](../CLAUDE.md),
§2 et §3 ; ce document dit où elles sont vérifiées.

## Couches

| Couche | Dossier | Peut importer |
|---|---|---|
| Domaine | `src/observatoire/domain/` | la bibliothèque standard hors E/S, `pydantic`, le domaine |
| Application | `src/observatoire/application/` | tout sauf `adapters/` et `cli.py` |
| Adapters | `src/observatoire/adapters/` | le domaine |
| Composition | `src/observatoire/cli.py` | tout : seul endroit où l'on instancie et câble |

Ces règles sont vérifiées sur le code source par `tests/unit/test_architecture.py`, qui
tourne dans `make check`. Une violation fait donc échouer la vérification avant qu'un
comportement ne repose dessus.

## Pipeline

`collect_daily` → `annotate_documents` → `compute_scores` → `generate_report`, chacun
recevant ses dépendances par son constructeur. Détail des ports et des adapters du POC :
[`PROMPT_BOOTSTRAP.md`](../PROMPT_BOOTSTRAP.md).

### Ce qui est implémenté : collecte et corpus brut

| Commande | Cas d'usage | Adapters câblés dans `cli.py` |
|---|---|---|
| `observatoire collect` | `CollectDaily` | `RssReader`, `HtmlPageReader`, `PdfReader`, `AssembleeNationaleReader`, tous derrière `PoliteHttpClient` (robots.txt, délai par site, agent identifié) |
| `observatoire import-legacy` | `CollectDaily` | `LegacyPipelineReader` : la base de la version précédente (branche `daily`) |
| `observatoire segment` | `SegmentDocuments` | `ParagraphSegmenter` (règles de `config/segmentation.yaml`), `AliasMatcher`, `SqliteRepository` |
| `observatoire corpus` | `InspectCorpus` | `SqliteRepository`, `AliasMatcher`, `CorpusHtmlRenderer` |

`collect` et `import-legacy` exécutent le **même** cas d'usage avec des lecteurs
différents : même clé de dédoublonnage, même stockage, même vue. Ajouter un type de source,
c'est ajouter un lecteur dans `adapters/sources/` et l'enregistrer dans `cli.py`, sans
toucher à `application/`.

La segmentation ne modifie jamais un document : elle enregistre, pour chacun, ses segments
(avec leurs plages de caractères dans le texte collecté) et ses passages écartés (avec leur
motif). La version du segmenteur est l'empreinte de ses règles et de ses réglages : en
changer redécoupe le corpus au prochain `observatoire segment`, sinon rien n'est refait.

Annotation, scores et rapport restent à écrire : ils attendent les décisions de
[`methodology.md`](methodology.md).

## Version précédente

La branche `archi` ne contient que cette version. Le pipeline précédent reste sur la
branche `daily`. Voir [ADR 0001](adr/0001-archi-version-autonome.md).
