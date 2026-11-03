# Sources à vérifier — candidats non suivis

État au 3 novembre 2026. Aucune de ces sources n'est dans `config/sources.yaml` : chacune
doit d'abord être **récupérée, confrontée à son `robots.txt` et extraite avec succès**
(règle de `config/sources.yaml`). Elles ont été repérées par recherche web uniquement :
depuis l'environnement de développement, ces sites ne sont pas joignables, et rien n'a été
téléchargé. Tant qu'une source n'est pas vérifiée, le candidat reste « Non suivi » sur le
registre, ce qui n'est pas « aucune position identifiée ».

Aucun flux RSS n'a été confirmé. Quand un site montre des indices WordPress (chemins
`/wp-content/`, `/app/uploads/` ou `/author/`), un flux `/feed/` est probable mais non
confirmé. Les chaînes YouTube sont surtout des entretiens à plusieurs voix : elles ne
peuvent alimenter que des pistes (`speakers: multi`), jamais des déclarations.

Confiance : **haute** = l'URL apparaît telle quelle dans un résultat de recherche du site
officiel ; **moyenne** = URL de rubrique déduite d'URL d'articles ; **basse** = page datée
ou attribution incertaine.

## Prêt à ajouter après une simple vérification

| Candidat | Source | Identifiant | Confiance |
|---|---|---|---|
| François Ruffin | Assemblée nationale, comptes rendus | `PA722142` (assemblee-nationale.fr/dyn/deputes/PA722142) | haute |

Même lecteur que les autres députés (`assemblee_nationale`) : seule la vérification que
l'identifiant porte bien des interventions dans l'archive est à faire.

## À vérifier

| Candidat | Type | URL | Confiance | Remarques |
|---|---|---|---|---|
| Nathalie Arthaud | site | https://www.nathalie-arthaud.info/ | haute | |
| | page | https://www.lutte-ouvriere.org/portail/editoriaux/ | moyenne | Éditoriaux hebdomadaires signés « Éditorial de Nathalie Arthaud » (dernier vu : 26 octobre 2026) ; URL de rubrique déduite |
| Nicolas Dupont-Aignan | page | https://www.debout-la-france.fr/actualite/ | moyenne | WordPress : `/feed/` probable, non confirmé. Plus de mandat de député depuis 2024 |
| Raphaël Glucksmann | Parlement européen | député `197694` (europarl.europa.eu/meps/en/197694) | haute | Demande un lecteur des comptes rendus du Parlement européen, qui n'existe pas encore |
| | site | https://glucks2027.fr/ | haute | Site de campagne ; https://raphaelglucksmann.fr/ existe aussi, lequel fait foi n'est pas établi |
| | site | https://place-publique.eu/ | haute | CMS `/posts/<id>/<slug>`, pas de flux vu |
| David Lisnard | site | https://www.unenouvelleenergie.fr/ | haute | Le domaine est `unenouvelleenergie.fr`. La rubrique « Dans les médias » republie de la presse : niveau 3, pistes seulement |
| | page | https://www.unenouvelleenergie.fr/questions/ | moyenne | Pages « les positions de David Lisnard » par thème |
| Fabien Roussel | site | https://www.fabienroussel2027.fr/ | haute | Site de campagne désigné par le PCF |
| | site | https://www.pcf.fr/ | haute | Discours (ex. université d'été 2026) ; pas de flux ni d'index vu |
| Marine Tondelier | site | https://marinetondelier.fr/ | haute | Rubriques `/blog/`, `/journal-de-campagne` (peut-être vidéo), `/manifeste` |
| | site | https://lesecologistes.fr/ | haute | Discours et communiqués ; CMS `/posts/<id>/<slug>`, pas de flux vu |
| Éric Zemmour | site | https://www.parti-reconquete.fr/ | haute | « Dernières prises de parole » ; les sous-domaines `fedeNN.` sont des fédérations (niveau 2) |
| | page | https://www.ericzemmour.fr/communiques | basse | Titrée « 2022 », peut-être figée |
| François Ruffin | site | https://francoisruffin.fr/ et https://debout.fr/ | haute | Pas de flux vu |

Candidats déjà suivis, sources supplémentaires repérées :

| Candidat | URL | Confiance | Remarques |
|---|---|---|---|
| Gabriel Attal | https://www.gabrielattal.fr/ | moyenne | Certaines pages datent de 2018 |
| Marine Le Pen | https://rassemblementnational.fr/communiques/ | moyenne | `/author/marinelepen/` suggère WordPress |
| Édouard Philippe | https://horizonsleparti.fr/ | haute | Discours (Adidas Arena 5 juillet 2026, Reims 10 mai 2026) ; URL des pages non vues |

## Décision éditoriale en attente

Le flux du Parti socialiste (`olivier-faure/rss/ps`) reste attribué à Olivier Faure, qui
s'est retiré le 11 octobre 2026. Raphaël Glucksmann est depuis le candidat commun PS–Place
publique : rattacher ce flux à lui, à partir de quelle date, est une décision éditoriale.
En attendant, ni Olivier Faure ni ce flux n'apparaissent sur le registre.

## Comment vérifier

Depuis une machine qui a accès au réseau (ou depuis GitHub Actions, où tourne déjà la
collecte quotidienne de la version précédente) :

1. Récupérer l'URL et son `robots.txt` avec l'agent `ESSECMetalabBot/1.0`.
2. Pour un flux : compter les éléments et vérifier qu'ils sont datés. Pour une page :
   vérifier que trafilatura en extrait le texte (au-delà de `min_text_chars`).
3. Ajouter l'entrée à `config/sources.yaml`, puis `observatoire collect --source-id <id>`.
