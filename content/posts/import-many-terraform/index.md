---
title: "Terraform Tips & Tricks: Managing Large-Scale Azure Resource Imports"
description: How to bulk import existing infrastructure in terraform
date: 2023-01-08T14:44:21Z
draft: false
tags: ["azure", "Terraform", "devops"]
---


This post describes my journey to import several hundred Azure resources in Terraform. Before digging into the what and the how let me give you a brief description of our environment's infrastructure.

In my current company, we manage many Azure resources for each environment and we have a few of them (DEV, TEST, etc.). Every environment looks pretty much the same and it mostly differs by product SKUs, database sizes, etc.

My fellow team members and I are building a microservices solution, we have around 50 independent services deployed in Azure that require some specific resources (imagine a SQL database or a Storage container), and on top of that, we have all the service agnostic infrastructure.

All these resources aren't created/updated in the same way, some use ARM templates, some use PowerShell scripts, some use Azure cli scripts and so on.
This is mostly because we need to work around some tooling limitations e.g. you can't create resources in Azure Active Directory using ARM templates.

All the aforementioned scripts are placed in a shared repository and every project references what it needs in its deployment pipeline.

This approach works, but it has several problems:

1. We use different technologies to deploy infrastructure and that makes it harder for newcomers to get up to speed quickly
2. Deployments take longer than necessary
3. It's impossible to have a preview of the changes that are going to be applied at deployment time
4. Re-deploying infrastructure may not fix all the [configuration drift](https://wiki.gccollab.ca/index.php?title=Technology_Trends/Infrastructure_as_Code&mobileaction=toggle_view_desktop#Configuration_Drift) especially the PowerShell/az cli scripts

I'm sure I missed several other points but these are the most painful ones.

Hence we decided to move to Terraform since it can address all the points above and, according to [GitHub Octoverse 2022](https://octoverse.github.com/2022/top-programming-languages), HCL was the fastest growing language in 2021-2022.

## The import challenge

If you start on a greenfield project everything is quite easy, but as you may know, if a resource has been created outside Terraform, it needs to be imported to be managed with Terraform in the future.
Importing resources is not difficult, on the provider documentation site, at the bottom of the page of every resource, you can find the command to execute to import a given resource.

My problem was that I had hundreds of them, around 160 global resources, multiplied by all the various environments + between 5-10 resource service dependent multiplied by the number of services ~50 multiplied by the number of environments.

As you can imagine this adds up very quickly, especially because importing resources is a tedious task. 
To import a resource in Terraform you need a couple of things:
- Create the resource in your configuration files
- The Terraform resource id 
- The Azure resource id

For example:
```sh
                |--------------Terraform resource id-------------------| |-----------------------------------------Azure resource id---------------------------------------------------------------|
terraform import module.servicebus.azurerm_servicebus_namespace.example  /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/mygroup1/providers/Microsoft.ServiceBus/namespaces/sbns1
```

To get the Terraform resource id, you may first need to come up with the final module structure because if you use modules, the module name would be part of the Terraform resource id (as can be seen above).

Figuring out the Azure resource id can also be challenging for some nested resources, e.g. a cosmos role assignment requires some az cli gymnastics.
 
This seemed like a herculean effort so I started looking around hoping to find a tool that could help with a bulk import.

### Azure Terrafy - Aztfy
[Aztfy](https://github.com/Azure/aztfy) is a tool developed by Microsoft that allows you to bulk import resources, it has some configuration so you can specify what to import, the names to import and so on.
After spending some time with the tool, I quickly realized it may be a no-go. The problem I had with this tool is twofold:

1. It doesn't generate reproducible Terraform configurations
2. It doesn't generate Terraform idiomatic code

Let me expand on those:

Not generating reproducible configurations means that after an import, when you run Terraform plan, you may still have changes that you need to fix manually, or worse, Terraform may fail due to validation problems. 
This limitation is documented in the project [README](https://github.com/Azure/aztfy#limitation) and I could've lived with it.

Not generating idiomatic code is a bit more problematic, since it requires manually changing most parts of the imported code to make use of variables or to reference a parent resource.
This means that all the code that **aztfy** will output, needs to be adjusted/modified. Moreover, if you decide to reorganize the code and move resources in a different module (hence changing the Terraform resource id) after it has been imported, then you have to either start modifying the Terraform state manually, or you may need to import it all over again.

Given the above downsides, I decided to use it only marginally and instead start writing my configuration from scratch.

## My approach

Before starting I came up with a set of principles to use as guidelines when writing HCL modules, which are:

1. One module for every different resource type used
2. For every module that needs access to resources defined in other modules, read these resources with a data source
3. All the module's inputs are defined in a file called `variables.tf`
4. All the permissions-related stuff (RBAC, AAD group membership) will go in a file called `permission.tf`
5. All the networking configuration (Firewall rules, VNet, Private endpoints and so on) will go in a file called `networking.tf`
6. All the module's outputs will go in a file called `output.tf`
7. These lower-level modules will be invoked by a higher-level module where most of the naming logic will be
8. Lower-level modules can only be called by higher-level modules
9. Several higher-level modules will be created:
    - Environment specific with all the global resources 
    - Several service-specific ones, one for each type of service
10. Client code can only reference higher-level modules
11. Higher level modules should have the least number of secret possible
12. Lower-level modules shouldn't reference other lower-level modules

> Please note that these are principles I came up with and that make sense in my specific scenario, your mileage may vary

### Directory structure

The principles stated above helped me come up with a directory structure that looks like the following:

```bash
├── environments
│   ├── acc
│   ├── dev
│   ├── prod
│   └── tst
├── modules
│   ├── private                --> Lower-level modules
│   │   ├── global
│   │   │   ├── global_azure_service_1          e.g. Cosmos Db 
│   │   │   ├── global_azure_service_2          e.g. vNET
│   │   │   ├── global_azure_service_3          e.g. App Service Plan
│   │   └── service
│   │       ├── service_specific_resource_1     e.g. App service
│   │       ├── service_specific_resource_2     e.g. Cosmos container
│   │       ├── service_specific_resource_3     e.g. Sql Database
│   └── public                 --> Higher-level modules
│       ├── environment     
│       └── webapp
```

### Import Script

After coming up with this list of principles, I started creating the Terraform module for each resource type, importing it in a local state, running Terraform plan to ensure there are no changes and repeating till I created all the modules.

To make the plan/import phase quick, I was applying the changes on a single lower-level module basis. 

Since I ended up importing the resources over and over and over again, I decided to write a small PowerShell script to help me speed up the process. 

This script tries to address the two main paint points:
- Do not re-import a resource that's already imported 
- Simplify reuse across environments via PowerShell string interpolation, whenever Azure resource Ids are predictable.

>Please note that the last point depends on your resources naming conventions.

The script looks like this:

```ps1
Terraform init // Comment this out after the first execution

# Get all the items from Terraform state and put it inside an array
$stateItems = $(Terraform state list)

function ImportIfNotExists {
    param (
        [String]$resourceName,
        [String]$resourceId
    )

    if ($resourceId -eq $null -or $resourceId -eq "") {
        Write-Warning "Resource id for $resourceName is null"
        return
    }

    if ($stateItems -notcontains $resourceName.Replace("\", "")) {
        Write-Host "Importing $resourceName with id $resourceId"
        Terraform import "$resourceName" "$resourceId"
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Error importing $resourceName with id $resourceId"
        } else {
            Write-Host "$resourceName imported"
        }
    } else {
        Write-Host "$resourceName already exists"
    }
}

$env = "DEV"
$subscriptionId = "your-subscription-id-here"
$spokeResourceGroupName = "myrg-spoke-$env".ToLower()
$hubResourceGroupName = "myrg-hub-$env".ToLower()

$ErrorActionPreference  = "Stop"

## Resource group import
ImportIfNotExists 'module.environment.azurerm_resource_group.spoke_rg' "/subscriptions/$subscriptionId/resourceGroups/$spokeResourceGroupName"
ImportIfNotExists 'module.environment.azurerm_resource_group.hub_rg' "/subscriptions/$subscriptionId/resourceGroups/$hubResourceGroupName"
```

This script allows me to quickly import resources and iterate faster since it allows me to re-run the same over and over without worrying about re-importing a resource that's already part of the state.

As stated above, you can make the script reusable for multiple environments with few modifications. Some Azure resource ids are a bit more complex to figure out hence I usually do a manual lookup and find-and-replace.
Some of those resources include:

- Cosmos Sql Role Definition (The Role id uses a guid so it's different for every role definition)
- Cosmos Sql Role Assignment (same as above)
- RBAC role assignment
- Automation account job schedules
- AAD Groups
- AAD Groups membership

> Please note that your mileage may vary depending on the resources you use

If you want to, you can enhance the script to also look up these resources using the azure cli and a bit of [JMESPath](https://learn.microsoft.com/en-us/cli/azure/query-azure-cli?tabs=concepts,bash), for example, I'm doing this to look up AAD groups since in my case they follow a naming convention:

```ps1
ImportIfNotExists 'sample.azuread_group.your_group_name' $(az ad group show --group "{your-group-name-prefix}-$env" --query id --output tsv)
```

Here below you can see an example where I'm employing JMESPath to further filter the result of az cli to look up the role assignment for a given role and group:

```ps1
ImportIfNotExists 'sample.azurerm_role_assignment.your_group_assingments' $(az role assignment list --scope {your-scope} --query "[?principalName=='{you-principal-name}' && roleDefinitionName=='{your-role-name}'].id" -o tsv)
```

where:

- **{your-scope}** is the resource you assigned the RBAC role assignment to (e.g. the resource group or a specific resource)
- **{you-principal-name}** is the user name, group name or managed identity name of the principal that will be granted the role
- **{your-role-name}** is the name of the RBAC roles you assigned (e.g. Contributor)

This is quite powerful and allows you to make the script parametric enough to allow you to reuse it for all environments. 

>It's also worth considering though that the import operation will be executed just once, so it may be quick to just do a find replace at times.

## Quirks

If you have declared resources that use `for_each` in HCL, the name of the resource may contain (based on what you're foreach-ing) a string, e.g.
imagine you're creating several service bus topic using a for_each in the following way:

```hcl
resource "azurerm_servicebus_namespace" "example" {
  name                = "tfex-servicebus-namespace"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  sku                 = "Standard"
}

resource "azurerm_servicebus_topic" "topics" {
  name         = each.value
  namespace_id = azurerm_servicebus_namespace.example.id

  for_each var.topics
}
```

Then the Terraform identifier will be something like the following: 
```tf
module.servicebus.azurerm_servicebus_topic.topics["{topic-name}"].
```

To make Terraform and PowerShell play nicely together in the import script, you have to write the above this way:

```ps1
ImportIfNotExists 'module.servicebus.azurerm_servicebus_topic.topics[\"{topic-name}\"]' "{servicebus-resource-id}"
```

To avoid the Terraform error: import requires you to specify two arguments.

## Useful resources
To import a resource you need to find its unique identifier in Azure and this is not always easily doable from the portal so I took advantage of the following tools to make my life simpler

- [az cli](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- [resources.azure.com](resource.azure.com)

The first one will be familiar to everyone, it's the azure command line tool and it's a must-have, the second one is a bit less known in my opinion but still an excellent resource to look into the definition of the various resources.

This work took quite a bit of time but in the end, I was able to import all the resources in all the environments and come up with idiomatic HCL code.

I hope you find this helpful!

Till the next time.