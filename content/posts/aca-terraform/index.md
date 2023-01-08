---
title: "Create Azure Container Apps with terraform"
date: 2022-05-26T10:04:06Z
draft: false
tags: ["azure","terraform", "cloudnative"]
---

Microsoft announced at Microsoft Build that [Azure Container Apps](https://azure.microsoft.com/en-us/services/container-apps/) are now generally available (GA).

If you're not familiar with Azure Container Apps (ACA) I suggest you to go and check out the documentation [here](https://docs.microsoft.com/en-us/azure/container-apps/?ocid=AID3042118). 

> Fully managed serverless container service for building and deploying modern apps at scale

This is how Microsoft itself markets the product.

I think it's a very interesting platform and it offers some of the benefits of Kubernetes, abstracting a lot of concepts and complexity.

In order to start playing around with it, I usually create a repo with some terraform code so I can spin up a set of resources, play with them and then destroy all of them when I'm done.

As you may know not all Azure resources are available in terraform azure provider(s) from day 1, but for a month or so we have the awesome **AzApi** provider for terraform.

Follow [this](https://github.com/hashicorp/terraform-provider-azurerm/issues/14122) github issue that tracks adding support for it in the **azurerm** official provider.

>The AzAPI provider enables you to manage any Azure resource type using any API version.

Thanks to this provider it is very easy to create an Azure Container App with terraform.

Here's how you configure the provider:
{{< gist ilmax 11817b6c0e00df9237ae54e2c5fcef84 "provider.tf" >}}

Here you can see how you can use **azapi_resource** to create an Azure Container App
{{< gist ilmax 11817b6c0e00df9237ae54e2c5fcef84 "containerapp.tf" >}}

## Tips
In order to discover the properties, I first make the changes it in the Azure portal, then I'm running the following **az-cli** command:

`az containerapp list`

and then you need to transform the json to the terraform equivalent.

You can also install [Terraform AzApi Provider Visual Studio Code Extension](https://marketplace.visualstudio.com/items?itemName=azapi-vscode.azapi) VS Code extension that should provide completion support.

> Kudos to [piizei](https://github.com/piizei) for coming up with the suggestion [here](https://github.com/hashicorp/terraform-provider-azurerm/issues/14122#issuecomment-1101561028)

If you want to see a more advanced example, you can give a look at my repo [here](https://github.com/ilmax/container-apps-sample/blob/main/infra/container-app.tf). 

Hope you find this helpful, if you have any question/suggestion, don't hesitate to comment!