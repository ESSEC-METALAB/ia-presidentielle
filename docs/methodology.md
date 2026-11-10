# Méthodologie

Codebook, axes de positionnement et règles de calcul de l'indicateur. Ce document est
publié avec chaque rapport (README, « Conformité »).

> **État : à rédiger.** Les sections ci-dessous sont remplies à mesure que les décisions
> sont prises. Aucun chiffre n'est calculé tant que la section correspondante est vide.

## Périmètre

### Période

Le corpus couvre les textes publiés **depuis le 1er juillet 2026**
(`config/sources.yaml`, `collection.since`). La règle est appliquée à un seul endroit, le
cas d'usage de collecte, quel que soit le lecteur ; `--since` peut la resserrer, jamais
l'élargir. Les textes sans date sont conservés et affichés « date non précisée » : une date
absente ne prouve pas qu'un texte est ancien. Déplacer la fenêtre laisse les textes plus
anciens en base, hors du périmètre : ils sont comptés sur la page du corpus, jamais effacés
sans trace.

Effet sur l'import du 14 octobre 2026 : sur 283 documents de la version précédente, 192 sont
antérieurs au 1er juillet et n'entrent pas ; 88 documents restent après dédoublonnage.

### Candidats

**Qui est affiché (depuis le 6 novembre 2026).** Après la démonstration du 5 novembre,
le registre affiche treize personnes : celles qui ont le meilleur score au premier tour
dans un sondage dont le terrain s'achève le 1er juillet 2026 ou après, parmi celles
testées dans au moins cinq de ces sondages. La liste ne dépend donc plus de la
déclaration de candidature : elle suit les personnes que les instituts mesurent.

Être affiché est un choix éditorial (`shown` dans `config/candidates.yaml`) ; la
candidature reste un fait, sourcé et daté, que le site indique quand la personne ne se
présente pas : Olivier Faure (battu à la primaire du 11 octobre) et François Hollande
(pressenti, non déclaré). Nathalie Arthaud et Nicolas Dupont-Aignan, déclarés, ne sont
plus affichés : leurs textes restent stockés, aucun n'est effacé, leurs sources ne sont
plus lues et leurs passages ne sont plus envoyés au modèle.

| Personne | Statut au 9 novembre 2026 | Meilleur score depuis juillet | Sondages |
|---|---|---|---|
| Marine Le Pen (RN) | déclarée | 38 % (Harris Interactive, août) | 142 |
| Édouard Philippe (Horizons) | déclaré | 24 % (Ifop, septembre) | 98 |
| Jean-Luc Mélenchon (LFI) | déclaré | 20,5 % (Cluster17, octobre) | 142 |
| Raphaël Glucksmann (PP-PS) | désigné, primaire du 11 octobre | 18 % (Ifop, août) | 106 |
| Bruno Retailleau (LR) | désigné | 17,5 % (Cluster17, octobre) | 137 |
| Gabriel Attal (Renaissance) | déclaré ; appelle à une primaire | 17 % (Ifop, septembre) | 82 |
| David Lisnard (Nouvelle Énergie) | déclaré | 17 % (Cluster17, octobre) | 25 |
| François Hollande (PS) | **pressenti, non déclaré** (« la réponse est au mois de décembre ») | 12 % (Ifop, août) | 23 |
| Marine Tondelier (Les Écologistes) | déclarée ; vote des militants le 13 décembre | 7 % (YouGov, septembre) | 130 |
| Éric Zemmour (Reconquête) | déclaré | 6 % (YouGov, septembre) | 141 |
| François Ruffin (Debout !) | déclaré | 6 % (Elabe, juillet) | 11 |
| Olivier Faure (PS) | **ne se présente plus**, battu à la primaire | 5,5 % (Ipsos BVA, septembre) | 11 |
| Fabien Roussel (PCF) | désigné | 4,5 % (Elabe, août) | 136 |

Juste en dessous : Dominique de Villepin (4,3 %, 20 sondages) et Nicolas Dupont-Aignan
(4 %, 133 sondages). Bruno Le Maire (6 %) n'est testé que dans deux sondages. Données
MieuxVoter, état du 9 novembre 2026 (dernier terrain : 29 octobre). La coupure entre le
13e et le 14e tient à quelques dixièmes de point : un nouveau sondage peut la déplacer, et
la liste est revue à la main, jamais automatiquement.

**Règle d'inclusion précédente**, appliquée le 14 octobre 2026, qui a constitué la
configuration. Une personne était suivie si :

1. elle a publiquement déclaré sa candidature à l'élection présidentielle de 2027, ou a
   été désignée par son parti ou par une primaire, et ne s'est pas retirée ;
2. et, soit son parti dispose d'un groupe parlementaire à l'Assemblée nationale ou au
   Sénat, soit elle a été créditée d'au moins 2 % des intentions de vote au premier tour
   dans un sondage dont le terrain s'achève le 1er juillet 2026 ou après.

Les sept personnes de la version précédente sont conservées ; celles qui ne se présentent
plus sont marquées comme telles, pas retirées de la liste : retirer une personne est une
décision éditoriale. L'ordre est alphabétique par nom.

| Personne | Statut au 14 octobre 2026 | Critère 2 | Décision |
|---|---|---|---|
| Nathalie Arthaud (LO) | déclarée, 8 décembre 2025 | 2 % (Elabe, juillet) | ajoutée |
| Gabriel Attal (Renaissance) | déclaré, 22 mai 2026 | groupe EPR ; 17 % | conservé |
| Jordan Bardella (RN) | ne se présente pas, 7 juillet 2026 | — | conservé, marqué |
| Nicolas Dupont-Aignan (DLF) | déclaré, mars 2025 | 4 % (Cluster17, 22-24 juillet) | ajouté |
| Olivier Faure (PS) | battu à la primaire du 11 octobre 2026 | — | conservé, marqué |
| Raphaël Glucksmann (Place publique) | désigné, primaire du 11 octobre 2026 (66,13 %) | groupe socialiste ; 18 % | ajouté |
| Marine Le Pen (RN) | déclarée, 7 juillet 2026 | groupe RN ; 38 % | conservée |
| David Lisnard (Nouvelle Énergie) | déclaré, 31 mars 2026 | 5,2 % (Cluster17, septembre) | ajouté |
| Jean-Luc Mélenchon (LFI) | déclaré, 3 mai 2026 | groupe LFI-NFP ; 19,8 % | conservé |
| Édouard Philippe (Horizons) | déclaré, 3 septembre 2024 | groupe HOR ; 24 % | conservé |
| Bruno Retailleau (LR) | désigné, 19 avril 2026 | groupe DR ; 12 % | conservé |
| Fabien Roussel (PCF) | désigné, 6 septembre 2026 | groupe GDR ; 4,5 % | ajouté |
| François Ruffin (Debout !) | déclaré (date non établie) | 6 % (Elabe, juillet) | ajouté |
| Marine Tondelier (Les Écologistes) | déclarée, 22 octobre 2025 | groupe EcoS ; 7 % | ajoutée |
| Éric Zemmour (Reconquête) | déclaré, 17 septembre 2026 | 6 % (YouGov, septembre) | ajouté |

**Non retenus pour l'instant, à surveiller :** Dominique de Villepin (« presque
candidat », pas de déclaration formelle trouvée ; 4,3 %), Xavier Bertrand (dit qu'il sera
candidat, en indépendant, déclaration annoncée pour la fin de l'année ; 1 % dans le seul
sondage depuis juillet), François Hollande (testé à 12 %, non déclaré). Ont renoncé ou
perdu la primaire : Gérald Darmanin, Laurent Wauquiez, François Bayrou, Clémentine Autain,
Sandrine Rousseau, Ségolène Royal, Emmanuel Maurel, Jérôme Guedj. Bernard Cazeneuve,
déclaré, n'apparaît dans aucun sondage depuis juillet et n'a pas de groupe.

**Sur quoi repose cette liste.** Les sondages viennent du jeu de données communautaire
MieuxVoter (`github.com/MieuxVoter/presidentielle2027`, état du 13 octobre 2026), qui cite
pour chaque sondage sa notice à la Commission des sondages. Les statuts reposent sur des
résumés de résultats de recherche des articles cités dans `config/candidates.yaml` : depuis
cet environnement, aucune page de presse n'a pu être ouverte. Avant toute publication,
chaque statut est à relire sur ces pages. Les groupes parlementaires sont ceux de la
XVIIe législature, toujours en cours : le compte rendu de l'Assemblée d'octobre 2026 porte
encore son numéro. La déclaration de Nathalie Arthaud n'est établie
que par des sources secondaires ; le statut de Marine Tondelier après la primaire du
11 octobre est à reconfirmer.

**Sources des personnes ajoutées.** Aucune n'a encore de source vérifiée : elles
apparaissent « non suivi ». Ce qu'il faut vérifier en premier est listé dans
`config/sources.yaml`.

## Dimensions et axes

Dix axes, dans `config/taxonomy.yaml` : régulation ; souveraineté et infrastructure ;
énergie ; emploi ; éducation et formation ; services publics ; surveillance et libertés ;
IA de défense ; sécurité des modèles ; financement. Chaque déclaration est rattachée à un
seul axe, celui de l'objet principal de la phrase. Quatre frontières ont une règle
explicite, écrite dans les définitions : l'électricité et le nucléaire au service de l'IA
relèvent de l'énergie, même présentés comme un atout national, le cloud, le calcul et les
puces de la souveraineté ; l'IA tournée vers la population relève de la surveillance, la
défense du pays ou de ses systèmes de l'IA de défense ; la sûreté des modèles eux-mêmes
relève de la sécurité des modèles, l'étiquetage des contenus générés de la régulation ; une
mesure délivrée sous forme de formation relève de l'éducation.

**Révision du 9 novembre 2026.** Les neuf axes du prototype de site (« IA 2027 —
Registre », v3) ont été revus après la démonstration du 5 novembre : « Environnement &
ressources » devient « Énergie », et « Sécurité & défense » est scindé en « IA de défense »
et « Sécurité des modèles ». La liste des axes fait partie de la consigne : changer d'axes
change d'annotateur, et tous les passages sont classés de nouveau. Une annotation qui
nomme un axe disparu n'est plus montrée ; son passage reste « en attente » jusqu'à sa
relecture. L'édition vérifiée du 3 novembre, classée sur les neuf anciens axes, n'est plus
publiée pour la même raison : son enregistrement reste dans `annotations/`, et ses
déclarations sont reclassées par l'annotateur du jour, sans le badge « Vérifiée », tant
qu'une nouvelle vérification croisée n'a pas été faite sur les dix axes.

Un axe nomme un sujet, jamais une direction : pas de pôles, pas d'orientation chiffrée.
C'est le choix du prototype de site (« Ni commentaire, ni score »), qui tranche la
première question ouverte ci-dessous pour ce qui est publié.

**Notes de 1 à 5 (10 novembre 2026, grille provisoire).** À la demande du CTO, chaque
déclaration publiée est notée sur les échelles de `config/scoring.yaml` (étape
`observatoire score`, consigne `score_statement.v1.md`, 24 appels en parallèle) :
`orientation` (« Encadrer ↔ Accélérer » : encadrer, protéger, freiner l'IA = 1 ;
développer, financer, libérer = 5 ; 3 = développer avec des garde-fous ; vide quand la
déclaration ne prend pas parti) et `concreteness` (1 = idée générale, 5 = mesure chiffrée
et datée). Pour chaque axe, la grille écrit ce que valent 1, 3 et 5 : c'est elle qui dit
pourquoi une déclaration a reçu sa note, avec la raison en une phrase que le modèle doit
donner. Garde-fou : le modèle cite les mots de la citation sur lesquels la note repose,
le code les retrouve, sinon la note est écartée (`dropped`). Le site montre la note et
sa raison sur chaque déclaration, et la moyenne par candidat et par axe dans le
baromètre (`aggregation: mean`), hachurée sous trois déclarations (`min_statements`).
Une note décrit une position, jamais la qualité d'un candidat. Grille écrite la veille de
la revue du CTO, à valider ; changer la grille change la consigne, donc la version du
noteur : tout est noté de nouveau. C'est le score qu'excluait la question ouverte 1
ci-dessous, décidé en connaissance de cause.

**Opportunité ou menace (10 novembre 2026).** À la demande du CTO, chaque déclaration
publiée reçoit en plus un cadrage : `opportunity` (l'IA présentée comme une chance),
`threat` (comme un danger), `both`, ou `none` (une mesure, un fait, une critique, sans
dire si l'IA est une chance ou un danger : le cas le plus fréquent). Ce n'est pas un
axe : une déclaration sur l'emploi peut être l'un ou l'autre. Étape à part, après le
classement (`observatoire frame`, consigne versionnée `frame_statement.v1.md`, quatre
appels en parallèle), pour ne pas reclasser les axes. Garde-fou : un cadrage autre que
`none` doit citer les mots de la citation qui le portent (`evidence`), que le code
retrouve, apostrophes et casse mises à part ; sinon il est enregistré `none`, avec la
raison. Le résumé et le contexte aident à lire la citation, jamais à trouver un cadrage
qu'elle ne dit pas. Publication : une étiquette sur chaque déclaration, un filtre dans
le fil, et une colonne du baromètre aux comptes bruts (une déclaration `both` compte des
deux côtés), jamais un pourcentage. C'est une entorse au principe « ni tonalité ni
sentiment » de la version précédente (question ouverte 1 ci-dessous), décidée en
connaissance de cause ; le site la signale dans sa méthodologie.

## Repérage et classement (`observatoire annotate`)

1. **Filtre déterministe.** Seuls les passages qui mentionnent l'IA sont examinés : un
   terme fort suffit (« intelligence artificielle », « IA », « algorithme », « centre de
   données »…), sinon deux termes faibles distincts (« numérique », « données »…). Règle
   et listes reprises de la version précédente, où une liste plate avait laissé passer un
   débat sur les retraites. Sur le corpus du 3 novembre 2026 : 121 passages sur 891.
2. **Annotation.** Pour chaque passage retenu, un modèle reçoit une consigne versionnée
   (`adapters/llm/prompts/classify_dimension.v1.md`, avec les axes écrits dedans) et
   rend, selon un schéma JSON strict, la liste des déclarations du passage : axe,
   citation, résumé et contexte en français et en anglais, traduction indicative. **Une
   liste vide est la réponse attendue pour la plupart des passages**, et elle est
   enregistrée comme les autres : le passage n'est pas renvoyé.
3. **Contrôles.** Une proposition n'est gardée que si la citation figure mot pour mot
   dans le passage (espaces et apostrophes typographiques près ; la citation enregistrée
   est alors le texte de la source, pas la copie du modèle), compte au plus 60 mots,
   porte un axe connu, n'est pas un doublon, et si ni le résumé ni le contexte ne
   contiennent de terme évaluatif (liste dans `config/taxonomy.yaml`). La citation n'est
   jamais filtrée : si un candidat qualifie son propre plan d'« ambitieux », c'est son
   mot. Toute proposition rejetée est conservée avec son motif.
4. **Provenance.** Le modèle ne dit jamais qui parle, où ni quand : le schéma l'interdit
   (`extra="forbid"`). Personne, niveau de source, URL, date et archive sont joints par le
   code, depuis le document stocké, au moment de construire le registre.

L'annotateur est versionné par son modèle, le fichier de consigne et le hachage de la
consigne rendue (qui contient les axes). Changer l'un des trois fait réannoter.

**Fournisseurs.** `--llm mistral` appelle l'API Mistral (sorties structurées, schéma
strict). `--llm batch` écrit les requêtes en attente dans un fichier JSONL au format batch
sans rien enregistrer ; `--llm recorded --responses <fichier>` rejoue des réponses
enregistrées par identifiant de requête (empreinte de la consigne et du passage), à
travers les mêmes contrôles. Une réponse qui ne correspond plus exactement à la requête
(consigne, axes ou passage modifiés) n'est pas rejouée.

**Édition du 3 novembre 2026 : brouillon, non relu.** L'API Mistral n'étant pas joignable
depuis l'environnement de développement, les 117 requêtes distinctes ont été écrites en
batch et traitées hors ligne par un assistant (Claude Code), avec la même consigne et le
même schéma, puis rejouées par `--llm recorded`. Les réponses sont versionnées dans
`annotations/2026-11-03-brouillon.jsonl` (modèle déclaré `claude-code-session-draft`) :
`make site` reconstruit le registre à l'identique, hors ligne. Ce n'est pas le
fournisseur retenu pour la production, et aucune de ces déclarations n'a encore été relue
par un éditeur ; le site le dit.

**Vérification croisée de l'édition du 3 novembre 2026.** Les contrôles automatiques
prouvent qu'une citation existe ; ils ne disent pas si elle porte une position, si l'axe
est le bon, ni si le résumé lui est fidèle. Chaque déclaration retenue par les contrôles
a donc été relue par six vérificateurs indépendants (des assistants, pas des éditeurs),
chacun sur un seul critère :

| Critère | Vérificateurs | Règle appliquée par le code |
|---|---|---|
| Substance et attribution : une position sur l'IA, du candidat ou de son parti | 3, chargés de réfuter | écartée si au moins 2 la réfutent |
| Axe : l'objet principal de la phrase, règles de frontière comprises | 2, qui choisissent d'abord leur axe | changé seulement si les 2 le rejettent et proposent le même ; sinon conservé et signalé |
| Fidélité et neutralité du résumé, du contexte et de la traduction | 1, qui propose une correction | la correction remplace les notes ; la citation n'est jamais touchée |

Les passages restés vides n'ont pas été réexaminés : une annotation vide est une réponse
correcte, et une seconde passe « pour trouver quelque chose » est précisément ce qui
fabrique des positions. Tous les verdicts et toutes les modifications sont versionnés dans
`annotations/2026-11-03-verification.json` ; les réponses brutes de l'annotateur, avant
vérification, dans `annotations/2026-11-03-brouillon-brut.jsonl`.

**Résultat de la vérification.** 188 déclarations distinctes soumises ; 6 écartées
(au moins 2 réfutations sur 3 : deux maximes, une prévision, une promesse d'effectifs
sans lien explicite à l'IA, un constat, un statut de dirigeant sans lien à l'IA) ; 1 axe
changé (des incitations fiscales pour retenir les talents : de formation à financement) ;
45 notes corrigées, surtout des résumés qui ajoutaient un mot absent du texte (« en
France », « citoyens ») ou en retiraient un (« toutes », « fortement »), et une nature
de texte (« entretien ») que la source ne dit pas. Les lecteurs d'axe, qui choisissaient
d'abord leur propre axe, retombent sur l'axe proposé dans 356 lectures sur 364 (98 %) ;
c'est une mesure d'accord entre assistants, pas une validation.

Un défaut des contrôles a été trouvé à cette occasion : la liste des termes évaluatifs
mêlait français et anglais, et l'anglais *sensible* (jugement) rejetait le français
« données sensibles » (description). Sept notes fidèles étaient écartées. Chaque langue a
désormais sa liste, appliquée à ses seuls champs ; `observatoire annotate --rebuild`
réapplique les contrôles aux réponses enregistrées.

## Registre public (`observatoire register`)

Construit dans `data/site/` à partir du gabarit `web/registre/` (le prototype v3, modifié
au minimum : mention « citations réelles, classement non relu », lien d'archive seulement
quand une capture existe, natures de source réelles, historique fictif des axes retiré)
et d'un fichier `data.js` généré.

- **Qui figure.** Les treize personnes de la liste éditoriale (`shown` dans
  `config/candidates.yaml`, section « Candidats » ci-dessus), par ordre alphabétique du
  nom. Nathalie Arthaud, Nicolas Dupont-Aignan et Jordan Bardella sont hors registre ;
  leurs documents restent stockés.
- **Suivi.** Un candidat est « suivi » s'il a au moins une source active. Sinon, chaque
  case porte « Non suivi » : nous n'écoutons pas, ce n'est pas un silence.
- **Niveaux.** Seuls les niveaux 1 et 2 deviennent des déclarations. Le niveau est
  confirmé seulement quand la source nomme elle-même l'orateur (compte rendu de
  l'Assemblée nationale) ; partout ailleurs il est attribué par défaut, en pointillés.
- **Nature.** Le site affiche la nature du support (séance, publication du site, page,
  PDF), pas le genre (discours, entretien, communiqué), qui est un jugement éditorial.
- **Archive.** Seule une vraie capture de la Wayback Machine (`/web/<14 chiffres>/`),
  héritée de la version précédente, est affichée ; sinon « pas encore de capture ».
- **Quelle annotation.** Pour chaque passage : celle d'une édition vérifiée
  (`config/register.yaml`, badge « Vérifiée »), sinon celle de l'annotateur du jour
  (badge « Contrôles automatiques »), sinon le passage est « en attente » : le site ne dit
  jamais « aucune position identifiée » d'un texte que personne n'a lu. Une mise à jour du
  matin ne remplace donc jamais une édition vérifiée.

## Niveaux de source

Repris du README. Seuls les niveaux 1 et 2 deviennent des déclarations ; la presse
(niveau 3) et les tiers (niveau 4) jamais, même avec une citation directe attribuée : ils
peuvent signaler une piste à un éditeur, pas établir une position.

**Réseaux sociaux (depuis le 9 novembre 2026).** Les comptes officiels des candidats sur
X, Facebook, Instagram, LinkedIn, TikTok et YouTube sont lus par des outils d'Apify
(apify.com), faute d'accès officiel abordable : l'API de X est payante, celles de Meta et
de TikTok sont réservées à des programmes de recherche sur dossier, LinkedIn n'en a pas.
Ces outils lisent les pages publiques ; c'est contraire aux conditions d'utilisation des
plateformes, un choix assumé pour ce prototype. Chaque compte a été vérifié en lisant ses
derniers posts avant d'être ajouté (`config/sources.yaml`). Seuls les posts écrits par le
compte sont gardés : ni republications, ni réponses à d'autres comptes, et jamais les
commentaires des internautes, qui ne sont pas stockés. Un post est de niveau 1 par
défaut, non confirmé : l'équipe de campagne écrit souvent les posts d'un candidat. Une
vidéo compte par ses mots : la légende, plus les sous-titres français quand TikTok les
fournit, ou la transcription automatique pour YouTube, où seuls les discours sont gardés
(les vidéos dont le titre ou la description annoncent un entretien, un débat ou des
questions sont écartées, mais le filtre peut en laisser passer). La première lecture d'un
compte remonte au début de la fenêtre, dans la limite de son `max_items` ; la mise à jour
quotidienne ne lit que les deux derniers jours. Priorités fixées le 10 novembre 2026 : X, LinkedIn et
Instagram sont lus depuis le début de la fenêtre ; Facebook ne l'est que pour les posts
récents (remonter à juillet coûterait environ 12 dollars) ; la collecte TikTok et YouTube
est arrêtée, et ce qu'elle a donné reste publié, sa source marquée « collecte arrêtée ».

**Discours en vidéo (depuis le 5 novembre 2026).** Un discours prononcé par le candidat
est de niveau 1, même quand la vidéo est diffusée par une chaîne de télévision : ce sont
ses mots, pas un article sur lui. Faute de texte publié, sa transcription est conservée
dans `config/transcripts/` (source `transcript`) et le registre renvoie à la vidéo. C'est
la transcription automatique de la vidéo (sous-titres YouTube), débarrassée des
horodatages et des bruits de salle, sans autre retouche : une citation peut donc porter
une erreur de sous-titrage, à vérifier sur la vidéo à la relecture. Seuls les monologues
sont retenus : les sous-titres d'un entretien ne disent pas qui parle, et la question du
journaliste serait attribuée au candidat ; une conférence de presse est coupée là où le
candidat passe la parole. Premiers ajouts : Éric Zemmour à Port-Marly (13 septembre
2026) ; Marine Le Pen à Hénin-Beaumont (13 septembre), en conférence de presse
(6 octobre) et à Orléans (25 octobre 2026) ; Jean-Luc Mélenchon à la Fête de
l'Humanité (12 septembre) et à Clermont-Ferrand (11 octobre 2026).

## Indicateur

À définir, dans `config/scoring.yaml`, si un score est un jour publié : pondération par
niveau de source, seuil de segments sous lequel on affiche « données insuffisantes »,
intervalle de confiance. Le registre n'en publie aucun.

## Relecture humaine

À définir : taille de l'échantillon, profil des relecteurs, mesure d'accord. Aucune
déclaration de l'édition du 3 novembre 2026 n'a été relue.

## Constat sur le registre du 3 novembre 2026 : une couverture très inégale

182 déclarations, dont 178 de Bruno Retailleau, et 167 tirées d'un seul document : son
programme consacré à l'IA (« L'IA au service des Français », PDF du 7 juillet 2026). Jean-
Luc Mélenchon en compte 1, Édouard Philippe 3 ; Gabriel Attal et Marine Le Pen sont suivis
(Assemblée nationale) sans déclaration sur l'IA depuis juillet ; huit candidats ne sont pas
suivis du tout.

Ce déséquilibre mesure nos sources, pas l'intérêt des candidats pour l'IA : le registre
le dit en distinguant « aucune position identifiée » de « Non suivi », mais le baromètre,
qui compte une déclaration par mesure, place mécaniquement un programme détaillé loin
devant tout le reste. Avant toute publication : vérifier et activer les sources des
candidats non suivis (`docs/sources-a-verifier.md`), et décider si le baromètre doit
signaler qu'une ligne repose sur un programme dédié.

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
- **Zéro intervention pour Bruno Retailleau** dans le compte rendu de la XVIIe législature :
  c'est attendu (interventions ministérielles terminées, retour au Sénat, dont le compte
  rendu demande son propre lecteur). Olivier Faure, à zéro le 4 octobre, a deux séances
  dans les données du 14 octobre, après la rentrée parlementaire du 1er octobre :
  l'identifiant PA609332 est donc le bon.
- **Jordan Bardella n'est pas suivi** : aucune source vérifiée. Député européen, son compte
  rendu est celui du Parlement européen.
- Les fils de parti (niveau 2) publient l'actualité de tout le parti : la vue indique pour
  chaque document s'il cite le candidat.
