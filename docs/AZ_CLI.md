# Azure CLI Setup & Teardown

How to create (and destroy) the Azure AI Foundry resources used by this
project.

## Prerequisites

- Azure CLI 2.85+ (`sudo pacman -S azure-cli`)
- An active Azure subscription

## Login

```bash
az login --use-device-code
```

Verify your subscription:

```bash
az account show --query "{name:name, id:id, state:state}" -o table
```

## Create Resources

### 1. Resource Group

```bash
az group create --name rg-daemon --location centralus
```

### 2. Cognitive Services Account

```bash
az cognitiveservices account create \
  --name daemon-resource \
  --resource-group rg-daemon \
  --location centralus \
  --kind CognitiveServices \
  --sku S0
```

### 3. Deploy a Model

```bash
az cognitiveservices account deployment create \
  --name daemon-resource \
  --resource-group rg-daemon \
  --deployment-name gpt-5.1 \
  --model-name gpt-5.1 \
  --model-version 2025-11-13 \
  --model-format OpenAI \
  --sku-capacity 50 \
  --sku-name GlobalStandard
```

`--sku-capacity` controls the throughput quota — each unit = 1K tokens/min and
~10 requests/min. Capacity 50 gives 50K TPM / 500 RPM, which is comfortable for
interactive use and repeated test runs. Capacity 1 (the minimum) hits the
429 rate limit almost immediately under any real load.

To check the current limits on a running deployment:

```bash
az cognitiveservices account deployment show \
  --name daemon-resource \
  --resource-group rg-daemon \
  --deployment-name gpt-5.1 \
  --query "{capacity:sku.capacity, rateLimits:properties.rateLimits}" \
  -o json
```

To adjust capacity on an existing deployment, re-run the `create` command
above with a different `--sku-capacity` value — it upserts in place
(`az cognitiveservices account deployment update` does not exist).

Verify the deployment:

```bash
az cognitiveservices account deployment list \
  --name daemon-resource \
  --resource-group rg-daemon \
  --query "[].{name:name, model:properties.model.name, version:properties.model.version}" \
  -o table
```

### 4. Retrieve Endpoint & API Key

```bash
# Endpoint hostname
az cognitiveservices account show \
  --name daemon-resource \
  --resource-group rg-daemon \
  --query properties.endpoint -o tsv

# API key
az cognitiveservices account keys list \
  --name daemon-resource \
  --resource-group rg-daemon \
  --query key1 -o tsv
```

For this project the endpoint is `daemon-resource.services.ai.azure.com`
and the API key goes into `k8s/secrets/azure-ai-foundry-apikey.yaml`
(gitignored).

### 5. Create the Kubernetes Secret

```bash
kubectl create secret generic azure-ai-foundry-apikey \
  --from-literal=apiKey="$(az cognitiveservices account keys list \
      --name daemon-resource \
      --resource-group rg-daemon \
      --query key1 -o tsv)"
```

Or apply the YAML directly:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: azure-ai-foundry-apikey
type: Opaque
stringData:
  apiKey: "<paste key here>"
```

## Teardown

Remove resources in reverse order to avoid orphans:

```bash
# Delete the model deployment
az cognitiveservices account deployment delete \
  --name daemon-resource \
  --resource-group rg-daemon \
  --deployment-name gpt-5.1

# Delete the Cognitive Services account
az cognitiveservices account delete \
  --name daemon-resource \
  --resource-group rg-daemon

# Delete the resource group (removes everything inside it)
az group delete --name rg-daemon --yes --no-wait
```

## Useful Queries

```bash
# List all deployed models
az cognitiveservices account deployment list \
  --name daemon-resource \
  --resource-group rg-daemon -o table

# List available models for deployment
az cognitiveservices account list-models \
  --name daemon-resource \
  --resource-group rg-daemon \
  --query "[?kind=='OpenAI'].{model:model.name, version:model.version}" \
  -o table

# Check resource group contents
az resource list --resource-group rg-daemon -o table

# Show current capacity and rate limits for the deployment
az cognitiveservices account deployment show \
  --name daemon-resource \
  --resource-group rg-daemon \
  --deployment-name gpt-5.1 \
  --query "{capacity:sku.capacity, rateLimits:properties.rateLimits}" \
  -o json
```
