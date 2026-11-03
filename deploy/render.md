# Déployer la recette sur Render (Francfort)

Environnement de **recette** décrit par [`render.yaml`](../render.yaml) : un service web
(gunicorn), un worker (Procrastinate : relève mail, synchros, rappels, délais, RGPD) et
PostgreSQL 16, tous dans la région `frankfurt` (UE, constitution III). La production reste
prévue sur Azure ([README.md](./README.md)).

Différences avec Azure :

- pas d'identité managée : Microsoft Graph utilise le **certificat** d'une inscription
  d'application Entra, fourni à Render comme fichier secret ;
- pas de stockage objet : les pièces jointes sont stockées **dans PostgreSQL**
  (`ITSM_ATTACHMENT_STORAGE=database`, `core.storage.DatabaseStorage`), seul espace partagé
  par le web et le worker. Elles sont incluses dans les sauvegardes de la base ; surveiller
  l'espace disque de la base.

## 1. Côté Entra

Pour la recette, **une seule** inscription d'application sert à la connexion des techniciens
(secret client) et à Graph (certificat) : `AZURE_CLIENT_ID` = `OIDC_RP_CLIENT_ID`.

1. Inscription « ITSM (recette) » selon
   [`docs/configuration-entra.md`](../docs/configuration-entra.md) : secret client, rôles
   `ITSM.Technicien` / `ITSM.Administrateur`, affectation requise. L'URI de redirection
   `https://<service>.onrender.com/oidc/callback/` s'ajoute **après** le premier déploiement,
   une fois l'adresse Render connue.
2. Certificat (clé privée + certificat dans un seul fichier PEM, hors du dépôt) :
   `openssl req -x509 -newkey rsa:2048 -nodes -keyout itsm-graph.key -out itsm-graph.crt -days 730 -subj "/CN=ITSM recette Graph"`
   puis `cat itsm-graph.key itsm-graph.crt > itsm-graph.pem`. Charger `itsm-graph.crt` dans
   **Certificats & secrets › Certificats**.
3. **Autorisations d'API** (type *Application*) : `User.Read.All`,
   `DeviceManagementManagedDevices.Read.All`, puis consentement administrateur. Pas de
   `Mail.*` ici : la messagerie est accordée par le RBAC Exchange, limité aux boîtes support
   ([README.md §5](./README.md#5-limiter-la-messagerie-aux-seules-boîtes-support-rbac-exchange),
   avec l'ID d'application et l'ID d'objet de l'application d'entreprise).

## 2. Côté Render

1. **New › Blueprint**, choisir le dépôt et la branche ; Render lit `render.yaml`.
2. Render ne demande pas les variables `sync: false` d'un groupe d'environnement : les
   ajouter à la main dans **Environment Groups › itsm-config** : `ITSM_BASE_URL`,
   `AZURE_TENANT_ID`, `OIDC_RP_CLIENT_ID`, `OIDC_RP_CLIENT_SECRET`, `AZURE_CLIENT_ID`.
3. Dans le même groupe, ajouter le **fichier secret** `itsm-graph.pem` : il est monté dans
   `/etc/secrets/itsm-graph.pem` pour le web et le worker.
4. Le premier déploiement échoue tant que ces valeurs manquent ; relancer ensuite
   **Manual Deploy** sur le web et le worker. Les migrations s'exécutent avant chaque
   déploiement (`preDeployCommand`).

`ALLOWED_HOSTS` et `CSRF_TRUSTED_ORIGINS` reçoivent automatiquement le nom d'hôte Render
(`RENDER_EXTERNAL_HOSTNAME`). Pour un domaine personnalisé, les compléter dans `itsm-config`.

Aucune vérification de santé HTTP n'est configurée : `/healthz` répond 503 tant que la relève
mail n'a pas réussi depuis 5 minutes, ce qui bloquerait le premier déploiement.

## 3. Après le premier déploiement

1. Ajouter l'URI de redirection dans Entra et corriger `ITSM_BASE_URL` si l'adresse diffère.
2. Se connecter avec un compte Administrateur, lancer les synchros Entra et Intune depuis
   l'admin, puis dérouler la recette T103
   ([recette.md](../specs/001-ticketing-gestion-parc/recette.md)).
