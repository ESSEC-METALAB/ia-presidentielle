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

## Segmentation

Découpage léger et déterministe, sans modèle de langage (`services/segmentation.py`,
réglages dans `config/segmentation.yaml`). Un segment est un passage lisible seul ; son
texte est celui du document sur ses plages de caractères, espaces près. Rien n'est écarté
sans motif enregistré.

| Règle | Motif enregistré | Raison, mesurée sur le corpus du 4 octobre 2026 |
|---|---|---|
| Ligne de 1 à 3 chiffres | numéro de page ou de section | pagination du programme PDF ; une année seule sur sa ligne (« 2030 ») reste du texte |
| Ligne courte, sans ponctuation finale, d'au moins deux mots, répétée 3 fois dans un document | en-tête répété | titre courant du PDF ; les mots isolés par la mise en page (« la », « de ») restent |
| Même ligne courte dans au moins 3 documents d'une source | ligne répétée dans la source | bloc signature de 16 des 24 billets des Républicains, étiquettes « Communiqué du groupe LFI » |
| Tout ce qui suit « Découvrez aussi », « Lire aussi » | liens vers d'autres articles | listes d'articles liés en fin de billet |
| Ligne ouvrant sur un texte d'interface configuré | texte d'interface | bandeau de cookies du site du Parti socialiste |
| Parenthèse de didascalie, compte rendu de l'Assemblée seulement | didascalie | 403 « (Applaudissements…) », « (« Eh oui ! » sur les bancs…) » : les mots des sténographes, pas de l'orateur |
| Passage de moins de 40 caractères | trop court | 186 des 671 prises de parole sont des interjections (« Bravo ! », « C'est faux ! ») |

Les lignes d'un PDF sont réunies en paragraphes, y compris par-dessus un saut de page quand
la phrase continue. Une ligne courte d'un billet est rattachée à la ligne suivante du même
bloc (intertitres, puces). Un paragraphe de plus de 1 200 caractères est coupé entre deux
phrases, jamais au milieu. Deux prises de parole séparées dans le compte rendu ne sont
jamais fusionnées.

Résultat : 1 887 segments pour 230 documents ; 68 documents sans contenu exploitable (60 séances
faites d'interjections, 7 billets vidéo, 1 bandeau de cookies).

## Constats sur les données (import du 4 octobre 2026)

Import de la base de la version précédente : 239 documents, 230 conservés après
dédoublonnage, collectés entre le 18 septembre et le 4 octobre 2026.

- **Bandeau de cookies pris pour un article.** Cinq documents du fil du Parti socialiste
  contiennent le texte du bandeau de consentement (« Nous utilisons des cookies… ») au lieu
  de l'article. Le dédoublonnage en élimine quatre ; la segmentation écarte le dernier comme
  texte d'interface. L'extraction de `parti-socialiste.fr` est à revérifier dès que le
  réseau le permet : l'article lui-même n'a jamais été collecté.
- **Billets sans texte.** 7 des 24 billets du fil des Républicains ne contiennent que leur
  titre, la signature et les liens associés : l'article est une vidéo. Ils restent dans le
  corpus, marqués « aucun passage exploitable ».
- **Séances sans prise de position.** Dans 60 séances, la seule intervention du candidat est
  une interjection (43 pour Gabriel Attal, 17 pour Marine Le Pen).
- **Questions des journalistes.** Les entretiens publiés sur le site des Républicains
  contiennent les questions (« Le JDD. … ? ») : ces segments ne sont pas les mots du
  candidat. À traiter avant l'annotation (étiquette d'orateur ou relecture).
- **Graphique du programme PDF.** Les valeurs d'un graphique (« 2,5 3,3 7 18 31… »)
  subsistent comme texte dans un segment : le PDF n'a pas de couche qui les distingue.
- **Zéro intervention pour Olivier Faure et Bruno Retailleau** dans le compte rendu de la
  XVIIe législature, déjà le 4 octobre dans la version précédente. Pour Bruno Retailleau,
  c'est attendu (interventions ministérielles terminées, retour au Sénat) ; pour Olivier
  Faure, l'identifiant d'acteur PA609332 est à revérifier.
- **Jordan Bardella n'est pas suivi** : aucune source vérifiée. Député européen, son compte
  rendu est celui du Parlement européen.
- Les fils de parti (niveau 2) publient l'actualité de tout le parti : la vue indique pour
  chaque document s'il cite le candidat.
