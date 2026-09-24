# ADR 0001 — Le POC vit dans un sous-dossier, à côté du pipeline existant

- **Statut** : proposé, à valider
- **Date** : 2026-09-24

## Contexte

`PROMPT_BOOTSTRAP.md` suppose un dépôt vide. Le dépôt `ia-presidentielle` contient déjà un
pipeline en service : un paquet `observatoire/` à la racine, sa base SQLite commitée, sa
configuration `sources.yaml` et un workflow quotidien.

## Décision

Le POC est créé dans `observatoire-ia-2027/`, avec son propre `pyproject.toml`, son
environnement virtuel et son `CLAUDE.md`. Rien à la racine n'est modifié.

## Conséquences

- Le pipeline existant continue de tourner, sans changement.
- Les deux projets déclarent un paquet `observatoire`. Ils ne se croisent pas tant que
  l'on travaille depuis `observatoire-ia-2027/` : la disposition `src/` et le venv propre
  gardent la racine hors du `sys.path`. Lancer `pytest` depuis la racine du dépôt
  mélangerait les deux.
- Remonter le POC à la racine plus tard se fait par un `git mv`, s'il remplace le pipeline
  existant.
