---

description: "Liste des tâches d'implémentation : ticketing et gestion de parc"
---

# Tasks: Gestion de maintenance (ticketing) et gestion de parc

**Input**: documents de conception de `specs/001-ticketing-gestion-parc/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: la constitution (section « Workflow et contrôles qualité ») **impose** des tests
automatisés sur les règles critiques : permissions, délais/SLA, cycle de vie des tickets,
affectation, rappels, rapprochement Intune, analyse des e-mails, purge RGPD (research R17).
Les tâches de test ci-dessous couvrent ces règles ; elles s'écrivent avant ou avec le code
qu'elles vérifient et doivent passer avant de clore la phase.

**Organization**: tâches regroupées par user story. Ordre des phases : US5 et US1 (P1) puis
US2, US3, US4 (P2) puis US6, US7 (P3) — conforme à l'ordre de livraison validé du plan.

## Format: `[ID] [P?] [Story] Description`

- **[P]** : parallélisable (fichiers différents, pas de dépendance sur une tâche non terminée)
- **[Story]** : user story concernée (US1 à US7)

## Path Conventions

Projet Django unique à la racine : code dans `src/` (applications `itsm`, `core`,
`directory`, `helpdesk`, `inventory`), tests dans `tests/`, déploiement dans `deploy/`.
Commandes via `uv run …`. Langue de l'interface, des e-mails et des messages : français.

---

## Phase 1: Setup (infrastructure partagée)

**Purpose**: initialiser le projet, l'outillage et les ressources statiques.

- [ ] T001 Créer `pyproject.toml` géré par `uv` (Python 3.12) avec les dépendances : `django~=5.2`, `psycopg[binary]~=3.2`, `procrastinate[django]`, `mozilla-django-oidc`, `azure-identity`, `httpx`, `django-storages[azure]`, `nh3`, `holidays`, `gunicorn`, `whitenoise` ; dépendances de dev : `pytest`, `pytest-django`, `pytest-cov`, `factory-boy`, `respx`, `time-machine`, `pytest-playwright`, `ruff`, `pip-audit` ; puis générer `uv.lock`
- [ ] T002 Créer le projet Django dans `src/itsm/` (`settings/base.py`, `settings/dev.py`, `settings/prod.py`, `urls.py`, `wsgi.py`) et `manage.py` à la racine ajoutant `src/` au `sys.path` ; créer les applications vides `src/core/`, `src/directory/`, `src/helpdesk/`, `src/inventory/` ; `LANGUAGE_CODE = "fr-fr"`, `TIME_ZONE = "Europe/Paris"`, `USE_TZ = True` ; **déclarer `AUTH_USER_MODEL = "directory.Account"` avant toute première migration**
- [ ] T003 [P] Créer `docker-compose.yml` (service `db` PostgreSQL 16, volume nommé, port 5432) et `Dockerfile` multi-étapes (image Python 3.12 slim, `uv sync --frozen --no-dev`, utilisateur non root, `collectstatic`, commande par défaut `gunicorn itsm.wsgi`)
- [ ] T004 [P] Créer `.env.example` listant toutes les variables : `DJANGO_SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`, `ITSM_GRAPH_ENABLED` (défaut `false`), `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_CERTIFICATE_PATH`, `OIDC_RP_CLIENT_ID`, `OIDC_RP_CLIENT_SECRET`, `AZURE_STORAGE_ACCOUNT_NAME`, `AZURE_STORAGE_CONTAINER`, `DEV_LOGIN` — sans aucune valeur secrète
- [ ] T005 [P] Configurer `ruff` (lint + format, `line-length = 100`) et `pytest` (`DJANGO_SETTINGS_MODULE=itsm.settings.dev`, `pythonpath = ["src"]`, marqueur `e2e`) dans `pyproject.toml` ; créer `tests/conftest.py` et `tests/__init__.py`
- [ ] T006 [P] Créer `scripts/check.sh` exécutant `ruff check`, `ruff format --check`, `pytest --cov=src -m "not e2e"` et `pip-audit` ; échec si l'une des étapes échoue
- [ ] T007 [P] Copier `LOGO ARMOSA DIGITAL OK 2.png` vers `src/core/static/img/logo.png` ; produire `src/core/static/img/logo.svg` à partir de `LOGO ARMOSA DIGITAL OK.svg` en recadrant la `viewBox` sur l'emprise réelle des tracés (le fichier source est une planche 1190×842 avec marges) et en supprimant les métadonnées Illustrator
- [ ] T008 [P] Télécharger les polices sous licence OFL au format woff2 dans `src/core/static/fonts/` : EB Garamond 400/500/600, IBM Plex Sans 400/500/600, IBM Plex Mono 400/500 (aucun chargement depuis Google Fonts, research R15) ; télécharger HTMX 2.0.x minifié dans `src/core/static/js/htmx.min.js`

---

## Phase 2: Foundational (prérequis bloquants)

**Purpose**: socle commun : configuration, calendrier ouvré, audit, authentification Entra et
rôles, client Graph, file de tâches, thème Armosa.

**⚠️ CRITICAL**: aucune user story ne commence avant la fin de cette phase.

- [ ] T009 Configurer dans `src/itsm/settings/base.py` : base via `DATABASE_URL`, `whitenoise`, stockage des fichiers (`FileSystemStorage` en dev, `storages.backends.azure_storage.AzureStorage` avec identité managée en prod), journalisation JSON sur stdout sans corps d'e-mail ni jeton, en-têtes de sécurité (`SECURE_*`, cookies `Secure`/`HttpOnly`, `SESSION_COOKIE_AGE` 8 h) dans `settings/prod.py`
- [ ] T010 Créer les modèles `Settings` (instance unique) et `ClosureDay` dans `src/core/models.py` avec les champs et défauts de data-model.md : `ack_target_minutes` par priorité « haute 60, normale 240, basse 540 (minutes ouvrées) », `business_hours` « lun–ven 09:00–18:00, `Europe/Paris` », `reminder_delay_business_days` 2, `max_reminders` 3, `auto_close_business_days` 5, `retention_years` 3, `support_mailboxes` (liste), `internal_domains` (liste), `licence_expiry_warning_days` 30 ; `ClosureDay.date` « unique ; s'ajoute aux fériés français » ; accesseur `Settings.load()`
- [ ] T011 Créer le modèle `AuditEntry` dans `src/core/models.py` (`at`, `actor` → Account nullable « vide = système », `action`, `target_type`, `target_id`, `details` JSON « sans secret », `ip_address`) et une migration `RunSQL` réversible installant un déclencheur PostgreSQL qui refuse `UPDATE` et `DELETE` sauf quand la variable de session `itsm.audit_purge` vaut `on` ; helper `record(actor, action, target, details, request=None)` dans `src/core/audit.py`
- [ ] T012 [P] Implémenter `src/core/business_time.py` : `is_business_time(dt)`, `add_business_minutes(start, minutes)`, `business_minutes_between(start, end)`, `add_business_days(start, days)`, basés sur `Settings.business_hours`, les fériés de `holidays.France()` et `ClosureDay` ; tous les calculs en `Europe/Paris`, résultats en UTC
- [ ] T013 [P] Écrire `tests/unit/test_business_time.py` : vendredi 17:30 + 60 min ouvrées = lundi 09:30 ; création un samedi démarre lundi 09:00 ; 1er mai et jour de fermeture sautés ; passage à l'heure d'été/hiver ; `business_minutes_between` symétrique de `add_business_minutes`
- [ ] T014 Créer dans `src/directory/models.py` les modèles `Subsidiary` (`name` unique, `entra_company_names` liste, `is_active`), `Site` (`name` unique, `subsidiary` optionnel, `address`, `entra_office_locations` liste, `is_active`), `DirectoryUser` (`entra_id` UUID unique, `display_name`, `given_name`, `surname`, `email` « unique (insensible à la casse) si renseigné », `upn` unique, `job_title`, `department`, `subsidiary`, `site`, `manager` → DirectoryUser, `is_active`, `deactivated_at`, `anonymized_at`, `last_synced_at`), `Account` (utilisateur Django, `directory_user` un pour un, `roles` ⊂ {`technicien`, `administrateur`}, propriétés `is_technician` et `is_admin`) et `SyncRun` (`kind` ∈ {`entra_users`, `intune_devices`, `mailbox`}, `mailbox`, `started_at`, `finished_at`, `status` ∈ {`running`, `success`, `failed`}, compteurs `created`/`updated`/`deactivated`/`skipped`, `error`, `delta_token`) ; index sur `lower(email)` et index trigramme (`pg_trgm`) sur `display_name` ; migration initiale
- [ ] T015 Implémenter l'authentification dans `src/core/auth.py` : backend `mozilla-django-oidc` qui rattache le compte au `DirectoryUser` par la revendication `oid` (création minimale si absent), recopie `roles` (`ITSM.Technicien` → `technicien`, `ITSM.Administrateur` → `administrateur`) à chaque connexion et refuse la connexion sans rôle ; mixins `TechnicianRequiredMixin` et `AdminRequiredMixin` (403 sinon) ; connexion `DEV_LOGIN` active uniquement si `DEBUG` ; routes `/oidc/` et `POST /logout/` dans `src/itsm/urls.py` ; `/admin/` réservé au rôle administrateur
- [ ] T016 [P] Écrire `tests/integration/test_auth.py` : jeton sans rôle → refus ; rôle technicien → accès aux pages techniciens, 403 sur `/admin/` ; rôle administrateur → accès complet ; rôles retirés dans Entra → retirés à la connexion suivante
- [ ] T017 [P] Implémenter le client Graph mince `src/core/graph.py` : jeton applicatif via `azure-identity` (`ManagedIdentityCredential` si identité managée, sinon `ClientCertificateCredential`), `get`, `get_paged` (suivi de `@odata.nextLink`), `post`, reprise sur `429`/`503` en respectant `Retry-After` (défaut 30 s, 5 tentatives), exception `GraphPermissionError` sur `401`/`403`, `GraphDeltaExpired` sur `410` ; aucun jeton ni en-tête d'autorisation dans les journaux ; désactivé si `ITSM_GRAPH_ENABLED=false`
- [ ] T018 [P] Écrire `tests/unit/test_graph_client.py` avec `respx` : pagination, reprise sur 429 avec `Retry-After`, abandon après 5 tentatives, 403 → `GraphPermissionError`, 410 → `GraphDeltaExpired`
- [ ] T019 Configurer Procrastinate dans `src/itsm/worker.py` (application adossée à PostgreSQL, découverte des `tasks.py` des applications, verrou par tâche périodique) et créer la commande `src/core/management/commands/run_job.py` (`manage.py run_job <nom.de.tâche>` exécute une tâche immédiatement, pour la recette et le quickstart)
- [ ] T020 [P] Créer `src/core/static/css/tokens.css` : tous les tokens du design system Armosa (couleurs `brand`, `logo-green`, `logo-navy`, rampe `sage-*`, rampe `accent-*`, `canvas`, `paper`, `linen`, `hairline`, `ink*`, `action`, `action-text`, `border-control`, `focus` ; familles `display`/`sans`/`mono` ; échelle typographique ; `space-1` à `space-10` ; `radius-xs/md/lg/pill` ; `shadow-float`) en variables CSS, plus les tokens d'état de research R16 : `danger #a3372b`, `danger-100 #f6e3df`, `warning #8a5a00`, `warning-100 #f7ead0`, `success #2f6b45`, `success-100 #dcebdf`, `info #3b5a78`, `info-100 #e1e8ef` ; déclarations `@font-face` vers `static/fonts/`
- [ ] T021 [P] Créer `src/core/static/css/app.css` : composants de base conformes aux règles d'usage Armosa — bouton principal `action` (pilule, un seul par écran), bouton secondaire bordé, cartes `paper` + filet `hairline` sans ombre, tags et badges en pilule (états `danger`/`warning`/`success`/`info` toujours avec libellé), tableaux, champs (`border-control`, `radius-md`), étiquettes mono en capitales, anneau de focus 2 px `focus`, textes ≥ 14 px, mise en page responsive
- [ ] T022 Créer `src/core/templates/base.html` (logo SVG, navigation : Tickets, Suivi, Base de résolution, Parc, Licences, Admin si administrateur ; zone de messages ; chargement de `tokens.css`, `app.css`, `htmx.min.js` avec jeton CSRF dans `hx-headers`) et thémer l'admin Django via `src/core/templates/admin/base_site.html` (variables CSS de l'admin mappées sur les tokens Armosa, logo, titre « ITSM Armosa Digital »)
- [ ] T023 [P] Créer la vue `/healthz` dans `src/core/views.py` : `200` si la base répond et si le dernier `SyncRun` `mailbox` réussi date de moins de 5 minutes (ou si `ITSM_GRAPH_ENABLED=false`), sinon `503` ; aucune donnée métier dans la réponse
- [ ] T024 Enregistrer `Settings`, `ClosureDay` et `AuditEntry` (lecture seule, ni ajout ni suppression) dans `src/core/admin.py` ; toute modification de `Settings` crée une entrée d'audit `settings.change`
- [ ] T025 [P] Créer les fabriques `factory_boy` de base dans `tests/factories.py` (`SubsidiaryFactory`, `SiteFactory`, `DirectoryUserFactory`, `AccountFactory` avec traits `technician` et `admin`) et les fixtures pytest `technician_client` et `admin_client` dans `tests/conftest.py`

**Checkpoint**: socle prêt ; connexion Entra opérationnelle, thème Armosa visible, tâches
planifiables.

---

## Phase 3: User Story 5 - Annuaire utilisateurs synchronisé avec Entra (Priority: P1) 🎯 MVP

**Goal**: les collaborateurs (nom, e-mail, filiale, site, service, responsable, état) sont
importés depuis Entra et tenus à jour.

**Independent Test**: créer, modifier puis désactiver un utilisateur de test dans Entra et
lancer `run_job directory.sync_entra` après chaque étape (quickstart S6).

### Tests for User Story 5

- [ ] T026 [P] [US5] Créer les fixtures Graph `tests/fixtures/graph/users_delta_page1.json`, `users_delta_page2.json` (avec `@odata.nextLink` puis `@odata.deltaLink`), `users_delta_changes.json` (modification, `accountEnabled: false`, `@removed`) et `users_delta_410.json`
- [ ] T027 [P] [US5] Écrire `tests/integration/test_entra_sync.py` : création avec filiale via `companyName` et site via `officeLocation` (création automatique des filiales/sites inconnus) ; mise à jour ; `accountEnabled=false` et `@removed` → `is_active = false` + `deactivated_at`, jamais de suppression ; responsable résolu ; 410 → synchro complète ; synchro interrompue → aucune désactivation déduite ; un `SyncRun` par exécution avec compteurs

### Implementation for User Story 5

- [ ] T028 [US5] Implémenter `src/directory/services/entra_sync.py` : `sync_users(full=False)` utilisant `GET /users/delta?$select=id,displayName,givenName,surname,mail,userPrincipalName,companyName,officeLocation,department,jobTitle,accountEnabled,manager` et le jeton delta du dernier `SyncRun` réussi ; correspondances de contracts/graph-integration.md (`mail` à défaut `userPrincipalName` → `email`) ; résolution des responsables en seconde passe ; transaction par page ; en mode complet, les utilisateurs absents deviennent inactifs ; émission du signal `directory_user_deactivated(user)` défini dans `src/directory/signals.py`
- [ ] T029 [US5] Déclarer les tâches périodiques dans `src/directory/tasks.py` : `directory.sync_entra` toutes les 30 minutes (delta) et à 02:00 (complète) ; après 3 échecs consécutifs, journaliser une alerte (l'e-mail aux administrateurs est branché en US1, T055)
- [ ] T030 [P] [US5] Enregistrer dans `src/directory/admin.py` : `Subsidiary` et `Site` (édition des listes `entra_company_names` / `entra_office_locations`), `DirectoryUser` (lecture seule pour les champs issus d'Entra), `SyncRun` (lecture seule, filtres par type et statut — FR-005) ; vue `/admin/sync/<kind>/run/` déclenchant une synchro manuelle (administrateur uniquement)
- [ ] T031 [US5] Créer la fiche personne `/people/<entra_id>/` dans `src/directory/views.py` et `src/directory/templates/directory/person.html` : identité, filiale, site, service, responsable, état actif/inactif ; blocs extensibles « Tickets » et « Équipements » remplis par US1 et US4 (inclusion de gabarits fournis par les autres applications)
- [ ] T032 [P] [US5] Créer la commande `src/directory/management/commands/seed_demo.py` : 2 filiales, 3 sites, 20 utilisateurs fictifs dont 3 techniciens et 1 administrateur (comptes `DEV_LOGIN`) ; idempotente ; refuse de s'exécuter si `DEBUG` est faux

**Checkpoint**: l'annuaire est synchronisé ; US5 testable seule.

---

## Phase 4: User Story 1 - Créer et traiter un ticket de bout en bout (Priority: P1) 🎯 MVP

**Goal**: tickets créés par e-mail ou par un technicien, qualifiés, pris en compte, échangés par
e-mail (notes externes), commentés (notes internes), chronométrés, résolus puis fermés.

**Independent Test**: quickstart S1 (e-mail jusqu'à fermeture) et S2 (création manuelle).

### Tests for User Story 1

- [ ] T033 [P] [US1] Créer les fixtures e-mail `tests/fixtures/mail/` : `nouvelle_demande.eml` (expéditeur connu, pièce jointe, image inline), `reponse_demandeur.eml` (objet `RE: [T-00001] …`, historique cité Outlook), `reponse_sans_reference.eml` (rattachement par `In-Reply-To`), `absence.eml` (`Auto-Submitted: auto-replied`), `liste.eml` (`List-Id`), `expediteur_inconnu_interne.eml`, `expediteur_inconnu_externe.eml`, `html_malveillant.eml` (`<script>`, `onerror`)
- [ ] T034 [P] [US1] Écrire `tests/unit/test_mail_parsing.py` : extraction de la référence `\[T-(\d{5,})\]` ; nettoyage des préfixes `RE:`, `TR:`, `FW:` ; détection des e-mails automatiques selon contracts/email.md règle 3 ; séparation de l'historique cité (« De : », « From: », « Le … a écrit : ») ; assainissement HTML (aucun script ni attribut d'événement)
- [ ] T035 [P] [US1] Écrire `tests/unit/test_ticket_lifecycle.py` : toutes les transitions autorisées de la machine à états de data-model.md et refus (`InvalidTransition`) de toutes les autres ; `cree → pris_en_compte` refusé sans `type`, `category` et `subsidiary` ; `resolu` refusé sans résolution ; `cree → resolu` renseigne `acknowledged_at` ; réponse du demandeur en `attente_reponse` → `pris_en_compte` ; réponse en `resolu` → `pris_en_compte` et `resolved_at` effacé ; réponse sur `ferme` → nouveau ticket lié ; chaque transition crée un `TicketEvent`
- [ ] T036 [P] [US1] Écrire `tests/integration/test_mail_inbound.py` (Graph simulé par `respx`) : règles 1 à 7 de contracts/email.md dans l'ordre (doublon ignoré, boucle, automatique, limite de 20/h, rattachement par référence / `In-Reply-To` / `conversationId`, ticket fermé → nouveau ticket lié, nouveau ticket) ; déplacement vers « ITSM/Traités » et « ITSM/Ignorés » ; pièces jointes > 25 Mo remplacées par une mention ; expéditeur inconnu externe → pas d'accusé
- [ ] T037 [P] [US1] Écrire `tests/integration/test_mail_outbound.py` : brouillon puis envoi Graph, `internet_message_id` enregistré, objet `[T-xxxxx] <titre>`, logo en `cid:logo` ; **l'ensemble des `kind` envoyés à un demandeur est exactement {`accuse_reception`, `note_externe`, `rappel`, `resolution`}** et aucun e-mail au demandeur sur prise en compte, mise en attente, fermeture, réaffectation ou changement de priorité (FR-038) ; aucune note interne dans un e-mail
- [ ] T038 [P] [US1] Écrire `tests/integration/test_ticket_views.py` : création manuelle (FR-014, FR-014a), qualification, prise en compte, notes interne/externe, saisie de temps (`minutes` « 1 à 1 440 », `date` « ≤ aujourd'hui »), résolution (422 sans résolution), réaffectation en masse, export CSV ; 403 pour un utilisateur sans rôle sur chaque route de contracts/ui-routes.md section Tickets

### Implementation for User Story 1

- [ ] T039 [P] [US1] Créer dans `src/helpdesk/models.py` les référentiels : `Category` (`name` « unique parmi les catégories de même parent », `parent`, `level` « calculé : niveau du parent + 1 ; un niveau 4 est refusé », `is_active`, `position`), `Tool` (`name` unique, `description`, `default_group` → TechnicianGroup optionnel, `is_active`), `TechnicianGroup` (`name` unique, `members` → Account, `email` optionnel), `Skill` (`technician`, `tool`, unicité (`technician`, `tool`))
- [ ] T040 [US1] Créer dans `src/helpdesk/models.py` le modèle `Ticket` avec tous les champs de data-model.md (`number` via une séquence PostgreSQL créée en `RunSQL` réversible, affiché `T-%05d` ; `title` « texte (≤ 255) obligatoire » ; `channel` ∈ {`email`, `app`} ; `created_by` ; `requester` ; `requester_email` ; `subsidiary` ; `type` ∈ {`incident`, `demande`} « vide tant que non qualifié » ; `category` ; `tool` ; `priority` ∈ {`haute`, `normale`, `basse`} « défaut `normale` » ; `status` ∈ {`cree`, `pris_en_compte`, `attente_reponse`, `en_attente`, `resolu`, `ferme`} « défaut `cree` » ; `assignee` ; `assigned_group` ; `assignment_mode` ∈ {`auto`, `manuel`, `aucun`} ; `related_ticket` ; `acknowledged_at` ; `ack_due_at` ; `ack_business_minutes` ; `ack_breached` ; `breach_alerted_at` ; `waiting_since` ; `reminders_sent` « entier 0–3 » ; `last_reminder_at` ; `resolution` ; `resolution_kind` ∈ {`technicien`, `sans_reponse`} ; `resolved_at` ; `closed_at` ; `has_unread_reply` ; `anonymized_at`) et les index de data-model.md (`status`+`assignee`, `status`+`assigned_group`, `ack_due_at`, `waiting_since`, `resolved_at`, `closed_at`)
- [ ] T041 [US1] Créer dans `src/helpdesk/models.py` : `TicketNote` (`visibility` ∈ {`interne`, `externe`}, `direction` ∈ {`entrant`, `sortant`, `interne`}, `author`, `author_email`, `body_text`, `body_html`, `email_message`), `Attachment` (`file` « ≤ 25 Mo », `filename`, `content_type`, `size`, `content_id`, `note` optionnelle), `EmailMessage` (`direction`, `mailbox`, `graph_id`, `internet_message_id` **unique**, `conversation_id` indexé, `in_reply_to`, `references`, `ticket`, `kind` ∈ {`accuse_reception`, `note_externe`, `rappel`, `resolution`, `alerte_technicien`, `entrant`}, `processing` ∈ {`ticket_cree`, `note_ajoutee`, `ignore_automatique`, `ignore_boucle`, `ignore_limite`, `envoye`, `echec`}, `sent_at`, `received_at`, `error`), `TimeEntry` (`technician`, `date` « ≤ aujourd'hui », `minutes` « 1 à 1 440 », `comment`), `TicketEvent` (`at`, `actor` « vide = système », `kind` selon la liste de data-model.md, `old_value`, `new_value`, `data`) ; générer les migrations
- [ ] T042 [US1] Implémenter la machine à états dans `src/helpdesk/services/lifecycle.py` : table des transitions de data-model.md, exception `InvalidTransition`, contrôles de qualification et de résolution, effets (`acknowledged_at` et `ack_business_minutes` via `core.business_time`, `waiting_since` et `reminders_sent = 0` à l'entrée en `attente_reponse`, `resolved_at`, `closed_at`, `has_unread_reply`), un `TicketEvent` par changement ; point d'extension `on_status_changed` (signal) utilisé par US3
- [ ] T043 [US1] Implémenter `src/helpdesk/services/tickets.py` : `create_from_email(...)`, `create_manual(technician, requester, title, description, type, category, tool, priority)` (`channel = app`, `created_by`), `qualify(ticket, actor, **fields)` (événements par champ modifié ; signal `ticket_qualified` utilisé par US2 et US3), `take(ticket, technician)`, `assign(ticket, actor, assignee=None, group=None)` (`assignment_mode = manuel`), `bulk_reassign(from_technician, to_technician=None, to_group=None, actor)`, `add_note(ticket, actor, visibility, body, files)`, `add_time(ticket, technician, date, minutes, comment)`, `register_requester_reply(ticket, email_message)` ; chaque création envoie l'accusé de réception
- [ ] T044 [P] [US1] Implémenter `src/helpdesk/mail/parsing.py` : `extract_ticket_number(subject)`, `clean_subject(subject)`, `is_automatic(headers, sender)` (règle 3 de contracts/email.md), `split_quoted(text)`, `sanitize_html(html)` avec `nh3` (liste blanche de balises de mise en forme, liens `http`/`https`/`mailto` uniquement, images `cid:` réécrites vers la pièce jointe)
- [ ] T045 [US1] Implémenter `src/helpdesk/mail/inbound.py` : `poll_mailbox(mailbox)` via `GET /users/{boîte}/mailFolders/inbox/messages/delta` (champs de contracts/graph-integration.md), création des dossiers « ITSM/Traités » et « ITSM/Ignorés » au premier passage, règles 1 à 7 de contracts/email.md dans l'ordre, limite de 20 messages/heure par expéditeur (alerte administrateurs une fois par heure), pièces jointes vers le stockage, identification du demandeur par e-mail (insensible à la casse), expéditeur inconnu marqué « non identifié », accusé seulement si le domaine figure dans `Settings.internal_domains`, un `SyncRun` (`kind = mailbox`) par boîte
- [ ] T046 [US1] Implémenter `src/helpdesk/mail/outbound.py` : `queue_email(ticket, kind, note=None)` refusant tout `kind` destiné au demandeur hors {`accuse_reception`, `note_externe`, `rappel`, `resolution`} ; `send(email_message)` : brouillon `POST /users/{boîte}/messages` puis `POST …/send`, enregistrement de `internet_message_id`, expéditeur = boîte ayant reçu le ticket sinon première boîte paramétrée, logo PNG en pièce jointe inline `cid:logo` ; si `ITSM_GRAPH_ENABLED=false`, enregistrement sans envoi ; `send_technician_alert(recipients, subject, body)` pour les alertes
- [ ] T047 [P] [US1] Créer les gabarits e-mail : `src/core/templates/email/base.html` (styles en ligne Armosa : fond `canvas`, texte `ink`, titres EB Garamond avec repli Georgia, logo `cid:logo` 200 px, texte alternatif « Armosa Digital ») et `base.txt` ; `src/helpdesk/templates/email/accuse_reception.html|.txt`, `note_externe.html|.txt`, `resolution.html|.txt` avec les contenus minimaux de contracts/email.md
- [ ] T048 [US1] Déclarer dans `src/helpdesk/tasks.py` : `mail.poll_mailboxes` chaque minute, `mail.send` à la demande avec 3 tentatives (1, 5, 15 min), `helpdesk.auto_close` toutes les heures (`resolu` → `ferme` après `Settings.auto_close_business_days` jours ouvrés, FR-033)
- [ ] T049 [P] [US1] Créer la commande `src/helpdesk/management/commands/inject_email.py` : traite un fichier `.eml` local comme un message entrant (mêmes règles que `inbound.py`), pour le développement et le quickstart
- [ ] T050 [US1] Créer les vues de liste dans `src/helpdesk/views.py` et `src/helpdesk/templates/helpdesk/ticket_list.html` : `GET /tickets/` avec filtres (statut, priorité, assigné dont « moi » et « non affecté », groupe, filiale, catégorie, outil, dépassement, texte), tri par échéance, pagination 50, badge « non identifié » et « nouvelle réponse », filtres en HTMX ; `GET /tickets/export.csv` (tickets filtrés)
- [ ] T051 [US1] Créer la création manuelle : `GET/POST /tickets/new/` (`src/helpdesk/templates/helpdesk/ticket_new.html`) et la recherche d'annuaire `GET /directory/search/?q=` dans `src/directory/views.py` (« 10 utilisateurs actifs max par nom ou e-mail (≥ 2 caractères) », fragment HTMX)
- [ ] T052 [US1] Créer la fiche ticket `GET /tickets/<number>/` (`src/helpdesk/templates/helpdesk/ticket_detail.html`) : en-tête (numéro, statut, priorité, demandeur, filiale, canal et créateur), bloc qualification, fil chronologique (notes, e-mails, événements, historique cité replié), temps total et par technicien, pièces jointes ; marque `has_unread_reply = false` à l'ouverture par l'assigné
- [ ] T053 [US1] Créer les actions HTMX de la fiche dans `src/helpdesk/views.py` : `POST /tickets/<number>/qualify/`, `/status/` (422 avec message en français si transition refusée), `/take/`, `/assign/`, `/notes/` (pièces jointes, note externe → e-mail), `/time/` ; `POST /tickets/bulk-assign/` ; `GET /attachments/<id>/` (URL signée courte durée en prod) ; gabarits de fragments dans `src/helpdesk/templates/helpdesk/partials/`
- [ ] T054 [P] [US1] Enregistrer dans `src/helpdesk/admin.py` : `Category` (arborescence, refus du niveau 4, désactivation plutôt que suppression), `Tool`, `TechnicianGroup`, `EmailMessage` (lecture seule, pour le support de la messagerie)
- [ ] T055 [US1] Brancher dans `src/helpdesk/receivers.py` : sur `directory_user_deactivated`, signaler ses tickets ouverts à réaffecter et envoyer une `alerte_technicien` aux administrateurs ; brancher l'alerte e-mail après 3 échecs consécutifs de synchro ou de relève (T029)
- [ ] T056 [US1] Ajouter le bloc « Tickets » de la fiche personne (`src/helpdesk/templates/helpdesk/person_tickets.html`, inclus par T031)
- [ ] T057 [P] [US1] Étendre `seed_demo` (`src/directory/management/commands/seed_demo.py`) avec une arborescence de catégories sur 3 niveaux, 5 outils, 2 groupes et `Settings.support_mailboxes`/`internal_domains` de démonstration
- [ ] T058 [US1] Écrire les tests e2e Playwright `tests/e2e/test_s1_ticket_email.py` et `tests/e2e/test_s2_ticket_manual.py` reproduisant quickstart S1 et S2 (marqueur `e2e`)

**Checkpoint**: MVP (US5 + US1) : un pilote sur une boîte support de test est possible.

---

## Phase 5: User Story 2 - Affectation automatique selon les compétences (Priority: P2)

**Goal**: un ticket qualifié avec un outil est affecté automatiquement au bon technicien ou
groupe.

**Independent Test**: quickstart S3 (outils A, B, C).

### Tests for User Story 2

- [ ] T059 [P] [US2] Écrire `tests/unit/test_assignment.py` : les 5 cas de la règle d'affectation de data-model.md (1 compétent → technicien ; groupe défini → groupe ; ≥ 2 sans groupe → moins de tickets ouverts puis affecté le moins récemment ; aucun → file de dispatch) ; non exécutée si `assignment_mode = manuel` ou statut ≠ `cree` ; techniciens inactifs exclus
- [ ] T060 [P] [US2] Écrire `tests/integration/test_assignment_views.py` : qualification avec outil → affectation visible ; « Prendre » par un membre du groupe → assigné ; réaffectation manuelle → événement + plus d'affectation automatique ; vue dispatch ; audit `skill.change` / `group.change` lors des modifications en admin

### Implementation for User Story 2

- [ ] T061 [US2] Implémenter `src/helpdesk/services/assignment.py` : `auto_assign(ticket)` appliquant exactement les étapes 1 à 5 de data-model.md, `assignment_mode = auto`, événement `affectation` ; branché sur le signal `ticket_qualified` (T043) quand `tool` est renseigné ou modifié
- [ ] T062 [US2] Ajouter la vue dispatch `GET /tickets/?view=dispatch` et un filtre « mes groupes » dans `src/helpdesk/views.py` et `ticket_list.html` ; afficher le groupe et le mode d'affectation sur la fiche ticket
- [ ] T063 [US2] Compléter `src/helpdesk/admin.py` : `Skill` en inline sur `Tool` et sur `Account`, membres de `TechnicianGroup` limités aux comptes techniciens actifs ; journaliser chaque modification de compétences (`skill.change`) et de groupes (`group.change`) via `core.audit`
- [ ] T064 [US2] Dans `src/helpdesk/receivers.py`, sur `directory_user_deactivated` : supprimer les compétences du technicien et le retirer de ses groupes (cas limite de la spec)

**Checkpoint**: US2 fonctionne ; sans compétences déclarées, US1 reste utilisable manuellement.

---

## Phase 6: User Story 3 - Suivi des délais, rappels et priorités (Priority: P2)

**Goal**: échéances de prise en compte par priorité en heures ouvrées, alertes de dépassement,
rappels automatiques, suivi du temps passé.

**Independent Test**: quickstart S4 (horloge avancée avec `time-machine` / `run_job`).

### Tests for User Story 3

- [ ] T065 [P] [US3] Écrire `tests/unit/test_sla.py` : `ack_due_at` = création + cible (haute 60, normale 240, basse 540 minutes ouvrées) ; recalcul si la priorité change avant prise en compte, pas après ; ticket haute priorité vendredi 17:30 → échéance lundi 09:30 ; dépassement marqué et **une seule** alerte par ticket
- [ ] T066 [P] [US3] Écrire `tests/unit/test_reminders.py` : rappels à 2, 4 et 6 jours ouvrés, résolution automatique `sans_reponse` 2 jours ouvrés après le 3e rappel avec e-mail `resolution` ; réponse du demandeur → compteur remis à zéro ; aucun rappel en `en_attente` ; aucun ticket en `attente_reponse` plus de 10 jours ouvrés (SC-007)

### Implementation for User Story 3

- [ ] T067 [US3] Implémenter `src/helpdesk/services/sla.py` : `compute_ack_due(ticket)` (branché sur la création et sur `ticket_qualified` quand la priorité change sans `acknowledged_at`), `check_ack_deadlines()` (marque `ack_breached`, alerte l'assigné, sinon `email` du groupe, sinon ses membres, sinon les administrateurs, une fois via `breach_alerted_at`)
- [ ] T068 [US3] Implémenter `src/helpdesk/services/reminders.py` : `send_reminders()` (délai `Settings.reminder_delay_business_days` depuis `waiting_since` ou `last_reminder_at`, au plus `Settings.max_reminders`, événement `rappel`), puis résolution automatique « sans réponse du demandeur » via `lifecycle` (`resolution_kind = sans_reponse`)
- [ ] T069 [P] [US3] Créer le gabarit `src/helpdesk/templates/email/rappel.html|.txt` (rang du rappel « 1/3… », dernière note externe, date de résolution automatique prévue)
- [ ] T070 [US3] Déclarer dans `src/helpdesk/tasks.py` : `helpdesk.check_ack_deadlines` toutes les 5 minutes et `helpdesk.send_reminders` toutes les heures en heures ouvrées
- [ ] T071 [US3] Créer la vue de suivi `GET /tracking/` (`src/helpdesk/views.py`, `src/helpdesk/templates/helpdesk/tracking.html`) : tickets non pris en compte triés par échéance avec badge `warning` sous 25 % du délai restant et `danger` en dépassement, taux de respect par priorité sur la période (SC-003), temps passé par technicien sur la période
- [ ] T072 [US3] Afficher l'échéance, le badge de délai et le temps total dans `ticket_list.html` et `ticket_detail.html`

**Checkpoint**: US3 fonctionne au-dessus de US1.

---

## Phase 7: User Story 4 - Inventaire du parc synchronisé et complété (Priority: P2)

**Goal**: parc Intune synchronisé, équipements et licences ajoutés à la main, sites et statuts,
affectation aux utilisateurs.

**Independent Test**: quickstart S5.

### Tests for User Story 4

- [ ] T073 [P] [US4] Créer les fixtures Graph `tests/fixtures/graph/managed_devices_page1.json` et `managed_devices_page2.json` (Windows, macOS, iOS, Android, iPadOS, un numéro de série générique « To Be Filled By O.E.M. », un appareil disparu entre deux synchros)
- [ ] T074 [P] [US4] Écrire `tests/integration/test_intune_sync.py` : création avec type déduit (Windows/macOS → PC, iOS/Android → Téléphone, iPadOS → Tablette) ; rapprochement par identifiant Intune puis par numéro de série normalisé avec un équipement manuel (devient `source = intune`, historique conservé) ; numéros génériques exclus ; appareil absent → `intune_removed_at` ; réapparition → `retour_intune` ; `assigned_to` initialisé depuis l'utilisateur principal puis remplacé seulement si celui-ci change ; nombre d'équipements Intune = nombre d'appareils (SC-004)
- [ ] T075 [P] [US4] Écrire `tests/unit/test_equipment_rules.py` et `tests/unit/test_licences.py` : affectation d'un équipement en `stock` → `en_utilisation` ; champs Intune ignorés à l'enregistrement d'un équipement `source = intune` (FR-062) ; postes consommés = utilisateurs + équipements, dépassement si > `seats` ; licence signalée si `expires_at` ≤ aujourd'hui + 30 jours

### Implementation for User Story 4

- [ ] T076 [P] [US4] Créer dans `src/inventory/models.py` : `EquipmentType` (`name` unique, `is_active` ; migration de données créant « PC, Écran, Imprimante, Télévision, Caméra, Téléphone, Tablette ») ; `Equipment` (`type` obligatoire, `source` ∈ {`intune`, `manuel`}, `name`, `manufacturer`, `model`, `serial_number` « normalisé (majuscules, sans espaces) ; unique quand non vide et non générique », `os`, `os_version`, `intune_id` « unique si renseigné », `intune_primary_user`, `intune_last_sync_at`, `intune_enrolled_at`, `intune_removed_at`, `site` « obligatoire (FR-061) ; « À définir » par défaut pour un appareil Intune sans site déduit », `status` ∈ {`stock`, `en_utilisation`} obligatoire, `assigned_to`, `purchase_date`, `warranty_end`, `notes`) ; `Licence` (`name` obligatoire, `vendor`, `seats` « entier ≥ 1 », `expires_at` optionnelle, `assigned_users`, `assigned_equipment`, `subsidiary`, `notes` « sans clé de licence en clair ») ; `EquipmentEvent` (même structure que `TicketEvent`, `kind` ∈ {`creation`, `affectation`, `site`, `statut`, `rapprochement_intune`, `retrait_intune`, `retour_intune`, `modification`}, référence équipement ou licence) ; index de data-model.md
- [ ] T077 [US4] Ajouter le champ `Ticket.equipment` (ensemble → `inventory.Equipment`) dans `src/helpdesk/models.py` avec sa migration, et la route `POST /tickets/<number>/equipment/` (lier/délier, événement `equipement`) ; ajouter le choix des équipements du demandeur au formulaire de création manuelle (FR-014, FR-017)
- [ ] T078 [US4] Implémenter `src/inventory/services/intune_sync.py` : `sync_devices()` via `GET /deviceManagement/managedDevices` (champs de contracts/graph-integration.md), synchro complète, rapprochement dans l'ordre identifiant Intune → numéro de série normalisé (hors génériques « To Be Filled By O.E.M. », « 0 », « Default string ») → création, statut `en_utilisation` à la création si utilisateur principal, `intune_removed_at` pour les absents (jamais de suppression), événements, `SyncRun` (`kind = intune_devices`) ; aucune désactivation si la synchro est incomplète
- [ ] T079 [US4] Implémenter `src/inventory/services/equipment.py` (`create_manual`, `update_itsm_fields` ignorant côté serveur les champs Intune d'un équipement `source = intune`, `assign`/`unassign` avec passage `stock` ↔ `en_utilisation`, événements) et `src/inventory/services/licences.py` (`seats_used`, `is_over_allocated`, `expiring_soon(days=Settings.licence_expiry_warning_days)`)
- [ ] T080 [US4] Déclarer dans `src/inventory/tasks.py` : `inventory.sync_intune` toutes les heures et `inventory.licence_digest` le lundi à 08:00 (récapitulatif aux administrateurs via `send_technician_alert`)
- [ ] T081 [US4] Créer les vues du parc dans `src/inventory/views.py` et `src/inventory/templates/inventory/` : `GET /inventory/` (filtres type, site, statut, filiale, utilisateur, source, « retiré d'Intune » ; pagination 50), `GET /inventory/export.csv`, `GET/POST /inventory/new/` (type, site, statut obligatoires), `GET/POST /inventory/<id>/` (champs Intune en lecture seule, historique, tickets liés), `POST /inventory/<id>/assign/`
- [ ] T082 [US4] Créer les vues licences : `GET /licences/`, `GET /licences/<id>/`, `GET/POST /licences/new/` dans `src/inventory/views.py` avec badges `warning` « expire bientôt » et `danger` « dépassement »
- [ ] T083 [P] [US4] Enregistrer dans `src/inventory/admin.py` : `EquipmentType` (désactivation plutôt que suppression) ; suppression d'un équipement ou d'une licence réservée aux administrateurs et auditée (`equipment.delete`)
- [ ] T084 [US4] Dans `src/inventory/receivers.py`, sur `directory_user_deactivated` : alerte aux administrateurs listant les équipements et licences encore affectés (US5-2) ; ajouter le bloc « Équipements et licences » de la fiche personne (`src/inventory/templates/inventory/person_equipment.html`, inclus par T031) et la liste des équipements liés sur la fiche ticket
- [ ] T085 [P] [US4] Étendre `seed_demo` avec 30 équipements (dont 10 en stock) et 3 licences ; écrire le test e2e `tests/e2e/test_s5_inventory.py` (écran en stock → affecté → `en_utilisation`)

**Checkpoint**: US4 fonctionne indépendamment du ticketing (seul T077 touche aux tickets).

---

## Phase 8: User Story 6 - Base de résolution et historique (Priority: P3)

**Goal**: historique complet consultable et recherche plein texte dans les résolutions, avec
suggestions sur les tickets en cours.

**Independent Test**: quickstart S7.

### Tests for User Story 6

- [ ] T086 [P] [US6] Écrire `tests/integration/test_knowledge.py` : recherche « imprimante bourrage » trouvant « Imprimante : bourrage papier » (accents et casse ignorés, racinisation française) ; filtres catégorie, outil, filiale, période ; seuls les tickets `ferme` sont renvoyés ; suggestions sur un ticket ouvert = tickets fermés de même catégorie ou même outil, classés par pertinence

### Implementation for User Story 6

- [ ] T087 [US6] Créer une migration dans `src/helpdesk/migrations/` : extensions `unaccent` et `pg_trgm`, configuration de recherche `french_unaccent`, colonne générée `Ticket.search_vector` (titre poids A, résolution poids B, description poids C) et index GIN ; migration réversible
- [ ] T088 [US6] Implémenter `src/helpdesk/services/knowledge.py` : `search(query, category=None, tool=None, subsidiary=None, date_from=None, date_to=None)` classé par `ts_rank` sur les tickets fermés ; `suggestions(ticket, limit=5)`
- [ ] T089 [US6] Créer la vue `GET /knowledge/` (`src/helpdesk/templates/helpdesk/knowledge.html`) et le panneau « Résolutions similaires » chargé en HTMX sur `ticket_detail.html` (FR-042) ; vérifier que le fil de la fiche affiche chaque `TicketEvent` avec date, auteur, ancienne et nouvelle valeur (US6-1)

**Checkpoint**: US6 fonctionne avec les tickets fermés de US1.

---

## Phase 9: User Story 7 - Prise en main à distance avec TeamViewer (Priority: P3)

**Goal**: identifiant TeamViewer visible et copiable depuis les tickets ; interventions
déclarées et tracées. **Aucun lancement ni intégration de TeamViewer** (research R13).

**Independent Test**: quickstart S8. **Dépend de US4** (équipements) et de T077.

### Tests for User Story 7

- [ ] T090 [P] [US7] Écrire `tests/integration/test_remote_sessions.py` : identifiant TeamViewer affiché sur la fiche ticket pour chaque équipement lié ; déclaration valide → `RemoteSession`, `TicketEvent` `prise_en_main` et `AuditEntry` `remote_session.declare` ; refus si `ended_at` ≤ `started_at` ou `started_at` futur ; aucune URL ni bouton de lancement dans le HTML rendu

### Implementation for User Story 7

- [ ] T091 [US7] Ajouter `Equipment.teamviewer_id` dans `src/inventory/models.py` (« identifiant TeamViewer (9 à 10 chiffres, espaces ignorés) ; optionnel », modifiable aussi pour un équipement `source = intune`) avec migration ; champ dans les formulaires de `src/inventory/views.py`
- [ ] T092 [US7] Créer le modèle `RemoteSession` dans `src/helpdesk/models.py` (`technician`, `equipment` obligatoire, `ticket` obligatoire, `started_at` « obligatoire, ≤ maintenant », `ended_at` « obligatoire, > `started_at` », `comment`) avec migration, et `src/helpdesk/services/remote.py` : `declare(ticket, technician, equipment, started_at, ended_at, comment)` créant l'événement et l'entrée d'audit
- [ ] T093 [US7] Créer la route `POST /tickets/<number>/remote/` et le formulaire HTMX « Déclarer une prise en main » sur `ticket_detail.html` ; afficher l'identifiant TeamViewer avec un bouton « Copier » (presse-papiers, sans lien de lancement) sur la fiche ticket et sur `src/inventory/templates/inventory/equipment_detail.html`

**Checkpoint**: toutes les user stories sont fonctionnelles.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: RGPD, sécurité, déploiement, recette.

- [ ] T094 Implémenter `src/core/gdpr.py` : `apply_retention()` (tickets fermés depuis plus de `Settings.retention_years` ans → suppression des notes, pièces jointes et corps d'e-mails, demandeur remplacé par « anonymisé », `requester_email` vidé, e-mails, numéros de téléphone et nom du demandeur masqués dans le titre et la résolution, catégorie/outil/dates/priorité conservés ; utilisateurs inactifs depuis plus de 3 ans et non référencés anonymisés ; entrées d'audit de plus de 3 ans purgées via la variable de session `itsm.audit_purge`) ; `export_person(directory_user)` (JSON de toutes ses données) ; `anonymize_person(directory_user)` ; tâche `core.gdpr_retention` à 03:00 dans `src/core/tasks.py`
- [ ] T095 Créer les vues d'administration `/admin/gdpr/<entra_id>/export/` et `/admin/gdpr/<entra_id>/anonymize/` (confirmation obligatoire, administrateur uniquement, audit `gdpr.export` / `gdpr.anonymize`) dans `src/core/views.py` avec un lien depuis la fiche `DirectoryUser` de l'admin ; ajouter l'aide « ne pas saisir de données personnelles dans la résolution » sous le champ résolution
- [ ] T096 [P] Écrire `tests/integration/test_gdpr.py` (horloge avancée de 3 ans : anonymisation conforme, résolution conservée et masquée, export JSON complet) et `tests/integration/test_audit.py` (`UPDATE`/`DELETE` d'une `AuditEntry` refusés par la base ; purge autorisée uniquement via `apply_retention`)
- [ ] T097 [P] Écrire `tests/integration/test_permissions_matrix.py` : pour chaque route de contracts/ui-routes.md, matrice anonyme / sans rôle / technicien / administrateur → code attendu (redirection, 403, 200)
- [ ] T098 [P] Créer `deploy/containerapps.bicep` (Container Apps `web` et `worker` sur la même image, PostgreSQL Flexible Server, compte de stockage, Key Vault, identité managée, Application Insights, région `francecentral`) et `deploy/README.md` : inscriptions d'applications et permissions Graph, restriction RBAC Exchange des boîtes support, rôles d'application et accès conditionnel MFA, procédure de bascule (redirection de l'adresse support) et de retour arrière vers Atera
- [ ] T099 Passe d'accessibilité et de conformité Armosa sur tous les gabarits de `src/*/templates/` : navigation clavier, focus visible, libellés de formulaires, statut et priorité jamais portés par la seule couleur, un seul bouton `action` par écran, aucune ombre hors menus flottants
- [ ] T100 Exécuter `scripts/check.sh` (ruff, tests, `pip-audit`) et vérifier une couverture ≥ 90 % sur `core/business_time.py`, `helpdesk/services/`, `helpdesk/mail/`, `inventory/services/intune_sync.py`, `core/gdpr.py`, `core/auth.py`
- [ ] T101 Dérouler les scénarios S1 à S9 de [quickstart.md](./quickstart.md) en local puis sur le tenant de test, et consigner les écarts

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** : aucune dépendance.
- **Foundational (Phase 2)** : dépend de Phase 1 ; **bloque toutes les user stories**.
- **US5 (Phase 3)** : dépend de Phase 2.
- **US1 (Phase 4)** : dépend de Phase 2 et de US5 (identification des demandeurs, fiche
  personne, signal de désactivation).
- **US2, US3 (Phases 5–6)** : dépendent de US1 (tickets) ; indépendantes entre elles.
- **US4 (Phase 7)** : dépend de US5 seulement, sauf T077 (lien ticket ↔ équipement) qui
  dépend de US1 ; peut démarrer en parallèle de US1.
- **US6 (Phase 8)** : dépend de US1.
- **US7 (Phase 9)** : dépend de US1 et US4 (T077, `Equipment`).
- **Polish (Phase 10)** : après les user stories souhaitées ; T094–T097 peuvent démarrer dès US1.

### User Story Dependencies

```text
Setup → Foundational → US5 → US1 ─┬─ US2
                          │        ├─ US3
                          │        ├─ US6
                          └─ US4 ──┴─ US7 (US1 + US4)
```

### Within Each User Story

- Fixtures et tests des règles critiques d'abord, puis modèles → services → tâches → vues.
- Une phase est close quand ses tests passent et que son scénario quickstart est validé.
- Commit à la fin de chaque groupe de tâches cohérent (message `feat(<app>): …`, `test(<app>): …`).

### Parallel Opportunities

- Phase 1 : T003 à T008 en parallèle après T001–T002.
- Phase 2 : T012/T013, T017/T018, T020/T021, T023, T025 en parallèle une fois T009–T011 et T014 faits.
- US1 : fixtures et tests T033–T038 en parallèle ; T039, T044, T047, T049, T054, T057 en parallèle.
- Après US1 : US2, US3, US6 en parallèle ; US4 peut avancer dès la fin de US5.

---

## Parallel Example: User Story 1

```bash
# Fixtures et tests des règles critiques :
Task: "T033 Fixtures e-mail dans tests/fixtures/mail/"
Task: "T034 Tests d'analyse des e-mails dans tests/unit/test_mail_parsing.py"
Task: "T035 Tests de la machine à états dans tests/unit/test_ticket_lifecycle.py"

# Briques indépendantes :
Task: "T039 Référentiels Category/Tool/TechnicianGroup/Skill dans src/helpdesk/models.py"
Task: "T044 Analyse des e-mails dans src/helpdesk/mail/parsing.py"
Task: "T047 Gabarits e-mail dans src/core/templates/email/ et src/helpdesk/templates/email/"
```

## Parallel Example: User Story 4

```bash
Task: "T073 Fixtures Intune dans tests/fixtures/graph/"
Task: "T074 Tests de synchro Intune dans tests/integration/test_intune_sync.py"
Task: "T076 Modèles du parc dans src/inventory/models.py"
```

---

## Implementation Strategy

### MVP First (US5 + US1)

1. Phase 1 Setup puis Phase 2 Foundational.
2. Phase 3 (US5) : annuaire synchronisé.
3. Phase 4 (US1) : tickets par e-mail et manuels.
4. **STOP et VALIDER** : quickstart S1, S2, S6 ; pilote sur une boîte support de test, en
   parallèle d'Atera.

### Incremental Delivery

1. MVP → pilote.
2. US2 + US3 (affectation, délais, rappels) → l'équipe peut traiter tout son flux dans l'ITSM.
3. US4 (parc et licences) → remplacement de l'inventaire Atera.
4. US6 + US7 (base de résolution, TeamViewer) → confort et traçabilité.
5. Polish (RGPD, déploiement Azure, recette S1–S9) → bascule de l'adresse support.

---

## Notes

- [P] = fichiers différents, sans dépendance sur une tâche non terminée.
- Les valeurs paramétrables (délais, rappels, rétention, boîtes, domaines) viennent de
  `Settings`, jamais de constantes dans le code.
- Aucune écriture vers Entra ou Intune ; aucun secret dans le dépôt.
- Les tokens d'état Armosa (R16) sont à reporter dans le design system Armosa (hors dépôt).
