# Contrat — Messagerie entrante et sortante

L'ITSM échange avec les demandeurs uniquement par e-mail (FR-014b), via une ou plusieurs
boîtes support Exchange Online (paramètre `support_mailboxes`).

## Référence de ticket

- Format : `T-` + numéro sur 5 chiffres minimum (`T-00042`, `T-123456`).
- Tout e-mail sortant lié à un ticket a un objet de la forme `[T-00042] <titre du ticket>`.
- Reconnaissance en entrée : expression `\[T-(\d{5,})\]` n'importe où dans l'objet.

## Entrant — règles de traitement (ordre d'évaluation)

| # | Condition | Résultat (`processing`) | Effets |
|---|---|---|---|
| 1 | `internet_message_id` déjà connu | — | ignoré silencieusement (idempotence) |
| 2 | expéditeur = une boîte support | `ignore_boucle` | déplacé dans « ITSM/Ignorés » |
| 3 | e-mail automatique : `Auto-Submitted` ≠ `no`, `X-Auto-Response-Suppress` présent, `Precedence` ∈ {bulk, junk, list}, `List-Id` présent, expéditeur `noreply`/`no-reply`/`mailer-daemon`/`postmaster` | `ignore_automatique` | déplacé dans « ITSM/Ignorés » ; aucun accusé |
| 4 | plus de 20 messages de cet expéditeur dans l'heure | `ignore_limite` | déplacé dans « ITSM/Ignorés » ; alerte administrateurs (une par heure) |
| 5 | référence `[T-n]` d'un ticket existant non fermé, ou `In-Reply-To`/`References` d'un message sortant connu, ou `conversation_id` connu | `note_ajoutee` | note externe entrante ; effets de statut selon la machine à états ([data-model.md](../data-model.md)) |
| 6 | comme 5 mais ticket `ferme` | `ticket_cree` | nouveau ticket, `related_ticket` = ancien ; accusé de réception |
| 7 | sinon | `ticket_cree` | nouveau ticket `channel = email` ; accusé de réception (voir ci-dessous) |

Pour un nouveau ticket : titre = objet (sans préfixes `RE:`, `TR:`, `FW:`), description = corps
texte, `description_html` = corps HTML assaini, pièces jointes conservées (≤ 25 Mo chacune ; au-
delà, la pièce est remplacée par une mention dans la description), demandeur = utilisateur
d'annuaire dont l'e-mail correspond (insensible à la casse), filiale = filiale du demandeur.

**Expéditeur inconnu** : ticket créé, `requester` vide, `requester_email` conservé, signalé
« non identifié » dans la liste. Accusé envoyé seulement si le domaine de l'expéditeur figure
dans `internal_domains`.

**Destinataires en copie** : ignorés dans cette version (le demandeur est l'expéditeur).

## Sortant — liste fermée des e-mails au demandeur (FR-038)

| `kind` | Déclencheur | Destinataire | Contenu minimal |
|---|---|---|---|
| `accuse_reception` | création d'un ticket (e-mail ou application) | demandeur | numéro, titre, rappel « répondez à cet e-mail pour compléter votre demande » |
| `note_externe` | note externe d'un technicien | demandeur | texte de la note, prénom du technicien, pièces jointes de la note |
| `rappel` | tâche de rappel (FR-034) | demandeur | rang du rappel (1/3…), dernière note externe, date de résolution automatique prévue |
| `resolution` | passage à `resolu` (technicien ou automatique) | demandeur | résolution ; « répondez sous 5 jours ouvrés si le problème persiste » |

Aucun autre événement (prise en compte, en attente, fermeture, réaffectation, changement de
priorité) n'envoie d'e-mail au demandeur. Un test automatisé vérifie que l'ensemble des
`kind` émis vers un demandeur est exactement celui-ci.

## Sortant — alertes aux techniciens

| `kind` | Déclencheur | Destinataire |
|---|---|---|
| `alerte_technicien` | dépassement d'échéance de prise en compte (une fois par ticket) | assigné, sinon `email` du groupe, sinon membres du groupe, sinon administrateurs |
| `alerte_technicien` | utilisateur désactivé ayant encore des équipements ou tickets ouverts | administrateurs |
| `alerte_technicien` | 3 échecs consécutifs d'une synchronisation ou relève | administrateurs |
| `alerte_technicien` | licences expirant sous 30 jours ou en dépassement (récapitulatif hebdomadaire) | administrateurs |

## Format des e-mails sortants

- Expéditeur : la boîte support qui a reçu le ticket (sinon la première boîte paramétrée).
- HTML aux styles en ligne conforme au design system Armosa (fond `canvas`, texte `ink`,
  titres EB Garamond avec repli Georgia, aucun bouton coloré `brand`) + partie texte.
- Logo : `src/core/static/img/logo.png` (824×113) en pièce jointe inline `cid:logo`, affiché à
  200 px de large, texte alternatif « Armosa Digital ».
- Les notes internes, le nom des groupes et les informations d'autres demandeurs ne figurent
  jamais dans un e-mail au demandeur.
- Langue : français.
