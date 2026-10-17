# Frontière de sécurité de la préversion

OCN est une bibliothèque expérimentale, pas une enceinte de sécurité
universelle. Son installation n'active aucun service réseau, agent autonome ou
accès à la maison. Les adaptateurs locaux qui interrogent un modèle utilisent
par défaut l'API Ollama sur `127.0.0.1:11434` lorsqu'ils sont appelés.

Les documents à lire doivent être choisis par l'opérateur. La vérification des
chemins, versions et empreintes ne prouve pas la vérité du contenu. Ne pas
confier au prototype des secrets, données de santé ou documents personnels
pour un essai public ou une demande d'assistance.

`ocn_core.agent_integration.PinnedSynthesizer` exécute le module Python épinglé
avec les **droits du processus hôte**. L'empreinte prouve l'identité des octets,
pas leur innocuité. Ce mode n'est destiné qu'au code déjà approuvé et relu.
Les essais `sandbox_trial` exigent Bubblewrap et échouent s'il manque ; ils ne
constituent pas une garantie générale contre tout code malveillant. Un modèle
ou une intégration reçue d'un tiers ne doit pas passer directement en mode
non isolé. Les mainteneurs doivent auditer le code et les permissions avant
toute activation sur une machine contenant des données privées.

La CI incluse n'utilise ni clé ni service domestique et exécute seulement des
tests hors ligne et des rejeux de traces enregistrées. Elle n'est pas une
certification de sûreté. Si vous trouvez une vulnérabilité, ne publiez pas de
secret ni de preuve d'exploitation contenant des données privées dans une
issue publique ; utilisez le signalement privé GitHub si cette fonctionnalité
est activée pour le dépôt.
