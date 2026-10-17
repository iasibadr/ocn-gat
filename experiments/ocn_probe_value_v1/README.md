# PV-1 — décider si la veille vaut son coût

Le [protocole](PROTOCOL.md) a été figé au commit `da3f5c1` avant l'inférence.
Les trois politiques disposent des mêmes alertes, fichiers, droits, mémoire
bornée et worker local `qwen3.5:9b`. Le classique `sticky` ne sonde pas ; le
classique `alert_classic` sonde son chemin préféré à chaque alerte ;
`ocn_value` estime un risque et peut s'abstenir. Les accès réels, y compris
ceux de la veille, sont comptés dans la [trace](results/run.json).

| Épisode | Politique | Réponses exactes | À temps | Sondes | Valeur nette |
|---|---|---:|---:|---:|---:|
| Perturbations | sticky | 9/9 | 7/9 | 0 | 8,00 |
| Perturbations | classique alerté | 9/9 | 9/9 | 11 | **8,45** |
| Perturbations | OCN | 9/9 | 8/9 | 10 | 8,00 |
| Alertes bruitées | sticky | 12/12 | 11/12 | 0 | 11,50 |
| Alertes bruitées | classique alerté | 12/12 | 12/12 | 9 | **11,55** |
| Alertes bruitées | OCN | 12/12 | 11/12 | 6 | 11,20 |

Les six bras ont chacun effectué deux appels au même
worker et n'ont demandé aucune intervention humaine. Le critère prospectif
d'une valeur OCN strictement supérieure aux deux classiques dans **chaque**
épisode échoue.

La première rupture causale est visible lors de `change_B` : OCN sonde une
copie valide, puis sa sélection stochastique choisit une autre route non
vérifiée et perd l'échéance. La membrane de sélection n'a donc pas respecté
l'information que la membrane perceptive venait d'acquérir. Dans l'épisode
bruité, six alertes bénignes font baisser le risque estimé ; OCN saute alors
l'alerte qui correspond réellement à la disparition de A primaire et découvre
la panne pendant la demande. Économiser trois sondes ne compense pas la
réponse tardive dans la fonction de valeur annoncée.

L'état `X,t,Q,T`, Hamilton et Boltzmann sont présents dans la boucle de
lecture, mais cet essai ne valide ni leur nécessité ni une température
physique. La valeur est une convention opérationnelle, les fichiers et les
alertes sont synthétiques, et deux épisodes ne mesurent pas la généralisation.
Une politique classique qui estime le risque pourrait encore améliorer la
référence. Aucun paramètre de PV-1 ne sera réglé sur ces deux traces.

Prochaine correction architecturale : une sonde réussie doit devenir une
précondition dure de la prochaine sélection de route, avec date de validité
et coût de revalidation. Elle doit être évaluée sur **de nouveaux épisodes**
face à un classique qui applique la même règle et dispose d'un estimateur de
risque comparable. Sinon un gain éventuel pourrait provenir de la règle
classique de cohérence entre observation et action, pas de la géométrie OCN.

```sh
.venv/bin/python experiments/ocn_probe_value_v1/verify.py experiments/ocn_probe_value_v1/results/run.json
```
