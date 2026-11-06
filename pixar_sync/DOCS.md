# Pixar Sync 0.4.1 — fichiers de la page Tesla 3D

**Nouveauté 0.4.1 :** installe aussi, depuis une liste fermée, le moteur 3D Three.js (`pixar/vendor/three/`) et le modèle 3D allégé (`pixar/tesla/tesla-model-3-lite.glb`, 8 Mo maximum) dans `/local/pixar-board/`. Seuls les dossiers `tesla`, `vendor` et `vendor/three` peuvent être créés, à l'intérieur du dossier Pixar existant. Même contrôle SHA-256 par `manifest.sha256`, même sauvegarde avant remplacement. Mise à niveau : remplacer le dossier `pixar_sync` dans `local_apps` puis **Mettre à jour**, comme pour la 0.4.0 ; les options sont conservées.

---

# Pixar Sync 0.4.0 — tableau de bord Pixar synchronisé depuis GitHub

**Nouveauté 0.4.0 :** option `auto_dashboard_sync` (désactivée par défaut). Une fois activée, le tableau de bord `pixar-board-v2` est mis à jour automatiquement à partir du fichier `dashboard-updates/pixar-board-v2.yaml` du dépôt, à chaque contrôle (5 à 15 minutes).

## Fonctionnement et sécurité

- Un **seul tableau** est concerné : `pixar-board-v2`, en mode storage. Les autres tableaux, les ressources, `configuration.yaml` et `.storage` ne sont jamais touchés.
- Le fichier doit figurer dans `manifest.sha256` avec la bonne empreinte, sinon rien n'est appliqué.
- Contrôles avant écriture : YAML valide, vue `accueil` avec la stratégie `custom:pixar-board-v2`, chemins de vues uniques, et **aucune vue existante ne doit disparaître**.
- Sauvegarde de la configuration actuelle dans `/data/dashboard-backups` (10 dernières) avant chaque écriture, par l'API officielle `lovelace/config/save`.
- Relecture après écriture ; si le résultat ne correspond pas, la configuration précédente est restaurée automatiquement.
- **Modification manuelle protégée :** si le tableau a été modifié dans l'éditeur de Home Assistant depuis la dernière synchronisation, le synchroniseur refuse d'écraser et l'écrit dans le journal (`edited by hand`). Pour reprendre : recopier la configuration brute actuelle dans le fichier GitHub, puis supprimer `/data/dashboard-sync-state.json` (ou réinstaller l'application).
- Journal : `[pixar-dashboard] Dashboard updated and verified` puis `already up to date`.

## Mise en service (une seule fois)

1. Faire une sauvegarde complète de Home Assistant.
2. Remplacer le dossier `pixar_sync` dans `smb://192.168.0.120/local_apps` par la version 0.4.0 complète (le nouveau fichier `dashboard_sync.js` est indispensable), sans désinstaller l'application.
3. **Paramètres → Applications → ⋮ → Vérifier les mises à jour**, puis **Mettre à jour** Pixar — Synchronisation GitHub vers 0.4.0.
4. Dans **Configuration**, activer `auto_dashboard_sync`, enregistrer, redémarrer l'application.
5. Ne plus modifier le tableau Pixar dans l'éditeur de Home Assistant : passer par le fichier GitHub.

Retour arrière : désactiver `auto_dashboard_sync`. La configuration déjà appliquée reste en place ; les sauvegardes restent dans `/data/dashboard-backups`.

---

# Pixar Sync 0.3.1 — activation et contrôles

**Correctif 0.3.1 :** corrige l'erreur `JSONDecodeError: Unterminated string` causée par la limite à 256 Ko lors de la lecture des entités de Home Assistant. Si la V0.3.0 est déjà installée, remplacer le dossier local et mettre à jour vers V0.3.1, sans désinstaller pour conserver le jeton GitHub et les options.


Cette version ajoute la synchronisation automatique d'une **seule automatisation Home Assistant** (charge Lenovo via prise Shelly de la cuisine). Les mises à jour Pixar Board V2 précédemment validées sont conservées.

## Installation ponctuelle (depuis le Mac)

1. **Faire une sauvegarde complète de Home Assistant** avant de modifier une application locale.
2. Depuis GitHub, récupérer le dossier `local_apps/pixar_sync` **dans son intégralité** (version 0.3.1). Ne pas copier seulement `automation_sync.py` : il faut aussi le nouveau `Dockerfile`, `updater.py` et `config.yaml`.
3. Dans Finder, ouvrir `smb://192.168.0.120/local_apps`. Remplacer le dossier `pixar_sync` par la version 0.3.1 **sans désinstaller l'application**. Garder une copie de l'ancien dossier.
4. Dans Home Assistant : **Paramètres → Applications → Installer une application → ⋮ → Vérifier les mises à jour**, puis ouvrir **Pixar — Synchronisation GitHub** et cliquer **Mettre à jour** vers **0.3.0**. Selon la version de l'interface, l'entrée « Vérifier les mises à jour » peut être située ailleurs.
5. Vérifier dans **Configuration** : `enabled: true`, `auto_automation_sync: true`, intervalle habituel, et conserver `auto_resource_version` dans son état validé. **Ne jamais copier le jeton GitHub dans le chat ou dans un dépôt**.
6. Ouvrir **Journal** ; attendre le contrôle suivant. Chercher : `[pixar-automation] Lenovo charging automation deployed and verified` puis, aux contrôles suivants, `already up to date`.
7. Vérifier **Paramètres → Automatisations et scènes** : `Lenovo - Charge automatique Shelly 40-80 %`. Contrôler l'état de la prise et le niveau de batterie. Il n'y a pas de test réel tant que le nouveau journal n'a pas confirmé le déploiement.

L'application ne se met **pas** à niveau elle-même : cette première installation de la version 0.3.1 reste nécessaire. Les **modifications ultérieures du fichier d'automatisation autorisé** seront alors synchronisées toutes les 5 à 15 minutes selon ton réglage.

## Sécurité du synchroniseur

- Le programme accepte **un seul chemin GitHub** : `automations/lenovo-recharge-shelly-40-80.yaml`.
- Le SHA-256 doit correspondre à `manifest.sha256` ; la structure des actions, du capteur, de la prise et des seuils est contrôlée.
- Il utilise l'API de l'éditeur des automatisations de Home Assistant avec le jeton Supervisor existant et `homeassistant_api: true`.
- Il ne touche ni à `configuration.yaml`, ni à `automations.yaml`, ni à `.storage`, ni aux autres automatisations.
- Identifiant unique `pixar_sync_lenovo_charge_40_80_v1`. Si cet identifiant ou son nom existe déjà sans provenance connue, l'installation est bloquée.
- Un enregistrement local dans `/data/automation-sync-state.json` protège contre l'écrasement de modifications manuelles.
- Les sauvegardes sont conservées dans `/data/automation-backups` ; aucune sauvegarde n'est envoyée à GitHub.
- L'API de configuration des automatisations est une API interne de Home Assistant et peut évoluer. Si l'API ne répond pas ou refuse une requête, le synchroniseur s'arrête sans modifier les autres automatisations.
- Une erreur de déploiement est visible dans le journal : `[pixar-sync] Sync aborted safely:`.

## Sécurité de la batterie

- Batterie ≤ 40 % : la Shelly est allumée.
- Batterie ≥ 80 % : la Shelly est éteinte.
- Entre les deux : aucun changement de la prise.
- Niveau inconnu, indisponible ou mesure âgée de plus de 2 h : la Shelly est allumée à titre conservatoire.
- L'automatisation est relancée lors d'un changement de valeur, toutes les 5 minutes et au démarrage de Home Assistant.

**Attention :** cette dernière sécurité **ne fonctionne pas si Home Assistant est arrêté** ou si le réseau Shelly est inaccessible. La tablette peut se vider si la Shelly était OFF. Prévoir si nécessaire une limite de durée d'extinction directement dans la Shelly (fonction de remise sous tension automatique, selon firmware), après vérification du modèle.

## Retour arrière

Pour désactiver immédiatement les futurs déploiements de l'automatisation, passer `auto_automation_sync: false` dans l'application et enregistrer.

Cela **ne désactive pas** une automatisation déjà installée. Pour stopper la recharge automatique, désactiver `Lenovo - Charge automatique Shelly 40-80 %` depuis l'interface Home Assistant, puis mettre manuellement la prise ON au besoin. Ne pas supprimer le fichier GitHub en espérant que le synchroniseur efface l'automatisation : il ne supprime jamais d'automatisations.

Les sauvegardes locales sont disponibles dans `/data/automation-backups`. Une mise à niveau ou un retour à 0.2.1 n'efface pas les automatisations Home Assistant déjà créées.

## Référence de l'ancienne version

0.2.1 avait corrigé la transmission de `SUPERVISOR_TOKEN` par S6. L'option `auto_resource_version` est maintenue à l'identique dans 0.3.0 ; la nouvelle fonction ne modifie pas le mécanisme Pixar.
