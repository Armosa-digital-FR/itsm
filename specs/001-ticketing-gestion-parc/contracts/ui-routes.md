# Contrat — Écrans et routes de l'application

Application web rendue côté serveur ; les actions partielles sont des requêtes HTMX qui
renvoient un fragment HTML. Toutes les routes exigent une session OIDC valide ; sans rôle
`technicien` ou `administrateur` → **403**. Toute requête modifiante exige le jeton CSRF.

Légende des rôles : **T** = technicien (et administrateur), **A** = administrateur seul.

## Authentification

| Méthode | Route | Rôle | Comportement |
|---|---|---|---|
| GET | `/oidc/authenticate/` | public | redirection vers Entra ID |
| GET | `/oidc/callback/` | public | création/mise à jour du compte, rôles recopiés du jeton |
| POST | `/logout/` | connecté | fin de session |
| GET | `/healthz` | public | `200` si base joignable et dernière relève mail < 5 min, sinon `503` ; aucune donnée métier |

## Accueil

| Méthode | Route | Rôle | Exigences | Comportement |
|---|---|---|---|---|
| GET | `/` | T | FR-081 | tableau de bord par module (tickets : à traiter, en cours, non affectés, délais dépassés, mes tickets, résolus cette semaine, prochaines échéances) ; anonyme → `/connexion/` |
| GET | `/connexion/` | public | FR-083 | bouton Microsoft si l'application Entra est configurée ; lien de démonstration en mode développement uniquement |

## Tickets

| Méthode | Route | Rôle | Exigences | Comportement |
|---|---|---|---|---|
| GET | `/tickets/` | T | FR-073, FR-082, SC-006 | onglets `onglet` = `a_traiter` (défaut), `en_cours`, `traites`, `tous`, avec compteurs ; liste filtrable : priorité, entité, site, assigné (dont « moi », « non affecté »), groupe, filiale, catégorie, outil, dépassement, texte ; tri par échéance ; pagination 50 |
| GET | `/tickets/?view=dispatch` | T | FR-021 | tickets sans assigné ni groupe |
| GET | `/tickets/export.csv` | T | principe V | export CSV des tickets filtrés |
| GET | `/tickets/new/` | T | FR-014 | formulaire de création manuelle |
| POST | `/tickets/new/` | T | FR-014, FR-014a | crée le ticket (`channel = app`), envoie l'accusé, déclenche l'affectation si outil → redirige vers la fiche |
| GET | `/directory/search/?q=` | T | FR-014 | fragment : 10 utilisateurs actifs max par nom ou e-mail (≥ 2 caractères) |
| GET | `/tickets/<number>/` | T | US1 | fiche : en-tête, qualification, fil chronologique (notes, e-mails, événements), temps, équipements liés, suggestions de résolution (FR-042) ; marque la réponse comme lue |
| POST | `/tickets/<number>/qualify/` | T | FR-015 à FR-019 | met à jour type, catégorie, outil, priorité, filiale ; recalcul de l'échéance ; affectation auto |
| POST | `/tickets/<number>/status/` | T | FR-030, FR-032 | corps : `status`, `resolution` si `resolu` ; transition refusée → fragment d'erreur `422` |
| POST | `/tickets/<number>/take/` | T | FR-023 | l'utilisateur courant devient assigné ; passe en `pris_en_compte` si `cree` |
| POST | `/tickets/<number>/assign/` | T | FR-024 | corps : `assignee` et/ou `group` ; `assignment_mode = manuel` |
| POST | `/tickets/bulk-assign/` | T | cas limite | réaffectation en masse des tickets d'un technicien vers un autre/groupe |
| POST | `/tickets/<number>/notes/` | T | FR-031 | corps : `visibility`, `body`, pièces jointes ; note externe → e-mail au demandeur |
| POST | `/tickets/<number>/time/` | T | FR-035 | corps : `date`, `minutes`, `comment` |
| POST | `/time-entries/<id>/` · `/time-entries/<id>/delete/` | T (auteur) | FR-035a | correction ou suppression d'une saisie ; 403 pour un autre technicien |
| POST | `/tickets/<number>/equipment/` | T | FR-017 | lier / délier un équipement |
| POST | `/quick-create/<category|tool>/` | T | FR-019a | corps : `new_category_name`, `new_category_parent` ou `new_tool_name`, `new_tool_group` ; renvoie la liste à jour avec l'élément créé sélectionné (422 + erreurs sinon) ; audit `category.create` / `tool.create` |
| POST | `/tickets/<number>/remote/` | T | FR-050 | corps : `equipment`, `started_at`, `ended_at`, `comment` ; déclare une intervention TeamViewer réalisée, événement + audit (aucun lancement de TeamViewer) |
| GET | `/attachments/<id>/` | T | | téléchargement via URL signée courte durée du stockage |

## Suivi des délais et du temps (US3)

| Méthode | Route | Rôle | Comportement |
|---|---|---|---|
| GET | `/tracking/` | T | tickets non pris en compte triés par échéance (badges `warning` à < 25 % du délai restant, `danger` en dépassement) ; taux de respect par priorité sur la période (SC-003) ; temps passé par technicien sur la période |

## Base de résolution (US6)

| Méthode | Route | Rôle | Comportement |
|---|---|---|---|
| GET | `/knowledge/?q=&category=&tool=&subsidiary=&from=&to=` | T | recherche plein texte dans les tickets fermés et leurs résolutions, classée par pertinence (FR-041) |

## Parc

| Méthode | Route | Rôle | Exigences | Comportement |
|---|---|---|---|---|
| GET | `/inventory/` | T | FR-065 | liste filtrable : type, site, statut, filiale, utilisateur, source, « retiré d'Intune » |
| GET | `/inventory/export.csv` | T | principe V | export CSV |
| GET/POST | `/inventory/new/` | T | FR-060, FR-061 | création manuelle (type, site, statut obligatoires) |
| GET | `/inventory/<id>/` | T | US4-2 | fiche ; champs Intune affichés en lecture seule ; historique ; tickets liés ; identifiant TeamViewer avec bouton de copie |
| POST | `/inventory/<id>/` | T | FR-062 | modification des seuls champs ITSM ; champs Intune ignorés côté serveur |
| POST | `/inventory/<id>/assign/` | T | US4-4 | affectation / désaffectation à un utilisateur |
| GET | `/licences/` · `/licences/<id>/` | T | FR-064 | liste avec badges d'expiration et de dépassement ; fiche avec consommateurs |
| GET/POST | `/licences/new/` | T | FR-064 | création |
| GET | `/people/<entra_id>/` | T | FR-065 | fiche utilisateur : équipements, licences, tickets |

## Administration (admin Django thémée Armosa)

| Route | Rôle | Contenu |
|---|---|---|
| `/admin/` | A | catégories (3 niveaux), outils, compétences, groupes, types d'équipement, filiales, sites et correspondances Entra, paramètres, jours de fermeture, exécutions de synchronisation (FR-005), journal d'audit (lecture seule) |
| `/admin/gdpr/<entra_id>/export/` | A | export JSON de toutes les données d'une personne (audité) |
| `/admin/gdpr/<entra_id>/anonymize/` | A | anonymisation anticipée, confirmation obligatoire (auditée) |
| `/admin/sync/<kind>/run/` | A | déclenchement manuel d'une synchronisation |

Toute modification de compétences, de groupes, de paramètres et toute suppression via l'admin
crée une entrée d'audit (FR-071).

## Règles transverses

- Codes de réponse : `200` page ou fragment ; `302` après POST classique ; `403` rôle
  insuffisant ; `404` objet inconnu ; `422` validation métier refusée (fragment d'erreur
  lisible en français).
- Identité visuelle : toutes les pages utilisent la feuille de tokens Armosa ; un seul bouton
  principal (`action`) par écran ; aucune ombre hors menus flottants ; textes ≥ 14 px.
- Accessibilité : navigation clavier complète, anneau de focus `focus`, libellés de formulaire
  explicites, statut et priorité jamais portés par la seule couleur.
