#!/usr/bin/env bash
# OffBall Lane 1: Azure setup for data ingestion (ingestion LLD §8 and §10).
# Rebuilds the whole Lane 1 setup from scratch; safe to re-run (every step creates or updates).
#
# Run after: az login            Usage: bash azure-setup.sh
# Needs: Azure CLI. Optional: Functions Core Tools (`func`) to deploy the normalizers and Docker
# running to build the engine image; without them those steps are skipped with instructions.
# Uses only management-plane commands, so it also works on CLIs whose data-plane commands
# fail (Homebrew CLI on Python 3.14).
set -e
cd "$(dirname "$0")"

# ---------- 0. Names (change SUFFIX to something unique, e.g. initials + 4 digits) ----------
export SUFFIX=${SUFFIX:-kr2610}
export RG=${RG:-offball-rg}
export LOC=${LOC:-westus2}    # if a step fails with RequestDisallowedByAzure, pick an allowed region
EH=offball-eh-$SUFFIX         # Event Hubs namespace
ST=offballst$SUFFIX           # data storage: bronze, frames, dead letters, checkpoints, team sheets
FUNCST=offballfn$SUFFIX       # separate storage just for the Function App
COSMOS=offball-cosmos-$SUFFIX
FUNC=offball-ingest-$SUFFIX   # normalizers; its Application Insights has the same name
ACR=offballacr$SUFFIX         # container registry for the engine image
ACAENV=offball-env
ENGINE=offball-engine
SUB=$(az account show --query id -o tsv)
ARM="https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers"

echo "== 1. Registering Azure services on this subscription (one time) =="
for p in Microsoft.EventHub Microsoft.Storage Microsoft.DocumentDB Microsoft.Web \
         Microsoft.App Microsoft.OperationalInsights Microsoft.Insights \
         Microsoft.ManagedIdentity Microsoft.ContainerRegistry; do
  az provider register --namespace $p --wait
done

echo "== 2. Resource group =="
az group create --name $RG --location $LOC -o none

echo "== 3. Event Hubs namespace, hubs and consumer groups =="
az eventhubs namespace create --name $EH --resource-group $RG --location $LOC --sku Standard -o none
for hub in raw-events raw-tracking normalized; do
  az eventhubs eventhub create --name $hub --namespace-name $EH --resource-group $RG \
    --partition-count 4 --retention-time 168 --cleanup-policy Delete -o none
done
# Normalizers read the raw hubs, the match engine reads normalized
az eventhubs eventhub consumer-group create --resource-group $RG --namespace-name $EH --eventhub-name raw-events   --name ingest -o none
az eventhubs eventhub consumer-group create --resource-group $RG --namespace-name $EH --eventhub-name raw-tracking --name ingest -o none
az eventhubs eventhub consumer-group create --resource-group $RG --namespace-name $EH --eventhub-name normalized   --name engine -o none

echo "== 4. Storage: Bronze, Silver frames, dead letters, engine checkpoints, team sheets =="
az storage account create --name $ST --resource-group $RG --location $LOC \
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false --hns true -o none
for c in bronze silver-frames dead-letter checkpoints teamsheets; do
  az storage container-rm create --storage-account $ST --resource-group $RG --name $c -o none
done

echo "== 5. Cosmos DB (serverless), database and events container (takes ~5-10 min) =="
az cosmosdb create --name $COSMOS --resource-group $RG \
  --locations regionName=$LOC --capabilities EnableServerless -o none
az cosmosdb sql database create --account-name $COSMOS --resource-group $RG --name offball -o none
az cosmosdb sql container create --account-name $COSMOS --resource-group $RG \
  --database-name offball --name events --partition-key-path /match_id -o none

echo "== 6. Function App on Flex Consumption, Python 3.12 (also creates Application Insights) =="
az storage account create --name $FUNCST --resource-group $RG --location $LOC \
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false -o none
az functionapp show --resource-group $RG --name $FUNC -o none 2>/dev/null || \
  az functionapp create --resource-group $RG --name $FUNC --storage-account $FUNCST \
    --flexconsumption-location $LOC --runtime python --runtime-version 3.12 -o none

echo "== 7. Event Hubs Capture: raw hubs to the bronze container (Avro, 5 min / 300 MB) =="
STID=$(az storage account show --name $ST --resource-group $RG --query id -o tsv)
for hub in raw-events raw-tracking; do
  az eventhubs eventhub update --name $hub --namespace-name $EH --resource-group $RG \
    --enable-capture true --encoding Avro --capture-interval 300 --capture-size-limit 314572800 \
    --skip-empty-archives true --destination-name EventHubArchive.AzureBlockBlob \
    --storage-account "$STID" --blob-container bronze \
    --archive-name-format "{Namespace}/{EventHub}/{PartitionId}/{Year}/{Month}/{Day}/{Hour}/{Minute}/{Second}" \
    -o none
done

echo "== 8. Container Apps environment for the match engine =="
# Uses the ARM API directly: the containerapp extension won't install on CLIs running Python 3.14.
# No log destination: the subscription creates an "express" environment, which rejects one.
# The engine sends its logs to Application Insights itself (role offball-engine).
az rest --method put \
  --url "$ARM/Microsoft.App/managedEnvironments/$ACAENV?api-version=2024-03-01" \
  --body "{\"location\":\"$LOC\",\"properties\":{\"workloadProfiles\":[{\"name\":\"Consumption\",\"workloadProfileType\":\"Consumption\"}],\"zoneRedundant\":false}}" \
  -o none
# The PUT returns while provisioning is still running; wait for it to finish
until s=$(az rest --method get \
    --url "$ARM/Microsoft.App/managedEnvironments/$ACAENV?api-version=2024-03-01" \
    --query properties.provisioningState -o tsv) && [ "$s" != "InProgress" ] && [ "$s" != "Waiting" ]; do
  sleep 15
done
[ "$s" = "Succeeded" ] || { echo "Container Apps environment ended in state: $s"; exit 1; }

echo "== 9. Container registry for the engine image (Basic, admin login off) =="
az acr create --resource-group $RG --name $ACR --sku Basic --admin-enabled false --location $LOC -o none

echo "== 10. Managed identities and least-privilege roles (LLD §10) =="
for id in id-ingest id-engine; do
  az identity create --resource-group $RG --name $id --location $LOC -o none
done
ING=$(az identity show -g $RG -n id-ingest --query principalId -o tsv)
ENG=$(az identity show -g $RG -n id-engine --query principalId -o tsv)
HUBS=$ARM/Microsoft.EventHub/namespaces/$EH/eventhubs
BLOBS=$ARM/Microsoft.Storage/storageAccounts/$ST/blobServices/default/containers
assign() {  # principal, role, scope; re-running finds the existing assignment
  az role assignment create --assignee-object-id "$1" --assignee-principal-type ServicePrincipal \
    --role "$2" --scope "$3" -o none
}
# Normalizers: read raw hubs, write normalized, dead letters and team sheets
assign $ING "Azure Event Hubs Data Receiver" $HUBS/raw-events
assign $ING "Azure Event Hubs Data Receiver" $HUBS/raw-tracking
assign $ING "Azure Event Hubs Data Sender"   $HUBS/normalized
assign $ING "Storage Blob Data Contributor"  $BLOBS/dead-letter
assign $ING "Storage Blob Data Contributor"  $BLOBS/teamsheets
# Engine: read normalized, write frames and checkpoints, pull its image, write Cosmos events
assign $ENG "Azure Event Hubs Data Receiver" $HUBS/normalized
assign $ENG "Storage Blob Data Contributor"  $BLOBS/silver-frames
assign $ENG "Storage Blob Data Contributor"  $BLOBS/checkpoints
assign $ENG "AcrPull" "$(az acr show -n $ACR --query id -o tsv)"
# Cosmos data-plane role (built-in Data Contributor), scoped to the events container only
if [ -z "$(az cosmosdb sql role assignment list -g $RG -a $COSMOS --query "[?principalId=='$ENG'].id" -o tsv)" ]; then
  az cosmosdb sql role assignment create -g $RG -a $COSMOS --principal-id $ENG \
    --role-definition-id 00000000-0000-0000-0000-000000000002 --scope "/dbs/offball/colls/events" -o none
fi

echo "== 11. Normalizer Functions: identity, keyless settings, code =="
az functionapp identity assign -g $RG -n $FUNC \
  --identities "$(az identity show -g $RG -n id-ingest --query id -o tsv)" -o none
ING_CLIENT=$(az identity show -g $RG -n id-ingest --query clientId -o tsv)
az functionapp config appsettings set -g $RG -n $FUNC -o none --settings \
  "EventHubConnection__fullyQualifiedNamespace=$EH.servicebus.windows.net" \
  "EventHubConnection__credential=managedidentity" \
  "EventHubConnection__clientId=$ING_CLIENT" \
  "AZURE_CLIENT_ID=$ING_CLIENT" \
  "STORAGE_ACCOUNT_URL=https://$ST.blob.core.windows.net"
if command -v func >/dev/null; then
  scripts/build_functionapp.sh
  (cd build/functionapp && func azure functionapp publish $FUNC --python)
else
  echo "   Functions Core Tools not found: install them, then run"
  echo "   scripts/build_functionapp.sh && (cd build/functionapp && func azure functionapp publish $FUNC --python)"
fi

echo "== 12. Match engine Container App (build, push, deploy) =="
# Built locally: ACR Tasks (cloud builds) are not allowed on student subscriptions
if docker info >/dev/null 2>&1; then
  scripts/deploy_engine.sh
else
  echo "   Docker is not running: start Docker Desktop, then run  SUFFIX=$SUFFIX RG=$RG scripts/deploy_engine.sh"
fi

echo "== 13. Writing connection strings to .env for local tools (keep this file out of Git) =="
{
  echo "EVENTHUB_CONNECTION=$(az eventhubs namespace authorization-rule keys list \
      --resource-group $RG --namespace-name $EH --name RootManageSharedAccessKey \
      --query primaryConnectionString -o tsv)"
  echo "COSMOS_CONNECTION=$(az cosmosdb keys list --name $COSMOS --resource-group $RG \
      --type connection-strings --query 'connectionStrings[0].connectionString' -o tsv)"
  echo "STORAGE_CONNECTION=$(az storage account show-connection-string \
      --name $ST --resource-group $RG -o tsv)"
  echo "COSMOS_DATABASE=offball"
  echo "COSMOS_CONTAINER=events"
} > .env
grep -qx ".env" .gitignore 2>/dev/null || echo ".env" >> .gitignore

echo ""
echo "Done. Resources are in resource group: $RG"
echo "Stop the engine when not testing:  RG=$RG scripts/engine.sh stop"
echo "Start it again:                    RG=$RG scripts/engine.sh start"
