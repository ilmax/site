---
title: "My experience on importing hundreds of existing Azure resources in terraform"
date: 2023-01-08T14:44:21Z
draft: true
tags: ["azure", "terraform", "devops"]
---

In my current company, we have a discrete number of Azure resources for each evnrionemnt (DEV, TEST, ecc).

Before digging into what and how, let me briefly give you a quick description of what's there.

Me and my fellow team members are building software for our company, we have aroun 50 indipendent services that requires some specific Azure resources (imagine a Sql database or a Storage container) and on top of that we have all the service agnostic infrastructure..

All these resources are created/update by various means and forms, some use ARM templates, some use PowerShell scripts, some Azure cli scripts and so on.

We have a share repository that contains all of these scripts and, project by project we reference what we need in the deployment pipeline.

This works ok, but it has several problems:

1. We use different technologies to setup infra and that makes it harder for newcomers to get up to speed
2. Deployments take longer than they could
3. You don't have a preview of what's going to happen when the deployment runs
4. Re-applying the code may not fix [configuration drift](https://wiki.gccollab.ca/index.php?title=Technology_Trends/Infrastructure_as_Code&mobileaction=toggle_view_desktop#Configuration_Drift) especially the PowerShell/az cli scripts
5. Possibly more

Hence we decided to move to terraform since it can address all the point above and, according to GitHub octoverse 2022, HCL was the fastest growing language (more info [here](https://octoverse.github.com/2022/top-programming-languages))

# The challenges

 As you may know, if a resource has been created outside terraform, it needs to be imported in order to be managed with terraform in the future.
 Importing resources is not difficult, on the provider documentation at the bottom of the page you can find the command to execute to import a given resource.

 My problem was that I had around 160 global resources, multiplied by all the various environments + between 5-10 resource service dendent multiplied by the number of services ~50 multiplied by the number of environments.

 As you can imagine this adds up very quickly, especially because it's a bit of a tedious work since, in order to import a resourvce, you need to define it first, on top of that you need to come up with the final module organization since you have to pass the resource identifier for terraform to the import command.
 
 At first this seemed like an herculeous effort so I started looking elsewhere.

 ## Aztfy
[Aztfy](https://github.com/Azure/aztfy) is a tool developed by Microsoft that allows you to bulk import resources, it has some configuration so you can specify what to import, the names to import and so on.
The problem I had with this tool is twofold:

1. It doesn't generate reproducible terraform configurations
2. It doesn't generate terraform idiomatic code

Let me expand on those two:

Not generating reproducible configurations means that after an import, when you run terraform plan, you may still have changes that you need to fix manually or worse, fail due to same validation problems. 
These limitation are clearly documented on the project README and I could live with them.

Not generating idiomatic code is a bit more annoying to me, since it requires to manually change most of the imported code to make use of variables or reference a parent resource.
This means that pretty much all the code that aztfy will output, needs to be adjusted/modified and if you move the resource around in a different module, then you either start moving resources in the state as well, or you need to import it again.

Given the following downsides I decided to use it only marginally but start writing my configuration from scratch.

I think an example may be better to understand what's the output of the code

# How I did it

Before starting I came up with some principles to use a guidelines when writing my HCL modules, those are:

1. One module for every different resource type used
2. Every module that needs to resources defined in other modules, read these resources with a data source
3. All the modules input are defined in a file called variables.tf
4. All the permission related stuff (RBAC, AAD group membership) will go in a file called permission.tf
5. All the networking configuration (Firewall rules, VNet, Private endpoints and so on) will go in a file called networking.tf
6. All the modules outputs will go in a file called output.tf
7. These lower level modules, will be invoked by a higher level module where most of the naming logic will be
8. Lower level modules can only be called by higher level modules
9. Several higher level modules will be created:
    - Environment specific with all the global resources 
    - Several service specific ones, one for each type of service
10. Client code can only reference higher level modules
11. Higher level modules should have the least number of secret possible

TODO: Add directory tree output

After coming up with this list of principles, I started creating the HCL module for each resource type we use, import it in a local state, run terraform plan to ensure there are no changes and repeat till I create all the modules.

In order to make the plan/import phase quick, I was applying the changes on a single module basis. 

Since I ended up importing the resources over and over and over again, I decided to write a small powershell script to help me speed up the process.

The script looks like this:

```ps
```

This allows me to quickly import resources and run and re-run the same over and over without worring about re-importing a resource that' already part of the state.

## Useful resources

In order to import a resource you need to find it's unique identifier in Azure and this is not always easily doable from the portal so I took advantage of the following tools to make my life simpler

- az cli
- [resources.azure.com](resource.azure.com)

The first one may be familiar to everyone, it's the azure command line tool, the second is a bit less known in my opinion but still an excellent resource to look into the definition of the various resources.

This work took quite a bit of time