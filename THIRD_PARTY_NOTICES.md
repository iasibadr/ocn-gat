# Dépendances et contenus externes

Le dépôt sélectionné ne contient ni poids de modèle, ni corpus privé, ni copie
du code de NumPy, smolagents ou Ollama. `numpy>=1.24,<3` est installé comme
dépendance du noyau. L'intégration facultative `smolagents==1.26.0` est
installée séparément ; elle conserve sa licence Apache-2.0. Les expériences
avec `qwen3.5:9b` nécessitent un modèle local installé séparément et ses
conditions d'utilisation restent celles de sa distribution.

Les fichiers `experiments/*/results/*.json` sélectionnés sont des traces OCN
de scénarios synthétiques, pas le corpus ou les poids du modèle. Leurs
protocoles et limites sont indiqués dans chaque dossier. La licence MIT de ce
dépôt s'applique aux éléments originaux OCN, pas aux logiciels ou modèles
installés séparément.
