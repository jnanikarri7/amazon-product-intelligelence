terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.47"
    }
  }
}

provider "azurerm" {
  # Reads auth from `az login`. Students subscription is auto-selected if it's your default.
  features {}
}

provider "azuread" {}

data "azurerm_client_config" "current" {}

# ----------------------------------------------------------------------------
# 1. Resource group — the logical container for everything.
# ----------------------------------------------------------------------------
resource "azurerm_resource_group" "nfl" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

# ----------------------------------------------------------------------------
# 2. ADLS Gen2 storage account.
#    is_hns_enabled=true is what makes it "Gen2" (hierarchical namespace) vs
#    plain Blob. Standard tier + LRS + Hot = cheapest viable config.
# ----------------------------------------------------------------------------
resource "azurerm_storage_account" "lake" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.nfl.name
  location                 = azurerm_resource_group.nfl.location
  account_tier             = "Standard"
  account_replication_type = "LRS" # locally redundant = cheapest; fine for a portfolio lake
  account_kind             = "StorageV2"
  is_hns_enabled           = true  # <-- enables ADLS Gen2 / abfss://
  access_tier              = "Hot"
  min_tls_version          = "TLS1_2"
  tags                     = var.tags
}

# ----------------------------------------------------------------------------
# 3. Medallion containers (ADLS Gen2 filesystems): bronze / silver / gold.
# ----------------------------------------------------------------------------
resource "azurerm_storage_data_lake_gen2_filesystem" "bronze" {
  name               = "bronze"
  storage_account_id = azurerm_storage_account.lake.id
}

resource "azurerm_storage_data_lake_gen2_filesystem" "silver" {
  name               = "silver"
  storage_account_id = azurerm_storage_account.lake.id
}

resource "azurerm_storage_data_lake_gen2_filesystem" "gold" {
  name               = "gold"
  storage_account_id = azurerm_storage_account.lake.id
}

# ----------------------------------------------------------------------------
# 4. Service principal (app registration) Databricks will use to read the lake.
#    Preferred over account keys: scoped, rotatable, auditable.
# ----------------------------------------------------------------------------
resource "azuread_application" "databricks" {
  display_name = var.service_principal_name
}

resource "azuread_service_principal" "databricks" {
  client_id = azuread_application.databricks.client_id
}

resource "azuread_service_principal_password" "databricks" {
  service_principal_id = azuread_service_principal.databricks.id
}

# Grant the SP data-plane read/write ONLY on this storage account (least privilege).
resource "azurerm_role_assignment" "sp_blob_contributor" {
  scope                = azurerm_storage_account.lake.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azuread_service_principal.databricks.object_id
}

# ----------------------------------------------------------------------------
# 5. Azure Databricks workspace.
# ----------------------------------------------------------------------------
resource "azurerm_databricks_workspace" "nfl" {
  name                = var.databricks_workspace_name
  resource_group_name = azurerm_resource_group.nfl.name
  location            = azurerm_resource_group.nfl.location
  sku                 = var.databricks_sku
  tags                = var.tags
}
