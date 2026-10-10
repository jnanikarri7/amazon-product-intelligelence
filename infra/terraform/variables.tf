variable "resource_group_name" {
  type        = string
  description = "Resource group that holds all NFL platform resources."
  default     = "rg-nfl-predict"
}

variable "location" {
  type        = string
  description = "Azure region. Pick one close to you with Databricks + DS-series quota (e.g. eastus, eastus2, westus2)."
  default     = "eastus"
}

variable "storage_account_name" {
  type        = string
  description = "Globally unique ADLS Gen2 account name. 3-24 chars, lowercase letters + digits only."
  # No default on purpose: must be globally unique. Set in terraform.tfvars.
}

variable "databricks_workspace_name" {
  type        = string
  description = "Azure Databricks workspace name."
  default     = "dbw-nfl-predict"
}

variable "databricks_sku" {
  type        = string
  description = "Databricks SKU. 'standard' is cheapest and sufficient (Databricks-backed secret scopes work). 'premium' adds Key Vault-backed scopes + RBAC but costs more per DBU."
  default     = "standard"
}

variable "service_principal_name" {
  type        = string
  description = "Azure AD app registration / service principal display name used by Databricks to read ADLS."
  default     = "sp-nfl-databricks"
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to every resource (handy for cost tracking in Azure Cost Management)."
  default = {
    project     = "nfl-prediction-platform"
    environment = "dev"
    owner       = "portfolio"
    cost_center = "azure-for-students"
  }
}
