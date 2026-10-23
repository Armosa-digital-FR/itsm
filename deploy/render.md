# Déployer la recette sur Render (Francfort)

Environnement de **recette** décrit par [`render.yaml`](../render.yaml) : un service web
(gunicorn), un worker (Procrastinate : relève mail, synchros, rappels, délais, RGPD) et
PostgreSQL 16, tous dans la région `frankfurt` (UE, constitution III). La production reste
prévue sur Azure ([README.md](./README.md)).

Render n'a pas d'identité managée Azure : Graph **et** Blob Storage utilisent une inscription
d'application avec **certificat**, fourni à Render comme fichier secret.

## 1. Côté Azure / Entra

1. **Connexion des techniciens** : application « ITSM » selon
   [`docs/configuration-entra.md`](../docs/configuration-entra.md), avec l'URI de redirection
   `https://<service>.onrender.com/oidc/callback/`.
2. **Identité Graph** : une inscription d'application « ITSM recette – Graph » avec un
   certificat (clé privée + certificat dans un seul fichier PEM). Lui accorder les permissions
   applicatives de [README.md §4](./README.md#4-autoriser-lidentité-managée-sur-microsoft-graph)
   (en remplaçant l'identité managée par son principal de service) et la restreindre aux boîtes
   support de test ([§5](./README.md#5-limiter-la-messagerie-aux-seules-boîtes-support-rbac-exchange)).
3. **Pièces jointes** : un compte de stockage en France Central, conteneur `attachments`,
   accès public désactivé ; donner à l'identité Graph le rôle *Contributeur aux données Blob
   du stockage* sur ce compte.

## 2. Côté Render

1. **New › Blueprint**, choisir le dépôt et la branche ; Render lit `render.yaml`.
2. Renseigner les valeurs demandées (`sync: false`) : `ITSM_BASE_URL`, `AZURE_TENANT_ID`,
   `OIDC_RP_CLIENT_ID`, `OIDC_RP_CLIENT_SECRET`, `AZURE_CLIENT_ID` (identité Graph),
   `AZURE_STORAGE_ACCOUNT_NAME`.
3. Dans le groupe d'environnement `itsm-config`, ajouter le **fichier secret**
   `itsm-graph.pem` (le PEM de l'identité Graph) : il est monté dans
   `/etc/secrets/itsm-graph.pem` pour le web et le worker.
4. Les migrations s'exécutent avant chaque déploiement (`preDeployCommand`).

`ALLOWED_HOSTS` et `CSRF_TRUSTED_ORIGINS` reçoivent automatiquement le nom d'hôte Render
(`RENDER_EXTERNAL_HOSTNAME`). Pour un domaine personnalisé, les compléter dans `itsm-config`.

Aucune vérification de santé HTTP n'est configurée : `/healthz` répond 503 tant que la relève
mail n'a pas réussi depuis 5 minutes, ce qui bloquerait le premier déploiement.

## 3. Après le premier déploiement

Se connecter avec un compte Administrateur, lancer les synchros Entra et Intune depuis l'admin,
puis dérouler la recette T103 ([recette.md](../specs/001-ticketing-gestion-parc/recette.md)).
