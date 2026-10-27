#!/usr/bin/env bash
# Build the match control image, push it to ACR and create/update its Container App.
# Creates the id-sim identity with send-only access to the raw hubs if it does not exist.
# Needs Docker running locally and `az login` with rights on the resource group.
# Usage: [SUFFIX=kr2610 RG=offball-rg LOC=westus2 CONTROL_PASSCODE=...] scripts/deploy_sim.sh [tag]
set -euo pipefail
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

echo "== build and push $IMAGE"
docker build --platform linux/amd64 -f Dockerfile.sim -t "$IMAGE" .
az acr login -n "$ACR" >/dev/null
docker push "$IMAGE" >/dev/null

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
  --body "@$BODY" --query "{name:name,state:properties.provisioningState}" -o tsv
FQDN=$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)
echo "deployed $IMAGE${FQDN:+ at https://$FQDN}"
