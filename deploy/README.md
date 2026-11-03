# Déployer l'ITSM sur Azure (France Central)

Infrastructure décrite dans [`containerapps.bicep`](./containerapps.bicep) (research R5) :
une image Docker, une Container App `web` (gunicorn), une Container App `worker`
(Procrastinate : relève mail, synchros, rappels, délais, RGPD), un job `migrate`, PostgreSQL
Flexible Server 16, Blob Storage (pièces jointes), Key Vault (secrets), Container Registry et
Log Analytics. Toutes les ressources sont en **France Central** (constitution III).

Une **identité managée** unique accède à Key Vault, au stockage, au registre et à Microsoft
Graph : aucun secret d'accès Graph ou Blob n'existe.

> Le modèle Bicep a été écrit sans abonnement de test : validez-le d'abord avec
> `az deployment group what-if` sur un groupe de ressources de recette.

## 1. Prérequis

- Azure CLI ≥ 2.60 avec Bicep, rôle *Propriétaire* (ou *Contributeur* + *Administrateur de
  l'accès utilisateur*) sur un groupe de ressources dédié.
- Microsoft Graph PowerShell et Exchange Online PowerShell (étapes 4 et 5), rôles
  *Administrateur de rôle privilégié* (Entra) et *Administrateur Exchange*.
- L'inscription d'application « ITSM » pour la connexion des techniciens :
  [`docs/configuration-entra.md`](../docs/configuration-entra.md), avec l'URI de redirection
  `https://<hôte>/oidc/callback/`.

## 2. Construire et publier l'image

```bash
az group create -n rg-itsm-prod -l francecentral
# Premier passage : créer le registre seul, ou déployer une première fois avec une image publique
# de test, puis :
az acr login -n <registre>
docker build -t <registre>.azurecr.io/itsm:$(date +%Y.%m.%d) .
docker push <registre>.azurecr.io/itsm:$(date +%Y.%m.%d)
```

## 3. Déployer l'infrastructure

```bash
az deployment group what-if -g rg-itsm-prod -f deploy/containerapps.bicep \
  -p image=<registre>.azurecr.io/itsm:<tag> hostName=itsm.armosa.eu \
     oidcClientId=<id application ITSM> \
     postgresAdminPassword=<généré> oidcClientSecret=<secret> djangoSecretKey=<généré>

az deployment group create ...   # mêmes paramètres
az containerapp job start -g rg-itsm-prod -n itsm-migrate   # migrations
```

Les secrets passés en paramètres ne sont stockés que dans Key Vault ; ne les écrivez dans
aucun fichier du dépôt. Générez la clé Django avec
`python -c "import secrets; print(secrets.token_urlsafe(50))"`.

Après chaque nouvelle image : mettre à jour `web`, `worker` et `migrate`, puis lancer le job
`migrate` **avant** de basculer le trafic (les migrations sont réversibles, voir
`scripts/check.sh`).

## 4. Autoriser l'identité managée sur Microsoft Graph

Permissions **applicatives** (contracts/graph-integration.md), lecture seule sauf messagerie :

```powershell
Connect-MgGraph -Scopes "AppRoleAssignment.ReadWrite.All","Application.Read.All"
$mi    = Get-MgServicePrincipal -Filter "displayName eq 'itsm-id'"
$graph = Get-MgServicePrincipal -Filter "appId eq '00000003-0000-0000-c000-000000000000'"
foreach ($p in "User.Read.All","DeviceManagementManagedDevices.Read.All","Mail.ReadWrite","Mail.Send") {
  $role = $graph.AppRoles | Where-Object { $_.Value -eq $p }
  New-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $mi.Id `
    -PrincipalId $mi.Id -ResourceId $graph.Id -AppRoleId $role.Id
}
```

Aucune permission d'écriture sur Entra ou Intune n'est accordée (FR-004).

## 5. Limiter la messagerie aux seules boîtes support (RBAC Exchange)

`Mail.ReadWrite` et `Mail.Send` sont, par défaut, valables sur toutes les boîtes du locataire.
On les **restreint aux boîtes support** avec le RBAC pour les applications d'Exchange Online
(constitution II) :

```powershell
Connect-ExchangeOnline
# 1. Étiqueter les boîtes support
Set-Mailbox support@armosa.eu -CustomAttribute10 "ITSM"
# 2. Portée limitée à ces boîtes
New-ManagementScope -Name "ITSM - boîtes support" `
  -RecipientRestrictionFilter "CustomAttribute10 -eq 'ITSM'"
# 3. Déclarer l'identité managée dans Exchange
New-ServicePrincipal -AppId <managedIdentityClientId> -ObjectId <managedIdentityPrincipalId> `
  -DisplayName "ITSM"
# 4. Rôles applicatifs limités à la portée
foreach ($r in "Application Mail.ReadWrite","Application Mail.Send") {
  New-ManagementRoleAssignment -App <managedIdentityClientId> -Role $r `
    -CustomResourceScope "ITSM - boîtes support"
}
```

Si Exchange refuse de déclarer l'identité managée (`New-ServicePrincipal`), créer une
inscription d'application « ITSM-sync » à certificat, lui appliquer les étapes 4 et 5, et
renseigner `AZURE_CLIENT_ID` / `AZURE_CLIENT_CERTIFICATE_PATH` avec
`ITSM_USE_MANAGED_IDENTITY=false` (research R7).

Puis **retirer** les attributions Graph `Mail.ReadWrite` et `Mail.Send` faites à l'étape 4 :
avec le RBAC Exchange, ce sont les attributions de portée qui s'appliquent, et l'attribution
Graph globale donnerait sinon accès à toutes les boîtes.

**Vérification (quickstart S9-5)** :
`Test-ServicePrincipalAuthorization -Identity <managedIdentityClientId> -Resource autre.boite@armosa.eu`
doit répondre `InScope : False`, et une lecture Graph de cette boîte par l'identité doit
renvoyer 403.

## 6. Paramétrer l'ITSM

Dans l'admin (`/admin/`, rôle administrateur) :

1. **Paramètres** : boîtes support relevées, domaines internes, délais, rétention.
2. **Entités et sites** : rattacher les valeurs `companyName` / `officeLocation` d'Entra.
3. **Synchronisations** : lancer « Utilisateurs Entra » puis « Appareils Intune » et
   vérifier les compteurs (SC-004).
4. **Catégories, outils, groupes, compétences**.

## 7. Sécurité

- Stratégie d'**accès conditionnel** imposant la MFA à l'application « ITSM ».
- Renouveler le secret OIDC avant expiration (mettre à jour le secret `oidc-client-secret`
  dans Key Vault puis redémarrer les révisions).
- Pour une exposition durable, placer PostgreSQL et l'environnement Container Apps dans un
  réseau virtuel (accès privé) et retirer la règle `AllowAzureServices`.
- Sauvegardes PostgreSQL : rétention 14 jours, restauration à un instant donné
  (`az postgres flexible-server restore`) ; test de restauration une fois par trimestre.

## 8. Bascule depuis Atera et retour arrière (constitution V)

1. **Pilote (2 semaines)** : l'ITSM relève une boîte dédiée (`support-itsm@…`) ; Atera reste
   l'outil de référence. Les techniciens traitent les demandes du pilote dans l'ITSM.
2. **Bascule** : quand l'équipe support valide le pilote, rediriger l'adresse publique
   `support@…` vers la boîte relevée par l'ITSM (règle de transport Exchange
   « rediriger vers »), puis désactiver la création de tickets par e-mail dans Atera.
3. **Retour arrière** : supprimer la règle de transport (les e-mails repartent vers Atera),
   réactiver la création par e-mail dans Atera. Les tickets créés dans l'ITSM restent
   consultables et exportables (CSV). Procédure à **tester une fois** avant la bascule.
4. La reprise de l'historique Atera (tickets, inventaire) fait l'objet d'une fonctionnalité
   distincte, avec scripts reproductibles et contrôles de cohérence.

## 9. Exploitation

- Santé : `GET /healthz` (base + relève de moins de 5 minutes), utilisée par la sonde de
  la Container App `web`.
- Journaux JSON dans Log Analytics : `ContainerAppConsoleLogs_CL`.
- Historique des synchronisations et relèves : admin › Exécutions de synchronisation.
- Alertes aux administrateurs par e-mail : 3 échecs consécutifs d'une synchro ou d'une
  relève, tickets d'un technicien désactivé, matériel à récupérer, licences (lundi 8 h).
