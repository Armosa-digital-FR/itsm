# Implementation Plan: Gestion de maintenance (ticketing) et gestion de parc

**Branch**: `001-ticketing-gestion-parc` | **Date**: 2026-10-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-ticketing-gestion-parc/spec.md`

## Summary

Remplacer le ticketing et l'inventaire d'Atera par une application interne : tickets créés par
e-mail ou par un technicien, qualifiés (type, catégorie à 3 niveaux, outil, priorité), affectés
automatiquement selon les compétences, suivis en délai de prise en compte (heures ouvrées),
relancés automatiquement, résolus puis fermés ; base de résolution consultable ; parc
synchronisé depuis Intune et complété à la main (équipements, licences, sites, statut) ;
annuaire synchronisé depuis Entra ; prise en main à distance lancée depuis l'ITSM.

Approche technique ([research.md](./research.md)) : **monolithe modulaire Django 5.2 LTS**
(Python 3.12) rendu côté serveur avec HTMX, **PostgreSQL 16** comme unique stockage
(données, recherche plein texte française, file de tâches **Procrastinate**), **Microsoft
Graph** en lecture seule pour Entra et Intune et pour les boîtes support Exchange, connexion
**OIDC Entra ID** avec rôles d'application, hébergement **Azure France Central** en conteneurs
(web + worker) avec identité managée. Interface et e-mails aux couleurs du design system
**Armosa**.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: Django 5.2 LTS ; HTMX 2 ; Procrastinate (tâches, adossé à
PostgreSQL) ; mozilla-django-oidc (connexion Entra) ; azure-identity + httpx (Microsoft Graph) ;
django-storages[azure] (pièces jointes) ; nh3 (assainissement HTML) ; holidays (fériés
français) ; gunicorn

**Storage**: PostgreSQL 16 (Azure Database for PostgreSQL Flexible Server) ; Azure Blob Storage
pour les pièces jointes

**Testing**: pytest + pytest-django, factory_boy, respx (Graph simulé), time-machine (horloge),
Playwright (3 parcours e2e) ; ruff ; pip-audit

**Target Platform**: conteneurs Linux sur Azure Container Apps (France Central) ; navigateurs
récents (Edge, Chrome, Firefox) sur poste de technicien

**Project Type**: application web (monolithe Django rendu serveur) + processus worker

**Performance Goals**: pages et listes affichées en moins de 2 s (SC-009) ; accusé de réception
en moins de 5 min (SC-001, relève chaque minute) ; synchro Intune complète (1 000 appareils)
en moins de 2 min

**Constraints**: données hébergées dans l'UE, chiffrées en transit et au repos ; aucune écriture
dans Entra/Intune ; permissions messagerie limitées aux boîtes support ; polices auto-hébergées ;
aucun e-mail au demandeur hors liste fermée FR-038

**Scale/Scope**: ~500 utilisateurs d'annuaire, ~1 000 équipements, ~300 tickets/mois, ≤ 10
techniciens simultanés, croissance ×2 sans changement d'architecture ; ~20 écrans + admin

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principe / section | Vérification | Statut |
|---|---|---|
| **I. Simplicité (YAGNI)** | Monolithe modulaire, un dépôt, une image. Pas de SPA, pas de broker, pas de moteur de recherche : PostgreSQL couvre données, recherche et file de tâches. Référentiels gérés par l'admin Django. Prise en main par modèle d'URL plutôt qu'intégration d'API éditeur. Seul le reporting strictement demandé est inclus. Écarts justifiés dans *Complexity Tracking*. | ✅ |
| **II. Sécurité par conception** | OIDC Entra + rôles d'application vérifiés côté serveur sur chaque vue (matrice testée) ; MFA par accès conditionnel ; aucun secret dans le code (identité managée, Key Vault) ; permissions Graph minimales, messagerie restreinte aux boîtes support ; journal d'audit en ajout seul (déclencheur PostgreSQL) pour prise en main, droits, compétences, paramètres, suppressions et RGPD ; HTML entrant assaini (nh3), CSRF, limites de taille des pièces jointes ; `pip-audit` en CI. | ✅ |
| **III. RGPD** | Minimisation : seuls les attributs Entra utiles sont lus ; rétention 3 ans puis anonymisation automatique (FR-072) ; export et anonymisation à la demande depuis l'admin (droits des personnes sans accès base) ; hébergement France Central, TLS, chiffrement au repos ; données, finalité et durée documentées (research R15) pour le registre ; polices auto-hébergées (pas d'IP transmise à Google). | ✅ |
| **IV. IA assistive** | Aucune fonctionnalité d'IA dans cette feature (qualification manuelle). La base de résolution et l'historique structuré préparent les futures fonctionnalités, qui devront repasser ce contrôle. | ✅ (N/A) |
| **V. Remplacement progressif d'Atera** | Pilote en parallèle d'Atera sur une boîte dédiée ; bascule par redirection de l'adresse support, retour arrière par rétablissement de la redirection (quickstart) ; exports CSV ; migration de l'historique Atera traitée par une feature distincte avec scripts vérifiables. | ✅ |
| **Contraintes techniques et d'hébergement** | Pile justifiée (research R1–R5) ; hébergement et sous-traitants UE (Azure France Central, Microsoft 365) ; aucun agent supplémentaire installé sur le parc (Intune seul). | ✅ |
| **Workflow et contrôles qualité** | Tests automatisés obligatoires sur permissions, délais/SLA, cycle de vie, affectation, rappels, rapprochement Intune, analyse e-mail, purge RGPD (research R17) ; migrations Django versionnées et réversibles (`RunPython` avec fonction inverse) ; revue de code avec contrôle accès/données/secrets. | ✅ |

**Résultat avant Phase 0** : aucun blocage. **Réévaluation après Phase 1** (data-model,
contrats) : aucun nouvel écart ; le seul ajout par rapport à la spec est l'export/anonymisation
RGPD à la demande et les exports CSV, exigés directement par la constitution (III et V).

**Décisions prises par défaut, à confirmer par l'équipe** (réversibles, sans impact sur la
spec) : pile Python/Django (R1), hébergement Azure (R5), outil de prise en main à distance (R13 :
lanceur générique ; l'outil réel reste à nommer — si c'est le Splashtop intégré à Atera, prévoir
un remplaçant avant la bascule).

## Project Structure

### Documentation (this feature)

```text
specs/001-ticketing-gestion-parc/
├── plan.md              # ce fichier
├── research.md          # Phase 0 : décisions R1 à R19
├── data-model.md        # Phase 1 : entités, machine à états, règle d'affectation
├── quickstart.md        # Phase 1 : mise en route et scénarios de validation S1 à S9
├── contracts/
│   ├── ui-routes.md          # écrans, routes, rôles
│   ├── email.md              # messagerie entrante/sortante, liste fermée FR-038
│   ├── graph-integration.md  # permissions, appels et correspondances Graph
│   └── scheduled-jobs.md     # tâches planifiées
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
pyproject.toml · uv.lock · manage.py · Dockerfile · docker-compose.yml · .env.example
src/
├── itsm/                     # projet Django
│   ├── settings/             # base.py, dev.py, prod.py
│   ├── urls.py · wsgi.py
│   └── worker.py             # application Procrastinate et planifications
├── core/                     # transverse
│   ├── business_time.py      # calendrier ouvré (plages, fériés, fermetures)
│   ├── graph.py              # client Graph mince (jetons, pagination, reprises)
│   ├── audit.py              # écriture du journal d'audit
│   ├── gdpr.py               # rétention, anonymisation, export
│   ├── models.py             # Settings, ClosureDay, AuditEntry
│   ├── auth.py               # backend OIDC, rôles, décorateurs d'accès
│   ├── templates/            # gabarit de base, gabarits e-mail
│   └── static/               # css/tokens.css, css/app.css, fonts/, img/logo.svg, img/logo.png, js/htmx.min.js
├── directory/                # Subsidiary, Site, DirectoryUser, Account, SyncRun ; sync Entra ; fiche personne
├── helpdesk/                 # tickets
│   ├── models.py             # Category, Tool, Skill, TechnicianGroup, Ticket, TicketNote, Attachment,
│   │                         # EmailMessage, TimeEntry, TicketEvent, RemoteSession
│   ├── services/             # lifecycle.py (machine à états), assignment.py, sla.py,
│   │                         # reminders.py, knowledge.py, remote.py
│   ├── mail/                 # inbound.py (relève, rattachement), parsing.py, outbound.py
│   ├── tasks.py · views.py · urls.py · templates/helpdesk/
│   └── admin.py
└── inventory/                # EquipmentType, Equipment, Licence, EquipmentEvent ; sync Intune
    ├── services/             # intune_sync.py, licences.py
    ├── tasks.py · views.py · urls.py · templates/inventory/
    └── admin.py

tests/
├── unit/                     # business_time, lifecycle, assignment, sla, reminders, parsing, gdpr
├── integration/              # vues + permissions, relève/envoi (respx), sync Entra/Intune (respx)
├── e2e/                      # Playwright : S1, S2, S5
└── fixtures/                 # mail/*.eml, graph/*.json

deploy/                       # définition Azure Container Apps (web, worker), procédure de bascule et de retour arrière
```

**Structure Decision**: un seul projet Django à la racine, découpé en quatre applications par
domaine (`core`, `directory`, `helpdesk`, `inventory`) qui correspondent aux modules du
[data-model.md](./data-model.md). La logique métier vit dans des modules `services/` testables
sans HTTP ; les vues restent minces. Le logo est copié depuis la racine du dépôt vers
`src/core/static/img/` (SVG recadré, PNG pour les e-mails).

## Ordre de livraison recommandé

Aligné sur les priorités de la spec pour permettre un pilote tôt :

1. **Socle** : projet, connexion Entra et rôles, `core` (calendrier, audit, paramètres), thème
   Armosa.
2. **P1** : US5 (annuaire Entra) puis US1 (tickets e-mail et manuels, cycle de vie, notes,
   temps, accusés) → **pilote possible** sur une boîte de test.
3. **P2** : US2 (affectation), US3 (délais, rappels), US4 (parc Intune + manuel + licences).
4. **P3** : US6 (base de résolution), US7 (prise en main à distance).
5. **Recette et bascule** : scénarios S1–S9, pilote parallèle, bascule de l'adresse support.

## Complexity Tracking

| Écart | Pourquoi nécessaire | Alternative plus simple écartée |
|---|---|---|
| Second processus (*worker*) en plus du serveur web | Relève mail chaque minute, synchros, rappels, alertes et purge doivent tourner hors requête HTTP et être repris après échec | Cron système : absent en conteneur PaaS, sans reprise ni file pour les e-mails ; tâches dans la requête : bloquantes et perdues en cas d'erreur |
| Stockage objet (Blob) en plus de PostgreSQL | Les conteneurs n'ont pas de disque persistant ; les pièces jointes (jusqu'à 25 Mo) alourdiraient sauvegardes et requêtes si stockées en base | Fichiers en base (`bytea`) : sauvegardes et restaurations lourdes ; disque local : perdu à chaque redéploiement |
| Tokens d'état (`danger`, `warning`, `success`, `info`) ajoutés hors du design system Armosa | L'ITSM doit signaler priorités, dépassements et échecs ; le design system n'a pas de couleurs d'état et limite `brand`/`accent` à 1–2 usages par écran | Utiliser `accent` bronze pour tous les états : contraire aux règles d'usage du design system et non distinguable entre états |
