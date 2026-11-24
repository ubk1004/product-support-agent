using './main.bicep'

param environment = 'tst'
param instance = '23'
param location = 'canadaeast'
param locationAbbreviation = 'cae'
param owner = 'platform-team'
param costCenter = 'deployment-test'
param deployFoundry = true
param useDocumentDbFreeTier = true
param documentDbLocation = 'canadacentral'
param deployApim = true
param apimPublisherEmail = 'deployment-test@example.com'
param apiTargetPort = 80
param webTargetPort = 80
param scheduleIngestion = false
