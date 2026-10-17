# VR-3 — quarantaine courte des routes échouées

Le [protocole](PROTOCOL.md) a été figé au commit `994240c`. La quarantaine
empêche pendant deux demandes futures une exploration volontaire d'une route
ayant échoué ; le repli reste possible et une preuve exacte lève l'interdiction.
Les trois références classiques, le worker `qwen3.5:9b`, les permissions, la
mémoire, les alertes et la valeur de mission sont les mêmes que PV-2.

| Épisode | Sticky | Classique alerté | Classique à risque | OCN + quarantaine |
|---|---:|---:|---:|---:|
| Silence et rétablissement | 10,50 | **10,80** | **10,80** | 10,30 |
| Signaux incertains | 11,50 | **12,05** | **12,05** | 11,60 |
| Indisponibilité | **8,50** | 8,20 | 8,20 | 8,20 |

Toutes les demandes obtiennent la réponse exacte ou le refus attendu :
12/12, 13/13 et 9/9 par bras. Chaque bras effectue deux appels LLM par épisode.
La règle résout localement le réessai immédiat d'une route défaillante, mais
**échoue au critère prospectif** de valeur nette dans les trois milieux.
Elle n'est pas intégrée au noyau ni activée par défaut.

Dans `silence_retablissement`, une ancienne quarantaine expire puis OCN
réessaie A primaire avant qu'une alerte n'arrive : la demande devient tardive.
Dans `signaux_incertains`, le même défaut apparaît pour B sur une demande
silencieuse. Un classique conservant simplement le dernier chemin réussi
évite une de ces reprises inutiles. Augmenter la durée de quarantaine sur
ces traces serait un réglage rétrospectif et n'est pas retenu. À l'inverse,
une interdiction permanente masquerait une route restaurée sans alerte ; la
preuve de viabilité exige donc un véritable arbitrage entre exploration et
coût d'une demande urgente.

La [trace finale](results/run.json) et [son vérificateur](verify.py) comptent
sondes, échecs, refus et états de route. Le premier fichier
[`invalid_trace.json`](results/invalid_trace.json) est conservé : ses valeurs
de mission étaient identiques, mais ses états internes imbriqués étaient
enregistrés par référence et affichaient à tort l'état final sur toutes les
lignes. Seule la copie des états dans la trace a été corrigée avant le
nouveau parcours. Les épisodes ont donc servi au débogage de l'instrumentation
et ne sont plus une réserve indépendante.

Cette expérience ne mesure pas l'énergie physique ni l'efficacité d'un
quaternion en général. La version MIT partageable doit présenter VR-3 comme
un contre-exemple documenté, pas comme une amélioration validée.

```sh
.venv/bin/python -m unittest experiments.ocn_viability_routes_v3.test_viability
.venv/bin/python experiments/ocn_viability_routes_v3/verify.py experiments/ocn_viability_routes_v3/results/run.json
```
