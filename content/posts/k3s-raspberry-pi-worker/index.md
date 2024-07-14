---
title: "Install k3s on a Raspberry PI - Worker node"
date: 2024-07-12T09:23:18+02:00
draft: true
series: ["K3s on Raspberry PI"]
series_order: 2
tags: ["Kubernetes", "homelab", "rpi", "tutorial"]
---

In the last article of this mini-series, we configured the master node and kubectl on our PC, now it's time to configure the worker nodes and join them to the cluster, here's the final state with my hostnames and IPs:

{{<figure src="k3scluster.svg" alt="The K3s multinode cluster" caption="*The diagram of the K3s multinode cluster*" nozoom=true >}}

## Operating System Preparation

Similar to the previous article, we will go through some basic O.S. configuration and then start the installation of K3s on the new node. Since those steps were already explained in the first post of the series, I will only show the relevant command to execute, if you want to read a bit more, you can go back the the first article of the series.

### OS & Packages updates

1. SSH into the Raspberry PI using either the `ssh user@hostname.domain` format (if you don’t have a domain configured you can use the `hostname.local`, for me for example it’s `ssh pi-node-02.local`) or `ssh user@ip-address`
1. Update apt packages & OS using the following commands:

    ```sh
    sudo apt-get update -y
    sudo apt-get upgrade -y
    sudo apt-get dist-upgrade -y
    sudo apt --fix-broken install -y
    sudo apt autoremove -y
    ```

{{<alert icon="info-solid">}}
More information on what is the **local** domain and how it works can be found [here](https://en.wikipedia.org/wiki/.local)
{{</alert>}}

### Configure a static IP on the Raspberry PI
 
```sh
sudo nmcli con mod preconfigured ipv4.method manual ipv4.addr 192.168.2.202/24 ipv4.gateway 192.168.2.254 ipv4.dns 192.168.2.59
sudo reboot
```

### Configure the kernel to enable cgroup v2

```sh
echo ' cgroup_memory=1 cgroup_enable=memory' | sudo tee -a /boot/firmware/cmdline.txt 
sudo reboot
```

### Verify cgroup v2 is enabled

```sh
pi-adm@pi-node-02:~$ grep cgroup /proc/filesystems

nodev   cgroup
nodev   cgroup2 <-- This tells us that cgroup v2 is enabled
```

## Worker node installation

The worker node installation is similar to the master node one, we still have to run the k3s install script, but we will change some parameters, we need to tell K3s that's going to act as a worker and what the master node IP is, let's see how here below:

1. SSH into your Raspberry PI master node using `ssh user@hostname.domain` or `ssh user@ip-address`
1. Copy the master node token using the following command:

    ```sh
    sudo cat /var/lib/rancher/k3s/server/node-token
    ```

1. SSH into the worker node using `ssh user@hostname.domain` or `ssh user@ip-address`
1. Prepare K3s kubelet configuration file in `/etc/rancher/k3s/kubelet.config`

    ```sh
    kubeconfig=/etc/rancher/k3s/kubelet.config
    sudo mkdir -p $(dirname $kubeconfig)
    sudo tee $kubeconfig >/dev/null <<EOF
    apiVersion: kubelet.config.k8s.io/v1beta1
    kind: KubeletConfiguration
    shutdownGracePeriod: 30s
    shutdownGracePeriodCriticalPods: 10s
    EOF
    ```

1. Set the variable NODE_TOKEN with the value of the node token copied from the server in step 2

    ```sh
    export NODE_TOKEN=K10....
    ```

1. Set the variable MASTER_IP with the IP of the master node

    ```sh
    export MASTER_IP=192.168.2.201
    ```

1. SSH Into the worker host and Install k3s using the command below:

    ```sh
    curl -sfL https://get.k3s.io | K3S_URL=https://$MASTER_IP:6443 \
    K3S_TOKEN=$NODE_TOKEN sh -s - --node-label 'node_type=worker' \
    --kubelet-arg 'config=/etc/rancher/k3s/kubelet.config' \
    --kube-proxy-arg 'metrics-bind-address=0.0.0.0'
    ```

### Installation Parameters

Let’s now look at all the parameters that we specified in the command line:

- `K3S_URL` Is used to specify the address of the master node, this also assumes it's an agent installation (as opposed to a server one)
- `K3S_TOKEN` This is the token we copied from the K3s master node that will be used by k3s to join the cluster
- `--node-label 'node_type=worker'` This is a random label that we add to the node, label name and value are completely up to you, can be omitted
- `--kubelet-arg 'config=/etc/rancher/k3s/kubelet.config'` Specify the position of the kubelet config file (the one we generated in the previous step)
- `--kube-proxy-arg 'metrics-bind-address=0.0.0.0'` Bind on all addresses to enable metrics scraping from an external node

### Verify worker node installation

If everything is configured correctly, from our machine we should now be able to see the new node added to our cluster:

```sh
kubectl get nodes
NAME                  STATUS   ROLES                  AGE    VERSION
pi-node-01            Ready    control-plane,master   20m   v1.29.5+k3s1
pi-node-02            Ready    <none>                 20s   v1.29.5+k3s1
```

If you are like me and want to change the `<none>` role to correctly be a worker, we can run the following command:

```sh
kubectl label node pi-node-02 kubernetes.io/role=worker
```

{{<alert>}}
Please note that's not possible to specify the label `kubernetes.io/role=worker` at K3s installation time using the parameter `--node-label` Installation will result in an error, thus we have to manually label the node after the installation
{{</alert>}}

## Lens Metrics

If you're using [Lens](https://k8slens.dev/), the Kubernetes GUI, you can configure the metrics displayed in the cluster overview page to display information about your cluster, like memory usage and CPU usage as shown in the picture below:

{{<figure src="lens.png" alt="Lens cluster metrics" caption="*The cluster metrics displayed by Lens*" nozoom=true >}}

1. Installing Prometheus
1. Configure lens metrics to use Helm
1. Specify the Prometheus service address

```sh
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/prometheus --namespace monitoring --create-namespace
```

In Lens, from the catalog, go to the cluster setting -> Metrics and set the Prometheus service address to `monitoring/prometheus-server:80`

## Conclusions

That's all it takes to add a K3s node to an existing cluster, if you have multiple nodes, you can simply repeat those steps multiple times.
So far we installed a multinode cluster, but haven't implemented any of the features discussed in the first post, in the next post of the series though we will start to implement those capabilities.

See you in the next post!

*Hero Image generated by Bing Copilot*