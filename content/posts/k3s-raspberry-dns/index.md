---
title: "Install K3s on a Raspberry PI - Automatic DNS management"
date: 2024-08-05T21:11:10+02:00
draft: true
series: ["K3s on Raspberry PI"]
series_order: 4
tags: ["Kubernetes", "homelab", "rpi", "tutorial"]
---

So far so good, if you're following along, we implemented a great deal of features and we automated several, one though still need to be addressed, automatic DNS management, and that's the focus of today's post.

External-dns is pretty much the de-facto standard in this area and its goal is to:

{{<lead>}}
ExternalDNS synchronizes exposed Kubernetes Services and Ingresses with DNS providers
{{</lead>}}

Which automates the DNS management making sure we don't have to create DNS entries whenever we deploy a new service or that we don't leave [dangling DNS records](https://www.paloaltonetworks.com/cyberpedia/what-is-a-dangling-dns) whenever we delete an exposed service.

The idea is that we somehow tag some services to be watched by external-dns and the tool takes care of keeping our DNS provider in sync with the services exposed in Kubernetes, seems simple enough right?

Actually to get this working it took me way more time than I want to admit, so I decided to document how I configured external-dns and the result I got, so without further ado, let's delve into it.

## Concepts

External-dns needs to synchronize exposed Kubernetes **sources** with DNS **providers**.

### Sources

External-dns can monitor several different types of Kubernetes resources used to expose a service, among the supported ones we can find Ingress, Services, Gateway and also Traefik's own IngressRoute we used in the preceding blog posts.

The source is the resource type external-dns keeps monitoring for changes and the one used to construct the DNS records that will be then synched in the DNS provider.

{{<alert icon="lightbulb" cardColor="#097969" iconColor="#AFE1AF" textColor="#f1faee">}}
**TIP:** The list of supported sources can be found in the [documentation](https://kubernetes-sigs.github.io/external-dns/v0.14.2/sources/sources/).
{{</alert>}}

### Providers

The provider identifies the DNS provider where external-dns synchronizes the DNS changes, there're a lot of supported providers and they have different stability levels, the one I'm interested in, CloudFlare, has a **beta** stability level which is defined as:

> **Beta**: Community supported, well tested, but maintainers have no access to resources to execute integration tests on the real platform and/or are not using it in production.

So far I haven't found any issues using the CloudFlare provider, both additions and deletions work just fine.

{{<alert icon="lightbulb" cardColor="#097969" iconColor="#AFE1AF" textColor="#f1faee">}}
**TIP:** The list of supported providers and their relative stability levels can be found in the [documentation](https://kubernetes-sigs.github.io/external-dns/v0.14.2/#status-of-in-tree-providers).
{{</alert>}}

### Annotations

External-dns comes with a slew of annotations that allow you to customize the behavior of external-dns for every single service, some of the most used are probably:

- external-dns.alpha.kubernetes.io/ttl that specifies the time to live (TTL) of the DNS record
- external-dns.alpha.kubernetes.io/target that specifies the DNS record targets (more on this later on)

{{<alert icon="lightbulb" cardColor="#097969" iconColor="#AFE1AF" textColor="#f1faee">}}
**TIP:** The list of supported annotations can be found in the [documentation](https://kubernetes-sigs.github.io/external-dns/v0.14.2/annotations/annotations/).
{{</alert>}}

### Record ownership

To guarantee updates and deletions of external-dns created records, an ownership concept is implemented to make sure external-dns, there are various configurable mechanisms to implement this ownership mechanism, by default it uses a TXT record, but other options are for example to use AWS DynamoDB or AWS Service Discovery.

I stick with the default TXT configuration so you can see in your DNS provider which are the records created by external-dns.

## Troubleshooting

As I stated above, I ran into several issues while trying to setup external-dns, so I decided to document them here:

### failed to sync traefik.containo.us/v1alpha1, context deadline exceeded

This is the first issue I encountered as soon as I installed external-dns using `traefik-proxy` as a source, this was the error message:

```sh
time="2024-07-28T15:19:44Z" level=fatal msg="failed to sync traefik.containo.us/v1alpha1, Resource=ingressrouteudps: context deadline exceeded"
```

This issue has been solved by disabling the legacy Traefik source using the argument `--traefik-disable-legacy`

### Not Generating any records with Traefik IngressRoute

The second issue I found was the inability to generate any record at all when using Traefik IngressRoute as a source, the message found in the logs was the following:

```sh
time="2024-07-29T13:00:07Z" level=debug msg="Endpoints generated from service: demo-dns-site/nginx-service: []"
```

This was because my IngressRoute was missing the target annotation, such annotation specifies the IP or Hostname of the DNS target, if you omit this annotation, nothing will be generated.

In my wishful thinking, I was hoping that external-dns could resolve the Traefik service and use the external IP as a target but there's no relationship between the IngressRoute and the Traefik service, so external-dns explicitly requires you to specify a target annotation.

If the target is an IPv4, an A address is generated, if the target is an IPv6 an AAAA record is generated, otherwise the target is interpreted as a string and a CNAME is thus generated.

This annoyed me because it meant that the configuration had to be repeated on every IngressRoute, making it more difficult to change, especially in an environment that's mostly a test cluster. I decided then to look into the new Kubernetes networking resource, the Gateway.

### Gateway traefik/traefik-gateway has not accepted HTTPRoute demo-dns-site/nginx-service-http-route

Gateway is the new, improved version of the Ingress resource, the Gateway resource has to specify the parent Gateway controller and the Gateway controller is assigned an address section. This seems perfect to avoid duplication so I decided to replace the Traefik IngressRoute with a Gateway and immediately ran into the following error:

```sh
level=debug msg="Gateway traefik/traefik-gateway has not accepted HTTPRoute demo-dns-site/nginx-service-http-route"
```

The issue this time was related to Traefik, to resolve it I had to update the Traefik installation by adding the following to the values file:

```yml
gateway:
  listeners:
    web:
      namespacePolicy: All
    websecure: null # Do not install the websecure listenere for now     
```

For reference the complete values file for my latest working Traefik configuration is the following:

```yml
additionalArguments:
  - "--log.level=DEBUG"
  - "--global.sendanonymoususage=false"
# - "--providers.kubernetesgateway.statusaddress.ip=192.168.2.210"
  - "--providers.kubernetesgateway.statusaddress.service.name=traefik"
  - "--providers.kubernetesgateway.statusaddress.service.namespace=traefik"

deployment:
  enabled: true
  replicas: 1
  annotations: {}
  podAnnotations: {}
  additionalContainers: []
  initContainers: []

image:
  tag: 3.1.12

ports:
  web:
    redirectTo:
      port: websecure
      priority: 10
  websecure:
    http3:
      enabled: true
    advertisedPort: 4443
    tls:
      enabled: true

ingressRoute:
  dashboard:
    enabled: false

providers:
  kubernetesCRD:
    enabled: true
  kubernetesIngress:
    enabled: false
  kubernetesGateway:
    enabled: true

rbac:
  enabled: true

service:
  enabled: true
  type: LoadBalancer

gateway:
  listeners:
    web:
      namespacePolicy: All
    websecure: null
```

### Not Generating any records with HTTPRoute

As soon as the route acceptance issue was fixed after re-deploying Traefik, the new error was the good old: Hey I don't know what DNS records to create for this HTTPRoute 🤷‍♂️.

To troubleshoot this issue I went down a rabbit hole, I decided to clone both external-dns and Traefik and added some logging because, truth be told, external-dns with debug logging enabled is still not logging enough information to easily troubleshoot failures.

```sh
time="2024-08-07T06:07:39Z" level=debug msg="Endpoints generated from HTTPRoute demo-dns-site/nginx-service-http-route: [test.k8slab.app 0 IN A  192.168.2.210 []]"
```

While troubleshooting this issue I figured that my Gateway didn't get and address. That turned out to be related to some missing Traefik **static configuration**

Traefik's Gateway Address can be configured in 3 different ways:

- Using a fixed IP address
- Using a hostname
- Using a service reference

## Installation

I like helm chart to install Kubernetes applications/workload and external-dns provides a helm chart, so let's start by installing it:

1. Add the external-dns repo to Heml repos

    ```sh
    helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/
    helm repo update
    ```


## References

- [External-dns documentation](https://kubernetes-sigs.github.io/external-dns/v0.14.2/)
- [Traefik configuration overview](https://doc.traefik.io/traefik/getting-started/configuration-overview/)
- [Traefik Gateway provider configuration](https://doc.traefik.io/traefik/providers/kubernetes-gateway/#statusaddress)