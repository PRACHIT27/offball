#!/usr/bin/env bash
# Build the match control image, push it to ACR and create/update its Container App.
# Creates the id-sim identity with send-only access to the raw hubs if it does not exist, and
# lets it start and stop the live pipeline (engine, insights, cue manager): Play wakes them,
# IDLE_MINUTES (default 20) without a match puts them back to sleep (sim/control/pipeline.py).
# Needs Docker running locally and `az login` with rights on the resource group.
# Usage: [SUFFIX=kr2610 RG=offball-rg LOC=westus2 CONTROL_PASSCODE=... IDLE_MINUTES=20] scripts/deploy_sim.sh [tag]
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

TAG=${1:-$(git rev-parse --short HEAD)}
SUFFIX=${SUFFIX:-kr2610}
RG=${RG:-offball-rg}
LOC=${LOC:-westus2}
ACR=offballacr$SUFFIX
EH=offball-eh-$SUFFIX
APP=offball-sim
ENV=offball-env
IMAGE="$ACR.azurecr.io/offball-sim:$TAG"
PIPELINE_APPS=${PIPELINE_APPS-offball-engine,offball-insights,offball-cues}
IDLE_MINUTES=${IDLE_MINUTES:-20}

echo "== identity id-sim"
if ! az identity show -g "$RG" -n id-sim >/dev/null 2>&1; then
  az identity create -g "$RG" -n id-sim -l "$LOC" -o none
fi
ID_RES=$(az identity show -g "$RG" -n id-sim --query id -o tsv)
ID_CLIENT=$(az identity show -g "$RG" -n id-sim --query clientId -o tsv)
ID_PRINCIPAL=$(az identity show -g "$RG" -n id-sim --query principalId -o tsv)
for hub in raw-events raw-tracking; do
  HUB_ID=$(az eventhubs eventhub show -g "$RG" --namespace-name "$EH" -n "$hub" --query id -o tsv)
  az role assignment create --assignee-object-id "$ID_PRINCIPAL" --assignee-principal-type ServicePrincipal \
    --role "Azure Event Hubs Data Sender" --scope "$HUB_ID" -o none 2>/dev/null || true
done
ACR_ID=$(az acr show -n "$ACR" --query id -o tsv)
az role assignment create --assignee-object-id "$ID_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$ACR_ID" -o none 2>/dev/null || true

if [ -n "$PIPELINE_APPS" ]; then
  echo "== id-sim may read, start and stop the pipeline apps (nothing else)"
  SUB=$(az account show --query id -o tsv)
  ROLE="OffBall pipeline switch"
  if [ -z "$(az role definition list --name "$ROLE" --query "[].name" -o tsv)" ]; then
    az role definition create -o none --role-definition "{
      \"Name\": \"$ROLE\",
      \"Description\": \"Read, start and stop the OffBall pipeline Container Apps\",
      \"Actions\": [\"Microsoft.App/containerApps/read\", \"Microsoft.App/containerApps/start/action\",
                    \"Microsoft.App/containerApps/stop/action\"],
      \"AssignableScopes\": [\"/subscriptions/$SUB/resourceGroups/$RG\"]}"
  fi
  for app in ${PIPELINE_APPS//,/ }; do
    APP_ID=$(az containerapp show -g "$RG" -n "$app" --query id -o tsv)
    az role assignment create --assignee-object-id "$ID_PRINCIPAL" --assignee-principal-type ServicePrincipal \
      --role "$ROLE" --scope "$APP_ID" -o none 2>/dev/null || true
  done
fi

echo "== build and push $IMAGE"
docker build --platform linux/amd64 -f Dockerfile.sim -t "$IMAGE" .
# The registry push sometimes drops mid-upload: retry until the registry confirms the digest
for i in 1 2 3 4 5; do
  az acr login -n "$ACR" >/dev/null
  if docker push "$IMAGE" 2>&1 | tail -1 | grep -q "^$TAG: digest:"; then break; fi
  [ "$i" = 5 ] && { echo "push failed 5 times"; exit 1; }
  echo "   push dropped, retrying ($i)"
done

echo "== container app $APP"
SUB=$(az account show --query id -o tsv)
ENV_ID=$(az resource show -g "$RG" -n "$ENV" --resource-type Microsoft.App/managedEnvironments --query id -o tsv)
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT
python3 - "$BODY" <<EOF
import json, os, sys
secrets, env = [], [
  {"name": "AZURE_CLIENT_ID", "value": "$ID_CLIENT"},
  {"name": "EVENTHUB_NAMESPACE", "value": "$EH.servicebus.windows.net"},
  {"name": "WARM_STORYLINE", "value": "red_card"},
  {"name": "PIPELINE_APPS", "value": "$PIPELINE_APPS"},
  {"name": "PIPELINE_HEALTH_URLS", "value": "https://offball-insights.whitemoss-2f18829c.westus2.azurecontainerapps.io/health,https://offball-cues.whitemoss-2f18829c.westus2.azurecontainerapps.io/health"},
  {"name": "IDLE_MINUTES", "value": "$IDLE_MINUTES"},
  {"name": "VIEWER_URL", "value": "${VIEWER_URL:-https://jolly-cliff-0ccede51e.4.azurestaticapps.net}"},
  {"name": "AZ_SUBSCRIPTION", "value": "$(az account show --query id -o tsv)"},
  {"name": "AZ_RESOURCE_GROUP", "value": "$RG"},
  {"name": "DEPLOYED_AT", "value": "$(date -u +%Y%m%dT%H%M%SZ)"},
]
if os.environ.get("CONTROL_PASSCODE"):
    secrets.append({"name": "passcode", "value": os.environ["CONTROL_PASSCODE"]})
    env.append({"name": "CONTROL_PASSCODE", "secretRef": "passcode"})
body = {
  "location": "$LOC",
  "identity": {"type": "UserAssigned", "userAssignedIdentities": {"$ID_RES": {}}},
  "properties": {
    "environmentId": "$ENV_ID",
    "workloadProfileName": "Consumption",
    "configuration": {
      "activeRevisionsMode": "Single",
      "ingress": {"external": True, "targetPort": 8000, "transport": "auto"},
      "registries": [{"server": "$ACR.azurecr.io", "identity": "$ID_RES"}],
      "secrets": secrets,
    },
    "template": {
      "containers": [{"name": "sim", "image": "$IMAGE",
                      "resources": {"cpu": 1.0, "memory": "2Gi"}, "env": env}],
      "scale": {"minReplicas": 1, "maxReplicas": 1},
    },
  },
}
json.dump(body, open(sys.argv[1], "w"))
EOF
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/$APP?api-version=2024-03-01" \
  --body "@$BODY" --query "{name:name,state:properties.provisioningState,revision:properties.latestRevisionName}" -o tsv
FQDN=$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)
echo "deployed $IMAGE${FQDN:+ at https://$FQDN}"
