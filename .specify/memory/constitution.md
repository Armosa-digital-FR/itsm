# Constitution ITSM

Plateforme ITSM interne destinée à remplacer Atera : gestion des tickets et des demandes de
service, gestion du parc informatique, et fonctionnalités d'IA intégrées.

## Core Principles

### I. Simplicité d'abord (YAGNI)

- Chaque fonctionnalité DOIT répondre à un besoin réel et présent, documenté dans une
  spécification (`/speckit-specify`). On n'ajoute rien « au cas où ».
- La solution la plus simple qui satisfait la spécification DOIT être retenue. Toute
  abstraction, couche, service ou dépendance supplémentaire DOIT être justifiée dans la section
  « Complexity Tracking » du plan, avec l'alternative plus simple écartée et la raison.
- Le périmètre fonctionnel d'Atera n'est PAS une cible à reproduire intégralement : seuls les
  usages effectivement pratiqués par l'équipe sont repris.
- Un monolithe modulaire est l'architecture par défaut ; tout découpage en services distincts
  DOIT être justifié par une contrainte mesurée (charge, isolation, sécurité).

**Justification** : un outil interne maintenu par une petite équipe doit rester compréhensible et
évolutif ; la complexité non justifiée est la première cause de dette et d'abandon.

### II. Sécurité par conception

- Toute fonctionnalité DOIT appliquer le moindre privilège : contrôle d'accès basé sur les rôles
  (au minimum technicien, administrateur, demandeur) vérifié côté serveur sur chaque requête.
- L'authentification DOIT s'appuyer sur un fournisseur d'identité de l'entreprise (SSO/OIDC) dès
  qu'il est disponible ; aucun mot de passe n'est stocké en clair, l'authentification
  multifacteur est obligatoire pour les comptes à privilèges.
- Les secrets (identifiants d'agents, clés API, accès distants au parc) NE DOIVENT JAMAIS être
  committés ni journalisés ; ils sont stockés dans un gestionnaire de secrets ou chiffrés.
- Les actions sensibles (modification de droits, accès à un poste, exécution de script sur le
  parc, suppression de données) DOIVENT être tracées dans un journal d'audit horodaté,
  non modifiable par les utilisateurs applicatifs.
- Toute entrée externe (formulaires, e-mails entrants, API, remontées d'agents) DOIT être
  validée ; les dépendances DOIVENT être analysées pour les vulnérabilités connues.

**Justification** : un ITSM concentre les accès à l'ensemble du parc ; sa compromission
équivaut à la compromission du système d'information.

### III. Protection des données & conformité RGPD

- Les données personnelles (demandeurs, utilisateurs du parc, contenus de tickets) DOIVENT être
  minimisées : seules les données nécessaires à la finalité documentée sont collectées.
- Chaque catégorie de données personnelles DOIT avoir une durée de conservation définie et une
  purge ou anonymisation automatisée à échéance.
- Le système DOIT permettre l'exercice des droits des personnes (accès, rectification,
  effacement, export) sans intervention en base de données.
- Les données DOIVENT être hébergées dans l'Union européenne, chiffrées en transit (TLS) et au
  repos.
- Toute nouvelle fonctionnalité traitant des données personnelles DOIT indiquer dans sa
  spécification les données traitées, la finalité et la durée de conservation, afin d'alimenter
  le registre des traitements.

**Justification** : l'entreprise est soumise au RGPD ; les tickets et l'inventaire du parc
contiennent des données personnelles et parfois sensibles.

### IV. IA assistive, traçable et maîtrisée

- L'IA est une aide : toute action à effet de bord (clôture, réaffectation, réponse envoyée au
  demandeur, exécution sur le parc) DOIT être validée par un humain, sauf règle d'automatisation
  explicitement approuvée et désactivable.
- Les contenus générés par l'IA DOIVENT être identifiés comme tels dans l'interface et
  l'historique des tickets.
- Aucune donnée personnelle ou secret NE DOIT être transmis à un fournisseur d'IA tiers sans
  pseudonymisation préalable ou sans contrat garantissant l'absence de réutilisation pour
  l'entraînement et un traitement conforme au RGPD.
- Chaque appel IA DOIT être journalisé (fonctionnalité, modèle, horodatage, utilisateur) et les
  fonctionnalités IA DOIVENT pouvoir être désactivées sans dégrader le fonctionnement de base
  de l'ITSM.

**Justification** : l'IA apporte de la valeur au triage et à la résolution, mais ses erreurs et
ses fuites de données ont un impact direct sur les utilisateurs et la conformité.

### V. Remplacement progressif d'Atera sans perte de service

- La migration DOIT être incrémentale : un parcours n'est basculé hors d'Atera que lorsque son
  équivalent est livré, testé et accepté par l'équipe support.
- Les données historiques nécessaires (tickets, clients/utilisateurs, actifs du parc) DOIVENT
  être importées par des scripts reproductibles et vérifiables (comptages et contrôles de
  cohérence), jamais par saisie manuelle.
- Chaque bascule DOIT disposer d'un plan de retour arrière documenté.
- Les modèles de données et exports DOIVENT rester dans des formats ouverts afin d'éviter un
  nouvel enfermement propriétaire.

**Justification** : le support ne peut pas s'interrompre pendant la transition ; un remplacement
« big bang » ferait courir un risque opérationnel inacceptable.

## Contraintes techniques et d'hébergement

- La pile technique n'est pas fixée par cette constitution : elle est choisie et justifiée
  fonctionnalité par fonctionnalité lors de `/speckit-plan`, en privilégiant la cohérence avec
  les choix déjà faits et des technologies maîtrisées par l'équipe.
- Toute nouvelle technologie (langage, framework, base de données, service managé) introduite
  dans le projet DOIT être justifiée au regard des principes I et II.
- L'hébergement et les sous-traitants (cloud, IA, e-mail) DOIVENT être situés dans l'UE ou
  couverts par des garanties RGPD adéquates.
- Les agents ou mécanismes de collecte installés sur le parc DOIVENT communiquer de manière
  authentifiée et chiffrée, et ne collecter que les informations d'inventaire nécessaires.

## Workflow de développement et contrôles qualité

- Toute fonctionnalité suit le cycle Spec Kit : spécification → (clarification) → plan → tâches
  → implémentation. Le « Constitution Check » du plan DOIT être passé avant l'implémentation.
- Toute modification passe par une revue de code avant fusion ; la revue vérifie explicitement
  le contrôle d'accès, la gestion des données personnelles et l'absence de secrets.
- Des tests automatisés DOIVENT couvrir les règles métier critiques : permissions, calcul et
  suivi des SLA, cycle de vie des tickets, scripts de migration depuis Atera, purge RGPD.
- Les fonctionnalités IA DOIVENT être évaluées sur un jeu d'exemples représentatif (pseudonymisé)
  avant mise en production.
- Les changements de schéma de données DOIVENT être versionnés et réversibles.

## Governance

- Cette constitution prévaut sur toute autre pratique du projet. En cas de conflit entre une
  spécification, un plan ou une habitude d'équipe et la constitution, la constitution s'applique
  ou est amendée.
- **Amendement** : toute modification est proposée via `/speckit-constitution`, documentée
  (motif, impact sur les spécifications et plans en cours) et validée par le responsable du
  projet avant fusion.
- **Versionnement** (SemVer) : MAJEUR pour la suppression ou redéfinition incompatible d'un
  principe ; MINEUR pour l'ajout d'un principe ou d'une section, ou un élargissement significatif ;
  CORRECTIF pour les clarifications et corrections de forme.
- **Conformité** : chaque plan (`/speckit-plan`) et chaque revue de code vérifient le respect des
  principes ; toute dérogation DOIT être consignée et justifiée dans « Complexity Tracking ».
  Une revue de la constitution est menée au minimum à chaque jalon majeur de la migration
  depuis Atera.

**Version**: 1.0.0 | **Ratified**: 2026-10-20 | **Last Amended**: 2026-10-20
