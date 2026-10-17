# CD-1 — premier test de la boucle documentaire couplée

Le [protocole](PROTOCOL.md) a été écrit avant l'exécution. Le script [run.py](run.py)
utilise de vrais fichiers temporaires déplacés ou modifiés, deux chemins
autorisés, le worker local `qwen3.5:9b`, un organe d'extraction à deux cellules,
une mémoire bornée et le même validateur de preuves pour les deux bras. La
politique classique conserve le dernier chemin réussi. Le candidat OCN ajoute
une veille facturée et lie observations, états `X,t,Q,T` des routes, produit
de Hamilton, sélection de Boltzmann, worker, vérification et mise à jour pour
la demande suivante. Il ne s'agit pas de l'OCN théorique entier.

| Mesure, six étapes | Classique | OCN candidat |
|---|---:|---:|
| Réponses correctes, refus attendu compris | 6 | 6 |
| Appels au worker local | 2 | 2 |
| Tentatives d'accès, veille incluse | 24 | 32 |
| Échecs d'accès, veille incluse | 4 | 8 |
| Interventions humaines | 0 | 0 |

L'OCN anticipe deux ruptures et évite alors deux échecs **pendant la tâche**,
mais dépense dix sondes, dont six échouent. Ses cinq demandes qui aboutissent
utilisent chacune quatre accès de tâche (lecture initiale et revalidation de
deux documents). Le classique en ajoute un lors de la perte de A primaire et
un lors de la modification de B primaire. Sur la métrique globale préannoncée,
**aucun avantage de valeur ni d'autonomie n'apparaît, et l'OCN coûte davantage**.
Les deux bras refusent A lorsqu'aucune copie de la version autorisée ne subsiste.

La trace complète est dans [run.json](results/run.json) : lecture des deux côtés
de la membrane, distribution de choix antérieure à l'action, reçus, mémoire,
température suivante et sorties. [verify.py](verify.py) contrôle la cohérence
du résultat sans refaire d'inférence. Le modèle des cellules reste très simple :
Hamilton n'est qu'un terme de coût construit à la main ; `T` est un actuateur de
choix, pas une température unifiée, et `Q` une perte opérationnelle, pas de la
chaleur. La « réduction » H vers paramètres réels est le choix de route et la
commande typée du worker, sans conjugaison algébrique démontrée.

Le cas reste minuscule, rédigé par nous, et le classique ne fait pas de veille.
Un classique avec veille ou apprentissage pourrait faire aussi bien ou mieux.
La vérification sémantique est une comparaison de valeurs attendues propre au
banc, pas un juge universel. Les résultats ne justifient aucune affirmation de
supériorité. L'étape suivante utile est d'apprendre **quand** une observation
préventive vaut son coût, puis de comparer sur des perturbations réservées à un
classique disposant lui aussi des mêmes signaux et de la même mémoire.

```sh
.venv/bin/python experiments/ocn_coupled_documents/verify.py experiments/ocn_coupled_documents/results/run.json
# Nouvelle inférence seulement après installation locale du modèle requis :
.venv/bin/python experiments/ocn_coupled_documents/run.py --output /tmp/ocn-cd1-replay.json
.venv/bin/python experiments/ocn_coupled_documents/verify.py /tmp/ocn-cd1-replay.json
```
