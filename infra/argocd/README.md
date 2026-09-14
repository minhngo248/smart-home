# Argo CD ingress

Traefik terminates TLS and proxies plain HTTP to `argocd-server:80`.

```bash
kubectl apply -f infra/argocd/server-params.yaml
kubectl -n argo rollout restart deployment/argocd-server
kubectl apply -f infra/argocd/ingress.yaml
```

`argocd.local-pi` must resolve to Traefik's address. cert-manager creates the
`argocd-tls` secret using the existing `ca-homelab` issuer.
