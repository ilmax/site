---
title: "Poor mans App services deployment slot auto-swap for Linux with GitHub Actions"
date: 2021-12-08T18:14:44Z
draft: false
tags: ["azure", "cloud", "terraform", "github"]
---

Nowadays [App Service](https://docs.microsoft.com/en-us/azure/app-service/) deployment has became quite straight forward. Since support for running Docker containers was added to the platform, this has become my preferred way of deploying and running code in production.

One way to deploy a Docker container to an App Service is taking advantage of an [Azure Container Registry](https://azure.microsoft.com/en-us/services/container-registry/) (henceforth  referred to as ACR), the process looks like this:

Ahead of time:
* Configure the App Service to pull the image from your ACR

During continuous delivery build:
* Build and tag your docker image with the name of the ACR
* Login to ACR
* Push the image to ACR via a docker pull
* Somehow push the new image from ACR to the App Service

One of the way to achieve it is to configure an [ACR webhook](https://docs.microsoft.com/en-us/azure/container-registry/container-registry-webhook) so ACR "pushes" the new image to the App Service as soon as a new image is pushed to the ACR repository. 
This can be achieved quite easily with terraform, as shown in the following snippet:

```terraform
resource "azurerm_resource_group" "rg" {
  name     = "${var.prefix}-${var.env}"
  location = var.region
}

resource "azurerm_app_service_plan" "plan" {
  name                = "${var.prefix}-plan-${var.env}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  kind                = "linux"
  reserved            = true
  sku {
    tier = var.app_service_plan_sku_tier
    size = var.app_service_plan_sku_size
  }
}

resource "azurerm_app_service" "app" {
  name                = "${var.prefix}-app-${var.env}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  app_service_plan_id = azurerm_app_service_plan.plan.id
  https_only          = true
  site_config {
    always_on         = "true"
    linux_fx_version  = "DOCKER|${azurerm_container_registry.acr.login_server}/app:latest"
  }
}

resource "azurerm_container_registry" "acr" {
  name                = "${var.prefix}${var.env}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "Standard"
  admin_enabled       = true
}

resource "azurerm_container_registry_webhook" "webhook" {
  name                = "${var.prefix}webhook${var.env}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  registry_name       = azurerm_container_registry.acr.name
  service_uri         = "https://${azurerm_app_service.app.site_credential[0].username}:${azurerm_app_service.app.site_credential[0].password}@${azurerm_app_service.app.name}.scm.azurewebsites.net/docker/hook"
  status              = "enabled"
  scope               = "app:*"
  actions             = ["push"]
  custom_headers      = { "Content-Type" = "application/json" }
}
```

As shown, it's quite straightforward to implement. We just configure the App Service to run the Docker image `app:latest` and use the ACR as the source. 
On the ACR side we define a webhook that pushes the image to the App Service identified by the `service_uri` when a new image is pushed to an ACR repository that matches the scope `app:*`

>The `actions` value defines the webhook trigger


>The `scope` at which the webhook works. If not specified, the scope is for all events in the registry. It can be specified for a repository or a tag by using the format "repository:tag", or "repository:*" for all tags under a repository.

The github action is also quite easy, for example:

```yml
name: Build and deploy app

on:
  push:
    branches:
      - master

env:
  webAppName: app
  imageTag: ${{secrets.REGISTRY_URL}}/app:latest      

jobs:
  build-and-push:
    name: Build and publish
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout
        uses: actions/checkout@v2

      - name: Docker Login
        uses: azure/docker-login@v1
        with:
          login-server: ${{secrets.REGISTRY_URL}}
          username: ${{secrets.REGISTRY_LOGIN}}
          password: ${{secrets.REGISTRY_PASSWORD}}

      - name: Build & push application
        run: |
          docker build -f ./Path/To/Your/Dockerfile . --tag ${{env.imageTag}}
          docker push ${{env.imageTag}}
```

As you can see we just 
* build the docker image 
* tag it with something that will look like: `{your_acr_name}.azurecr.io/app:latest` 
* push it to the ACR.

>Please note that you have to tag the Docker image with the ACR name, for the tag version you can come up with more sophisticated approaches like using a version or the sha1 of the latest git commit, but for the sake of simplicity I'll go with `latest` tag version.

This way of deploying things makes it very simple to configure your github action since you just login to ACR and then do a docker push, everything else is taken care of by the webhook.

So far so good. 
You can build and deploy your code to an App Service very easily.
If you also want to implement **zero downtime deployments** and you're running on **Linux** things get just a bit more complicated because, as you're probably aware, Azure App Service auto-swap functionality is not available in Linux based App Service.

>If you need to know what a deployment slot is, you can find the documentation [here](https://docs.microsoft.com/en-us/azure/app-service/deploy-staging-slots).

When using a deployment slot, the deployment process becomes the following:
* Build and tag your docker image with the name of the ACR
* Login to ACR
* Push the image to ACR via a docker pull
* Somehow push the new image from ACR to the App Service deployment slot
* Swap the deployment slot

The problem here is **how to make sure the updated container image has been deployed to the staging slot before starting the slot swap**. 

This is tricky to get right since we don't have control over ACR webhook execution so we have no way to ensure that swapping the slot will be executed after the slot has been updated. 

If your app service targets Windows you can use the [auto-swap](https://docs.microsoft.com/en-us/azure/app-service/deploy-staging-slots#configure-auto-swap), when on Linux instead you can slightly change your github action to push to ACR and also deploy the container to your staging slot. This step (App Services deploy) will wait till deployment is completed so we can safely run the swap action soon after.

See the updated github action below, also note we don't need the webhook anymore on the ACR.

```yml
name: Build and deploy app

on:
  push:
    branches:
      - master

env:
  webAppName: app
  imageTag: ${{secrets.REGISTRY_URL}}/app:latest      

jobs:
  build-and-push:
    name: Build and publish
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout
        uses: actions/checkout@v2

      - name: Docker Login
        uses: azure/docker-login@v1
        with:
          login-server: ${{secrets.REGISTRY_URL}}
          username: ${{secrets.REGISTRY_LOGIN}}
          password: ${{secrets.REGISTRY_PASSWORD}}

      - name: Build & push application
        run: |
          docker build -f ./Path/To/Your/Dockerfile . --tag ${{env.imageTag}}
          docker push ${{env.imageTag}}

      - name: Azure Login
        uses: azure/login@v1
        with:
          creds: ${{secrets.AZURE_CREDENTIALS}}

      - name: App Services deploy
        uses: azure/webapps-deploy@v2
        with:
          app-name: ${{env.webAppName}}
          images: ${{env.imageTag}}

      - name: Sign out of Azure
        run: az logout
```

I hope you enjoyed it and find it useful.
