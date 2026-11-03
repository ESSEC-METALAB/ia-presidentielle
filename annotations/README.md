# Annotations enregistrées

Réponses d'annotation versionnées : ce sont la provenance des déclarations du registre.
`make site` les rejoue hors ligne, à travers les mêmes contrôles qu'un appel en direct
(`docs/methodology.md`, « Repérage et classement »).

| Fichier | Contenu |
|---|---|
| `2026-11-03-brouillon-brut.jsonl` | Réponses de l'annotateur, telles quelles : une ligne par requête (117), identifiée par l'empreinte de la consigne et du passage |
| `2026-11-03-brouillon.jsonl` | Les mêmes après vérification croisée : 6 déclarations écartées, 1 axe changé, 45 notes corrigées. C'est ce fichier que rejoue `make annotate-replay` |
| `2026-11-03-verification.json` | Les règles appliquées, puis chaque déclaration : votes et raisons des vérificateurs, issue, modifications avant/après |

L'annotateur et les vérificateurs de cette édition sont des assistants (Claude Code),
pas Mistral ni des éditeurs : aucune déclaration n'a encore été relue par une personne.

Une réponse n'est rejouée que si la requête est identique, consigne, axes et passage
compris. Un passage modifié depuis, ou une nouvelle version de consigne, n'a pas de
réponse : il est annoté à nouveau (`observatoire annotate`).
