---
title: "Configure secret-less connection from App Services to Azure Sql via terraform"
date: 2022-02-16T18:17:46Z
draft: false
tags: ["azure", "terraform", "sql", "managed-identity"]
featuredImage: cover.jpg
---

It's been a while since we can connect App services to Azure Sql in a secret-less fashion, using [managed service identity](https://docs.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/overview) (MSI for brevity from now onwards). 

The configuration is a bit more complicated than connecting to other Azure services e.g. Azure Storage Account because it involves running some queries on the Azure Sql database in order to create the user and grant them the required privileges, for more info see the tutorial [here](https://docs.microsoft.com/en-us/azure/app-service/tutorial-connect-msi-sql-database?tabs=windowsclient%2Cdotnet).

In order to be able to connect to Azure Sql with MSI we need to configure few things:
 - Grant database access to Azure AD users
 - Turn on MSI on the App Service
 - Create a user for the service principal and grant the required privileges in the database(s)
 - Change the connection string to use the new authentication mode

This is quite easy to do manually, but if you are using IaC, then manual changes are a no go.

Configure all of this in terraform was a non trivial task and took me quite a bit to understand the ins and outs and since I wasn't able to find much documentation online, I decided to put together this blog post.

## Step 1: Grant database access to Azure AD users
In order to be able to connect to Azure Sql with a managed identity, we need to configure the Azure Sql Server to allow Azure AD authentication, you can read more on the subject [here](https://docs.microsoft.com/en-us/azure/azure-sql/database/authentication-aad-configure?tabs=azure-powershell#provision-an-azure-active-directory-administrator-for-your-azure-sql-database-server).

Via terraform we can configure it adding the `azuread_administrator` block on the Azure Sql Server resource as shown below:

```hcl
resource "azurerm_mssql_server" "sql" {
  ...

  azuread_administrator {
    login_username = var.sql_server_ad_admin_username
    object_id      = var.sql_server_ad_admin_object_id
  }

  ...
}
```

Here we're passing in the **user name** and the **object id** of the Azure AD User or Azure AD Group that we want to configure as the server admin.

## Step 2: Turn on MSI on the App Service
In order to create a MSI for our App Service, we need to configure the identity block to `SytemAssigned` as shown below.

Please note that there's a small catch in terraform about turning on managed identity for an existing App Service, essentially you can't use it until it's there, so you may need to run `terraform apply` twice, one to turn on MSI, and then the second time to grant some privileges to it.

You can find more details on an issue I opened in the **azurerm** terraform provider [here](https://github.com/hashicorp/terraform-provider-azurerm/issues/14139).

```hcl
resource "azurerm_app_service" "web" {
  name                = "${var.prefix}-web-backend-${var.env}"
  location            = azurerm_resource_group.backend.location
  resource_group_name = azurerm_resource_group.backend.name
  ...

  identity {
    type = "SystemAssigned"
  }

  ...
}
```

## Step 3: Create a user for the service principal and grant the required privileges in the database(s)
This is the tricky part, that I struggled to automate because it requires running a couple of sql commands in the Sql Server database, as suggested in this article [here](https://techcommunity.microsoft.com/t5/azure-database-support-blog/using-managed-service-identity-msi-to-authenticate-on-azure-sql/ba-p/1288248).

The sql you need to run creates a user and grants it the required privileges as shown below.

```sql
CREATE USER [ServicePrincipalName] FROM EXTERNAL PROVIDER;
GO
ALTER ROLE db_datareader ADD MEMBER [ServicePrincipalName];
ALTER ROLE db_datawriter ADD MEMBER [ServicePrincipalName];
```

The point of this article though is to take care of this via terraform, in order to do so we need to:

1. Get the current Azure tenant id
2. Read the App Service service principal from Azure AD
3. Create the user and grant it required privileges in the database

Let's see how we can achieve this with terraform:

### Get current tenant id
This is easy, we can use a built-in terraform data source to access it:

```hcl
data "azurerm_client_config" "current" {}
```

### Read the App Service service principal from Azure AD
Here we can once again use a terraform data source to get access to the `application_id` property of the generated MSI as follows:

```hcl
data "azuread_service_principal" "web_managed_identity" {
  object_id = azurerm_app_service.web.identity.0.principal_id
}
```

### Create the user and grant it required privileges
In order to achieve this step, we need to use a 3rd party provider called `mssql_user`, you can find it on the terraform registry [here](https://registry.terraform.io/providers/betr-io/mssql/latest/docs/resources/user)

The only catch here is that you need to specify an Azure AD credential to connect to the Azure Sql database, so you can use the user we configured in the step 1 above.
If you used an Azure AD group instead you may create a service principal, add it to the group in Azure AD and use it's **client_id/client_secret** to connect to the database.

```hcl
resource "mssql_user" "web" {
  server {
    host = azurerm_mssql_server.sql.fully_qualified_domain_name
    azure_login {
      tenant_id     = data.azurerm_client_config.current.tenant_id
      client_id     = var.sql_sp_client_id
      client_secret = var.sql_sp_client_secret
    }
  }
  object_id = data.azuread_service_principal.web_managed_identity.application_id
  database  = var.database_name
  username  = azurerm_app_service.web.name
  roles     = ["db_datareader", "db_datawriter"]
}
```

Here we need to specify few things:
- The FQDN name of the Azure Sql Server
- How to login to the database (I'm using a service principal that's been added to the Azure AD group that's set as the Azure Sql Admin)
- What's the object id of the service principal we are granting access to
- What's the name of the service principal
- What roles we want to assign to it

## Step 4: Change the connection string to use the new authentication mode
> Note that you need to reference System.Data.SqlClient version 3 or greater for dotnet core, older versions doesn't support `Authentication=Active Directory Default`

```hcl
locals {
  connection_string = "Server=${var.prefix}-sql-${var.env}.database.windows.net; Authentication=Active Directory Default; Database=${var.database_name};MultipleActiveResultSets=False;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;Persist Security Info=False;"
}
```

and then we just need to set this new connection string on the App Service as follows:

```hcl
resource "azurerm_app_service" "web" {
  ...

  app_settings = {
    "ConnectionStrings__Database" = local.connection_string
    ...
  }

  ...
}

```

As a last step, I'm showing the terraform configuration to include all the required providers used to achieve this:

```hcl
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 2.84"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.14.0"
    }
    mssql = {
      source  = "betr-io/mssql"
      version = "0.2.4"
    }
  }
}

```

Nothing else needs to change in your code, given you were reading the connection string from the configuration.

I hope you find this useful!