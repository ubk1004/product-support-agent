@description('Deployment environment used in resource names.')
@minLength(3)
@maxLength(3)
param environment string

@description('Two-digit resource instance number.')
@minLength(2)
@maxLength(2)
param instance string

@description('Azure region for API Management.')
param location string

@description('Mandatory resource tags.')
param tags object

@description('Classic API Management tier: Developer for dev and test (no SLA, one unit), Premium for production.')
@allowed([
  'Developer'
  'Premium'
])
param skuName string

@description('Premium scale units. Developer always uses one unit.')
@minValue(1)
@maxValue(10)
param skuCapacity int = 1

@description('Dedicated, undelegated API Management subnet resource ID.')
param subnetId string

@description('Standard public IPv4 address resource ID with a DNS label, used as the gateway VIP.')
param publicIpAddressId string

@description('Publisher contact e-mail shown on the developer portal.')
param publisherEmail string

@description('Publisher name shown on the developer portal.')
param publisherName string

@description('Application Insights resource ID for gateway request telemetry.')
param applicationInsightsId string

@description('Application Insights connection string, kept in a secret API Management named value.')
@secure()
param applicationInsightsConnectionString string

@description('Log Analytics workspace resource ID for gateway diagnostic logs.')
param logAnalyticsWorkspaceId string

@description('Internal HTTPS URL of the FastAPI Container App, reachable only inside the VNet.')
param backendUrl string

var apiManagementName = 'apim-psa-${environment}-cac-${instance}-${substring(uniqueString(resourceGroup().id), 0, 8)}'

// The gateway forwards only /chat and /catalog/coverage, caps body size, rate-limits per
// subscription key, and strips identifying response headers. It never logs bodies.
var apiPolicy = '''
<policies>
  <inbound>
    <base />
    <rate-limit-by-key calls="30" renewal-period="60" counter-key="@(context.Subscription.Id)" />
    <validate-content unspecified-content-type-action="prevent" max-size="49152" size-exceeded-action="prevent" errors-variable-name="requestBodyValidation" />
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
    <set-header name="X-Powered-By" exists-action="delete" />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
'''

var noBodies = {
  body: {
    bytes: 0
  }
}

resource apiManagement 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apiManagementName
  location: location
  tags: tags
  sku: {
    name: skuName
    capacity: skuName == 'Developer' ? 1 : skuCapacity
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    // External mode: the gateway is public, and backends are reached through the VNet.
    // The FastAPI Container App keeps internal-only ingress.
    virtualNetworkType: 'External'
    virtualNetworkConfiguration: {
      subnetResourceId: subnetId
    }
    publicIpAddressId: publicIpAddressId
    publicNetworkAccess: 'Enabled'
    customProperties: {
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls11': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls10': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls11': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Ssl30': 'False'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Protocols.Server.Http2': 'True'
    }
  }
}

resource appInsightsNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apiManagement
  name: 'appinsights-connection-string'
  properties: {
    displayName: 'appinsights-connection-string'
    value: applicationInsightsConnectionString
    secret: true
  }
}

resource appInsightsLogger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apiManagement
  name: 'appinsights'
  properties: {
    loggerType: 'applicationInsights'
    resourceId: applicationInsightsId
    credentials: {
      connectionString: '{{${appInsightsNamedValue.properties.displayName}}}'
    }
  }
}

// W3C trace context joins gateway spans to the API's OpenTelemetry traces. No bodies,
// headers, or client IP addresses are logged.
resource appInsightsDiagnostic 'Microsoft.ApiManagement/service/diagnostics@2024-05-01' = {
  parent: apiManagement
  name: 'applicationinsights'
  properties: {
    loggerId: appInsightsLogger.id
    alwaysLog: 'allErrors'
    httpCorrelationProtocol: 'W3C'
    verbosity: 'information'
    logClientIp: false
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    frontend: {
      request: noBodies
      response: noBodies
    }
    backend: {
      request: noBodies
      response: noBodies
    }
  }
}

resource productSupportApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apiManagement
  name: 'product-support'
  properties: {
    displayName: 'Product Support API'
    path: 'product-support'
    protocols: [
      'https'
    ]
    serviceUrl: backendUrl
    // Callers authenticate with an API Management subscription key. Entra ID user sign-in
    // (validate-jwt) is a production gate; see the production gap register.
    subscriptionRequired: true
    apiType: 'http'
  }
}

resource chatOperation 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: productSupportApi
  name: 'post-chat'
  properties: {
    displayName: 'Ask a question'
    method: 'POST'
    urlTemplate: '/chat'
  }
}

resource coverageOperation 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: productSupportApi
  name: 'get-coverage'
  properties: {
    displayName: 'Catalog coverage'
    method: 'GET'
    urlTemplate: '/catalog/coverage'
  }
}

resource productSupportApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: productSupportApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: apiPolicy
  }
}

resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'apim-to-log-analytics'
  scope: apiManagement
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output apiManagementName string = apiManagement.name
output gatewayUrl string = apiManagement.properties.gatewayUrl
output principalId string = apiManagement.identity.principalId
