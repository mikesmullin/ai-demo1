# Setup Guide

## Quick start

```bash
# 1. One-time: copy the secret template and fill in your Azure API key
cp k8s/secrets/azure-ai-foundry-apikey.yaml.example \
   k8s/secrets/azure-ai-foundry-apikey.yaml
# edit the file — replace <YOUR_AZURE_API_KEY> with your key

# 2. Create the cluster, install everything, run tests
make restart
make test
```

That's it. The sections below explain what each step does and why, so
you can troubleshoot or adapt the setup. The Makefile is the authoritative
source of commands — the steps here describe intent, not copy-paste recipes.

## Prerequisites

Install these tools before running `make`:

| Tool | Minimum Version | Install (Arch Linux) |
|------|----------------|----------------------|
| Podman | 5.x | `sudo pacman -S podman` |
| KIND | 0.31+ | `go install sigs.k8s.io/kind@latest` |
| Helm | 3.17+ | `sudo pacman -S helm` |
| kubectl | 1.35+ | `sudo pacman -S kubectl` |
| Azure CLI | 2.85+ | `sudo pacman -S azure-cli` |

You also need:
- An Azure AI Foundry resource with a deployed model (see next section).
- Network access to `*.services.ai.azure.com` on port 443.

## 1. Azure AI Foundry Setup (one-time, manual)

This is the only step not automated by `make` — it provisions cloud
infrastructure that persists across cluster rebuilds.

```bash
az login

az group create --name rg-myteam --location centralus

az cognitiveservices account create \
  --name my-ai-resource \
  --resource-group rg-myteam \
  --location centralus \
  --kind CognitiveServices \
  --sku S0

az cognitiveservices account deployment create \
  --name my-ai-resource \
  --resource-group rg-myteam \
  --deployment-name gpt-5.1 \
  --model-name gpt-5.1 \
  --model-version 2025-11-13 \
  --model-format OpenAI \
  --sku-capacity 1 \
  --sku-name GlobalStandard
```

Record the **hostname** and **API key** — you'll put them in
`k8s/secrets/azure-ai-foundry-apikey.yaml` and `k8s/azure-ai-foundry.yaml`.
See [AZ_CLI.md](AZ_CLI.md) for the full setup and teardown reference.

## 2. What `make up` does

`make up` runs four targets in order:

### `make cluster`
Creates the KIND cluster from `k8s/kind-cluster.yaml`. KIND runs inside
rootless Podman and requires delegated cgroups (`systemd-run --scope`).
Port mappings 30080 (Envoy), 30200 (chat-front2-ui), and 30300 (oauth-idp)
are forwarded from the host.

### `make install`
Installs three Helm charts, then applies the base gateway manifests:

1. **`eg` — Envoy Gateway** (controller + Gateway API CRDs)
   Installed with `-f k8s/eg-values.yaml`, which enables three required settings:

   | Setting | Why |
   |---------|-----|
   | `extensionManager` | Registers the AI Gateway controller as Envoy Gateway's xDS translation hook — without this, `AIGatewayRoute` and `MCPRoute` are silently ignored |
   | `enableBackend: true` | Required for `Backend` resources (Azure FQDN endpoint) |
   | `enableEnvoyPatchPolicy: true` | Required for `EnvoyPatchPolicy` (HTTP/1.1 upstream workaround) |

2. **`aieg-crd` — AI Gateway CRDs** (`AIGatewayRoute`, `MCPRoute`, etc.)

3. **`aieg` — AI Gateway controller**

4. **`k8s/base-gateway.yaml`** — `GatewayClass`, `Gateway`, `EnvoyProxy`,
   `ClientTrafficPolicy`. The `EnvoyProxy` resource uses a `JSONMerge`
   patch on `envoyService` to declaratively pin the NodePort to 30080,
   matching the KIND port mapping.

### `make images`
Builds `mcp-server` and `oauth-idp` with Podman, saves them as tarballs,
and loads them into the KIND node with `kind load image-archive`. These
images are not pushed to any registry — they live only in the local KIND
cluster.

### `make apply`
Applies all remaining Kubernetes manifests in dependency order:
- Azure API key secret (from the gitignored `k8s/secrets/` directory)
- `k8s/azure-ai-foundry.yaml` — `AIGatewayRoute`, `AIServiceBackend`,
  `BackendSecurityPolicy`, `Backend`, `BackendTLSPolicy`
- `k8s/envoy-patch-alpn.yaml` — `EnvoyPatchPolicy` forcing HTTP/1.1
  upstream (workaround for Azure + AI Gateway ext_proc protocol error)
- `k8s/mcp-server.yaml` + `k8s/mcp-route.yaml` — MCP tool server and
  its `MCPRoute` (triggers an Envoy pod rollout to inject the MCP sidecar)
- `k8s/oauth-idp.yaml` — mock JWT identity provider (not for production)
- `k8s/security-policy-jwt.yaml` — `SecurityPolicy` enforcing Bearer JWT
  on all incoming requests

`make apply` waits for all deployments to roll out, including the
MCPRoute-triggered Envoy pod rollout and a readiness poll on the MCP
proxy endpoint before returning.

## Troubleshooting

### Routes accepted but inference/MCP returns 502 or 503

The most likely cause: `eg` was installed without `-f k8s/eg-values.yaml`.
Without that file the AI Gateway controller's xDS hooks are not registered,
so routes are accepted by the Kubernetes API but never programmed into Envoy.

Fix: `make restart`.

### `upstream_reset_before_response_started{protocol_error}`

The `EnvoyPatchPolicy` in `k8s/envoy-patch-alpn.yaml` is not programmed.
Check: `kubectl get envoypatchpolicy azure-force-alpn` — both `ACCEPTED`
and `PROGRAMMED` should be `True`.

### NodePort not reachable

KIND only exposes ports listed in `k8s/kind-cluster.yaml`. Verify the
Envoy service is on 30080:

```bash
kubectl get svc -n envoy-gateway-system | grep ai-gw-lab
# Should show 80:30080/TCP
```

If not, the declarative NodePort patch in `base-gateway.yaml` may not
have applied. Run `make restart` to rebuild from scratch.

### Pods stuck in `Pending`

KIND's single-node cluster has limited resources. Check events:

```bash
kubectl describe pod -n envoy-gateway-system <pod-name>
```

### CRD version warnings

The `BackendTLSPolicy` v1alpha3 deprecation warning is informational and
does not affect functionality.

## GitOps with ArgoCD (next level)

The Makefile automates cluster lifecycle but is still imperative. For true
GitOps (the cluster auto-reconciles to git state), the next step is ArgoCD.

```
make cluster    ← imperative (infrastructure provisioning)
make install    ← imperative (bootstraps Helm charts; could add ArgoCD here)
                     └─ ArgoCD Application watches k8s/ in this repo
                            └─ ArgoCD applies/reconciles manifests automatically
make images     ← imperative (local builds; eliminated by pushing to GHCR)
make test       ← imperative (run from outside the cluster)
```

**Image builds** always require an imperative step unless images are pushed
to a registry. For a public lab repo, GHCR (GitHub Container Registry) is
free and removes this limitation.

### Minimal ArgoCD bootstrap

```bash
# After `make cluster && make install`:
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ai-gw-lab
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/<your-org>/<this-repo>
    targetRevision: HEAD
    path: k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF
```

Every `git push` to `k8s/` then reconciles the cluster automatically.
Secret management moves to [Sealed Secrets][sealed] or [SOPS][sops] so
the Azure API key can be committed safely.

[sealed]: https://github.com/bitnami-labs/sealed-secrets
[sops]: https://github.com/getsops/sops