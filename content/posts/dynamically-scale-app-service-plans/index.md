---
title: "Dynamically scale down AppService outside business hours to save 💰💰"
date: 2022-07-25T12:59:43Z
draft: false
tags: ["azure", "devops", "tutorial"]
---


The other day I was on a quest to lower a bit our Azure spending.

Im my current company we have several environment that we use for different purposes, Development, Test, Acceptance and so on.

All these environments have slightly different tiers for various services and I was wondering how to lower App Service Plan tier outside business hours.

App Services have some built-in, albeit limited, capabilities to scale but this only involves scaling out.

**Scaling out** is the process of adding additional instances of our application to adapt to an increasing load.
**Scaling up** is the process of running the application on a more performant hardware. 

Since there's no built-in support to scale up & down in App Services, I had to come up with a custom solution.

After a bit of research, I ended up creating an Azure automation account, two runbooks that execute on a schedule the scale down and scale up of our App Service Plan.

It turned out to be extremely simple to implement yet effective.

> Disclaimer: This is just one of the possible way to scale services up & down outside business hours, you can achieve the same with a scheduled github action or Azure DevOps pipeline than runs your IaC code with different Sku parameter values for example.

Here's what I've created:

- Azure automation account
- Azure Runbooks
- Azure automation schedule
- Azure automation account variables

---

## Azure automation account - [Docs](https://docs.microsoft.com/en-us/azure/automation/overview)
This is the go to resource to automate processes in Azure, where you define the runbooks, the schedule and the variables.

## Azure Runbooks - [Docs](https://docs.microsoft.com/en-us/azure/automation/overview)
This is where I defined what needs to happen when the schedule triggers the runbook and starts a job.
There are several [different types](https://docs.microsoft.com/en-us/azure/automation/automation-runbook-types) of runbooks, here I chose the powershell one.

## Azure automation schedule - [Docs](https://docs.microsoft.com/en-us/azure/automation/shared-resources/schedules)
This is where I defined when to execute our runbooks, I went with a weekly schedule to scale down resource in the evening and scale them back up early in the morning. 

## Azure automation account variables - [Docs](https://docs.microsoft.com/en-us/azure/automation/shared-resources/variables?tabs=azure-powershell)
This is where I defined few variables used by the runbook.
This step is optional since you can potentially hardcode everything in the runbook itself, but if you want to use the same runbook across different environment, you can define variables and read them in the runbook.
I defined few variables, one for the resource group name, one for the app service plan name and the desired scale down sku and the one the needs to be used during business hours.

> In order for the runbook to successfully change the App Service Plan, we also need to grant the identity - either managed identity or user assigned one - of the automation account enough grant on the App Service Plan. I went with managed identity.

## Putting it all together
After creating the variables, the schedules and the runbooks I linked the schedule to the runbook.
I created two schedules called scale-down and scale-up, two runbooks named the same way and linked the schedule to the runbook. You link a runbook to a schedule in the overview page of the runbook itself.

Last missing part is the code of the runbook itself, so here's the shortest possible version of it (of course you can make it smarter based on your needs) used to scale down, the scale up version is exactly the same but read a different variable for the sku.

{{< gist ilmax efaee63ccba80469ee51fd0a15565e73 >}} 

Till the next one!

