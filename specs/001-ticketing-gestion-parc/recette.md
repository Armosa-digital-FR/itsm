# Recette — ticketing et gestion de parc

**Feature** : `001-ticketing-gestion-parc` | **Date** : 2026-10-21 | **Guide** : [quickstart.md](./quickstart.md)

## Synthèse

| Contrôle | Résultat |
|---|---|
| `scripts/check.sh` (ruff, migrations à jour, aller-retour des migrations, tests, `pip-audit`) | ✅ tout passe |
| Tests unitaires et d'intégration | ✅ 454 tests |
| Couverture | ✅ 94 % au total ; modules critiques ≥ 93 % (`business_time` 96 %, `lifecycle` 98 %, `tickets` 93 %, `mail/*` 93–99 %, `intune_sync` 96 %, `gdpr` 97 %, `auth` 100 %) |
| Parcours de bout en bout (Playwright, Chromium) | ✅ S1, S2, S5 |
| Volumétrie doublée (SC-009, `pytest -m perf`) | ✅ toutes les pages < 120 ms (objectif 2 s), ≤ 25 requêtes SQL |
| Accessibilité (axe-core, WCAG 2.1 AA) | ✅ aucune violation sur 13 pages |
| Vulnérabilités des dépendances | ✅ aucune connue |

## Scénarios du quickstart

| Scénario | Local (Graph simulé) | Tenant de test | Preuves automatisées |
|---|---|---|---|
| S1 — e-mail jusqu'à la fermeture | ✅ | ⏳ à faire | `e2e/test_s1_ticket_email.py`, `test_mail_inbound.py`, `test_ticket_lifecycle.py`, `test_helpdesk_misc.py` (fermeture à J+5) |
| S2 — création manuelle | ✅ | ⏳ | `e2e/test_s2_ticket_manual.py`, `test_ticket_views.py` |
| S3 — affectation automatique | ✅ | — | `test_assignment.py`, `test_assignment_views.py` |
| S4 — délais et rappels | ✅ | — | `test_sla.py`, `test_reminders.py`, `test_tracking.py` |
| S5 — parc | ✅ (manuel) | ⏳ synchro Intune réelle | `e2e/test_s5_inventory.py`, `test_intune_sync.py`, `test_inventory_views.py` |
| S6 — annuaire Entra | ✅ (simulé) | ⏳ synchro Entra réelle | `test_entra_sync.py` |
| S7 — base de résolution | ✅ | — | `test_knowledge.py` |
| S8 — TeamViewer | ✅ | — | `test_remote_sessions.py` |
| S9-1 à 4 — sécurité, RGPD, audit | ✅ | — | `test_permissions_matrix.py`, `test_gdpr.py`, `test_audit.py` |
| S9-5 — boîte non support refusée | — | ⏳ | nécessite le RBAC Exchange du tenant (`deploy/README.md` §5) |

## Reste à faire sur le tenant de test (T103)

1. Inscrire l'application « ITSM » et les rôles (`docs/configuration-entra.md`), se connecter
   avec un compte Technicien et un compte sans rôle.
2. Déployer (`deploy/README.md`) ou lancer en local avec `ITSM_GRAPH_ENABLED=true` et une
   identité à certificat ; lancer les synchros Entra et Intune depuis l'admin et comparer les
   compteurs (SC-004).
3. Envoyer un e-mail réel à la boîte de test et dérouler S1 ; vérifier la réception de
   l'accusé (< 5 min, SC-001) et le rattachement des réponses depuis Outlook.
4. Vérifier S9-5 (`Test-ServicePrincipalAuthorization`, lecture Graph refusée).
5. Tester une fois la procédure de bascule et de retour arrière vers Atera.

## Écarts constatés et corrigés pendant la recette locale

- Champ date de la saisie de temps vide dans le navigateur (format français) → format ISO.
- Recherche d'annuaire non déclenchée par un collage → événement `input`.
- Purge de l'audit laissant la protection levée dans une transaction englobante → réarmement.
- Images intégrées des e-mails perdues ; limite de 20 e-mails/h fondée sur une date falsifiable.
- Sonde de santé Azure rejetée par `ALLOWED_HOSTS` → en-tête `Host` dans la sonde.
- Contraste du texte secondaire sur fonds linen/sauge, hiérarchie des titres (axe-core).
