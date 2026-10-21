# Phase 0 — Recherche et décisions : ticketing et gestion de parc

**Feature** : `001-ticketing-gestion-parc` | **Date** : 2026-10-21 | **Plan** : [plan.md](./plan.md)

Ce document tranche chaque inconnue du contexte technique. La constitution laisse la pile
ouverte : les choix ci-dessous sont faits au regard des principes I (simplicité) et II
(sécurité), du contexte Microsoft 365 existant (Entra, Intune, Exchange Online) et de la
volumétrie clarifiée (500 utilisateurs, 1 000 équipements, 300 tickets/mois, ≤ 10 techniciens).

Toutes les décisions ont été validées par l'équipe le 2026-10-21 (pile, hébergement,
TeamViewer hors application, couleurs d'état, ordre de livraison).

---

## R1. Langage et framework applicatif — validé le 2026-10-21

- **Decision** : Python 3.12 + Django 5.2 LTS, en monolithe modulaire (un dépôt, un déployable).
- **Rationale** :
  - Django fournit d'origine ce dont l'ITSM a besoin : ORM et migrations versionnées et
    réversibles (exigence « Workflow » de la constitution), authentification et permissions,
    formulaires validés côté serveur, protection CSRF/XSS, et surtout **l'admin Django**, qui
    couvre sans développement spécifique toute l'administration des référentiels (catégories,
    outils, compétences, groupes, types d'équipement, sites, paramètres). C'est le levier
    principal de simplicité (principe I).
  - Version LTS supportée jusqu'en avril 2028 : pas de montée de version majeure imposée
    pendant la migration depuis Atera.
  - Écosystème Python mature pour Microsoft Graph (`azure-identity`, `httpx`) et pour le futur
    volet IA (principe IV).
- **Alternatives considered** :
  - *TypeScript (Next.js/NestJS + React)* : interface plus riche, mais deux applications
    (API + front) et un back-office d'administration à écrire ; rejeté pour l'effort.
  - *.NET (ASP.NET Core + Blazor)* : excellente intégration Microsoft, mais pas d'équivalent
    de l'admin Django ; à retenir uniquement si l'équipe maîtrise C# et pas Python.

## R2. Interface utilisateur

- **Decision** : rendu serveur (templates Django) + **HTMX 2** pour les interactions partielles
  (changement de statut, ajout de note, saisie de temps, filtres de listes, recherche d'un
  utilisateur dans l'annuaire). Pas de framework JavaScript, pas d'étape de build front.
  CSS écrit à la main à partir des tokens du design system Armosa exposés en variables CSS.
- **Rationale** : ≤ 10 utilisateurs simultanés et des écrans de type formulaire/liste ; HTMX
  donne une interface réactive sans dupliquer la logique côté client. Une seule base de code
  à tester. L'admin Django est thémé avec les mêmes variables CSS.
- **Alternatives considered** : SPA React/Vue (rejetée : API + front + état client pour un
  bénéfice faible à cette échelle) ; Tailwind (rejeté : build supplémentaire, et le design
  system fournit déjà ses tokens).

## R3. Base de données et recherche

- **Decision** : PostgreSQL 16. Recherche plein texte native PostgreSQL (`tsvector` en colonne
  générée + index GIN, configuration `french` combinée à `unaccent`) pour la base de résolution
  (FR-041, FR-042).
- **Rationale** : quelques milliers de tickets par an : la recherche native de PostgreSQL suffit
  largement (classement `ts_rank`, racinisation française, insensibilité aux accents) sans
  moteur dédié. Une seule brique de stockage à opérer et sauvegarder.
- **Alternatives considered** : Elasticsearch/OpenSearch, Meilisearch (rejetés : service
  supplémentaire injustifié à ce volume) ; recherche `ILIKE` (rejetée : ni racinisation ni
  classement).

## R4. Tâches planifiées et asynchrones

- **Decision** : **Procrastinate** (file de tâches adossée à PostgreSQL, intégration Django,
  tâches périodiques), exécuté dans un processus *worker* séparé du serveur web, avec la même
  image applicative.
- **Rationale** : l'ITSM a besoin de tâches périodiques (synchros Entra/Intune, relève des
  boîtes mail, rappels, alertes de délai, fermeture automatique, purge RGPD) et de tâches
  ponctuelles (envoi d'e-mails hors requête). Procrastinate s'appuie sur la base PostgreSQL
  existante : pas de Redis ni de broker à exploiter, verrouillage transactionnel, reprise
  après échec, tâches périodiques sans planificateur externe.
- **Alternatives considered** :
  - *Celery + Redis* : standard mais deux composants de plus (broker + beat) ; rejeté (I).
  - *Cron système + commandes `manage.py`* : simple, mais pas de reprise, pas de file pour les
    envois d'e-mails, et pas de cron natif en conteneur PaaS ; rejeté.
  - *Framework de tâches de Django 6* : backends de production encore immatures ; à réévaluer.

## R5. Hébergement — validé le 2026-10-21

- **Decision** : Microsoft Azure, région **France Central** :
  - Azure Container Apps : une application `web` (gunicorn) et une application `worker`
    (Procrastinate), même image Docker ;
  - Azure Database for PostgreSQL – Flexible Server (sauvegardes automatiques, restauration à
    un instant donné) ;
  - Azure Blob Storage (pièces jointes, chiffrement au repos) ;
  - Azure Key Vault (secrets) ; **identité managée** pour accéder à Key Vault, Blob et Graph ;
  - Azure Monitor / Log Analytics (journaux JSON des conteneurs).
- **Rationale** : le tenant Microsoft 365 existe déjà (Entra, Intune, Exchange) ; l'identité
  managée supprime tout secret pour Graph, Blob et Key Vault (principe II) ; hébergement UE
  et chiffrement au repos natifs (principe III). Le conteneur Docker garde la solution
  portable vers un autre hébergeur (principe V : pas de nouvel enfermement).
- **Alternatives considered** : serveur interne ou VM (rejeté par défaut : sauvegardes,
  correctifs et TLS à opérer soi-même) ; OVHcloud/Scaleway (viables, mais sans identité
  managée vers Graph : un certificat d'application à gérer).

## R6. Authentification et rôles (FR-070)

- **Decision** : OpenID Connect avec Microsoft Entra ID (bibliothèque `mozilla-django-oidc`),
  application Entra dédiée « ITSM ». Les rôles sont des **rôles d'application Entra**
  (`ITSM.Technicien`, `ITSM.Administrateur`) attribués à des groupes Entra et lus dans la revendication
  `roles` du jeton à chaque connexion. Sans rôle : accès refusé (403). La MFA est imposée par
  une stratégie d'accès conditionnel Entra ciblant l'application.
- **Rationale** : pas de mot de passe stocké, gestion des droits centralisée dans Entra
  (moindre privilège, révocation immédiate au départ d'un collaborateur), MFA déléguée à
  l'accès conditionnel. Le compte applicatif est créé au premier login et rattaché à
  l'utilisateur d'annuaire par l'identifiant objet Entra (`oid`).
- **Alternatives considered** : `django-allauth` (plus large que nécessaire) ; MSAL avec flux
  maison (plus de code de sécurité à maintenir) ; rôles gérés dans l'ITSM (rejeté : double
  source de vérité).

## R7. Accès Microsoft Graph (Entra, Intune, Exchange)

- **Decision** : appels REST Microsoft Graph v1.0 via `httpx`, jetons applicatifs obtenus
  par `azure-identity` (`ManagedIdentityCredential` en Azure, `ClientCertificateCredential` en
  local/recette). Un client Graph unique et mince (pagination `@odata.nextLink`, reprise sur
  `429`/`503` en respectant `Retry-After`), plutôt que le SDK `msgraph-sdk`.
- **Permissions applicatives (lecture seule sauf messagerie)** :
  - `User.Read.All` : utilisateurs et responsables ;
  - `DeviceManagementManagedDevices.Read.All` : appareils Intune ;
  - `Mail.ReadWrite` et `Mail.Send` : **restreintes aux seules boîtes support** via le RBAC
    Exchange Online pour les applications (portée de gestion limitée aux boîtes support).
- **Rationale** : seul un petit nombre de points d'accès est utilisé ; le client mince est
  plus simple à tester (simulation avec `respx`) que le SDK généré, asynchrone et volumineux.
  FR-004 (lecture seule Entra/Intune) est garanti par les permissions elles-mêmes.
- **Alternatives considered** : SDK `msgraph-sdk` (rejeté : dépendance lourde, API
  asynchrone) ; IMAP/SMTP pour la messagerie (rejeté : authentification basique désactivée
  dans Exchange Online, OAuth IMAP plus complexe que Graph).

## R8. Synchronisation Entra (FR-001, US5)

- **Decision** : requête delta `GET /users/delta` (sélection : `id`, `displayName`,
  `givenName`, `surname`, `mail`, `userPrincipalName`, `companyName`, `officeLocation`,
  `department`, `jobTitle`, `accountEnabled`, `manager`) toutes les **30 minutes** ; jeton
  delta conservé en base. Synchronisation complète de réconciliation chaque nuit.
- **Correspondances** : filiale ← `companyName` ; site ← `officeLocation` ; service ←
  `department`. Une filiale ou un site inconnu est créé automatiquement puis administrable.
  La table de correspondance attribut → filiale est paramétrable si `companyName` n'est pas
  renseigné de façon homogène dans Entra.
- **Comptes désactivés ou supprimés** : l'utilisateur passe inactif (jamais supprimé), ses
  compétences et appartenances aux groupes de techniciens sont retirées, ses tickets ouverts
  sont signalés à réaffecter, et une alerte liste les équipements encore affectés (US5-2).
- **Rationale** : le delta limite le volume et la charge sur Graph ; la réconciliation
  nocturne rattrape un jeton delta expiré.

## R9. Synchronisation Intune (FR-002, FR-003, US4)

- **Decision** : `GET /deviceManagement/managedDevices` (sélection : `id`, `deviceName`,
  `manufacturer`, `model`, `serialNumber`, `operatingSystem`, `osVersion`, `userId`,
  `userPrincipalName`, `lastSyncDateTime`, `enrolledDateTime`, `managedDeviceOwnerType`)
  **toutes les heures**, en synchronisation complète (l'API `managedDevices` n'offre pas de
  requête delta ; 1 000 appareils ≈ une dizaine de pages).
- **Rapprochement** : 1) par identifiant Intune déjà connu ; 2) sinon par numéro de série
  normalisé (majuscules, sans espaces) avec un équipement manuel → l'équipement manuel
  devient « source Intune » (FR-003, US4-5) ; 3) sinon création. Numéros de série vides ou
  génériques (« To Be Filled By O.E.M. », « 0 », « Default string ») exclus du rapprochement.
- **Type** : Windows/macOS → PC ; iOS/Android → Téléphone ; iPadOS → Tablette (type ajouté
  au référentiel, extensible par FR-060).
- **Appareil absent d'Intune** : la fiche est marquée « retirée d'Intune » avec la date, jamais
  supprimée (cas limite de la spec).
- **Statut automatique** : un appareil Intune avec un utilisateur principal est « en
  utilisation » à sa création ; ensuite le statut reste géré dans l'ITSM (FR-062).

## R10. Messagerie entrante (FR-010 à FR-013, SC-001)

- **Decision** : relève **chaque minute** de chaque boîte support par requête delta Graph
  `GET /users/{boîte}/mailFolders/inbox/messages/delta`. Chaque message traité est déplacé dans
  un dossier « ITSM/Traités » (ou « ITSM/Ignorés »), ce qui rend le traitement idempotent et
  visible des administrateurs de messagerie. L'identifiant Internet du message est enregistré
  pour empêcher tout doublon.
- **Rattachement à un ticket existant** (dans l'ordre) :
  1. référence `[T-00042]` dans l'objet ;
  2. en-têtes `In-Reply-To` / `References` correspondant à un message envoyé par l'ITSM ;
  3. `conversationId` Exchange déjà associé à un ticket.
  Sinon : nouveau ticket. Ticket « fermé » → nouveau ticket lié à l'ancien (cas limite).
- **E-mails automatiques ignorés** (pas de ticket, pas d'accusé) : en-tête `Auto-Submitted`
  différent de `no`, `X-Auto-Response-Suppress`, `Precedence: bulk|junk|list`, présence de
  `List-Id`, expéditeur de type `noreply`/`mailer-daemon`/`postmaster`, expéditeur égal à une
  boîte support (anti-boucle), et plafond de 20 messages/heure par expéditeur.
- **Expéditeur inconnu** : ticket créé avec demandeur « non identifié » (adresse conservée).
  L'accusé de réception n'est envoyé que si le domaine de l'expéditeur fait partie des
  domaines internes paramétrés (évite de répondre au spam et la rétrodiffusion).
- **Corps** : le HTML est assaini (`nh3`, liste blanche de balises) avant stockage et affichage ;
  la version texte est conservée pour la recherche. L'historique cité d'une réponse
  (séparateurs Outlook « De : », « From: », « Le … a écrit : ») est replié à l'affichage, pas
  supprimé.
- **Pièces jointes** : stockées dans Blob Storage, 25 Mo maximum par fichier ; les images
  inline (`cid:`) sont conservées comme pièces jointes et réaffichées.
- **Alternatives considered** : notifications Graph (webhooks) : latence plus faible mais
  nécessite un point d'entrée public et le renouvellement des abonnements ; rejeté au regard
  de SC-001 (5 minutes) que la relève minute satisfait.

## R11. Messagerie sortante (FR-012, FR-031, FR-034, FR-038)

- **Decision** : envoi depuis la boîte support via Graph en deux temps (création d'un brouillon
  `POST /users/{boîte}/messages` puis `POST …/send`) pour connaître l'identifiant Internet du
  message envoyé, nécessaire au rattachement des réponses (R10). Objet toujours préfixé de
  `[T-xxxxx]`. Envois exécutés en tâche asynchrone avec trois tentatives.
- **Gabarits** : gabarits Django HTML (styles en ligne, logo PNG en pièce jointe inline `cid:`)
  + version texte. Le SVG n'est pas utilisé dans les e-mails (non supporté par Outlook).
- **Liste fermée des e-mails au demandeur** (FR-038) : accusé de réception, note externe,
  rappel, résolution (dont automatique). Aucun autre événement n'envoie d'e-mail au demandeur.
- **Alertes techniciens** (dépassement de délai, sync en échec, licences) : e-mail à
  l'adresse du technicien ou des membres du groupe affecté + indicateur dans l'interface.

## R12. Calendrier ouvré, délais et rappels (FR-033 à FR-037)

- **Decision** : module de calcul maison `business_time` : plages ouvrées paramétrables
  (lundi–vendredi, 9 h–18 h, `Europe/Paris`), jours fériés français fournis par la
  bibliothèque `holidays` (France métropolitaine), plus jours de fermeture saisis par
  l'administrateur. Fonctions : ajouter une durée ouvrée à un instant, mesurer la durée
  ouvrée entre deux instants.
- **Délai de prise en compte** : échéance = création + cible de la priorité (haute 1 h,
  normale 4 h, basse 9 h ouvrées = 1 jour ouvré). Recalculée si la priorité change avant la
  prise en compte. Une tâche toutes les 5 minutes marque les tickets en dépassement et alerte
  une seule fois par ticket.
- **Rappels** : à l'entrée en « en attente de réponse », compteur remis à zéro ; tâche
  horaire : rappel après 2 jours ouvrés sans réponse depuis l'entrée ou le dernier rappel,
  3 rappels maximum ; 2 jours ouvrés après le 3e rappel → résolution automatique « sans
  réponse du demandeur » (au plus 8 jours ouvrés, conforme à SC-007).
- **Fermeture automatique** : 5 jours ouvrés après la résolution.
- **Rationale** : la logique est petite, critique et doit être testée finement (constitution :
  tests obligatoires sur le calcul des délais) ; aucune bibliothèque de calendrier ouvré ne
  couvre proprement fuseau + plages + fériés.

## R13. Prise en main à distance (FR-050, US7) — décidé le 2026-10-21

- **Decision** : **TeamViewer, hors application** (choix de l'équipe). L'ITSM ne lance ni ne
  pilote TeamViewer et n'appelle aucune API TeamViewer. Il stocke un champ « identifiant
  TeamViewer » par équipement, l'affiche avec un bouton de copie sur la fiche de l'appareil et
  sur les tickets liés, et permet au technicien de **déclarer** une intervention réalisée
  (appareil, début, fin) dans le ticket. La déclaration crée un événement de ticket et une
  entrée d'audit `remote_session.declare`.
- **Rationale** : respecte le choix « non intégré » tout en conservant la traçabilité exigée
  par US7 et FR-071 ; aucun secret ni connecteur éditeur à gérer (principes I et II). Les
  journaux de connexion détaillés restent ceux de la console TeamViewer.
- **Alternatives considered** : lien de lancement `https://start.teamviewer.com/<id>` (écarté :
  l'équipe ne veut pas d'intégration pour l'instant ; ajout trivial plus tard) ; API TeamViewer
  pour récupérer automatiquement les sessions (écartée : intégration, compte API à gérer).

## R14. Historique, audit et intégrité

- **Decision** :
  - historique métier : tables d'événements explicites `TicketEvent` et `EquipmentEvent`
    (auteur, date, type, ancienne/nouvelle valeur), écrites par la couche service, affichées
    telles quelles (FR-040, FR-063) ;
  - journal d'audit de sécurité `AuditEntry` distinct (FR-071 et constitution II), en ajout
    seul : un déclencheur PostgreSQL refuse `UPDATE` et `DELETE` (hors purge de rétention
    exécutée par une fonction dédiée).
- **Alternatives considered** : `django-simple-history` (copie complète de chaque ligne,
  illisible pour l'historique d'un ticket et non distincte de l'audit) ; rejeté.

## R15. RGPD : rétention, anonymisation, droits des personnes (FR-072, constitution III)

- **Decision** :
  - tâche quotidienne : tickets fermés depuis plus de 3 ans (paramétrable) → suppression des
    notes, pièces jointes et corps d'e-mails ; demandeur remplacé par « anonymisé » ;
    adresses e-mail, numéros de téléphone et nom du demandeur masqués dans le titre et la
    résolution ; catégorie, outil, dates, priorité et résolution masquée conservées (base de
    résolution, FR-072) ;
  - saisie de la résolution : aide à l'écran rappelant de ne pas y mettre de données
    personnelles ;
  - utilisateurs d'annuaire inactifs depuis plus de 3 ans et sans ticket ni équipement non
    anonymisé : anonymisés ;
  - journal d'audit : conservé 3 ans, puis purgé ;
  - droits des personnes, depuis l'admin : **export** (JSON) de toutes les données d'un
    utilisateur et **anonymisation anticipée** sur demande ; la rectification se fait dans Entra
    (source de vérité).
- **Polices** : EB Garamond, IBM Plex Sans et IBM Plex Mono sont **auto-hébergées** (fichiers
  woff2 sous licence OFL) plutôt que chargées depuis Google Fonts, pour ne pas transmettre
  l'adresse IP des utilisateurs à un tiers.
- **Données traitées (pour le registre)** : identité professionnelle, e-mail, filiale, site,
  service et responsable des collaborateurs ; contenu des échanges de support ; inventaire
  des équipements affectés. Finalité : support informatique interne et gestion du parc.

## R16. Identité visuelle (FR-080)

- **Decision** : tokens du design system « Armosa » transcrits en variables CSS
  (`static/css/tokens.css`) ; polices auto-hébergées (R15) ; logo PNG (824×113) pour les
  e-mails, SVG pour l'interface après recadrage de la `viewBox` (le fichier fourni est une
  planche Illustrator de 1190×842 avec marges).
- **Lacune comblée — couleurs d'état** (absentes du design system, contrastes vérifiés sur
  `canvas` #f6f5f0) :

  | Token proposé | Valeur | Contraste | Usage |
  |---|---|---|---|
  | `danger` | `#a3372b` | 6,1:1 | Priorité haute, délai dépassé, échec de synchro |
  | `danger-100` | `#f6e3df` | fond | Fond des badges `danger` (texte `danger` 5,4:1) |
  | `warning` | `#8a5a00` | 5,4:1 | Délai proche de l'échéance, licence bientôt expirée |
  | `warning-100` | `#f7ead0` | fond | Fond des badges `warning` (5,0:1) |
  | `success` | `#2f6b45` | 5,8:1 | Synchro réussie, ticket résolu |
  | `success-100` | `#dcebdf` | fond | Fond des badges `success` (5,1:1) |
  | `info` | `#3b5a78` | 6,6:1 | En attente, information neutre |
  | `info-100` | `#e1e8ef` | fond | Fond des badges `info` (5,8:1) |

  `success` et `brand` ont une luminance proche : un badge `success` porte toujours un libellé
  ou une icône, jamais la couleur seule. Ces tokens sont à reporter dans le design system
  Armosa (action hors dépôt, à proposer à son propriétaire).
- **Écart aux règles d'usage** : le design system limite `brand` et l'accent bronze à une ou
  deux touches par écran ; dans les listes (plusieurs priorités hautes à l'écran), ce sont les
  tokens d'état qui portent l'information, jamais `brand` ni `accent`.

## R17. Tests, qualité et sécurité de la chaîne

- **Decision** : `pytest` + `pytest-django`, `factory_boy` (données), `respx` (simulation de
  Graph), `time-machine` (horloge pour délais et rappels) ; Playwright pour 3 parcours de bout en
  bout (ticket par e-mail jusqu'à fermeture, création manuelle, équipement stock → utilisation).
  `ruff` (lint + format), `pip-audit` (vulnérabilités des dépendances, constitution II),
  gestion des dépendances avec `uv` (fichier de verrouillage).
- **Tests obligatoires (constitution, Workflow)** : matrice de permissions (rôles × vues),
  calcul ouvré et échéances, machine à états du ticket, rappels et fermetures automatiques,
  affectation automatique, rapprochement Intune, analyse des e-mails entrants (rattachement,
  e-mails automatiques), purge/anonymisation RGPD.

## R18. Observabilité et exploitation

- **Decision** : journaux JSON structurés (stdout → Azure Monitor), sans corps d'e-mail ni
  données personnelles au-delà des identifiants techniques ; chaque exécution de synchro et de
  relève est enregistrée en base (`SyncRun` : début, fin, compteurs, erreur) et visible des
  administrateurs (FR-005) ; point de santé `/healthz` (base + dernière relève de moins de
  5 minutes) ; alerte e-mail aux administrateurs après 3 échecs consécutifs d'une même
  synchronisation.

## R19. Bascule depuis Atera (principe V)

- **Decision** : cette fonctionnalité ne migre pas l'historique (fonctionnalité séparée) mais
  rend la bascule réversible : l'ITSM relève une boîte support dédiée ; la bascule consiste à
  rediriger l'adresse support publique d'Atera vers cette boîte (règle de transport Exchange),
  et le retour arrière à la rétablir. Pendant le pilote, les deux outils coexistent. Les listes
  de tickets et d'équipements sont exportables en CSV (format ouvert).
