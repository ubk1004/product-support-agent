@description('Deployment environment used in resource names.')
@minLength(3)
@maxLength(3)
param environment string

@description('Two-digit resource instance number.')
@minLength(2)
@maxLength(2)
param instance string

@description('Azure region for the network resources.')
param location string

@description('Mandatory resource tags.')
param tags object

@description('Create the API Management subnet, NSG, and public IP.')
param deployApim bool = false

@description('DNS label for the API Management public IP; must be unique in the region.')
param apimDnsLabel string = 'apim-psa-${environment}-${instance}-${substring(uniqueString(resourceGroup().id), 0, 6)}'

var virtualNetworkName = 'vnet-psa-${environment}-cac-${instance}'
var containerAppsNsgName = 'nsg-aca-psa-${environment}-cac-${instance}'
var privateEndpointsNsgName = 'nsg-pe-psa-${environment}-cac-${instance}'
var apimNsgName = 'nsg-apim-psa-${environment}-cac-${instance}'
var apimSubnetPrefix = '10.20.3.0/27'

resource containerAppsNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: containerAppsNsgName
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowOutboundHttps'
        properties: {
          access: 'Allow'
          direction: 'Outbound'
          priority: 100
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRange: '443'
        }
      }
    ]
  }
}

resource privateEndpointsNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: privateEndpointsNsgName
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowVnetInbound'
        properties: {
          access: 'Allow'
          direction: 'Inbound'
          priority: 100
          protocol: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

// Minimum rules for classic API Management in external VNet mode:
// https://learn.microsoft.com/azure/api-management/api-management-using-with-vnet#configure-nsg-rules
resource apimNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = if (deployApim) {
  name: apimNsgName
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowClientHttpsInbound'
        properties: {
          access: 'Allow'
          direction: 'Inbound'
          priority: 100
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '443'
        }
      }
      {
        name: 'AllowApimManagementInbound'
        properties: {
          access: 'Allow'
          direction: 'Inbound'
          priority: 110
          protocol: 'Tcp'
          sourceAddressPrefix: 'ApiManagement'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '3443'
        }
      }
      {
        name: 'AllowAzureLoadBalancerInbound'
        properties: {
          access: 'Allow'
          direction: 'Inbound'
          priority: 120
          protocol: 'Tcp'
          sourceAddressPrefix: 'AzureLoadBalancer'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '6390'
        }
      }
      {
        name: 'AllowTrafficManagerInbound'
        properties: {
          access: 'Allow'
          direction: 'Inbound'
          priority: 130
          protocol: 'Tcp'
          sourceAddressPrefix: 'AzureTrafficManager'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '443'
        }
      }
      {
        name: 'AllowCertificateValidationOutbound'
        properties: {
          access: 'Allow'
          direction: 'Outbound'
          priority: 100
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRange: '80'
        }
      }
      {
        name: 'AllowStorageOutbound'
        properties: {
          access: 'Allow'
          direction: 'Outbound'
          priority: 110
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Storage'
          destinationPortRange: '443'
        }
      }
      {
        name: 'AllowSqlOutbound'
        properties: {
          access: 'Allow'
          direction: 'Outbound'
          priority: 120
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Sql'
          destinationPortRange: '1433'
        }
      }
      {
        name: 'AllowKeyVaultOutbound'
        properties: {
          access: 'Allow'
          direction: 'Outbound'
          priority: 130
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzureKeyVault'
          destinationPortRange: '443'
        }
      }
      {
        name: 'AllowAzureMonitorOutbound'
        properties: {
          access: 'Allow'
          direction: 'Outbound'
          priority: 140
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzureMonitor'
          destinationPortRanges: [
            '1886'
            '443'
          ]
        }
      }
    ]
  }
}

resource apimPublicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = if (deployApim) {
  name: 'pip-apim-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
    dnsSettings: {
      domainNameLabel: apimDnsLabel
    }
  }
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-nat-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource natGateway 'Microsoft.Network/natGateways@2024-05-01' = {
  name: 'nat-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    idleTimeoutInMinutes: 10
    publicIpAddresses: [
      {
        id: publicIp.id
      }
    ]
  }
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: virtualNetworkName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.20.0.0/16'
      ]
    }
  }
}

resource containerAppsSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: virtualNetwork
  name: 'snet-container-apps'
  properties: {
    addressPrefix: '10.20.0.0/23'
    delegations: [
      {
        name: 'containerAppsEnvironment'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
    networkSecurityGroup: {
      id: containerAppsNsg.id
    }
    natGateway: {
      id: natGateway.id
    }
  }
}

resource privateEndpointSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: virtualNetwork
  name: 'snet-private-endpoints'
  properties: {
    addressPrefix: '10.20.2.0/24'
    privateEndpointNetworkPolicies: 'Disabled'
    networkSecurityGroup: {
      id: privateEndpointsNsg.id
    }
  }
}

// Classic API Management injection: undelegated subnet with its own NSG. /27 leaves room for
// up to 12 Premium scale-out units.
resource apimSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = if (deployApim) {
  parent: virtualNetwork
  name: 'snet-apim'
  properties: {
    addressPrefix: apimSubnetPrefix
    networkSecurityGroup: {
      id: apimNsg.id
    }
  }
  dependsOn: [
    privateEndpointSubnet
  ]
}

output virtualNetworkId string = virtualNetwork.id
output virtualNetworkName string = virtualNetwork.name
output virtualNetworkAddressSpace string = '10.20.0.0/16'
output containerAppsSubnetId string = containerAppsSubnet.id
output containerAppsSubnetName string = containerAppsSubnet.name
output privateEndpointSubnetId string = privateEndpointSubnet.id
output privateEndpointSubnetName string = privateEndpointSubnet.name
output containerAppsNsgName string = containerAppsNsg.name
output privateEndpointsNsgName string = privateEndpointsNsg.name
output natGatewayName string = natGateway.name
output publicIpName string = publicIp.name
output apimSubnetId string = deployApim ? apimSubnet.id : ''
output apimPublicIpId string = deployApim ? apimPublicIp.id : ''
