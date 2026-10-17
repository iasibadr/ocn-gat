# État des preuves

Ce dépôt est une **préversion de recherche**. Le noyau logiciel offre des
contrats de tâches, des budgets, des membranes d'accès, une mémoire bornée et
des chemins de reprise documentaire. Les quatre expériences incluses testent
ensemble sélection, perturbation des chemins, veille, coût et sorties du worker.

| Expérience | Observation enregistrée | Limite |
|---|---|---|
| CD-1 | 6/6 réponses ou refus attendus dans les deux bras ; OCN 32 accès contre 24 | La veille coûte plus que le gain local |
| PV-1 | Valeur OCN 8,00 / 11,20 contre 8,45 / 11,55 pour le meilleur témoin alerté | Aucun gain sur deux épisodes |
| PV-2 | Gain étroit dans un milieu, perte face au meilleur témoin dans les deux autres | Scénarios petits et construits |
| VR-3 | Réponses attendues exactes dans les deux bras ; valeur OCN 10,30 / 11,60 / 8,20 contre 10,80 / 12,05 / 8,50 | Critère prospectif échoué dans les trois milieux ; scénarios utilisés pour déboguer la trace |

Les `verify.py` vérifient les traces sauvegardées ; ils ne relancent pas le
modèle. Les `run.py` exigent un modèle local `qwen3.5:9b` disponible via
Ollama et peuvent produire de nouveaux résultats. Les protocoles `PROTOCOL.md`
décrivent ce qui a été fixé avant chaque essai.

`Q` est une perte opérationnelle conventionnelle, pas une chaleur mesurée en
joules. `T` est un paramètre numérique de décision, pas une température
physique. Le produit de Hamilton et la sélection de Boltzmann sont des
composants expérimentaux ; aucun bénéfice propre du quaternion n'a été établi
ici face à un contrôleur réel comparable. Les tests ne démontrent ni agent
universel, ni conversion automatique d'agents, ni supériorité générale.

La provenance privée du candidat est le commit
`362659f6d3612cd11fa7cdaf5effdb6f040b363c`. Ce dépôt public sélectionné
possède un historique Git neuf pour ne pas diffuser les anciennes traces
personnelles ou expérimentales. Les nombres ci-dessus proviennent des
résultats inclus et doivent être revérifiés après chaque modification.
