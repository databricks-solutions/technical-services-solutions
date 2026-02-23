"""
Databricks-specific Terraform actions for each cloud provider.

This module defines the EXACT IAM/RBAC actions that Terraform executes
when deploying a Databricks workspace, organized by resource type.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class DeploymentMode(Enum):
    """Databricks deployment modes."""
    STANDARD = "standard"  # Basic workspace
    PRIVATE_LINK = "privatelink"  # With PrivateLink/Private Endpoints
    CUSTOMER_MANAGED_VPC = "customer_managed_vpc"  # Bring your own VPC
    UNITY_CATALOG = "unity_catalog"  # With Unity Catalog


class VPCType(Enum):
    """VPC deployment types for Databricks.
    
    Note: Databricks Managed VPC has been sunset for AWS. Only customer-managed
    VPC options are available for new deployments.
    """
    CUSTOMER_MANAGED_DEFAULT = "customer_managed_default"  # Customer VPC with default restrictions
    CUSTOMER_MANAGED_CUSTOM = "customer_managed_custom"  # Customer VPC with custom restrictions


# =============================================================================
# DATABRICKS CROSS-ACCOUNT ROLE POLICIES (from official documentation)
# https://docs.databricks.com/aws/en/admin/workspace/create-uc-workspace#step-2-create-an-access-policy
# =============================================================================

# Customer-managed VPC with default restrictions
CUSTOMER_MANAGED_VPC_DEFAULT_ACTIONS = [
    "ec2:AssociateDhcpOptions",
    "ec2:AssociateIamInstanceProfile",
    "ec2:AssociateRouteTable",
    "ec2:AttachInternetGateway",
    "ec2:AttachVolume",
    "ec2:AuthorizeSecurityGroupEgress",
    "ec2:AuthorizeSecurityGroupIngress",
    "ec2:CancelSpotInstanceRequests",
    "ec2:CreateDhcpOptions",
    "ec2:CreateFleet",
    "ec2:CreateLaunchTemplate",
    "ec2:CreateLaunchTemplateVersion",
    "ec2:CreateRoute",
    "ec2:CreateSecurityGroup",
    "ec2:CreateTags",
    "ec2:CreateVolume",
    "ec2:DeleteDhcpOptions",
    "ec2:DeleteFleets",
    "ec2:DeleteLaunchTemplate",
    "ec2:DeleteLaunchTemplateVersions",
    "ec2:DeleteRoute",
    "ec2:DeleteSecurityGroup",
    "ec2:DeleteTags",
    "ec2:DeleteVolume",
    "ec2:DescribeAvailabilityZones",
    "ec2:DescribeFleetHistory",
    "ec2:DescribeFleetInstances",
    "ec2:DescribeFleets",
    "ec2:DescribeIamInstanceProfileAssociations",
    "ec2:DescribeInstanceStatus",
    "ec2:DescribeInstances",
    "ec2:DescribeInternetGateways",
    "ec2:DescribeLaunchTemplates",
    "ec2:DescribeLaunchTemplateVersions",
    "ec2:DescribeNatGateways",
    "ec2:DescribePrefixLists",
    "ec2:DescribeReservedInstancesOfferings",
    "ec2:DescribeRouteTables",
    "ec2:DescribeSecurityGroups",
    "ec2:DescribeSpotInstanceRequests",
    "ec2:DescribeSpotPriceHistory",
    "ec2:DescribeSubnets",
    "ec2:DescribeVolumes",
    "ec2:DescribeVpcAttribute",
    "ec2:DescribeVpcs",
    "ec2:DetachInternetGateway",
    "ec2:DisassociateIamInstanceProfile",
    "ec2:DisassociateRouteTable",
    "ec2:GetLaunchTemplateData",
    "ec2:GetSpotPlacementScores",
    "ec2:ModifyFleet",
    "ec2:ModifyLaunchTemplate",
    "ec2:ReplaceIamInstanceProfileAssociation",
    "ec2:RequestSpotInstances",
    "ec2:RevokeSecurityGroupEgress",
    "ec2:RevokeSecurityGroupIngress",
    "ec2:RunInstances",
    "ec2:TerminateInstances",
]

# Customer-managed VPC - Custom restrictions (most restrictive)
# Note: This requires resource-level restrictions with specific VPC/Subnet/SG ARNs
CUSTOMER_MANAGED_VPC_CUSTOM_ACTIONS = CUSTOMER_MANAGED_VPC_DEFAULT_ACTIONS.copy()

# IAM actions for Spot instances (required for all VPC types)
SPOT_SERVICE_LINKED_ROLE_ACTIONS = [
    "iam:CreateServiceLinkedRole",
    "iam:PutRolePolicy",
]

# Unity Catalog storage credential actions
UNITY_CATALOG_STORAGE_ACTIONS = [
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
    "s3:ListBucket",
    "s3:GetBucketLocation",
    "kms:Decrypt",
    "kms:Encrypt",
    "kms:GenerateDataKey*",
    "sts:AssumeRole",
]

# Unity Catalog file events actions (optional but recommended)
UNITY_CATALOG_FILE_EVENTS_ACTIONS = [
    "s3:GetBucketNotification",
    "s3:PutBucketNotification",
    "sns:ListSubscriptionsByTopic",
    "sns:GetTopicAttributes",
    "sns:SetTopicAttributes",
    "sns:CreateTopic",
    "sns:TagResource",
    "sns:Publish",
    "sns:Subscribe",
    "sqs:CreateQueue",
    "sqs:DeleteMessage",
    "sqs:ReceiveMessage",
    "sqs:SendMessage",
    "sqs:GetQueueUrl",
    "sqs:GetQueueAttributes",
    "sqs:SetQueueAttributes",
    "sqs:TagQueue",
    "sqs:ChangeMessageVisibility",
    "sqs:PurgeQueue",
    "sqs:ListQueues",
    "sqs:ListQueueTags",
    "sns:ListTopics",
    "sns:Unsubscribe",
    "sns:DeleteTopic",
    "sqs:DeleteQueue",
]


def get_cross_account_actions(vpc_type: VPCType = VPCType.CUSTOMER_MANAGED_DEFAULT) -> List[str]:
    """Get the required cross-account IAM actions for a VPC type.
    
    Since Databricks Managed VPC is sunset, this defaults to customer-managed.
    """
    if vpc_type == VPCType.CUSTOMER_MANAGED_CUSTOM:
        return CUSTOMER_MANAGED_VPC_CUSTOM_ACTIONS + SPOT_SERVICE_LINKED_ROLE_ACTIONS
    return CUSTOMER_MANAGED_VPC_DEFAULT_ACTIONS + SPOT_SERVICE_LINKED_ROLE_ACTIONS


@dataclass
class TerraformAction:
    """A single Terraform action that requires a specific permission."""
    action: str  # IAM action (e.g., "ec2:CreateVpc")
    resource: str  # Resource ARN pattern (e.g., "*" or "arn:aws:s3:::*")
    description: str  # Human-readable description
    required: bool = True  # Is this action required or optional?
    condition: Optional[str] = None  # When is this needed? (e.g., "if creating new VPC")


@dataclass
class TerraformResource:
    """A Terraform resource with all its required actions."""
    name: str  # Resource name (e.g., "Cross-Account IAM Role")
    resource_type: str  # Terraform resource type (e.g., "aws_iam_role")
    actions: List[TerraformAction] = field(default_factory=list)
    description: str = ""
    

# =============================================================================
# AWS DATABRICKS TERRAFORM ACTIONS
# =============================================================================

AWS_CROSS_ACCOUNT_ROLE = TerraformResource(
    name="Cross-Account IAM Role",
    resource_type="aws_iam_role",
    description="IAM role that Databricks control plane assumes to manage resources",
    actions=[
        TerraformAction("iam:CreateRole", "*", "Create the cross-account role"),
        TerraformAction("iam:GetRole", "*", "Read role configuration"),
        TerraformAction("iam:DeleteRole", "*", "Delete role on destroy"),
        TerraformAction("iam:TagRole", "*", "Add tags to role"),
        TerraformAction("iam:UntagRole", "*", "Remove tags from role"),
        TerraformAction("iam:UpdateAssumeRolePolicy", "*", "Update trust policy"),
        TerraformAction("iam:PutRolePolicy", "*", "Attach inline policy"),
        TerraformAction("iam:DeleteRolePolicy", "*", "Remove inline policy"),
        TerraformAction("iam:GetRolePolicy", "*", "Read inline policy"),
        TerraformAction("iam:AttachRolePolicy", "*", "Attach managed policy"),
        TerraformAction("iam:DetachRolePolicy", "*", "Detach managed policy"),
        TerraformAction("iam:ListRolePolicies", "*", "List inline policies"),
        TerraformAction("iam:ListAttachedRolePolicies", "*", "List managed policies"),
    ]
)

AWS_INSTANCE_PROFILE = TerraformResource(
    name="Instance Profile (for clusters)",
    resource_type="aws_iam_instance_profile",
    description="Instance profile attached to Databricks cluster nodes",
    actions=[
        TerraformAction("iam:CreateRole", "*", "Create role for instance profile"),
        TerraformAction("iam:CreateInstanceProfile", "*", "Create instance profile"),
        TerraformAction("iam:GetInstanceProfile", "*", "Read instance profile"),
        TerraformAction("iam:DeleteInstanceProfile", "*", "Delete instance profile"),
        TerraformAction("iam:AddRoleToInstanceProfile", "*", "Attach role to profile"),
        TerraformAction("iam:RemoveRoleFromInstanceProfile", "*", "Detach role from profile"),
        TerraformAction("iam:PassRole", "*", "Allow passing role to EC2"),
        TerraformAction("iam:ListInstanceProfilesForRole", "*", "List profiles for role"),
    ]
)

AWS_S3_ROOT_BUCKET = TerraformResource(
    name="S3 Root Bucket (DBFS)",
    resource_type="aws_s3_bucket",
    description="S3 bucket for Databricks File System (DBFS) root storage",
    actions=[
        TerraformAction("s3:CreateBucket", "arn:aws:s3:::*", "Create the root bucket"),
        TerraformAction("s3:DeleteBucket", "arn:aws:s3:::*", "Delete bucket on destroy"),
        TerraformAction("s3:GetBucketLocation", "arn:aws:s3:::*", "Get bucket region"),
        TerraformAction("s3:ListBucket", "arn:aws:s3:::*", "List bucket contents"),
        TerraformAction("s3:GetBucketAcl", "arn:aws:s3:::*", "Read bucket ACL"),
        TerraformAction("s3:PutBucketAcl", "arn:aws:s3:::*", "Set bucket ACL"),
        # Bucket Policy
        TerraformAction("s3:GetBucketPolicy", "arn:aws:s3:::*", "Read bucket policy"),
        TerraformAction("s3:PutBucketPolicy", "arn:aws:s3:::*", "Set bucket policy for Databricks access"),
        TerraformAction("s3:DeleteBucketPolicy", "arn:aws:s3:::*", "Remove bucket policy"),
        # Versioning
        TerraformAction("s3:GetBucketVersioning", "arn:aws:s3:::*", "Read versioning config"),
        TerraformAction("s3:PutBucketVersioning", "arn:aws:s3:::*", "Enable versioning"),
        # Encryption
        TerraformAction("s3:GetEncryptionConfiguration", "arn:aws:s3:::*", "Read encryption"),
        TerraformAction("s3:PutEncryptionConfiguration", "arn:aws:s3:::*", "Enable SSE encryption"),
        # Public Access Block
        TerraformAction("s3:GetBucketPublicAccessBlock", "arn:aws:s3:::*", "Read public access block"),
        TerraformAction("s3:PutBucketPublicAccessBlock", "arn:aws:s3:::*", "Block public access"),
        # Tags
        TerraformAction("s3:GetBucketTagging", "arn:aws:s3:::*", "Read bucket tags"),
        TerraformAction("s3:PutBucketTagging", "arn:aws:s3:::*", "Set bucket tags"),
        # Objects (for DBFS)
        TerraformAction("s3:GetObject", "arn:aws:s3:::*/*", "Read objects"),
        TerraformAction("s3:PutObject", "arn:aws:s3:::*/*", "Write objects"),
        TerraformAction("s3:DeleteObject", "arn:aws:s3:::*/*", "Delete objects"),
    ]
)

AWS_UNITY_CATALOG_BUCKET = TerraformResource(
    name="S3 Unity Catalog Bucket",
    resource_type="aws_s3_bucket",
    description="S3 bucket for Unity Catalog metastore storage",
    actions=[
        TerraformAction("s3:CreateBucket", "arn:aws:s3:::*", "Create Unity Catalog bucket"),
        TerraformAction("s3:PutBucketPolicy", "arn:aws:s3:::*", "Set bucket policy for Unity Catalog"),
        TerraformAction("s3:PutBucketVersioning", "arn:aws:s3:::*", "Enable versioning"),
        TerraformAction("s3:PutEncryptionConfiguration", "arn:aws:s3:::*", "Enable encryption"),
        TerraformAction("s3:PutBucketPublicAccessBlock", "arn:aws:s3:::*", "Block public access"),
    ]
)

AWS_VPC = TerraformResource(
    name="VPC",
    resource_type="aws_vpc",
    description="Virtual Private Cloud for Databricks workspace",
    actions=[
        TerraformAction("ec2:CreateVpc", "*", "Create the VPC"),
        TerraformAction("ec2:DeleteVpc", "*", "Delete VPC on destroy"),
        TerraformAction("ec2:DescribeVpcs", "*", "Read VPC configuration"),
        TerraformAction("ec2:ModifyVpcAttribute", "*", "Enable DNS hostnames/support"),
        TerraformAction("ec2:DescribeVpcAttribute", "*", "Read VPC attributes"),
        TerraformAction("ec2:CreateTags", "*", "Tag the VPC"),
        TerraformAction("ec2:DeleteTags", "*", "Remove tags"),
    ]
)

AWS_SUBNETS = TerraformResource(
    name="Subnets (Private)",
    resource_type="aws_subnet",
    description="Private subnets for Databricks clusters (minimum 2 in different AZs)",
    actions=[
        TerraformAction("ec2:CreateSubnet", "*", "Create private subnets"),
        TerraformAction("ec2:DeleteSubnet", "*", "Delete subnets on destroy"),
        TerraformAction("ec2:DescribeSubnets", "*", "Read subnet configuration"),
        TerraformAction("ec2:ModifySubnetAttribute", "*", "Modify subnet attributes"),
        TerraformAction("ec2:CreateTags", "*", "Tag subnets"),
        TerraformAction("ec2:DescribeAvailabilityZones", "*", "List available AZs"),
    ]
)

AWS_SECURITY_GROUP = TerraformResource(
    name="Security Group",
    resource_type="aws_security_group",
    description="Security group for Databricks cluster communication",
    actions=[
        TerraformAction("ec2:CreateSecurityGroup", "*", "Create security group"),
        TerraformAction("ec2:DeleteSecurityGroup", "*", "Delete security group"),
        TerraformAction("ec2:DescribeSecurityGroups", "*", "Read security group"),
        TerraformAction("ec2:AuthorizeSecurityGroupIngress", "*", "Add inbound rules"),
        TerraformAction("ec2:AuthorizeSecurityGroupEgress", "*", "Add outbound rules"),
        TerraformAction("ec2:RevokeSecurityGroupIngress", "*", "Remove inbound rules"),
        TerraformAction("ec2:RevokeSecurityGroupEgress", "*", "Remove outbound rules"),
        TerraformAction("ec2:UpdateSecurityGroupRuleDescriptionsIngress", "*", "Update rule descriptions"),
        TerraformAction("ec2:UpdateSecurityGroupRuleDescriptionsEgress", "*", "Update rule descriptions"),
        TerraformAction("ec2:CreateTags", "*", "Tag security group"),
    ]
)

AWS_INTERNET_GATEWAY = TerraformResource(
    name="Internet Gateway",
    resource_type="aws_internet_gateway",
    description="Internet gateway for public subnet access",
    actions=[
        TerraformAction("ec2:CreateInternetGateway", "*", "Create internet gateway"),
        TerraformAction("ec2:DeleteInternetGateway", "*", "Delete internet gateway"),
        TerraformAction("ec2:DescribeInternetGateways", "*", "Read internet gateway"),
        TerraformAction("ec2:AttachInternetGateway", "*", "Attach to VPC"),
        TerraformAction("ec2:DetachInternetGateway", "*", "Detach from VPC"),
        TerraformAction("ec2:CreateTags", "*", "Tag internet gateway"),
    ]
)

AWS_NAT_GATEWAY = TerraformResource(
    name="NAT Gateway",
    resource_type="aws_nat_gateway",
    description="NAT gateway for private subnet outbound access",
    actions=[
        TerraformAction("ec2:CreateNatGateway", "*", "Create NAT gateway"),
        TerraformAction("ec2:DeleteNatGateway", "*", "Delete NAT gateway"),
        TerraformAction("ec2:DescribeNatGateways", "*", "Read NAT gateway"),
        TerraformAction("ec2:AllocateAddress", "*", "Allocate Elastic IP for NAT"),
        TerraformAction("ec2:ReleaseAddress", "*", "Release Elastic IP"),
        TerraformAction("ec2:DescribeAddresses", "*", "Read Elastic IPs"),
        TerraformAction("ec2:CreateTags", "*", "Tag NAT gateway"),
    ]
)

AWS_ROUTE_TABLES = TerraformResource(
    name="Route Tables",
    resource_type="aws_route_table",
    description="Route tables for VPC traffic routing",
    actions=[
        TerraformAction("ec2:CreateRouteTable", "*", "Create route table"),
        TerraformAction("ec2:DeleteRouteTable", "*", "Delete route table"),
        TerraformAction("ec2:DescribeRouteTables", "*", "Read route tables"),
        TerraformAction("ec2:CreateRoute", "*", "Add route to table"),
        TerraformAction("ec2:DeleteRoute", "*", "Remove route"),
        TerraformAction("ec2:ReplaceRoute", "*", "Modify existing route"),
        TerraformAction("ec2:AssociateRouteTable", "*", "Associate with subnet"),
        TerraformAction("ec2:DisassociateRouteTable", "*", "Disassociate from subnet"),
        TerraformAction("ec2:CreateTags", "*", "Tag route table"),
    ]
)

AWS_VPC_ENDPOINTS = TerraformResource(
    name="VPC Endpoints (PrivateLink)",
    resource_type="aws_vpc_endpoint",
    description="VPC endpoints for private connectivity to AWS services and Databricks",
    actions=[
        TerraformAction("ec2:CreateVpcEndpoint", "*", "Create VPC endpoint"),
        TerraformAction("ec2:DeleteVpcEndpoints", "*", "Delete VPC endpoints"),
        TerraformAction("ec2:DescribeVpcEndpoints", "*", "Read VPC endpoints"),
        TerraformAction("ec2:ModifyVpcEndpoint", "*", "Modify VPC endpoint"),
        TerraformAction("ec2:DescribeVpcEndpointServices", "*", "List available endpoint services"),
        TerraformAction("ec2:DescribePrefixLists", "*", "Get prefix lists for S3 endpoint"),
        TerraformAction("ec2:CreateTags", "*", "Tag VPC endpoints"),
    ]
)

AWS_KMS_KEY = TerraformResource(
    name="KMS Key (CMK)",
    resource_type="aws_kms_key",
    description="Customer-managed key for encryption",
    actions=[
        TerraformAction("kms:CreateKey", "*", "Create KMS key"),
        TerraformAction("kms:DescribeKey", "*", "Read key details"),
        TerraformAction("kms:EnableKey", "*", "Enable the key"),
        TerraformAction("kms:DisableKey", "*", "Disable the key"),
        TerraformAction("kms:ScheduleKeyDeletion", "*", "Schedule key deletion"),
        TerraformAction("kms:CreateAlias", "*", "Create key alias"),
        TerraformAction("kms:DeleteAlias", "*", "Delete key alias"),
        TerraformAction("kms:UpdateAlias", "*", "Update key alias"),
        TerraformAction("kms:GetKeyPolicy", "*", "Read key policy"),
        TerraformAction("kms:PutKeyPolicy", "*", "Set key policy"),
        TerraformAction("kms:CreateGrant", "*", "Create key grant for Databricks"),
        TerraformAction("kms:ListGrants", "*", "List key grants"),
        TerraformAction("kms:RevokeGrant", "*", "Revoke key grant"),
        TerraformAction("kms:TagResource", "*", "Tag KMS key"),
        TerraformAction("kms:UntagResource", "*", "Untag KMS key"),
    ]
)


# =============================================================================
# AWS DEPLOYMENT PROFILES
# =============================================================================

AWS_STANDARD_DEPLOYMENT: List[TerraformResource] = [
    AWS_CROSS_ACCOUNT_ROLE,
    AWS_INSTANCE_PROFILE,
    AWS_S3_ROOT_BUCKET,
    AWS_VPC,
    AWS_SUBNETS,
    AWS_SECURITY_GROUP,
    AWS_INTERNET_GATEWAY,
    AWS_NAT_GATEWAY,
    AWS_ROUTE_TABLES,
]

AWS_PRIVATELINK_DEPLOYMENT: List[TerraformResource] = [
    *AWS_STANDARD_DEPLOYMENT,
    AWS_VPC_ENDPOINTS,
]

AWS_UNITY_CATALOG_DEPLOYMENT: List[TerraformResource] = [
    *AWS_STANDARD_DEPLOYMENT,
    AWS_UNITY_CATALOG_BUCKET,
]

AWS_FULL_DEPLOYMENT: List[TerraformResource] = [
    AWS_CROSS_ACCOUNT_ROLE,
    AWS_INSTANCE_PROFILE,
    AWS_S3_ROOT_BUCKET,
    AWS_UNITY_CATALOG_BUCKET,
    AWS_VPC,
    AWS_SUBNETS,
    AWS_SECURITY_GROUP,
    AWS_INTERNET_GATEWAY,
    AWS_NAT_GATEWAY,
    AWS_ROUTE_TABLES,
    AWS_VPC_ENDPOINTS,
    AWS_KMS_KEY,
]


# =============================================================================
# AZURE DATABRICKS TERRAFORM ACTIONS
# =============================================================================

AZURE_DATABRICKS_WORKSPACE = TerraformResource(
    name="Databricks Workspace",
    resource_type="azurerm_databricks_workspace",
    description="Azure Databricks workspace resource",
    actions=[
        TerraformAction("Microsoft.Databricks/workspaces/read", "*", "Read workspace"),
        TerraformAction("Microsoft.Databricks/workspaces/write", "*", "Create/update workspace"),
        TerraformAction("Microsoft.Databricks/workspaces/delete", "*", "Delete workspace"),
    ]
)

AZURE_VNET = TerraformResource(
    name="Virtual Network",
    resource_type="azurerm_virtual_network",
    description="VNet for Databricks VNet injection",
    actions=[
        TerraformAction("Microsoft.Network/virtualNetworks/read", "*", "Read VNet"),
        TerraformAction("Microsoft.Network/virtualNetworks/write", "*", "Create/update VNet"),
        TerraformAction("Microsoft.Network/virtualNetworks/delete", "*", "Delete VNet"),
        TerraformAction("Microsoft.Network/virtualNetworks/subnets/read", "*", "Read subnets"),
        TerraformAction("Microsoft.Network/virtualNetworks/subnets/write", "*", "Create/update subnets"),
        TerraformAction("Microsoft.Network/virtualNetworks/subnets/delete", "*", "Delete subnets"),
        TerraformAction("Microsoft.Network/virtualNetworks/subnets/join/action", "*", "Join subnet"),
    ]
)

AZURE_SUBNET_DELEGATION = TerraformResource(
    name="Subnet Delegation",
    resource_type="azurerm_subnet",
    description="Subnets delegated to Databricks (public and private)",
    actions=[
        TerraformAction("Microsoft.Network/virtualNetworks/subnets/write", "*", "Create delegated subnet"),
        TerraformAction("Microsoft.Network/virtualNetworks/subnets/join/action", "*", "Allow delegation"),
        TerraformAction("Microsoft.Databricks/workspaces/virtualNetworkPeerings/read", "*", "Read VNet peering"),
        TerraformAction("Microsoft.Databricks/workspaces/virtualNetworkPeerings/write", "*", "Create VNet peering"),
    ]
)

AZURE_NSG = TerraformResource(
    name="Network Security Group",
    resource_type="azurerm_network_security_group",
    description="NSG for Databricks subnet security",
    actions=[
        TerraformAction("Microsoft.Network/networkSecurityGroups/read", "*", "Read NSG"),
        TerraformAction("Microsoft.Network/networkSecurityGroups/write", "*", "Create/update NSG"),
        TerraformAction("Microsoft.Network/networkSecurityGroups/delete", "*", "Delete NSG"),
        TerraformAction("Microsoft.Network/networkSecurityGroups/join/action", "*", "Associate NSG"),
        TerraformAction("Microsoft.Network/networkSecurityGroups/securityRules/read", "*", "Read rules"),
        TerraformAction("Microsoft.Network/networkSecurityGroups/securityRules/write", "*", "Create/update rules"),
        TerraformAction("Microsoft.Network/networkSecurityGroups/securityRules/delete", "*", "Delete rules"),
    ]
)

AZURE_NAT_GATEWAY = TerraformResource(
    name="NAT Gateway",
    resource_type="azurerm_nat_gateway",
    description="NAT gateway for private workspace egress",
    actions=[
        TerraformAction("Microsoft.Network/natGateways/read", "*", "Read NAT gateway"),
        TerraformAction("Microsoft.Network/natGateways/write", "*", "Create/update NAT gateway"),
        TerraformAction("Microsoft.Network/natGateways/delete", "*", "Delete NAT gateway"),
        TerraformAction("Microsoft.Network/natGateways/join/action", "*", "Associate NAT gateway"),
        TerraformAction("Microsoft.Network/publicIPAddresses/read", "*", "Read public IP"),
        TerraformAction("Microsoft.Network/publicIPAddresses/write", "*", "Create public IP"),
        TerraformAction("Microsoft.Network/publicIPAddresses/delete", "*", "Delete public IP"),
        TerraformAction("Microsoft.Network/publicIPAddresses/join/action", "*", "Associate public IP"),
    ]
)

AZURE_PRIVATE_ENDPOINT = TerraformResource(
    name="Private Endpoint",
    resource_type="azurerm_private_endpoint",
    description="Private endpoint for Databricks Private Link",
    actions=[
        TerraformAction("Microsoft.Network/privateEndpoints/read", "*", "Read private endpoint"),
        TerraformAction("Microsoft.Network/privateEndpoints/write", "*", "Create private endpoint"),
        TerraformAction("Microsoft.Network/privateEndpoints/delete", "*", "Delete private endpoint"),
        TerraformAction("Microsoft.Databricks/workspaces/privateEndpointConnectionsApproval/action", "*", "Approve PE connection"),
    ]
)

AZURE_PRIVATE_DNS = TerraformResource(
    name="Private DNS Zone",
    resource_type="azurerm_private_dns_zone",
    description="Private DNS zones for Private Link resolution",
    actions=[
        TerraformAction("Microsoft.Network/privateDnsZones/read", "*", "Read DNS zone"),
        TerraformAction("Microsoft.Network/privateDnsZones/write", "*", "Create DNS zone"),
        TerraformAction("Microsoft.Network/privateDnsZones/delete", "*", "Delete DNS zone"),
        TerraformAction("Microsoft.Network/privateDnsZones/virtualNetworkLinks/read", "*", "Read VNet link"),
        TerraformAction("Microsoft.Network/privateDnsZones/virtualNetworkLinks/write", "*", "Create VNet link"),
        TerraformAction("Microsoft.Network/privateDnsZones/virtualNetworkLinks/delete", "*", "Delete VNet link"),
        TerraformAction("Microsoft.Network/privateDnsZones/A/read", "*", "Read A records"),
        TerraformAction("Microsoft.Network/privateDnsZones/A/write", "*", "Create A records"),
    ]
)

AZURE_STORAGE_ACCOUNT = TerraformResource(
    name="Storage Account (ADLS Gen2)",
    resource_type="azurerm_storage_account",
    description="ADLS Gen2 storage for Unity Catalog",
    actions=[
        TerraformAction("Microsoft.Storage/storageAccounts/read", "*", "Read storage account"),
        TerraformAction("Microsoft.Storage/storageAccounts/write", "*", "Create storage account"),
        TerraformAction("Microsoft.Storage/storageAccounts/delete", "*", "Delete storage account"),
        TerraformAction("Microsoft.Storage/storageAccounts/listKeys/action", "*", "Get storage keys"),
        TerraformAction("Microsoft.Storage/storageAccounts/blobServices/read", "*", "Read blob service"),
        TerraformAction("Microsoft.Storage/storageAccounts/blobServices/containers/read", "*", "Read containers"),
        TerraformAction("Microsoft.Storage/storageAccounts/blobServices/containers/write", "*", "Create containers"),
        TerraformAction("Microsoft.Storage/storageAccounts/blobServices/containers/delete", "*", "Delete containers"),
    ]
)

AZURE_KEY_VAULT = TerraformResource(
    name="Key Vault",
    resource_type="azurerm_key_vault",
    description="Key Vault for secret-backed scopes and CMK",
    actions=[
        TerraformAction("Microsoft.KeyVault/vaults/read", "*", "Read Key Vault"),
        TerraformAction("Microsoft.KeyVault/vaults/write", "*", "Create Key Vault"),
        TerraformAction("Microsoft.KeyVault/vaults/delete", "*", "Delete Key Vault"),
        TerraformAction("Microsoft.KeyVault/vaults/secrets/read", "*", "Read secrets"),
        TerraformAction("Microsoft.KeyVault/vaults/secrets/write", "*", "Write secrets"),
        TerraformAction("Microsoft.KeyVault/vaults/keys/read", "*", "Read keys"),
        TerraformAction("Microsoft.KeyVault/vaults/keys/write", "*", "Write keys"),
        TerraformAction("Microsoft.KeyVault/vaults/accessPolicies/write", "*", "Set access policies"),
    ]
)

AZURE_MANAGED_IDENTITY = TerraformResource(
    name="User-Assigned Managed Identity",
    resource_type="azurerm_user_assigned_identity",
    description="Managed identity for Unity Catalog access",
    actions=[
        TerraformAction("Microsoft.ManagedIdentity/userAssignedIdentities/read", "*", "Read identity"),
        TerraformAction("Microsoft.ManagedIdentity/userAssignedIdentities/write", "*", "Create identity"),
        TerraformAction("Microsoft.ManagedIdentity/userAssignedIdentities/delete", "*", "Delete identity"),
        TerraformAction("Microsoft.ManagedIdentity/userAssignedIdentities/assign/action", "*", "Assign identity"),
    ]
)

AZURE_ROLE_ASSIGNMENT = TerraformResource(
    name="Role Assignment",
    resource_type="azurerm_role_assignment",
    description="RBAC role assignments for Databricks",
    actions=[
        TerraformAction("Microsoft.Authorization/roleAssignments/read", "*", "Read role assignments"),
        TerraformAction("Microsoft.Authorization/roleAssignments/write", "*", "Create role assignment"),
        TerraformAction("Microsoft.Authorization/roleAssignments/delete", "*", "Delete role assignment"),
        TerraformAction("Microsoft.Authorization/roleDefinitions/read", "*", "Read role definitions"),
    ]
)


# =============================================================================
# AZURE DEPLOYMENT PROFILES
# =============================================================================

AZURE_STANDARD_DEPLOYMENT: List[TerraformResource] = [
    AZURE_DATABRICKS_WORKSPACE,
    AZURE_VNET,
    AZURE_SUBNET_DELEGATION,
    AZURE_NSG,
]

AZURE_PRIVATELINK_DEPLOYMENT: List[TerraformResource] = [
    *AZURE_STANDARD_DEPLOYMENT,
    AZURE_NAT_GATEWAY,
    AZURE_PRIVATE_ENDPOINT,
    AZURE_PRIVATE_DNS,
]

AZURE_UNITY_CATALOG_DEPLOYMENT: List[TerraformResource] = [
    *AZURE_STANDARD_DEPLOYMENT,
    AZURE_STORAGE_ACCOUNT,
    AZURE_MANAGED_IDENTITY,
    AZURE_ROLE_ASSIGNMENT,
]

AZURE_FULL_DEPLOYMENT: List[TerraformResource] = [
    AZURE_DATABRICKS_WORKSPACE,
    AZURE_VNET,
    AZURE_SUBNET_DELEGATION,
    AZURE_NSG,
    AZURE_NAT_GATEWAY,
    AZURE_PRIVATE_ENDPOINT,
    AZURE_PRIVATE_DNS,
    AZURE_STORAGE_ACCOUNT,
    AZURE_KEY_VAULT,
    AZURE_MANAGED_IDENTITY,
    AZURE_ROLE_ASSIGNMENT,
]


# =============================================================================
# GCP DATABRICKS TERRAFORM ACTIONS
# =============================================================================

GCP_VPC_NETWORK = TerraformResource(
    name="VPC Network",
    resource_type="google_compute_network",
    description="Custom VPC for Databricks workspace",
    actions=[
        TerraformAction("compute.networks.create", "*", "Create VPC network"),
        TerraformAction("compute.networks.delete", "*", "Delete VPC network"),
        TerraformAction("compute.networks.get", "*", "Read VPC network"),
        TerraformAction("compute.networks.updatePolicy", "*", "Update network policy"),
    ]
)

GCP_SUBNETWORK = TerraformResource(
    name="Subnetwork",
    resource_type="google_compute_subnetwork",
    description="Subnet for Databricks with Private Google Access",
    actions=[
        TerraformAction("compute.subnetworks.create", "*", "Create subnet"),
        TerraformAction("compute.subnetworks.delete", "*", "Delete subnet"),
        TerraformAction("compute.subnetworks.get", "*", "Read subnet"),
        TerraformAction("compute.subnetworks.update", "*", "Update subnet"),
        TerraformAction("compute.subnetworks.use", "*", "Use subnet"),
        TerraformAction("compute.subnetworks.setPrivateIpGoogleAccess", "*", "Enable Private Google Access"),
    ]
)

GCP_FIREWALL = TerraformResource(
    name="Firewall Rules",
    resource_type="google_compute_firewall",
    description="Firewall rules for Databricks cluster communication",
    actions=[
        TerraformAction("compute.firewalls.create", "*", "Create firewall rule"),
        TerraformAction("compute.firewalls.delete", "*", "Delete firewall rule"),
        TerraformAction("compute.firewalls.get", "*", "Read firewall rule"),
        TerraformAction("compute.firewalls.update", "*", "Update firewall rule"),
    ]
)

GCP_ROUTER = TerraformResource(
    name="Cloud Router",
    resource_type="google_compute_router",
    description="Cloud Router for NAT gateway",
    actions=[
        TerraformAction("compute.routers.create", "*", "Create router"),
        TerraformAction("compute.routers.delete", "*", "Delete router"),
        TerraformAction("compute.routers.get", "*", "Read router"),
        TerraformAction("compute.routers.update", "*", "Update router (add NAT)"),
    ]
)

GCP_NAT = TerraformResource(
    name="Cloud NAT",
    resource_type="google_compute_router_nat",
    description="Cloud NAT for private cluster egress",
    actions=[
        TerraformAction("compute.routers.update", "*", "Configure NAT on router"),
        TerraformAction("compute.routers.get", "*", "Read router/NAT config"),
    ]
)

GCP_SERVICE_ACCOUNT = TerraformResource(
    name="Service Account",
    resource_type="google_service_account",
    description="Service account for Databricks nodes",
    actions=[
        TerraformAction("iam.serviceAccounts.create", "*", "Create service account"),
        TerraformAction("iam.serviceAccounts.delete", "*", "Delete service account"),
        TerraformAction("iam.serviceAccounts.get", "*", "Read service account"),
        TerraformAction("iam.serviceAccounts.actAs", "*", "Use service account"),
        TerraformAction("iam.serviceAccountKeys.create", "*", "Create SA key"),
        TerraformAction("iam.serviceAccountKeys.delete", "*", "Delete SA key"),
    ]
)

GCP_IAM_BINDING = TerraformResource(
    name="IAM Binding",
    resource_type="google_project_iam_binding",
    description="IAM role bindings for Databricks",
    actions=[
        TerraformAction("resourcemanager.projects.getIamPolicy", "*", "Read IAM policy"),
        TerraformAction("resourcemanager.projects.setIamPolicy", "*", "Set IAM policy"),
    ]
)

GCP_STORAGE_BUCKET = TerraformResource(
    name="GCS Bucket",
    resource_type="google_storage_bucket",
    description="GCS bucket for Unity Catalog",
    actions=[
        TerraformAction("storage.buckets.create", "*", "Create bucket"),
        TerraformAction("storage.buckets.delete", "*", "Delete bucket"),
        TerraformAction("storage.buckets.get", "*", "Read bucket"),
        TerraformAction("storage.buckets.update", "*", "Update bucket"),
        TerraformAction("storage.buckets.getIamPolicy", "*", "Read bucket IAM"),
        TerraformAction("storage.buckets.setIamPolicy", "*", "Set bucket IAM"),
        TerraformAction("storage.objects.create", "*", "Write objects"),
        TerraformAction("storage.objects.delete", "*", "Delete objects"),
        TerraformAction("storage.objects.get", "*", "Read objects"),
        TerraformAction("storage.objects.list", "*", "List objects"),
    ]
)

GCP_KMS_KEYRING = TerraformResource(
    name="KMS Key Ring",
    resource_type="google_kms_key_ring",
    description="KMS key ring for CMEK",
    actions=[
        TerraformAction("cloudkms.keyRings.create", "*", "Create key ring"),
        TerraformAction("cloudkms.keyRings.get", "*", "Read key ring"),
        TerraformAction("cloudkms.keyRings.getIamPolicy", "*", "Read key ring IAM"),
        TerraformAction("cloudkms.keyRings.setIamPolicy", "*", "Set key ring IAM"),
    ]
)

GCP_KMS_KEY = TerraformResource(
    name="KMS Crypto Key",
    resource_type="google_kms_crypto_key",
    description="KMS key for CMEK encryption",
    actions=[
        TerraformAction("cloudkms.cryptoKeys.create", "*", "Create crypto key"),
        TerraformAction("cloudkms.cryptoKeys.get", "*", "Read crypto key"),
        TerraformAction("cloudkms.cryptoKeys.update", "*", "Update crypto key"),
        TerraformAction("cloudkms.cryptoKeys.getIamPolicy", "*", "Read key IAM"),
        TerraformAction("cloudkms.cryptoKeys.setIamPolicy", "*", "Set key IAM"),
        TerraformAction("cloudkms.cryptoKeyVersions.useToEncrypt", "*", "Use key to encrypt"),
        TerraformAction("cloudkms.cryptoKeyVersions.useToDecrypt", "*", "Use key to decrypt"),
    ]
)


# =============================================================================
# GCP DEPLOYMENT PROFILES
# =============================================================================

GCP_STANDARD_DEPLOYMENT: List[TerraformResource] = [
    GCP_VPC_NETWORK,
    GCP_SUBNETWORK,
    GCP_FIREWALL,
    GCP_ROUTER,
    GCP_NAT,
    GCP_SERVICE_ACCOUNT,
    GCP_IAM_BINDING,
]

GCP_UNITY_CATALOG_DEPLOYMENT: List[TerraformResource] = [
    *GCP_STANDARD_DEPLOYMENT,
    GCP_STORAGE_BUCKET,
]

GCP_FULL_DEPLOYMENT: List[TerraformResource] = [
    GCP_VPC_NETWORK,
    GCP_SUBNETWORK,
    GCP_FIREWALL,
    GCP_ROUTER,
    GCP_NAT,
    GCP_SERVICE_ACCOUNT,
    GCP_IAM_BINDING,
    GCP_STORAGE_BUCKET,
    GCP_KMS_KEYRING,
    GCP_KMS_KEY,
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_all_actions_for_profile(resources: List[TerraformResource]) -> List[str]:
    """Get all unique actions from a deployment profile."""
    actions = set()
    for resource in resources:
        for action in resource.actions:
            actions.add(action.action)
    return sorted(list(actions))


def get_aws_deployment_profile(mode: DeploymentMode) -> List[TerraformResource]:
    """Get AWS deployment profile based on mode."""
    if mode == DeploymentMode.STANDARD:
        return AWS_STANDARD_DEPLOYMENT
    elif mode == DeploymentMode.PRIVATE_LINK:
        return AWS_PRIVATELINK_DEPLOYMENT
    elif mode == DeploymentMode.UNITY_CATALOG:
        return AWS_UNITY_CATALOG_DEPLOYMENT
    else:
        return AWS_FULL_DEPLOYMENT


def get_azure_deployment_profile(mode: DeploymentMode) -> List[TerraformResource]:
    """Get Azure deployment profile based on mode."""
    if mode == DeploymentMode.STANDARD:
        return AZURE_STANDARD_DEPLOYMENT
    elif mode == DeploymentMode.PRIVATE_LINK:
        return AZURE_PRIVATELINK_DEPLOYMENT
    elif mode == DeploymentMode.UNITY_CATALOG:
        return AZURE_UNITY_CATALOG_DEPLOYMENT
    else:
        return AZURE_FULL_DEPLOYMENT


def get_gcp_deployment_profile(mode: DeploymentMode) -> List[TerraformResource]:
    """Get GCP deployment profile based on mode."""
    if mode == DeploymentMode.STANDARD:
        return GCP_STANDARD_DEPLOYMENT
    elif mode == DeploymentMode.UNITY_CATALOG:
        return GCP_UNITY_CATALOG_DEPLOYMENT
    else:
        return GCP_FULL_DEPLOYMENT

