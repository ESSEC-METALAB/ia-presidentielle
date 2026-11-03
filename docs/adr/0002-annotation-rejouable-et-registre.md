# ADR 0002 — Annotation rejouable, et un registre sans score

- **Statut** : accepté
- **Date** : 2026-11-03

## Contexte

Le pipeline devait passer du corpus découpé à quelque chose de lisible : le prototype de
site « IA 2027 — Registre » (v3), fourni par l'équipe, affiche des déclarations mot pour
mot sur neuf axes et s'interdit « score, note, classement, indicateur de tonalité ». Le
README de ce POC prévoit, lui, une orientation chiffrée et une tonalité.

L'API Mistral n'est pas joignable depuis l'environnement de développement. Les sites des
candidats ne le sont pas non plus.

## Décision

1. **Le registre suit le prototype.** L'annotation rattache une déclaration à un axe,
   avec sa citation exacte et un résumé descriptif. Pas d'orientation, pas de tonalité :
   `observatoire score` reste non implémenté.
2. **Une seule chaîne d'annotation, quel que soit le fournisseur.** Un `LLMClient` répond ;
   l'`LLMAnnotator`, les contrôles (`AnnotationGates`) et le stockage sont les mêmes pour
   Mistral, le faux client et les réponses enregistrées.
3. **Annotation en deux temps possible.** `--llm batch` écrit les requêtes exactes (format
   batch, identifiées par l'empreinte de la consigne et du passage) sans rien stocker ;
   `--llm recorded` rejoue des réponses par identifiant. Le fichier de réponses est
   versionné : c'est la provenance des annotations, et il permet de reconstruire le
   registre hors ligne (`make site`).
4. **Le modèle ne rapporte jamais la provenance**, et la citation enregistrée est le
   texte de la source localisé par le code, pas la copie du modèle.

## Conséquences

- Basculer vers Mistral ne change aucun cas d'usage : `LLM_PROVIDER=mistral` et une clé.
  Le premier appel réel reste à faire ; l'adapter a été écrit d'après la documentation
  et testé contre une réponse simulée.
- L'édition du 3 novembre 2026 a été annotée hors ligne par un assistant, avec la même
  consigne et le même schéma ; elle est marquée comme brouillon non relu sur le site et
  dans `docs/methodology.md`.
- Une modification de la consigne, des axes ou d'un passage invalide les réponses
  enregistrées correspondantes : elles ne sont pas rejouées, le passage est réannoté.
- La question ouverte n° 1 de `docs/methodology.md` (score et tonalité) est tranchée pour
  ce qui est publié ; elle reste ouverte pour une analyse interne.
