# ITSM Armosa

Outil interne de support informatique qui remplace Atera : tickets reçus par e-mail ou créés
par les techniciens, affectation automatique, délais en heures ouvrées, parc et licences,
annuaire synchronisé depuis Entra ID et Intune, base de résolution, RGPD.

- **Stack** : Python 3.12 (uv), Django 5.2, PostgreSQL 16, HTMX, Procrastinate (tâches),
  Microsoft Graph (boîtes support, Entra, Intune), connexion OIDC Entra.
- **Spécification** : [`specs/001-ticketing-gestion-parc/`](specs/001-ticketing-gestion-parc/)
  (spec, plan, modèle de données, routes, tâches, recette), menée avec Spec Kit.

## Lancer en local

Prérequis : Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL 16 (`docker compose up -d db`).

```bash
uv sync
cp .env.example .env              # Graph désactivé : connexion de démo, e-mails non envoyés
uv run python manage.py migrate
uv run python manage.py seed_demo # données fictives
uv run python manage.py runserver # http://localhost:8000
uv run python manage.py procrastinate worker   # second terminal : tâches planifiées
```

Simuler un e-mail entrant : `uv run python manage.py inject_email tests/fixtures/mail/nouvelle_demande.eml`.

## Vérifier

```bash
scripts/check.sh     # ruff, migrations, tests + couverture 95 %, pip-audit
uv run pytest -m e2e # parcours Playwright (uv run playwright install chromium au préalable)
```

## Déployer

- Recette : Render ([`render.yaml`](render.yaml), [`deploy/render.md`](deploy/render.md)),
  déployée depuis `main` ; les migrations passent au pré-déploiement.
- Production : Azure Container Apps ([`deploy/`](deploy/)).
- Configuration Entra et permissions Graph : [`docs/configuration-entra.md`](docs/configuration-entra.md).

## Façon de travailler

Une branche courte par demande depuis `main` (`feat/…`, `fix/…`, ou `NNN-…` pour une
fonctionnalité Spec Kit), test sur l'instance locale, puis fusion dans `main` par PR.
