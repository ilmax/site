---
title: "Zero downtime deployment with Azure Container Apps and Github Actions - Part 1"
date: 2022-06-24T10:12:18Z
draft: false
tags: ["azure", "github", "devops", "cloudnative"]
---

## Introduction
As you may know, Azure Container Apps went out of preview during Microsoft Build in late May this year.
Azure Container Apps is a very interesting service that runs on top of Kubernetes adding some additional powerful capabilities in a simple and covinient way.
Some of these capabilities are:

- Built in support for Keda autoscalers
- Built in support for Dapr components
- Ability to scale to zero

There's a lot more to it, you can dig deeper on the official Microsoft documentation [here](https://docs.microsoft.com/en-us/azure/container-apps/)

> TL;DR; All the code described in this article is available on Github [here](https://github.com/ilmax/container-apps-sample/releases/tag/v0.3)
I'm still working on improvements so main branch may be updated by the time you read this.

## Requirements
I would like to migrate several Azure App Services to Azure Container Apps, I have two different type of services, http api that write to a Service Bus queue/topic and web jobs that consume and process the messages, a pretty common setup these days.

Azure Container Apps allows me to easily scale the web jobs based on the amount of messages present in the queue/topic and also makes it easy to scale to zero outside business hours.

In order to migrate from Azure App Service to Azure Container Apps I want to implement a zero downtime deployment for the http api services.

## Problem
Azure Container Apps has built in support for [health probes](https://docs.microsoft.com/en-us/azure/container-apps/health-probes), there are 3 types of health probes:

- Liveness
- Readiness
- Startup

Given the built-in health probes support, I went under the assumption that, while using single revision mode, we could just deploy another revision and the control plane could take care of warming up and then swapping traffic to the new revision without downtime.
To my surprise I figured out that's not the case and if you're reading this blog post, you might have noticed that too.

I also double checked it on [Discord](https://aka.ms/containerapps-discord) with the Azure Container Apps team if I was missing something on my end, but they confirmed my findings.

---


After doing a bit of research, I figured it out that I can implement my own workflow to implement zero downtime deployment. This is far from ideal but still better than a deployment process that causes downtime.
Hopefully Azure Container Apps will implement built support for zero downtime deployment, but in the meantime the following approach is an acceptable workaround.

## Solution
In order to implement zero downtime deployment in (pseudo) single revisions mode (meaning using multiple revision mode with a single active revision at a time, serving all the traffic), we need to do the following steps:

1. Redirect all the traffic to the latest revision by name (more on that later)
2. Deploy a new revision
3. Warm up the new revision
4. Redirect the traffic to the newly deployed revision

> In this blog post I am using multiple revision mode because it happened to me that moving from single revision to multiple revision mode caused downtime - I'm currently investigating it and will update this post as soon as I found.
The idea is to have the container app configured in multiple revision mode but only have one active revision at a time.

Regarding step 1, Redirect all the traffic to the latest revision by name, has to do with the **latest** revision alias.
I found that if the traffic is set to the latest revision, when deploying a new revision, the traffic get redirected to the new revision even while it's still in the provisioning state, leading to possible timeouts and failures on the caller side.

The workflow above is a bit long but not particularly difficult, and we can easily implement it with the help of the Azure Cli **containerapp** extension.

Out of all the steps above, point 3 (Warm up the new revision) is the most tricky since different services may have different health probe configurations. I really didn't want to duplicate health probe configurations in the infrastructure and in the deployment pipeline but rather reuse what has been configured in the Container App Container instead.

Dynamically discovering and calling the health probe in bash is doable but I am a bit more proficient writing that code in a high level language so I decided to write a small C# application to do that.

In order to manage Azure resources, we can use the Azure Management SDK, this is a set of packages that allows you to manage Azure resources in your language of choice.
You can find all the supported resources [here](https://azure.github.io/azure-sdk-for-net/).

Luckily, Azure Container Apps already have an SDK available, although in beta at the moment of writing.

Since I should be able to invoke this application from a  Github Action, I decided to implementing a web application that exposes an api to make my life easy.

Essentially all the steps described above but steps 4 are executed in a github action, while step 4 is executed by a web application invoked by cURL in the Github Actions.

The next point to solve is where should be this web application deployed, we have few options:

- Have it always available
- Make it available on demand

> If you deploy an internal Azure Container App Environment and the application is not exposed to the internet, point two may be a bit more complicated since you need to make sure the github action runner can reach the Azure Container App you want to warm up.

I initially went with the first approach, having the application always available, but since I didn't want to also add authentication to the mix (to make sure only verified clients can call the warmup endpoint), I later decided against it.

In order to make this application available on demand, I decided to use Github Actions service container.
This post is getting already a bit too long so I won't go into detail of what service container is, let's just say that it allows you to run a container and made it available on the runner. If you wanna dig deeper, you can check the documentation [here](https://docs.github.com/en/actions/using-containerized-services/about-service-containers)

After sorting the Github Actions service container, last problem that I had to tackle was how to authenticate the application against Azure.
Thanks to **Azure.Identity** package and the **DefaultAzureCredential** class, we can just set some environment variables and authenticate with a previously defined service principal.

### Azure management SDK authentication
In order to get the required credentials to authenticate, we need to create a service principal with the **Reader** role on the resource group that contains the Azure Container Apps. 
We can quickly create this with the az cli and the following command:

```shell
az ad sp create-for-rbac -n "HealthProbeSp" --role Contributor --scopes /subscriptions/{subscriptionId}/resourceGroups/{resourceGroupId}
```
> Remember to replace the subscription and resource group names

After setting all this up, I was able to implement zero downtime deployment.

Here's an extract of the Github Action:

```yaml
jobs:
  build:
    name: build ${{ matrix.services.appName }}
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: read
    services:
      health-invoker:
        image: ghcr.io/${{ github.repository }}/health-invoker:main
        ports:
          - 5000:80
        env:
          AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
          AZURE_CLIENT_ID:  ${{ secrets.AZURE_CLIENT_ID }}
          AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
          Azure__SubscriptionId: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
          Azure__ResourceGroupName: ${{ secrets.RESOURCE_GROUP_NAME }}

# Clone repo, Build and push omitted for brevity 

      - name: Deploy azure container app without downtime
        if: github.event_name != 'pull_request' && matrix.services.zeroDowntime == true
        run: |
          echo "Installing containerapp extension"
          az extension add --name containerapp --upgrade &> /dev/null
          echo "Get latest active revision name"
          latest_revision=$(az containerapp show -n ${{ matrix.services.appName }} -g ${{ secrets.RESOURCE_GROUP_NAME }} --query properties.latestRevisionName -o tsv)
          echo "Redirect traffic to active revision $latest_revision"
          az containerapp ingress traffic set -n ${{ matrix.services.appName }} -g ${{ secrets.RESOURCE_GROUP_NAME }} --revision-weight $latest_revision=100 &> /dev/null
          echo "Create new revision"
          az containerapp update -n ${{ matrix.services.appName }} -g ${{ secrets.RESOURCE_GROUP_NAME }} -i ${{ steps.image-tag.outputs.tag }} &> /dev/null
          new_revision=$(az containerapp show -n ${{ matrix.services.appName }} -g ${{ secrets.RESOURCE_GROUP_NAME }} --query properties.latestRevisionName -o tsv)
          echo "Warmup new revision at ${{ env.WARMUP_APP }}/warmup/${{ matrix.services.appName }}"
          health_response_status=$(curl -m 180 --write-out "%{http_code}\n" -s ${{ env.WARMUP_APP }}/warmup/${{ matrix.services.appName }} --output backend.txt)
          if [ $health_response_status = "200" ]; then
            echo "Redirect traffic to new revision $new_revision"
            az containerapp ingress traffic set -n ${{ matrix.services.appName }} -g ${{ secrets.RESOURCE_GROUP_NAME }} --revision-weight $new_revision=100 $latest_revision=0 &> /dev/null
            echo "Deactivate revision $latest_revision"
            az containerapp revision deactivate -n ${{ matrix.services.appName }} -g ${{ secrets.RESOURCE_GROUP_NAME }} --revision $latest_revision &> /dev/null
          else
            echo "Warmup failed with status code $health_response_status"
            cat ./backend.txt
            echo "Redirect traffic to active revision $latest_revision"
            az containerapp ingress traffic set -n ${{ matrix.services.appName }} -g ${{ secrets.RESOURCE_GROUP_NAME }} --revision-weight $latest_revision=100 &> /dev/null
            if [ ! -z "$new_revision" ]; then
              echo "Deactivate revision $new_revision"
              az containerapp revision deactivate -n ${{ matrix.services.appName }} -g ${{ secrets.RESOURCE_GROUP_NAME }} --revision $new_revision &> /dev/null
            fi
            exit 1
          fi
```
Here's the output of [wrk](https://github.com/wg/wrk) while deploying a new revision:

```
wrk -t12 -c400 -d30s https://xxxxxxxx.azurecontainerapps.io/api/echo/ping
Running 30s test @ https://xxxxxxxx.azurecontainerapps.io/api/echo/ping
  12 threads and 400 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   268.53ms  123.73ms   1.02s    68.90%
    Req/Sec   137.15    103.17     1.15k    66.59%
  41604 requests in 30.10s, 8.89MB read
Requests/sec:   1382.32
Transfer/sec:    302.38KB
```

After deployment has been completed:
```
wrk -t12 -c400 -d30s https://xxxxxxxx.azurecontainerapps.io/api/echo/ping
Running 30s test @ https://xxxxxxxx.azurecontainerapps.io/api/echo/ping
  12 threads and 400 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   251.00ms  135.47ms   1.24s    77.22%
    Req/Sec   148.38    104.52   434.00     63.10%
  44970 requests in 30.09s, 9.61MB read
Requests/sec:   1494.36
Transfer/sec:    326.89KB
```

As you can see there's almost no difference and, most importantly, wrk doesn't indicate any non 2XX or 3XX response meaning that we were able to serve all requests while deploying a new revision.

> The numbers are quite low because I'm using a very small configuration for testing purposes (0.25 Cores and 0.5 Gi of memory)

---

I hope you find this helpful and if you have suggestions , don’t hesitate to comment or reach me out via twitter at [twitter.com/maxx_don](twitter.com/maxx_don).

Stay tuned for part 2 that will be out very soon!