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

Le pipeline existant à la racine du dépôt a pris des décisions contraires sur certains
points. Elles sont à trancher explicitement avant toute publication :

1. **Score et tonalité.** La spécification du pipeline existant
   (`../docs/superpowers/specs/2026-09-17-essec-ia-2027-design.md`, §1 « Non-goals ») exclut
   tout score, classement et analyse de sentiment, au motif qu'un score est une évaluation
   et qu'une évaluation d'un candidat publiée sous le nom d'ESSEC est le risque de
   neutralité principal. L'indicateur de ce POC comprend une orientation chiffrée et une
   tonalité.
2. **Presse (niveau 3).** Le pipeline existant n'en tire jamais une position, même avec
   une citation propre ; il s'en sert seulement comme piste. Ce POC l'admet sous
   condition de citation directe attribuée.
3. **Date de publication.** Le pipeline existant ne devine jamais une date absente
   (trafilatura invente un 1er janvier par défaut) et affiche « date non précisée ». Ce POC
   trace la date de collecte ; la date de publication reste à modéliser, et doit pouvoir
   être absente.
