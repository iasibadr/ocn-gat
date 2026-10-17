# PV-2 — lier la veille à la sélection réelle

Le [protocole](PROTOCOL.md) a été gelé au commit `51645ae`. Les trois
épisodes sont nouveaux par rapport à PV-1. Chaque bras a les mêmes alertes,
deux routes, versions épinglées, worker local `qwen3.5:9b`, organes de cache
et vérifications. Une sonde positive produit une preuve utilisable pour la
prochaine demande seulement ; la version est revérifiée à chaque lecture et
un repli reste possible si la copie change entre la sonde et l'action.

| Épisode | Sticky | Classique alerté | Classique à risque | OCN avec preuve |
|---|---:|---:|---:|---:|
| Bascule : valeur nette | 8,00 | 8,50 | 8,50 | **8,55** |
| Bruit puis rupture : valeur nette | **13,50** | 13,40 | 13,40 | 13,40 |
| Miroir : valeur nette | 7,00 | **7,50** | **7,50** | 7,05 |

Toutes les réponses sont exactes : 9/9, 14/14 et 8/8 par bras, avec deux
appels LLM par bras et par épisode. Dans `bascule`, OCN sonde neuf fois contre
dix pour les classiques alertés et répond à temps aux neuf demandes. Le gain
est **un seul coût de sonde, soit 0,05 point** ; il ne constitue pas une preuve
de l'apport de Hamilton. Dans `bruit_puis_rupture`, il fait égalité avec les
classiques alertés, mais `sticky` a une valeur supérieure parce qu'il évite
les sondes. Dans `miroir`, OCN choisit une route A déjà observée défaillante
sur une demande sans alerte ; l'exploration stochastique coûte une échéance.
Le critère prospectif (gagner dans les trois épisodes) **échoue**.

La [trace corrigée](results/run.json) et [son vérificateur](verify.py) contrôlent
la provenance, l'usage dans la même demande et les coûts des preuves. Un test
ciblé confirme que le classique garde le dernier chemin réussi après usage du
reçu et que le reçu expire. Le premier essai est conservé dans
[`invalid_initial.json`](results/invalid_initial.json) : une erreur
d'implémentation empêchait le classique à risque de conserver la route réussie.
Nous avons corrigé ce seul défaut et relancé les mêmes épisodes, sans changer
la règle de risque, la température, la récompense ou les perturbations. Comme
les épisodes avaient déjà été vus lors du débogage, même le petit gain sur
`bascule` n'est pas une validation indépendante réservée.

Le raccord observation → choix est maintenant fonctionnel. Le prochain défaut
est différent : hors reçu frais, l'état OCN garde bien des échecs passés mais
Boltzmann peut réessayer une route coûteuse sans bénéfice suffisant. Il faudra
définir un coût explicite de cette exploration, une durée de validité des
preuves et un mécanisme de récupération des routes restaurées, puis évaluer
sur de nouveaux cas face au même classique à risque. Ni `X,t,Q,T` ni le terme
Hamilton n'ont montré ici une supériorité générale.

```sh
.venv/bin/python -m unittest experiments.ocn_probe_lease_v2.test_lease
.venv/bin/python experiments/ocn_probe_lease_v2/verify.py experiments/ocn_probe_lease_v2/results/run.json
```
