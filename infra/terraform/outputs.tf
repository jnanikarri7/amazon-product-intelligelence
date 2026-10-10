# These feed directly into the Databricks secret scope (see scripts/az_setup.sh
# step 7 and databricks/notebooks/00_connect_adls.py).
#
# Pull secrets with:  terraform output -raw sp_client_secret

output "storage_account_name" {
  value       = azurerm_storage_account.lake.name
  description = "Use in abfss://<container>@<this>.dfs.core.windows.net/"
}

output "databricks_workspace_url" {
  value       = "https://${azurerm_databricks_workspace.nfl.workspace_url}"
  description = "Open this to launch the Databricks workspace."
}

output "sp_tenant_id" {
  value       = data.azurerm_client_config.current.tenant_id
  description = "Azure AD tenant ID (directory ID) for the OAuth token endpoint."
}

output "sp_client_id" {
  value       = azuread_application.databricks.client_id
  description = "Service principal application (client) ID."
}

output "sp_client_secret" {
  value       = azuread_service_principal_password.databricks.value
  description = "Service principal secret. SENSITIVE — never commit."
  sensitive   = true
}
