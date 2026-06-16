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
from reporters import TxtReporter, JsonReporter, MarkdownReporter
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


def _progress(message: str, *, fg: Optional[str] = None, bold: bool = False) -> None:
    """Emit human progress/status to STDERR so STDOUT stays a pure report.

    This keeps `--json` output parseable and the Markdown report clean when
    stdout is piped to a file or a CI step, while a human running interactively
    still sees the progress (stderr also goes to the terminal).
    """
    text = click.style(message, fg=fg, bold=bold) if (fg or bold) else message
    click.echo(text, err=True)


def cleanup_orphaned_resources(
    cloud: Optional[str],
    region: Optional[str],
    profile: Optional[str],
    subscription_id: Optional[str] = None,
):
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

    if cloud == "azure" or cloud is None:
        cleanup_azure_orphans(subscription_id, region)

    if cloud == "gcp":
        click.echo(click.style(
            "\nℹ️  GCP checks are read-only - they never create resources, "
            "so there is nothing to clean up.", fg="cyan"
        ))


def cleanup_azure_orphans(subscription_id: Optional[str], region: Optional[str]):
    """Find and delete orphaned Azure test resource groups (prefix dbxprecheck-*).

    Read-first: lists matching resource groups and asks for confirmation before
    deleting. Deleting the resource group cascades to all contained resources.
    """
    azure_prefix = "dbxprecheck"
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.resource import ResourceManagementClient

        credential = DefaultAzureCredential()

        # Resolve subscription if not provided (use the first enabled one).
        # SubscriptionClient isn't shipped by every SDK build, so import it
        # lazily and require --subscription-id when it's unavailable.
        sub_id = subscription_id
        if not sub_id:
            SubscriptionClient = None
            for module_path in ("azure.mgmt.resource", "azure.mgmt.subscription"):
                try:
                    mod = __import__(module_path, fromlist=["SubscriptionClient"])
                except ImportError:
                    continue
                SubscriptionClient = getattr(mod, "SubscriptionClient", None)
                if SubscriptionClient is not None:
                    break
            if SubscriptionClient is None:
                click.echo(click.style(
                    "   Pass --subscription-id to sweep Azure orphans "
                    "(could not enumerate subscriptions on this SDK build)", fg="yellow"))
                return
            sub_client = SubscriptionClient(credential)
            subs = [s for s in sub_client.subscriptions.list() if s.state == "Enabled"]
            if not subs:
                click.echo(click.style("   Could not determine an Azure subscription", fg="yellow"))
                return
            sub_id = subs[0].subscription_id
            click.echo(f"   Using Azure subscription: {subs[0].display_name} ({sub_id})")

        client = ResourceManagementClient(credential, sub_id)
        orphan_rgs = [
            rg for rg in client.resource_groups.list()
            if rg.name and rg.name.startswith(azure_prefix)
        ]

        if not orphan_rgs:
            click.echo(click.style("\n✓ No orphaned Azure test resource groups found!", fg="green"))
            return

        click.echo(click.style(
            f"\n📁 Found {len(orphan_rgs)} orphaned Azure resource group(s):", fg="yellow"
        ))
        for rg in orphan_rgs:
            click.echo(f"   - {rg.name} ({rg.location})")

        if not click.confirm("\nDelete these resource groups (and everything inside them)?"):
            click.echo("Aborted - nothing deleted.")
            return

        for rg in orphan_rgs:
            try:
                client.resource_groups.begin_delete(rg.name)
                click.echo(click.style(f"     ✓ Deleting {rg.name} (async, cascades)", fg="green"))
            except Exception as e:
                click.echo(click.style(f"     ✗ Error deleting {rg.name}: {str(e)[:60]}", fg="red"))

    except ImportError:
        click.echo(click.style(
            "\nAzure SDK not installed - cannot sweep Azure orphans "
            "(pip install azure-identity azure-mgmt-resource)", fg="yellow"
        ))
    except Exception as e:
        click.echo(click.style(f"\nCould not sweep Azure orphans: {str(e)[:80]}", fg="red"))


def show_azure_dry_run_plan():
    """Show what Azure would create/delete without doing it."""
    click.echo("""
┌─────────────────────────────────────────────────────────────────────┐
│                 DRY-RUN: AZURE TEST PLAN                              │
├─────────────────────────────────────────────────────────────────────┤
│  Azure proves permissions by creating REAL temporary resources and    │
│  then deleting them. The following WOULD be created (prefix            │
│  "dbxprecheck-*"), then removed (Resource Group delete cascades):      │
│                                                                       │
│    • Resource Group        dbxprecheck-rg-<uuid>                      │
│    • VNet + Subnet + NSG    (VNet-injection readiness)               │
│    • Storage Account (ADLS) (Unity Catalog metastore)                │
│    • Access Connector       (Unity Catalog)                          │
│    • NAT Gateway            (PrivateLink / egress)                    │
│                                                                       │
│  NOTE: NAT Gateway / Public IP incur small charges for the few        │
│  seconds they exist. Cleanup deletes the Resource Group, which        │
│  cascades to every contained resource.                                │
└─────────────────────────────────────────────────────────────────────┘

To run the actual tests: Remove the --dry-run flag
""")


def show_gcp_dry_run_plan():
    """Show what GCP would check. GCP is fully read-only."""
    click.echo("""
┌─────────────────────────────────────────────────────────────────────┐
│                 DRY-RUN: GCP TEST PLAN                                │
├─────────────────────────────────────────────────────────────────────┤
│  GCP checks are 100% READ-ONLY - NOTHING is ever created, even in a   │
│  normal (non-dry-run) run. It uses projects.testIamPermissions and    │
│  read-only describe/list calls to verify:                             │
│                                                                       │
│    • Service Account credentials & project state                      │
│    • Required APIs enabled (compute, storage, iam, kms, ...)          │
│    • IAM permissions for the deployment                               │
│    • Network / Private Google Access / Cloud NAT readiness            │
│    • Quotas (CPUs, networks, subnetworks)                             │
│                                                                       │
│  A normal GCP run is already safe to execute unattended.              │
└─────────────────────────────────────────────────────────────────────┘

To run the actual checks: Remove the --dry-run flag
""")


def show_dry_run_plan():
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


def run_aws_checks(
    region: Optional[str],
    profile: Optional[str],
    verify_only: bool = False,
    vpc_id: Optional[str] = None,
    sg_id: Optional[str] = None,
    databricks_account_id: Optional[str] = None,
) -> tuple:
    """Run AWS checks and return the report and checker instance.

    Runs all permission checks and reports which deployment types are supported.
    """
    _progress("\n▶ Running AWS checks (all deployment types)...", fg="yellow")
    if verify_only:
        _progress("   VERIFY-ONLY mode: Read-only checks (no resource creation)", fg="cyan")
    else:
        _progress("   Testing with REAL temporary resources (create → verify → delete)", fg="cyan")

    try:
        checker = AWSChecker(
            region=region,
            profile=profile,
            verify_only=verify_only,
            vpc_id=vpc_id,
            sg_id=sg_id,
            databricks_account_id=databricks_account_id,
        )
        report = checker.run_all_checks()

        if report.total_not_ok > 0:
            _progress("  ✗ AWS checks completed with errors", fg="red")
        elif report.total_warning > 0:
            _progress("  ⚠ AWS checks completed with warnings", fg="yellow")
        else:
            _progress("  ✓ AWS checks passed", fg="green")

        return report, checker
    except ImportError as e:
        _progress(f"  ✗ AWS SDK not installed: {e}", fg="red")
        _progress("    Install with: pip install boto3")
        return None, None
    except Exception as e:
        _progress(f"  ✗ AWS check failed: {e}", fg="red")
        return None, None


def run_azure_checks(
    region: Optional[str],
    subscription_id: Optional[str],
    resource_group: Optional[str],
    verify_only: bool = False,
    vnet_id: Optional[str] = None,
) -> Optional[CheckReport]:
    """Run Azure checks and return the report."""
    _progress("\n▶ Running Azure checks (all deployment types)...", fg="yellow")
    if verify_only:
        _progress("   VERIFY-ONLY mode: Read-only checks (no resource creation)", fg="cyan")
    else:
        _progress("   Testing with REAL temporary resources (create → verify → delete)", fg="cyan")

    try:
        checker = AzureChecker(
            region=region,
            subscription_id=subscription_id,
            resource_group=resource_group,
            verify_only=verify_only,
            vnet_id=vnet_id,
        )
        report = checker.run_all_checks()

        if report.total_not_ok > 0:
            _progress("  ✗ Azure checks completed with errors", fg="red")
        elif report.total_warning > 0:
            _progress("  ⚠ Azure checks completed with warnings", fg="yellow")
        else:
            _progress("  ✓ Azure checks passed", fg="green")

        return report
    except ImportError as e:
        _progress(f"  ✗ Azure SDK not installed: {e}", fg="red")
        _progress("    Install with: pip install azure-identity azure-mgmt-resource azure-mgmt-network azure-mgmt-storage")
        return None
    except Exception as e:
        _progress(f"  ✗ Azure check failed: {e}", fg="red")
        return None


def run_gcp_checks(
    region: Optional[str],
    project: Optional[str],
    credentials_file: Optional[str],
    verify_only: bool = False,
) -> Optional[CheckReport]:
    """Run GCP checks and return the report."""
    _progress("\n▶ Running GCP checks...", fg="yellow")
    if verify_only:
        _progress("   VERIFY-ONLY mode: Read-only checks (no resource creation)", fg="cyan")

    try:
        checker = GCPChecker(
            region=region,
            project_id=project,
            credentials_file=credentials_file,
            verify_only=verify_only,
        )
        report = checker.run_all_checks()

        if report.total_not_ok > 0:
            _progress("  ✗ GCP checks completed with errors", fg="red")
        elif report.total_warning > 0:
            _progress("  ⚠ GCP checks completed with warnings", fg="yellow")
        else:
            _progress("  ✓ GCP checks passed", fg="green")

        return report
    except ImportError as e:
        _progress(f"  ✗ GCP SDK not installed: {e}", fg="red")
        _progress("    Install with: pip install google-cloud-storage google-api-python-client google-auth")
        return None
    except Exception as e:
        _progress(f"  ✗ GCP check failed: {e}", fg="red")
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
@click.option(
    "--vpc-id",
    help="AWS: scope BYO-network checks to a specific VPC (subnets/AZ/size/egress)"
)
@click.option(
    "--sg-id",
    help="AWS: validate an existing security group's rules (intra-SG + control-plane egress)"
)
@click.option(
    "--databricks-account-id",
    help="Your Databricks account UUID — validates the cross-account role trust content"
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
@click.option(
    "--vnet-id",
    help="Azure: validate an existing VNet for VNet injection (delegation/NSG/size). Full resource id or '<rg>/<vnet-name>'"
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
    "--verify-only",
    is_flag=True,
    help="Run read-only checks without creating temporary resources (useful when resource creation requires approval)"
)
@click.option(
    "--cleanup-orphans",
    is_flag=True,
    help="Find and delete any leftover test resources (dbx-precheck-temp-*)"
)
# New options for production use
@click.option(
    "--format", "output_format",
    type=click.Choice(["text", "markdown", "md", "json"], case_sensitive=False),
    default="text",
    help="Report format: text (default), markdown (customer-friendly), json (CI/CD)"
)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="Shortcut for --format json (machine-readable, for CI/CD pipelines)"
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
@click.option(
    "--strict",
    is_flag=True,
    help="Exit non-zero on warnings / NOT-VERIFIED items too (for strict CI gating)"
)
@click.version_option(
    version="1.2.0",
    prog_name="Databricks Terraform Pre-Check"
)
def main(
    cloud: Optional[str],
    check_all: bool,
    region: Optional[str],
    output: Optional[str],
    profile: Optional[str],
    vpc_id: Optional[str],
    sg_id: Optional[str],
    databricks_account_id: Optional[str],
    subscription_id: Optional[str],
    resource_group: Optional[str],
    vnet_id: Optional[str],
    project: Optional[str],
    credentials_file: Optional[str],
    verbose: bool,
    dry_run: bool,
    verify_only: bool,
    cleanup_orphans: bool,
    output_format: str,
    json_output: bool,
    log_level: str,
    log_file: Optional[str],
    config: Optional[str],
    quiet: bool,
    strict: bool,
):
    """
    Databricks Terraform Pre-Check Tool
    
    Validates credentials, permissions, and resources BEFORE running Terraform.
    Checks ALL permissions and reports which deployment types are supported.
    
    \b
    The tool automatically checks permissions for all deployment types:
      Standard    - Basic workspace (VPC, S3/Storage, IAM)
      PrivateLink - With VPC Endpoints for private connectivity
      Unity       - With Unity Catalog storage credentials
      Full        - All features (PrivateLink + Unity Catalog + CMK)
    
    \b
    EXAMPLES:
      # Check AWS permissions (all deployment types)
      python main.py --cloud aws --region us-east-1
    
      # Check Azure permissions
      python main.py --cloud azure --subscription-id xxx
    
      # Save report to file
      python main.py --cloud aws --output pre-check-report.txt
    
      # JSON output for CI/CD
      python main.py --cloud aws --json --quiet
    
      # Read-only checks (no resource creation)
      python main.py --cloud aws --verify-only
    
      # Debug mode with log file
      python main.py --cloud aws --log-level debug --log-file debug.log
    """
    # Setup logging
    log_config = setup_logging(level=log_level, log_file=log_file)
    logger.debug("Starting Databricks Terraform Pre-Check v1.2.0")
    
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
        cleanup_orphaned_resources(cloud, region, profile, subscription_id)
        sys.exit(0)

    # Handle dry-run mode (cloud-aware: each cloud has a different test surface)
    if dry_run:
        click.echo(click.style("\n🔍 DRY-RUN MODE - No resources will be created", fg="cyan", bold=True))
        dry_run_cloud = cloud or "aws"
        if dry_run_cloud == "azure":
            show_azure_dry_run_plan()
        elif dry_run_cloud == "gcp":
            show_gcp_dry_run_plan()
        else:
            show_dry_run_plan()
        sys.exit(0)
    
    # Handle verify-only mode
    if verify_only:
        _progress("\n🔒 VERIFY-ONLY MODE - Read-only checks (no resource creation)", fg="cyan", bold=True)
        _progress("   This mode checks credentials, quotas, and existing resources without creating anything.")
        _progress("   Some permission checks may be limited. Use full mode for comprehensive validation.")
        _progress("")

    _progress("Checking all deployment types (Standard, PrivateLink, Unity Catalog, Full)", fg="cyan")
    
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
        
        _progress(f"\nDetected credentials for: {', '.join(c.upper() for c in available_clouds)}")

        if len(available_clouds) == 1:
            cloud = available_clouds[0]
            _progress(f"Automatically selecting {cloud.upper()}")
        else:
            check_all = True
            _progress("Running checks for all detected clouds...")
    
    reports: List[CheckReport] = []
    aws_checker = None
    
    if check_all:
        available = CredentialLoader.detect_available_clouds()
        
        if available.get("aws"):
            report, checker = run_aws_checks(region, profile, verify_only, vpc_id, sg_id, databricks_account_id)
            if report:
                reports.append(report)
                aws_checker = checker
        
        if available.get("azure"):
            report = run_azure_checks(region, subscription_id, resource_group, verify_only, vnet_id)
            if report:
                reports.append(report)
        
        if available.get("gcp"):
            report = run_gcp_checks(region, project, credentials_file, verify_only)
            if report:
                reports.append(report)
    else:
        if cloud == "aws":
            report, checker = run_aws_checks(region, profile, verify_only, vpc_id, sg_id, databricks_account_id)
            if report:
                reports.append(report)
                aws_checker = checker
        elif cloud == "azure":
            report = run_azure_checks(region, subscription_id, resource_group, verify_only, vnet_id)
            if report:
                reports.append(report)
        elif cloud == "gcp":
            report = run_gcp_checks(region, project, credentials_file, verify_only)
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
    
    # Determine exit code. Blockers always fail (2). In --strict, unresolved
    # warnings / NOT-VERIFIED items also fail (distinct code) so CI can gate on an
    # incomplete run; default keeps warnings = 0.
    if total_not_ok > 0:
        exit_code = ExitCode.PERMISSION_DENIED
    elif strict and total_warning > 0:
        exit_code = ExitCode.GENERAL_ERROR
    else:
        exit_code = ExitCode.SUCCESS
    
    # Normalize the requested output format (--json is a shortcut for --format json).
    fmt = output_format.lower()
    if json_output:
        fmt = "json"
    elif fmt == "md":
        fmt = "markdown"

    # Markdown output mode (customer-friendly report)
    if fmt == "markdown":
        md_reporter = MarkdownReporter()
        if len(reports) == 1:
            md_content = md_reporter.generate(reports[0])
        else:
            md_content = md_reporter.generate_all_clouds(reports)
        click.echo(md_content)
        if output:
            with open(output, 'w') as f:
                f.write(md_content)
            logger.info("Markdown report saved to %s", output)
        sys.exit(exit_code)

    # JSON output mode
    if fmt == "json":
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
