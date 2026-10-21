# Phase 1 — Modèle de données : ticketing et gestion de parc

**Feature** : `001-ticketing-gestion-parc` | **Date** : 2026-10-21 | **Plan** : [plan.md](./plan.md)

Conventions : chaque entité possède un identifiant technique `id`, `created_at` et
`updated_at` (non répétés ci-dessous). Les dates sont stockées en UTC et affichées en
`Europe/Paris`. « → X » désigne une référence vers l'entité X. Les entités sont regroupées par
module applicatif (voir la structure du code dans [plan.md](./plan.md)).

---

## Module `directory` — annuaire synchronisé avec Entra

### Filiale (`Subsidiary`)

| Champ | Type | Règles |
|---|---|---|
| `name` | texte | unique, obligatoire |
| `entra_company_names` | liste de textes | valeurs de `companyName` Entra correspondant à cette filiale |
| `is_active` | booléen | défaut vrai |

### Site (`Site`)

| Champ | Type | Règles |
|---|---|---|
| `name` | texte | unique, obligatoire |
| `subsidiary` | → Filiale | optionnel |
| `address` | texte | optionnel |
| `entra_office_locations` | liste de textes | valeurs `officeLocation` Entra correspondant à ce site |
| `is_active` | booléen | défaut vrai |

### Utilisateur d'annuaire (`DirectoryUser`)

Toute personne présente dans Entra (demandeur, technicien ou non).

| Champ | Type | Règles |
|---|---|---|
| `entra_id` | UUID | unique, obligatoire (identifiant objet Entra) |
| `display_name`, `given_name`, `surname` | texte | depuis Entra |
| `email` | e-mail | unique (insensible à la casse) si renseigné ; clé d'identification des e-mails entrants |
| `upn` | texte | unique |
| `job_title`, `department` | texte | depuis Entra |
| `subsidiary` | → Filiale | déduite de `companyName` ; peut être vide |
| `site` | → Site | déduit de `officeLocation` ; peut être vide |
| `manager` | → DirectoryUser | optionnel |
| `is_active` | booléen | reflète `accountEnabled` et la présence dans Entra |
| `deactivated_at` | date-heure | renseignée au passage inactif |
| `anonymized_at` | date-heure | renseignée par la purge RGPD ; les champs personnels sont alors vidés |
| `last_synced_at` | date-heure | |

Règles : jamais supprimé physiquement par la synchro ; les champs issus d'Entra ne sont pas
modifiables dans l'ITSM.

### Compte applicatif (`Account`, utilisateur Django)

| Champ | Type | Règles |
|---|---|---|
| `directory_user` | → DirectoryUser | un pour un, rattaché par l'`oid` du jeton OIDC |
| `roles` | ensemble {`technicien`, `administrateur`} | recopié de la revendication `roles` à chaque connexion |
| `is_active` | booléen | faux si l'utilisateur d'annuaire est inactif ou n'a plus de rôle |
| `last_login` | date-heure | |

Un « technicien » est un compte ayant le rôle `technicien` ou `administrateur`.

### Exécution de synchronisation (`SyncRun`)

| Champ | Type | Règles |
|---|---|---|
| `kind` | énum {`entra_users`, `intune_devices`, `mailbox`} | |
| `mailbox` | texte | pour `kind = mailbox` |
| `started_at`, `finished_at` | date-heure | |
| `status` | énum {`running`, `success`, `failed`} | |
| `created`, `updated`, `deactivated`, `skipped` | entiers | compteurs |
| `error` | texte | message d'erreur sans données personnelles |
| `delta_token` | texte | jeton delta Graph pour la reprise (Entra, messagerie) |

---

## Module `helpdesk` — tickets, affectation, délais, base de résolution

### Catégorie (`Category`)

| Champ | Type | Règles |
|---|---|---|
| `name` | texte | obligatoire ; unique parmi les catégories de même parent |
| `parent` | → Category | vide pour le niveau 1 |
| `level` | entier 1–3 | calculé : niveau du parent + 1 ; **un niveau 4 est refusé** |
| `is_active` | booléen | une catégorie inactive n'est plus proposée mais reste sur les tickets existants |
| `position` | entier | ordre d'affichage |

### Outil (`Tool`)

| Champ | Type | Règles |
|---|---|---|
| `name` | texte | unique, obligatoire |
| `description` | texte | optionnel |
| `default_group` | → TechnicianGroup | optionnel ; groupe compétent sur l'outil |
| `is_active` | booléen | |

### Compétence (`Skill`)

| Champ | Type | Règles |
|---|---|---|
| `technician` | → Account | doit avoir le rôle technicien ou administrateur |
| `tool` | → Tool | |

Unicité (`technician`, `tool`). Supprimée automatiquement quand le technicien devient inactif.

### Groupe de techniciens (`TechnicianGroup`)

| Champ | Type | Règles |
|---|---|---|
| `name` | texte | unique |
| `members` | ensemble → Account | techniciens actifs uniquement |
| `email` | e-mail | optionnel ; destinataire des alertes du groupe, sinon chaque membre |

### Ticket (`Ticket`)

| Champ | Type | Règles |
|---|---|---|
| `number` | entier | séquence unique, affiché `T-00042` (5 chiffres minimum) |
| `title` | texte (≤ 255) | obligatoire ; objet de l'e-mail ou saisi |
| `description` | texte | corps texte ; `description_html` assaini en parallèle |
| `channel` | énum {`email`, `app`} | canal de création (FR-014a) |
| `mailbox` | e-mail | boîte support d'origine (expéditeur des réponses) ; boîte par défaut si création dans l'application |
| `created_by` | → Account | renseigné si `channel = app` |
| `requester` | → DirectoryUser | vide si expéditeur non identifié ou anonymisé |
| `requester_email` | e-mail | adresse d'origine, conservée pour les réponses ; vidée à l'anonymisation |
| `subsidiary` | → Filiale | « Entité » dans l'interface ; recopiée du demandeur à la création, modifiable (cas limite multi-filiales) |
| `site` | → Site | site du demandeur, recopié à la création, modifiable (FR-019) |
| `type` | énum {`incident`, `demande`} | vide tant que non qualifié |
| `category` | → Category | nœud de niveau 1 à 3 |
| `tool` | → Tool | optionnel ; déclenche l'affectation automatique |
| `priority` | énum {`haute`, `normale`, `basse`} | défaut `normale` |
| `status` | énum (voir machine à états) | défaut `cree` |
| `assignee` | → Account | technicien responsable |
| `assigned_group` | → TechnicianGroup | groupe affecté |
| `assignment_mode` | énum {`auto`, `manuel`, `aucun`} | |
| `equipment` | ensemble → Equipment | équipements liés (FR-017) |
| `related_ticket` | → Ticket | ticket fermé auquel ce ticket fait suite |
| `acknowledged_at` | date-heure | date de prise en compte (FR-036) |
| `ack_due_at` | date-heure | échéance de prise en compte (FR-037) |
| `ack_business_minutes` | entier | délai de prise en compte mesuré en minutes ouvrées |
| `ack_breached` | booléen | vrai si `acknowledged_at` > `ack_due_at` ou échéance dépassée sans prise en compte |
| `breach_alerted_at` | date-heure | une seule alerte par ticket |
| `waiting_since` | date-heure | entrée en `attente_reponse` |
| `reminders_sent` | entier 0–3 | |
| `last_reminder_at` | date-heure | |
| `resolution` | texte | obligatoire pour `resolu` (FR-032) |
| `resolution_kind` | énum {`technicien`, `sans_reponse`} | |
| `resolved_at`, `closed_at` | date-heure | |
| `has_unread_reply` | booléen | réponse du demandeur non lue par le technicien |
| `search_vector` | tsvector (colonne générée) | titre + description + résolution, config `french` + `unaccent` |
| `anonymized_at` | date-heure | |

**Règles de validation** :
- Le passage `cree → pris_en_compte` exige `type`, `category` et `subsidiary` renseignés
  (qualification minimale) ; `priority` a toujours une valeur.
- `assignee` et `assigned_group` peuvent coexister : le groupe est la file, l'assigné la
  personne qui a pris le ticket (FR-023).
- `ack_due_at` = `created_at` + cible de la priorité en temps ouvré ; recalculé si la priorité
  change tant que `acknowledged_at` est vide.

#### Machine à états du ticket (FR-030)

États : `cree` (créé), `pris_en_compte`, `attente_reponse` (en attente de réponse),
`en_attente`, `resolu`, `ferme`.

| De | Vers | Déclencheur | Effets |
|---|---|---|---|
| `cree` | `pris_en_compte` | technicien (« Prendre en compte ») | `acknowledged_at`, délai de prise en compte calculé ; l'assigné devient l'acteur s'il n'y en a pas |
| `cree` | `resolu` | technicien (résolution immédiate) | `acknowledged_at` = maintenant ; résolution obligatoire ; e-mail de résolution |
| `pris_en_compte` | `attente_reponse` | technicien | `waiting_since`, `reminders_sent = 0` |
| `pris_en_compte` | `en_attente` | technicien (dépendance externe) | aucun rappel |
| `attente_reponse` | `pris_en_compte` | réponse du demandeur (automatique) ou technicien | compteur de rappels remis à zéro ; `has_unread_reply` |
| `en_attente` | `pris_en_compte` | technicien | |
| `pris_en_compte`, `attente_reponse`, `en_attente` | `resolu` | technicien | résolution obligatoire ; e-mail de résolution |
| `attente_reponse` | `resolu` | système, 2 jours ouvrés après le 3e rappel | `resolution_kind = sans_reponse` ; e-mail de résolution |
| `resolu` | `pris_en_compte` | réponse du demandeur dans les 5 jours ouvrés, ou technicien | `resolved_at` effacé |
| `resolu` | `ferme` | système (5 jours ouvrés) ou technicien | `closed_at` |
| `ferme` | — | état final | une réponse crée un nouveau ticket lié (`related_ticket`) |

Toute autre transition est refusée. Une réponse du demandeur reçue en `cree`, `pris_en_compte`
ou `en_attente` ajoute une note externe sans changer le statut (`has_unread_reply` = vrai).

#### Règle d'affectation automatique (FR-021 à FR-023)

Exécutée quand `tool` est renseigné ou modifié **et** que le ticket est en `cree` **et** que
`assignment_mode` ≠ `manuel` :

1. `C` = techniciens actifs ayant une compétence sur l'outil.
2. Si `|C| = 1` → `assignee` = ce technicien.
3. Sinon, si l'outil a un `default_group` → `assigned_group` = ce groupe, `assignee` vide.
4. Sinon, si `|C| ≥ 2` → `assignee` = le technicien de `C` ayant le moins de tickets ouverts
   (statuts autres que `resolu`/`ferme`) ; à égalité, celui affecté le moins récemment.
5. Sinon → aucune affectation, le ticket reste dans la file de dispatch.

`assignment_mode` = `auto` dans les cas 2 à 4. Une réaffectation par un technicien passe
`assignment_mode` à `manuel` (plus d'affectation automatique ensuite) et crée un événement.

### Note (`TicketNote`)

| Champ | Type | Règles |
|---|---|---|
| `ticket` | → Ticket | |
| `visibility` | énum {`interne`, `externe`} | une note interne n'est jamais envoyée par e-mail |
| `direction` | énum {`entrant`, `sortant`, `interne`} | `entrant` = e-mail du demandeur |
| `author` | → Account | vide pour un e-mail entrant |
| `author_email` | e-mail | expéditeur pour un e-mail entrant |
| `body_text`, `body_html` | texte | HTML assaini |
| `email_message` | → EmailMessage | e-mail entrant ou sortant associé |

### Pièce jointe (`Attachment`)

| Champ | Type | Règles |
|---|---|---|
| `ticket` | → Ticket | |
| `note` | → TicketNote | optionnel |
| `file` | fichier (Blob Storage) | ≤ 25 Mo |
| `filename`, `content_type`, `size` | | |
| `content_id` | texte | pour les images inline `cid:` |

### Message e-mail (`EmailMessage`)

| Champ | Type | Règles |
|---|---|---|
| `direction` | énum {`entrant`, `sortant`} | |
| `mailbox` | e-mail | boîte support concernée |
| `graph_id` | texte | identifiant Graph |
| `internet_message_id` | texte | **unique** : anti-doublon et rattachement des réponses |
| `conversation_id` | texte | identifiant de conversation Exchange |
| `in_reply_to`, `references` | texte | en-têtes du message entrant |
| `ticket` | → Ticket | vide si ignoré |
| `kind` | énum {`accuse_reception`, `note_externe`, `rappel`, `resolution`, `alerte_technicien`, `entrant`} | liste fermée (FR-038) |
| `processing` | énum {`ticket_cree`, `note_ajoutee`, `ignore_automatique`, `ignore_boucle`, `ignore_limite`, `a_envoyer`, `envoye`, `simule`, `echec`} | `simule` : Graph désactivé (développement) |
| `subject`, `from_address`, `to_addresses` | texte | objet, expéditeur, destinataires |
| `body_html`, `body_text` | texte | corps rendu des e-mails sortants (les corps entrants sont dans les notes) |
| `sent_at` / `received_at` | date-heure | |
| `error` | texte | |

### Saisie de temps (`TimeEntry`)

| Champ | Type | Règles |
|---|---|---|
| `ticket` | → Ticket | |
| `technician` | → Account | |
| `date` | date | ≤ aujourd'hui |
| `minutes` | entier | 1 à 1 440 |
| `comment` | texte | optionnel |

Agrégats affichés : total du ticket ; total par technicien sur le ticket ; total par technicien
sur une période (vue de suivi).

### Événement de ticket (`TicketEvent`)

| Champ | Type | Règles |
|---|---|---|
| `ticket` | → Ticket | |
| `at` | date-heure | |
| `actor` | → Account | vide = système |
| `kind` | énum {`creation`, `statut`, `priorite`, `categorie`, `type`, `outil`, `affectation`, `filiale`, `site`, `demandeur`, `note`, `temps`, `resolution`, `equipement`, `rappel`, `alerte_delai`, `prise_en_main`, `fusion_reponse`} | |
| `old_value`, `new_value` | texte | libellés lisibles |
| `data` | JSON | détails complémentaires |

En ajout seul ; affiché dans l'ordre chronologique (FR-040, US6-1).

### Session de prise en main (`RemoteSession`)

Intervention TeamViewer **déclarée** par le technicien après coup ; l'ITSM ne lance pas
TeamViewer (R13).

| Champ | Type | Règles |
|---|---|---|
| `technician` | → Account | technicien déclarant |
| `equipment` | → Equipment | obligatoire ; de préférence un équipement lié au ticket |
| `ticket` | → Ticket | obligatoire |
| `started_at` | date-heure | obligatoire, ≤ maintenant |
| `ended_at` | date-heure | obligatoire, > `started_at` |
| `comment` | texte | optionnel |

---

## Module `inventory` — gestion de parc

### Type d'équipement (`EquipmentType`)

| Champ | Type | Règles |
|---|---|---|
| `name` | texte | unique ; valeurs initiales : PC, Écran, Imprimante, Télévision, Caméra, Téléphone, Tablette |
| `is_active` | booléen | extensible par un administrateur (FR-060) |

### Équipement (`Equipment`)

| Champ | Type | Règles |
|---|---|---|
| `type` | → EquipmentType | obligatoire |
| `source` | énum {`intune`, `manuel`} | |
| `name` | texte | nom d'appareil Intune ou libellé saisi |
| `manufacturer`, `model` | texte | |
| `serial_number` | texte | normalisé (majuscules, sans espaces) ; unique quand non vide et non générique |
| `os`, `os_version` | texte | Intune |
| `intune_id` | UUID | unique si renseigné |
| `intune_primary_user` | → DirectoryUser | utilisateur principal Intune |
| `intune_last_sync_at`, `intune_enrolled_at` | date-heure | |
| `intune_removed_at` | date-heure | appareil absent de la dernière synchro (« retiré d'Intune ») |
| `site` | → Site | **obligatoire** (FR-061) ; « À définir » par défaut pour un appareil Intune sans site déduit |
| `status` | énum {`stock`, `en_utilisation`} | obligatoire (FR-061) |
| `assigned_to` | → DirectoryUser | optionnel |
| `teamviewer_id` | texte | identifiant TeamViewer (9 à 10 chiffres, espaces ignorés) ; optionnel |
| `purchase_date`, `warranty_end` | date | optionnels |
| `notes` | texte | |

**Règles** :
- Si `source = intune` : `name`, `manufacturer`, `model`, `serial_number`, `os`, `os_version`,
  `intune_*` sont en lecture seule dans l'interface (FR-062) ; `site`, `status`,
  `assigned_to`, `teamviewer_id`, `notes` restent modifiables.
- Affecter un équipement en `stock` à un utilisateur le passe en `en_utilisation` ; retirer
  l'affectation propose de le repasser en `stock` (US4-4).
- À sa création par la synchro, `assigned_to` = `intune_primary_user` ; ensuite la synchro ne
  remplace `assigned_to` que si l'utilisateur principal Intune change.
- Rapprochement (FR-003) : un équipement `manuel` dont le numéro de série correspond à un
  appareil Intune devient `source = intune` et reçoit les champs Intune ; son historique est
  conservé.

### Licence (`Licence`)

| Champ | Type | Règles |
|---|---|---|
| `name` | texte | obligatoire (ex. « Adobe Acrobat Pro ») |
| `vendor` | texte | |
| `seats` | entier ≥ 1 | nombre de postes |
| `expires_at` | date | optionnelle (licence perpétuelle) |
| `assigned_users` | ensemble → DirectoryUser | consommateurs |
| `assigned_equipment` | ensemble → Equipment | consommateurs |
| `subsidiary` | → Filiale | optionnel |
| `notes` | texte | sans clé de licence en clair |

Règles : postes consommés = utilisateurs + équipements affectés ; dépassement signalé si
consommés > `seats` ; licence signalée si `expires_at` ≤ aujourd'hui + 30 jours (FR-064).
Les clés de licence ne sont pas stockées (principe II).

### Événement d'équipement (`EquipmentEvent`)

Même structure que `TicketEvent` ; `kind` ∈ {`creation`, `affectation`, `site`, `statut`,
`rapprochement_intune`, `retrait_intune`, `retour_intune`, `modification`}. Les licences
utilisent la même table avec une référence vers la licence.

---

## Module `core` — paramètres, calendrier, audit

### Paramètres (`Settings`, instance unique)

| Champ | Défaut | Exigence |
|---|---|---|
| `ack_target_minutes` par priorité | haute 60, normale 240, basse 540 (minutes ouvrées) | FR-037 |
| `business_hours` | lun–ven 09:00–18:00, `Europe/Paris` | Hypothèses |
| `reminder_delay_business_days` | 2 | FR-034 |
| `max_reminders` | 3 | FR-034 |
| `auto_close_business_days` | 5 | FR-033 |
| `retention_years` | 3 | FR-072 |
| `support_mailboxes` | liste | FR-010 |
| `internal_domains` | liste | accusé de réception des inconnus (R10) |
| `licence_expiry_warning_days` | 30 | FR-064 |

### Jour de fermeture (`ClosureDay`)

| Champ | Type | Règles |
|---|---|---|
| `date` | date | unique ; s'ajoute aux fériés français |
| `label` | texte | |

### Entrée d'audit (`AuditEntry`)

| Champ | Type | Règles |
|---|---|---|
| `at` | date-heure | |
| `actor` | → Account | vide = système |
| `action` | texte | ex. `remote_session.declare`, `skill.change`, `group.change`, `role.change`, `equipment.delete`, `gdpr.export`, `gdpr.anonymize`, `settings.change` |
| `target_type`, `target_id` | texte | |
| `details` | JSON | sans secret |
| `ip_address` | texte | |

En ajout seul (déclencheur PostgreSQL refusant `UPDATE`/`DELETE`, sauf purge de rétention
à 3 ans).

---

## Relations principales

```text
Subsidiary 1─* Site            Subsidiary 1─* DirectoryUser       DirectoryUser 1─0..1 Account
Account *─* TechnicianGroup    Account *─* Tool (via Skill)       Tool *─0..1 TechnicianGroup
Category 1─* Category (3 niveaux)
Ticket *─1 DirectoryUser (requester)   Ticket *─1 Subsidiary   Ticket *─0..1 Category
Ticket *─0..1 Tool   Ticket *─0..1 Account (assignee)   Ticket *─0..1 TechnicianGroup
Ticket *─* Equipment   Ticket 1─* TicketNote / Attachment / TimeEntry / TicketEvent / EmailMessage
Equipment *─1 EquipmentType   Equipment *─1 Site   Equipment *─0..1 DirectoryUser (assigned_to)
Licence *─* DirectoryUser   Licence *─* Equipment   RemoteSession *─1 Equipment, *─0..1 Ticket
```

## Index et performances

- `Ticket` : index sur (`status`, `assignee`), (`status`, `assigned_group`), `ack_due_at`
  (tickets non pris en compte), `waiting_since`, `resolved_at`, `closed_at` ; GIN sur
  `search_vector`.
- `DirectoryUser` : index sur `lower(email)` et trigrammes sur `display_name` (recherche du
  demandeur à la création manuelle, FR-014).
- `Equipment` : index sur `serial_number`, `intune_id`, (`site`, `status`), `assigned_to`.
- `EmailMessage` : unique sur `internet_message_id`, index sur `conversation_id`.
