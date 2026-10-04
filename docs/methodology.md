# Méthodologie

Codebook, axes de positionnement et règles de calcul de l'indicateur. Ce document est
publié avec chaque rapport (README, « Conformité »).

> **État : à rédiger.** Les sections ci-dessous sont remplies à mesure que les décisions
> sont prises. Aucun chiffre n'est calculé tant que la section correspondante est vide.

## Périmètre

À définir : les cinq candidats du POC et la raison de ce choix.

## Dimensions et axes

À définir, dans `config/taxonomy.yaml` : pour `regulation`, `sovereignty` et `environment`,
une définition et les deux pôles de l'axe, formulés de façon descriptive.

## Niveaux de source

Repris du README. À préciser : ce qu'est une « citation directe attribuée » pour qu'une
source de niveau 3 alimente un score.

## Indicateur

À définir, dans `config/scoring.yaml` : pondération par niveau de source, seuil de
segments sous lequel on affiche « données insuffisantes », intervalle de confiance.

## Relecture humaine

À définir : taille de l'échantillon, profil des relecteurs, mesure d'accord.

## Questions ouvertes

La version précédente (branche `daily`) a pris des décisions contraires sur certains
points. Elles sont à trancher explicitement avant toute publication :

1. **Score et tonalité.** La spécification de la version précédente
   (branche `daily`, `docs/superpowers/specs/2026-09-17-essec-ia-2027-design.md`,
   §1 « Non-goals ») exclut
   tout score, classement et analyse de sentiment, au motif qu'un score est une évaluation
   et qu'une évaluation d'un candidat publiée sous le nom d'ESSEC est le risque de
   neutralité principal. L'indicateur de ce POC comprend une orientation chiffrée et une
   tonalité.
2. **Presse (niveau 3).** La version précédente n'en tire jamais une position, même avec
   une citation propre ; il s'en sert seulement comme piste. Ce POC l'admet sous
   condition de citation directe attribuée.
3. **Date de publication.** Réglé : comme la version précédente, ce POC ne devine jamais
   une date absente (`RawDocument.published_on` peut être vide, l'extraction désactive la
   recherche heuristique de trafilatura) et la vue affiche « date non précisée ».
4. **Dédoublonnage par le seul texte.** La clé imposée par `CLAUDE.md` (SHA-256 du texte
   normalisé) fusionne deux interventions identiques prononcées dans deux séances
   différentes : sur les données de la version précédente, cinq séances où Gabriel Attal n'a
   dit que « Bravo ! », « Très bien ! » ou « Merci ! » sont ramenées à deux. Sans effet sur
   les positions, mais le nombre de séances est sous-estimé. Option : inclure l'URL de la
   source dans la clé.

## Constats sur les données (import du 4 octobre 2026)

Import de la base de la version précédente : 239 documents, 230 conservés après
dédoublonnage, collectés entre le 18 septembre et le 4 octobre 2026.

- **Bandeau de cookies pris pour un article.** Cinq documents du fil du Parti socialiste
  contiennent le texte du bandeau de consentement (« Nous utilisons des cookies… ») au lieu
  de l'article. Le dédoublonnage en élimine quatre ; il en reste un. L'extraction de
  `parti-socialiste.fr` est à revérifier dès que le réseau le permet.
- **Zéro intervention pour Olivier Faure et Bruno Retailleau** dans le compte rendu de la
  XVIIe législature, déjà le 4 octobre dans la version précédente. Pour Bruno Retailleau,
  c'est attendu (interventions ministérielles terminées, retour au Sénat) ; pour Olivier
  Faure, l'identifiant d'acteur PA609332 est à revérifier.
- **Jordan Bardella n'est pas suivi** : aucune source vérifiée. Député européen, son compte
  rendu est celui du Parlement européen.
- Les fils de parti (niveau 2) publient l'actualité de tout le parti : la vue indique pour
  chaque document s'il cite le candidat.
