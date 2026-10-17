# PV-2 — preuve de veille consommable et comparaison classique équitable

Gel prospectif avant tout résultat PV-2. PV-1 a montré une rupture causale :
une sonde positive n'était pas imposée à la sélection de route suivante.
PV-2 corrige cette liaison sans changer le worker, l'autorité des versions,
le validateur, les deux routes ni la fonction de valeur de PV-1. Les épisodes
ci-dessous sont nouveaux ; aucun paramètre ne sera réglé après leur ouverture.

Une sonde positive donne un reçu `(document_id, route, version épinglée,
numéro de requête)`. La membrane de sélection privilégie exclusivement cette
route **pour la prochaine demande seulement**, y compris sa relecture finale.
Un échec entre sonde et lecture permet le repli vers l'autre route ; la version
est contrôlée à chaque lecture. Le reçu expire à la fin de cette demande même
si elle échoue. Aucune sonde ne donne droit à une nouvelle version. Une sonde
négative interdit d'abord la route observée invalide pour cette demande, sans
interdire le repli si l'autre route échoue. Quand aucune preuve positive n'est
acquise, chaque politique suit sa règle habituelle.

Quatre bras reçoivent exactement les mêmes alertes `(document_id)` :

- `sticky` : dernier chemin réussi, sans sonde ;
- `alert_classic` : sonde à chaque alerte puis utilise la preuve consommable ;
- `risk_classic` : même estimateur de risque et même seuil de sonde que l'OCN,
  mais routage déterministe classique hors preuve ;
- `ocn_lease` : même estimateur, sondes, preuve consommable, puis coordonnées
  `X,t,Q,T`, Hamilton et sélection de Boltzmann seulement entre routes encore
  admissibles. Les mêmes cellules d'extraction et le même worker sont utilisés
  par les quatre bras.

Tous les bras ont les mêmes deux routes autorisées, la même mémoire bornée et
les mêmes questions. Les coûts de sonde comptent, même si elles échouent.
Épisodes, chacun partant d'un habitat neuf :

1. `bascule` : initial ; B primaire modifié ; alerte B sans changement ; B
   primaire restauré ; A primaire supprimé ; alerte A sans changement ; A
   primaire restauré ; B primaire modifié ; B primaire restauré.
2. `bruit_puis_rupture` : initial ; cinq alertes A sans changement ; A primaire
   supprimé ; deux demandes sans alerte ; A primaire restauré ; deux alertes A
   sans changement ; A primaire supprimé de nouveau ; A primaire restauré.
3. `miroir` : initial ; A miroir déplacé ; A primaire supprimé ; alerte A sans
   changement ; A miroir modifié sans autorisation ; A miroir restauré à sa
   version épinglée ; B primaire modifié ; B primaire restauré.

Une réponse exacte en au plus quatre tentatives de lecture de **mission** vaut
1 ; exacte mais tardive vaut 0,5 ; un refus exact quand toutes les copies
épinglées requises sont absentes vaut 1 ; sinon 0. Valeur nette = somme moins
0,05 par sonde. Rapporter séparément exactitude, réponses à temps, tentatives
de mission, sondes, échecs, appels LLM et traces des reçus consommés.

Critère prospectif de progression : `ocn_lease` doit avoir une valeur nette
strictement supérieure aux trois références dans chacun des trois épisodes,
sans baisse d'exactitude ni appels worker supplémentaires. Une égalité avec
`risk_classic` ne démontre aucun apport de Hamilton. En cas d'échec, conserver
ce résultat et diagnostiquer la première rupture, sans optimisation sur ces
épisodes. La valeur est conventionnelle, pas une mesure physique d'énergie.
