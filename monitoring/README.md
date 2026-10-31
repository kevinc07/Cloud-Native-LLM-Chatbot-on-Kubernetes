# 監控:kube-prometheus-stack(Day 11)

Prometheus(抓指標)+ Grafana(畫圖)+ Alertmanager(告警)+ node-exporter / kube-state-metrics(提供資料來源),
一次用 Helm 裝在獨立的 `monitoring` namespace。

## 安裝

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

kubectl create namespace monitoring

# Grafana 管理員帳密:存在 cluster 的 Secret,不進 git
kubectl -n monitoring create secret generic grafana-admin \
  --from-literal=admin-user=admin \
  --from-literal=admin-password="$(openssl rand -base64 18)"

helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring -f monitoring/kube-prometheus-stack-values.yaml
```

## 開啟 Grafana

Grafana 沒有公開 IP,用 port-forward 連:

```bash
kubectl -n monitoring port-forward svc/monitoring-grafana 3001:80
# 瀏覽器開 http://localhost:3001
```

取得密碼:

```bash
kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d; echo
```
