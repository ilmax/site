---
title: "Azure WebJobs, Service Bus and Managed Identity: Lesson learned"
date: 2022-08-09T13:07:51Z
draft: false
tags: ["azure", "dotnet", "managed-identity"]
---

Today I was converting some Azure webjobs to connect to Azure Service Bus using managed service identity (MSI).

The application is a simple C# Azure WebJob built using the Azure WebJob SDK that subscribe to a topic and process incoming message writing to a database.

> These are the nuget packages used:
- Microsoft.Azure.WebJobs v 3.0.33
- Microsoft.Azure.WebJobs.Extensions.ServiceBus v 5.6.0
Please note that since Azure Functions are built on top of the WebJobs SDK, you may encounter the same issue there, I haven't verified though.

In order to grant the required permission, I created a security group and added the managed identity of the app service to the group, then I proceeded to grant this service group the [Azure Service Bus Data Owner](https://docs.microsoft.com/en-us/azure/role-based-access-control/built-in-roles#azure-service-bus-data-owner)

According to the description, this role should have full access to the whole Service Bus namespace, so imagine my surprise when I tried to run the application and got an error that looks like the following:

```
Unauthorized access. 'Listen' claim(s) are required to perform this operation. 
Resource: 'sb://{namespace-name}.servicebus.windows.net/{topic-name}/subscriptions/{service-name}'.
TrackingId:4e956a067b044b1089b5e327c0d08fd0_G9, SystemTracker:gateway7, Timestamp:2022-08-05T15:32:58 
```

After several trial and error, this is what I found:

1. If you assign the permission **Azure Service Bus Data Owner** to a group and the managed identity of the application is part of the group, it won't work, no matter which permission you grant ❌
2. If you assign the managed service identity the permission **Azure Service Bus Data Owner** it won't work ❌
3. If you assign the permission **Azure Service Bus Data Receiver** to a group and the managed identity of the application is part of the group, it will work ✅
4. If you assign the managed service identity the permission **Azure Service Bus Data Receiver**, it will work ✅

> Please note it may take up to 5 minutes for the permission changes to be applied, so you may still experience failures after applying them.

The only way to get it working was to assign the managed identity the **Azure Service Bus Data Receiver** role to either the service identity or the security group.

This seems either a bug in the Azure SDK or in the Service Bus itself, I'm not the only one that ran into this [issue](https://github.com/Azure/azure-sdk-for-net/issues/24289) and here you can find additional information.

Till the next time.
