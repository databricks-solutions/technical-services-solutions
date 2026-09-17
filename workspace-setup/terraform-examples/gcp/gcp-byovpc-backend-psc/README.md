## GCP BYOVPC Terraform Deployment — Backend Private Service Connect (PSC)

Provisions a Databricks workspace on GCP inside an **existing (customer-managed / shared) VPC** with **backend Private Service Connect** — private connectivity from the classic compute plane (your VPC) to the Databricks control plane. This creates the **two backend PSC endpoints** required for classic compute:

| # | Endpoint | Targets | Purpose |
|---|----------|---------|---------|
| 1 | **REST API** endpoint | `plproxy-psc-endpoint-all-ports` | Data plane → control plane **REST APIs** (`rest_api`) |
| 2 | **SCC relay** endpoint | `ngrok-psc-endpoint` | Data plane → **secure cluster connectivity (SCC) relay** (`dataplane_relay`) |

> **Scope:** This example implements **backend PSC only**. Front-end (user → workspace) traffic still uses the public internet. To also lock down front-end access, add a front-end PSC endpoint and set `public_access_enabled = false` — out of scope here.

Reference: [Enable Private Service Connect for your workspace (classic compute)](https://docs.databricks.com/gcp/en/security/network/classic/private-service-connect).

---

### What Gets Created

**In GCP (VPC host project):**
- Two internal IP addresses (`google_compute_address`) — one per backend endpoint
- Two PSC endpoints (`google_compute_forwarding_rule` with a service-attachment `target`)
- *(Optional)* A private Cloud DNS zone for `gcp.databricks.com` + three A records

**In Databricks (Account level):**
- Two registered VPC endpoints (`databricks_mws_vpc_endpoint`) — REST API + SCC relay
- A private access settings object (`databricks_mws_private_access_settings`)
- An MWS network config (`databricks_mws_networks`) wiring the endpoints via `vpc_endpoints { rest_api / dataplane_relay }`
- The workspace (`databricks_mws_workspaces`) attached to the network + private access settings
- Admin user added to the workspace `admins` group
- *(Optional)* Unity Catalog metastore assignment, if `metastore_id` is provided

> **Not created:** the VPC, subnets, or metastore — these are referenced as-is and remain untouched on `terraform destroy`.

---

### Repository Structure

| File | Description |
|------|-------------|
| `versions.tf` | Required Terraform providers and versions |
| `providers.tf` | Google (service + VPC-host alias) and Databricks (accounts + workspace) providers |
| `variables.tf` | All input variable definitions |
| `network.tf` | Data sources referencing the existing VPC, node subnet, and PSC subnet |
| `psc.tf` | The two backend PSC endpoints (internal IPs + forwarding rules) |
| `databricks.tf` | VPC endpoint registration, private access settings, network config, workspace, metastore, admin user |
| `dns.tf` | Private DNS zone + A records pointing the compute plane at the PSC endpoint IPs |
| `outputs.tf` | Output values (workspace URL, PSC connection statuses, endpoint IPs) |
| `terraform.tfvars.example` | Template for variable values |
| `service-account-impersonation.md` | Guide for service account setup + impersonation (incl. backend-PSC permissions) |

---

### Architecture

```
                         ┌──────────────────────────────────────────────┐
                         │              Databricks Control Plane          │
                         │   plproxy (REST API SA)     ngrok (SCC relay SA)│
                         └──────▲───────────────────────────▲────────────┘
                                │ PSC                         │ PSC
   VPC Host Project             │                             │
   ┌────────────────────────────┼─────────────────────────────┼─────────┐
   │  Existing VPC (BYO / shared)│                             │         │
   │                             │                             │         │
   │   PSC subnet                │                             │         │
   │   ┌─────────────────────────┴───┐   ┌─────────────────────┴──────┐  │
   │   │ REST API PSC endpoint (IP)  │   │ SCC relay PSC endpoint (IP) │  │
   │   │ fwd rule → workspace SA     │   │ fwd rule → relay SA         │  │
   │   └─────────────────────────────┘   └────────────────────────────┘  │
   │                                                                      │
   │   Node subnet ──► Databricks GCE data plane (in service project)     │
   │                                                                      │
   │   Private Cloud DNS (gcp.databricks.com):                            │
   │     <workspace_id>.gcp.databricks.com     → REST API endpoint IP     │
   │     dp-<workspace_id>.gcp.databricks.com  → REST API endpoint IP     │
   │     tunnel.<region>.gcp.databricks.com    → SCC relay endpoint IP    │
   └──────────────────────────────────────────────────────────────────────┘

   Databricks Account objects:
     mws_vpc_endpoint (rest_api)  ─┐
     mws_vpc_endpoint (relay)     ─┤► mws_networks.vpc_endpoints ─► workspace
     mws_private_access_settings ─┘                               (+ PAS)
```

---

### Prerequisites

- Terraform v1.3+
- Google Cloud SDK (`gcloud`) installed and authenticated
- A Databricks **Enterprise** plan account — [Subscribe from GCP Marketplace](https://docs.databricks.com/gcp/en/admin/account-settings-gcp/create-subscription)
- An **existing VPC** with:
  - a **node subnet** (for the Databricks GCE data plane), and
  - a **subnet for the PSC endpoints** (may be the same subnet as the node subnet)
- A Google Service Account (GSA) that is an **account admin** in Databricks and holds the [customer-managed VPC role requirements](https://docs.databricks.com/gcp/en/security/network/classic/customer-managed-vpc#role-requirements) **plus** PSC/DNS permissions on the host project (see [service-account-impersonation.md](service-account-impersonation.md))
- *(Optional)* An existing Unity Catalog metastore ID

> **Same-region rule:** Backend PSC has **no cross-region connectivity**. The VPC, subnets, PSC endpoints, and workspace must all be in the **same region**.
>
> **Quota:** Up to **10 PSC endpoints of each type** per region, per host project.

---

### Region Service Attachment URIs

Set `workspace_service_attachment` and `relay_service_attachment` to the values for **your workspace region**. The workspace (REST/plproxy) attachment lives in a per-region Databricks project; the relay (ngrok) attachment is consistently in `prod-gcp-<region>`.

| Region | `workspace_service_attachment` (plproxy-psc-endpoint-all-ports) | `relay_service_attachment` (ngrok-psc-endpoint) |
|--------|-----------------------------------------------------------------|-------------------------------------------------|
| us-central1 | `projects/gcp-prod-general/regions/us-central1/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-us-central1/regions/us-central1/serviceAttachments/ngrok-psc-endpoint` |
| us-east1 | `projects/general-prod-useast1-01/regions/us-east1/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-us-east1/regions/us-east1/serviceAttachments/ngrok-psc-endpoint` |
| us-east4 | `projects/general-prod-useast4-01/regions/us-east4/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-us-east4/regions/us-east4/serviceAttachments/ngrok-psc-endpoint` |
| us-west1 | `projects/general-prod-uswest1-01/regions/us-west1/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-us-west1/regions/us-west1/serviceAttachments/ngrok-psc-endpoint` |
| us-west4 | `projects/general-prod-uswest4-01/regions/us-west4/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-us-west4/regions/us-west4/serviceAttachments/ngrok-psc-endpoint` |
| northamerica-northeast1 | `projects/general-prod-nanortheast1-01/regions/northamerica-northeast1/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-northamerica-northeast1/regions/northamerica-northeast1/serviceAttachments/ngrok-psc-endpoint` |
| southamerica-east1 | `projects/gen-prod-saeast1-01/regions/southamerica-east1/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-southamerica-east1/regions/southamerica-east1/serviceAttachments/ngrok-psc-endpoint` |
| europe-west1 | `projects/general-prod-europewest1-01/regions/europe-west1/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-europe-west1/regions/europe-west1/serviceAttachments/ngrok-psc-endpoint` |
| europe-west2 | `projects/general-prod-europewest2-01/regions/europe-west2/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-europe-west2/regions/europe-west2/serviceAttachments/ngrok-psc-endpoint` |
| europe-west3 | `projects/general-prod-europewest3-01/regions/europe-west3/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-europe-west3/regions/europe-west3/serviceAttachments/ngrok-psc-endpoint` |
| asia-northeast1 | `projects/general-prod-asianortheast1-01/regions/asia-northeast1/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-asia-northeast1/regions/asia-northeast1/serviceAttachments/ngrok-psc-endpoint` |
| asia-south1 | `projects/gen-prod-asias1-01/regions/asia-south1/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-asia-south1/regions/asia-south1/serviceAttachments/ngrok-psc-endpoint` |
| asia-southeast1 | `projects/general-prod-asiasoutheast1-01/regions/asia-southeast1/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-asia-southeast1/regions/asia-southeast1/serviceAttachments/ngrok-psc-endpoint` |
| australia-southeast1 | `projects/general-prod-ausoutheast1-01/regions/australia-southeast1/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-australia-southeast1/regions/australia-southeast1/serviceAttachments/ngrok-psc-endpoint` |
| me-central2 | `projects/gen-prod-mec2-01/regions/me-central2/serviceAttachments/plproxy-psc-endpoint-all-ports` | `projects/prod-gcp-me-central2/regions/me-central2/serviceAttachments/ngrok-psc-endpoint` |

> ⚠️ These URIs change over time and new regions are added. **Always confirm against the authoritative table:** [PSC attachment URIs and project numbers](https://docs.databricks.com/gcp/en/resources/ip-domain-region#psc).

---

### Authentication

Set up the GSA and export an access token before running Terraform:

```bash
gcloud config set project <SERVICE_PROJECT_ID>
gcloud config set auth/impersonate_service_account <GSA_EMAIL>
export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)
```

Then add the GSA to your Databricks Account Console as an **account admin**:

1. [Login](https://docs.gcp.databricks.com/administration-guide/users-groups/users.html#manage-users-in-your-account) to the account console
2. [Add](https://docs.gcp.databricks.com/administration-guide/users-groups/users.html#add-users-to-your-account-using-the-account-console) the GSA as an account user
3. [Assign](https://docs.gcp.databricks.com/administration-guide/users-groups/users.html#assign-account-admin-roles-to-a-user) the account admin role to the GSA

> **Recommended:** For granular, least-privilege setup, use service account impersonation and the custom role — see [service-account-impersonation.md](service-account-impersonation.md), which also lists the extra `compute.*` / `dns.*` permissions backend PSC needs on the host project.

---

### Configuration

Copy the example file and fill in your values:

```bash
cp terraform.tfvars.example terraform.tfvars
```

| Variable | Type | Required | Description |
|----------|------|----------|-------------|
| `google_service_account_email` | string | Yes | GSA email used by providers |
| `google_project_name` | string | Yes | Service (consumer) project ID where the data plane runs |
| `google_region` | string | Yes | GCP region — must match the service attachment region |
| `vpc_network_project_id` | string | Yes | Project ID where the VPC resides. Set equal to `google_project_name` if same-project |
| `vpc_name` | string | Yes | Existing VPC network name |
| `subnet_name` | string | Yes | Existing node subnet name (Databricks GCE) |
| `psc_subnet_name` | string | Yes | Existing subnet for the PSC endpoint IPs (may equal `subnet_name`) |
| `databricks_account_id` | string | Yes | Databricks Account ID |
| `databricks_workspace_name` | string | Yes | Name for the new workspace |
| `databricks_admin_user` | string | Yes | Admin user email — must exist at the Account level |
| `workspace_service_attachment` | string | Yes | Region-specific REST/plproxy service attachment URI |
| `relay_service_attachment` | string | Yes | Region-specific SCC relay/ngrok service attachment URI |
| `workspace_pe_name` | string | No | Name of the REST API PSC endpoint (default `dbx-backend-rest-ep`) |
| `relay_pe_name` | string | No | Name of the SCC relay PSC endpoint (default `dbx-backend-relay-ep`) |
| `public_access_enabled` | bool | No | Keep front-end/public access on (default `true` for backend-only PSC) |
| `metastore_id` | string | No | UC metastore ID. Leave empty (`""`) for auto-create/auto-assign |
| `create_private_dns` | bool | No | Create the private DNS zone + records (default `true`) |
| `private_zone_name` | string | No | Private zone name (default `databricks-psc`) |
| `dns_name` | string | No | Must be `gcp.databricks.com.` with trailing dot (default) |

**Same project vs. Shared VPC:**

| Scenario | `google_project_name` | `vpc_network_project_id` |
|---|---|---|
| VPC in the **same** project | `my-project` | `my-project` |
| VPC in a **different** host project (Shared VPC) | `my-service-project` | `my-host-project` |

---

### Private DNS — why it's required

Backend PSC only carries traffic if the classic compute plane **resolves the Databricks control-plane hostnames to the private PSC endpoint IPs** instead of their public IPs. This module creates a private Cloud DNS zone for `gcp.databricks.com` in the host project with:

| Record | Resolves to |
|--------|-------------|
| `<workspace_id>.gcp.databricks.com` | REST API endpoint IP |
| `dp-<workspace_id>.gcp.databricks.com` | REST API endpoint IP |
| `tunnel.<region>.gcp.databricks.com` | SCC relay endpoint IP |

The per-region `tunnel.*` record is shared by all workspaces in the region; the two per-workspace records are unique. If you manage DNS centrally (e.g. a shared response policy or an existing `gcp.databricks.com` zone), set `create_private_dns = false` and add the equivalent records yourself using the `rest_api_endpoint_ip` / `relay_endpoint_ip` outputs.

---

### Usage

#### 1. Initialize and deploy

```bash
terraform init
terraform validate
terraform plan
terraform apply
```

Because Terraform creates the GCP PSC endpoints first and only then registers them with Databricks and builds the workspace, a single `apply` handles ordering via the `depends_on` chain. The workspace can take several minutes to provision.

#### 2. Retrieve outputs

```bash
terraform output -raw workspace_url
terraform output rest_api_psc_status   # expect: ACCEPTED
terraform output relay_psc_status      # expect: ACCEPTED
terraform output rest_api_endpoint_ip
terraform output relay_endpoint_ip
```

---

### Validation

After a successful apply:

1. **PSC connection status** — both endpoints should report `ACCEPTED`:
   ```bash
   terraform output rest_api_psc_status
   terraform output relay_psc_status
   # Or via gcloud:
   gcloud compute forwarding-rules describe <workspace_pe_name> \
     --region <REGION> --project <VPC_HOST_PROJECT> \
     --format="value(pscConnectionStatus)"
   ```
   If a status is `PENDING`, the Databricks side hasn't accepted the connection yet — usually clears within a few minutes.

2. **Databricks Account Console** — under **Cloud resources → Network** confirm the network config shows both the `rest_api` and `dataplane_relay` VPC endpoints. Under **Cloud resources → Private Service Connect (VPC endpoints)** confirm both endpoints are registered in the correct region.

3. **DNS resolution** (from a VM inside the VPC):
   ```bash
   dig +short <workspace_id>.gcp.databricks.com          # → REST API endpoint IP
   dig +short tunnel.<region>.gcp.databricks.com         # → SCC relay endpoint IP
   ```

4. **Workspace** — open `workspace_url`, confirm it loads and the admin user has admin rights. Launch a cluster; it should start and reach the control plane over PSC (nodes have no public IPs when using SCC).

---

### Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| PSC status stuck `PENDING` | Wrong service attachment URI, or wrong region | Verify the URI matches your region exactly (see region table + docs) |
| `load_balancing_scheme` error | Target is a service attachment | Must be `""` (already set in `psc.tf`) — do not override |
| Permission errors (403) creating forwarding rules / DNS | GSA missing PSC/DNS permissions on host project | Grant `roles/compute.networkAdmin` + `roles/dns.admin` on the host project (see service-account doc) |
| Clusters fail to start / can't reach control plane | DNS not resolving to PSC IPs | Confirm the private zone is attached to the VPC and A records resolve from inside the VPC |
| VPC/Subnet not found | Wrong name or project | Verify `vpc_name`, `subnet_name`, `psc_subnet_name`, `vpc_network_project_id`; subnets must be in `google_region` |
| Cross-region error | Components in different regions | All of VPC, subnets, endpoints, and workspace must be in one region |
| Endpoint quota exceeded | >10 endpoints of a type in the region/host project | Reuse existing endpoints or request a quota increase |
| Metastore assignment error | Invalid or wrong-region metastore | Verify `metastore_id` exists in the same region as the workspace |

> The Databricks accounts host for GCP is always `https://accounts.gcp.databricks.com`.

---

### Unity Catalog Metastore Behavior

Metastores are **region-specific** — one per region per Databricks account.

- **First workspace in a region:** Databricks auto-creates a metastore and assigns it. Leave `metastore_id` empty.
- **Auto-assign enabled:** If *"Automatically assign new workspaces to this metastore"* is on, the metastore is assigned automatically. Leave `metastore_id` empty.
- **Manual assignment needed:** If auto-assign is off, or you need a specific metastore, provide its ID in `metastore_id`.

---

### Teardown

```bash
terraform destroy
```

This removes the workspace, the Databricks network / private access settings / VPC endpoint registrations, the GCP PSC endpoints (forwarding rules + IPs), and the private DNS zone/records (if created). The existing VPC, subnets, and metastore are **not affected**.

> Destroy the Terraform-managed resources rather than deleting PSC endpoints manually in the console, so the Databricks-side registrations are cleaned up in the right order.

---

### References

- [Enable Private Service Connect for your workspace (classic compute)](https://docs.databricks.com/gcp/en/security/network/classic/private-service-connect)
- [PSC attachment URIs and project numbers](https://docs.databricks.com/gcp/en/resources/ip-domain-region#psc)
- [Customer-managed VPC role requirements](https://docs.databricks.com/gcp/en/security/network/classic/customer-managed-vpc#role-requirements)
- [`databricks_mws_vpc_endpoint`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/mws_vpc_endpoint) · [`databricks_mws_networks`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/mws_networks) · [`databricks_mws_private_access_settings`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/mws_private_access_settings)
