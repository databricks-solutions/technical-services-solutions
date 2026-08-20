# Databricks Terraform Pre-Check

CLI tool to validate **credentials, permissions, and resources** before deploying
Databricks workspaces via Terraform on **AWS, Azure, and GCP**. It runs all checks
automatically and produces a **`report.md`** you can send back to your Databricks
contact.

---

## Quick start

You do **not** need to edit any files or change any settings. From this folder:

**macOS / Linux**
```bash
./run.sh
```

**Windows (PowerShell)**
```powershell
.\run.ps1
```

> If Windows blocks the script with *"running scripts is disabled on this system,"*
> run it this way instead (allows it for this one session only):
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\run.ps1
> ```

> **Linux note:** if you get *"No module named venv"*, install the venv package
> first — e.g. `sudo apt install python3-venv` on Debian/Ubuntu — then re-run.

The runner sets everything up on first run (~1–2 minutes), asks for your cloud and
a couple of values, then asks whether you want a **dry run** or a **full run**. A
full run writes **`report.md`** next to this file — **send that back to your
Databricks contact. That's the whole job.**

### Two ways to run it (the runner asks you to pick one)

1. **Dry run — creates nothing.** Shows exactly what the full run *would* create and
   test in your account. No changes are made. Run this first if you (or your security
   team) want to see what will happen before anything runs. A dry run does **not**
   produce a report.
2. **Full run — creates temporary resources, then deletes them.** This is the real
   check, and the one that produces the `report.md` you send back. To *prove* your
   permissions, it briefly creates a few small, clearly-tagged resources (named
   `dbxprecheck-*` / `dbx-precheck-temp-*`) and **deletes them at the end of the run**
   (on Azure, deleting the resource group removes everything inside it):
   - On **Azure**, this briefly includes a NAT Gateway + Public IP — a few cents for
     the seconds they exist.
   - On **AWS**, it's a temporary bucket / IAM role / security group (no cost).
   - On **GCP**, nothing is ever created — it's read-only in *both* modes.

**A typical path:** dry run once to see what it does → full run to produce the report.

### Before you run

1. **Python 3.10 or newer** installed ([python.org/downloads](https://www.python.org/downloads/)).
2. **Logged in to your cloud** from this machine, using an identity that has
   permission to deploy the workspace:

   | Cloud | Log in with |
   |-------|-------------|
   | AWS   | `aws configure` (or set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) |
   | Azure | `az login` |
   | GCP   | `gcloud auth application-default login` |

3. Know a couple of values you'll be asked for — nothing to configure in advance:

   | Cloud | You'll be asked for |
   |-------|---------------------|
   | AWS   | Region (e.g. `us-east-1`) |
   | Azure | Subscription ID + region (e.g. `eastus`) |
   | GCP   | Project ID + region (e.g. `us-central1`) |

### What the report tells you

At the top you'll see a **Deployment Compatibility** summary — for each workspace
type (Standard, PrivateLink, Unity Catalog, Full) it says one of:

- **SUPPORTED** — every permission that type needs was verified and is clean.
- **NOT SUPPORTED** — a required permission is missing; the report names which one.
- **REVIEW** — permissions are fine, but something is worth a look (e.g. a small subnet).
- **NOT VERIFIED** — the check couldn't confirm this area (e.g. read-only mode).

If anything is missing, the report lists exactly which permission is needed and how
to fix it — just send `report.md` back and we'll take it from there.

> **Locked-down environment** where you're not allowed to create resources at all,
> even temporarily? Run a read-only check instead — it produces a real report but
> can't confirm every write permission:
> `./run.sh --cloud azure --subscription-id <id> --region <region> --verify-only`

Everything below is reference material for advanced use and CI/CD.

---

## Why use this?

Before running `terraform apply`, this tool verifies:

- ✅ Valid and correctly configured credentials
- ✅ Databricks-specific IAM/RBAC permissions
- ✅ Network configuration (VPC, Subnets, Security Groups)
- ✅ **Private Link / VPC Endpoints** for private connectivity
- ✅ Storage for DBFS and Unity Catalog
- ✅ Resource quotas and limits
- ✅ KMS/Key Vault for CMK encryption

## How it works

This tool tests permissions by **creating temporary resources and immediately
deleting them**:

```
┌─────────────────────────────────────────────────────────────────┐
│  1. Creates temporary Resource Group / VPC                      │
│  2. Creates test resources inside (VNet, Storage, etc.)        │
│  3. Verifies all permissions succeeded                         │
│  4. Deletes everything (Resource Group deletion cascades)      │
│  5. Generates detailed report                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Guarantees:**
- All temporary resources use prefix `dbxprecheck-*` or `dbx-precheck-temp-*`
- Resources are deleted immediately after testing
- Resource Group deletion in Azure cascades to all contained resources
- Run `--cleanup-orphans` to find/delete any leftover resources

## Advanced usage (run directly with Python)

The `run.sh` / `run.ps1` wrappers above are the customer path. To run the checker
directly (development, CI, or fine-grained flags), set up the environment once:

```bash
git clone <repo-url> && cd workspace-setup/terraform-checker
python3 -m venv venv
source venv/bin/activate   # Linux/Mac (Windows: venv\Scripts\activate)
pip install -r requirements.txt
```

Authenticate with your cloud provider:

```bash
# AWS — pick one
aws configure                          # interactive setup
# or: export AWS_ACCESS_KEY_ID=xxx && export AWS_SECRET_ACCESS_KEY=xxx

# Azure — pick one
az login                               # browser-based login
# or: export AZURE_CLIENT_ID=xxx && export AZURE_CLIENT_SECRET=xxx && export AZURE_TENANT_ID=xxx

# GCP — pick one
gcloud auth application-default login  # browser-based login
# or: export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

Then run the checker (one command per cloud):

```bash
# AWS
python main.py --cloud aws --region us-east-1

# Azure
python main.py --cloud azure --subscription-id <your-sub-id> --region eastus

# GCP
python main.py --cloud gcp --project <your-project-id> --region us-central1
```

> **No `--mode` or `--vpc-type` needed.** Since v1.2.0 the checker runs all checks
> automatically and produces a **Deployment Compatibility** matrix showing which
> deployment types (Standard, PrivateLink, Unity Catalog, Full) your permissions
> support.

### Per-cloud examples

```bash
# AWS — with a specific profile / read-only
python main.py --cloud aws --region us-east-1 --profile my-profile
python main.py --cloud aws --region us-east-1 --verify-only

# Azure — targeting a specific resource group / read-only
python main.py --cloud azure --subscription-id <sub-id> --resource-group my-rg --region eastus
python main.py --cloud azure --subscription-id <sub-id> --region eastus --verify-only

# GCP — with an explicit credentials file
python main.py --cloud gcp --project my-project --credentials-file /path/to/key.json --region us-central1
```

### Additional options

```bash
# Check all configured clouds
python main.py --all

# Save report to file
python main.py --cloud aws --region us-east-1 --output report.txt

# JSON output for CI/CD
python main.py --cloud aws --region us-east-1 --json --quiet

# Dry-run (show what would be tested without creating resources)
python main.py --cloud aws --region us-east-1 --dry-run

# Verify-only mode (read-only checks, no resource creation)
python main.py --cloud aws --region us-east-1 --verify-only

# Debug logging
python main.py --cloud aws --region us-east-1 --log-level debug --log-file debug.log

# Clean up any orphaned test resources
python main.py --cleanup-orphans --cloud aws --region us-east-1

# Customer-friendly Markdown report (plain-language verdict + remediation)
python main.py --cloud aws --region us-east-1 --format markdown --output report.md

# Strict CI gating: exit non-zero on warnings / NOT-VERIFIED items too
python main.py --cloud aws --region us-east-1 --strict --json --quiet

# Scope BYO-network validation to a specific VPC and/or security group (AWS)
python main.py --cloud aws --region us-east-1 --vpc-id vpc-xxxxxxxx --sg-id sg-xxxxxxxx

# Validate the cross-account role TRUST content (AWS)
python main.py --cloud aws --region us-east-1 --databricks-account-id <databricks-account-uuid>

# Validate an existing VNet for VNet injection, incl. cross-subscription (Azure)
python main.py --cloud azure --subscription-id <id> --vnet-id "<resource-group>/<vnet-name>"

# READ-ONLY Databricks account-console check (token valid + account-admin + reachable)
export DATABRICKS_ACCOUNT_TOKEN=<account-level-token>
python main.py --cloud aws --region us-east-1 \
  --databricks-account-id <databricks-account-uuid> --databricks-account-token "$DATABRICKS_ACCOUNT_TOKEN"
```

### Targeted / BYO-network validation

| Flag | Cloud | What it checks |
|------|-------|----------------|
| `--vpc-id` | AWS | Scopes network checks to one VPC: private-subnet count, AZ spread, subnet size (/17–/26), and NAT/egress for non-PrivateLink deployments. |
| `--sg-id` | AWS | Validates an existing security group's rules (intra-SG all-traffic ingress/egress + control-plane egress). |
| `--databricks-account-id` | AWS | Validates the cross-account role *trust* content (Databricks signing principal `414351767826` + your account as ExternalId), not just that you can create the role. |
| `--vnet-id` | Azure | Validates an existing VNet for VNet injection: Databricks-delegated subnets, NSG association, and subnet sizing. Accepts a full ARM id or `<rg>/<vnet-name>`. |
| `--databricks-account-token` | all | **Read-only** account-console check: confirms the Databricks Account API is reachable, the token authenticates, and the principal is an **account admin**. Requires `--databricks-account-id`. Also reads `DATABRICKS_ACCOUNT_TOKEN`. Creates nothing. |
| `--databricks-account-host` | all | Override the Account API host for gov/custom control planes (defaults per `--cloud`). |

### Databricks account-console check (read-only)

The cloud checkers validate the *cloud-side* prerequisites. The `databricks_mws_*`
Terraform resources authenticate against the Databricks **Account API** instead.
Most of those can't be fully pre-checked (registering `databricks_mws_credentials`
/ `networks` / `customer_managed_keys` validates the underlying cloud resource,
which doesn't exist yet before `terraform apply`), but the cheap, early-failing
slice can be — **read-only**:

- **Reachability** of the account console from this environment (proxy/egress).
- The account **token authenticates** (not expired/malformed).
- The principal is an **account admin** (a 403 means "authenticated but not admin").

It maps HTTP `200 → admin`, `401 → invalid token`, `403 → not an admin`, network
error → reachability blocker; anything else is reported as unverified (never a
false pass). Dependency-free (stdlib `urllib`), all `GET`s. It does **not** create
workspaces or register any `mws_*` resource — the report's "Not validated" section
says so explicitly.

### Output formats

```bash
--format text        # default: rich terminal report
--format markdown    # customer-friendly report (verdict, action items, docs links)
--format json        # machine-readable, for CI/CD
--json               # shortcut for --format json
```

Progress/status lines are written to **stderr**, so `--json` on **stdout** is pure,
parseable JSON and a redirected Markdown report has no progress noise prepended —
safe to pipe directly in CI (`... --json --quiet > report.json`).

### Verify-only mode

The `--verify-only` flag runs read-only permission checks without creating any
temporary resources. This is useful when:

- Resource creation requires approval from your organization
- You want a quick validation of credentials and existing resources
- You're in a restricted environment where resource creation is blocked

**Limitations of verify-only mode:**
- Cannot fully verify write permissions (e.g., create bucket, create VNet)
- Uses IAM policy simulation when available, which may not reflect all conditions
- Some permission checks will show as "WARNING" instead of definitive pass/fail

For comprehensive permission validation, run without `--verify-only` to test with
actual resource creation.

## Deployment compatibility matrix

Since v1.2.0, the tool runs **all checks automatically** and produces a compatibility
matrix at the end of every report. No `--mode` flag is needed — the report tells you
which deployment types your current permissions support.

Example output:

```
╔══════════════════════════════════════════════════════════════════════╗
║                    DEPLOYMENT COMPATIBILITY                          ║
╠══════════════════════════════════════════════════════════════════════╣
║  Standard               SUPPORTED                                    ║
║  PrivateLink            SUPPORTED                                    ║
║  Unity Catalog          SUPPORTED                                    ║
║  Full                   SUPPORTED                                    ║
╚══════════════════════════════════════════════════════════════════════╝
```

Each deployment type is reported with one of four honest states:

| State | Meaning |
|-------|---------|
| **SUPPORTED** | Every area the mode needs was verified and is clean. |
| **NOT SUPPORTED** | A required area has a hard blocker (missing permission / failed create). The detail lists which area. |
| **REVIEW** | Permissions were verified, but a required area has an actionable advisory (e.g. an undersized subnet, no NAT egress) — not a blocker, worth a look before deploying. |
| **NOT VERIFIED** | Could not confirm a required area (IAM simulation unavailable — e.g. under SSO — `--verify-only`, or no target resource passed). The tool never silently reports these as SUPPORTED. |

```
║  Standard               SUPPORTED                                    ║
║  PrivateLink            NOT SUPPORTED (missing perms)                ║
║  Unity Catalog          REVIEW (advisories, no blockers)            ║
║  Full                   NOT VERIFIED                                 ║
```

The per-mode detail line always names the **actual** reason (which area, and whether
it was a blocker, an advisory, or simply unverifiable) rather than a generic
catch-all.

## AWS deployment types

The checker validates permissions for all of these deployment types in a single run:

| Type | VPC | Storage (Root Bucket) | Unity Catalog Storage | VPC Endpoints | Cross-Account Role |
|------|-----|----------------------|----------------------|---------------|-------------------|
| **Standard** | Customer-managed | **You create** S3 bucket | N/A | N/A | **You create** |
| **PrivateLink** | Customer-managed | **You create** S3 bucket | N/A | **You create** | **You create** |
| **Unity Catalog** | Customer-managed | **You create** S3 bucket | **You create** S3 bucket | N/A | **You create** |
| **Full** | Customer-managed | **You create** S3 bucket | **You create** S3 bucket | **You create** | **You create** |

> **Note:** Databricks-managed VPC has been sunset for new AWS deployments. All
> configurations now use customer-managed VPCs.

### Unity Catalog requirements (AWS)

Per [Databricks documentation](https://docs.databricks.com/aws/en/connect/unity-catalog/cloud-storage/index.html):

1. **S3 Bucket** - For Unity Catalog metastore data
2. **IAM Role** - Cross-account role with trust policy for Databricks
3. **S3 Permissions on Role:**
   - `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` - Read/write data
   - `s3:ListBucket` - List bucket contents
   - `s3:GetBucketLocation` - Get bucket region
4. **KMS Permissions (if using CMK):**
   - `kms:Encrypt`, `kms:Decrypt` - For encryption operations

## Azure deployment types

| Type | VNet | Storage (DBFS) | Unity Catalog Storage | NAT Gateway | Private Link |
|------|------|----------------|----------------------|-------------|--------------|
| **Standard** | Databricks-managed | Databricks-managed | N/A | N/A | N/A |
| **VNet Injection** | **You create** | Databricks-managed | N/A | N/A | N/A |
| **Unity Catalog** | Databricks-managed | Databricks-managed | **You create ADLS Gen2** | N/A | N/A |
| **PrivateLink** | **You create** | Databricks-managed | N/A | **Required** | **You create** |
| **Full** | **You create** | Databricks-managed | **You create ADLS Gen2** | **Required** | **You create** |

### Unity Catalog requirements (Azure)

Per [Microsoft documentation](https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/azure-managed-identities):

1. **Access Connector for Azure Databricks** - First-party Azure resource with managed identity
2. **ADLS Gen2 Storage Account** - For Unity Catalog metastore
3. **RBAC Roles on Storage Account:**
   - `Storage Blob Data Contributor` - Read/write data
   - `Storage Queue Data Contributor` - For file events (optional)
4. **RBAC Roles on Resource Group:**
   - `EventGrid EventSubscription Contributor` - For auto file events (optional)

## GCP deployment types

GCP Databricks deployments use a simpler model compared to AWS and Azure. The checker
validates permissions for all of these configurations in a single run:

| Configuration | VPC | Storage (GCS) | Unity Catalog Storage | Private Google Access | Cloud NAT |
|--------------|-----|---------------|----------------------|----------------------|-----------|
| **Standard** | Databricks or Customer | **You create** GCS bucket | N/A | Recommended | Recommended |
| **With Unity Catalog** | Databricks or Customer | **You create** GCS bucket | **You create** GCS bucket | Recommended | Recommended |
| **Private Connectivity** | **You create** | **You create** GCS bucket | Optional | **Required** | **Required** |

### GCP VPC configuration

| VPC Type | Description | Requirements |
|----------|-------------|--------------|
| **Databricks-managed** | Databricks creates VPC in your project | `compute.networks.create`, `compute.subnetworks.create` |
| **Customer-managed** | You provide an existing VPC | Custom mode VPC, Private Google Access enabled on subnets |

### Unity Catalog requirements (GCP)

Per [Databricks documentation](https://docs.gcp.databricks.com/data-governance/unity-catalog/index.html):

1. **GCS Bucket** - For Unity Catalog metastore data
2. **Service Account** - With appropriate IAM roles
3. **IAM Permissions on Bucket:**
   - `storage.objects.create`, `storage.objects.delete` - Read/write data
   - `storage.objects.get`, `storage.objects.list` - List/read objects
   - `storage.buckets.get` - Get bucket metadata
4. **Uniform Bucket-Level Access** - Recommended for Unity Catalog buckets

### Private connectivity requirements (GCP)

1. **Private Google Access** - Must be enabled on all subnets used by Databricks
2. **Cloud NAT** - Required for clusters without public IPs to access internet
3. **Firewall Rules** - Allow internal cluster communication
4. **Cloud Router** - Required for Cloud NAT configuration

## Databricks-specific checks

### AWS

| Category | Checks |
|----------|--------|
| **Credentials** | STS GetCallerIdentity, Account ID, Region |
| **IAM** | Policy simulation (ec2, s3, iam, kms), Cross-account role permissions |
| **Network** | VPC DNS settings, Subnets (private/public), Security Groups, NAT Gateways, AZs |
| **PrivateLink** | Existing VPC Endpoints, S3/STS/Kinesis endpoints, Creation permissions |
| **Storage** | S3 buckets, DBFS/Unity Catalog permissions, Public access block |
| **Quotas** | VPCs, Elastic IPs, Security Groups, vCPUs |

### Azure

| Category | Checks |
|----------|--------|
| **Credentials** | DefaultAzureCredential, Subscription state, Resource Group |
| **RBAC** | Role assignments, Contributor/Owner, Resource Providers |
| **Network** | VNet injection, Subnet delegation, NSGs, NAT Gateway |
| **Private Link** | Private Endpoints, Private DNS Zones (azuredatabricks.net, blob, dfs) |
| **Storage** | ADLS Gen2 accounts, HNS enabled, Storage creation |
| **Access Connector** | Managed identity for Unity Catalog |
| **Quotas** | VNets, NSGs, Public IPs, vCPUs |
| **Key Vault** | Vaults, Soft delete, Purge protection |

### GCP

| Category | Checks |
|----------|--------|
| **Credentials** | Service Account, Project state, Project number |
| **APIs** | compute, storage, iam, cloudresourcemanager, cloudkms, logging |
| **IAM** | testIamPermissions, Admin roles, Service Account permissions |
| **Network** | Custom VPC, Subnets, Private Google Access, Firewall rules, Cloud NAT |
| **Private Connectivity** | Private Google Access per subnet, Private Service Connect, Cloud NAT |
| **Storage** | GCS buckets, Uniform bucket-level access |
| **Quotas** | Networks, Subnetworks, CPUs, Disks, Instances |
| **KMS** | Key rings, CMEK readiness |

## Sample output

```
======================================================================
  DATABRICKS TERRAFORM PRE-CHECK REPORT
  Cloud: Azure | Region: eastus
  Subscription: my-subscription (xxxx-xxxx-xxxx)
======================================================================

[CREDENTIALS]
  Auth Method                                  OK - Using Azure CLI (az login)
  Azure Credentials                            OK - Authenticated successfully
  Subscription                                 OK - my-subscription
  Region                                       OK - eastus

[RESOURCE GROUP (REAL TEST)]
  Test Method                                  OK - Creating temporary RG for permission tests...
    📁 Creating test Resource Group             OK - dbxprecheck-rg-f086fad4
    Microsoft.Resources/resourceGroups/write   OK - ✓ CREATED: dbxprecheck-rg-f086fad4

[NETWORK - VNet Injection (REAL TEST)]
    🌐 Creating test VNet                       OK - dbxprecheck-vnet-f086fad4
    Microsoft.Network/networkSecurityGroups/wr OK - ✓ CREATED: dbxprecheck-nsg-f086fad4
    Microsoft.Network/virtualNetworks/write    OK - ✓ CREATED: dbxprecheck-vnet-f086fad4
    Subnet Delegation (Databricks)             OK - ✓ Delegated to Microsoft.Databricks/workspaces

[ACCESS CONNECTOR FOR DATABRICKS (REAL TEST)]
    🔗 Creating Access Connector for Databricks OK - dbxprecheck-connector-f086fad4
    Microsoft.Databricks/accessConnectors/write OK - ✓ CREATED
    System-Assigned Managed Identity           OK - ✓ Created

[PRIVATE LINK + SCC (REAL TEST)]
    🌐 Creating NAT Gateway (required for SCC)  OK - dbxprecheck-natgw-f086fad4
    Microsoft.Network/natGateways/write        OK - ✓ CREATED
    SCC (Secure Cluster Connectivity)          OK - NAT Gateway enables clusters without public IPs

[CLEANUP]
    🗑️  Deleting Resource Group (and all conte OK - ✓ DELETING: dbxprecheck-rg-f086fad4

╔══════════════════════════════════════════════════════════════════════╗
║                    DEPLOYMENT COMPATIBILITY                          ║
╠══════════════════════════════════════════════════════════════════════╣
║  Standard               SUPPORTED                                    ║
║  VNet Injection          SUPPORTED                                    ║
║  Unity Catalog          SUPPORTED                                    ║
║  PrivateLink            SUPPORTED                                    ║
║  Full                   SUPPORTED                                    ║
╚══════════════════════════════════════════════════════════════════════╝

======================================================================
  SUMMARY: 49 OK | 0 WARNING | 0 NOT OK
  STATUS: PASSED - All checks successful
======================================================================
```

## Credential configuration

### AWS

Credentials are automatically detected from:

1. **Environment variables**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`
2. **Credentials file**: `~/.aws/credentials`
3. **Instance metadata** (EC2, ECS, Lambda)

### Azure

Credentials are detected from:

1. **Environment variables**: `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`
2. **Azure CLI**: `az login`
3. **Managed Identity** (when running on Azure)

### GCP

Credentials are detected from:

1. **Environment variable**: `GOOGLE_APPLICATION_CREDENTIALS`
2. **Application Default Credentials**: `gcloud auth application-default login`
3. **Service Account** (when running on GCP)

## Verifying cleanup

To verify no orphaned resources were left behind:

```bash
# Azure - Check for orphaned resources
az group list --query "[?starts_with(name, 'dbxprecheck')]" -o table
az network vnet list --query "[?starts_with(name, 'dbxprecheck')]" -o table
az storage account list --query "[?starts_with(name, 'dbxprecheck')]" -o table

# AWS - Check for orphaned resources
aws s3 ls | grep dbx-precheck-temp
aws iam list-roles --query "Roles[?starts_with(RoleName, 'dbx-precheck-temp')]"
```

## CI/CD integration

```yaml
# GitHub Actions example
- name: Databricks Pre-Check
  run: |
    # stdout is pure JSON (progress goes to stderr); --strict fails the job on
    # warnings / NOT-VERIFIED items too, not just hard blockers.
    python main.py --cloud aws --region us-east-1 --strict --json --quiet > pre-check.json

- name: Upload Report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: pre-check-report
    path: pre-check.json
```

**Exit codes:** `0` = passed · `2` = blockers found (permissions denied) ·
`1` = passed but, under `--strict`, there were warnings / NOT-VERIFIED items.

## Required permissions

### AWS - minimum IAM policy for pre-check

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "ec2:Describe*",
        "ec2:CreateVpc",
        "ec2:DeleteVpc",
        "ec2:CreateSecurityGroup",
        "ec2:DeleteSecurityGroup",
        "s3:ListAllMyBuckets",
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:PutBucketVersioning",
        "iam:ListRoles",
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:CreatePolicy",
        "iam:DeletePolicy",
        "iam:SimulatePrincipalPolicy",
        "kms:ListKeys",
        "service-quotas:GetServiceQuota"
      ],
      "Resource": "*"
    }
  ]
}
```

### Azure - minimum RBAC

- **Contributor** on Subscription (for full testing with temporary resource creation)
- Or **Owner** if testing role assignments for Unity Catalog

### GCP - minimum IAM roles

- `roles/viewer` on project
- Or specific roles: `compute.viewer`, `storage.objectViewer`, `iam.securityReviewer`

## Troubleshooting

### "No credentials found"

```bash
# AWS
aws configure
# or
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=xxx

# Azure
az login
# or
export AZURE_CLIENT_ID=xxx
export AZURE_CLIENT_SECRET=xxx
export AZURE_TENANT_ID=xxx

# GCP
gcloud auth application-default login
# or
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

### "Access Denied" or "Permission Denied"

Check that your credentials have the permissions listed above. Use the report to
identify which specific permissions are missing.

### SDK not installed

```bash
# Activate virtual environment
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

## License

&copy; 2025 Databricks, Inc. All rights reserved. The source in this project is
provided subject to the Databricks License — see
[LICENSE.md](../../LICENSE.md) in the repository root.

This project is provided for your exploration only and is **not** a
Databricks-supported product and is not covered by Databricks support or Service
Level Agreements (SLAs). It is provided **AS-IS**, and we make no guarantees.
Please do not submit a support ticket relating to any issues arising from its use;
the team will help on a best-effort basis via GitHub issues.

### Third-party dependencies

This tool builds on the following open-source libraries, each distributed under its
own license. See [LICENSE-THIRD-PARTY.md](../../LICENSE-THIRD-PARTY.md) in the
repository root for the repository-wide third-party license text.

| Dependency | Purpose | License |
|------------|---------|---------|
| [boto3](https://github.com/boto/boto3) | AWS SDK | Apache-2.0 |
| [azure-identity, azure-mgmt-*](https://github.com/Azure/azure-sdk-for-python) | Azure SDKs | MIT |
| [google-cloud-*, google-api-python-client](https://github.com/googleapis/google-cloud-python) | GCP SDKs | Apache-2.0 |
| [Click](https://github.com/pallets/click) | CLI framework | BSD-3-Clause |
| [Rich](https://github.com/Textualize/rich) | Terminal rendering | MIT |
| [PyYAML](https://github.com/yaml/pyyaml) | Permission-set config parsing | MIT |

---

## Apêndice — Documentação em Português (Brasil)

<details>
<summary><strong>Clique para expandir a documentação em Português</strong></summary>

<br>

Ferramenta CLI para validar **credenciais, permissões e recursos** antes de realizar
deployments de workspaces Databricks via Terraform em **AWS, Azure e GCP**.

> **Só quer rodar e enviar um relatório?** Rode `./run.sh` (macOS/Linux) ou
> `.\run.ps1` (Windows) a partir desta pasta — o runner configura tudo, pergunta a
> cloud e se você quer um **dry run** ou um **full run**, e escreve o **`report.md`**
> que você envia de volta ao seu contato Databricks. O restante deste apêndice é
> material de referência para uso avançado e CI/CD.

### Por que usar?

Antes de rodar `terraform apply`, esta ferramenta verifica:

- ✅ Credenciais válidas e configuradas corretamente
- ✅ Permissões IAM/RBAC específicas para Databricks
- ✅ Configuração de rede (VPC, Subnets, Security Groups)
- ✅ **Private Link / VPC Endpoints** para conectividade privada
- ✅ Storage para DBFS e Unity Catalog
- ✅ Quotas e limites de recursos
- ✅ KMS/Key Vault para criptografia CMK

### Instalação (uso avançado, direto com Python)

```bash
# Criar virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# Instalar dependências
pip install -r requirements.txt
```

### Uso

```bash
# AWS
python main.py --cloud aws --region us-east-1
python main.py --cloud aws --region us-east-1 --profile my-profile   # com profile específico

# Azure
python main.py --cloud azure --subscription-id <subscription-id> --region eastus

# GCP
python main.py --cloud gcp --project <project-id> --region us-central1
python main.py --cloud gcp --project my-project --credentials-file /path/to/key.json  # com arquivo de credenciais

# Todas as clouds configuradas
python main.py --all

# Salvar relatório em arquivo
python main.py --cloud aws --output report.txt
```

### Opções adicionais

```bash
# Modo read-only (sem criação de recursos)
python main.py --cloud aws --region us-east-1 --verify-only

# Dry-run (mostra o que seria testado, sem criar nada)
python main.py --cloud aws --region us-east-1 --dry-run

# Limpar recursos de teste órfãos
python main.py --cleanup-orphans --cloud aws --region us-east-1

# Relatório Markdown amigável ao cliente (veredito em linguagem clara + remediação)
python main.py --cloud aws --region us-east-1 --format markdown --output report.md

# Gating estrito de CI: sai com código != 0 também em warnings / NOT-VERIFIED
python main.py --cloud aws --region us-east-1 --strict --json --quiet

# Escopar a validação de rede BYO a um VPC e/ou security group (AWS)
python main.py --cloud aws --region us-east-1 --vpc-id vpc-xxxxxxxx --sg-id sg-xxxxxxxx

# Validar o conteúdo de TRUST da role cross-account (AWS)
python main.py --cloud aws --region us-east-1 --databricks-account-id <uuid-da-conta-databricks>

# Validar uma VNet existente para VNet injection, incl. cross-subscription (Azure)
python main.py --cloud azure --subscription-id <id> --vnet-id "<resource-group>/<nome-da-vnet>"

# Logging de debug
python main.py --cloud aws --region us-east-1 --log-level debug --log-file debug.log
```

### Validação direcionada / BYO-network

| Flag | Cloud | O que valida |
|------|-------|--------------|
| `--vpc-id` | AWS | Escopa as checagens de rede a um VPC: contagem de subnets privadas, distribuição em AZs, tamanho da subnet (/17–/26) e NAT/egress para deployments sem PrivateLink. |
| `--sg-id` | AWS | Valida as regras de um security group existente (ingress/egress intra-SG de todo o tráfego + egress para o control plane). |
| `--databricks-account-id` | AWS | Valida o *conteúdo* do trust da role cross-account (principal de assinatura da Databricks `414351767826` + sua conta como ExternalId), não apenas que você consegue criar a role. |
| `--vnet-id` | Azure | Valida uma VNet existente para VNet injection: subnets delegadas à Databricks, associação de NSG e tamanho da subnet. Aceita id ARM completo ou `<rg>/<nome-da-vnet>`. |

### Formatos de saída

```bash
--format text        # padrão: relatório rico no terminal
--format markdown    # relatório amigável ao cliente (veredito, itens de ação, links de docs)
--format json        # legível por máquina, para CI/CD
--json               # atalho para --format json
```

As linhas de progresso/status vão para o **stderr**, então o `--json` no **stdout** é
JSON puro e parseável, e um relatório Markdown redirecionado não vem com ruído de
progresso — seguro para pipe direto em CI (`... --json --quiet > report.json`).

### Modo verify-only

A flag `--verify-only` roda checagens de permissão read-only sem criar nenhum recurso
temporário. Útil quando:

- A criação de recursos exige aprovação da sua organização
- Você quer uma validação rápida de credenciais e recursos existentes
- Você está num ambiente restrito onde a criação de recursos é bloqueada

**Limitações do modo verify-only:**
- Não verifica completamente permissões de escrita (ex.: criar bucket, criar VNet)
- Usa simulação de política IAM quando disponível, que pode não refletir todas as condições
- Algumas checagens aparecem como "WARNING" em vez de pass/fail definitivo

### Matriz de compatibilidade de deployment

Desde a v1.2.0, a ferramenta roda **todas as checagens automaticamente** e produz uma
matriz de compatibilidade ao final de cada relatório. Não é preciso a flag `--mode` —
o relatório diz quais tipos de deployment suas permissões atuais suportam.

Cada tipo de deployment é reportado com um de quatro estados honestos:

| Estado | Significado |
|--------|-------------|
| **SUPPORTED** | Todas as áreas que o modo precisa foram verificadas e estão OK. |
| **NOT SUPPORTED** | Uma área necessária tem um bloqueador real (permissão faltando / falha ao criar). O detalhe lista qual área. |
| **REVIEW** | As permissões foram verificadas, mas uma área necessária tem um aviso acionável (ex.: subnet pequena demais, sem NAT/egress) — não é bloqueador, mas vale revisar antes do deploy. |
| **NOT VERIFIED** | Não foi possível confirmar uma área necessária (simulação IAM indisponível — ex.: sob SSO — `--verify-only`, ou nenhum recurso alvo informado). A ferramenta nunca reporta isso silenciosamente como SUPPORTED. |

A linha de detalhe de cada modo sempre nomeia o motivo **real** (qual área, e se foi
bloqueador, aviso ou apenas não-verificável) em vez de uma mensagem genérica.

### Verificações específicas para Databricks

#### AWS

| Categoria | Verificações |
|-----------|--------------|
| **Credenciais** | STS GetCallerIdentity, Account ID, Region |
| **IAM** | Simulação de políticas (ec2, s3, iam, kms), Cross-account role permissions |
| **Rede** | VPC DNS settings, Subnets (private/public), Security Groups, NAT Gateways, AZs |
| **PrivateLink** | VPC Endpoints existentes, S3/STS/Kinesis endpoints, Permissões de criação |
| **Storage** | S3 buckets, DBFS/Unity Catalog permissions, Public access block |
| **Quotas** | VPCs, Elastic IPs, Security Groups, vCPUs |

#### Azure

| Categoria | Verificações |
|-----------|--------------|
| **Credenciais** | Service Principal, Subscription state, Resource Group |
| **RBAC** | Role assignments, Contributor/Owner, Resource Providers |
| **Rede** | VNet injection readiness, Subnet delegation, NSGs, NAT Gateway |
| **Private Link** | Private Endpoints, Private DNS Zones (azuredatabricks.net, blob, dfs) |
| **Storage** | ADLS Gen2 accounts, HNS enabled, Storage creation |
| **Quotas** | VNets, NSGs, Public IPs, vCPUs |
| **Key Vault** | Vaults, Soft delete, Purge protection |

#### GCP

| Categoria | Verificações |
|-----------|--------------|
| **Credenciais** | Service Account, Project state, Project number |
| **APIs** | compute, storage, iam, iamcredentials, serviceusage, container, deploymentmanager, cloudkms, dns (conjunto SRA completo) |
| **IAM** | testIamPermissions dirigido pelo conjunto de permissões SRA completo, subconjuntos deploy-blocking, impersonation (actAs), PSC/DNS |
| **Rede** | Custom VPC, Subnets, Private Google Access, Firewall rules, Cloud NAT |
| **Private Connectivity** | Private Google Access per subnet, Private Service Connect, Cloud NAT |
| **Storage** | GCS buckets, Uniform bucket-level access |
| **Quotas** | Networks, Subnetworks, CPUs, Disks, Instances |
| **KMS** | Key rings, CMEK readiness |

### Configuração de credenciais

#### AWS
1. **Variáveis de ambiente**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`
2. **Arquivo de credenciais**: `~/.aws/credentials`
3. **Instance metadata** (EC2, ECS, Lambda)

#### Azure
1. **Variáveis de ambiente**: `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`
2. **Azure CLI**: `az login`
3. **Managed Identity** (quando rodando no Azure)

#### GCP
1. **Variável de ambiente**: `GOOGLE_APPLICATION_CREDENTIALS`
2. **Application Default Credentials**: `gcloud auth application-default login`
3. **Service Account** (quando rodando no GCP)

### Integração com CI/CD

```yaml
# Exemplo GitHub Actions
- name: Databricks Pre-Check
  run: |
    # o stdout é JSON puro (o progresso vai para stderr); --strict faz o job
    # falhar também em warnings / NOT-VERIFIED, não só em bloqueadores.
    python main.py --cloud aws --region us-east-1 --strict --json --quiet > pre-check.json

- name: Upload Report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: pre-check-report
    path: pre-check.json
```

**Códigos de saída:** `0` = passou · `2` = bloqueadores encontrados (permissões negadas) ·
`1` = passou, mas sob `--strict` houve warnings / itens NOT-VERIFIED.

### Permissões necessárias

#### AWS - IAM Policy mínima para rodar o pre-check

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "ec2:Describe*",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "iam:ListRoles",
        "iam:ListInstanceProfiles",
        "iam:SimulatePrincipalPolicy",
        "kms:ListKeys",
        "service-quotas:GetServiceQuota"
      ],
      "Resource": "*"
    }
  ]
}
```

#### Azure - RBAC mínimo
- **Reader** no Subscription (para verificações)
- Ou **Contributor** para verificações completas

#### GCP - IAM roles mínimos
- `roles/viewer` no projeto
- Ou roles específicos: `compute.viewer`, `storage.objectViewer`, `iam.securityReviewer`

### Troubleshooting

Consulte a seção **Troubleshooting** em inglês acima para os passos de "No credentials
found", "Access Denied" e "SDK not installed" — os comandos são os mesmos.

### Licença

Consulte a seção **License** em inglês acima: o código original deste projeto está sob
a **Databricks License** (veja [LICENSE.md](../../LICENSE.md) na raiz do repositório),
e as dependências de terceiros são reconhecidas na tabela de **Third-party
dependencies**. Fornecido **AS-IS**, sem suporte formal da Databricks.

</details>
