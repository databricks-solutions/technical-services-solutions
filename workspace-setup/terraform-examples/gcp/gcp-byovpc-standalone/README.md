## GCP BYOVPC Terraform Deployment (Standalone)

Provisions a full GCP network and a Databricks workspace attached to it — everything is created from scratch within a single project.

---

### What Gets Created

- Google Compute Network (VPC)
- Subnet with `private_ip_google_access` enabled (allows cluster nodes to reach Google APIs without public IPs)
- Cloud Router and Cloud NAT (auto-allocated IPs)
- Databricks MWS Network referencing the VPC/subnet
- Databricks Workspace attached to that network
- Admin user added to the workspace and assigned to the `admins` group
- GCS buckets for workspace cloud storage (created automatically by Databricks)

> **On `terraform destroy`:** All resources above are removed. Nothing external is referenced, so teardown is self-contained (see [Teardown](#teardown) for known VPC deletion errors).

---

### Repository Structure

| File | Description |
|------|-------------|
| `variables.tf` | All input variable definitions |
| `versions.tf` | Required Terraform providers and versions |
| `providers.tf` | Google and Databricks provider configuration |
| `network.tf` | GCP VPC, subnet, router, and NAT resources |
| `databricks.tf` | MWS network, workspace, and admin user with group assignment |
| `outputs.tf` | Output values after deployment |
| `terraform.tfvars.example` | Template for variable values |
| `service-account-impersonation.md` | Guide for using service account impersonation |

---

### Prerequisites

- Terraform v1.3+
- Google Cloud SDK (`gcloud`) installed and authenticated
- A Google Service Account (GSA) with `roles/Owner` on the project
- A Databricks Account — [Subscribe from GCP Marketplace](https://docs.databricks.com/gcp/en/admin/account-settings-gcp/create-subscription)

Enable required APIs on your GCP project:

```bash
gcloud services enable compute.googleapis.com --project <PROJECT_ID>
```

---

### Authentication

Set up the GSA and export an access token before running Terraform:

```bash
gcloud config set project <PROJECT_ID>
gcloud config set auth/impersonate_service_account <GSA_EMAIL>
export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)
```

Then add the GSA to your Databricks Account Console:

1. [Login](https://docs.gcp.databricks.com/administration-guide/users-groups/users.html#manage-users-in-your-account) to the account console
2. [Add](https://docs.gcp.databricks.com/administration-guide/users-groups/users.html#add-users-to-your-account-using-the-account-console) the GSA as an account user
3. [Assign](https://docs.gcp.databricks.com/administration-guide/users-groups/users.html#assign-account-admin-roles-to-a-user) the account admin role to the GSA

> **Recommended:** For more granular permissions, use service account impersonation — see [service-account-impersonation.md](service-account-impersonation.md).

---

### Configuration

Copy the example file and fill in your values:

```bash
cp terraform.tfvars.example terraform.tfvars
```

| Variable | Type | Required | Description |
|----------|------|----------|-------------|
| `google_service_account_email` | string | Yes | GSA email used by providers |
| `google_project_name` | string | Yes | GCP project ID where all resources will be created |
| `google_region` | string | Yes | GCP region (e.g. `us-central1`) |
| `databricks_account_id` | string | Yes | Databricks Account ID |
| `databricks_workspace_name` | string | Yes | Name for the new Databricks workspace |
| `databricks_admin_user` | string | Yes | Admin user email — must already exist at the Databricks Account level |
| `subnet_cidr` | string | Yes | CIDR block for the Databricks subnet (e.g. `10.10.0.0/20`) |

---

### Usage

#### 1. Initialize and deploy

```bash
terraform init
terraform validate
terraform plan
terraform apply
```

#### 2. With a `terraform.tfvars` file (recommended)

```hcl
google_service_account_email = "<sa>@<project>.iam.gserviceaccount.com"
google_project_name          = "<project>"
google_region                = "us-central1"

databricks_account_id         = "<account-id>"
databricks_workspace_name     = "<workspace-name>"
databricks_admin_user         = "<admin-user-email>"

subnet_cidr = "10.10.0.0/20"
```

#### 3. With CLI flags

```bash
terraform apply \
  -var 'google_service_account_email=<sa>@<project>.iam.gserviceaccount.com' \
  -var 'google_project_name=<project>' \
  -var 'google_region=us-central1' \
  -var 'databricks_account_id=<account-id>' \
  -var 'databricks_workspace_name=<workspace-name>' \
  -var 'databricks_admin_user=<admin-user-email>' \
  -var 'subnet_cidr=10.10.0.0/20'
```

#### 4. With environment variables

```bash
export TF_VAR_google_service_account_email=<sa>@<project>.iam.gserviceaccount.com
export TF_VAR_google_project_name=<project>
export TF_VAR_google_region=us-central1
export TF_VAR_databricks_account_id=<account-id>
export TF_VAR_databricks_workspace_name=<workspace-name>
export TF_VAR_databricks_admin_user=<admin-user-email>
export TF_VAR_subnet_cidr=10.10.0.0/20

terraform apply
```

After `apply` completes, retrieve outputs:

```bash
terraform output -raw workspace_url
```

---

### Validation

After a successful apply:

```bash
# Confirm no drift
terraform plan

# Check GCP network resources
gcloud compute networks list --filter="name~^databricks-vpc-" --project <PROJECT_ID>
gcloud compute networks subnets list --filter="name~^databricks-subnet-" --regions <REGION> --project <PROJECT_ID>
gcloud compute routers list --filter="name~^databricks-router-" --regions <REGION> --project <PROJECT_ID>
```

- Open the `workspace_url` in a browser and verify the workspace loads
- Confirm the admin user appears in the workspace admin console with admin privileges

---

### Troubleshooting

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| Permission errors (403) | GSA missing roles | Ensure GSA has `roles/Owner` on the project |
| API not enabled | Compute API disabled | Run `gcloud services enable compute.googleapis.com --project <PROJECT_ID>` |
| Authentication failure | Expired access token | Re-run `export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)` |
| Cluster startup failures | Missing private Google access | Ensure `private_ip_google_access = true` on the subnet |

> The Databricks accounts host for GCP is always `https://accounts.gcp.databricks.com`.

---

### Teardown

```bash
terraform destroy
```

#### VPC "already being used" errors

If Databricks created firewall rules or other resources inside the VPC, GCP will block VPC deletion. Example error:

```
Error: Error waiting for Deleting Network: The network resource
'projects/<PROJECT_ID>/global/networks/databricks-vpc-<suffix>'
is already being used by 'projects/<PROJECT_ID>/global/firewalls/databricks-<digits>-ingress'
```

**Fix — destroy in dependency order:**

```bash
terraform destroy -target=databricks_mws_workspaces.databricks_workspace
terraform destroy -target=google_compute_router_nat.databricks_nat -target=google_compute_router.databricks_router
terraform destroy
```

**If the VPC is still blocked, manually remove dependent resources:**

Firewall rules:
```bash
gcloud compute firewall-rules list --filter="network~^databricks-vpc-" --project <PROJECT_ID>
gcloud compute firewall-rules delete <RULE_NAME> --project <PROJECT_ID>
```

NAT and Router:
```bash
gcloud compute routers nats delete <NAT_NAME> --router <ROUTER_NAME> --region <REGION> --project <PROJECT_ID>
gcloud compute routers delete <ROUTER_NAME> --region <REGION> --project <PROJECT_ID>
```

Subnets:
```bash
gcloud compute networks subnets delete <SUBNET_NAME> --region <REGION> --project <PROJECT_ID>
```

Then re-run:
```bash
terraform destroy
```

---

### Architecture

```
Databricks Workspace on GCP (Standalone VPC)
│
└─ [GCP Project]
      ├─ VPC (google_compute_network)
      │    ├─ Subnet — private_ip_google_access enabled
      │    ├─ Cloud Router
      │    └─ Cloud NAT
      │
      └─ Databricks (Accounts Provider)
            ├─ MWS Network → references VPC/Subnet
            ├─ Workspace
            └─ (Workspace Provider)
                  ├─ data: admins group
                  ├─ databricks_user (admin)
                  └─ databricks_group_member → assigns admin to admins group
```
