# Contrat — Intégration Microsoft Graph (Entra, Intune, Exchange Online)

Graph v1.0, jetons applicatifs (identité managée en Azure, certificat en local). Voir
[research.md](../research.md) R7 à R11 pour les justifications.

## Inscription d'application et permissions

| Élément | Valeur |
|---|---|
| Application de connexion (OIDC) | « ITSM », redirection `https://<hôte>/oidc/callback/`, rôles d'application `ITSM.Technicien`, `ITSM.Administrateur`, affectation obligatoire |
| Identité de l'application pour Graph | identité managée de l'environnement (ou application « ITSM-sync » à certificat hors Azure) |
| `User.Read.All` (application) | synchro Entra |
| `DeviceManagementManagedDevices.Read.All` (application) | synchro Intune |
| `Mail.ReadWrite`, `Mail.Send` (application) | boîtes support, **portée limitée aux boîtes support** par le RBAC Exchange Online pour les applications |

Aucune permission d'écriture sur Entra ou Intune (FR-004). Un test de recette vérifie qu'un
appel `Mail.Read` sur une boîte non support est refusé.

## Appels utilisés

| Usage | Appel | Fréquence |
|---|---|---|
| Utilisateurs (delta) | `GET /users/delta?$select=id,displayName,givenName,surname,mail,userPrincipalName,companyName,officeLocation,department,jobTitle,accountEnabled,manager` | 30 min ; complète chaque nuit |
| Appareils | `GET /deviceManagement/managedDevices?$select=id,deviceName,manufacturer,model,serialNumber,operatingSystem,osVersion,userId,userPrincipalName,lastSyncDateTime,enrolledDateTime,managedDeviceOwnerType` | 1 h |
| Relève | `GET /users/{boîte}/mailFolders/inbox/messages/delta?$select=id,internetMessageId,conversationId,subject,from,body,uniqueBody,receivedDateTime,hasAttachments,internetMessageHeaders` | 1 min |
| Pièces jointes | `GET /users/{boîte}/messages/{id}/attachments` | à la relève |
| Classement | `POST /users/{boîte}/messages/{id}/move` (dossiers « ITSM/Traités », « ITSM/Ignorés » créés au premier passage) | à la relève |
| Envoi | `POST /users/{boîte}/messages` (brouillon → `internetMessageId`) puis `POST /users/{boîte}/messages/{id}/send` | à la demande |

## Correspondances de champs

### Entra → `DirectoryUser`

| Graph | ITSM |
|---|---|
| `id` | `entra_id` |
| `displayName`, `givenName`, `surname`, `jobTitle`, `department` | mêmes champs |
| `mail` (à défaut `userPrincipalName`) | `email` |
| `userPrincipalName` | `upn` |
| `companyName` | `subsidiary` via `Subsidiary.entra_company_names` (création si inconnue) |
| `officeLocation` | `site` via `Site.entra_office_locations` (création si inconnu) |
| `manager` | `manager` |
| `accountEnabled = false` ou `@removed` | `is_active = false`, `deactivated_at` |

### Intune → `Equipment`

| Graph | ITSM |
|---|---|
| `id` | `intune_id` |
| `deviceName` | `name` |
| `manufacturer`, `model`, `osVersion` | mêmes champs |
| `operatingSystem` | `os` ; type : Windows/macOS → PC, iOS/Android → Téléphone, iPadOS → Tablette |
| `serialNumber` | `serial_number` normalisé (rapprochement FR-003) |
| `userId` | `intune_primary_user` (et `assigned_to` à la création) |
| `lastSyncDateTime`, `enrolledDateTime` | `intune_last_sync_at`, `intune_enrolled_at` |
| absent du résultat complet | `intune_removed_at` = maintenant (si vide) |
| réapparu | `intune_removed_at` vidé, événement `retour_intune` |

## Gestion des erreurs

| Situation | Comportement |
|---|---|
| `429` / `503` | attente `Retry-After` (défaut 30 s), 5 tentatives max, puis échec du `SyncRun` |
| `401` / `403` | échec immédiat du `SyncRun`, alerte administrateurs (permission manquante) |
| jeton delta expiré (`410`) | synchro complète immédiate |
| échec en cours de synchro | transaction par page : les données déjà traitées sont conservées ; aucune désactivation déduite d'une synchro incomplète |
| Graph indisponible | données existantes inchangées ; nouvelle tentative au cycle suivant (cas limite) |

Les journaux n'enregistrent ni corps d'e-mail, ni jeton, ni en-tête d'autorisation.
