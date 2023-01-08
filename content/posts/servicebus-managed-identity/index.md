---
title: "Using Managed Identity with Azure WebJobs and Service Bus"
date: 2022-05-24T10:01:30Z
draft: false
tags: ["azure", "terraform", "servicebus", "managedidentity"]
---

Managed Service Identity (or MSI for short) allows Azure resources to connect to Azure services that supports AD authentication (see the full list [here](https://docs.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/services-azure-active-directory-support)) without using secrets. 
This is extremely useful because handling secrets the proper way it's [far from easy](https://docs.microsoft.com/en-us/azure/cloud-adoption-framework/secure/best-practices/manage-secrets).

How MSI works is beyond the scope of the article and you can find more information [here](https://docs.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/managed-identities-status), but in a nutshell:

- You create a service principal object and an application in Azure AD to represents your service (this is done automatically when turning on managed identity) 
- You grant some permissions to access the downstream service it needs to communicate to
- You configure the authentication to the downstream service to be done via MSI

In my case, I have a WebJob that processes messages via a ServiceBus queue, so I granted the service principal a permission to read from the queue using the built in [Azure Service Bus Data Receiver](https://docs.microsoft.com/en-us/azure/role-based-access-control/built-in-roles#azure-service-bus-data-receiver) role.

The WebJob SDK supports connecting to the ServiceBus using MSI as described [here](https://docs.microsoft.com/en-us/dotnet/api/overview/azure/microsoft.azure.webjobs.extensions.servicebus-readme-pre#managed-identity-authentication) so I went ahead and configured the WebJob in the following way:

```json
"ServiceBusConnection__fullyQualifiedNamespace" : "<service_bus_namespace>.servicebus.windows.net"
"QueueName" : "test-queue"
```

The queue and the permission were defined in terraform as follows:

```terraform
// Define the queue
resource "azurerm_servicebus_queue" "msi-test-queue" {
  name                = "test-queue"
  namespace_id        = azurerm_servicebus_namespace.msi-test-sb.id
  enable_partitioning = true
}

// Grant the WebJob Azure Service Bus Data Receiver permissions
resource "azurerm_role_assignment" "consumer_service_bus_read" {
  scope                = azurerm_servicebus_queue.msi-test-queue.id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azapi_resource.consumer_container_app.identity.0.principal_id
  depends_on           = [azapi_resource.consumer_container_app]
}
```

The WebJob definition in C# is something like this:

```csharp
[FunctionName("Processor")]
public async Task ProcessEvent(
    [ServiceBusTrigger("%QueueName%", Connection = "ServiceBusConnection", IsSessionsEnabled = false)]
    ServiceBusReceivedMessage message, ServiceBusMessageActions messageActions)
{
    ....
}
```
Where the string **ServiceBusConnection** points to the name of the configuration value that contains the connection string to the Service Bus and the string **%QueueName%** point to the configuration value that contains the queue name.

>If you don't use the percent sign, the string will be the name of the queue and it will be hardcoded, adding the %% allows you to configure dynamically via a configuration lookup.

This unfortunately didn't work, the WebJob was throwing exception at startup complaining about permissions, the message was:

```
Unauthorized access. 'Listen' claim(s) are required to perform this operation
```

This was unexpected since the permission was there and I double checked it in the Azure portal.

The only way I was able to get this working was to grant **Azure Service Bus Data Receiver** permission on the whole service bus namespace.

```terraform
resource "azurerm_role_assignment" "consumer_service_bus_read" {
  scope                = azurerm_servicebus_namespace.msi-test-sb.id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azapi_resource.consumer_container_app.identity.0.principal_id
  depends_on           = [azapi_resource.consumer_container_app]
}
```

One caveat of this approach is that it grants more permissions than strictly required, but at least it got me unblocked.

If you're interested into the source code, you can find it [here](https://github.com/ilmax/container-apps-sample).

I hope you find this useful and if you have any questions/suggestions feel free to comment here below!