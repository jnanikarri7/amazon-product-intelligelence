#!/usr/bin/env bash
# =============================================================================
# Phase 1 — Azure CLI equivalent of the Terraform in infra/terraform/.
# Use this if you prefer imperative setup, or to understand what Terraform does.
# Idempotent-ish: re-running mostly no-ops, but it does NOT manage state.
#
# Prereqs:  az login   (and `az account set --subscription "<Azure for Students>"`)
# Run:      bash scripts/az_setup.sh
# =============================================================================
set -euo pipefail

# ---- Edit these ----
RG="rg-nfl-predict"
LOCATION="eastus"
STORAGE="stnflpredictXX"              # <-- MUST be globally unique, lowercase+digits
DBW="dbw-nfl-predict"
SP_NAME="sp-nfl-databricks"
# --------------------

echo ">>> Using subscription:"
az account show --query "{name:name, id:id}" -o table

# 1. Resource group
az group create -n "$RG" -l "$LOCATION" -o none
echo ">>> Resource group '$RG' ready."

# 2. ADLS Gen2 storage account (hierarchical namespace = Gen2)
az storage account create \
  --name "$STORAGE" --resource-group "$RG" --location "$LOCATION" \
  --sku Standard_LRS --kind StorageV2 --hns true \
  --access-tier Hot --min-tls-version TLS1_2 -o none
echo ">>> Storage account '$STORAGE' ready (ADLS Gen2)."

# 3. Medallion containers (filesystems). Uses your AAD identity for the data plane.
for FS in bronze silver gold; do
  az storage fs create -n "$FS" --account-name "$STORAGE" --auth-mode login -o none
  echo ">>> Container '$FS' ready."
done

# 4. Service principal scoped to this storage account only (least privilege)
STORAGE_ID=$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)
SP_JSON=$(az ad sp create-for-rbac \
  --name "$SP_NAME" \
  --role "Storage Blob Data Contributor" \
  --scopes "$STORAGE_ID" \
  -o json)

CLIENT_ID=$(echo "$SP_JSON"   | python -c "import sys,json;print(json.load(sys.stdin)['appId'])")
CLIENT_SECRET=$(echo "$SP_JSON" | python -c "import sys,json;print(json.load(sys.stdin)['password'])")
TENANT_ID=$(echo "$SP_JSON"   | python -c "import sys,json;print(json.load(sys.stdin)['tenant'])")

# 5. Databricks workspace (standard SKU = cheapest)
az databricks workspace create \
  --name "$DBW" --resource-group "$RG" --location "$LOCATION" \
  --sku standard -o none
DBW_URL=$(az databricks workspace show -n "$DBW" -g "$RG" --query workspaceUrl -o tsv)
echo ">>> Databricks workspace ready: https://$DBW_URL"

echo ""
echo "============================================================"
echo " SAVE THESE (feed into Databricks secret scope, step 7):"
echo "   TENANT_ID    = $TENANT_ID"
echo "   CLIENT_ID    = $CLIENT_ID"
echo "   CLIENT_SECRET= $CLIENT_SECRET"
echo "   STORAGE      = $STORAGE"
echo "   DBW_URL      = https://$DBW_URL"
echo "============================================================"
echo ""
echo "NEXT: create a Databricks secret scope + add these secrets."
echo "Install the CLI:  pip install databricks-cli"
echo "Auth:             databricks configure --token   (host = https://$DBW_URL)"
cat <<EOF

# 6. Create secret scope and store SP credentials (run after CLI auth):
databricks secrets create-scope nfl-adls
databricks secrets put-secret nfl-adls sp-client-id     --string-value "$CLIENT_ID"
databricks secrets put-secret nfl-adls sp-client-secret --string-value "$CLIENT_SECRET"
databricks secrets put-secret nfl-adls sp-tenant-id     --string-value "$TENANT_ID"
EOF
