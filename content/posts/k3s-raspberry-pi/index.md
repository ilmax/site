---
title: "Install k3s on a Raspberry PI"
date: 2024-07-01T18:55:40+02:00
draft: false
tags: ["Kubernetes", "homelab", "rpi", "tutorial"]
---

## Motivation

I recently bought a few Raspberry PI 5 SBCs to play around with Kubernetes at home and, without noticing, I started spending a lot of my free time playing around with it.

The initial set of features that I wanted to set up were the following:

- Multinode k8s Cluster
- Do not expose services to the internet
- Resolve my internal services via domain name
- Have free SSL certificates and certificate renewal

As we will soon see, even this limited set of features, requires a decent amount of work to configure, so this process is split into a mini-series of articles to keep them relatively short.

{{<alert icon="info-solid">}}
Please note that I'm not going through the O.S. installation and initial configuration in this article, like configuring ssh/static ip/etc
{{</alert>}}

## Installation of Kubernetes

### Why K3s

One of the more common distributions of Kubernetes that are installed on the Raspberry PI is K3s. K3s is a **certified** and **lightweight** distribution, it's also a goal of the project **not to diverge** from the main Kubernetes code, which makes it perfect for getting your hands dirty with Kubernetes on resource-constrained devices.

### OS & Packages updates

Let's first update all the installed packages and the kernel itself.

1. SSH into the Raspberry PI using either the `ssh user@hostname.domain` format (if you don't have a domain configured you can use the hostname.local, for me for example it's `pi-node-01.local`) or `ssh user@ip-address`
1. Update apt packages & OS using the following commands:

```sh
sudo apt-get update -y
sudo apt-get upgrade -y
sudo apt-get dist-upgrade -y
sudo apt --fix-broken install -y
sudo apt autoremove -y

# Reboot the system
sudo reboot
```

### Configure the kernel to enable cgroup v2

K3s requires cgroup v2 to function and, by default, they're disabled in the suggested Raspberry PI O.S. so we need to enable them as follows:

```sh
echo 'cgroup_memory=1 cgroup_enable=memory' | sudo tee -a /boot/firmware/cmdline.txt && sudo reboot
```

{{<alert>}}
Without memory cgroup v2 enabled, k3s will fail to start with the following error: `level=fatal msg="failed to find memory cgroup (v2)"`
{{</alert>}}

### Verify cgroup v2 is enabled

To verify that cgroup v2 is enabled we can run this command on the Raspberry PI:

```sh
pi-adm@pi-node-01:~$ grep cgroup /proc/filesystems

nodev   cgroup
nodev   cgroup2 <-- This tells us that cgroup v2 is enabled
```

## Master Node Installation

The first node that we will install is the master node, I'm calling this out because the install instruction is a tiny bit different between the master node and the worker nodes.

1. SSH into your Raspberry PI using `ssh user@hostname.domain` or `ssh user@ip-address`
1. Generate a random token, e.g. using OpenSSL

    ```sh
    export K3S_TOKEN=$(openssl rand -base64 20)
    ```

    TODO Explain what are those parameters
1. Prepare the K3s kubelet configuration file in `/etc/rancher/k3s/kubelet.config`

    ```yaml
    kubeconfig=/etc/rancher/k3s/kubelet.config
    sudo mkdir -p $(dirname $kubeconfig)
    sudo tee $kubeconfig >/dev/null <<EOF
    apiVersion: kubelet.config.k8s.io/v1beta1
    kind: KubeletConfiguration
    shutdownGracePeriod: 30s
    shutdownGracePeriodCriticalPods: 10s
    EOF
    ```

    This kubelet configuration enables the new kubernetes feature [Graceful Shutdown](https://kubernetes.io/docs/concepts/cluster-administration/node-shutdown/#graceful-node-shutdown) ensuring that the pod follows the normal [pod termination process](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination) during the node shutdown.

1. Install the K3S control plane node

```sh
curl -sfL https://get.k3s.io | K3S_TOKEN=$K3S_TOKEN sh -s - server \
--write-kubeconfig-mode '0644' --node-taint 'node-role.kubernetes.io/control-plane:NoSchedule' \
--disable 'servicelb' --disable 'traefik' --disable 'local-storage' \
--kube-controller-manager-arg 'bind-address=0.0.0.0' --kube-proxy-arg 'metrics-bind-address=0.0.0.0' \
--kube-scheduler-arg 'bind-address=0.0.0.0' --kubelet-arg 'config=/etc/rancher/k3s/kubelet.config' \
--kube-controller-manager-arg 'terminated-pod-gc-threshold=10'
```

{{<alert icon="info-solid" >}}
Please note that the argument `--node-taint...` tells Kubernetes not to schedule any pod on this node, if you want to schedule pods on the master node as well, remove that argument but bear in mind that's not the suggested approach. If you set up a single Kubernetes node though, you have to remove that argument.
{{</alert>}}

### Installation parameters

Let's now look at all the parameters that we specified in the command line:

- `-s server` Used to tell K3s to run in server mode (for master node) as opposed to agent mode (for worker nodes)
- `--write-kubeconfig-mode '0644'` Writes the kubeconfig file with the specified mode
- `--node-taint 'node-role.kubernetes.io/control-plane:NoSchedule'` Tells K3s to not schedule pods on the master node
- `--disable 'servicelb'` Do not install the built-in service load balancer (we will replace it with MetalLb later on)
- `--disable 'traefik'` Do not install Traefik, we will install it manually so we will have access to its configuration
- `--disable 'local-storage'` Disable local storage persistent volumes provider installed by K3s and use Longhorn instead
- `--kube-controller-manager-arg 'bind-address=0.0.0.0'` Bind on all addresses to enable metrics scraping from an external node
- `--kube-proxy-arg 'metrics-bind-address=0.0.0.0'` Bind on all addresses to enable metrics scraping from an external node
- `--kube-scheduler-arg 'bind-address=0.0.0.0'` Bind on all addresses to enable metrics scraping from an external node
- `--kubelet-arg 'config=/etc/rancher/k3s/kubelet.config'` Passes the file generated earlier to the kubelet process
- `--kube-controller-manager-arg 'terminated-pod-gc-threshold=3'` This setting limits to 3 the number of terminated pods that can exist before the terminated pod garbage collector starts deleting terminated pods. See [Pod Garbage collection](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-garbage-collection)

### Copy the kubeconfig files

To be able to connect to the cluster via the kubectl CLI, we need to copy the kubeconfig file in the default directory where the kubectl expects it:

```sh
 mkdir $HOME/.kube
 cp /etc/rancher/k3s/k3s.yaml $HOME/.kube/config
```

### Verify master node installation

If everything is configured correctly, from within the node we can check the status of the nodes as shown below:

```sh
kubectl get nodes
NAME                  STATUS   ROLES                  AGE    VERSION
pi-node-01            Ready    control-plane,master   20s   v1.29.5+k3s1
```

{{<alert icon="info-solid" >}}
To troubleshoot the installation you can look at the logs of the k3s service with `journalctl -u k3s` or `journalctl -xeu k3s.service`
{{</alert>}}

## Configure MetalLB

**TODO This is not the ingress controller, rewrite this paragraph.**

We will install MetalLB as our Ingress Controller to expose our k8s services to the outside of the cluster. In a cloud scenario, this role is usually taken care of by another service, for example for AKS you can use [AGIC](https://learn.microsoft.com/en-us/azure/application-gateway/ingress-controller-overview) that's using Azure Application Gateway as the ingress controller.
In our case, we need to expose the Ingress Controller using an IP address of the internal home network and MetalLB does exactly this for us.

MetalLB can be configured in two different modes:

- Layer 2 mode (where a single node gets all the traffic and then kube-proxy redirects to the service's pods)
- BGP mode (where each node establishes a BGP peering session with the network router and uses the peering session to advertise the IPs of external cluster services)

Both approaches have their pros and cons, in the layer 2 case, a single node can become a bottleneck while using BGP, if a node goes down, all active connections to the service will be terminated.
Since there's no clear winner here, I'm opting for using the layer 2 approach.

{{<alert>}}
You can look at the limitation for [layer 2 mode](https://metallb.universe.tf/concepts/layer2/#limitations) or the [BGP mode](https://metallb.universe.tf/concepts/bgp/#limitations) on the MetalLB documentation
{{</alert>}}

Logically we need to reserve some IP in your DHCP configuration so that there won't be other appliances with the same IP on the network. You should be able to configure your router to reserve some IP addresses, and then you can use those IP addresses in a Metallb `AddressPool`.

1. Install Metallb via kubectl apply

    ```sh
    kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.3/config/manifests/metallb-native.yaml
    ```

1. Create a file called `metallb.yml` and place the following content there:

   ```yml
   ---
   apiVersion: metallb.io/v1beta1
   kind: IPAddressPool
   metadata:
     name: k3s-lb-pool
     namespace: metallb-system
   spec:
     addresses:
     ## Replace this with your IP address reserved range. 
     ## This should be on the same network as your nodes!
     - 192.168.2.150-192.168.2.200 
   ---
   apiVersion: metallb.io/v1beta1
   kind: L2Advertisement
   metadata:
     name: k3s-lb-pool
     namespace: metallb-system
   ```

### Configuring the WiFI interface

If you connect the Raspberry PI to the network via ethernet, you can safely skip this step.

If you connect the Raspberry PI to the network via WiFi, you need to also change the configuration of the WiFi interface to make sure MetalLB works properly, you can see this in the product [documentation](https://metallb.universe.tf/troubleshooting/#using-wifi-and-can-t-reach-the-service).

> You can configure the interface (most likely called wlan0) with the following command: `sudo ifconfig <device> promisc`

{{<alert>}}
**Bear in mind that this configuration doesn't survive the node restart**
{{</alert>}}

### Make interface configuration persistent

If you want to make the configuration persistent, we need to implement a bit of a workaround using a service that starts after the network service comes online, and executes our command `ifconfig wlan0 promisc`

Here below you can see the code for such a service:

```sh
sudo bash -c 'cat > /etc/systemd/system/bridge-promisc.service' <<EOS
[Unit]
Description=Makes interfaces run in promiscuous mode at boot
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/ifconfig wlan0 promisc
TimeoutStartSec=0
RemainAfterExit=yes

[Install]
WantedBy=default.target
EOS

sudo systemctl enable bridge-promisc
```

### Verify MetalLB installation

To ensure the successful installation of MetalLB we can deploy a temporary service (for example an nginx image) and make sure it successfully gets assigned an external IP address.

```sh
kubectl create namespace test-metallb
kubectl create deployment nginx --image=nginx -n test-metallb
kubectl expose deployment nginx --type=LoadBalancer --name=nginx --port=80 --protocol=TCP -n test-metallb
```

After the deployment succeeds, we need to check if the newly created service gets an external IP address via:

```sh
kubectl get service -n test-metallb
NAME    TYPE           CLUSTER-IP      EXTERNAL-IP     PORT(S)        AGE
nginx   LoadBalancer   10.43.247.187   192.168.2.150   80:30129/TCP   13s
```

After navigating to the exposed IP address in the browser, we can now safely remove this test namespace via:

```sh
kubectl delete namespace test-metallb
```

## Install Traefik