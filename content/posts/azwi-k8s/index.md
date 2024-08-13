---
title: "Implement Azure AD Workload Identity on AKS with terraform"
description: Implement Managed identity (Workload identity) on Azure Kubernetes Services using Terraform
date: 2022-02-24T09:55:39Z
draft: false
tags: ["azure", "terraform", "helm", "kubernetes"]
featuredImage: azwi.webp
---

Azure makes it very easy to create managed identities for a variety of services (e.g. Azure Functions, App Services, Logic Apps...), but when we want to implement it for Azure Kubernetes Service, things gets just a bit more complicated.

First of all we have few options to choose from:

- [AAD Pod Identity](https://github.com/Azure/aad-pod-identity) (deprecated)
- [Azure AD Workload Identity](https://azure.github.io/azure-workload-identity/docs/introduction.html) What we discuss in this post, azwi for brevity.

Both solutions aims to associate a pod with an identity in Azure Active Directory so we can grant this identity permissions to access another resource (i.e. a storage account or an Azure Sql Database).

As described on the documentation, azwi is the suggested approach from now on since Azure AD Pod Identity has been (somehow) deprecated as you can read on the [github repo](https://github.com/Azure/aad-pod-identity) and on the blog post [here](https://cloudblogs.microsoft.com/opensource/2022/01/18/announcing-azure-active-directory-azure-ad-workload-identity-for-kubernetes/).

The documentation describes Azure AD Workload Identity as follows:

>Azure AD Workload Identity for Kubernetes integrates with the capabilities native to Kubernetes to federate with external identity providers. This approach is simpler to use and deploy, and overcomes several limitations in Azure AD Pod Identity

Assuming you already have an AKS cluster up & running (I won't cover the creation of it here), in order to configure **Azure AD Workload Identity** we need to:

1. Configure the AKS cluster to enable OIDC issuer
2. Deploy the Azure AD Workload Identity helm chart to the cluster
3. Create a Federated Azure AD Application + a Service Principal
4. Create a kubernetes service account manifest with some azwi specific metadata
5. Configure our pods to run with the service account

## 1. Configure the AKS cluster to enable OIDC issuer

Unfortunately since OIDC issuer feature is still in preview at the time of writing (February 2022), there's no built-in support in terraform, but this is a one time only operation, you can read more about it [here](https://docs.microsoft.com/en-us/azure/aks/cluster-configuration#oidc-issuer-preview).

So we need to enable it from the azure cli with the following command:

> Enable **az cli** preview feature 

```
# Install the aks-preview extension
az extension add --name aks-preview

# Update the extension to make sure you have the latest version installed
az extension update --name aks-preview
```

> Enable OIDC issuer on an existing cluster

```
az aks update -n aks -g myResourceGroup --enable-oidc-issuer
```

After we enable the **OIDC issuer** feature we need to get the OIDC issuer url that will be used in the next step to federate the Azure AD Application, this can be done with the following command:

```
az aks show --resource-group <resource_group> --name <cluster_name> --query "oidcIssuerProfile.issuerUrl" -otsv
```

## 2. Deploy the Azure AD Workload Identity helm chart to the cluster

We can deploy a helm chart in several ways, in this case I decided to deploy the chart using terraform. 
You can achieve that with the following terraform code:

```hcl
resource "kubernetes_namespace" "azure-workload-identity-system" {
  metadata {
    annotations = {
      name = "azure-workload-identity-system"
    }
    name   = "azure-workload-identity-system"
    labels = var.tags
  }
}

resource "helm_release" "azure-workload-identity-system" {
  name       = "workload-identity-webhook"
  namespace  = "azure-workload-identity-system"
  chart      = "workload-identity-webhook"
  repository = "https://azure.github.io/azure-workload-identity/charts"
  wait       = false
  depends_on = [kubernetes_namespace.azure-workload-identity-system]

  set {
    name  = "azureTenantID"
    value = var.azureTenantID
  }
}
```

Here we create a new kubernetes namespace and we deploy the helm release. I choose to deploy with terraform the helm charts that I depend on (i.e. my application dependencies, for example Azure AD Workload Identity and kong that I use as my ingress).
We need to set the **azureTenantID** value when we deploy the helm chart with the current azure tenant id.
I read the current tenant id in the root module with the `data "azurerm_subscription" "current" {}` data source and pass in as a variable in the child module.

## 3. Create a Federated Azure AD Application + a Service Principal

Here we need to create an Azure AD Application + a Service Principal and federate the application with the OIDC Issuer so that Azure AD can exchange a token issued to the pod with a token that can be used to access other Azure resources.

We can achieve it with a bit of terraform:

```hcl
locals {
  namespace_name = "app-ns"
  ## This should match the name of the service account created by helm chart
  service_account_name = "app-${local.namespace_name}"
}

## Azure AD application that represents the app
resource "azuread_application" "app" {
  display_name = "sp-app-${var.env}"
}

resource "azuread_service_principal" "app" {
  application_id = azuread_application.app.application_id
}

resource "azuread_service_principal_password" "app" {
  service_principal_id = azuread_service_principal.app.id
}

## Azure AD federated identity used to federate kubernetes with Azure AD
resource "azuread_application_federated_identity_credential" "app" {
  application_object_id = azuread_application.app.object_id
  display_name          = "fed-identity-app-${var.env}"
  description           = "The federated identity used to federate K8s with Azure AD with the app service running in k8s ${var.env}"
  audiences             = ["api://AzureADTokenExchange"]
  issuer                = var.oidc_k8s_issuer_url
  subject               = "system:serviceaccount:${local.namespace_name}:${local.service_account_name}"
}

output "app_client_id" {
  value = azuread_application.app.application_id
}

```

Here we need to specify a couple of things:
- The OIDC Issuer url that we got from step 1, (I'm using a variable here to hold it's value)
- The subject that should follow a specific format: _system:serviceaccount:{k8s_namespace}:{k8s_service_account_name}_

> The namespace should match the namespace you will use to install your app in kubernetes and the Service Account name should match what you define in the kubernetes manifest.

## 4. Create a kubernetes service account manifest with some specific metadata

Here we will create the service account manifest and add the required metadata to allow the azwi do it's magic.

Here's the code to create a service account and the corresponding value file:

```yml
# serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "app.serviceAccountName" . }}
  labels:
    {{- include "app.labels" . | nindent 4 }}
    {{- with .Values.serviceAccount.labels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  {{- with .Values.serviceAccount.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}

# value.yaml
serviceAccount:
  # Labels to add to the service account
  labels:
    azure.workload.identity/use: "true" # Represents the service account is to be used for workload identity, see https://azure.github.io/azure-workload-identity/docs/topics/service-account-labels-and-annotations.html
  # Annotations to add to the service account
  annotations:
    azure.workload.identity/client-id: "{Client Id of the azure ad application}"
    azure.workload.identity/tenant-id: "{Tenant Id of you Azure subscription}"
    azure.workload.identity/service-account-token-expiration: "86400" # Token is valid for 1 day

```
> Please note that you can get the **client id** from the output of the step 3 and that the name of the service account should match what you set in the subject of the **azuread_application_federated_identity_credential**.

## 5. Configure our pods to run with the service account

We need to make sure our pods run with the service account created in step 4. 
In order to do that we just need to specify the **serviceAccountName** with the name of the Service Account in our _deployment.yaml_ file as shown below:

```yml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "app.fullname" . }}
  labels:
    {{- include "app.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "app.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      {{- with .Values.podAnnotations }}
      annotations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      labels:
        {{- include "app.selectorLabels" . | nindent 8 }}
    spec:
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      serviceAccountName: {{ include "app.serviceAccountName" . }}
....
```

This is all it takes, after we're done here, we can grant our Service Principal some rights to, for example, allow it to access a storage account in the following way:

```hcl
## Lookup our storage account
data "azurerm_storage_account" "storage" {
  name                = var.storage_account_name
  resource_group_name = var.storage_account_rg
}

## Role assignment to the application
resource "azurerm_role_assignment" "app_storage_contributor" {
  scope                = data.azurerm_storage_account.storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azuread_service_principal.app.id
}

```

This is my `required_providers` configuration:

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

    helm = {
      version = "2.4.1"
    }
  }
}
```

That's all for now, I hope you find this interesting, if you have any questions/suggestions, don't hesitate to comment!