## GCP BYOVPC Terraform Deployment (Shared / Existing VPC)

This repository provisions a Databricks workspace on Google Cloud using an **existing / shared VPC** instead of creating a new one. The VPC can reside in the same project as the Databricks workspace (Existing VPC) or in a different host project (Shared VPC). It also adds a specified admin user to the workspace.

### Repository Structure
- `variables.tf`: All input variable definitions
- `versions.tf`: Terraform required providers and versions
- `providers.tf`: Provider configuration (Google, Databricks)
- `network.tf`: Data sources to reference the existing VPC and subnet
- `databricks.tf`: Databricks MWS network, workspace, optional metastore assignment, and admin user
- `outputs.tf`: All outputs
- `terraform.tfvars.example`: Example variable values
- `service-account-impersonation.md`: Guide for Service Account impersonation

### Prerequisites
- Terraform installed (v1.3+ recommended)
- Google Cloud SDK (`gcloud`) installed
- A Google Service Account (GSA) with required permissions
- A Databricks Account - Guide for Account Creation : [Subscribe to Databricks from GCP Marketplace](https://docs.databricks.com/gcp/en/admin/account-settings-gcp/create-subscription)
- An **existing VPC and subnet** - VPC name, subnet name, and the project ID where they reside
- (Optional) An **existing Unity Catalog metastore** - Metastore ID if a metastore already exists for the region


### Unity Catalog Metastore Behavior

Unity Catalog metastores are **region-specific** - there can only be one metastore per region per Databricks account.

- **First workspace in a region:** If no metastore exists for the region / no new workspace in the region yet, Databricks **automatically creates** a metastore and assigns it to the workspace. In this case, leave `metastore_id` empty (`""`).
- **Subsequent workspaces in the same region:** If a metastore already exists for the region (created by a previous workspace), Databricks will **not** automatically assign it to new workspaces. You must provide the existing `metastore_id` so that Terraform assigns it to the new workspace.


### Shared VPC Permissions
When using a shared VPC (VPC in a different host project), the GSA needs additional permissions:
- `roles/compute.networkUser` on the host project (or on the specific subnet)
- `roles/compute.networkViewer` on the host project

Grant these on the **host project** (where the VPC lives):
```
gcloud projects add-iam-policy-binding <VPC_HOST_PROJECT_ID> \
  --member="serviceAccount:<GSA_NAME>@<SERVICE_PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/compute.networkUser"

gcloud projects add-iam-policy-binding <VPC_HOST_PROJECT_ID> \
  --member="serviceAccount:<GSA_NAME>@<SERVICE_PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/compute.networkViewer"
```

Enable required APIs on the Databricks service project:
```
gcloud services enable compute.googleapis.com --project <SERVICE_PROJECT_ID>
```

### Authentication
Use a Google Service Account with roles/Owner permission to the project and run the below commands.
```
gcloud config set project <SERVICE_PROJECT_ID>
gcloud config set auth/impersonate_service_account <GSA_NAME>@<SERVICE_PROJECT_ID>.iam.gserviceaccount.com
export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)
```

Follow these steps to add the service account to the Databricks account console:

- [Login](https://docs.gcp.databricks.com/administration-guide/users-groups/users.html#manage-users-in-your-account) into the account console.
- [Add](https://docs.gcp.databricks.com/administration-guide/users-groups/users.html#add-users-to-your-account-using-the-account-console) service-account as an accounts user.
- [Assign](https://docs.gcp.databricks.com/administration-guide/users-groups/users.html#assign-account-admin-roles-to-a-user) accounts admin role to the service account.

**(RECOMMENDED) For more refined and granular level of permissions, use service account impersonation, see [service-account-impersonation.md](service-account-impersonation.md).**

### Variables
All variable definitions are in `variables.tf`. Refer to `terraform.tfvars.example` as a template and provide the values during runtime in CLI.

- `google_service_account_email` (string, required): Email of the GSA used by providers
- `google_project_name` (string, required): GCP project ID where the Databricks workspace will be created (service project)
- `google_region` (string, required): GCP region for resources (e.g., `us-central1`)
- `databricks_account_id` (string, required): Databricks Account ID
- `databricks_workspace_name` (string, required): Name for the Databricks workspace
- `databricks_admin_user` (string, required): Admin user email to add to the workspace (must be a valid Databricks user at the Account level)
- `vpc_network_project_id` (string, required): GCP project ID where the shared/existing VPC resides (host project). Set to the same value as `google_project_name` if the VPC is in the same project.
- `vpc_name` (string, required): Name of the existing VPC network to use
- `subnet_name` (string, required): Name of the existing subnet within the VPC to use
- `metastore_id` (string, optional, default `""`): Existing Unity Catalog metastore ID. If empty, no metastore assignment is made (Databricks auto-creates one for the first workspace in a region). If provided, the existing metastore is assigned to the workspace.

Example `terraform.tfvars.example`:
```
google_service_account_email = "<sa>@<project>.iam.gserviceaccount.com"
google_project_name          = "<databricks-service-project>"
google_region                = "<google-region>"

databricks_account_id          = "<account-id>"
databricks_workspace_name      = "<workspace-name>"
databricks_admin_user          = "<admin-user-email>"

vpc_network_project_id = "<vpc-host-project>"
vpc_name               = "<existing-vpc-name>"
subnet_name            = "<existing-subnet-name>"

# Leave metastore_id empty for the first workspace in a region (Databricks auto-creates one)
metastore_id = ""

# Use existing metastore for subsequent workspaces in the same region (uncomment and specify ID)
# metastore_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

### Usage Modes

#### First workspace in a region (leave metastore_id empty - Databricks auto-creates)
```
terraform apply \
  -var 'google_service_account_email=<sa>@<project>.iam.gserviceaccount.com' \
  -var 'google_project_name=<databricks-service-project>' \
  -var 'google_region=us-central1' \
  -var 'databricks_account_id=<account-id>' \
  -var 'databricks_workspace_name=<workspace-name>' \
  -var 'databricks_admin_user=<admin-user-email>' \
  -var 'vpc_network_project_id=<vpc-host-project>' \
  -var 'vpc_name=<existing-vpc-name>' \
  -var 'subnet_name=<existing-subnet-name>'
```

#### Subsequent workspaces in the same region (provide existing metastore ID)
```
terraform apply \
  -var 'google_service_account_email=<sa>@<project>.iam.gserviceaccount.com' \
  -var 'google_project_name=<databricks-service-project>' \
  -var 'google_region=us-central1' \
  -var 'databricks_account_id=<account-id>' \
  -var 'databricks_workspace_name=<workspace-name>' \
  -var 'databricks_admin_user=<admin-user-email>' \
  -var 'vpc_network_project_id=<vpc-host-project>' \
  -var 'vpc_name=<existing-vpc-name>' \
  -var 'subnet_name=<existing-subnet-name>' \
  -var 'metastore_id=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
```

Or with environment variables (TF_VAR_ prefix):
```
export TF_VAR_google_service_account_email=<sa>@<project>.iam.gserviceaccount.com
export TF_VAR_google_project_name=<databricks-service-project>
export TF_VAR_google_region=us-central1
export TF_VAR_databricks_account_id=<account-id>
export TF_VAR_databricks_workspace_name=<workspace-name>
export TF_VAR_databricks_admin_user=<admin-user-email>
export TF_VAR_vpc_network_project_id=<vpc-host-project>
export TF_VAR_vpc_name=<existing-vpc-name>
export TF_VAR_subnet_name=<existing-subnet-name>

# Optional: assign existing metastore (for subsequent workspaces in the same region)
# export TF_VAR_metastore_id=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

terraform apply
```

### Same Project vs Different Project (Shared VPC)

| Scenario | `google_project_name` | `vpc_network_project_id` |
|---|---|---|
| VPC in **same** project | `my-project` | `my-project` |
| VPC in **different** host project (Shared VPC) | `my-service-project` | `my-host-project` |

When using a shared VPC across projects, ensure that:
1. The GSA has `roles/compute.networkUser` and `roles/compute.networkViewer` on the host project
2. The subnet in the host project is shared with the service project
3. The VPC host project has Shared VPC enabled (`gcloud compute shared-vpc enable <HOST_PROJECT>`)
4. The service project is attached to the host project (`gcloud compute shared-vpc associated-projects add <SERVICE_PROJECT> --host-project <HOST_PROJECT>`)

### What Gets Created by the terraform script
- By default, Databricks creates GCS buckets for cloud storage
- Databricks MWS Network referencing the existing VPC/subnet
- Databricks Workspace attached to that network
- **If `metastore_id` is provided**: Metastore assignment - the existing Unity Catalog metastore is assigned to the workspace
- Admin user added to the workspace

### Step-by-Step Usage
From the repository root directory:
```
terraform init
terraform validate
terraform plan
terraform apply
```

After `apply` completes, view outputs:
```
terraform output
```
Key outputs:
- `workspace_url`: The URL of the created Databricks workspace
- `metastore_assignment`: The metastore ID assigned to the workspace (only when `metastore_id` is provided)

### Troubleshooting
- Permission errors (403): Ensure your GSA has the required roles on **both** the host project (for VPC access) and the service project (for workspace creation).
- API not enabled: Run the API enablement command shown above.
- Databricks account host is defaulted `https://accounts.gcp.databricks.com` for GCP.
- Authentication failures: Re-run the impersonation commands to refresh `GOOGLE_OAUTH_ACCESS_TOKEN`.
- VPC/Subnet not found: Verify the `vpc_name`, `subnet_name`, and `vpc_network_project_id` are correct. The subnet must exist in the specified `google_region`.
- Shared VPC permission errors: Ensure `roles/compute.networkUser` is granted on the host project for the GSA.
- Metastore assignment errors: Verify that the `metastore_id` is valid and that the metastore exists in the same region as the workspace.

### Teardown
To destroy all created resources:
```
terraform destroy
```

**Note:** Since the VPC and subnet are not managed by this Terraform configuration, `terraform destroy` will only remove the Databricks workspace, MWS network reference, the metastore assignment (if created), and the admin user. The existing VPC, subnet, and metastore remain untouched.

### Architecture
This module references an existing GCP shared VPC and provisions a Databricks workspace attached to that network. Optionally assigns an existing Unity Catalog metastore.

- Data sources look up the existing VPC and subnet from the host project.
- Databricks Accounts provider creates the MWS network reference (pointing to the shared VPC) and workspace.
- If `metastore_id` is provided, the existing metastore is assigned to the workspace via `databricks_metastore_assignment`.
- Databricks Workspace provider targets the created workspace to add the admin user.
- Resource names include a short random suffix to avoid collisions.

High-level diagram:
```
Databricks Workspace Creation (Shared / Existing VPC)
├─ Existing VPC (data.google_compute_network.existing_vpc) [in vpc_network_project_id]
│  └─ Existing Subnet (data.google_compute_subnetwork.existing_subnet) [in vpc_network_project_id]
└─ Databricks (Accounts)
   ├─ MWS Network (databricks_mws_networks.databricks_network) → references existing VPC/Subnet
   ├─ Workspace (databricks_mws_workspaces.databricks_workspace) [in google_project_name]
   │  └─ (Optional) Metastore Assignment (databricks_metastore_assignment.this) → uses var.metastore_id
   └─ Workspace (provider alias "workspace")
      ├─ data.databricks_group.admins
      └─ databricks_user.admin
```

### Validation
After applying, validate with the following:

- Terraform:
  - `terraform validate`
  - `terraform plan` (should show no changes immediately after apply)
  - `terraform output -raw workspace_url`

- Verify the existing VPC/subnet (from the host project):
```
gcloud compute networks describe <VPC_NAME> --project <VPC_HOST_PROJECT_ID>
gcloud compute networks subnets describe <SUBNET_NAME> --region <REGION> --project <VPC_HOST_PROJECT_ID>
```

- Databricks workspace:
  - Open the URL from `terraform output -raw workspace_url` in a browser.
  - Verify the workspace loads and the user exists in the workspace admin console.

- Unity Catalog metastore (only when `metastore_id` is provided):
  - In the workspace, navigate to **Data** to confirm the metastore is attached.
  - Run `terraform output metastore_assignment` to confirm the metastore ID.
