## GCP BYOVPC Terraform Deployment

This repository deploys a Customer-managed network on Google Cloud and provisions a Databricks workspace attached to that network. It also adds a specified user to the workspace.

### Repository Structure
- `variables.tf`: All input variable definitions
- `versions.tf`: Terraform required providers and versions
- `providers.tf`: Provider configuration (Google, Databricks)
- `network.tf`: GCP VPC, subnet, router, and NAT resources
- `databricks.tf`: Databricks MWS network, workspace, and admin user
- `outputs.tf`: All outputs
- `terraform.tfvars.example`: Example variable values (do not commit real secrets)
- `service-account-impersonation.md`: Guide for GSA impersonation

### Prerequisites
- Terraform installed (v1.3+ recommended)
- Google Cloud SDK (`gcloud`) installed
- A Google Service Account (GSA) with permissions to create networking resources
- A Databricks Account. Refer this guide - [Subscribe to Databricks from GCP Marketplace](https://docs.databricks.com/gcp/en/admin/account-settings-gcp/create-subscription)

Enable required APIs on your GCP project:
```
gcloud services enable compute.googleapis.com --project <PROJECT_ID>
```

### Authentication
Use a Google Service Account with roles/Owner permission to the project and run the below commands.
```
gcloud config set project <PROJECT_ID>
gcloud config set auth/impersonate_service_account <GSA_NAME>@<PROJECT_ID>.iam.gserviceaccount.com
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
- `google_project_name` (string, required): GCP project ID
- `google_region` (string, required): GCP region for resources (e.g., `us-central1`)
- `databricks_account_id` (string, required): Databricks Account ID
- `databricks_workspace_name` (string, required): Name for the Databricks workspace
- `databricks_admin_user` (string, required): Admin user email to add to the workspace (must be a valid Databricks user at the Account level)
 - `subnet_cidr` (string, required): CIDR block for the Databricks subnet

Pass variables via CLI (For example, refer below):
```
terraform plan \
  -var 'google_service_account_email=<sa>@<project>.iam.gserviceaccount.com' \
  -var 'google_project_name=<project>' \
  -var 'google_region=us-central1' \
  -var 'databricks_account_id=<account-id>' \
  -var 'databricks_workspace_name=<workspace-name>' \
  -var 'databricks_admin_user=<admin-user-email>' \
  -var 'subnet_cidr=10.10.0.0/20'

# Use the same -var flags with `terraform apply`
```

Or with environment variables (TF_VAR_ prefix):
```
export TF_VAR_google_service_account_email=<sa>@<project>.iam.gserviceaccount.com
export TF_VAR_google_project_name=<project>
export TF_VAR_google_region=us-central1
export TF_VAR_databricks_account_id=<account-id>
export TF_VAR_databricks_workspace_name=<workspace-name>
export TF_VAR_databricks_admin_user=<admin-user-email>
export TF_VAR_subnet_cidr=10.10.0.0/20

terraform apply
```

Example `terraform.tfvars.example`:
```
google_service_account_email = "<sa>@<project>.iam.gserviceaccount.com"
google_project_name          = "<project>"
google_region                = "us-central1"

databricks_account_id          = "<account-id>"
databricks_workspace_name      = "<workspace-name>"
databricks_admin_user          = "<admin-user-email>"

subnet_cidr = "10.10.0.0/20"
```

### What Gets Created by the terraform script
- Google Compute Network (VPC)
- Google Subnetwork in the specified region (CIDR is configurable via `subnet_cidr`)
- Google Cloud Router and Cloud NAT (Auto-allocated IPs)
- By default, Databricks creates GCS buckets for cloud storage
- Databricks Workspace attached to that network
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
Key output:
- `workspace_url`: The URL of the created Databricks workspace

### Troubleshooting
- Permission errors (403): Ensure your GSA has the required roles and that the correct project is set in `gcloud`.
- API not enabled: Run the API enablement command shown above.
 - Databricks account host is defaulted `https://accounts.gcp.databricks.com` for GCP.
- Authentication failures: Re-run the impersonation commands to refresh `GOOGLE_OAUTH_ACCESS_TOKEN`.

### Teardown
To destroy all created resources:
```
terraform destroy
```
#### Terraform destroy: VPC "already being used" errors
Example:
```
Error: Error waiting for Deleting Network: The network resource 'projects/<PROJECT_ID>/global/networks/databricks-vpc-<suffix>' is already being used by 'projects/<PROJECT_ID>/global/firewalls/databricks-<digits>-ingress'
```

Why this happens: GCP won’t let you delete a VPC while anything still references it (firewall rules, routes, subnets, VPNs, forwarding rules, etc.). If third-party tools created resources in your VPC (e.g., Databricks-managed firewall rules), you must remove those first.

Quick steps:
1) Destroy workspace and network in dependency order (if needed):
```
terraform destroy -target=databricks_mws_workspaces.databricks_workspace
terraform destroy -target=google_compute_router_nat.databricks_nat -target=google_compute_router.databricks_router
terraform destroy
```

2) If the VPC is still “in use”, check and delete dependent resources:
- Firewall rules referencing the VPC:
```
gcloud compute firewall-rules list --filter="network~^databricks-vpc-" --project <PROJECT_ID>
gcloud compute firewall-rules delete <RULE_NAME> --project <PROJECT_ID>
```
- NAT and Router (replace placeholders):
```
gcloud compute routers list --filter="name~^databricks-router-" --regions <REGION> --project <PROJECT_ID>
gcloud compute routers nats list --router <ROUTER_NAME> --region <REGION> --project <PROJECT_ID>
gcloud compute routers nats delete <NAT_NAME> --router <ROUTER_NAME> --region <REGION> --project <PROJECT_ID>
gcloud compute routers delete <ROUTER_NAME> --region <REGION> --project <PROJECT_ID>
```
- Subnets:
```
gcloud compute networks subnets list --filter="network~^databricks-vpc-" --regions <REGION> --project <PROJECT_ID>
gcloud compute networks subnets delete <SUBNET_NAME> --region <REGION> --project <PROJECT_ID>
```

3) Re-run:
```
terraform destroy
```

### Architecture
This module provisions a GCP network and a Databricks workspace attached to that network.

- Google provider creates VPC, subnet, router, and NAT in your project.
- Databricks Accounts provider creates the MWS network reference and workspace.
- Databricks Workspace provider targets the created workspace to add the admin user.
- Resource names include a short random suffix to avoid collisions.

High-level diagram:
```
Databricks Workspace Creation
├─ GCP Standalone VPC (google_compute_network.databricks_vpc)
│  ├─ Subnet (google_compute_subnetwork.databricks_subnet) [CIDR: var.subnet_cidr]
│  ├─ Router (google_compute_router.databricks_router)
│  └─ NAT (google_compute_router_nat.databricks_nat)
└─ Databricks (Accounts)
   ├─ MWS Network (databricks_mws_networks.databricks_network) → references VPC/Subnet
   └─ Workspace (databricks_mws_workspaces.databricks_workspace)
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

- GCP network resources (use your project ID):
```
gcloud compute networks list --filter="name~^databricks-vpc-" --project <PROJECT_ID>
gcloud compute networks subnets list --filter="name~^databricks-subnet-" --regions <REGION> --project <PROJECT_ID>
gcloud compute routers list --filter="name~^databricks-router-" --regions <REGION> --project <PROJECT_ID>
gcloud compute routers nats list --router=$(gcloud compute routers list --filter="name~^databricks-router-" --regions <REGION> --project <PROJECT_ID> --format="value(name)" | head -1) --region <REGION> --project <PROJECT_ID>
```

- Databricks workspace:
  - Open the URL from `terraform output -raw workspace_url` in a browser.
  - Verify the workspace loads and the user exists in the workspace admin console.

