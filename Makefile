# Makefile — Envoy AI Gateway lab cluster lifecycle
#
# Usage:
#   make up         — full fresh setup (cluster + charts + gateway + images + manifests)
#   make restart    — teardown then up
#   make test       — run integration tests
#   make teardown   — delete the KIND cluster
#
# Individual steps (in dependency order):
#   make cluster    — create the KIND cluster
#   make install    — install Helm charts + base gateway + NodePort patch
#   make images     — build and load all local container images
#   make apply      — apply Azure backend, MCP, OAuth, and security manifests

# ── Config ────────────────────────────────────────────────────────────
CLUSTER_NAME   := ai-gw-lab
CLUSTER_CONFIG := k8s/kind-cluster.yaml

export PATH := $(HOME)/go/bin:$(HOME)/.local/bin:$(PATH)

# kind requires rootless Podman with delegated cgroups
KIND       := systemd-run --user --scope -p Delegate=yes kind
KIND_PLAIN := KIND_EXPERIMENTAL_PROVIDER=podman kind

EG_VERSION   := v0.0.0-latest
AIEG_VERSION := v0.0.0-latest

# ── Phony targets ─────────────────────────────────────────────────────
.PHONY: up restart cluster install images apply test teardown \
        _install-eg _install-aieg-crd _install-aieg _apply-base-gateway \
        _build-mcp-server _build-oauth-idp _build-chat-front2-ui _check-secret

# ── Top-level targets ─────────────────────────────────────────────────

## Full fresh setup
up: cluster install images apply
	@echo ""
	@echo "Cluster is ready. Run 'make test' to verify."

## Tear down and rebuild from scratch
restart: teardown up

# ── Step 1: cluster ───────────────────────────────────────────────────

## Create the KIND cluster
cluster:
	$(KIND) create cluster --config $(CLUSTER_CONFIG)

# ── Step 2: install ───────────────────────────────────────────────────
#
# Order matters:
#   a) Helm charts (eg → aieg-crd → aieg)
#   b) base-gateway.yaml  — creates the Gateway, which triggers Envoy proxy creation
#   c) Wait for the Envoy proxy pod to be ready
#   d) Patch NodePort to 30080 (KIND only maps this one port)

## Install Helm charts and deploy base gateway
install: _install-eg _install-aieg-crd _install-aieg _apply-base-gateway

_install-eg:
	helm upgrade --install eg \
	  oci://docker.io/envoyproxy/gateway-helm \
	  --version $(EG_VERSION) \
	  -n envoy-gateway-system --create-namespace \
	  -f k8s/eg-values.yaml \
	  --wait

_install-aieg-crd:
	helm upgrade --install aieg-crd \
	  oci://docker.io/envoyproxy/ai-gateway-crds-helm \
	  --version $(AIEG_VERSION) \
	  -n envoy-ai-gateway-system --create-namespace \
	  --wait

_install-aieg:
	helm upgrade --install aieg \
	  oci://docker.io/envoyproxy/ai-gateway-helm \
	  --version $(AIEG_VERSION) \
	  -n envoy-ai-gateway-system \
	  --wait

_apply-base-gateway:
	kubectl apply -f k8s/base-gateway.yaml
	@echo "Waiting for Envoy proxy pod to be created..."
	@until kubectl get pods -n envoy-gateway-system \
	    -l "gateway.envoyproxy.io/owning-gateway-name=ai-gw-lab" \
	    --no-headers 2>/dev/null | grep -q .; do sleep 2; done
	@echo "Pod created — waiting for Ready..."
	kubectl wait --timeout=120s -n envoy-gateway-system \
	  -l "gateway.envoyproxy.io/owning-gateway-name=ai-gw-lab" \
	  pods --for=condition=Ready


# ── Step 3: images ────────────────────────────────────────────────────

## Build and load all local container images into KIND
images: _build-mcp-server _build-oauth-idp _build-chat-front2-ui

_build-mcp-server:
	@echo "Building mcp-server..."
	podman build -t localhost/mcp-server:latest mcp-server/
	podman save localhost/mcp-server:latest -o /tmp/mcp-server.tar
	$(KIND_PLAIN) load image-archive /tmp/mcp-server.tar --name $(CLUSTER_NAME)
	rm -f /tmp/mcp-server.tar

_build-oauth-idp:
	@echo "Building oauth-idp..."
	podman build -t localhost/oauth-idp:latest oauth-idp/
	podman save localhost/oauth-idp:latest -o /tmp/oauth-idp.tar
	$(KIND_PLAIN) load image-archive /tmp/oauth-idp.tar --name $(CLUSTER_NAME)
	rm -f /tmp/oauth-idp.tar

_build-chat-front2-ui:
	@echo "Building chat-front2-ui..."
	podman build -t localhost/chat-front2-ui:latest chat-front2-ui/
	podman save localhost/chat-front2-ui:latest -o /tmp/chat-front2-ui.tar
	$(KIND_PLAIN) load image-archive /tmp/chat-front2-ui.tar --name $(CLUSTER_NAME)
	rm -f /tmp/chat-front2-ui.tar

# ── Step 4: apply ─────────────────────────────────────────────────────

## Apply Azure backend, MCP server, OAuth IdP, and JWT security policy
apply: _check-secret
	kubectl apply -f k8s/secrets/azure-ai-foundry-apikey.yaml
	kubectl apply -f k8s/azure-ai-foundry.yaml
	kubectl apply -f k8s/envoy-patch-alpn.yaml
	kubectl apply -f k8s/mcp-server.yaml
	kubectl apply -f k8s/mcp-route.yaml
	kubectl apply -f k8s/oauth-idp.yaml
	kubectl apply -f k8s/security-policy-jwt.yaml
	kubectl apply -f k8s/chat-front2-ui.yaml
	@echo "Waiting for deployments..."
	kubectl rollout status deployment/mcp-server     --timeout=60s
	kubectl rollout status deployment/oauth-idp      --timeout=60s
	kubectl rollout status deployment/chat-front2-ui --timeout=60s
	@echo "Waiting for Envoy proxy rollout (MCPRoute injects a sidecar)..."
	kubectl rollout status -n envoy-gateway-system \
	  deployment/envoy-default-ai-gw-lab-82528b23 --timeout=120s
	@echo "Waiting for MCP proxy to accept connections..."
	@TOKEN=$$(curl -sf -X POST http://localhost:30300/admin/token \
	  -H "Content-Type: application/json" \
	  -d '{"sub":"readiness-check"}' \
	  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null); \
	until curl -sf http://localhost:30080/mcp \
	  -H "Content-Type: application/json" \
	  -H "Accept: application/json, text/event-stream" \
	  -H "Authorization: Bearer $$TOKEN" \
	  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"ready","version":"0.1"}}}' \
	  -o /dev/null 2>/dev/null; do \
	  printf '.'; sleep 2; \
	done; echo " ready"

_check-secret:
	@test -f k8s/secrets/azure-ai-foundry-apikey.yaml || { \
	  echo ""; \
	  echo "ERROR: k8s/secrets/azure-ai-foundry-apikey.yaml not found."; \
	  echo "Copy the example and fill in your Azure API key:"; \
	  echo "  cp k8s/secrets/azure-ai-foundry-apikey.yaml.example \\"; \
	  echo "     k8s/secrets/azure-ai-foundry-apikey.yaml"; \
	  echo ""; \
	  exit 1; \
	}

# ── Utility ───────────────────────────────────────────────────────────

## Run the integration test suite
test:
	python3 tests/test_integration.py

## Delete the KIND cluster
teardown:
	$(KIND_PLAIN) delete cluster --name $(CLUSTER_NAME)
