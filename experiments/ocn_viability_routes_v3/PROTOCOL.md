# VR-3 — exploration sous contrainte de viabilité, avant évaluation

PV-2 a établi le reçu de veille consommable, mais l'OCN a parfois exploré une
route récemment invalide sans nouvelle preuve. VR-3 ajoute une quarantaine
**de deux demandes futures** après tout échec vérifié d'une route. Une lecture
ou sonde valide de la version épinglée lève immédiatement la quarantaine. Si
toutes les routes sont en quarantaine, l'agent essaie tout de même les deux
routes pour pouvoir se rétablir ou refuser sur des lectures fraîches. La
quarantaine n'autorise jamais une nouvelle version et ne remplace pas le
contrôle d'empreinte. Les plans encore viables sont sélectionnés avec les
mêmes coordonnées, terme de Hamilton et température que PV-2. Une seule route
viable est choisie sans tirage stochastique ; le repli réel reste permis.

Comparer quatre bras avec les mêmes fichiers, alertes, droits, mémoire, worker
`qwen3.5:9b` et score que PV-2 : `sticky`, `alert_classic`, `risk_classic`,
`ocn_viability`. Les trois classiques sont ceux de PV-2, sans changement de
politique. Tous les appels de sonde, lectures de mission et LLM sont comptés.
Les épisodes ci-dessous sont neufs, rédigés avant exécution :

1. `silence_retablissement` : initial ; A primaire supprimé ; trois demandes
   sans alerte ; A primaire restauré sans alerte ; A miroir supprimé ; deux
   demandes sans alerte ; A miroir restauré avec alerte ; A primaire supprimé
   avec alerte ; A primaire restauré avec alerte.
2. `signaux_incertains` : initial ; quatre alertes A sans changement ; B
   primaire modifié avec alerte ; deux demandes sans alerte ; B primaire
   restauré sans alerte ; B miroir supprimé avec alerte ; B miroir restauré
   sans alerte ; B primaire modifié sans alerte ; B primaire restauré avec
   alerte.
3. `indisponibilite` : initial ; A miroir déplacé avec alerte ; A primaire
   supprimé sans alerte ; A miroir modifié sans autorisation avec alerte ; une
   demande sans alerte ; A miroir restauré avec alerte ; A primaire restauré
   sans alerte ; deux alertes A sans changement.

Une réponse exacte en au plus quatre lectures de mission vaut 1, exacte plus
tardive 0,5, refus correct quand A est absent sur toutes les routes 1, toute
autre sortie 0. Valeur nette = somme moins 0,05 par sonde. Le critère de
progression est strict : OCN doit dépasser **tous** les classiques dans chaque
épisode en valeur nette, sans perte d'exactitude ni appel worker supplémentaire.
Sinon publier l'échec et ne pas régler les paramètres sur ces scénarios. Une
égalité ou un gain local ne démontre pas la supériorité du quaternion.
