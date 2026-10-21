# Configurer la connexion Microsoft Entra

L'ITSM authentifie les techniciens par OpenID Connect avec Microsoft Entra ID (research R6).
Sans cette configuration, Entra répond `AADSTS900144: The request body must contain the
following parameter: 'client_id'` et la page de connexion affiche « La connexion Microsoft
n'est pas encore configurée ».

En développement, on peut s'en passer avec la connexion de démonstration (`seed_demo`, puis
« Connexion avec un compte de démonstration »), disponible uniquement en mode debug.

## 1. Inscrire l'application (centre d'administration Entra)

Rôle requis : *Administrateur d'application* ou *Administrateur général*.

1. **Identité › Applications › Inscriptions d'applications › Nouvelle inscription**
   - Nom : `ITSM (développement)` (une inscription distincte par environnement).
   - Types de comptes : *Comptes dans cet annuaire d'organisation uniquement*.
   - URI de redirection : plateforme **Web**, `http://localhost:8000/oidc/callback/`
     (en production : `https://<hôte>/oidc/callback/`).
2. Sur la page **Vue d'ensemble**, relever :
   - *ID d'application (client)* → `OIDC_RP_CLIENT_ID`
   - *ID de l'annuaire (locataire)* → `AZURE_TENANT_ID`
3. **Certificats et secrets › Nouveau secret client** → copier la *Valeur* (affichée une
   seule fois) → `OIDC_RP_CLIENT_SECRET`.

## 2. Créer les rôles d'application

**Rôles d'application › Créer un rôle d'application**, deux fois :

| Nom d'affichage | Types de membres | Valeur |
|---|---|---|
| Technicien | Utilisateurs/Groupes | `ITSM.Technicien` |
| Administrateur | Utilisateurs/Groupes | `ITSM.Administrateur` |

Les valeurs doivent être exactement celles-ci : l'ITSM lit la revendication `roles` du jeton.

## 3. Attribuer les rôles

1. **Identité › Applications › Applications d'entreprise › ITSM (développement)**.
2. **Propriétés** : *Affectation requise* = **Oui** (seules les personnes affectées peuvent se
   connecter).
3. **Utilisateurs et groupes › Ajouter un utilisateur/groupe** : choisir les techniciens (de
   préférence un groupe Entra « Support IT ») et le rôle *Technicien* ; idem pour les
   administrateurs avec le rôle *Administrateur*.

Un compte sans rôle est refusé (page « Accès refusé ») ; un changement de rôle prend effet à
la connexion suivante et est journalisé (`role.change`).

## 4. Renseigner `.env` et redémarrer

```dotenv
AZURE_TENANT_ID=<ID de l'annuaire>
OIDC_RP_CLIENT_ID=<ID d'application>
OIDC_RP_CLIENT_SECRET=<valeur du secret>
```

Le fichier `.env` n'est jamais commité. En production, ces valeurs viennent d'Azure Key
Vault et l'application refuse de démarrer si l'une d'elles manque.

## 5. Production

- Imposer l'authentification multifacteur par une **stratégie d'accès conditionnel** ciblant
  l'application (constitution II).
- Renouveler le secret avant son expiration (ou utiliser un certificat).
- La synchronisation Entra/Intune et la messagerie utilisent une autre identité (identité
  managée, permissions applicatives Graph) : voir `deploy/README.md`.
