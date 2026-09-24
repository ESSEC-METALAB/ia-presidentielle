# ADR 0001 — La branche `archi` est une version autonome

- **Statut** : accepté
- **Date** : 2026-09-24

## Contexte

`PROMPT_BOOTSTRAP.md` suppose un dépôt vide. Le dépôt `ia-presidentielle` porte déjà, sur
la branche `daily`, un pipeline en service : un paquet `observatoire/`, sa base SQLite
commitée, sa configuration `sources.yaml` et un workflow quotidien. Un premier essai a
placé ce POC dans un sous-dossier, à côté de ce pipeline.

## Décision

La branche `archi` ne contient que cette nouvelle version, à la racine. Le pipeline
précédent en a été retiré par un commit, sans réécrire l'historique : il reste intact sur
`daily`.

## Conséquences

- L'arbre ne contient plus qu'un paquet `observatoire` : le mélange entre les deux
  versions, possible avec le sous-dossier, ne l'est plus.
- Les décisions de la version précédente qui contredisent celle-ci sont listées dans
  [`docs/methodology.md`](../methodology.md), « Questions ouvertes ».
- L'historique commun avec `daily` est conservé : les deux branches restent comparables.
