# Contrat — Tâches planifiées et asynchrones

Exécutées par le processus *worker* (Procrastinate, file adossée à PostgreSQL). Chaque tâche
est idempotente : une double exécution ne produit ni doublon ni double e-mail. Les tâches
périodiques sont verrouillées (une seule instance à la fois).

| Tâche | Planification | Exigences | Effet |
|---|---|---|---|
| `mail.poll_mailboxes` | chaque minute | FR-010 à FR-013, SC-001 | relève de chaque boîte support selon [email.md](./email.md) ; un `SyncRun` par boîte |
| `mail.send` | à la demande, 3 tentatives (1, 5, 15 min) | FR-012, FR-031, FR-034, FR-038 | envoi d'un `EmailMessage` sortant ; statut `envoye` ou `echec` |
| `directory.sync_entra` | toutes les 30 min ; complète à 02:00 | FR-001, US5 | synchro delta des utilisateurs ; effets de désactivation (compétences, groupes, alertes) |
| `inventory.sync_intune` | toutes les heures | FR-002, FR-003, US4 | synchro complète des appareils et rapprochement |
| `helpdesk.check_ack_deadlines` | toutes les 5 min | FR-037, US3-1 | marque `ack_breached` ; alerte une fois par ticket |
| `helpdesk.send_reminders` | toutes les heures, en heures ouvrées | FR-034, US3-2, US3-3 | rappels et résolution automatique « sans réponse » |
| `helpdesk.auto_close` | toutes les heures | FR-033 | `resolu` → `ferme` après 5 jours ouvrés |
| `inventory.licence_digest` | lundi 08:00 | FR-064 | récapitulatif des licences à échéance ou en dépassement |
| `core.gdpr_retention` | chaque jour à 03:00 | FR-072, constitution III | anonymisation des tickets fermés depuis plus de 3 ans, des utilisateurs inactifs depuis plus de 3 ans non référencés ; purge de l'audit de plus de 3 ans |

Toutes les durées « ouvrées » utilisent le calendrier de `core.business_time` (plages
paramétrées, fériés français, jours de fermeture). Les valeurs (2 jours, 3 rappels, 5 jours,
3 ans, 30 jours) proviennent de `Settings` et non du code.
