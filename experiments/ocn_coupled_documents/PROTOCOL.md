# CD-1 — essai couplé documentaire, gel avant exécution

Mission : retrouver origine et destination de S dans deux documents locaux malgré
des déplacements, refuser une version modifiée non autorisée, puis reprendre
sans intervention humaine. Comparer une boucle OCN candidate à une politique
classique `sticky` avec les mêmes fichiers, deux routes, worker, organes de cache,
droits et versions épinglées. Les modifications de fichiers sont identiques.

Séquence fixée : état initial ; primaire A retiré ; miroir A déplacé ; primaire
B modifié ; A absent sur les deux routes ; A restauré. Une veille a lieu entre
les demandes seulement lorsque le milieu signale qu'un document a changé. Elle
lit au plus deux copies autorisées du document concerné ; ses lectures et ses
échecs sont facturés. Le classique reçoit le même signal mais garde sa politique
de reprise au moment de la demande. L'OCN suit deux cellules de route avec
quatre indicateurs normalisés, un produit de Hamilton candidat, un coût prédit,
une température et une sélection de Boltzmann déterministe par graine. Il utilise
le même EvidenceAgent pour lire, extraire, revalider et refuser. Le feedback de
lecture et le succès vérifié modifient les cellules et la température suivante.

Critère principal : réponses correctes/refus corrects sur les six étapes.
Secondaires : interventions, tentatives totales incluant la veille, échecs,
appels worker, mémoire, sélection et causalité de la mise à jour. Aucun réglage
après lecture du résultat. Un gain sur ce cas ne démontrerait aucune supériorité
générale. Les valeurs X,t,Q,T sont des indicateurs numériques, ni des grandeurs
thermiques ni une réalisation physique de H vers R. La synthèse est structurée ;
la vérification du sens est limitée aux valeurs attendues par ce banc.
