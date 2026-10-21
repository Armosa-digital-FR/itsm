# Quickstart — validation de bout en bout

**Feature** : `001-ticketing-gestion-parc` | **Plan** : [plan.md](./plan.md)

Guide pour lancer l'ITSM en local et prouver que chaque user story fonctionne. Les détails
des écrans, e-mails, appels Graph et tâches sont dans [contracts/](./contracts/) ; les règles
de données dans [data-model.md](./data-model.md).

## Prérequis

- Python 3.12, [`uv`](https://docs.astral.sh/uv/), Docker (PostgreSQL 16 local).
- Pour la recette « réelle » : un tenant Microsoft 365 de test (ou le tenant de production
  avec des comptes de test), une boîte support de test, l'application Entra « ITSM » et les
  permissions décrites dans [contracts/graph-integration.md](./contracts/graph-integration.md).

## Mise en route locale

```bash
uv sync                                   # dépendances verrouillées
docker compose up -d db                   # PostgreSQL 16
cp .env.example .env                      # ITSM_GRAPH_ENABLED=false par défaut
uv run python manage.py migrate
uv run python manage.py seed_demo         # filiales, sites, utilisateurs, catégories, outils, équipements fictifs
uv run python manage.py runserver         # interface : http://localhost:8000
uv run procrastinate --app=itsm.worker.app worker   # second terminal : tâches planifiées
```

Avec `ITSM_GRAPH_ENABLED=false` : la connexion se fait par un compte local de développement
(`DEV_LOGIN`, désactivé hors `DEBUG`), les e-mails sortants sont enregistrés (visibles dans
l'admin, `EmailMessage`) sans être envoyés, et un e-mail entrant se simule avec :

```bash
uv run python manage.py inject_email tests/fixtures/mail/nouvelle_demande.eml
```

## Tests automatisés

```bash
uv run pytest                       # unitaires + intégration (Graph simulé par respx, horloge figée)
uv run pytest -m e2e                # 3 parcours Playwright
uv run ruff check . && uv run ruff format --check .
uv run pip-audit                    # vulnérabilités des dépendances
```

Résultat attendu : tous les tests passent ; la couverture des modules critiques (`business_time`,
machine à états, affectation, rappels, rapprochement Intune, analyse des e-mails, RGPD,
permissions) est d'au moins 90 %.

## Scénarios de validation

Chaque scénario correspond à une user story de la [spec](./spec.md). En local, utiliser
`inject_email` et l'horloge (`manage.py run_job <tâche>` pour exécuter une tâche à la demande) ;
en recette, utiliser la vraie boîte support.

### S1 — Ticket par e-mail jusqu'à la fermeture (US1, P1)

1. Injecter `nouvelle_demande.eml` (expéditeur connu de l'annuaire).
   **Attendu** : ticket `T-00001` en « créé », demandeur et filiale renseignés, pièce jointe
   présente ; un `EmailMessage` `accuse_reception` vers le demandeur, objet `[T-00001] …`.
2. Qualifier (type, catégorie à 3 niveaux, priorité haute) puis « Prendre en compte ».
   **Attendu** : `acknowledged_at` et délai en minutes ouvrées affichés ; aucun e-mail au demandeur.
3. Ajouter une note interne, puis une note externe.
   **Attendu** : seul un e-mail `note_externe` est émis.
4. Injecter `reponse_demandeur.eml` (objet contenant `[T-00001]`).
   **Attendu** : note entrante ajoutée au même ticket, pas de nouveau ticket.
5. Saisir 30 min de temps, résoudre avec une résolution.
   **Attendu** : e-mail `resolution` ; résoudre sans résolution est refusé (422).
6. `run_job helpdesk.auto_close` avec l'horloge avancée de 5 jours ouvrés.
   **Attendu** : statut « fermé ».

### S2 — Création manuelle par un technicien (US1, scénarios 8–9)

1. « Nouveau ticket », rechercher un utilisateur par nom, saisir titre et description.
   **Attendu** : ticket `channel = app`, technicien créateur dans l'historique, accusé de
   réception émis comme en S1 ; une réponse e-mail du demandeur se rattache au ticket.

### S3 — Affectation automatique (US2, P2)

Données : outil A avec un seul technicien compétent ; outil B avec un groupe ; outil C sans
compétence.
**Attendu** : ticket qualifié avec A → assigné au technicien ; B → affecté au groupe, visible
de tous ses membres, « Prendre » par un membre le rend assigné ; C → file de dispatch ;
une réaffectation manuelle apparaît dans l'historique et bloque toute ré-affectation automatique.

### S4 — Délais et rappels (US3, P2)

1. Ticket haute priorité créé un vendredi à 17 h 30 ; avancer l'horloge au lundi 9 h 31.
   **Attendu** : échéance lundi 9 h 30 (heures ouvrées) ; `check_ack_deadlines` le marque en
   dépassement et envoie **une** alerte au technicien.
2. Ticket en « en attente de réponse » ; avancer de 2, 4 puis 6 jours ouvrés avec
   `send_reminders`.
   **Attendu** : 3 rappels ; 2 jours ouvrés plus tard, statut « résolu », résolution
   « sans réponse du demandeur », e-mail `resolution`.
3. Ticket « en attente » : aucun rappel quel que soit le délai.

### S5 — Parc (US4, P2)

1. Recette : `run_job inventory.sync_intune`.
   **Attendu** : nombre d'équipements source Intune = nombre d'appareils Intune (SC-004) ;
   champs Intune en lecture seule sur la fiche.
2. Créer un écran en « stock » sur un site, l'affecter à un utilisateur.
   **Attendu** : statut « en utilisation », événement d'affectation dans l'historique.
3. Créer un PC manuel avec le numéro de série d'un appareil Intune, relancer la synchro.
   **Attendu** : une seule fiche, devenue source Intune, historique conservé.
4. Créer une licence 2 postes expirant dans 20 jours, l'affecter à 3 utilisateurs.
   **Attendu** : badges « expire bientôt » et « dépassement ».

### S6 — Annuaire Entra (US5, P1)

Recette : créer, modifier puis désactiver un utilisateur de test dans Entra, lancer
`directory.sync_entra` après chaque étape.
**Attendu** : création, mise à jour de la filiale, passage inactif ; ses tickets et équipements
restent consultables ; alerte aux administrateurs s'il a encore un équipement affecté.

### S7 — Base de résolution (US6, P3)

Fermer 3 tickets « Imprimante » avec résolutions, ouvrir un nouveau ticket de même catégorie.
**Attendu** : les 3 résolutions proposées ; la recherche « imprimante bourrage » (sans accent
ni casse exacte) les trouve.

### S8 — Prise en main à distance (US7, P3)

Renseigner l'identifiant TeamViewer d'un PC, le lier à un ticket, puis déclarer une intervention
(début, fin) depuis le ticket.
**Attendu** : l'identifiant TeamViewer est affiché et copiable sur le ticket ; aucun bouton de
lancement ; intervention visible dans l'historique (technicien, appareil, début, fin) et entrée
d'audit `remote_session.declare`.

### S9 — Sécurité et RGPD

1. Utilisateur sans rôle ITSM : toutes les pages → 403.
2. Technicien sans rôle administrateur : `/admin/` → 403.
3. Avancer l'horloge de 3 ans après fermeture, `run_job core.gdpr_retention`.
   **Attendu** : demandeur « anonymisé », notes et pièces jointes supprimées, résolution
   conservée avec e-mails et téléphones masqués.
4. Tentative de modification d'une `AuditEntry` en base → refusée par la base.

## Critères de sortie de la recette

- S1 à S9 passent en recette sur le tenant de test.
- Pilote de 2 semaines en parallèle d'Atera sur une boîte support dédiée ; bascule de
  l'adresse support publique seulement après acceptation de l'équipe support ; procédure de
  retour arrière (rétablir la redirection vers Atera) testée une fois (principe V).
