---
title: "Connect from GitHub to Azure without secrets"
date: 2023-01-19T16:39:35+01:00
draft: true
tags: ["github", "azure", "devops", "terraform"]
---

OpenID Connect (OIDC) allows your GitHub Actions workflows to access resources in Azure, without needing to store the Azure credentials as long-lived GitHub secrets.

This functionality has been available for quite a while, it was first announced on [October 2021](https://azure.microsoft.com/en-us/updates/public-preview-openid-connect-integration-between-azure-ad-and-github-actions/) and up until now, it has been on my "things to look into" list.

Recently I'm working on a project to migrate Azure DevOps to GitHub so I decided that time has come to look into this functionality.

This will come in handy every time you need to connect from GitHub to Azure, for example when deploying your infrastructure or your applications.

## How a typical connection is configured
Usually, to connect to Azure as an application (i.e. when running a GitHub Action) you need to:
1. Create a Service Principal in Azure Ad
2. Create a Service Principal Credential
3. Grant to the Service Principal permissions on the subscription(s)
4. Copy the secret created in step 3 on your GitHub secrets
5. Authenticate the workflow using the secret created above

> Please note that the `az ad sp create-for-rbac` can simplify the process a bit since it can do steps from 1 to 3 in a single go, more infor [here](https://learn.microsoft.com/en-us/cli/azure/ad/sp?view=azure-cli-latest#az-ad-sp-create-for-rbac)

## Why should you use secret-less connections
It's quite obvious that having secrets-less connections is far better than using some form of a shared secret.
Since you don't have any secrets, you can't leak any moreover shared secrets usually comes with a fixed validity. Ideally, you should rotate them often to limit the risk derived from a secret leak.

One additional reason is that, in the case of infrastructure deployments, the Service Principal will have high privileges on your subscription(s) since it has to create resources, potentially assign RBAC role assignments (that require the Owner role) and so on.

> Please note that even if you store the shared secret in to GitHub secrets, it's still possible to get access to it

## How can we set it up?
Configuring OpenID Connect in Azure you need to do a couple of things:
1. Create an App Registration in Azure Ad
2. Create a Service Principal for the App Registration
3. Add the federated credentials in the App Registration
4. Copy the configuration values CLIENT_ID, SUBSCRIPTION_ID and TENANT_ID in GitHub
5. Configure your workflow permissions
6. Use the action `azure/login@v1` specifying all 3 parameters described above.

For a step-by-step guide, refer to [this](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-azure)

## How does it work?
It's not the goal of this post to dig into how this works, so my explanation will be quite brief.
Under the hood, this uses `Azure Workload identities` to exchange a token issued by GitHub with a token issued by Azure Active Directory.

For the token exchange to be successful, you need to configure the federated credential in Azure Active Directory filling in what the content of some claims will be, more specifically you need to fill it in:
- The issuer (iss claim of the access token issued by GitHub)
- The subject (sub claim of the access token issued by GitHub)
- The audience (fixed value of `api://AzureADTokenExchange`)

If you want to read more, here's the relative [documentation](https://learn.microsoft.com/en-us/azure/active-directory/develop/workload-identity-federation).

## Manual configuration
If you go to Azure Active Directory, after you created an App Registration, when you try to add federated credentials, the Azure Ad Portal helps you with filling in the required details for setting up GitHub federated credentials.

The screen looks like the following:
![GitHub Federated Credentials](federated-credentials.png "GitHub Federated Credentials")

If you have to configure multiple repositories, the manual approach falls short so let's look at how we can configure it with Terraform

## Terraform configuration
Since Terraform has a provider-based approach, we can configure a GitHub repository (or many) and at the same time create the required setup in Azure Active Directory, let's see how is done:

```tf
// Look-up GitHub Actions token issuer discover document
data "http" "github_actions_oidc_discovery_document" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"

  request_headers = {
    Accept = "application/json"
  }

  lifecycle {
    postcondition {
      condition     = contains([200], self.status_code)
      error_message = "Status code invalid"
    }
  }
}

locals {
  github_issuer = jsondecode(data.http.github_actions_oidc_discovery_document.response_body)["issuer"]
}

// Create an Azure AD Application for the GitHub Actions Service Principal
resource "azuread_application" "github_app_registration" {
  display_name = "GitHub-App-Registration"
}

// Create a Service Principal for the GitHub Actions App Registration
resource "azuread_service_principal" "github_service_principal" {
  application_id = azuread_application.github_app_registration.application_id
  use_existing   = true
}

// Create the Federated Credential for the App Registration
resource "azuread_application_federated_identity_credential" "github_federated_credentials" {
  application_object_id = azuread_application.github_app_registration.object_id
  audiences             = ["api://AzureADTokenExchange"]
  display_name          = "GitHub-FederatedCredential"
  issuer                = local.github_issuer
  subject               = "repository_owner:${var.organization}:environment:${var.environment}"
}

// Look-up current subscription and tenant id
data "azurerm_client_config" "current" {}

// Create the repository and the environment
resource "github_repository" "repository" {
  name        = var.repository_name
  description = var.repository_description
}

resource "github_repository_environment" "environment" {
  environment  = var.environemnt
  repository   = github_repository.repository.name
}

// Create the secrets into the environment
resource "github_actions_environment_secret" "client_id" {
  environment     = github_repository_environment.environment.environment
  repository      = github_repository.repository.name
  secret_name     = "CLIENT_ID"
  plaintext_value = azuread_application.github_app_registration.application_id
}

resource "github_actions_environment_secret" "subscription_id" {
  environment     = github_repository_environment.environment.environment
  repository      = github_repository.repository.name
  secret_name     = "SUBSCRIPTION_ID"
  plaintext_value = data.azurerm_client_config.current.subscription_id
}

resource "github_actions_environment_secret" "tenant_id" {
  environment     = github_repository_environment.environment.environment
  repository      = github_repository.repository.name
  secret_name     = "TENANT_ID"
  plaintext_value = data.azurerm_client_config.current.tenant_id
}

```

## Quirks
As you can see, the configuration is quite straightforward, but there's a catch.
Since you have to configure the subject (sub) claim in the Federated Credential with the same value of the sub claim that GitHub is issuing to your workflow and by default the repository name will be part of the claim value, this means you will have to create one App Registration, Federated Credential and Service Principal for each repository.

This may be a totally fine solution if you have a limited number of repositories, but in my case, I had around 60 repositories that needs to be deployed.
On top of that, we (like probably most of you) have several environments e.g. Development, Testing, Acceptance, and Production and since I don't want the same Service Principal to have access to different subscriptions for security reasons, the number of App Registrations, Federated Credentials and Service Principal gets multiplied by a 4 factor (one for each environment) reaching a whopping 240.

> Please note that In order to achieve this you need to use GitHub deployment environments. Environments, environment secrets, and environment protection rules are available in public repositories for all products. For access to environments, environment secrets, and deployment branches in private or internal repositories, you must use GitHub Pro, GitHub Team, or GitHub Enterprise. For access to other environment protection rules in private or internal repositories, you must use GitHub Enterprise, see [documentation](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment)

As you can imagine this is not ideal so I decided to look at possible alternatives. What I wanted to achieve was creating 4 App Registration, one for every environment and using the same one across all the repositories.
To achieve what I described above, I need a way to change the content of the subject claim issued by GitHub, luckily for use this functionality is supported out of the box via an api call.
> As far as I know, there's no UI support to change the content of the access token issued by GitHub yet.

## Configure the subject claim with Terraform
Here below you can see how to configure the subject claim for our use case:

```tf

```

There're more customization possible and you can learn about these in the GitHub [documentation](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect#customizing-the-token-claims).

I hope you found this useful. 
Till the next time

