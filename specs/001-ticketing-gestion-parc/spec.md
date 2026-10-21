# Feature Specification: Gestion de maintenance (ticketing) et gestion de parc

**Feature Branch**: `001-ticketing-gestion-parc`

**Created**: 2026-10-20

**Status**: Draft

**Input**: User description: "Gestion de maintenance : synchronisé avec Entra (utilisateurs) et
Intune (matériel) ; catégorisation des tickets sur 3 niveaux ; incident / demande ; outils ;
gestion de compétences par outil pour l'affectation automatique, groupes si pas de compétence
unique ; ticket affecté à un utilisateur et une filiale ; notes internes et externes avec
résolution ; priorité haute/normale/basse ; création de ticket par mail ; historisation avec base
de résolution ; mail automatique à la création ; statuts (créé, pris en compte, en attente de
réponse, en attente, résolu, fermé) ; rappel si pas de réponse ; temps passé par ticket ; délai
de prise en compte ; outil de prise en main à distance. Gestion de parc : parc existant sur
Intune ; ajout du matériel absent d'Intune (PC, écran, imprimante, télévision, caméra, licences,
téléphone) ; emplacement (site) et statut (stock ou en utilisation)."

## Clarifications

### Session 2026-10-21

- Q: Quel volume l'ITSM doit-il absorber ? → A: Petit : jusqu'à ~500 utilisateurs, ~1 000
  équipements, ~300 tickets/mois, 10 techniciens au plus.
- Q: Les techniciens voient-ils toutes les filiales ou seulement les leurs ? → A: Toutes les
  filiales (équipe IT unique, pas de cloisonnement).
- Q: Combien de temps conserver les données personnelles des tickets fermés ? → A: 3 ans après
  fermeture, puis anonymisation.
- Q: Quels changements de statut déclenchent un e-mail au demandeur ? → A: Aucun en dehors des
  e-mails déjà prévus (accusé de réception, notes externes, rappels, résolution).
- Q: Quels délais cibles de prise en compte par priorité ? → A: Haute 1 h, normale 4 h, basse
  1 jour ouvré (en heures ouvrées).
- Q: Un technicien peut-il créer un ticket depuis l'application ? → A: Oui, pour le compte d'un
  utilisateur choisi dans l'annuaire ; le ticket se comporte ensuite exactement comme un ticket
  créé par e-mail (accusé de réception, échanges par e-mail avec le demandeur).
- Q: Quelle identité visuelle pour l'interface ? → A: Celle d'Armosa Digital : logo fourni à la
  racine du dépôt et design system « Armosa ».
- Q: Quel outil de prise en main à distance, et comment l'intégrer ? → A: TeamViewer, utilisé en
  dehors de l'application (pas d'intégration ni de lancement depuis l'ITSM) ; l'ITSM conserve
  l'identifiant TeamViewer des appareils et la trace des interventions déclarées.

### Session 2026-10-21 (retours sur le MVP)

- Q: Comment appeler la filiale dans l'interface ? → A: « Entité » (même notion : attribut
  société d'Entra) ; chaque ticket porte aussi le site du demandeur.
- Q: Comment choisir le demandeur à la création manuelle ? → A: Recherche tant qu'aucun
  demandeur n'est choisi, puis une carte (nom, e-mail, entité, site) remplace le champ, avec
  « Changer ».
- Q: Faut-il une page d'accueil ? → A: Oui : accueil unique après connexion, avec une section
  de tableau de bord par module (tickets, parc…).
- Q: Comment séparer les tickets ? → A: Onglets « À traiter » (créés), « En cours » (pris en
  compte, en attente de réponse, en attente), « Traités » (résolus, fermés), « Tous ».
- Q: La connexion de démonstration est-elle acceptable ? → A: Uniquement en mode
  développement, jamais en production ; un bandeau signale ce mode.

### Session 2026-10-21 (temps passé par ticket)

- Q: Comment mesurer le temps passé sur un ticket ? → A: En plus de la saisie manuelle, un
  chronomètre Démarrer/Arrêter sur la fiche ; l'arrêt crée une saisie de temps corrigeable.
- Q: Quelle information afficher par ticket ? → A: « Mon temps » et le temps total, sur la
  fiche, dans la liste et dans l'export, et le délai de résolution (création → résolution, en
  heures ouvrées).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Créer et traiter un ticket de bout en bout (Priority: P1)

Un collaborateur envoie un e-mail à l'adresse du support. Un ticket est créé automatiquement,
rattaché au collaborateur (identifié via son adresse e-mail) et à sa filiale, et le collaborateur
reçoit un accusé de réception avec le numéro du ticket. Un technicien qualifie le ticket (type
incident ou demande, catégorie sur 3 niveaux, priorité), le prend en compte, échange avec le
demandeur via des notes externes, consigne ses constats dans des notes internes, saisit le temps
passé, puis le résout en renseignant une résolution. Le ticket est ensuite fermé.

**Why this priority**: c'est le cœur du service desk et la condition minimale pour pouvoir
basculer le support hors d'Atera.

**Independent Test**: envoyer un e-mail au support, vérifier la création du ticket et
l'accusé de réception, puis faire passer le ticket par tous les statuts jusqu'à « fermé » en
ajoutant notes, temps passé et résolution.

**Acceptance Scenarios**:

1. **Given** un collaborateur connu de l'annuaire, **When** il envoie un e-mail à l'adresse du
   support, **Then** un ticket au statut « créé » est généré avec l'objet comme titre, le corps
   comme description, les pièces jointes, le demandeur et sa filiale renseignés, et un e-mail
   d'accusé de réception contenant le numéro du ticket lui est envoyé.
2. **Given** un ticket ouvert, **When** le demandeur répond à un e-mail du ticket, **Then** sa
   réponse est ajoutée au ticket comme note externe et aucun nouveau ticket n'est créé.
3. **Given** un ticket « créé », **When** un technicien le passe à « pris en compte », **Then**
   la date de prise en compte est enregistrée et le délai de prise en compte est calculé.
4. **Given** un ticket en cours, **When** le technicien ajoute une note interne, **Then** la
   note est visible des seuls techniciens et n'est jamais envoyée au demandeur.
5. **Given** un ticket en cours, **When** le technicien ajoute une note externe, **Then** la
   note est envoyée par e-mail au demandeur et visible dans l'historique du ticket.
6. **Given** un ticket en cours, **When** le technicien le passe à « résolu », **Then** une
   résolution est obligatoire, elle est communiquée au demandeur et le ticket est fermé
   automatiquement après le délai de fermeture si le demandeur ne le rouvre pas.
7. **Given** un ticket « résolu », **When** le demandeur répond pour signaler que le problème
   persiste, **Then** le ticket revient au statut « pris en compte ».
8. **Given** un technicien connecté à l'application (par exemple après un appel téléphonique),
   **When** il crée un ticket en choisissant un utilisateur de l'annuaire comme demandeur,
   **Then** le ticket est rattaché à cet utilisateur et à sa filiale, le demandeur reçoit le même
   accusé de réception qu'un ticket créé par e-mail, et la suite des échanges (notes externes
   envoyées par e-mail, réponses du demandeur rattachées au ticket) est identique.
9. **Given** un ticket créé manuellement, **When** on consulte son historique, **Then** le
   canal de création (« application ») et le technicien créateur sont indiqués.

---

### User Story 2 - Affectation automatique selon les compétences (Priority: P2)

L'administrateur définit les outils (logiciels, matériels, services) et déclare, pour chaque
technicien, les outils sur lesquels il est compétent. Il crée des groupes de techniciens
lorsqu'aucune personne seule ne couvre un sujet. Lorsqu'un ticket est qualifié avec un outil,
il est affecté automatiquement au technicien compétent, ou au groupe compétent.

**Why this priority**: réduit le temps de dispatch manuel et le délai de prise en compte,
mais le service desk reste utilisable avec une affectation manuelle.

**Independent Test**: configurer deux outils avec des compétences différentes, créer un ticket
pour chacun et vérifier l'affectation obtenue.

**Acceptance Scenarios**:

1. **Given** un outil pour lequel un seul technicien est compétent, **When** un ticket est
   qualifié avec cet outil, **Then** le ticket est affecté à ce technicien.
2. **Given** un outil associé à un groupe de techniciens, **When** un ticket est qualifié avec
   cet outil, **Then** le ticket est affecté au groupe et visible de tous ses membres, jusqu'à
   ce que l'un d'eux le prenne en charge.
3. **Given** un outil sans aucune compétence déclarée, **When** un ticket est qualifié avec cet
   outil, **Then** le ticket reste non affecté et apparaît dans la file de dispatch.
4. **Given** un ticket affecté automatiquement, **When** un technicien le réaffecte
   manuellement, **Then** la réaffectation est enregistrée dans l'historique.

---

### User Story 3 - Suivi des délais, rappels et priorités (Priority: P2)

Les responsables suivent le délai de prise en compte des tickets selon leur priorité et le
temps passé. Les tickets en attente de réponse du demandeur font l'objet de rappels
automatiques.

**Why this priority**: garantit la qualité de service et évite les tickets oubliés, mais
dépend du cycle de vie de base (US1).

**Independent Test**: créer des tickets de chaque priorité, laisser expirer les délais et
vérifier les alertes ; passer un ticket « en attente de réponse » et vérifier les rappels.

**Acceptance Scenarios**:

1. **Given** un ticket de priorité haute non pris en compte, **When** son délai cible de prise
   en compte est dépassé, **Then** le ticket est signalé comme en dépassement et le technicien
   ou groupe affecté est alerté.
2. **Given** un ticket « en attente de réponse », **When** le demandeur n'a pas répondu après le
   délai de rappel, **Then** un e-mail de rappel lui est envoyé automatiquement.
3. **Given** un ticket ayant atteint le nombre maximal de rappels sans réponse, **When** le
   dernier délai expire, **Then** le ticket passe à « résolu » avec une résolution
   « sans réponse du demandeur », et le demandeur en est informé.
4. **Given** un ticket au statut « en attente » (dépendance externe), **When** le temps
   s'écoule, **Then** aucun rappel n'est envoyé au demandeur.
5. **Given** plusieurs saisies de temps sur un ticket, **When** on consulte le ticket, **Then**
   le temps total passé est affiché, ventilé par technicien.

---

### User Story 4 - Inventaire du parc synchronisé et complété (Priority: P2)

Le parc géré dans Intune est importé et tenu à jour automatiquement. Les techniciens ajoutent
manuellement le matériel et les licences absents d'Intune (nouveau PC, écran, imprimante,
télévision, caméra, licence, téléphone), avec leur site et leur statut (stock ou en utilisation),
et les rattachent éventuellement à un utilisateur.

**Why this priority**: remplace la partie inventaire d'Atera et alimente le contexte des
tickets ; indépendant du ticketing.

**Independent Test**: lancer une synchronisation et comparer le nombre d'appareils avec Intune ;
créer un écran en stock sur un site, puis l'affecter à un utilisateur.

**Acceptance Scenarios**:

1. **Given** des appareils gérés dans Intune, **When** la synchronisation s'exécute, **Then**
   chaque appareil existe dans le parc avec ses informations d'inventaire et son utilisateur
   principal, marqué comme provenant d'Intune.
2. **Given** un appareil synchronisé depuis Intune, **When** un technicien consulte sa fiche,
   **Then** les champs issus d'Intune sont en lecture seule, et les champs propres à l'ITSM
   (site, statut, commentaires) restent modifiables.
3. **Given** un équipement absent d'Intune, **When** un technicien le crée en choisissant son
   type, son site et son statut « stock », **Then** il apparaît dans l'inventaire du site.
4. **Given** un équipement en stock, **When** un technicien l'affecte à un utilisateur, **Then**
   son statut passe à « en utilisation » et l'historique conserve l'affectation.
5. **Given** un PC créé manuellement, **When** il est ensuite enrôlé dans Intune avec le même
   numéro de série, **Then** la synchronisation rapproche les deux fiches au lieu de créer un
   doublon.
6. **Given** une licence, **When** elle est créée, **Then** on peut renseigner son nombre de
   postes, sa date d'expiration et les utilisateurs ou appareils qui la consomment.

---

### User Story 5 - Annuaire utilisateurs synchronisé avec Entra (Priority: P1)

Les utilisateurs (nom, e-mail, filiale, site, service, responsable) sont importés depuis Entra et
tenus à jour, pour que tout ticket et tout équipement soit rattaché à une personne et une
filiale fiables.

**Why this priority**: prérequis à l'identification des demandeurs dans US1 et au rattachement
du matériel dans US4.

**Independent Test**: lancer la synchronisation et vérifier qu'un utilisateur créé, modifié puis
désactivé dans Entra est reflété dans l'ITSM.

**Acceptance Scenarios**:

1. **Given** un utilisateur présent dans Entra, **When** la synchronisation s'exécute, **Then**
   il existe dans l'ITSM avec sa filiale et ses attributs à jour.
2. **Given** un utilisateur désactivé dans Entra, **When** la synchronisation s'exécute, **Then**
   il est marqué inactif dans l'ITSM, ses tickets et équipements restent consultables, et les
   techniciens sont alertés des équipements encore affectés à cet utilisateur.

---

### User Story 6 - Base de résolution et historique (Priority: P3)

Tout l'historique d'un ticket (changements de statut, affectations, notes, temps, résolution)
est conservé. Les résolutions des tickets fermés forment une base consultable ; lorsqu'un
technicien traite un ticket, il retrouve les résolutions de tickets similaires (même catégorie,
même outil, mots-clés).

**Why this priority**: accélère la résolution et capitalise le savoir ; prépare les futures
fonctionnalités d'IA, mais n'est pas bloquant pour la bascule.

**Independent Test**: fermer plusieurs tickets d'une même catégorie avec résolution, puis
ouvrir un nouveau ticket de cette catégorie et vérifier les suggestions proposées.

**Acceptance Scenarios**:

1. **Given** un ticket, **When** on consulte son historique, **Then** chaque événement apparaît
   avec sa date, son auteur et l'ancienne et la nouvelle valeur.
2. **Given** des tickets fermés avec résolution, **When** un technicien recherche par mot-clé,
   catégorie ou outil, **Then** il obtient les tickets et résolutions correspondants.

---

### User Story 7 - Prise en main à distance avec TeamViewer (Priority: P3)

Les interventions à distance se font avec TeamViewer, en dehors de l'application. Depuis un
ticket ou la fiche d'un appareil, le technicien retrouve l'identifiant TeamViewer du poste
concerné, puis déclare dans le ticket l'intervention réalisée, qui reste ainsi tracée.

**Why this priority**: fonctionnalité très utilisée sous Atera, mais pouvant être assurée
temporairement par l'outil existant en dehors de l'ITSM.

**Independent Test**: renseigner l'identifiant TeamViewer d'un poste, l'afficher depuis un
ticket lié, déclarer une intervention et vérifier sa présence dans l'historique.

**Acceptance Scenarios**:

1. **Given** un ticket lié à un appareil dont l'identifiant TeamViewer est renseigné, **When**
   le technicien consulte le ticket, **Then** l'identifiant TeamViewer est affiché et copiable
   en un clic, sans avoir à ouvrir la fiche de l'appareil.
2. **Given** une intervention TeamViewer réalisée, **When** le technicien la déclare dans le
   ticket (appareil, début, fin), **Then** le ticket conserve la trace de l'intervention
   (technicien, appareil, date de début et de fin) et elle apparaît dans l'historique.
3. **Given** l'application, **When** on cherche à lancer TeamViewer depuis l'ITSM, **Then**
   aucun lancement n'est proposé : TeamViewer reste un outil externe.

---

### Edge Cases

- E-mail reçu d'un expéditeur inconnu de l'annuaire : le ticket est créé avec un demandeur
  « non identifié » et signalé pour qualification ; aucune donnée n'est rejetée.
- E-mails automatiques (réponses d'absence, notifications, boucles) : ils ne créent pas de
  ticket et ne déclenchent pas d'accusé de réception.
- Réponse à un ticket déjà fermé : un nouveau ticket est créé et lié au ticket fermé.
- Utilisateur appartenant à plusieurs filiales ou sans filiale renseignée dans Entra : la
  filiale peut être corrigée manuellement sur le ticket.
- Indisponibilité d'Entra ou d'Intune pendant une synchronisation : les données existantes sont
  conservées, l'échec est signalé aux administrateurs et la synchronisation suivante reprend.
- Appareil supprimé d'Intune : la fiche n'est pas supprimée ; elle est marquée « retiré
  d'Intune » pour décision d'un technicien.
- Ticket prioritaire arrivé en dehors des heures ouvrées : le délai de prise en compte est
  calculé sur les heures ouvrées.
- Technicien absent ou inactif détenant des tickets : ses tickets peuvent être réaffectés en
  masse.
- Membre d'un groupe qui quitte l'entreprise : il est retiré des groupes et compétences lors de
  la synchronisation Entra.

## Requirements *(mandatory)*

### Functional Requirements

**Synchronisations**

- **FR-001**: Le système DOIT importer et mettre à jour périodiquement (au moins une fois par
  heure) les utilisateurs depuis Entra : identité, e-mail, filiale, site, service, responsable,
  état actif/inactif.
- **FR-002**: Le système DOIT importer et mettre à jour périodiquement (au moins une fois par
  heure) les appareils gérés dans Intune avec leurs informations d'inventaire (nom, type,
  fabricant, modèle, numéro de série, système d'exploitation, utilisateur principal, dernière
  synchronisation).
- **FR-003**: Le système DOIT rapprocher les équipements créés manuellement des appareils Intune
  par numéro de série pour éviter les doublons.
- **FR-004**: Le système NE DOIT PAS modifier les données dans Entra ou Intune (synchronisation
  en lecture seule).
- **FR-005**: Les administrateurs DOIVENT pouvoir consulter l'état et l'historique des
  synchronisations, y compris les erreurs.

**Tickets : création et qualification**

- **FR-010**: Le système DOIT créer un ticket à partir de chaque e-mail reçu sur la ou les
  adresses du support, en conservant objet, corps et pièces jointes.
- **FR-011**: Le système DOIT identifier le demandeur à partir de l'adresse e-mail de
  l'expéditeur et renseigner automatiquement sa filiale.
- **FR-012**: Le système DOIT envoyer automatiquement un accusé de réception au demandeur à la
  création du ticket, contenant le numéro et le titre du ticket.
- **FR-013**: Le système DOIT rattacher au ticket existant toute réponse e-mail portant la
  référence de ce ticket.
- **FR-014**: Les techniciens DOIVENT pouvoir créer un ticket depuis l'application pour le
  compte d'un utilisateur choisi dans l'annuaire (recherche par nom ou e-mail). Le ticket est
  rattaché à cet utilisateur et à sa filiale, déclenche le même accusé de réception (FR-012) et
  les échanges ultérieurs passent par e-mail avec le demandeur exactement comme pour un ticket
  créé par e-mail (FR-013, FR-031). Le technicien peut saisir dès la création la description,
  le type, la catégorie, l'outil, la priorité et les équipements liés.
- **FR-014a**: Le système DOIT enregistrer le canal de création de chaque ticket (e-mail ou
  application) et, pour un ticket créé dans l'application, le technicien créateur.
- **FR-014b**: L'e-mail est le seul canal côté demandeur : aucun portail demandeur n'est prévu
  dans cette version.
- **FR-015**: Chaque ticket DOIT avoir un type : incident ou demande.
- **FR-016**: Chaque ticket DOIT pouvoir être classé dans une arborescence de catégories à
  3 niveaux (catégorie, sous-catégorie, sous-sous-catégorie), administrable.
- **FR-017**: Chaque ticket DOIT pouvoir être associé à un outil du référentiel d'outils et à un
  ou plusieurs équipements du parc.
- **FR-018**: Chaque ticket DOIT avoir une priorité parmi haute, normale et basse ; la priorité
  par défaut est normale.
- **FR-019**: Un ticket DOIT être rattaché à un demandeur et à une entité (filiale) pour pouvoir
  être pris en compte ; il porte aussi le site du demandeur, repris à la création et modifiable.
  Entité et site sont affichés dans la liste, la fiche, la création et l'export. Le demandeur peut rester vide uniquement pour un expéditeur non identifié (jusqu'à
  sa qualification) ou après anonymisation (FR-072).

**Tickets : affectation et compétences**

- **FR-020**: Les administrateurs DOIVENT pouvoir gérer le référentiel d'outils, les compétences
  des techniciens par outil et les groupes de techniciens.
- **FR-021**: À la qualification d'un ticket avec un outil, le système DOIT l'affecter
  automatiquement : au technicien compétent s'il est seul, au groupe associé à l'outil sinon ;
  s'il n'existe ni technicien ni groupe compétent, le ticket reste dans la file de dispatch.
- **FR-022**: Lorsqu'un outil a plusieurs techniciens compétents sans groupe défini, le système
  DOIT affecter le ticket au technicien compétent ayant le moins de tickets ouverts.
- **FR-023**: Un ticket affecté à un groupe DOIT pouvoir être pris en charge par n'importe quel
  membre du groupe, qui en devient le technicien responsable.
- **FR-024**: Les techniciens DOIVENT pouvoir réaffecter manuellement un ticket à un technicien
  ou à un groupe.

**Tickets : cycle de vie, notes et temps**

- **FR-030**: Le système DOIT gérer les statuts : créé, pris en compte, en attente de réponse,
  en attente, résolu, fermé, avec les transitions décrites dans les scénarios.
- **FR-031**: Les techniciens DOIVENT pouvoir ajouter des notes internes (visibles des seuls
  techniciens) et des notes externes (envoyées au demandeur par e-mail).
- **FR-032**: Le passage au statut « résolu » DOIT exiger la saisie d'une résolution, transmise
  au demandeur.
- **FR-033**: Un ticket résolu DOIT passer automatiquement à « fermé » après 5 jours ouvrés sans
  contestation du demandeur ; une réponse du demandeur avant ce délai le rouvre.
- **FR-034**: Le système DOIT envoyer un rappel au demandeur lorsqu'un ticket est « en attente
  de réponse » depuis 2 jours ouvrés, jusqu'à 3 rappels ; après le 3e rappel sans réponse, le
  ticket passe à « résolu » avec la résolution « sans réponse du demandeur ». Ces valeurs DOIVENT
  être paramétrables.
- **FR-035**: Les techniciens DOIVENT pouvoir saisir le temps passé sur un ticket (durée,
  date, technicien) ; le système DOIT afficher le cumul par ticket et par technicien.
- **FR-035a**: Chaque technicien DOIT pouvoir chronométrer son travail sur un ticket
  (Démarrer/Arrêter) : un seul chronomètre actif par technicien (en démarrer un autre arrête
  et enregistre le précédent), visible sur toutes les pages, arrêté automatiquement quand ce
  technicien résout le ticket. L'arrêt crée une saisie de temps (au moins 1 minute,
  24 heures au plus) que son auteur peut modifier ou supprimer, avec historique.
- **FR-035b**: Pour chaque ticket, le système DOIT afficher le temps que le technicien
  connecté y a passé et le temps total, sur la fiche, dans la liste (colonne dédiée, tous les
  onglets) et dans l'export CSV ; la liste DOIT pouvoir être filtrée sur les tickets où le
  technicien a saisi du temps.
- **FR-036**: Le système DOIT enregistrer la date de prise en compte et calculer le délai de
  prise en compte en heures ouvrées.
- **FR-037**: Le système DOIT permettre de définir un délai cible de prise en compte par
  priorité, en heures ouvrées : haute 1 h, normale 4 h, basse 1 jour ouvré (valeurs
  paramétrables), signaler les tickets en dépassement et alerter le technicien ou le groupe affecté.
- **FR-037a**: Le système DOIT calculer le délai de résolution de chaque ticket (de la création
  à la résolution, en heures ouvrées), le recalculer si le ticket est rouvert puis résolu à
  nouveau, et l'afficher sur la fiche, dans l'onglet « Traités », dans l'export et en moyenne
  par priorité sur la vue de suivi.
- **FR-038**: Le demandeur NE DOIT recevoir d'e-mail que dans les cas suivants : accusé de
  réception à la création, note externe, rappel en attente de réponse, résolution (y compris
  résolution automatique « sans réponse du demandeur »). Les autres changements de statut
  (pris en compte, en attente, fermé, réaffectation) ne déclenchent aucun e-mail au demandeur.

**Historique et base de résolution**

- **FR-040**: Le système DOIT historiser tous les événements d'un ticket (création, changements
  de statut, de priorité, de catégorie, d'affectation, notes, temps, résolution) avec date et
  auteur.
- **FR-041**: Les techniciens DOIVENT pouvoir rechercher dans les tickets fermés et leurs
  résolutions par mot-clé, catégorie, outil, filiale et période.
- **FR-042**: Lors du traitement d'un ticket, le système DOIT proposer les résolutions de
  tickets fermés de même catégorie ou même outil.

**Prise en main à distance**

- **FR-050**: Chaque équipement DOIT pouvoir porter un identifiant TeamViewer, affiché et
  copiable depuis sa fiche et depuis les tickets qui lui sont liés. Les techniciens DOIVENT
  pouvoir déclarer dans un ticket une intervention à distance réalisée (appareil, début, fin),
  tracée avec le technicien et l'horodatage. L'application ne lance ni ne pilote TeamViewer.

**Gestion de parc**

- **FR-060**: Les techniciens DOIVENT pouvoir créer manuellement des équipements des types :
  PC, écran, imprimante, télévision, caméra, téléphone, et des licences ; la liste des types
  DOIT être extensible par un administrateur.
- **FR-061**: Chaque équipement DOIT avoir un site (emplacement) et un statut « stock » ou
  « en utilisation », et peut être affecté à un utilisateur.
- **FR-062**: Les champs issus d'Intune DOIVENT être en lecture seule dans l'ITSM ; site, statut
  et informations complémentaires restent modifiables.
- **FR-063**: Le système DOIT historiser les changements d'affectation, de site et de statut de
  chaque équipement.
- **FR-064**: Chaque licence DOIT pouvoir porter un nombre de postes, une date d'expiration et
  la liste des utilisateurs ou appareils qui la consomment ; le système DOIT signaler les
  licences expirant dans les 30 jours et les dépassements de postes.
- **FR-065**: Les techniciens DOIVENT pouvoir filtrer l'inventaire par type, site, statut,
  filiale et utilisateur, et consulter depuis une fiche utilisateur ses équipements et tickets.

**Sécurité et données**

- **FR-070**: L'accès à l'application DOIT se faire par authentification unique avec les
  comptes de l'entreprise ; les rôles minimaux sont technicien et administrateur.
- **FR-071**: Les actions sensibles DOIVENT être journalisées dans un journal d'audit non
  modifiable : déclaration de prise en main à distance, changement de rôle d'un compte (constaté
  à la connexion, les rôles étant attribués dans Entra), modification des compétences, des
  groupes et des paramètres, toute suppression de données (y compris via l'administration),
  export et anonymisation de données personnelles.
- **FR-072**: Les tickets fermés et leurs données personnelles DOIVENT être conservés selon une
  durée de 3 ans après fermeture (paramétrable), puis anonymisés ; la base de résolution
  conserve les résolutions anonymisées.
- **FR-073**: Tout technicien DOIT avoir accès aux tickets et au parc de toutes les filiales ;
  aucun cloisonnement par filiale n'est appliqué. Les listes DOIVENT pouvoir être filtrées par
  filiale.
- **FR-074**: Données personnelles traitées (registre des traitements, constitution III) :
  finalité unique : support informatique interne et gestion du parc des collaborateurs de
  l'entreprise et de ses filiales. Le système NE DOIT traiter que les catégories suivantes, avec
  ces durées de conservation (paramétrables) :

  | Catégorie | Données | Conservation |
  |---|---|---|
  | Annuaire | nom, prénom, e-mail, identifiant Entra, filiale, site, service, fonction, responsable, état du compte | tant que le compte est actif dans Entra ; anonymisé 3 ans après sa désactivation s'il n'est plus référencé par un ticket ou un équipement non anonymisé |
  | Échanges de support | contenu des tickets, notes, e-mails reçus et envoyés, pièces jointes, adresse de l'expéditeur | 3 ans après la fermeture du ticket, puis anonymisation (FR-072) |
  | Parc | équipements et licences affectés à une personne, identifiant TeamViewer, historique d'affectation | tant que l'équipement est suivi ; l'affectation suit l'anonymisation de la personne |
  | Activité des techniciens | temps saisis, interventions déclarées, historique des actions | comme le ticket concerné |
  | Journal d'audit | auteur, action, objet, date, adresse IP | 3 ans, puis purge |

  Aucune autre donnée personnelle (notamment donnée sensible au sens du RGPD) n'est collectée
  volontairement ; les techniciens sont invités à n'en saisir aucune dans les résolutions.
- **FR-075**: Les administrateurs DOIVENT pouvoir, sans intervention en base de données,
  exporter (format JSON) toutes les données d'une personne et anonymiser ses données de façon
  anticipée sur demande ; chaque opération est journalisée (FR-071). La rectification se fait
  dans Entra, source de vérité de l'annuaire.
- **FR-076**: Les listes de tickets et d'équipements DOIVENT être exportables en CSV avec les
  filtres appliqués (format ouvert, constitution V).

**Accueil et navigation**

- **FR-081**: Après connexion, le technicien DOIT arriver sur une page d'accueil présentant une
  section de tableau de bord par module (tickets ; parc à partir de US4) : indicateurs clés
  cliquables vers les listes filtrées et listes courtes (prochaines échéances, mes tickets).
- **FR-082**: La liste des tickets DOIT séparer les tickets « À traiter » (créés), « En cours »
  (pris en compte, en attente de réponse, en attente) et « Traités » (résolus, fermés), avec un
  onglet « Tous » ; chaque onglet affiche son nombre de tickets selon les filtres actifs.
- **FR-083**: La connexion par compte de démonstration NE DOIT exister qu'en mode
  développement ; la configuration de production refuse de démarrer sans les paramètres de
  connexion Entra.

**Identité visuelle**

- **FR-080**: L'interface de l'application et les e-mails envoyés aux demandeurs DOIVENT
  reprendre l'identité visuelle d'Armosa Digital : le logo officiel et le design system
  « Armosa » (couleurs, typographies, espacements, composants et règles d'usage).

### Key Entities *(include if feature involves data)*

- **Utilisateur** : personne de l'annuaire Entra (demandeur ou technicien) ; filiale, site,
  service, responsable, état actif.
- **Entité** (filiale) : entité juridique/organisationnelle à laquelle sont rattachés
  utilisateurs, tickets et équipements ; libellée « Entité » dans l'interface.
- **Site** : emplacement physique où se trouve un équipement.
- **Technicien** : utilisateur ayant un rôle de support ; possède des compétences et appartient
  à des groupes.
- **Groupe de techniciens** : ensemble de techniciens couvrant un sujet commun.
- **Outil** : logiciel, matériel ou service supporté ; associé à des compétences et
  éventuellement à un groupe.
- **Compétence** : lien entre un technicien et un outil.
- **Catégorie** : nœud d'une arborescence à 3 niveaux.
- **Ticket** : canal de création (e-mail ou application), type, catégorie, outil, priorité,
  statut, demandeur, entité, site, affectation (technicien et/ou groupe), équipements liés, dates
  de création, de prise en compte, de résolution et de fermeture.
- **Note** : message interne ou externe rattaché à un ticket, avec auteur et date.
- **Saisie de temps** : durée passée par un technicien sur un ticket.
- **Événement d'historique** : trace datée d'un changement sur un ticket ou un équipement.
- **Résolution** : texte de résolution d'un ticket, indexé pour la recherche.
- **Équipement** : élément du parc (PC, écran, imprimante, télévision, caméra, téléphone…),
  source (Intune ou manuel), numéro de série, site, statut, utilisateur affecté.
- **Licence** : droit d'usage logiciel avec nombre de postes, expiration et consommateurs.
- **Session de prise en main** : intervention TeamViewer déclarée par un technicien sur un
  appareil (début, fin, ticket).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % des e-mails reçus par le support (hors e-mails automatiques) donnent lieu à
  un ticket ou à une note sur un ticket existant, et l'accusé de réception parvient au demandeur
  en moins de 5 minutes.
- **SC-002**: Au moins 80 % des tickets qualifiés avec un outil sont affectés automatiquement
  sans intervention manuelle.
- **SC-003**: Au moins 90 % des tickets de priorité haute sont pris en compte dans leur délai
  cible.
- **SC-004**: Après synchronisation, le nombre d'appareils et d'utilisateurs actifs dans l'ITSM
  correspond à 100 % à celui d'Entra et d'Intune, sans doublon.
- **SC-005**: Un technicien qualifie et prend en compte un nouveau ticket en moins de 2 minutes.
- **SC-006**: Un technicien retrouve un équipement ou un ticket historique en moins de
  30 secondes.
- **SC-007**: Aucun ticket ne reste « en attente de réponse » plus de 10 jours ouvrés sans
  action du système ou d'un technicien.
- **SC-008**: L'équipe support peut cesser d'utiliser Atera pour le ticketing et l'inventaire
  dans les 3 mois suivant la mise en service, sans interruption du support.
- **SC-009**: Le système supporte la volumétrie cible (500 utilisateurs, 1 000 équipements,
  300 tickets/mois, 10 techniciens simultanés) avec un affichage des listes et fiches en moins de
  2 secondes, et une capacité de croissance d'un facteur 2 sans dégradation perceptible.

## Assumptions

- Volumétrie cible : environ 500 utilisateurs, 1 000 équipements, 300 tickets par mois et
  10 techniciens au plus.
- Les demandeurs sont les collaborateurs de l'entreprise et de ses filiales présents dans
  Entra ; le ticket est « affecté à un utilisateur et une filiale » au sens du demandeur et de
  sa filiale, l'affectation au support se faisant vers un technicien ou un groupe.
- La prise en main à distance se fait avec TeamViewer, en dehors de l'application : l'ITSM
  stocke l'identifiant TeamViewer des appareils et la trace des interventions déclarées, sans
  intégration ni lancement. Une intégration pourra faire l'objet d'une fonctionnalité ultérieure.
- Aucun portail demandeur n'est prévu : les collaborateurs créent et suivent leurs tickets par
  e-mail uniquement (un portail pourra faire l'objet d'une fonctionnalité ultérieure).
- Les techniciens forment une équipe IT interne unique et transverse (voir FR-073).
- La filiale est déduite d'un attribut Entra (société ou département) ; les sites proviennent
  d'Entra ou sont administrés dans l'ITSM.
- La qualification (type, catégorie, outil, priorité) est faite par un technicien ;
  l'auto-qualification par IA est hors périmètre de cette fonctionnalité.
- Les heures ouvrées sont du lundi au vendredi, 9 h – 18 h, heure de Paris, hors jours fériés
  français ; elles sont paramétrables.
- L'identité visuelle s'appuie sur le design system « Armosa »
  (https://claude.ai/artifact/TpiLP3RLTVE5tpVmBcxAsG) et sur le logo Armosa Digital déposé à la
  racine du dépôt. Ce design system ne définit pas encore de couleurs d'état (erreur,
  avertissement, succès) ni de thème sombre : les couleurs d'état nécessaires à l'ITSM
  (priorités, dépassements de délai, échecs de synchronisation) seront à y ajouter lors de la
  conception de l'interface.
- Les e-mails sont envoyés et reçus via la messagerie de l'entreprise (une ou plusieurs boîtes
  support dédiées).
- La migration des tickets et de l'inventaire historiques d'Atera fera l'objet d'une
  fonctionnalité distincte.
- Le rapportage avancé (tableaux de bord, statistiques par filiale) est hors périmètre ;
  seules les vues de suivi des délais et du temps passé sont incluses.
- Les accès Entra et Intune en lecture sont accordés au projet par l'administrateur Microsoft
  365.
