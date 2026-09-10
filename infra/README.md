# Step of installing on Pi
- Install Pi OS then flash into microSD
- Set PasswordAuthentication of sshd_config to `no`
- Install ufw, then allow port 22 and port 6443
- Install k3s (remember to allow cgroup then reboot)

# Install Mosquitto on K8s
## Self-signed certificate
- `allow_anonymous true`

```bash
# Publisher
docker run --rm -v ./certs/ca.crt:/ca.crt eclipse-mosquitto   mosquitto_pub -h local-pi -p 30883 --cafile /ca.crt -t /home/office/light -m "off"

# Subscriber
docker run --rm -v ./certs/ca.crt:/ca.crt eclipse-mosquitto   mosquitto_sub -h local-pi -p 30883 --cafile /ca.crt -t /home/office/light -v
```

# CPU Temp
```bash
vcgencmd measure_temp

# Max speed fan
sudo pinctrl set 45 a0

# Then reboot, fan will return to normal speed
sudo reboot
```

# Monitor Pi host from inside k3s
This installs Prometheus, Grafana, and node-exporter. It collects the Pi's CPU,
memory, filesystem, and network metrics. Kubernetes object metrics and
workload scraping are disabled for now.

Check that the k3s local storage class exists:

```bash
kubectl get storageclass local-path
```

Install Helm if it is not already available, then install the chart:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
kubectl create namespace monitoring

helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
	--namespace monitoring \
	--values infra/monitoring/prometheus-values.yaml
```

Wait for the workloads:

```bash
kubectl get pods -n monitoring -w
```

Confirm that node-exporter is running and that Prometheus is scraping it:

```bash
kubectl get pod -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090
```

Open `http://localhost:9090/targets` and check that the node-exporter target is
UP. Then expose Grafana temporarily through port-forwarding:

```bash
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
```

Open `http://localhost:3000`. The Grafana admin password can be retrieved with:

```bash
kubectl get secret -n monitoring monitoring-grafana \
	-o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Add the Grafana dashboard with ID `1860` (Node Exporter Full). It includes CPU,
memory, filesystem, network, load, and uptime panels for the Pi.

Useful checks from the Pi itself:

```bash
kubectl get pvc -n monitoring
kubectl top node
kubectl get --raw='/api/v1/nodes' >/dev/null && echo 'k3s API is responding'
```

The Prometheus data is retained for seven days. Grafana uses a 1 GiB PVC and
Prometheus uses a 2 GiB PVC through k3s's `local-path` storage class.
