// Infrastructure Azure de l'ITSM (research R5) — région France Central.
//
// Une image, deux Container Apps (web + worker Procrastinate), un job de migration,
// PostgreSQL Flexible Server 16, Blob Storage (pièces jointes), Key Vault (secrets),
// Container Registry, Log Analytics (journaux JSON), identité managée unique.
//
// Déploiement : voir deploy/README.md.

targetScope = 'resourceGroup'

@description('Préfixe des ressources (minuscules, 3 à 11 caractères).')
@minLength(3)
@maxLength(11)
param prefix string = 'itsm'

param location string = 'francecentral'

@description('Image de l\'application, ex. itsmacr.azurecr.io/itsm:2026.10.21')
param image string

@description('Nom d\'hôte public de l\'ITSM (domaine personnalisé ou FQDN Container Apps).')
param hostName string

@description('Locataire Entra (connexion des techniciens et Graph).')
param tenantId string = subscription().tenantId

@description('ID d\'application de l\'inscription OIDC « ITSM » (docs/configuration-entra.md).')
param oidcClientId string

@description('Administrateur PostgreSQL (le mot de passe est stocké dans Key Vault).')
param postgresAdminLogin string = 'itsmadmin'

@secure()
param postgresAdminPassword string

@secure()
@description('Secret client de l\'inscription OIDC.')
param oidcClientSecret string

@secure()
@description('Clé secrète Django (50 caractères aléatoires).')
param djangoSecretKey string

var suffix = uniqueString(resourceGroup().id)
var names = {
  identity: '${prefix}-id'
  logs: '${prefix}-logs'
  registry: '${prefix}acr${suffix}'
  vault: '${prefix}-kv-${take(suffix, 8)}'
  storage: '${prefix}st${take(suffix, 10)}'
  postgres: '${prefix}-pg-${take(suffix, 8)}'
  environment: '${prefix}-env'
  web: '${prefix}-web'
  worker: '${prefix}-worker'
  migrate: '${prefix}-migrate'
}

// Rôles intégrés Azure.
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: names.identity
  location: location
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.logs
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 90
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: names.registry
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, roles.acrPull)
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

// --- Pièces jointes : Blob Storage, accès par identité managée uniquement ---------

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: names.storage
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_ZRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    supportsHttpsTrafficOnly: true
    encryption: {
      services: { blob: { enabled: true } }
      keySource: 'Microsoft.Storage'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 14 }
  }
}

resource attachments 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'attachments'
  properties: { publicAccess: 'None' }
}

resource blobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, roles.blobContributor)
  scope: storage
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobContributor)
  }
}

// --- PostgreSQL 16 (sauvegardes automatiques, restauration à un instant donné) ----

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2023-12-01-preview' = {
  name: names.postgres
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32, autoGrow: 'Enabled' }
    backup: { backupRetentionDays: 14, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-12-01-preview' = {
  parent: postgres
  name: 'itsm'
  properties: { charset: 'UTF8', collation: 'fr_FR.utf8' }
}

// Extensions requises par les migrations (pg_trgm, unaccent).
resource extensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2023-12-01-preview' = {
  parent: postgres
  name: 'azure.extensions'
  properties: { value: 'PG_TRGM,UNACCENT', source: 'user-override' }
}

// Accès réservé aux services Azure ; passer en réseau privé (VNet) pour la production
// durable (voir README).
resource allowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-12-01-preview' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

// --- Secrets ------------------------------------------------------------------------

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: names.vault
  location: location
  properties: {
    tenantId: tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
  }
}

resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, roles.keyVaultSecretsUser)
  scope: vault
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

var databaseUrl = 'postgres://${postgresAdminLogin}:${uriComponent(postgresAdminPassword)}@${postgres.properties.fullyQualifiedDomainName}:5432/itsm?sslmode=require'

resource secretDatabase 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: databaseUrl }
}

resource secretDjango 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'django-secret-key'
  properties: { value: djangoSecretKey }
}

resource secretOidc 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'oidc-client-secret'
  properties: { value: oidcClientSecret }
}

// --- Container Apps -------------------------------------------------------------------

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: names.environment
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var secrets = [
  { name: 'database-url', keyVaultUrl: secretDatabase.properties.secretUri, identity: identity.id }
  { name: 'django-secret-key', keyVaultUrl: secretDjango.properties.secretUri, identity: identity.id }
  { name: 'oidc-client-secret', keyVaultUrl: secretOidc.properties.secretUri, identity: identity.id }
]

var env = [
  { name: 'DJANGO_SETTINGS_MODULE', value: 'itsm.settings.prod' }
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'DJANGO_SECRET_KEY', secretRef: 'django-secret-key' }
  { name: 'OIDC_RP_CLIENT_SECRET', secretRef: 'oidc-client-secret' }
  { name: 'OIDC_RP_CLIENT_ID', value: oidcClientId }
  { name: 'AZURE_TENANT_ID', value: tenantId }
  { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
  { name: 'ITSM_USE_MANAGED_IDENTITY', value: 'true' }
  { name: 'ITSM_GRAPH_ENABLED', value: 'true' }
  { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: storage.name }
  { name: 'AZURE_STORAGE_CONTAINER', value: 'attachments' }
  { name: 'ALLOWED_HOSTS', value: hostName }
  { name: 'CSRF_TRUSTED_ORIGINS', value: 'https://${hostName}' }
  { name: 'ITSM_BASE_URL', value: 'https://${hostName}' }
]

var identityConfig = {
  type: 'UserAssigned'
  userAssignedIdentities: { '${identity.id}': {} }
}

var registries = [ { server: registry.properties.loginServer, identity: identity.id } ]

resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: names.web
  location: location
  identity: identityConfig
  dependsOn: [ acrPull, secretsUser, blobContributor ]
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      secrets: secrets
      registries: registries
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: image
          env: env
          resources: { cpu: json('0.5'), memory: '1Gi' }
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8000, httpHeaders: [
                { name: 'X-Forwarded-Proto', value: 'https' }
                { name: 'Host', value: hostName }
              ] }
              periodSeconds: 60
              failureThreshold: 5
            }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
}

resource worker 'Microsoft.App/containerApps@2024-03-01' = {
  name: names.worker
  location: location
  identity: identityConfig
  dependsOn: [ acrPull, secretsUser, blobContributor ]
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      secrets: secrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: image
          command: [ 'python', 'manage.py', 'procrastinate', 'worker' ]
          env: env
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      // Un seul worker : les tâches périodiques sont de toute façon verrouillées.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

resource migrate 'Microsoft.App/jobs@2024-03-01' = {
  name: names.migrate
  location: location
  identity: identityConfig
  dependsOn: [ acrPull, secretsUser ]
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 900
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      secrets: secrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: image
          command: [ 'python', 'manage.py', 'migrate', '--noinput' ]
          env: env
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
    }
  }
}

output webFqdn string = web.properties.configuration.ingress.fqdn
output registryServer string = registry.properties.loginServer
output managedIdentityPrincipalId string = identity.properties.principalId
output managedIdentityClientId string = identity.properties.clientId
output keyVaultName string = vault.name
