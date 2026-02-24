# Databricks Terraform Pre-Check

CLI tool to validate **credentials, permissions, and resources** before deploying Databricks workspaces via Terraform on **AWS, Azure, and GCP**.

## Why Use This?

Before running `terraform apply`, this tool verifies:

- ✅ Valid and correctly configured credentials
- ✅ Databricks-specific IAM/RBAC permissions
- ✅ Network configuration (VPC, Subnets, Security Groups)
- ✅ **Private Link / VPC Endpoints** for private connectivity
- ✅ Storage for DBFS and Unity Catalog
- ✅ Resource quotas and limits
- ✅ KMS/Key Vault for CMK encryption

## How It Works

This tool tests permissions by **creating temporary resources and immediately deleting them**:

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

## Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

## Quick Start Testing

**1. Set up the environment** (first time only):

```bash
git clone <repo-url> && cd workspace-setup/terraform-checker
python3 -m venv venv
source venv/bin/activate   # Linux/Mac (Windows: venv\Scripts\activate)
pip install -r requirements.txt
```

**2. Authenticate with your cloud provider:**

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

**3. Run the checker** (one command per cloud):

```bash
# AWS
python main.py --cloud aws --region us-east-1

# Azure
python main.py --cloud azure --subscription-id <your-sub-id> --region eastus

# GCP
python main.py --cloud gcp --project <your-project-id> --region us-central1
```

> **No `--mode` or `--vpc-type` needed.** Since v1.2.0 the checker runs all checks automatically and produces a **Deployment Compatibility** matrix showing which deployment types (Standard, PrivateLink, Unity Catalog, Full) your permissions support.

## Usage

### AWS Checks

```bash
# All checks (creates temporary resources, then deletes them)
python main.py --cloud aws --region us-east-1

# With specific AWS profile
python main.py --cloud aws --region us-east-1 --profile my-profile

# Read-only checks (no resource creation)
python main.py --cloud aws --region us-east-1 --verify-only
```

### Azure Checks

```bash
# All checks with subscription ID
python main.py --cloud azure --subscription-id <sub-id> --region eastus

# Targeting a specific resource group
python main.py --cloud azure --subscription-id <sub-id> --resource-group my-rg --region eastus

# Read-only checks
python main.py --cloud azure --subscription-id <sub-id> --region eastus --verify-only
```

### GCP Checks

```bash
# All checks
python main.py --cloud gcp --project <project-id> --region us-central1

# With credentials file
python main.py --cloud gcp --project my-project --credentials-file /path/to/key.json --region us-central1
```

### Additional Options

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
```

### Verify-Only Mode

The `--verify-only` flag runs read-only permission checks without creating any temporary resources. This is useful when:

- Resource creation requires approval from your organization
- You want a quick validation of credentials and existing resources
- You're in a restricted environment where resource creation is blocked

**Limitations of verify-only mode:**
- Cannot fully verify write permissions (e.g., create bucket, create VNet)
- Uses IAM policy simulation when available, which may not reflect all conditions
- Some permission checks will show as "WARNING" instead of definitive pass/fail

For comprehensive permission validation, run without `--verify-only` to test with actual resource creation.

## Deployment Compatibility Matrix

Since v1.2.0, the tool runs **all checks automatically** and produces a compatibility matrix at the end of every report. No `--mode` flag is needed — the report tells you which deployment types your current permissions support.

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

If some permissions are missing, the matrix highlights exactly which deployment types are affected:

```
║  Standard               SUPPORTED                                    ║
║  PrivateLink            MISSING PERMISSIONS                          ║
║  Unity Catalog          SUPPORTED                                    ║
║  Full                   MISSING PERMISSIONS                          ║
```

## AWS Deployment Types

The checker validates permissions for all of these deployment types in a single run:

| Type | VPC | Storage (Root Bucket) | Unity Catalog Storage | VPC Endpoints | Cross-Account Role |
|------|-----|----------------------|----------------------|---------------|-------------------|
| **Standard** | Customer-managed | **You create** S3 bucket | N/A | N/A | **You create** |
| **PrivateLink** | Customer-managed | **You create** S3 bucket | N/A | **You create** | **You create** |
| **Unity Catalog** | Customer-managed | **You create** S3 bucket | **You create** S3 bucket | N/A | **You create** |
| **Full** | Customer-managed | **You create** S3 bucket | **You create** S3 bucket | **You create** | **You create** |

> **Note:** Databricks-managed VPC has been sunset for new AWS deployments. All configurations now use customer-managed VPCs.

### Unity Catalog Requirements (AWS)

Per [Databricks documentation](https://docs.databricks.com/aws/en/connect/unity-catalog/cloud-storage/index.html):

1. **S3 Bucket** - For Unity Catalog metastore data
2. **IAM Role** - Cross-account role with trust policy for Databricks
3. **S3 Permissions on Role:**
   - `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` - Read/write data
   - `s3:ListBucket` - List bucket contents
   - `s3:GetBucketLocation` - Get bucket region
4. **KMS Permissions (if using CMK):**
   - `kms:Encrypt`, `kms:Decrypt` - For encryption operations

## Azure Deployment Types

| Type | VNet | Storage (DBFS) | Unity Catalog Storage | NAT Gateway | Private Link |
|------|------|----------------|----------------------|-------------|--------------|
| **Standard** | Databricks-managed | Databricks-managed | N/A | N/A | N/A |
| **VNet Injection** | **You create** | Databricks-managed | N/A | N/A | N/A |
| **Unity Catalog** | Databricks-managed | Databricks-managed | **You create ADLS Gen2** | N/A | N/A |
| **PrivateLink** | **You create** | Databricks-managed | N/A | **Required** | **You create** |
| **Full** | **You create** | Databricks-managed | **You create ADLS Gen2** | **Required** | **You create** |

### Unity Catalog Requirements (Azure)

Per [Microsoft documentation](https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/azure-managed-identities):

1. **Access Connector for Azure Databricks** - First-party Azure resource with managed identity
2. **ADLS Gen2 Storage Account** - For Unity Catalog metastore
3. **RBAC Roles on Storage Account:**
   - `Storage Blob Data Contributor` - Read/write data
   - `Storage Queue Data Contributor` - For file events (optional)
4. **RBAC Roles on Resource Group:**
   - `EventGrid EventSubscription Contributor` - For auto file events (optional)

## GCP Deployment Types

GCP Databricks deployments use a simpler model compared to AWS and Azure. The checker validates permissions for all of these configurations in a single run:

| Configuration | VPC | Storage (GCS) | Unity Catalog Storage | Private Google Access | Cloud NAT |
|--------------|-----|---------------|----------------------|----------------------|-----------|
| **Standard** | Databricks or Customer | **You create** GCS bucket | N/A | Recommended | Recommended |
| **With Unity Catalog** | Databricks or Customer | **You create** GCS bucket | **You create** GCS bucket | Recommended | Recommended |
| **Private Connectivity** | **You create** | **You create** GCS bucket | Optional | **Required** | **Required** |

### GCP VPC Configuration

| VPC Type | Description | Requirements |
|----------|-------------|--------------|
| **Databricks-managed** | Databricks creates VPC in your project | `compute.networks.create`, `compute.subnetworks.create` |
| **Customer-managed** | You provide an existing VPC | Custom mode VPC, Private Google Access enabled on subnets |

### Unity Catalog Requirements (GCP)

Per [Databricks documentation](https://docs.gcp.databricks.com/data-governance/unity-catalog/index.html):

1. **GCS Bucket** - For Unity Catalog metastore data
2. **Service Account** - With appropriate IAM roles
3. **IAM Permissions on Bucket:**
   - `storage.objects.create`, `storage.objects.delete` - Read/write data
   - `storage.objects.get`, `storage.objects.list` - List/read objects
   - `storage.buckets.get` - Get bucket metadata
4. **Uniform Bucket-Level Access** - Recommended for Unity Catalog buckets

### Private Connectivity Requirements (GCP)

1. **Private Google Access** - Must be enabled on all subnets used by Databricks
2. **Cloud NAT** - Required for clusters without public IPs to access internet
3. **Firewall Rules** - Allow internal cluster communication
4. **Cloud Router** - Required for Cloud NAT configuration

## Databricks-Specific Checks

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

## Sample Output

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

## Credential Configuration

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

## Verifying Cleanup

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

## CI/CD Integration

```yaml
# GitHub Actions example
- name: Databricks Pre-Check
  run: |
    python main.py --cloud aws --region us-east-1 --output pre-check-report.txt
    cat pre-check-report.txt
    
- name: Upload Report
  uses: actions/upload-artifact@v3
  with:
    name: pre-check-report
    path: pre-check-report.txt
```

## Required Permissions

### AWS - Minimum IAM Policy for pre-check

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

### Azure - Minimum RBAC

- **Contributor** on Subscription (for full testing with temporary resource creation)
- Or **Owner** if testing role assignments for Unity Catalog

### GCP - Minimum IAM roles

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

Check that your credentials have the permissions listed above. Use the report to identify which specific permissions are missing.

### SDK not installed

```bash
# Activate virtual environment
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

## License

MIT

