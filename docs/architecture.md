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

## Version précédente

La branche `archi` ne contient que cette version. Le pipeline précédent reste sur la
branche `daily`. Voir [ADR 0001](adr/0001-archi-version-autonome.md).
