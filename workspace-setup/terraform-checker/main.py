#!/usr/bin/env python3
"""
Databricks Terraform Pre-Check CLI

A tool to validate credentials, permissions, and resources before deploying
Databricks workspaces on AWS, Azure, and GCP.

This tool tests permissions by creating TEMPORARY resources and cleaning up.
"""

import sys
import json
import logging
from typing import List, Optional
from pathlib import Path

import click

from checkers import AWSChecker, AzureChecker, GCPChecker
from checkers.base import CheckReport
from checkers.databricks_actions import DeploymentMode, VPCType
from reporters import TxtReporter, JsonReporter
from utils import CredentialLoader, ExitCode, load_config, setup_logging


# Configure root logger
logger = logging.getLogger(__name__)


def print_banner():
    """Print the tool banner."""
    banner = """
╔═══════════════════════════════════════════════════════════════════════╗
║         DATABRICKS TERRAFORM PRE-CHECK                                ║
║         Validate your cloud environment before deployment             ║
║                                                                       ║
║  Tests permissions by creating temporary resources and cleaning up    ║
║  Zero leftover resources - Complete diagnostic before Terraform runs  ║
╚═══════════════════════════════════════════════════════════════════════╝
"""
    click.echo(click.style(banner, fg="cyan"))


def cleanup_orphaned_resources(cloud: Optional[str], region: Optional[str], profile: Optional[str]):
    """Find and delete any orphaned test resources."""
    prefix = "dbx-precheck-temp"
    
    if cloud == "aws" or cloud is None:
        try:
            import boto3
            
            if profile:
                session = boto3.Session(profile_name=profile, region_name=region or "us-east-1")
            else:
                session = boto3.Session(region_name=region or "us-east-1")
            
            orphans_found = False
            
            # Check S3 buckets
            s3 = session.client("s3")
            try:
                buckets = s3.list_buckets().get("Buckets", [])
                orphan_buckets = [b["Name"] for b in buckets if b["Name"].startswith(prefix)]
                
                if orphan_buckets:
                    orphans_found = True
                    click.echo(click.style(f"\n📦 Found {len(orphan_buckets)} orphaned S3 bucket(s):", fg="yellow"))
                    for bucket in orphan_buckets:
                        click.echo(f"   - {bucket}")
                        try:
                            s3.delete_bucket(Bucket=bucket)
                            click.echo(click.style(f"     ✓ Deleted", fg="green"))
                        except Exception as e:
                            click.echo(click.style(f"     ✗ Error: {str(e)[:50]}", fg="red"))
            except Exception as e:
                click.echo(f"   Could not check S3: {str(e)[:50]}")
            
            # Check IAM Roles
            iam = session.client("iam")
            try:
                roles = iam.list_roles().get("Roles", [])
                orphan_roles = [r["RoleName"] for r in roles if r["RoleName"].startswith(prefix)]
                
                if orphan_roles:
                    orphans_found = True
                    click.echo(click.style(f"\n👤 Found {len(orphan_roles)} orphaned IAM role(s):", fg="yellow"))
                    for role in orphan_roles:
                        click.echo(f"   - {role}")
                        try:
                            # Delete inline policies
                            inline = iam.list_role_policies(RoleName=role).get("PolicyNames", [])
                            for policy in inline:
                                iam.delete_role_policy(RoleName=role, PolicyName=policy)
                            # Delete attached policies
                            attached = iam.list_attached_role_policies(RoleName=role).get("AttachedPolicies", [])
                            for policy in attached:
                                iam.detach_role_policy(RoleName=role, PolicyArn=policy["PolicyArn"])
                            # Delete role
                            iam.delete_role(RoleName=role)
                            click.echo(click.style(f"     ✓ Deleted", fg="green"))
                        except Exception as e:
                            click.echo(click.style(f"     ✗ Error: {str(e)[:50]}", fg="red"))
            except Exception as e:
                click.echo(f"   Could not check IAM Roles: {str(e)[:50]}")
            
            # Check IAM Policies
            try:
                policies = iam.list_policies(Scope='Local').get("Policies", [])
                orphan_policies = [p for p in policies if p["PolicyName"].startswith(prefix)]
                
                if orphan_policies:
                    orphans_found = True
                    click.echo(click.style(f"\n📜 Found {len(orphan_policies)} orphaned IAM policy(ies):", fg="yellow"))
                    for policy in orphan_policies:
                        click.echo(f"   - {policy['PolicyName']}")
                        try:
                            # Delete non-default versions
                            versions = iam.list_policy_versions(PolicyArn=policy["Arn"]).get("Versions", [])
                            for v in versions:
                                if not v["IsDefaultVersion"]:
                                    iam.delete_policy_version(PolicyArn=policy["Arn"], VersionId=v["VersionId"])
                            # Delete policy
                            iam.delete_policy(PolicyArn=policy["Arn"])
                            click.echo(click.style(f"     ✓ Deleted", fg="green"))
                        except Exception as e:
                            click.echo(click.style(f"     ✗ Error: {str(e)[:50]}", fg="red"))
            except Exception as e:
                click.echo(f"   Could not check IAM Policies: {str(e)[:50]}")
            
            # Check Security Groups
            ec2 = session.client("ec2")
            try:
                sgs = ec2.describe_security_groups().get("SecurityGroups", [])
                orphan_sgs = [sg for sg in sgs if sg["GroupName"].startswith(prefix)]
                
                if orphan_sgs:
                    orphans_found = True
                    click.echo(click.style(f"\n🔒 Found {len(orphan_sgs)} orphaned Security Group(s):", fg="yellow"))
                    for sg in orphan_sgs:
                        click.echo(f"   - {sg['GroupId']} ({sg['GroupName']})")
                        try:
                            ec2.delete_security_group(GroupId=sg["GroupId"])
                            click.echo(click.style(f"     ✓ Deleted", fg="green"))
                        except Exception as e:
                            click.echo(click.style(f"     ✗ Error: {str(e)[:50]}", fg="red"))
            except Exception as e:
                click.echo(f"   Could not check Security Groups: {str(e)[:50]}")
            
            if not orphans_found:
                click.echo(click.style("\n✓ No orphaned test resources found!", fg="green"))
            else:
                click.echo(click.style("\n✓ Cleanup complete!", fg="green"))
                
        except ImportError:
            click.echo(click.style("AWS SDK (boto3) not installed", fg="red"))
        except Exception as e:
            click.echo(click.style(f"Error: {e}", fg="red"))


def show_dry_run_plan(mode: str, vpc_type: str):
    """Show what would be tested without creating anything."""
    click.echo("""
┌─────────────────────────────────────────────────────────────────────┐
│                     DRY-RUN: TEST PLAN                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  The following TEMPORARY resources would be created and deleted:    │
│                                                                     │
│  ┌─ S3 BUCKET (empty, 0 bytes, $0.00 cost) ─────────────────────┐  │
│  │  Name: dbx-precheck-temp-{account_id}-{uuid}                 │  │
│  │  Tests: CreateBucket, PutBucketVersioning, PutBucketPolicy,  │  │
│  │         PutEncryptionConfiguration, PutBucketTagging         │  │
│  │  Cleanup: DeleteBucket (immediate)                           │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ IAM ROLE (no permissions attached) ─────────────────────────┐  │
│  │  Name: dbx-precheck-temp-role-{uuid}                         │  │
│  │  Tests: CreateRole, GetRole, TagRole, PutRolePolicy          │  │
│  │  Cleanup: DeleteRolePolicy, DeleteRole (immediate)           │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ IAM POLICY (deny-all, no effect) ───────────────────────────┐  │
│  │  Name: dbx-precheck-temp-policy-{uuid}                       │  │
│  │  Tests: CreatePolicy, GetPolicy, CreatePolicyVersion         │  │
│  │  Cleanup: DeletePolicyVersion, DeletePolicy (immediate)      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ SECURITY GROUP (empty, no rules) ───────────────────────────┐  │
│  │  Name: dbx-precheck-temp-sg-{uuid}                           │  │
│  │  Tests: CreateSecurityGroup, AuthorizeIngress/Egress         │  │
│  │  Cleanup: DeleteSecurityGroup (immediate)                    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ EC2/VPC TESTS (DryRun=True, NOTHING CREATED) ───────────────┐  │
│  │  CreateVpc, CreateSubnet, CreateInternetGateway              │  │
│  │  RunInstances, CreateVolume, AllocateAddress                 │  │
│  │  → Uses AWS DryRun feature, no actual resources created      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  GUARANTEES:                                                        │
│  ✓ All temporary resources are deleted immediately after testing   │
│  ✓ Resources use prefix "dbx-precheck-temp-" for easy identification│
│  ✓ EC2/VPC tests use DryRun (nothing created)                      │
│  ✓ Run --cleanup-orphans to find/delete any leftover resources     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

To run the actual tests: Remove the --dry-run flag
To cleanup orphans:      python main.py --cleanup-orphans --cloud aws
""")


def get_deployment_mode(mode_str: str) -> DeploymentMode:
    """Convert string to DeploymentMode enum."""
    mode_map = {
        "standard": DeploymentMode.STANDARD,
        "privatelink": DeploymentMode.PRIVATE_LINK,
        "unity": DeploymentMode.UNITY_CATALOG,
        "unity_catalog": DeploymentMode.UNITY_CATALOG,
        "full": DeploymentMode.UNITY_CATALOG,  # Full includes everything
    }
    return mode_map.get(mode_str.lower(), DeploymentMode.STANDARD)


def get_vpc_type(vpc_str: str) -> VPCType:
    """Convert string to VPCType enum."""
    vpc_map = {
        "databricks": VPCType.DATABRICKS_MANAGED,
        "databricks_managed": VPCType.DATABRICKS_MANAGED,
        "managed": VPCType.DATABRICKS_MANAGED,
        "customer": VPCType.CUSTOMER_MANAGED_DEFAULT,
        "customer_managed": VPCType.CUSTOMER_MANAGED_DEFAULT,
        "customer_default": VPCType.CUSTOMER_MANAGED_DEFAULT,
        "default": VPCType.CUSTOMER_MANAGED_DEFAULT,
        "custom": VPCType.CUSTOMER_MANAGED_CUSTOM,
        "customer_custom": VPCType.CUSTOMER_MANAGED_CUSTOM,
    }
    return vpc_map.get(vpc_str.lower(), VPCType.CUSTOMER_MANAGED_DEFAULT)


def run_aws_checks(
    region: Optional[str], 
    profile: Optional[str],
    deployment_mode: DeploymentMode,
    vpc_type: VPCType,
) -> tuple:
    """Run AWS checks and return the report and checker instance."""
    vpc_type_name = {
        VPCType.DATABRICKS_MANAGED: "Databricks-managed",
        VPCType.CUSTOMER_MANAGED_DEFAULT: "Customer-managed (default)",
        VPCType.CUSTOMER_MANAGED_CUSTOM: "Customer-managed (custom)",
    }.get(vpc_type, "Unknown")
    
    click.echo(click.style(f"\n▶ Running AWS checks...", fg="yellow"))
    click.echo(f"   Mode: {deployment_mode.value} | VPC: {vpc_type_name}")
    click.echo(click.style("   Testing with REAL temporary resources (create → verify → delete)", fg="cyan"))
    
    try:
        checker = AWSChecker(
            region=region, 
            profile=profile,
            deployment_mode=deployment_mode,
            vpc_type=vpc_type,
        )
        report = checker.run_all_checks()
        
        if report.total_not_ok > 0:
            click.echo(click.style("  ✗ AWS checks completed with errors", fg="red"))
        elif report.total_warning > 0:
            click.echo(click.style("  ⚠ AWS checks completed with warnings", fg="yellow"))
        else:
            click.echo(click.style("  ✓ AWS checks passed", fg="green"))
        
        return report, checker
    except ImportError as e:
        click.echo(click.style(f"  ✗ AWS SDK not installed: {e}", fg="red"))
        click.echo("    Install with: pip install boto3")
        return None, None
    except Exception as e:
        click.echo(click.style(f"  ✗ AWS check failed: {e}", fg="red"))
        return None, None


def get_azure_deployment_mode(mode_str: str):
    """Convert string to Azure deployment mode."""
    from checkers.azure import AzureDeploymentMode
    
    mode_map = {
        "standard": AzureDeploymentMode.STANDARD,
        "vnet": AzureDeploymentMode.VNET_INJECTION,
        "unity": AzureDeploymentMode.UNITY_CATALOG,
        "unity_catalog": AzureDeploymentMode.UNITY_CATALOG,
        "privatelink": AzureDeploymentMode.PRIVATELINK,
        "full": AzureDeploymentMode.FULL,
    }
    return mode_map.get(mode_str.lower(), AzureDeploymentMode.STANDARD)


def run_azure_checks(
    region: Optional[str],
    subscription_id: Optional[str],
    resource_group: Optional[str],
    deployment_mode: str = "standard",
) -> Optional[CheckReport]:
    """Run Azure checks and return the report."""
    from checkers.azure import AzureDeploymentMode
    
    azure_mode = get_azure_deployment_mode(deployment_mode)
    
    mode_display = {
        AzureDeploymentMode.STANDARD: "Standard (Databricks-managed VNet + Storage)",
        AzureDeploymentMode.VNET_INJECTION: "VNet Injection (Customer-managed VNet)",
        AzureDeploymentMode.UNITY_CATALOG: "Unity Catalog (Customer-managed Storage)",
        AzureDeploymentMode.PRIVATELINK: "Private Link + SCC + NAT Gateway",
        AzureDeploymentMode.FULL: "Full (VNet + Unity + Private Link)",
    }.get(azure_mode, deployment_mode)
    
    click.echo(click.style("\n▶ Running Azure checks...", fg="yellow"))
    click.echo(f"   Mode: {mode_display}")
    click.echo(click.style("   Testing with REAL temporary resources (create → verify → delete)", fg="cyan"))
    
    try:
        checker = AzureChecker(
            region=region,
            subscription_id=subscription_id,
            resource_group=resource_group,
            deployment_mode=azure_mode,
        )
        report = checker.run_all_checks()
        
        if report.total_not_ok > 0:
            click.echo(click.style("  ✗ Azure checks completed with errors", fg="red"))
        elif report.total_warning > 0:
            click.echo(click.style("  ⚠ Azure checks completed with warnings", fg="yellow"))
        else:
            click.echo(click.style("  ✓ Azure checks passed", fg="green"))
        
        return report
    except ImportError as e:
        click.echo(click.style(f"  ✗ Azure SDK not installed: {e}", fg="red"))
        click.echo("    Install with: pip install azure-identity azure-mgmt-resource azure-mgmt-network azure-mgmt-storage")
        return None
    except Exception as e:
        click.echo(click.style(f"  ✗ Azure check failed: {e}", fg="red"))
        return None


def run_gcp_checks(
    region: Optional[str],
    project: Optional[str],
    credentials_file: Optional[str],
) -> Optional[CheckReport]:
    """Run GCP checks and return the report."""
    click.echo(click.style("\n▶ Running GCP checks...", fg="yellow"))
    
    try:
        checker = GCPChecker(
            region=region,
            project_id=project,
            credentials_file=credentials_file,
        )
        report = checker.run_all_checks()
        
        if report.total_not_ok > 0:
            click.echo(click.style("  ✗ GCP checks completed with errors", fg="red"))
        elif report.total_warning > 0:
            click.echo(click.style("  ⚠ GCP checks completed with warnings", fg="yellow"))
        else:
            click.echo(click.style("  ✓ GCP checks passed", fg="green"))
        
        return report
    except ImportError as e:
        click.echo(click.style(f"  ✗ GCP SDK not installed: {e}", fg="red"))
        click.echo("    Install with: pip install google-cloud-storage google-api-python-client google-auth")
        return None
    except Exception as e:
        click.echo(click.style(f"  ✗ GCP check failed: {e}", fg="red"))
        return None


@click.command()
@click.option(
    "--cloud", "-c",
    type=click.Choice(["aws", "azure", "gcp"], case_sensitive=False),
    help="Cloud provider to check (aws, azure, gcp)"
)
@click.option(
    "--all", "-a", "check_all",
    is_flag=True,
    help="Check all cloud providers with detected credentials"
)
@click.option(
    "--mode", "-m",
    type=click.Choice(["standard", "privatelink", "unity", "full"], case_sensitive=False),
    default="standard",
    help="Deployment mode: standard, privatelink, unity (Unity Catalog), full"
)
@click.option(
    "--vpc-type",
    type=click.Choice(["databricks", "customer", "custom"], case_sensitive=False),
    default="customer",
    help="VPC type: databricks (Databricks-managed), customer (Customer-managed default), custom (Customer-managed custom)"
)
@click.option(
    "--region", "-r",
    help="Cloud region (e.g., us-east-1, eastus, us-central1)"
)
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output file path for the report (TXT format)"
)
# AWS-specific options
@click.option(
    "--profile",
    help="AWS profile name (from ~/.aws/credentials)"
)
# Azure-specific options
@click.option(
    "--subscription-id",
    help="Azure subscription ID"
)
@click.option(
    "--resource-group",
    help="Azure resource group name"
)
# GCP-specific options
@click.option(
    "--project",
    help="GCP project ID"
)
@click.option(
    "--credentials-file",
    type=click.Path(exists=True),
    help="GCP service account credentials JSON file"
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable verbose output"
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be tested WITHOUT creating any resources"
)
@click.option(
    "--cleanup-orphans",
    is_flag=True,
    help="Find and delete any leftover test resources (dbx-precheck-temp-*)"
)
# New options for production use
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="Output results in JSON format (for CI/CD pipelines)"
)
@click.option(
    "--log-level",
    type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
    default="info",
    help="Set logging verbosity level"
)
@click.option(
    "--log-file",
    type=click.Path(),
    help="Write logs to file (in addition to console)"
)
@click.option(
    "--config", "-C",
    type=click.Path(exists=True),
    help="Path to configuration file (precheck.yaml)"
)
@click.option(
    "--quiet", "-q",
    is_flag=True,
    help="Suppress banner and progress output (only show results)"
)
@click.version_option(
    version="1.0.0",
    prog_name="Databricks Terraform Pre-Check"
)
def main(
    cloud: Optional[str],
    check_all: bool,
    mode: str,
    vpc_type: str,
    region: Optional[str],
    output: Optional[str],
    profile: Optional[str],
    subscription_id: Optional[str],
    resource_group: Optional[str],
    project: Optional[str],
    credentials_file: Optional[str],
    verbose: bool,
    dry_run: bool,
    cleanup_orphans: bool,
    json_output: bool,
    log_level: str,
    log_file: Optional[str],
    config: Optional[str],
    quiet: bool,
):
    """
    Databricks Terraform Pre-Check Tool
    
    Validates credentials, permissions, and resources BEFORE running Terraform.
    This tool SIMULATES permissions without creating any resources.
    
    \b
    DEPLOYMENT MODES:
      standard    - Basic workspace (VPC, S3/Storage, IAM)
      privatelink - With PrivateLink/VPC Endpoints
      unity       - With Unity Catalog storage
      full        - All features (PrivateLink + Unity Catalog + CMK)
    
    \b
    VPC TYPES (AWS):
      databricks  - Databricks creates and manages VPC
      customer    - Customer-managed VPC with default restrictions
      custom      - Customer-managed VPC with custom restrictions
    
    \b
    EXAMPLES:
      # Standard deployment with customer-managed VPC
      python main.py --cloud aws --region us-east-1
    
      # Databricks-managed VPC
      python main.py --cloud aws --vpc-type databricks
    
      # Full deployment with Unity Catalog
      python main.py --cloud aws --mode full --vpc-type customer
    
      # Azure with subscription
      python main.py --cloud azure --subscription-id xxx --mode full
    
      # Save report to file
      python main.py --cloud aws --output pre-check-report.txt
    
      # JSON output for CI/CD
      python main.py --cloud aws --json --quiet
    
      # Debug mode with log file
      python main.py --cloud aws --log-level debug --log-file debug.log
    """
    # Setup logging
    log_config = setup_logging(level=log_level, log_file=log_file)
    logger.debug("Starting Databricks Terraform Pre-Check v1.0.0")
    
    # Load config file if specified
    file_config = None
    if config:
        file_config = load_config(config)
        if file_config:
            logger.info("Loaded configuration from %s", config)
    
    # Print banner (unless quiet mode or JSON output)
    if not quiet and not json_output:
        print_banner()
    
    # Handle cleanup-orphans mode
    if cleanup_orphans:
        click.echo(click.style("\n🧹 Searching for orphaned test resources...", fg="yellow"))
        cleanup_orphaned_resources(cloud, region, profile)
        sys.exit(0)
    
    # Handle dry-run mode
    if dry_run:
        click.echo(click.style("\n🔍 DRY-RUN MODE - No resources will be created", fg="cyan", bold=True))
        show_dry_run_plan(mode, vpc_type)
        sys.exit(0)
    
    deployment_mode = get_deployment_mode(mode)
    vpc_type_enum = get_vpc_type(vpc_type)
    
    vpc_type_display = {
        VPCType.DATABRICKS_MANAGED: "Databricks-managed",
        VPCType.CUSTOMER_MANAGED_DEFAULT: "Customer-managed (default)",
        VPCType.CUSTOMER_MANAGED_CUSTOM: "Customer-managed (custom)",
    }.get(vpc_type_enum, vpc_type)
    
    click.echo(f"Deployment mode: {click.style(deployment_mode.value, fg='cyan', bold=True)}")
    click.echo(f"VPC type: {click.style(vpc_type_display, fg='cyan', bold=True)}")
    
    if not cloud and not check_all:
        click.echo("\nNo cloud specified. Detecting available credentials...")
        available = CredentialLoader.detect_available_clouds()
        
        available_clouds = [c for c, v in available.items() if v]
        
        if not available_clouds:
            click.echo(click.style("\n✗ No cloud credentials detected!", fg="red"))
            click.echo("\nPlease configure credentials for at least one cloud provider:")
            click.echo("  AWS:   Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or configure ~/.aws/credentials")
            click.echo("  Azure: Set AZURE_CLIENT_ID/AZURE_CLIENT_SECRET/AZURE_TENANT_ID or run 'az login'")
            click.echo("  GCP:   Set GOOGLE_APPLICATION_CREDENTIALS or run 'gcloud auth application-default login'")
            sys.exit(1)
        
        click.echo(f"\nDetected credentials for: {', '.join(c.upper() for c in available_clouds)}")
        
        if len(available_clouds) == 1:
            cloud = available_clouds[0]
            click.echo(f"Automatically selecting {cloud.upper()}")
        else:
            check_all = True
            click.echo("Running checks for all detected clouds...")
    
    reports: List[CheckReport] = []
    aws_checker = None
    
    if check_all:
        available = CredentialLoader.detect_available_clouds()
        
        if available.get("aws"):
            report, checker = run_aws_checks(region, profile, deployment_mode, vpc_type_enum)
            if report:
                reports.append(report)
                aws_checker = checker
        
        if available.get("azure"):
            report = run_azure_checks(region, subscription_id, resource_group, mode)
            if report:
                reports.append(report)
        
        if available.get("gcp"):
            report = run_gcp_checks(region, project, credentials_file)
            if report:
                reports.append(report)
    else:
        if cloud == "aws":
            report, checker = run_aws_checks(region, profile, deployment_mode, vpc_type_enum)
            if report:
                reports.append(report)
                aws_checker = checker
        elif cloud == "azure":
            report = run_azure_checks(region, subscription_id, resource_group, mode)
            if report:
                reports.append(report)
        elif cloud == "gcp":
            report = run_gcp_checks(region, project, credentials_file)
            if report:
                reports.append(report)
    
    if not reports:
        logger.error("No checks were completed successfully")
        if not json_output:
            click.echo(click.style("\n✗ No checks were completed successfully.", fg="red"))
        sys.exit(ExitCode.PROVIDER_ERROR)
    
    # Calculate totals
    total_not_ok = sum(r.total_not_ok for r in reports)
    total_warning = sum(r.total_warning for r in reports)
    
    # Determine exit code
    if total_not_ok > 0:
        exit_code = ExitCode.PERMISSION_DENIED
    else:
        exit_code = ExitCode.SUCCESS
    
    # JSON output mode
    if json_output:
        json_reporter = JsonReporter(pretty=True)
        if len(reports) == 1:
            json_content = json_reporter.generate(reports[0])
        else:
            # Combine multiple reports
            combined = {
                "version": "1.0",
                "clouds": [json.loads(json_reporter.generate(r)) for r in reports],
                "overall_status": "FAILED" if total_not_ok > 0 else ("WARNING" if total_warning > 0 else "PASSED"),
                "exit_code": int(exit_code),
            }
            json_content = json.dumps(combined, indent=2)
        
        click.echo(json_content)
        
        # Save to file if requested
        if output:
            with open(output, 'w') as f:
                f.write(json_content)
            logger.info("JSON report saved to %s", output)
        
        sys.exit(exit_code)
    
    # Text output mode
    reporter = TxtReporter()
    
    if len(reports) == 1:
        report_content = reporter.generate(reports[0])
    else:
        report_content = reporter.generate_all_clouds(reports)
    
    # Print report
    click.echo("\n" + "─" * 70)
    click.echo(report_content)
    
    # Save to file if requested
    if output:
        with open(output, 'w') as f:
            f.write(report_content)
        click.echo(f"\n✓ Report saved to: {output}")
        logger.info("Report saved to %s", output)
    
    # Summary
    click.echo()
    if total_not_ok > 0:
        click.echo(click.style(
            f"⚠️  {total_not_ok} permission(s) DENIED - Terraform deployment will likely FAIL",
            fg="red", bold=True
        ))
        click.echo("   Review the report above and fix missing permissions before running terraform apply")
        logger.warning("%d permission(s) denied", total_not_ok)
        
        # Generate suggested policy for AWS
        if aws_checker and cloud == "aws":
            aws_report = reports[0] if reports else None
            if aws_report:
                suggested_policy = aws_checker.generate_suggested_policy(aws_report)
                if suggested_policy:
                    click.echo()
                    click.echo(click.style("╔══════════════════════════════════════════════════════════════════════╗", fg="yellow"))
                    click.echo(click.style("║  📋 SUGGESTED IAM POLICY - Add this policy to fix the issues        ║", fg="yellow"))
                    click.echo(click.style("╠══════════════════════════════════════════════════════════════════════╣", fg="yellow"))
                    click.echo(click.style("║                                                                      ║", fg="yellow"))
                    click.echo(click.style("║  HOW TO APPLY:                                                       ║", fg="yellow"))
                    click.echo(click.style("║  1. Go to AWS Console → IAM → Policies → Create Policy              ║", fg="yellow"))
                    click.echo(click.style("║  2. Paste the JSON below                                             ║", fg="yellow"))
                    click.echo(click.style("║  3. Attach the policy to your user/role                              ║", fg="yellow"))
                    click.echo(click.style("║                                                                      ║", fg="yellow"))
                    click.echo(click.style("╚══════════════════════════════════════════════════════════════════════╝", fg="yellow"))
                    click.echo()
                    click.echo(json.dumps(suggested_policy, indent=2))
                    click.echo()
                    
                    # Save suggested policy to file
                    policy_file = output.replace('.txt', '-policy.json') if output else 'suggested-policy.json'
                    with open(policy_file, 'w') as f:
                        json.dump(suggested_policy, f, indent=2)
                    click.echo(click.style(f"✓ Policy saved to: {policy_file}", fg="green"))
                    click.echo(click.style("  You can import this file directly in the AWS Console", fg="cyan"))
        
        sys.exit(exit_code)
    elif total_warning > 0:
        click.echo(click.style(
            f"✓ Pre-check passed with {total_warning} warning(s)",
            fg="yellow", bold=True
        ))
        click.echo("  You can proceed with terraform apply, but review warnings")
        logger.info("Pre-check passed with %d warning(s)", total_warning)
        sys.exit(exit_code)
    else:
        click.echo(click.style(
            "✓ Pre-check PASSED - All permissions verified",
            fg="green", bold=True
        ))
        click.echo("  You can proceed with terraform apply")
        logger.info("Pre-check PASSED - All permissions verified")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
