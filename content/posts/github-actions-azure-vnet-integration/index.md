---
title: "Github Actions Azure Vnet Integration"
date: 2024-07-24T14:26:00+02:00
draft: true
tags: ["github", "azure", "devops", "terraform"]
---

Today we will look at an interesting one, having GitHub actions interact with Azure services which are not accepting traffic from the internet.

## Problem Statement

If you care about your security posture, one of the first things that you should fix when deploying services in Azure is to close down the public access to some PaaS services, like for example Azure Storage, Azure Cosmos DB or Azure SQL Server.

Most services allow you to close public access, meaning that you can't connect to those services over the Internet anymore. For your services running in Azure, you can take advantage of Virtual Networks, Private Endpoints and Private DNS Zones to restore connectivity without changing any single line of code in your services.

This is all good and well, but what about CI/CD runners? Chances are that you interact with your infrastructure in CI/CD pipelines (like for example running terraform apply) and as soon as you close the firewall, some operations will start to fail. One such operation is for example creating a storage container within an Azure Storage Account, whilst creating a container in an Azure Cosmos DB No-Sql account works just fine.

At this point, we have several ways of fixing the issue, here's a quick list:

- Open and close the PaaS Service public access when the pipeline starts and revert the operation at the end
- Allow access to the PaaS Services from within your office network and self-host your runners within your office network
- Self-host your runners in Azure Virtual Machines with network connectivity to those services

Not long ago, we got a new (better IMO) option which is to take advantage of GitHub private networking for hosted runners.

## GitHub private networking with GitHub-hosted runners

This relatively new feature, allows GitHub-hosted runners to use a NIC created in a VNET under your control. This way we don't have to manage our own hosted runners, GitHub will keep doing that for us, while still benefitting from the additional security benefits derived from disabling public access to the PaaS service in question.

To set this up we need to configure a few things:

1. Get your GitHub the Enterprise ID or Organization ID based on whether you want to create the Hosted Networking Configuration at the Enterprise or Organization level
1. Create the Azure VNET and Subnet in Azure that will host the NICs used by the GitHub runners
1. Create a GitHub network configuration in Azure
1. Create a Hosten Computed Newtock configuration in GitHub
1. Create the Runner Group(s) and Runner(s) in GitHub
1. Reference the newly created Runner(s) in your GitHub action `runs-on`

## Azure Private connectivity

Let's now take a look into a few concepts that are necessary for understanding how this can be configured.

### Private Endpoints

Private Endpoints can be thought of as Network Interface Cards (NICs) for your PaaS services. Those NICs are created in the VNET you specify and are assigned a private IP from the subnet address space.

When using Private Endpoints, the traffic never leaves the Microsoft backbone network as opposed to going through the public internet, making it not only more secure but also a faster way to access your PaaS services.

// TODO expand

### Private DNS Zones

A private DNS zone is then created in a well-defined zone name that contains an A record that resolves to the IP of the NIC. Private endpoints then allow you to connect to the PaaS service over Private Link.

When linking the Private Endpoint to the Private DNS Zone, we make sure that whenever the IP of the NIC connected to the Private Endpoint changes, the DNS record is automatically updated by the platform for us.

// TODO expand

### VNET Peering

If you need to connect from another VNET to the same service, you can take advantage of network peering and you should be able to connect to all the services in the directly peered networks.

// TODO expand

{{<alert>}}
Bear in mind that network peering is not transitive, so if you need to traverse several networks, you need to configure an NVA that knows how to route traffic
{{</alert>}}

All three components here above are used to configure private access to PaaS services and GitHub-hosted runners can take advantage of this infrastructure, in a similar way as your services do. When doing this from the Azure Portal, several steps are automated, whilst when using IaC tools, no automation comes to our rescue, so we need to configure a bit more stuff.

## Configuration

To get this configured we need to configure the networking in Azure, create the hosted network configuration in GitHub, create runner groups and runners in GitHub and, last step, we can change the workflow's `runs-on` to specify the new runner name, let see how to do this in detail

### Azure configuration

In Azure, you have to decide in which VNET the GitHub-hosted runner NICs will be created. You can use the same network where the private endpoint for your PaaS services lives or create another VNET to keep things separate, this decision is up to you and depends on your networking configuration. What's worth noting is that just a subset of Azure regions are supported, so you may be forced to create a VNET in a region different from the VNET that contains your Private Endpoints.

As of today (July 2024) the only supported regions are:

- EastUs
- EastUs2
- WestUs2
- WestUs3
- CentralUs
- NorthCentralUs
- SouthCentralUs
- AustraliaEast
- JapanEast
- FranceCentral
- GermanyWestCentral
- NorthEurope
- NorwayEast
- SwedenCentral
- SwitzerlandNorth
- UkSouth
- SoutheastAsia

If your VNET that contains the Private Endpoints is not in any of those regions, you have to create a new VNET and use Regional VNET Peerings. If you use a HUB/Spoke network topology, you may want to create a dedicated spoke where to host the GitHub NICs.

When you have multiple spokes, that need to communicate you can either peer them together or configure traffic routing through an NVA, please refer to the documentation on how to achieve that. // TODO expand and add documentation link

After the networking part has been created, we need to:

1. Register a new resource provider
1. Create a new resource of type GitHub.Network/netowkrSettings
1. Copy the tag.GithubId output

// Show the code and how to get the database id/organization id via a grapqhl query

### GitHub configuration

In GitHub, depending on whether you have an Enterprise Cloud or Team Plan, you can configure the **Hosted Compute Networking** on the Enterprise level or at the organization level. If you have GitHub Enterprise Cloud, you can still select whether to configure it at the Enterprise or Organization level.

I decided to create the Hosted Compute Networking configurations at the Organization levels because it was where it made the most sense to me, but creating it at the Enterprise level is pretty much the same thing, so you can easily adapt this tutorial to it.

1. Go to your Organization Settings
1. In Hosted Compute Networking, create a new Network Configuration and pick Azure Private Networking
1. Add a name to the configuration and then click on the _Add Azure Virtual Network_ button
1. Paste the ID copied before in the Network settings resource ID field
1. Save the configuration

After the network configuration is created, we have to create a Runner Group that uses the network configuration just created.

1. Go to Organization settings > Actions > Runner Groups
1. Give the Runner Group a name
1. In the network configuration dropdown, select the network configuration created in the previous step
1. Save the Runner group

After the Runner Group has been created, it's now time to create a runner (or more) within the Runner Group

1. Click on the Runner Group just created
1. Click on the New runner > New GitHub-hosted runner
1. Specify name, OS, Image (OS Version) and Specs (Size)
1. Make sure the Runner Group is the previously created Runner Group
1. Save the runner

Now that we have configured everything, we can change the `runs-on` label on a workflow and it will use the new runner that has VNET connectivity with our PaaS service.

## Conclusion

Thanks to GitHub private networking for hosted runners, we can ensure our CI/CD pipeline works seamlessly even when we deny public access to the PaaS services we use, allowing us to enhance the security posture of our Azure Subscription.

In this repository, I have a simple terraform configuration where I deploy an Azure Storage Account, disable Public Access, and create the Private Endpoints for blob and tables within a VNET. In another VNET I have configured the GitHub network settings, the output of such configuration is the token that you can input in GitHub when creating the Hosted Compute Networking configuration.

I hope you enjoyed this article, if you have some questions, don't hesitate to reach out.
Till the next time!
