#!/usr/bin/env bash
# Broadcast: create (if missing) Web PubSub, identity id-cues with least-privilege roles and the
# `cues` consumer group on the stats hub; then build the cue manager image, push it and
# create/update Container App offball-cues. Needs Docker running locally.
# Usage: [SUFFIX=kr2610 RG=offball-rg LOC=westus2 PRODUCER_PASSCODE=…] scripts/deploy_cues.sh [tag]
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

TAG=${1:-$(git rev-parse --short HEAD)}
SUFFIX=${SUFFIX:-kr2610}
RG=${RG:-offball-rg}
LOC=${LOC:-westus2}
ACR=offballacr$SUFFIX
EH=offball-eh-$SUFFIX
COSMOS=offball-cosmos-$SUFFIX
WPS=offball-pubsub-$SUFFIX
APP=offball-cues
ENV=offball-env
IMAGE="$ACR.azurecr.io/offball-cues:$TAG"
SUB=$(az account show --query id -o tsv)
SCREEN_ORIGIN=${SCREEN_ORIGIN:-https://jolly-cliff-0ccede51e.4.azurestaticapps.net}
INSIGHTS_URL=${INSIGHTS_URL:-https://offball-insights.whitemoss-2f18829c.westus2.azurecontainerapps.io}
# Fabric Eventhouse for the Real-Time Dashboard (scripts/fabric_dashboard.py prints it); "" turns it off
FABRIC_KUSTO_URI=${FABRIC_KUSTO_URI-https://trd-2femkkugfffmm8qyfq.z6.kusto.fabric.microsoft.com}

echo "== Web PubSub $WPS (Standard S1: Free allows 20k messages a day, a live match sends ~27k per viewer)"
az provider register --namespace Microsoft.SignalRService --wait
az webpubsub show -g "$RG" -n "$WPS" -o none 2>/dev/null || \
  az webpubsub create -g "$RG" -n "$WPS" -l "$LOC" --sku Standard_S1 --unit-count 1 -o none
WPS_ID=$(az webpubsub show -g "$RG" -n "$WPS" --query id -o tsv)
WPS_EP="https://$(az webpubsub show -g "$RG" -n "$WPS" --query hostName -o tsv)"

echo "== identity id-cues and roles"
az identity show -g "$RG" -n id-cues -o none 2>/dev/null || az identity create -g "$RG" -n id-cues -l "$LOC" -o none
PRINCIPAL=$(az identity show -g "$RG" -n id-cues --query principalId -o tsv)
ID_RES=$(az identity show -g "$RG" -n id-cues --query id -o tsv)
ID_CLIENT=$(az identity show -g "$RG" -n id-cues --query clientId -o tsv)
HUBS="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.EventHub/namespaces/$EH/eventhubs"
assign() {  # role, scope; re-running finds the existing assignment
  az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
    --role "$1" --scope "$2" -o none
}
assign "Azure Event Hubs Data Receiver" "$HUBS/stats"
assign "Web PubSub Service Owner" "$WPS_ID"
assign "AcrPull" "$(az acr show -n "$ACR" --query id -o tsv)"
# Cosmos built-in Data Reader on events, for the pre-match info (team names, players)
if [ -z "$(az cosmosdb sql role assignment list -g "$RG" -a "$COSMOS" --query "[?principalId=='$PRINCIPAL'].id" -o tsv)" ]; then
  az cosmosdb sql role assignment create -g "$RG" -a "$COSMOS" --principal-id "$PRINCIPAL" \
    --role-definition-id 00000000-0000-0000-0000-000000000001 --scope "/dbs/offball/colls/events" -o none
fi
az eventhubs eventhub consumer-group show -g "$RG" --namespace-name "$EH" --eventhub-name stats -n cues -o none 2>/dev/null || \
  az eventhubs eventhub consumer-group create -g "$RG" --namespace-name "$EH" --eventhub-name stats -n cues -o none

if [ -n "$FABRIC_KUSTO_URI" ]; then
  echo "== Fabric: id-cues may ingest into KQL database offball (ingestor only)"
  TENANT=$(az account show --query tenantId -o tsv)
  az rest --method post --url "$FABRIC_KUSTO_URI/v1/rest/mgmt" --resource "$FABRIC_KUSTO_URI" \
    --body "{\"db\": \"offball\", \"csl\": \".add database offball ingestors ('aadapp=$ID_CLIENT;$TENANT') 'offball-cues'\"}" \
    -o none || echo "   (could not add the ingestor; the cue manager runs without Fabric)"
fi

echo "== build and push $IMAGE"
docker build --platform linux/amd64 -f Dockerfile.cues -t "$IMAGE" .
az acr login -n "$ACR" >/dev/null
docker push "$IMAGE" >/dev/null

echo "== container app $APP"
# The producer passcode goes in as a Container App secret; generated once if not given
PASSCODE=${PRODUCER_PASSCODE:-$(python3 -c "import secrets; print(secrets.token_urlsafe(9))")}
ENV_ID=$(az resource show -g "$RG" -n "$ENV" --resource-type Microsoft.App/managedEnvironments --query id -o tsv)
COSMOS_EP=$(az cosmosdb show -g "$RG" -n "$COSMOS" --query documentEndpoint -o tsv)
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT
PASSCODE="$PASSCODE" python3 - "$BODY" <<PY
import json, os, sys
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
      "secrets": [{"name": "producer-passcode", "value": os.environ["PASSCODE"]}],
    },
    "template": {
      "containers": [{
        "name": "cues",
        "image": "$IMAGE",
        "resources": {"cpu": 0.5, "memory": "1Gi"},
        "env": [
          {"name": "AZURE_CLIENT_ID", "value": "$ID_CLIENT"},
          {"name": "EVENTHUB_NAMESPACE", "value": "$EH.servicebus.windows.net"},
          {"name": "COSMOS_ENDPOINT", "value": "$COSMOS_EP"},
          {"name": "WEBPUBSUB_ENDPOINT", "value": "$WPS_EP"},
          {"name": "INSIGHTS_URL", "value": "$INSIGHTS_URL"},
          {"name": "ALLOWED_ORIGINS", "value": "$SCREEN_ORIGIN"},
          {"name": "FABRIC_KUSTO_URI", "value": "$FABRIC_KUSTO_URI"},
          {"name": "PRODUCER_PASSCODE", "secretRef": "producer-passcode"},
          {"name": "DEPLOYED_AT", "value": "$(date -u +%Y%m%dT%H%M%SZ)"},
        ],
      }],
      # One replica: each match's cue state lives in one process
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
if [ -z "${PRODUCER_PASSCODE:-}" ]; then
  echo "Producer console passcode (generated; keep it for the testing instructions): $PASSCODE"
fi
