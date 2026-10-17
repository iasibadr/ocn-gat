# PV-1 — valeur prospective de la veille documentaire

Geler ce protocole avant le premier résultat. Trois bras, mêmes fichiers locaux,
routes, versions épinglées, travailleur `qwen3.5:9b`, organe d'extraction à deux
cellules, mémoire de quatre entrées par cellule, alertes `(document_id)` et
questions. Aucun bras ne reçoit la nature réelle d'un changement avant une
lecture. Les sondes lisent seulement les routes autorisées, sont facturées et
ne changent jamais une version autorisée. Chaque bras reçoit les mêmes alertes
et peut choisir de les ignorer.

1. `sticky` : agent classique robuste, dernier chemin réussi, repli à la demande.
2. `alert_classic` : sur chaque alerte, sonde son chemin préféré ; s'il échoue,
   sonde l'autre puis privilégie une copie valide. Repli et vérification identiques.
3. `ocn_value` : sur chaque alerte, estime la probabilité d'un chemin préféré
   invalide à partir de ses reçus et de son état de cellule ; décide de sonder
   ou non avec un calcul coût/bénéfice fixé avant l'essai. Si elle sonde,
   mêmes droits et sondes que `alert_classic`. Pour ses lectures de mission,
   elle utilise les quatre coordonnées numériques, un produit de Hamilton
   comme terme de coût, Boltzmann, puis le même worker et la même vérification.
   Résultat vérifié et rejets de la membrane actualisent les états suivants.

Épisodes fixés avant l'essai (chaque épisode repart d'un habitat vierge) :

- `perturbations` : initial ; A primaire supprimé ; alerte A sans nouveau
  changement ; A miroir déplacé ; B primaire modifié ; alerte B sans nouveau
  changement ; A indisponible sur les deux routes ; A restauré ; alerte A sans
  changement. Les documents requis restent A+B.
- `bruit` : initial ; six alertes successives sur A sans changement ; puis A
  primaire supprimé ; trois demandes sans nouvelle alerte ; puis A restauré.
  Les alertes ne décrivent pas une cause et ne portent aucun futur oracle.

Une réponse complète et exacte en **quatre tentatives de lecture de mission**
vaut 1 ; complète mais plus tardive vaut 0,5. Un refus exact lorsque la version
requise est absente vaut 1 ; toute autre sortie vaut 0. Valeur nette : somme de
ces scores moins 0,05 par sonde. Mesurer séparément réponses exactes, délais
en lectures, sondes, échecs, appels worker et octets lus si disponibles. La
récompense est conventionnelle, pas une énergie physique. Les interventions
humaines doivent rester nulles ; un refus injustifié compte comme échec.

Critère de progression : `ocn_value` doit avoir une valeur nette strictement
supérieure aux deux classiques dans chacun des deux épisodes, sans réduction
du nombre de réponses exactes ni appel worker supplémentaire. Si le critère
échoue, ne pas optimiser sur ces mêmes traces et ne pas attribuer la perte à
Hamilton seul. Vérifier la trace causalement, conserver tous les résultats.
Deux épisodes construits par nous ne démontrent aucune généralisation.
