# Pixar — Synchronisation GitHub 0.3.1

Application locale Home Assistant OS dédiée à **Pixar Board V2** et à **une seule automatisation de recharge Lenovo/Shelly**.

## Fonctions maintenues

- Synchronisation du JavaScript et des images Pixar, depuis GitHub avec contrôle SHA-256.
- Sauvegarde des fichiers remplacés et restauration en cas de copie échouée.
- Option `auto_resource_version` pour actualiser seulement l’URL de la ressource Pixar V2.
- Aucun changement du tableau de bord lui-même, de ses vues YAML, de ses entités ou des autres appareils.

## Nouveau en 0.3.x

- `auto_automation_sync: true` synchronise uniquement `automations/lenovo-recharge-shelly-40-80.yaml`.
- Cette automatisation commande **uniquement** `switch.cuisine_prise_tablette_ha` en fonction de `sensor.lenovo_tb_x606f_battery_level`.
- Batterie ≤ 40 % : alimentation ON. Batterie ≥ 80 % : alimentation OFF. Contrôle toutes les 5 minutes et au démarrage.
- Si la batterie est indisponible ou sa dernière valeur n’a pas changé depuis 2 h : alimentation ON par précaution **tant que Home Assistant fonctionne**.
- Déploiement via l'éditeur de configuration de Home Assistant, sans éditer directement `automations.yaml`.
- Identifiant fixe ; vérification de l'absence d'un doublon ; sauvegardes datées ; refus d'écraser un changement manuel.
- L'option se désactive à tout moment dans la configuration de Pixar Sync.

**Correctif 0.3.1 :** la liste d'entités Home Assistant peut dépasser 256 Ko ; le synchroniseur lit maintenant des réponses jusqu'à 8 Mo et refuse les réponses tronquées.

**Limites importantes :** si Home Assistant est arrêté alors que la prise est coupée, il ne peut pas la rallumer. Une sécurité indépendante dans la Shelly reste souhaitable. La mise à jour du code de l'application locale n'est pas automatique : une **mise à niveau ponctuelle de 0.2.1 vers 0.3.1** est nécessaire pour activer cette nouvelle capacité.

La licence Fully Kiosk et les réglages d'écran/caméra restent totalement indépendants.

Lire `DOCS.md` avant toute mise à niveau. Aucun jeton d'accès ne doit être placé dans GitHub.
