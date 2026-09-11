# Databricks Attribute-Based Access Control (ABAC) Demo

## Note

The Data Classification Terraform resource contains a bug at the moment, so this demo doesn't rely on the automated data classification tags. The two system tags (age and email address) are assigned in the Terraform project. At a later stage, when Data Classification can be enabled via Terraform, these manual assignments will be dropped from this demo.

If you want to enable automatic Data Classification in the UI, refer to the ABAC playbook.

## About the demo

This example demonstrates how to implement Attribute-Based Access Control (ABAC) in Databricks using Unity Catalog policies. The demo showcases:

- **Row-Level Security (RLS)**: Filtering rows based on user group membership and tenant attributes
- **Column Masking**: Masking sensitive data (email and age) based on data classification tags
- **Tag-Based Governance**: Using governed tags to apply policies dynamically

## Architecture

The solution consists of two main components:

1. **SQL Setup** (`setup.sql`): Creates demo tables, data, and functions
2. **Terraform Configuration** (`tf/`): Deploys ABAC policies, tags, and groups

### Key Components

- **Demo Table**: `user` - Contains user records with tenant information
- **RLS Function**: `filter_users_rls` - Filters rows based on group membership
- **Masking Functions**: `filter_email`, `filter_age` - Mask sensitive columns

## Prerequisites

- Databricks workspace (AWS, Azure, or GCP)
- Unity Catalog enabled
- Terraform installed
- Databricks CLI login configured for the workspace
  - `databricks auth login --host <workspace_url>`
- Databricks CLI login configured for account-level access
  - `databricks auth login --host <account_host> --account-id <databricks_account_id> --profile account`

## Setup Instructions

### 1. Prepare SQL Objects

Run the SQL [setup](./setup.sql) script to create the demo tables and functions. Edit the first variable to match your catalog:

```sql
DECLARE OR REPLACE VARIABLE catalog_name STRING DEFAULT '<YOUR_CATALOG>';
```

Then run the whole script.


This creates:
- `abac_demo` schema in your catalog
- `user` table with 10 sample users across 3 tenants
- RLS function that checks group membership
- Column masking functions for email and age

### 2. Configure Terraform

Create a `terraform.tfvars` file from the example:

```bash
cd tf
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your values:

```hcl
workspace_url           = "https://your-workspace.cloud.databricks.com"
workspace_name          = "your-workspace-name"  # Required for AWS/GCP
databricks_account_id   = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
cloud_provider          = "aws"  # or "azure", "gcp"
catalog_name            = "your_catalog"
```

### 3. Deploy with Terraform

Initialize and apply the Terraform configuration:

```bash
terraform init
terraform plan
terraform apply
```

This will create:
- Account group `abac_demo_group_1`
- Group membership (adds current user)
- Workspace access for the group
- Governed tags (`abac_demo_rls` with value `tenant`)
- Tag assignments to table columns
- ABAC policies for RLS (based on the tenant) and column masking (for email and age columns)

## How It Works

### Row-Level Security

1. The `abac_demo_rls` tag with value `tenant` is applied to the `tenant_name` column
2. The `tenant_row_isolation` policy matches columns with this tag
3. For matched columns, the policy calls `filter_users_rls(tenant_name)`
4. The function checks if the user belongs to a group mapped to that tenant
5. Users only see rows for their assigned tenant(s)

**Example**: Users in `abac_demo_group_1` only see rows where `tenant_name = 'tenantB'`

### Column Masking

1. The system tags `class.age` and `class.email_address` are automatically applied to respective columns via the automatic Data Classification on the catalog
2. The `mask_classified_ages` policy matches columns tagged with `class.age`
3. The `mask_classified_emails` policy matches columns tagged with `class.email_address`
4. Masking functions replace actual values with:
   - Email: `***@***`
   - Age: `0`

### Policy Application

Policies are applied at the catalog level and automatically affect all tables within the catalog that match the policy conditions. The policies use:

- `to_principals = ["account users"]`: Applies to all users
- `match_columns`: Targets columns based on tag conditions
- `row_filter` or `column_mask`: Specifies the function to apply

# TODO:
## Testing the Demo

### As a Group Member

```sql
USE CATALOG <YOUR_CATALOG>;

-- Query as a user in abac_demo_group_1
SELECT * FROM abac_demo.user;

-- Expected results:
-- - Only rows with tenant_name = 'tenantB' (Bob, Edward, Hannah)
-- - Email shows as '***@***'
-- - Age shows as 0
```

### As an Admin (with except_principals)

To exempt admins from policies, modify the policies:

```hcl
resource "databricks_policy_info" "tenant_rls" {
  # ... other config ...
  except_principals = ["your-admin-group"]
}
```

## Cleanup

To remove all resources:

```bash
terraform destroy
```

Then manually drop the SQL objects:

```sql
USE CATALOG <YOUR_CATALOG>;

DROP SCHEMA IF EXISTS abac_demo CASCADE;
```

## Key Concepts

### Governed Tags

Governed tags are centrally managed metadata that can be used to enforce policies. Unlike regular tags:
- Defined at the account level
- Can have controlled values
- Used in policy conditions
- Provide governance and compliance

### Policy Types

- **POLICY_TYPE_ROW_FILTER**: Controls which rows users can see
- **POLICY_TYPE_COLUMN_MASK**: Transforms column values before display

### Policy Matching

Policies use conditions to determine which columns/tables they apply to:
- `has_tag(tag_key)`: Matches any column with the tag
- `has_tag_value(tag_key, tag_value)`: Matches columns with specific tag value

## References

- [Databricks Unity Catalog ABAC Documentation](https://docs.databricks.com/en/data-governance/unity-catalog/abac.html)
- [Row and Column Filters](https://docs.databricks.com/en/data-governance/unity-catalog/manage-privileges/row-and-column-filters.html)
- [Terraform Provider - databricks_policy_info](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/policy_info)

## Troubleshooting

### During the regular resource cleanup I get an error regarding the state of the resources

**Solution** Delete the state files.

### During the regular resource cleanup the governed tag `abac_demo_rls` was not deleted and locally it is cleared from the state

**Solution** Import the tag into the state:

```sh
terraform import databricks_tag_policy.tag_rls "abac_demo_rls"
```

### Invalid condition in policy 'tenant_row_isolation'. Compilation error with message 'Unknown tag policy key `abac_demo_rls`'.

**Solution** This error only occurs in Azure, working on a fix to solve this. A re-run of `terraform apply` solves this issue.