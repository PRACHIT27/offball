#!/usr/bin/env bash
# Build the live Insight Generation image, push it to ACR and create/update its Container App.
# Creates identity id-insights and its least-privilege roles if missing, and the `insights`
# consumer group on the stats hub. Needs Docker running locally (no ACR Tasks on this subscription).
# Usage: [SUFFIX=kr2610 RG=offball-rg LOC=westus2] scripts/deploy_insights.sh [tag]
set -euo pipefail
cd "$(dirname "$0")/.."

TAG=${1:-$(git rev-parse --short HEAD)}
SUFFIX=${SUFFIX:-kr2610}
RG=${RG:-offball-rg}
LOC=${LOC:-westus2}
ACR=offballacr$SUFFIX
EH=offball-eh-$SUFFIX
COSMOS=offball-cosmos-$SUFFIX
AI=offball-ai-$SUFFIX
APP=offball-insights
ENV=offball-env
IMAGE="$ACR.azurecr.io/offball-insights:$TAG"
SUB=$(az account show --query id -o tsv)

echo "== identity id-insights and roles"
az identity show -g "$RG" -n id-insights -o none 2>/dev/null || \
  az identity create -g "$RG" -n id-insights -l "$LOC" -o none
PRINCIPAL=$(az identity show -g "$RG" -n id-insights --query principalId -o tsv)
ID_RES=$(az identity show -g "$RG" -n id-insights --query id -o tsv)
ID_CLIENT=$(az identity show -g "$RG" -n id-insights --query clientId -o tsv)
HUBS="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.EventHub/namespaces/$EH/eventhubs"
assign() {  # role, scope; re-running finds the existing assignment
  az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
    --role "$1" --scope "$2" -o none
}
assign "Azure Event Hubs Data Receiver" "$HUBS/triggers"
assign "Azure Event Hubs Data Receiver" "$HUBS/stats"
AI_ID=$(az cognitiveservices account show -g "$RG" -n "$AI" --query id -o tsv)
assign "Cognitive Services OpenAI User" "$AI_ID"
assign "Cognitive Services User" "$AI_ID"
assign "AcrPull" "$(az acr show -n "$ACR" --query id -o tsv)"
# Cosmos built-in Data Reader, events container only
if [ -z "$(az cosmosdb sql role assignment list -g "$RG" -a "$COSMOS" --query "[?principalId=='$PRINCIPAL'].id" -o tsv)" ]; then
  az cosmosdb sql role assignment create -g "$RG" -a "$COSMOS" --principal-id "$PRINCIPAL" \
    --role-definition-id 00000000-0000-0000-0000-000000000001 --scope "/dbs/offball/colls/events" -o none
fi
az eventhubs eventhub consumer-group show -g "$RG" --namespace-name "$EH" --eventhub-name stats -n insights -o none 2>/dev/null || \
  az eventhubs eventhub consumer-group create -g "$RG" --namespace-name "$EH" --eventhub-name stats -n insights -o none

echo "== build and push $IMAGE"
docker build --platform linux/amd64 -f Dockerfile.insights -t "$IMAGE" .
az acr login -n "$ACR" >/dev/null
docker push "$IMAGE" >/dev/null

echo "== container app $APP"
ENV_ID=$(az resource show -g "$RG" -n "$ENV" --resource-type Microsoft.App/managedEnvironments --query id -o tsv)
COSMOS_EP=$(az cosmosdb show -g "$RG" -n "$COSMOS" --query documentEndpoint -o tsv)
AI_EP=$(az cognitiveservices account show -g "$RG" -n "$AI" --query properties.endpoint -o tsv)
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT
python3 - "$BODY" <<PY
import json, sys
body = {
  "location": "$LOC",
  "identity": {"type": "UserAssigned", "userAssignedIdentities": {"$ID_RES": {}}},
  "properties": {
    "environmentId": "$ENV_ID",
    "workloadProfileName": "Consumption",
    "configuration": {
      "activeRevisionsMode": "Single",
      "ingress": {"external": True, "targetPort": 8080, "transport": "auto"},
      "registries": [{"server": "$ACR.azurecr.io", "identity": "$ID_RES"}],
    },
    "template": {
      "containers": [{
        "name": "insights",
        "image": "$IMAGE",
        "resources": {"cpu": 1.0, "memory": "2Gi"},
        "env": [
          {"name": "AZURE_CLIENT_ID", "value": "$ID_CLIENT"},
          {"name": "EVENTHUB_NAMESPACE", "value": "$EH.servicebus.windows.net"},
          {"name": "COSMOS_ENDPOINT", "value": "$COSMOS_EP"},
          {"name": "AZURE_AI_ENDPOINT", "value": "$AI_EP"},
        ],
      }],
      # One replica: each match's data and the trigger dedupe live in one process
      "scale": {"minReplicas": 1, "maxReplicas": 1},
    },
  },
}
json.dump(body, open(sys.argv[1], "w"))
PY
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/$APP?api-version=2024-03-01" \
  --body "@$BODY" --query "{name:name,state:properties.provisioningState,url:properties.configuration.ingress.fqdn}" -o tsv
echo "deployed $IMAGE"
