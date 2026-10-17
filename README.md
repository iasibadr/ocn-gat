# OCN / GAT — adaptation contrôlée des agents

**OCN** (Organisation Cognitive Numérique) est un prototype de recherche de
Charadi Badr. Il ajoute à des agents des mécanismes bornés de sélection,
mémoire, contrôle d'accès et reprise lorsque des documents ou chemins changent.
**GAT** (Generative Agent Transformer) désigne l'outillage expérimental de
création et d'intégration. Un modèle de langage existant reste le worker ; ce
dépôt ne recrée pas un LLM et ne transforme pas automatiquement tout agent.

L'objectif falsifiable de cette préversion est de retrouver et synthétiser des
documents malgré leur déplacement ou altération, en mesurant réponses,
refus, accès, appels au modèle et interventions. Le noyau est en Python ; les
exemples hors ligne utilisent des fichiers temporaires et ne requièrent aucune
clé API. La licence est [MIT](LICENSE) et l'attribution demandée figure dans
[AUTHORS.md](AUTHORS.md) et [CITATION.cff](CITATION.cff).

## Démarrage rapide

Python 3.10 ou plus récent. Depuis la racine du dépôt :

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ./packages/ocn-core
.venv/bin/python packages/ocn-core/examples/evidence_context.py
```

L'exemple crée un dossier temporaire, déplace un document, retrouve la version
autorisée et garde explicite une information inconnue. Il vérifie le parcours
logiciel ; son worker déterministe ne démontre pas une compréhension du texte.
Pour une inférence locale facultative, il faut installer séparément Ollama et
le modèle indiqué par la commande :

```sh
.venv/bin/python packages/ocn-core/examples/local_evidence_context.py --help
```

La commande ne télécharge pas de modèle. L'application qui produit un agent
documentaire borné est accessible par `gat --help` après installation. Lire
les options et budgets avant de la brancher à des documents personnels. Une
intégration Python non isolée est du **code de confiance exécuté avec les droits
du processus** : ne jamais lui fournir un fichier généré ou reçu d'un tiers
sans revue. Voir la [frontière de sécurité](SECURITY.md).

## Résultats reproductibles

Les quatre essais couplés retenus sont [CD-1](experiments/ocn_coupled_documents),
[PV-1](experiments/ocn_probe_value_v1),
[PV-2](experiments/ocn_probe_lease_v2) et
[VR-3](experiments/ocn_viability_routes_v3). Chaque dossier contient un protocole
fixé avant l'essai, le code, une trace et un vérificateur. Les vérificateurs
contrôlent des résultats **enregistrés** ; relancer le modèle est une autre
opération. Le [bilan des preuves](docs/RESEARCH_STATUS.md) conserve les
résultats défavorables : sur ces essais, OCN n'établit pas de supériorité
générale face aux meilleurs témoins classiques.

```sh
.venv/bin/python -m unittest discover -s packages/ocn-core/tests -q
.venv/bin/python experiments/ocn_coupled_documents/verify.py experiments/ocn_coupled_documents/results/run.json
.venv/bin/python experiments/ocn_probe_value_v1/verify.py experiments/ocn_probe_value_v1/results/run.json
.venv/bin/python experiments/ocn_probe_lease_v2/verify.py experiments/ocn_probe_lease_v2/results/run.json
.venv/bin/python experiments/ocn_viability_routes_v3/verify.py experiments/ocn_viability_routes_v3/results/run.json
```

Une inférence nouvelle nécessite un modèle local compatible déjà installé.
Les quatre `run.py` ne sont pas lancés par la CI : ils peuvent consommer des
ressources et leurs sorties ne sont pas des tests déterministes.

## Frontière scientifique

`X`, `t`, `Q` et `T` sont ici des indicateurs numériques normalisés, pas quatre
grandeurs physiques mesurées. La température sert à régler des choix et la
« dissipation » décrit notamment le coût et le retrait sélectif d'information.
La géométrie quaternionique, le produit de Hamilton et les membranes restent
des hypothèses d'architecture. Leur avantage propre et leur interprétation
thermodynamique ne sont pas démontrés. Le noyau opérationnel peut être utile
sans valider toute la théorie.

Le dépôt public est une sélection du laboratoire privé, sans son historique
Git. Les dépendances externes sont documentées dans
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Les contributions et
contre-exemples sont les bienvenus selon [CONTRIBUTING.md](CONTRIBUTING.md).
