#!/usr/bin/env bash
# OffBall Lane 1: Azure setup for data ingestion (from the LLD, sections 8 and 10)
# Run after: az login
# Usage: bash azure-setup.sh
set -e

# ---------- 0. Names (change SUFFIX to something unique, e.g. initials + 3 digits) ----------
SUFFIX=kr2610
RG=offball-rg
LOC=westus2                   # if a step fails with RequestDisallowedByAzure, pick an allowed region
EH=offball-eh-$SUFFIX         # Event Hubs namespace
ST=offballst$SUFFIX           # data storage: bronze, frames, dead letters
FUNCST=offballfn$SUFFIX       # separate storage just for the Function App
COSMOS=offball-cosmos-$SUFFIX
FUNC=offball-ingest-$SUFFIX
ACAENV=offball-env

echo "== 1. Registering Azure services on this subscription (one time) =="
for p in Microsoft.EventHub Microsoft.Storage Microsoft.DocumentDB Microsoft.Web \
         Microsoft.App Microsoft.OperationalInsights Microsoft.Insights; do
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

echo "== 4. Storage for Bronze, Silver frames and dead letters =="
az storage account create --name $ST --resource-group $RG --location $LOC \
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false --hns true -o none
for c in bronze silver-frames dead-letter; do
  az storage container create --account-name $ST --name $c --auth-mode key -o none
done

echo "== 5. Cosmos DB (serverless), database and events container (takes ~5-10 min) =="
az cosmosdb create --name $COSMOS --resource-group $RG \
  --locations regionName=$LOC --capabilities EnableServerless -o none
az cosmosdb sql database create --account-name $COSMOS --resource-group $RG --name offball -o none
az cosmosdb sql container create --account-name $COSMOS --resource-group $RG \
  --database-name offball --name events --partition-key-path /match_id -o none

echo "== 6. Function App on Flex Consumption (also creates Application Insights) =="
az storage account create --name $FUNCST --resource-group $RG --location $LOC \
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false -o none
az functionapp create --resource-group $RG --name $FUNC --storage-account $FUNCST \
  --flexconsumption-location $LOC --runtime python --runtime-version 3.11 -o none

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
SUB=$(az account show --query id -o tsv)
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/managedEnvironments/$ACAENV?api-version=2024-03-01" \
  --body "{\"location\":\"$LOC\",\"properties\":{\"workloadProfiles\":[{\"name\":\"Consumption\",\"workloadProfileType\":\"Consumption\"}],\"zoneRedundant\":false}}" \
  -o none
# The PUT returns while provisioning is still running; wait for it to finish
until s=$(az rest --method get \
    --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/managedEnvironments/$ACAENV?api-version=2024-03-01" \
    --query properties.provisioningState -o tsv) && [ "$s" != "InProgress" ] && [ "$s" != "Waiting" ]; do
  sleep 15
done
[ "$s" = "Succeeded" ] || { echo "Container Apps environment ended in state: $s"; exit 1; }

echo "== 9. Writing connection strings to .env (keep this file out of Git) =="
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
echo "Event Hubs Capture is on for raw-events and raw-tracking (writes to $ST/bronze)."
