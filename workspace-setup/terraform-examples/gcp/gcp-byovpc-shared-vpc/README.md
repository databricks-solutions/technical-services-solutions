## GCP BYOVPC Terraform Deployment (Shared / Existing VPC)

Provisions a Databricks workspace on GCP using an **existing or shared VPC** — no new network is created. The VPC can live in the same project as the workspace or in a separate host project (Shared VPC).

---

### What Gets Created

- Databricks MWS Network referencing the existing VPC/subnet
- Databricks Workspace attached to that network
- Admin user added to the workspace and assigned to the `admins` group
- *(Optional)* Unity Catalog metastore assignment, if `metastore_id` is provided
- GCS buckets for workspace cloud storage (created automatically by Databricks)

> **Not created:** VPC, subnet, or metastore — these are referenced as-is and remain untouched on `terraform destroy`.

---

### Repository Structure

| File | Description |
|------|-------------|
| `variables.tf` | All input variable definitions |
| `versions.tf` | Required Terraform providers and versions |
| `providers.tf` | Google and Databricks provider configuration |
| `network.tf` | Data sources referencing the existing VPC and subnet |
| `databricks.tf` | MWS network, workspace, metastore assignment, and admin user |
| `outputs.tf` | Output values after deployment |
| `terraform.tfvars.example` | Template for variable values |
| `service-account-impersonation.md` | Guide for using service account impersonation |

---

### Prerequisites

- Terraform v1.3+
- Google Cloud SDK (`gcloud`) installed and authenticated
- A Google Service Account (GSA) with `roles/Owner` on the service project
- A Databricks Account — [Subscribe from GCP Marketplace](https://docs.databricks.com/gcp/en/admin/account-settings-gcp/create-subscription)
- An existing VPC and subnet (names + project ID where they reside)
- *(Optional)* An existing Unity Catalog metastore ID

---

### Authentication

Set up the GSA and export an access token before running Terraform:

```bash
gcloud config set project <SERVICE_PROJECT_ID>
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
| `google_project_name` | string | Yes | GCP project ID where the workspace will be created (service project) |
| `google_region` | string | Yes | GCP region (e.g. `us-central1`) |
| `databricks_account_id` | string | Yes | Databricks Account ID |
| `databricks_workspace_name` | string | Yes | Name for the new Databricks workspace |
| `databricks_admin_user` | string | Yes | Admin user email — must already exist at the Databricks Account level |
| `vpc_network_project_id` | string | Yes | Project ID where the VPC resides. Set equal to `google_project_name` if VPC is in the same project |
| `vpc_name` | string | Yes | Name of the existing VPC network |
| `subnet_name` | string | Yes | Name of the existing subnet |
| `metastore_id` | string | No | Unity Catalog metastore ID. Leave empty (`""`) for auto-create/auto-assign behavior |

**Same project vs. Shared VPC:**

| Scenario | `google_project_name` | `vpc_network_project_id` |
|---|---|---|
| VPC in the **same** project | `my-project` | `my-project` |
| VPC in a **different** host project (Shared VPC) | `my-service-project` | `my-host-project` |

---

### Shared VPC — Additional Permissions

When the VPC is in a different host project, the GSA needs the following roles granted on the **host project**:

```bash
gcloud projects add-iam-policy-binding <VPC_HOST_PROJECT_ID> \
  --member="serviceAccount:<GSA_EMAIL>" \
  --role="roles/compute.networkUser"

gcloud projects add-iam-policy-binding <VPC_HOST_PROJECT_ID> \
  --member="serviceAccount:<GSA_EMAIL>" \
  --role="roles/compute.networkViewer"
```

Also ensure:
- Shared VPC is enabled on the host project: `gcloud compute shared-vpc enable <HOST_PROJECT>`
- The service project is attached: `gcloud compute shared-vpc associated-projects add <SERVICE_PROJECT> --host-project <HOST_PROJECT>`
- The Compute API is enabled on the service project: `gcloud services enable compute.googleapis.com --project <SERVICE_PROJECT_ID>`

---

### Unity Catalog Metastore Behavior

Metastores are **region-specific** — one per region per Databricks account.

- **First workspace in a region:** Databricks auto-creates a metastore and assigns it. Leave `metastore_id` empty.
- **Auto-assign enabled:** If *"Automatically assign new workspaces to this metastore"* is on in the Account Console, the metastore is assigned automatically. Leave `metastore_id` empty.
- **Manual assignment needed:** If auto-assign is off, or you need a specific metastore, provide its ID in `metastore_id`.

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
google_project_name          = "<databricks-service-project>"
google_region                = "<google-region>"

databricks_account_id         = "<account-id>"
databricks_workspace_name     = "<workspace-name>"
databricks_admin_user         = "<admin-user-email>"

vpc_network_project_id = "<vpc-host-project>"
vpc_name               = "<existing-vpc-name>"
subnet_name            = "<existing-subnet-name>"

metastore_id = ""  # Leave empty for auto-create/auto-assign
```

#### 3. With CLI flags

```bash
terraform apply \
  -var 'google_service_account_email=<sa>@<project>.iam.gserviceaccount.com' \
  -var 'google_project_name=<service-project>' \
  -var 'google_region=us-central1' \
  -var 'databricks_account_id=<account-id>' \
  -var 'databricks_workspace_name=<workspace-name>' \
  -var 'databricks_admin_user=<admin-email>' \
  -var 'vpc_network_project_id=<vpc-host-project>' \
  -var 'vpc_name=<vpc-name>' \
  -var 'subnet_name=<subnet-name>'
```

#### 4. With environment variables

```bash
export TF_VAR_google_service_account_email=<sa>@<project>.iam.gserviceaccount.com
export TF_VAR_google_project_name=<service-project>
export TF_VAR_google_region=us-central1
export TF_VAR_databricks_account_id=<account-id>
export TF_VAR_databricks_workspace_name=<workspace-name>
export TF_VAR_databricks_admin_user=<admin-email>
export TF_VAR_vpc_network_project_id=<vpc-host-project>
export TF_VAR_vpc_name=<vpc-name>
export TF_VAR_subnet_name=<subnet-name>

terraform apply
```

After `apply` completes, retrieve outputs:

```bash
terraform output -raw workspace_url
terraform output metastore_assignment
```

---

### Validation

After a successful apply:

```bash
# Confirm no drift
terraform plan

# Check VPC and subnet exist
gcloud compute networks describe <VPC_NAME> --project <VPC_HOST_PROJECT_ID>
gcloud compute networks subnets describe <SUBNET_NAME> --region <REGION> --project <VPC_HOST_PROJECT_ID>
```

- Open the `workspace_url` in a browser and verify the workspace loads
- Confirm the admin user appears in the workspace admin console with admin privileges
- *(If metastore provided)* Navigate to **Data** in the workspace to confirm the metastore is attached

---

### Troubleshooting

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| Permission errors (403) | GSA missing roles | Check roles on both service project and host project (for Shared VPC) |
| API not enabled | Compute API disabled | Run `gcloud services enable compute.googleapis.com --project <SERVICE_PROJECT_ID>` |
| Authentication failure | Expired access token | Re-run `export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)` |
| VPC/Subnet not found | Wrong name or project | Verify `vpc_name`, `subnet_name`, and `vpc_network_project_id`; subnet must be in `google_region` |
| Shared VPC permission error | Missing network roles on host | Grant `roles/compute.networkUser` and `roles/compute.networkViewer` on the host project |
| Metastore assignment error | Invalid or wrong-region metastore | Verify `metastore_id` exists in the same region as the workspace |

> The Databricks accounts host for GCP is always `https://accounts.gcp.databricks.com`.

---

### Teardown

```bash
terraform destroy
```

This removes the Databricks workspace, MWS network reference, metastore assignment (if created), and admin user. The existing VPC, subnet, and metastore are **not affected**.

---

### Architecture

```
Databricks Workspace on GCP (Shared / Existing VPC)
│
├─ [Host Project] Existing VPC (google_compute_network)
│     └─ Existing Subnet (google_compute_subnetwork)
│
└─ [Service Project] Databricks (Accounts Provider)
      ├─ MWS Network → references existing VPC/Subnet
      ├─ Workspace
      │    └─ (Optional) Metastore Assignment
      └─ (Workspace Provider)
           ├─ data: admins group
           ├─ databricks_user (admin)
           └─ databricks_group_member → assigns admin to admins group
```
