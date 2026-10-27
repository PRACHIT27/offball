#!/usr/bin/env bash
# Build the match engine image, push it to ACR and create/update the Container App.
# Needs Docker running locally (ACR Tasks are not allowed on this subscription).
# Usage: [SUFFIX=kr2610 RG=offball-rg LOC=westus2 TACTICS_ENABLED=1 METRICS_ENABLED=1] scripts/deploy_engine.sh [tag]
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

TAG=${1:-$(git rev-parse --short HEAD)}
SUFFIX=${SUFFIX:-kr2610}
RG=${RG:-offball-rg}
LOC=${LOC:-westus2}
ACR=offballacr$SUFFIX
APP=offball-engine
ENV=offball-env
IMAGE="$ACR.azurecr.io/offball-engine:$TAG"

echo "== build and push $IMAGE"
docker build --platform linux/amd64 -f Dockerfile.engine -t "$IMAGE" .
az acr login -n "$ACR" >/dev/null
docker push "$IMAGE" >/dev/null

echo "== container app $APP"
SUB=$(az account show --query id -o tsv)
ID_RES=$(az identity show -g "$RG" -n id-engine --query id -o tsv)
ID_CLIENT=$(az identity show -g "$RG" -n id-engine --query clientId -o tsv)
ENV_ID=$(az resource show -g "$RG" -n "$ENV" --resource-type Microsoft.App/managedEnvironments --query id -o tsv)
COSMOS=$(az cosmosdb show -g "$RG" -n "offball-cosmos-$SUFFIX" --query documentEndpoint -o tsv)
# Telemetry connection string goes in as a Container App secret; never printed
AI_CONN=$(az resource show -g "$RG" -n "offball-ingest-$SUFFIX" --resource-type microsoft.insights/components \
  --query properties.ConnectionString -o tsv)

BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT
python3 - "$BODY" <<EOF
import json, sys
body = {
  "location": "$LOC",
  "identity": {"type": "UserAssigned", "userAssignedIdentities": {"$ID_RES": {}}},
  "properties": {
    "environmentId": "$ENV_ID",
    "workloadProfileName": "Consumption",
    "configuration": {
      "activeRevisionsMode": "Single",
      "registries": [{"server": "$ACR.azurecr.io", "identity": "$ID_RES"}],
      "secrets": [{"name": "appinsights", "value": "$AI_CONN"}],
    },
    "template": {
      "containers": [{
        "name": "engine",
        "image": "$IMAGE",
        "resources": {"cpu": 0.5, "memory": "1Gi"},
        "env": [
          {"name": "AZURE_CLIENT_ID", "value": "$ID_CLIENT"},
          {"name": "EVENTHUB_NAMESPACE", "value": "offball-eh-$SUFFIX.servicebus.windows.net"},
          {"name": "STORAGE_ACCOUNT_URL", "value": "https://offballst$SUFFIX.blob.core.windows.net"},
          {"name": "COSMOS_ENDPOINT", "value": "$COSMOS"},
          {"name": "APPLICATIONINSIGHTS_CONNECTION_STRING", "secretRef": "appinsights"},
          {"name": "TACTICS_ENABLED", "value": "${TACTICS_ENABLED:-0}"},
          {"name": "METRICS_ENABLED", "value": "${METRICS_ENABLED:-0}"},
        ],
      }],
      # One replica: each match's merge state lives in one process
      "scale": {"minReplicas": 1, "maxReplicas": 1},
    },
  },
}
json.dump(body, open(sys.argv[1], "w"))
EOF
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/$APP?api-version=2024-03-01" \
  --body "@$BODY" --query "{name:name,state:properties.provisioningState}" -o tsv
echo "deployed $IMAGE"
