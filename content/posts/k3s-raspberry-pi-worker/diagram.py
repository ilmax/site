from diagrams import Cluster, Diagram, Edge
from diagrams.k8s.infra import Master, Node

graph_attr = {
    "bgcolor": "transparent",
    "fontsize": "20",
    "margin":"-2, -2",
}
cluster_attr = {"fontsize": "14"}
node_attr = {"fontsize": "14"}

with Diagram("", direction="TB", show=False, graph_attr=graph_attr, node_attr=node_attr, filename="k3scluster"):
    with Cluster("K3s Cluster", graph_attr=cluster_attr):
        master = Master("pi-node-01\n192.168.2.201")
        node1  = Node("pi-node-02\n192.168.2.202")
        node2  = Node("pi-node-03\n192.168.2.203")

        master - Edge() - [node1, node2]