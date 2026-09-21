Revue éditoriale du matin.

**À relire : `data/claims.json`.** Chaque claim porte une citation verbatim. Les
portes mécaniques ont déjà vérifié que la citation existe mot pour mot dans la
source, qu'un instantané Wayback daté existe, et que notre propre prose décrit
au lieu de juger.

Ce qu'elles ne peuvent pas vérifier, et qui est donc le travail de cette
relecture :

- **La citation soutient-elle vraiment la position qu'on lui prête ?** Une
  citation réelle peut être pliée en une position qu'elle n'énonce pas. Aucune
  porte n'attrape cela.
- **`contexte` est-il exact ?** C'est le seul champ généré qu'aucune porte ne
  protège.
- **Le `tier` marqué d'un astérisque.** Il vient par défaut de la source, pas
  d'un jugement sur ce document : un site de parti publie aussi bien ses
  communiqués que les discours du candidat. Confirmer ou corriger.
- **Les citations vidéo.** Le transcript est une transcription automatique et
  sert à localiser le passage, jamais de source de citation. Vérifier à
  l'oreille au timestamp indiqué.

Corriger directement dans le fichier : une claim déjà présente n'est jamais
réécrite par le pipeline le lendemain.

`data/observatoire.db` et `data/artifacts/` sont l'état du pipeline et la
provenance. Ils ne se relisent pas.
