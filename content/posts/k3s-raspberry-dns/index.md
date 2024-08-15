---
title: "Install K3s on a Raspberry PI - Automatic external DNS management"
description: How to use ExternalDNS to automatically synchronize DNS record with CloudFlare or any other DNS provider
date: 2024-08-05T21:11:10+02:00
draft: true
series: ["K3s on Raspberry PI"]
series_order: 4
tags: ["Kubernetes", "homelab", "rpi", "tutorial"]
---

ExternalDNS is used to automate DNS management using Kubernetes resources to build DNS records and synchronize the changes with your DNS provider. Its goal is defined as:

{{<lead>}}
ExternalDNS synchronizes exposed Kubernetes Services and Ingresses with DNS providers
{{</lead>}}

Automating DNS management helps to make sure we don't have to create DNS entries whenever we deploy a new service or that we don't leave [dangling DNS records](https://www.paloaltonetworks.com/cyberpedia/what-is-a-dangling-dns) whenever we delete an exposed service.

This allows us to simply deploy a new service in Kubernetes, add the required annotations and have the DNS record automatically created for us, so that we can resolve the service hostname without any additional manual work.

The idea is that ExternalDNS watches some resources (e.g. `Ingress`, `Service`, `IngressRoute`, etc) and takes care of keeping our DNS provider in sync, seems simple enough right?

Actually to get this working it took me way more time than I want to admit, so I decided to document how I configured ExternalDNS and the result I got. Without further ado, let's dive into it.

## Concepts

ExternalDNS generates DNS records from exposed Kubernetes **sources** that will then be synchronized with DNS **providers**.

{{<figure src="flowchart.svg" alt="ExternalDNS conceptual processing flow" caption="*Simplified conceptual processing logic of ExternalDNS*">}}

### Sources

ExternalDNS can monitor several different types of Kubernetes resources used to expose an application, among the supported ones we can find `Ingress`, `Services`, Gateway and also Traefik's own `IngressRoute` (the one we used in the preceding blog posts).

The source is the resource type ExternalDNS watches for changes and is the one used to construct the DNS records that will be then synched in the DNS provider.

{{<tip>}}
The list of supported sources can be found in the [documentation](https://kubernetes-sigs.github.io/external-dns/v0.14.2/sources/sources/).
{{</tip>}}

### Providers

A provider identifies the external service where your DNS zone lives, that's where ExternalDNS synchronizes the DNS records.
There are a lot of supported providers with different stability levels, the one I'm interested in, CloudFlare, has a **beta** stability level which is defined as:

> **Beta**: Community supported, well tested, but maintainers have no access to resources to execute integration tests on the real platform and/or are not using it in production.

So far I haven't found any issues using the CloudFlare provider, both additions and deletions work just fine.

{{<tip>}}
The list of supported providers and their relative stability levels can be found in the [documentation](https://kubernetes-sigs.github.io/external-dns/v0.14.2/#status-of-in-tree-providers).
{{</tip>}}

### Annotations

ExternalDNS comes with a slew of annotations that allow you to customize its behavior for every single service, some of the most used are probably:

- **external-dns.alpha.kubernetes.io/ttl** that specifies the time to live (TTL) of the DNS record
- **external-dns.alpha.kubernetes.io/target** that specifies the DNS record targets (Its usage will be covered in the [Recipes](#recipes) section)

{{<tip>}}
The list of supported annotations can be found in the [documentation](https://kubernetes-sigs.github.io/external-dns/v0.14.2/annotations/annotations/).
{{</tip>}}

### Record ownership

To guarantee updates and deletions of only ExternalDNS created records, ExternalDNS uses an ownership concept. There are various configurable mechanisms to implement this ownership mechanism. By default, a TXT record is used, but other available options are for example AWS DynamoDB or AWS Service Discovery.
This ownership has been implemented to make sure ExternalDNS won't modify/delete any of the other DNS records present in the same DNS zone.

I will stick with the default TXT configuration because it doesn't require any other service running and it also allows me to quickly see, in my DNS provider, which records are created by ExternalDNS and which ones aren't.

## Installation

### ExternalDNS

ExternalDNS needs to talk to a DNS provider, in my case CloudFlare, so it needs a way to authenticate to the DNS provider API, or more simply put an API access token. How to get such an access token is different for each provider, ExternalDNS [documentation](https://kubernetes-sigs.github.io/external-dns/v0.14.2/tutorials/cloudflare/) can help create the access token for your DNS provider of choice.

With the API access token created, now we have to create a Kubernetes secret:

```sh
kubectl create namespace external-dns-system
kubectl create secret generic cloudflare-api-key --from-literal=apiKey=replace_this_with_your_secret -n external-dns-system
```

I like Helm Charts to install Kubernetes applications/workloads and ExternalDNS provides one, so let's use it!

1. Add the ExternalDNS repo to Heml repos

    ```sh
    helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/
    helm repo update
    ```

1. Create a values file for ExternalDNS called external-dns-values.yml and paste the following markup:

    ```yml
    provider:
      name: cloudflare                # This is the name of your DNS provider
    env:
      - name: CF_API_TOKEN            # This is the environment variable where ExternalDNS expects to find the access token, varies by provider so if you're not using CloudFlare, make sure you check the documentation
        valueFrom:
          secretKeyRef:
            name: cloudflare-api-key  # This should have the same name of the secret created above
            key: apiKey

    extraArgs:
      - --zone-id-filter=zone_id_here # This is useful if you have multiple zones (domains) in the same DNS provider, so ExternalDNS only monitors one
      - --trafik-disable-leegacy      # Disable listeners on Resources under traefik.containo.us

    sources:                          # I'm using the Gateway, Service and Traefik as a sources, default is ingress and services only
      - gateway-httproute             # This is to analyze the Gateway HTTPRoute
      - traefik-proxy                 # This is to analyze Traefik's IngressRoute
      - service

    txtOwnerId: external-dns          # The value used to check records ownership with the standard ownership mechanism, TXT records

    policy: sync                      # How DNS records are synchronized between sources and providers; available values are `sync` & `upsert-only`. upsert-only doesn't delete records

    # logLevel: debug                 # Uncomment this one to get a bit more logging, but don't get your hopes up, it's not nearly verbose enough...
    ```

### Traefik & Gateway API

This article is long enough that I won't go into details about what the Gateway API is and why it's a good option to evaluate it, this will be the argument of a future post. For now, we just install it and configure it to test ExternalDNS support.

If you haven't done so, you need to install the custom CRDs before using the Gateway resource in Kubernetes, you can install the latest iteration of those CRDs (1.1.0 at the time of writing) using this command:

```sh
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/experimental-install.yaml
```

{{<note>}}
I won't configure TLS with the Gateway for now because I haven't yet figure out how it works, I'd like to configure a different certificate for every site, but it seems to me that, at the moment, you either use a single TLS certificate with all the hostnames at the gateway controller level, or you have to use TLSRoute that's still in the experimental channel at the time of writing (August 2024)
{{</note>}}

Traefik installation also needs to be updated to enable the kubernetesGateway provider, specify which namespaces are allowed to associate routes to the gateway and specify what the Gateway's address is using one of the supported ways. I'm using a service reference.

Traefik's Gateway Address can be configured in 3 different ways:

- Using a fixed IP address
- Using a hostname
- Using a service reference

{{<tip>}}
You can dig deeper in the Traefik's [documentation](https://doc.traefik.io/traefik/providers/kubernetes-gateway/#statusaddress)
{{</tip>}}

```yml
# I've added a comment to all the changed 
# configuration values with an explanation
additionalArguments:
  # Sets logging level
  - "--log.level=DEBUG"
  # Opt out of telemetry
  - "--global.sendanonymoususage=false"
  # This is the name of the Traefik service
  - "--providers.kubernetesgateway.statusaddress.service.name=traefik"
  # This is the namespace of the Traefik service
  - "--providers.kubernetesgateway.statusaddress.service.namespace=traefik"

deployment:
  enabled: true
  replicas: 1

image:
  tag: 3.1.2

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
    enabled: true         # Enable the Gateway provider

rbac:
  enabled: true

service:
  enabled: true
  type: LoadBalancer

gateway:
  listeners:
    web:
      namespacePolicy: All  # Allow association for the web listener from all namespaces
    websecure: null         # Do not enable the HTTPS listener, due to the reason explained above
```

## Recipes

Now that we have installed and configured everything, we should be able to deploy a test website, wait a few minutes for ExternalDNS to do its job, and be able to resolve the service hostname with our cluster Traefik ingress controller service.

My test deployment is the classic NGINX website, exposed in different ways, I've verified the current setup works with the:

- Service type=LoadBalancer
- Traefik IngressRoute
- Gateway HTTPRoute

Here's the invariant part of the manifest, it's just a namespace and the NGINX deployment:

```yml
---
apiVersion: v1
kind: Namespace
metadata:
  name: demo-dns-site
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
  namespace: demo-dns-site
spec:
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - image: nginx
        name: nginx
        ports:
        - containerPort: 80
---
# Paste the remainder of the configuration here below based on the 
# chosen approach and apply using kubectl apply -f
```

Below you can find the manifest for each of the configurations I tested, copy and paste the configuration into the manifest of the service:

### Service - A record

```yml
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
  namespace: demo-dns-site
  annotations:
    external-dns.alpha.kubernetes.io/hostname: test.k8slab.app # This tells ExternalDNS which hostname to create
    external-dns.alpha.kubernetes.io/ttl: 300                  # This tells ExternalDNS what TTL to use on the DNS record
spec:
  type: LoadBalancer                                           # This tells kubernetes to expose the service to be externally accessible, MetalLB provides the IP address
  selector:
    app: nginx
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
```

The created DNS record looks like this:

```console
Type    Name                Content
A       test.k8slab.app     192.168.2.210
```

### Service - CNAME record

```yml
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
  namespace: demo-dns-site
  annotations:
    external-dns.alpha.kubernetes.io/target: k8slab.app        # This tells ExternalDNS which is the target of the hostname
    external-dns.alpha.kubernetes.io/hostname: test.k8slab.app # This tells ExternalDNS which hostname to create
    external-dns.alpha.kubernetes.io/ttl: 300                  # This tells ExternalDNS what TTL to use on the DNS record
spec:
  type: LoadBalancer                                           # This tells kubernetes to expose the service to be externally accessible, MetalLB provides the IP address
  selector:
    app: nginx
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
```

The created DNS record looks like this:

```console
Type    Name                Content
CNAME   test.k8slab.app     k8slab.app
```

### IngressRote - A record

```yml
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
  namespace: demo-dns-site
spec:
  selector:
    app: nginx
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: nginx-ingress-secure
  namespace: demo-dns-site
  annotations:
    external-dns.alpha.kubernetes.io/target: 192.168.2.210  # This tells ExternalDNS which is the target of the hostname
    external-dns.alpha.kubernetes.io/ttl: "300"             # This tells ExternalDNS what TTL to use on the DNS record
spec:
  entryPoints:
  - web
  - websecure
  routes:
  - match: Host(`test.k8slab.app`)                          # This tells ExternalDNS which hostname to create
    kind: Rule
    services:
    - name: nginx-service
      port: 80
```

The created DNS record looks like this:

```console
Type    Name                Content
A       test.k8slab.app     192.168.2.210
```

### IngressRoute - CNAME record

```yml
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
  namespace: demo-dns-site
spec:
  selector:
    app: nginx
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: nginx-ingress-secure
  namespace: demo-dns-site
  annotations:
    external-dns.alpha.kubernetes.io/target: k8slab.app     # This tells ExternalDNS which is the target of the hostname
    external-dns.alpha.kubernetes.io/ttl: "300"             # This tells ExternalDNS what TTL to use on the DNS record
spec:
  entryPoints:
  - web
  - websecure
  routes:
  - match: Host(`test.k8slab.app`)                          # This tells ExternalDNS which hostname to create
    kind: Rule
    services:
    - name: nginx-service
      port: 80
```

The created DNS record looks like this:

```console
Type    Name                Content
CNAME   test.k8slab.app     k8slab.app
```

### Gateway HTTPRoute - A record

```yml
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
  namespace: demo-dns-site
spec:
  selector:
    app: nginx
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: nginx-service-http-route
  namespace: demo-dns-site
spec:
  parentRefs:   # This references the Traefik Gateway
    - name: traefik-gateway
      namespace: traefik

  hostnames:    # This specifies the hostname, same as Host(``) in IngressRoute
    - "test.k8slab.app"

  rules:
     - matches:
        - path:
            type: PathPrefix
            value: /

       backendRefs: # This specifies the target service
        - name: nginx-service
          namespace: demo-dns-site
          port: 80
```

Essentially when using a `Service` or `IngressRoute` you can decide to create an A record or a CNAME one, what you will choose depends on your configuration, in my case, I went with an A record that points to the Traefik service external IP, in my case I can pick the approach I like best because they're pretty much equivalent for my simple use case.

## Troubleshooting

As I stated above, I ran into several issues while trying to set up ExternalDNS, so I decided to document them here:

### Failed to sync traefik.containo.us/v1alpha1, context deadline exceeded

This is the first issue I encountered as soon as I installed ExternalDNS using `traefik-proxy` as a source, this was the error message:

```sh
time="2024-07-28T15:19:44Z" level=fatal msg="failed to sync traefik.containo.us/v1alpha1, Resource=ingressrouteudps: context deadline exceeded"
```

This issue has been solved by disabling the legacy Traefik source using the argument `--traefik-disable-legacy` as explained [here](https://github.com/kubernetes-sigs/external-dns/blob/master/docs/tutorials/traefik-proxy.md#disabling-resource-listeners).

### No records are created for a Traefik IngressRoute

The second issue I found was the inability to generate any record at all when using Traefik `IngressRoute` as a source, the message found in the logs was the following:

```sh
time="2024-07-29T13:00:07Z" level=debug msg="Endpoints generated from service: demo-dns-site/nginx-service: []"
```

This was because my `IngressRoute` was missing the target annotation, such annotation specifies the IP or Hostname of the DNS target, if you omit this annotation, nothing will be generated.

In my wishful thinking, I was hoping that ExternalDNS could resolve the Traefik service and use the external IP as a target but there's no relationship between the `IngressRoute` and the Traefik service, so ExternalDNS explicitly requires you to specify a target annotation.

If the target is an IPv4, an A address is generated, if the target is an IPv6 an AAAA record is generated, otherwise the target is interpreted as a string and a CNAME is thus generated.

This annoyed me because it meant that the configuration had to be repeated on every `IngressRoute`, making it more difficult to change, especially in an environment that's mostly a test cluster. I decided then to look into the new Kubernetes networking resource, the Gateway.

### Gateway traefik/traefik-gateway has not accepted HTTPRoute demo-dns-site/nginx-service-http-route

The Gateway API is a new and improved version of the old `Ingress` resource, this was to unify the configuration across the various implementations. Since the `Ingress` resource has a limited configuration area, all the implementations (NGINX, Traefik, Kong, Envoy, etc) came up with different annotations to implement specific functionality.
The Gateway resource is the response to this fragmentation, it allows you to specify a lot more behaviors in a vendor-agnostic way, so it's a welcome addition.

The Gateway resources, `HTTPRoute` and `GRPCRoute` resources have to specify the parent Gateway controller instance. A Gateway controller is in turn assigned an address. This seems perfect to avoid duplication I was facing with the `IngressRoute` option so I decided to replace the Traefik `IngressRoute` with a Gateway `HTTPRoute` and immediately ran into the following error:

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

### No records are created for an HTTPRoute

As soon as the route acceptance issue was fixed after re-deploying Traefik, the new error was the good old: Hey I don't know what DNS records to create for this `HTTPRoute` 🤷‍♂️.

To troubleshoot this issue I went down a rabbit hole, I decided to clone both ExternalDNS and Traefik and added some logging because, truth be told, ExternalDNS with debug logging enabled is still not logging enough information to easily troubleshoot failures.

```sh
time="2024-08-07T06:07:39Z" level=debug msg="Endpoints generated from HTTPRoute demo-dns-site/nginx-service-http-route: []"
```

While troubleshooting this issue I figured that my Gateway didn't get an address. That turned out to be related to some missing Traefik **static configuration**

As shown earlier, Traefik's Gateway Address can be configured in 3 different ways:

- Using a fixed IP address
- Using a hostname
- Using a service reference

But none of them worked, after a deeper investigation, it turned out to be a recently introduced issue in Traefik itself that I [reported](https://github.com/traefik/traefik/pull/10940#discussion_r1702623183) and got promptly fixed [the day after](https://github.com/traefik/traefik/pull/10972). Good job Traefik Labs! The fix has been released in versions 3.1.2 and 2.11.7.

## References

- [ExternalDNS documentation](https://kubernetes-sigs.github.io/external-dns/v0.14.2/)
- [Traefik configuration overview](https://doc.traefik.io/traefik/getting-started/configuration-overview/)
- [Traefik Gateway provider configuration](https://doc.traefik.io/traefik/providers/kubernetes-gateway/#statusaddress)

## Conclusion

As you can see this was not as straightforward as expected, but in the end we managed to configure ExternalDNS and have it sync our DNS records correctly.

Together with cert-manager, ExternalDNS allows us to completely automate the DNS management, allowing us to programmatically define, via Kubernetes manifests, the DNS configuration and the TLS certificate for our cluster, that's pretty neat and handy if you ask me.

One more step in our homelab journey automation!

Till the next time.
