#!/usr/bin/env bash
# Stop, start or check the match engine Container App. Stopped = 0 replicas, nothing billed for
# compute; starting resumes from the last checkpoint.
# Usage: scripts/engine.sh stop|start|status
set -euo pipefail

RG=${RG:-offball-rg}
APP=${APP:-offball-engine}
SUB=$(az account show --query id -o tsv)
URL="https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/$APP"

case "${1:-status}" in
  stop|start)
    az rest --method post --url "$URL/$1?api-version=2024-03-01" -o none
    want=$([ "$1" = stop ] && echo Stopped || echo Running)
    until [ "$(az rest --method get --url "$URL?api-version=2024-03-01" --query properties.runningStatus -o tsv)" = "$want" ]; do
      sleep 5
    done
    echo "$APP: $want" ;;
  status)
    az rest --method get --url "$URL?api-version=2024-03-01" \
      --query "{status:properties.runningStatus,image:properties.template.containers[0].image}" -o tsv ;;
  *)
    echo "usage: $0 stop|start|status" >&2; exit 2 ;;
esac
