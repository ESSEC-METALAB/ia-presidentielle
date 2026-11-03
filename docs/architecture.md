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

`collect_daily` → `segment_documents` → `annotate_documents` → `build_register`, plus
`watch_changes` (veille) et `inspect_corpus` (vue du corpus brut), chacun recevant ses
dépendances par son constructeur. `compute_scores` et `generate_report` restent des
squelettes : le registre public ne publie aucun score ([ADR 0002](adr/0002-annotation-rejouable-et-registre.md)).

| Commande | Cas d'usage | Adapters câblés dans `cli.py` |
|---|---|---|
| `observatoire collect` | `CollectDaily` | `RssReader`, `HtmlPageReader`, `PdfReader`, `AssembleeNationaleReader`, tous derrière `PoliteHttpClient` (robots.txt, délai par site, agent identifié) |
| `observatoire import-legacy` | `CollectDaily` | `LegacyPipelineReader` : la base de la version précédente (branche `daily`) |
| `observatoire segment` | `SegmentDocuments` | `ParagraphSegmenter` (règles de `config/segmentation.yaml`), `AliasMatcher`, `SqliteRepository` |
| `observatoire annotate` | `AnnotateDocuments` | `LLMAnnotator` sur un `LLMClient` au choix (`MistralClient`, `FakeLLMClient`, `RecordedLLMClient`, `BatchRequestWriter`), enveloppé par `UsageRecordingClient` ; `TermRelevanceFilter` et `AnnotationGates` (`config/taxonomy.yaml`) |
| `observatoire register` | `BuildRegister` | `RegisterDataScript` (le `data.js` du site), `write_site` (gabarit `web/registre/`) |
| `observatoire watch` | `WatchChanges` | `MieuxVoterRoster` (derrière `PoliteHttpClient`), `WatchMarkdown` (`config/watch.yaml`) |
| `observatoire corpus` | `InspectCorpus` | `SqliteRepository`, `AliasMatcher`, `CorpusHtmlRenderer` |
| `observatoire usage` | — | `SqliteRepository.usage_totals` |

`collect` et `import-legacy` exécutent le **même** cas d'usage avec des lecteurs
différents : même clé de dédoublonnage, même stockage, même vue. Ajouter un type de source,
c'est ajouter un lecteur dans `adapters/sources/` et l'enregistrer dans `cli.py`, sans
toucher à `application/`. De même, Mistral, le faux client et les réponses enregistrées
passent par le **même** annotateur, les mêmes contrôles et le même stockage.

La segmentation ne modifie jamais un document : elle enregistre, pour chacun, ses segments
(avec leurs plages de caractères dans le texte collecté) et ses passages écartés (avec leur
motif). La version du segmenteur est l'empreinte de ses règles et de ses réglages : en
changer redécoupe le corpus au prochain `observatoire segment`, sinon rien n'est refait.

L'annotateur est versionné par son modèle et l'empreinte de sa consigne (qui contient les
axes) : un changement réannote. Une annotation est gardée avec l'empreinte du texte du
passage, si bien qu'un passage redécoupé est réannoté. Le registre choisit, passage par
passage, l'annotation à montrer (`domain/annotation.py`, `published_annotations`) : celle
d'une édition vérifiée listée dans `config/register.yaml`, sinon celle de l'annotateur
automatique qui couvre le plus de passages actuels (les lignes de passages disparus ne
comptent pas), sinon rien : le passage est compté « en attente » pour son candidat. Le faux
annotateur ne fait que des essais à blanc (`DiscardingAnnotationStore`).

## Exploitation

`scripts/daily.sh` enchaîne les commandes chaque matin (verrou contre deux exécutions
simultanées, journal dans `data/logs/`, une étape en échec n'arrête pas les suivantes) ;
`scripts/schedule.sh` l'installe à 8 h (launchd, systemd ou cron) avec le serveur local du
site (`scripts/serve.sh`). Le site ne charge rien depuis internet : bibliothèques et
polices sont dans `web/registre/` (voir `web/registre/NOTICE.md`).

## Version précédente

La branche `archi` ne contient que cette version. Le pipeline précédent reste sur la
branche `daily`. Voir [ADR 0001](adr/0001-archi-version-autonome.md).
