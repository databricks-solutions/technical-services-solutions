"""AWS checker for Databricks Terraform Pre-Check.

Runs all permission checks and reports which deployment types are supported
based on the detected permissions. No deployment mode selection required.
"""

import uuid
import time
import json
import logging
import re
from typing import Optional, List, Dict, Any, Callable, Tuple

from utils.denial import is_access_denied, is_throttling, is_deploy_blocking
from .base import (
    BaseChecker,
    CheckCategory,
    CheckResult,
    CheckStatus,
    CheckReport,
)
from .databricks_actions import DeploymentMode, VPCType, TerraformResource

from .permissions import (
    get_registry,
    get_cross_account_actions,
    get_aws_deployment_profile_actions,
)

from .databricks_actions import (
    get_aws_deployment_profile,
    AWS_FULL_DEPLOYMENT,
    get_all_actions_for_profile,
    CUSTOMER_MANAGED_VPC_DEFAULT_ACTIONS,
    UNITY_CATALOG_STORAGE_ACTIONS,
    UNITY_CATALOG_FILE_EVENTS_ACTIONS,
    SPOT_SERVICE_LINKED_ROLE_ACTIONS,
)


logger = logging.getLogger(__name__)


# Prefix for temporary test resources
TEST_RESOURCE_PREFIX = "dbx-precheck-temp"


class AWSChecker(BaseChecker):
    """Checker for AWS resources and permissions for Databricks deployment.
    
    Runs all permission checks unconditionally and produces a deployment
    compatibility matrix showing which deployment types are supported.
    """
    
    def __init__(
        self,
        region: str = None,
        profile: str = None,
        verify_only: bool = False,
        vpc_id: str = None,
        sg_id: str = None,
        databricks_account_id: str = None,
        skip_cleanup: bool = False,
    ):
        super().__init__(region)
        self.profile = profile
        self.verify_only = verify_only
        self.skip_cleanup = skip_cleanup
        # Optional BYO-network scoping / validation targets.
        self.vpc_id = vpc_id
        self.sg_id = sg_id
        self.databricks_account_id = databricks_account_id
        self._session = None
        self._account_id = None
        self._arn = None
        self._user_arn = None
        self._can_simulate = False
        self._verbose = True
        self._test_id = str(uuid.uuid4())[:8]
        self._cleanup_tasks = []
        self._check_results_by_area: Dict[str, bool] = {}
        self._temp_bucket_name: Optional[str] = None
    
    @property
    def cloud_name(self) -> str:
        return "AWS"
    
    def _get_session(self):
        """Get or create boto3 session."""
        if self._session is None:
            try:
                import boto3
                if self.profile:
                    self._session = boto3.Session(
                        profile_name=self.profile,
                        region_name=self.region
                    )
                else:
                    self._session = boto3.Session(region_name=self.region)
            except ImportError:
                raise ImportError("boto3 is required for AWS checks. Install with: pip install boto3")
        return self._session
    
    def _get_client(self, service: str):
        """Get a boto3 client for the specified service."""
        return self._get_session().client(service)
    
    def _get_test_resource_name(self, resource_type: str) -> str:
        """Generate a unique name for a temporary test resource."""
        return f"{TEST_RESOURCE_PREFIX}-{resource_type}-{self._test_id}"
    
    def _cleanup_test_resources(self):
        """Delete every registered temp resource, most-recent first.

        Returns a list of ``(resource_name, error)`` for deletions that FAILED,
        so a leaked resource can be surfaced as NOT_OK in the report. A silent
        best-effort ``pass`` here made a leaked resource and a clean run look
        identical (review H1).
        """
        # --skip-cleanup: leave temp resources in place for inspection (review H10).
        if self.skip_cleanup:
            return []
        failures = []
        for cleanup_func, resource_name in reversed(self._cleanup_tasks):
            try:
                cleanup_func()
            except Exception as e:
                failures.append((resource_name, str(e)))
        self._cleanup_tasks = []
        return failures

    def _unregister_cleanup(self, resource_name):
        """Drop a resource from the cleanup queue once an inline delete has
        already removed it, so the final sweep doesn't re-issue the delete (which
        would always raise NoSuchEntity and be swallowed — review H1)."""
        self._cleanup_tasks = [t for t in self._cleanup_tasks if t[1] != resource_name]

    @staticmethod
    def _describe_all(client, method_name, result_key, **kwargs):
        """Collect ALL items from a paginated EC2 describe_* call.

        Unpaginated describe_subnets / describe_vpcs / describe_vpc_endpoints /
        describe_nat_gateways return only the first page, which silently skews
        subnet counts, endpoint-presence checks and quota verdicts on larger
        accounts (review M6). Falls back to a single call if no paginator exists.
        """
        try:
            paginator = client.get_paginator(method_name)
        except Exception:
            return getattr(client, method_name)(**kwargs).get(result_key, [])
        items = []
        for page in paginator.paginate(**kwargs):
            items.extend(page.get(result_key, []))
        return items

    @staticmethod
    def _safe_delete(fn, not_found_markers):
        """Run a delete, treating 'resource not found' as success (nothing was
        leaked) and re-raising anything else so a genuine leak still surfaces.

        Used for the defensive cleanup registered when a create call raises an
        *ambiguous* error — the resource may have been created server-side before
        the client-side exception (review M2)."""
        try:
            fn()
        except Exception as e:
            if any(marker in str(e) for marker in not_found_markers):
                return  # already gone — not a leak
            raise
    
    # =========================================================================
    # REAL RESOURCE TESTING (Create & Delete)
    # This is how we verify permissions without iam:SimulatePrincipalPolicy
    # =========================================================================

    def _verify_only_probe(self, label: str, actions: List[str]) -> List[CheckResult]:
        """Read-only permission probe used in --verify-only mode (creates nothing).

        Uses IAM policy simulation when available; otherwise reports honestly that
        full verification needs a create-test (run without --verify-only).
        """
        results = [CheckResult(
            name=f"── {label} (verify-only, read-only) ──",
            status=CheckStatus.OK,
            message="No resources created",
        )]
        if self._can_simulate:
            sim = self._simulate_actions(actions)
            for a in actions:
                s, m = sim.get(a, ("error", "not evaluated"))
                st = CheckStatus.OK if s == "allowed" else (
                    CheckStatus.NOT_OK if s == "denied" else CheckStatus.WARNING)
                results.append(CheckResult(name=f"  {a}", status=st, message=m))
        else:
            results.append(CheckResult(
                name=f"  {label} permissions",
                status=CheckStatus.WARNING,
                message=(
                    "Cannot fully verify in --verify-only without IAM simulation. "
                    "Re-run without --verify-only for a create-test, or ensure: "
                    + ", ".join(actions)
                ),
            ))
        return results

    def _test_s3_bucket_permissions(self) -> List[CheckResult]:
        """
        Test S3 permissions by creating a real bucket and testing operations.
        Returns list of CheckResults for each operation tested.
        """
        if self.verify_only:
            return self._verify_only_probe("S3 Root Bucket", [
                "s3:ListAllMyBuckets", "s3:CreateBucket", "s3:PutBucketPolicy",
                "s3:PutBucketVersioning", "s3:PutEncryptionConfiguration", "s3:DeleteBucket",
            ])
        results = []
        s3 = self._get_client("s3")
        bucket_name = f"{TEST_RESOURCE_PREFIX}-{self._account_id}-{self._test_id}"
        bucket_created = False
        
        # Show what we're creating
        results.append(CheckResult(
            name="  📦 Creating test bucket",
            status=CheckStatus.OK,
            message=bucket_name
        ))
        
        # Test CreateBucket
        try:
            if self.region == "us-east-1":
                s3.create_bucket(Bucket=bucket_name)
            else:
                s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': self.region}
                )
            bucket_created = True
            self._temp_bucket_name = bucket_name
            results.append(CheckResult(
                name="  s3:CreateBucket",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {bucket_name}"
            ))

            # Register cleanup at creation time so a mid-run exception can't leak
            # the bucket. The bucket is kept alive for the Unity Catalog object
            # test and torn down by _delete_temp_bucket() in run_all_checks; that
            # versioned-bucket teardown is also the right fallback for the
            # finally-block cleanup (a plain delete_bucket would fail on the
            # versioned + deny-policy test bucket). _delete_temp_bucket() no-ops
            # once the bucket has already been deleted.
            self._cleanup_tasks.append((
                self._delete_temp_bucket,
                bucket_name
            ))

        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:CreateBucket",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            elif "BucketAlreadyOwnedByYou" in error:
                bucket_created = True
                results.append(CheckResult(
                    name="  s3:CreateBucket",
                    status=CheckStatus.OK,
                    message="VERIFIED - Bucket exists (permission OK)"
                ))
            else:
                # Ambiguous error — the bucket may have been created server-side
                # before this raised. Register a not-found-tolerant delete so it
                # can't orphan; a genuine delete failure then surfaces via H1
                # instead of being silently dropped (review M2).
                self._temp_bucket_name = bucket_name
                self._cleanup_tasks.append((
                    lambda: self._safe_delete(
                        lambda: self._get_client("s3").delete_bucket(Bucket=bucket_name),
                        ["NoSuchBucket", "NotFound", "404"],
                    ),
                    bucket_name,
                ))
                results.append(CheckResult(
                    name="  s3:CreateBucket",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
            return results  # Can't test other operations without bucket
        
        if not bucket_created:
            return results
        
        # Test PutBucketVersioning
        try:
            s3.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={'Status': 'Enabled'}
            )
            results.append(CheckResult(
                name="  s3:PutBucketVersioning",
                status=CheckStatus.OK,
                message="VERIFIED - Enabled versioning"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:PutBucketVersioning",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  s3:PutBucketVersioning",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        # Test PutBucketPublicAccessBlock
        try:
            s3.put_public_access_block(
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    'BlockPublicAcls': True,
                    'IgnorePublicAcls': True,
                    'BlockPublicPolicy': True,
                    'RestrictPublicBuckets': True
                }
            )
            results.append(CheckResult(
                name="  s3:PutBucketPublicAccessBlock",
                status=CheckStatus.OK,
                message="VERIFIED - Blocked public access"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:PutBucketPublicAccessBlock",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  s3:PutBucketPublicAccessBlock",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        # Test PutBucketEncryption
        try:
            s3.put_bucket_encryption(
                Bucket=bucket_name,
                ServerSideEncryptionConfiguration={
                    'Rules': [{
                        'ApplyServerSideEncryptionByDefault': {
                            'SSEAlgorithm': 'AES256'
                        }
                    }]
                }
            )
            results.append(CheckResult(
                name="  s3:PutEncryptionConfiguration",
                status=CheckStatus.OK,
                message="VERIFIED - Configured encryption"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:PutEncryptionConfiguration",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  s3:PutEncryptionConfiguration",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        # Test PutBucketPolicy
        test_policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "PreCheckTest",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": f"arn:aws:s3:::{bucket_name}/*",
                "Condition": {"StringEquals": {"aws:PrincipalAccount": "000000000000"}}
            }]
        })
        
        try:
            s3.put_bucket_policy(Bucket=bucket_name, Policy=test_policy)
            results.append(CheckResult(
                name="  s3:PutBucketPolicy",
                status=CheckStatus.OK,
                message="VERIFIED - Applied bucket policy"
            ))

            # Delete the policy
            try:
                s3.delete_bucket_policy(Bucket=bucket_name)
                results.append(CheckResult(
                    name="  s3:DeleteBucketPolicy",
                    status=CheckStatus.OK,
                    message="VERIFIED"
                ))
            except Exception as e:
                # Surface the outcome instead of a bare except: pass, which hid a
                # denial of this permission entirely (review M10).
                results.append(CheckResult(
                    name="  s3:DeleteBucketPolicy",
                    status=CheckStatus.NOT_OK if is_access_denied(str(e)) else CheckStatus.WARNING,
                    message=(f"DENIED: {str(e)[:80]}" if is_access_denied(str(e))
                             else f"Could not verify: {str(e)[:80]}"),
                ))
                
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:PutBucketPolicy",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  s3:PutBucketPolicy",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        # Test PutBucketTagging
        try:
            s3.put_bucket_tagging(
                Bucket=bucket_name,
                Tagging={'TagSet': [{'Key': 'PreCheck', 'Value': 'Test'}]}
            )
            results.append(CheckResult(
                name="  s3:PutBucketTagging",
                status=CheckStatus.OK,
                message="VERIFIED - Added tags"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:PutBucketTagging",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
        
        self._temp_bucket_name = bucket_name
        results.append(CheckResult(
            name="  📦 Bucket kept for Unity Catalog tests",
            status=CheckStatus.OK,
            message=bucket_name
        ))
        
        return results
    
    def _test_unity_catalog_s3_permissions(self) -> List[CheckResult]:
        """Test Unity Catalog S3 object-level permissions using the temp bucket."""
        results = []
        if not self._temp_bucket_name:
            return results
        
        s3 = self._get_client("s3")
        bucket = self._temp_bucket_name
        test_key = "dbx-precheck-uc-test/test-object.txt"
        
        # s3:PutObject
        try:
            s3.put_object(Bucket=bucket, Key=test_key, Body=b"precheck-test")
            results.append(CheckResult(
                name="  s3:PutObject",
                status=CheckStatus.OK,
                message="VERIFIED - Wrote test object"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:PutObject",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  s3:PutObject",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        # s3:GetObject
        try:
            s3.get_object(Bucket=bucket, Key=test_key)
            results.append(CheckResult(
                name="  s3:GetObject",
                status=CheckStatus.OK,
                message="VERIFIED - Read test object"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:GetObject",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  s3:GetObject",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        # s3:DeleteObject
        try:
            s3.delete_object(Bucket=bucket, Key=test_key)
            results.append(CheckResult(
                name="  s3:DeleteObject",
                status=CheckStatus.OK,
                message="VERIFIED - Deleted test object"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:DeleteObject",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  s3:DeleteObject",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        # s3:ListBucket
        try:
            s3.list_objects_v2(Bucket=bucket, MaxKeys=1)
            results.append(CheckResult(
                name="  s3:ListBucket",
                status=CheckStatus.OK,
                message="VERIFIED - Listed bucket contents"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:ListBucket",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  s3:ListBucket",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        # s3:GetBucketLocation
        try:
            s3.get_bucket_location(Bucket=bucket)
            results.append(CheckResult(
                name="  s3:GetBucketLocation",
                status=CheckStatus.OK,
                message="VERIFIED - Got bucket region"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:GetBucketLocation",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  s3:GetBucketLocation",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        return results
    
    def _delete_temp_bucket(self) -> List[CheckResult]:
        """Delete the temp bucket and return results for DeleteBucket permission."""
        results = []
        if not self._temp_bucket_name:
            return results
        
        s3 = self._get_client("s3")
        bucket = self._temp_bucket_name
        
        # The bucket has versioning enabled + a (deny) bucket policy from the
        # permission test, so a plain delete fails. Remove the policy, then ALL
        # object versions + delete markers (not just current objects), then delete.
        try:
            s3.delete_bucket_policy(Bucket=bucket)
        except Exception:
            pass
        try:
            paginator = s3.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=bucket):
                to_delete = [
                    {"Key": o["Key"], "VersionId": o["VersionId"]}
                    for o in (page.get("Versions", []) + page.get("DeleteMarkers", []))
                ]
                for i in range(0, len(to_delete), 1000):
                    s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete[i:i + 1000]})
        except Exception:
            # Fall back to non-versioned listing if version listing isn't available.
            try:
                resp = s3.list_objects_v2(Bucket=bucket)
                for obj in resp.get("Contents", []):
                    s3.delete_object(Bucket=bucket, Key=obj["Key"])
            except Exception:
                pass

        try:
            s3.delete_bucket(Bucket=bucket)
            results.append(CheckResult(
                name="  🗑️  s3:DeleteBucket",
                status=CheckStatus.OK,
                message=f"✓ DELETED: {bucket}"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  s3:DeleteBucket",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  s3:DeleteBucket",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {bucket}"
                ))
        
        self._temp_bucket_name = None
        return results
    
    def _test_iam_role_permissions(self) -> List[CheckResult]:
        """
        Test IAM role permissions by creating a real role and testing operations.
        Returns list of CheckResults for each operation tested.
        """
        if self.verify_only:
            return self._verify_only_probe("Cross-account IAM Role", [
                "iam:ListRoles", "iam:CreateRole", "iam:GetRole",
                "iam:TagRole", "iam:PutRolePolicy", "iam:DeleteRole",
            ])
        results = []
        iam = self._get_client("iam")
        role_name = self._get_test_resource_name("role")
        role_created = False
        
        # Show what we're creating
        results.append(CheckResult(
            name="  👤 Creating test IAM role",
            status=CheckStatus.OK,
            message=role_name
        ))
        
        # Trust policy. With --databricks-account-id we build the representative
        # trust (real Databricks signing principal + ExternalId = your account id)
        # and validate the id; otherwise a self-trust placeholder + a note that the
        # trust CONTENT was not validated.
        DATABRICKS_SIGNING_ACCOUNT = "414351767826"
        import re as _re
        acct = self.databricks_account_id
        if acct and _re.fullmatch(r"[0-9a-fA-F-]{36}", acct):
            principal_arn = f"arn:aws:iam::{DATABRICKS_SIGNING_ACCOUNT}:root"
            external_id = acct
            results.append(CheckResult(
                name="  Cross-account trust content", status=CheckStatus.OK,
                message=f"Building trust for Databricks principal {DATABRICKS_SIGNING_ACCOUNT} + ExternalId {acct}",
            ))
        elif acct:
            principal_arn = f"arn:aws:iam::{self._account_id}:root"
            external_id = "precheck-test"
            results.append(CheckResult(
                name="  Cross-account trust content", status=CheckStatus.NOT_OK,
                message=f"--databricks-account-id '{acct}' is not a valid Databricks account UUID",
                remediation="Pass your Databricks account id (a UUID from the account console).",
            ))
        else:
            principal_arn = f"arn:aws:iam::{self._account_id}:root"
            external_id = "precheck-test"
            results.append(CheckResult(
                name="  Cross-account trust content", status=CheckStatus.WARNING,
                message="Trust CONTENT not validated - pass --databricks-account-id to verify the role trusts Databricks (414351767826) + your account ExternalId",
            ))
        trust_policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"AWS": principal_arn},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"sts:ExternalId": external_id}}
            }]
        })
        
        # Test CreateRole
        try:
            iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=trust_policy,
                Description="Databricks Pre-Check temporary test role",
                Tags=[{'Key': 'PreCheck', 'Value': 'Temporary'}]
            )
            role_created = True
            # Register for cleanup so a mid-run exception can't leak the role.
            self._cleanup_tasks.append((
                lambda: iam.delete_role(RoleName=role_name), role_name,
            ))
            results.append(CheckResult(
                name="  iam:CreateRole",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {role_name}"
            ))
            
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  iam:CreateRole",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            elif "EntityAlreadyExists" in error:
                # CreateRole reached the "already exists" check, so the permission
                # is proven. But a role with the test name pre-exists and we did
                # NOT create it — leaving role_created False makes the early-return
                # below skip the mutation/cleanup path, so we never modify or
                # delete a role we didn't create (review M3).
                results.append(CheckResult(
                    name="  iam:CreateRole",
                    status=CheckStatus.OK,
                    message="VERIFIED - permission OK (a role with the test name already exists; not modifying it)"
                ))
            else:
                # Ambiguous error — the role may have been created server-side
                # before this raised. Register a not-found-tolerant delete so it
                # can't orphan (review M2).
                self._cleanup_tasks.append((
                    lambda: self._safe_delete(
                        lambda: iam.delete_role(RoleName=role_name),
                        ["NoSuchEntity"],
                    ),
                    role_name,
                ))
                results.append(CheckResult(
                    name="  iam:CreateRole",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))

            if not role_created:
                return results
        
        # Test GetRole
        try:
            iam.get_role(RoleName=role_name)
            results.append(CheckResult(
                name="  iam:GetRole",
                status=CheckStatus.OK,
                message="VERIFIED"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  iam:GetRole",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
        
        # Test TagRole
        try:
            iam.tag_role(
                RoleName=role_name,
                Tags=[{'Key': 'Test', 'Value': 'Value'}]
            )
            results.append(CheckResult(
                name="  iam:TagRole",
                status=CheckStatus.OK,
                message="VERIFIED"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  iam:TagRole",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
        
        # Test UpdateAssumeRolePolicy
        try:
            iam.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=trust_policy
            )
            results.append(CheckResult(
                name="  iam:UpdateAssumeRolePolicy",
                status=CheckStatus.OK,
                message="VERIFIED"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  iam:UpdateAssumeRolePolicy",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
        
        # Test PutRolePolicy (inline policy)
        inline_policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Deny",
                "Action": "s3:*",
                "Resource": "*",
                "Condition": {"StringEquals": {"aws:PrincipalAccount": "000000000000"}}
            }]
        })
        
        try:
            iam.put_role_policy(
                RoleName=role_name,
                PolicyName="PreCheckTestPolicy",
                PolicyDocument=inline_policy
            )
            results.append(CheckResult(
                name="  iam:PutRolePolicy",
                status=CheckStatus.OK,
                message="VERIFIED - Added inline policy"
            ))
            
            # Delete the inline policy
            try:
                iam.delete_role_policy(RoleName=role_name, PolicyName="PreCheckTestPolicy")
                results.append(CheckResult(
                    name="  iam:DeleteRolePolicy",
                    status=CheckStatus.OK,
                    message="VERIFIED"
                ))
            except Exception as e:
                # Surface the outcome instead of a bare except: pass, which hid a
                # denial of this permission entirely (review M10).
                results.append(CheckResult(
                    name="  iam:DeleteRolePolicy",
                    status=CheckStatus.NOT_OK if is_access_denied(str(e)) else CheckStatus.WARNING,
                    message=(f"DENIED: {str(e)[:80]}" if is_access_denied(str(e))
                             else f"Could not verify: {str(e)[:80]}"),
                ))
                
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  iam:PutRolePolicy",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
        
        # CLEANUP: Delete the test role
        try:
            # First delete any attached policies
            try:
                attached = iam.list_attached_role_policies(RoleName=role_name)
                for policy in attached.get('AttachedPolicies', []):
                    iam.detach_role_policy(RoleName=role_name, PolicyArn=policy['PolicyArn'])
            except Exception:
                pass  # best-effort cleanup of a test artifact
            
            # Delete inline policies
            try:
                inline = iam.list_role_policies(RoleName=role_name)
                for policy_name in inline.get('PolicyNames', []):
                    iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
            except Exception:
                pass  # best-effort cleanup of a test artifact
            
            iam.delete_role(RoleName=role_name)
            self._unregister_cleanup(role_name)  # inline delete done; don't re-sweep
            results.append(CheckResult(
                name="  🗑️  iam:DeleteRole",
                status=CheckStatus.OK,
                message=f"✓ DELETED: {role_name}"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  iam:DeleteRole",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  iam:DeleteRole",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {role_name}"
                ))
        
        return results
    
    def _test_iam_policy_permissions(self) -> List[CheckResult]:
        """
        Test IAM policy permissions by creating a real policy and testing operations.
        Returns list of CheckResults for each operation tested.
        """
        if self.verify_only:
            return self._verify_only_probe("Cross-account IAM Policy", [
                "iam:CreatePolicy", "iam:GetPolicy",
                "iam:CreatePolicyVersion", "iam:DeletePolicy",
            ])
        results = []
        iam = self._get_client("iam")
        policy_name = self._get_test_resource_name("policy")
        policy_arn = None
        
        # Show what we're creating
        results.append(CheckResult(
            name="  📜 Creating test IAM policy",
            status=CheckStatus.OK,
            message=policy_name
        ))
        
        # Test policy document
        policy_doc = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Deny",
                "Action": "s3:*",
                "Resource": "*",
                "Condition": {"StringEquals": {"aws:PrincipalAccount": "000000000000"}}
            }]
        })
        
        # Test CreatePolicy
        try:
            response = iam.create_policy(
                PolicyName=policy_name,
                PolicyDocument=policy_doc,
                Description="Databricks Pre-Check temporary test policy",
                Tags=[{'Key': 'PreCheck', 'Value': 'Temporary'}]
            )
            policy_arn = response['Policy']['Arn']
            self._cleanup_tasks.append((
                lambda: iam.delete_policy(PolicyArn=policy_arn), policy_name,
            ))
            results.append(CheckResult(
                name="  iam:CreatePolicy",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {policy_arn}"
            ))
            
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  iam:CreatePolicy",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            elif "EntityAlreadyExists" in error:
                # Permission proven (create reached the "already exists" check).
                # Do NOT adopt the pre-existing policy ARN — leaving policy_arn
                # None makes the early-return below skip mutating/deleting a policy
                # we did not create (review M3).
                results.append(CheckResult(
                    name="  iam:CreatePolicy",
                    status=CheckStatus.OK,
                    message="VERIFIED - permission OK (a policy with the test name already exists; not modifying it)"
                ))
            else:
                # Ambiguous error — the policy may have been created server-side
                # before this raised. Register a not-found-tolerant delete so it
                # can't orphan (review M2).
                _maybe_arn = f"arn:aws:iam::{self._account_id}:policy/{policy_name}"
                self._cleanup_tasks.append((
                    lambda: self._safe_delete(
                        lambda: iam.delete_policy(PolicyArn=_maybe_arn),
                        ["NoSuchEntity"],
                    ),
                    policy_name,
                ))
                results.append(CheckResult(
                    name="  iam:CreatePolicy",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))

            if not policy_arn:
                return results
        
        # Test GetPolicy
        try:
            iam.get_policy(PolicyArn=policy_arn)
            results.append(CheckResult(
                name="  iam:GetPolicy",
                status=CheckStatus.OK,
                message="VERIFIED"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  iam:GetPolicy",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
        
        # Test CreatePolicyVersion
        try:
            iam.create_policy_version(
                PolicyArn=policy_arn,
                PolicyDocument=policy_doc,
                SetAsDefault=True
            )
            results.append(CheckResult(
                name="  iam:CreatePolicyVersion",
                status=CheckStatus.OK,
                message="VERIFIED"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  iam:CreatePolicyVersion",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            elif "LimitExceeded" in error:
                results.append(CheckResult(
                    name="  iam:CreatePolicyVersion",
                    status=CheckStatus.OK,
                    message="VERIFIED (version limit reached)"
                ))
        
        # CLEANUP: Delete the test policy
        try:
            # Delete non-default versions first
            try:
                versions = iam.list_policy_versions(PolicyArn=policy_arn)
                for version in versions.get('Versions', []):
                    if not version['IsDefaultVersion']:
                        iam.delete_policy_version(PolicyArn=policy_arn, VersionId=version['VersionId'])
            except Exception:
                pass  # best-effort cleanup of a test artifact
            
            iam.delete_policy(PolicyArn=policy_arn)
            self._unregister_cleanup(policy_name)  # inline delete done; don't re-sweep
            results.append(CheckResult(
                name="  🗑️  iam:DeletePolicy",
                status=CheckStatus.OK,
                message=f"✓ DELETED: {policy_arn}"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  iam:DeletePolicy",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  iam:DeletePolicy",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {policy_arn}"
                ))
        
        return results
    
    def _test_security_group_permissions(self, vpc_id: str = None) -> List[CheckResult]:
        """
        Test Security Group permissions by creating a real SG and testing operations.
        Returns list of CheckResults for each operation tested.
        """
        if self.verify_only:
            return self._verify_only_probe("Security Group", [
                "ec2:DescribeSecurityGroups", "ec2:CreateSecurityGroup",
                "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
                "ec2:DeleteSecurityGroup",
            ])
        results = []
        ec2 = self._get_client("ec2")
        sg_name = self._get_test_resource_name("sg")
        sg_id = None
        
        # Get a VPC to use for testing
        if not vpc_id:
            try:
                vpcs = ec2.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
                if vpcs.get('Vpcs'):
                    vpc_id = vpcs['Vpcs'][0]['VpcId']
                else:
                    # Get any VPC
                    vpcs = ec2.describe_vpcs(MaxResults=5)
                    if vpcs.get('Vpcs'):
                        vpc_id = vpcs['Vpcs'][0]['VpcId']
            except Exception as e:
                results.append(CheckResult(
                    name="  ec2:DescribeVpcs",
                    status=CheckStatus.WARNING,
                    message=f"Cannot get VPC for testing: {str(e)}"
                ))
                return results
        
        if not vpc_id:
            results.append(CheckResult(
                name="  Security Group Tests",
                status=CheckStatus.WARNING,
                message="No VPC available for testing"
            ))
            return results
        
        # Show what we're creating
        results.append(CheckResult(
            name="  🔒 Creating test Security Group",
            status=CheckStatus.OK,
            message=f"{sg_name} in {vpc_id}"
        ))
        
        # Test CreateSecurityGroup
        try:
            response = ec2.create_security_group(
                GroupName=sg_name,
                Description="Databricks Pre-Check temporary test SG",
                VpcId=vpc_id,
                TagSpecifications=[{
                    'ResourceType': 'security-group',
                    'Tags': [{'Key': 'PreCheck', 'Value': 'Temporary'}]
                }]
            )
            sg_id = response['GroupId']
            self._cleanup_tasks.append((
                lambda: ec2.delete_security_group(GroupId=sg_id), sg_id,
            ))
            results.append(CheckResult(
                name="  ec2:CreateSecurityGroup",
                status=CheckStatus.OK,
                message=f"VERIFIED - Created test SG: {sg_id}"
            ))
            
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  ec2:CreateSecurityGroup",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            elif "InvalidGroup.Duplicate" in error:
                # Permission proven (create reached the duplicate-name check). Do
                # NOT adopt the pre-existing SG — leaving sg_id None makes the
                # early-return below skip mutating/deleting an SG we did not
                # create (review M3).
                results.append(CheckResult(
                    name="  ec2:CreateSecurityGroup",
                    status=CheckStatus.OK,
                    message="VERIFIED - permission OK (an SG with the test name already exists; not modifying it)"
                ))
            else:
                # Ambiguous error — the SG may have been created server-side
                # before this raised. Look it up by name and register a
                # not-found-tolerant delete so it can't orphan (review M2).
                try:
                    _sgs = ec2.describe_security_groups(
                        Filters=[{'Name': 'group-name', 'Values': [sg_name]}]
                    )
                    _found = _sgs.get('SecurityGroups', [])
                    if _found:
                        _orphan_id = _found[0]['GroupId']
                        self._cleanup_tasks.append((
                            lambda: self._safe_delete(
                                lambda: ec2.delete_security_group(GroupId=_orphan_id),
                                ["InvalidGroup.NotFound"],
                            ),
                            _orphan_id,
                        ))
                except Exception:
                    pass
                results.append(CheckResult(
                    name="  ec2:CreateSecurityGroup",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))

            if not sg_id:
                return results
        
        # Test AuthorizeSecurityGroupIngress
        try:
            ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[{
                    'IpProtocol': 'tcp',
                    'FromPort': 8443,
                    'ToPort': 8443,
                    'IpRanges': [{'CidrIp': '192.0.2.0/24', 'Description': 'PreCheck test'}]
                }]
            )
            results.append(CheckResult(
                name="  ec2:AuthorizeSecurityGroupIngress",
                status=CheckStatus.OK,
                message="VERIFIED - Added ingress rule"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  ec2:AuthorizeSecurityGroupIngress",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            elif "InvalidPermission.Duplicate" in error:
                results.append(CheckResult(
                    name="  ec2:AuthorizeSecurityGroupIngress",
                    status=CheckStatus.OK,
                    message="VERIFIED - Rule exists (permission OK)"
                ))
            else:
                results.append(CheckResult(
                    name="  ec2:AuthorizeSecurityGroupIngress",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        # Test AuthorizeSecurityGroupEgress
        try:
            ec2.authorize_security_group_egress(
                GroupId=sg_id,
                IpPermissions=[{
                    'IpProtocol': 'tcp',
                    'FromPort': 8443,
                    'ToPort': 8443,
                    'IpRanges': [{'CidrIp': '192.0.2.0/24', 'Description': 'PreCheck test'}]
                }]
            )
            results.append(CheckResult(
                name="  ec2:AuthorizeSecurityGroupEgress",
                status=CheckStatus.OK,
                message="VERIFIED - Added egress rule"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  ec2:AuthorizeSecurityGroupEgress",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            elif "InvalidPermission.Duplicate" in error:
                results.append(CheckResult(
                    name="  ec2:AuthorizeSecurityGroupEgress",
                    status=CheckStatus.OK,
                    message="VERIFIED - Rule exists (permission OK)"
                ))
            else:
                results.append(CheckResult(
                    name="  ec2:AuthorizeSecurityGroupEgress",
                    status=CheckStatus.WARNING,
                    message=f"Error: {error}"
                ))
        
        # Test RevokeSecurityGroupIngress
        try:
            ec2.revoke_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[{
                    'IpProtocol': 'tcp',
                    'FromPort': 8443,
                    'ToPort': 8443,
                    'IpRanges': [{'CidrIp': '192.0.2.0/24'}]
                }]
            )
            results.append(CheckResult(
                name="  ec2:RevokeSecurityGroupIngress",
                status=CheckStatus.OK,
                message="VERIFIED"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  ec2:RevokeSecurityGroupIngress",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
        
        # CLEANUP: Delete the test security group
        try:
            ec2.delete_security_group(GroupId=sg_id)
            self._unregister_cleanup(sg_id)  # inline delete done; don't re-sweep
            results.append(CheckResult(
                name="  🗑️  ec2:DeleteSecurityGroup",
                status=CheckStatus.OK,
                message=f"✓ DELETED: {sg_id} ({sg_name})"
            ))
        except Exception as e:
            error = str(e)
            if is_access_denied(error):
                results.append(CheckResult(
                    name="  ec2:DeleteSecurityGroup",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            else:
                results.append(CheckResult(
                    name="  ec2:DeleteSecurityGroup",
                    status=CheckStatus.WARNING,
                    message=f"Manual cleanup needed: {sg_id}"
                ))
        
        return results
    
    def _simulate_actions(self, actions: List[str], resource: str = "*") -> Dict[str, Tuple[str, str]]:
        """
        Simulate IAM actions to check permissions.
        Returns dict of action -> (status, message)
        status: 'allowed' | 'denied' | 'error' | 'skip'
        """
        results = {}
        
        if not self._can_simulate:
            for action in actions:
                results[action] = ("skip", "IAM simulation not available")
            return results
        
        try:
            iam = self._get_client("iam")
            
            # Batch actions (max 100 per call)
            batch_size = 100
            for i in range(0, len(actions), batch_size):
                batch = actions[i:i + batch_size]
                
                try:
                    # Retry on transient throttling (otherwise a rate-limit
                    # would smear every action in the batch to "error"/WARNING).
                    response = None
                    for attempt in range(4):
                        try:
                            response = iam.simulate_principal_policy(
                                PolicySourceArn=self._user_arn,
                                ActionNames=batch,
                                ResourceArns=[resource] if resource else ["*"]
                            )
                            break
                        except Exception as se:
                            if is_throttling(se) and attempt < 3:
                                time.sleep(0.5 * (2 ** attempt))
                                continue
                            raise
                    if response is None:
                        raise RuntimeError("simulate_principal_policy returned no response")

                    for result in response.get("EvaluationResults", []):
                        action = result["EvalActionName"]
                        decision = result["EvalDecision"]

                        if decision == "allowed":
                            results[action] = ("allowed", "Permission granted")
                        else:
                            # Get reason for denial
                            matched = result.get("MatchedStatements", [])
                            if matched:
                                reason = f"Denied by {matched[0].get('SourcePolicyId', 'policy')}"
                            else:
                                reason = "Implicitly denied (no matching Allow statement)"
                            results[action] = ("denied", reason)

                except Exception as e:
                    # If the principal can't even self-simulate (denied), that's a
                    # real signal, not a benign error.
                    kind = "denied" if is_access_denied(e) else "error"
                    error_msg = ("Cannot self-verify: iam:SimulatePrincipalPolicy denied"
                                 if kind == "denied" else str(e))
                    for action in batch:
                        results[action] = (kind, error_msg)

        except Exception as e:
            kind = "denied" if is_access_denied(e) else "error"
            error_msg = str(e)
            for action in actions:
                results[action] = (kind, error_msg)

        return results
    
    def _test_dryrun(
        self,
        action_name: str,
        test_func: Callable,
        success_patterns: List[str] = None,
    ) -> Tuple[CheckStatus, str, bool]:
        """
        Test an action using DryRun.

        Returns (status, detailed_message, assumed). ``assumed`` is True only
        when the probe could NOT actually verify the permission — the request
        was rejected at parameter validation, BEFORE authorization was
        evaluated — so callers can flag the result and a mixed area won't read
        PASS on an unverified deploy-critical permission (review H3).
        """
        success_patterns = success_patterns or ["DryRunOperation"]

        try:
            test_func()
            # If no exception, unexpected success
            return (CheckStatus.OK, "Allowed (unexpected actual success)", False)
        except Exception as e:
            error_str = str(e)
            error_code = getattr(e, 'response', {}).get('Error', {}).get('Code', '')
            
            # Check for DryRun success (means permission is granted)
            for pattern in success_patterns:
                if pattern in error_str or pattern == error_code:
                    return (CheckStatus.OK, "Allowed (DryRun verified)", False)
            
            # Permission denied / org-policy / quota block. Use the shared
            # deploy-blocking classifier (SCP, permission boundary, explicit
            # deny, *Exception-suffixed codes) instead of ad-hoc substring
            # matching, which let SCP/boundary denials fall through to a soft
            # WARNING and then PASS (review H2).
            if is_deploy_blocking(error_str):
                if "is not authorized to perform" in error_str:
                    parts = error_str.split("is not authorized to perform:")
                    if len(parts) > 1:
                        denied_action = parts[1].split(" on ")[0].strip()
                        return (CheckStatus.NOT_OK, f"DENIED: {denied_action}", False)
                return (CheckStatus.NOT_OK, f"DENIED: {error_str[:100]}", False)

            # Resource-not-found: AWS evaluated the request, authorization PASSED,
            # and only THEN found the (deliberately non-existent) test resource
            # missing — so the permission is genuinely granted.
            resource_not_found_patterns = [
                "InvalidVpcID.NotFound", "InvalidSubnetID.NotFound",
                "InvalidGroup.NotFound", "InvalidAMIID.NotFound",
                "NoSuchEntity", "InvalidInstanceID.NotFound",
                "InvalidVolume.NotFound", "InvalidAllocationID.NotFound",
                "InvalidRoute.NotFound", "InvalidVpcEndpointId.NotFound",
                "does not exist",
            ]
            for pattern in resource_not_found_patterns:
                if pattern in error_str or pattern == error_code:
                    return (CheckStatus.OK, "Allowed (resource doesn't exist)", False)

            # Parameter-validation / malformed request: AWS rejected this BEFORE
            # evaluating authorization, so it proves NOTHING about the permission.
            # Report it unverified (WARNING) rather than OK, so it can't produce a
            # false PASS (review H3). The probes pass placeholder ids like
            # "vpc-test" / "i-test12345" that hit exactly this path.
            param_validation_patterns = [
                "InvalidParameterValue", "InvalidParameterCombination",
                "MalformedAMIID", "Malformed", "ValidationError",
                "InvalidParameter",
            ]
            for pattern in param_validation_patterns:
                if pattern in error_str or pattern == error_code:
                    return (
                        CheckStatus.WARNING,
                        f"Unverified — request rejected at parameter validation "
                        f"({pattern}), before authorization; cannot confirm this permission",
                        True,
                    )

            # Unknown error - return full message for debugging
            return (CheckStatus.WARNING, f"Check failed: {error_str}", False)
    
    def _add_detailed_result(self, category: CheckCategory, name: str, status: CheckStatus, message: str):
        """Add a result with proper formatting."""
        category.add_result(CheckResult(name=name, status=status, message=message))
    
    def check_credentials(self) -> CheckCategory:
        """Check AWS credentials validity."""
        category = CheckCategory(name="CREDENTIALS")
        
        try:
            sts = self._get_client("sts")
            identity = sts.get_caller_identity()
            
            self._account_id = identity["Account"]
            self._arn = identity["Arn"]
            self._user_arn = identity["Arn"]
            
            category.add_result(CheckResult(
                name="AWS Credentials (STS)",
                status=CheckStatus.OK,
                message="Valid credentials"
            ))
            
            category.add_result(CheckResult(
                name="Account ID",
                status=CheckStatus.OK,
                message=self._account_id
            ))
            
            category.add_result(CheckResult(
                name="Identity ARN",
                status=CheckStatus.OK,
                message=self._arn[:60] + "..." if len(self._arn) > 60 else self._arn
            ))
            
            if self._report:
                self._report.account_info = f"Account: {self._account_id} | ARN: {self._arn}"
            
            # Check region
            if self.region:
                category.add_result(CheckResult(
                    name="Region",
                    status=CheckStatus.OK,
                    message=self.region
                ))
            else:
                session = self._get_session()
                detected_region = session.region_name
                if detected_region:
                    self.region = detected_region
                    category.add_result(CheckResult(
                        name="Region",
                        status=CheckStatus.WARNING,
                        message=f"Using default: {detected_region}"
                    ))
                else:
                    self.region = "us-east-1"
                    category.add_result(CheckResult(
                        name="Region",
                        status=CheckStatus.WARNING,
                        message="No region, using us-east-1"
                    ))

            # STS regional endpoint activation. Cross-account AssumeRole and the
            # STS interface VPC endpoint both hit STS in the workspace region;
            # opt-in regions start DEACTIVATED and any region can be turned off,
            # which fails the deploy at AssumeRole (RegionDisabledException).
            try:
                regional_sts = self._get_session().client(
                    "sts", region_name=self.region,
                    endpoint_url=f"https://sts.{self.region}.amazonaws.com",
                )
                regional_sts.get_caller_identity()
                category.add_result(CheckResult(
                    name="STS Regional Endpoint", status=CheckStatus.OK,
                    message=f"Activated in {self.region}",
                ))
            except Exception as e:
                err = str(e)
                if "RegionDisabledException" in err or "not activated" in err:
                    category.add_result(CheckResult(
                        name="STS Regional Endpoint", status=CheckStatus.NOT_OK,
                        message=f"STS is NOT activated in {self.region} - cross-account AssumeRole and the STS VPC endpoint will FAIL",
                        remediation="Activate STS for this region: AWS Console -> IAM -> Account settings -> Security Token Service (STS).",
                        doc_link="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp_enable-regions.html",
                    ))
                else:
                    category.add_result(CheckResult(
                        name="STS Regional Endpoint", status=CheckStatus.WARNING,
                        message=f"Could not verify STS activation in {self.region}: {err[:80]}",
                    ))

            # Test IAM simulation capability
            try:
                iam = self._get_client("iam")
                iam.simulate_principal_policy(
                    PolicySourceArn=self._user_arn,
                    ActionNames=["sts:GetCallerIdentity"],
                    ResourceArns=["*"]
                )
                self._can_simulate = True
                category.add_result(CheckResult(
                    name="IAM Policy Simulation",
                    status=CheckStatus.OK,
                    message="Can simulate policies for accurate checks"
                ))
            except Exception as e:
                self._can_simulate = False
                category.add_result(CheckResult(
                    name="IAM Policy Simulation",
                    status=CheckStatus.OK,
                    message="Not available - using DryRun API calls"
                ))
                    
        except ImportError as e:
            category.add_result(CheckResult(
                name="AWS SDK",
                status=CheckStatus.NOT_OK,
                message=str(e)
            ))
        except Exception as e:
            error_msg = str(e)
            if "InvalidClientTokenId" in error_msg:
                message = "Invalid AWS Access Key ID"
            elif "SignatureDoesNotMatch" in error_msg:
                message = "Invalid AWS Secret Access Key"
            elif "ExpiredToken" in error_msg:
                message = "AWS session token expired"
            elif "NoCredentialsError" in error_msg or "Unable to locate credentials" in error_msg:
                message = "No AWS credentials found"
            else:
                message = error_msg[:100]
            
            category.add_result(CheckResult(
                name="AWS Credentials",
                status=CheckStatus.NOT_OK,
                message=message
            ))
        
        return category
    
    # =========================================================================
    # STEP 1: STORAGE CONFIGURATION
    # Based on: https://docs.databricks.com/aws/en/admin/workspace/create-uc-workspace#storage
    # =========================================================================
    
    def check_storage_configuration(self) -> CheckCategory:
        """
        Check permissions for Storage Configuration (Root Bucket).
        Tests permissions by creating REAL temporary resources and cleaning up.
        In verify_only mode, uses read-only checks and DryRun API calls.
        """
        category = CheckCategory(name="STORAGE CONFIGURATION (Root Bucket)")
        
        if self.verify_only:
            category.add_result(CheckResult(
                name="Test Method",
                status=CheckStatus.OK,
                message="VERIFY-ONLY: Read-only checks (no resource creation)"
            ))
            
            # Verify-only S3 checks
            category.add_result(CheckResult(
                name="── S3 Bucket Operations (Read-Only) ──",
                status=CheckStatus.OK,
                message=""
            ))
            
            s3 = self._get_client("s3")
            
            # Test ListBuckets
            try:
                s3.list_buckets()
                category.add_result(CheckResult(
                    name="  s3:ListBuckets",
                    status=CheckStatus.OK,
                    message="VERIFIED - Can list existing buckets"
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  s3:ListBuckets",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)[:80]}"
                ))
            
            # Check IAM simulation for S3 actions
            if self._can_simulate:
                s3_actions = ["s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketVersioning", 
                             "s3:PutBucketPolicy", "s3:PutEncryptionConfiguration"]
                results = self._simulate_actions(s3_actions)
                for action in s3_actions:
                    status_str, message = results.get(action, ("error", "Unknown"))
                    if status_str == "allowed":
                        status = CheckStatus.OK
                    elif status_str == "denied":
                        status = CheckStatus.NOT_OK  # explicit deny is a hard blocker (review C2)
                    else:
                        status = CheckStatus.WARNING
                    category.add_result(CheckResult(
                        name=f"  {action}",
                        status=status,
                        message=f"Simulated: {message}"
                    ))
            else:
                category.add_result(CheckResult(
                    name="  S3 Write Permissions",
                    status=CheckStatus.WARNING,
                    message="Cannot verify without IAM simulation or resource creation"
                ))
            
            # Verify-only IAM checks
            category.add_result(CheckResult(
                name="── IAM Role Operations (Read-Only) ──",
                status=CheckStatus.OK,
                message=""
            ))
            
            iam = self._get_client("iam")
            
            try:
                iam.list_roles(MaxItems=5)
                category.add_result(CheckResult(
                    name="  iam:ListRoles",
                    status=CheckStatus.OK,
                    message="VERIFIED - Can list existing roles"
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  iam:ListRoles",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)[:80]}"
                ))
            
            if self._can_simulate:
                iam_actions = ["iam:CreateRole", "iam:DeleteRole", "iam:PutRolePolicy", 
                              "iam:CreatePolicy", "iam:DeletePolicy"]
                results = self._simulate_actions(iam_actions)
                for action in iam_actions:
                    status_str, message = results.get(action, ("error", "Unknown"))
                    if status_str == "allowed":
                        status = CheckStatus.OK
                    elif status_str == "denied":
                        status = CheckStatus.NOT_OK  # explicit deny is a hard blocker (review C2)
                    else:
                        status = CheckStatus.WARNING
                    category.add_result(CheckResult(
                        name=f"  {action}",
                        status=status,
                        message=f"Simulated: {message}"
                    ))
            else:
                category.add_result(CheckResult(
                    name="  IAM Write Permissions",
                    status=CheckStatus.WARNING,
                    message="Cannot verify without IAM simulation or resource creation"
                ))
            
            return category
        
        # Full mode with resource creation
        category.add_result(CheckResult(
            name="Test Method",
            status=CheckStatus.OK,
            message="Using REAL resource creation (create → test → delete)"
        ))
        
        # =====================================================================
        # Step 1.1: Create S3 Bucket - REAL TEST
        # =====================================================================
        category.add_result(CheckResult(
                name="── S3 Bucket Operations ──",
            status=CheckStatus.OK,
            message=""
        ))
        
        s3_results = self._test_s3_bucket_permissions()
        for result in s3_results:
            category.add_result(result)
        
        # =====================================================================
        # Step 1.2: Create IAM Role - REAL TEST
        # =====================================================================
        category.add_result(CheckResult(
                name="── IAM Role Operations ──",
            status=CheckStatus.OK,
            message=""
        ))
        
        role_results = self._test_iam_role_permissions()
        for result in role_results:
            category.add_result(result)
        
        # =====================================================================
        # Step 1.3: Create IAM Policy - REAL TEST
        # =====================================================================
        category.add_result(CheckResult(
                name="── IAM Policy Operations ──",
            status=CheckStatus.OK,
            message=""
        ))
        
        policy_results = self._test_iam_policy_permissions()
        for result in policy_results:
            category.add_result(result)
        
        return category
    
    # =========================================================================
    # STEP 2: NETWORK CONFIGURATION (Customer-Managed VPC)
    # =========================================================================
    
    def check_network_configuration(self) -> CheckCategory:
        """
        Check permissions for Network Configuration (Customer-managed VPC).
        Tests EACH EC2/VPC permission individually.
        """
        category = CheckCategory(name="NETWORK CONFIGURATION (Customer-managed VPC)")
        
        ec2 = self._get_client("ec2")
        
        category.add_result(CheckResult(
            name="── VPC Configuration ──",
            status=CheckStatus.OK,
            message=""
        ))
        
        vpc_actions = [
            ("ec2:DescribeVpcs", "List/describe VPCs"),
            ("ec2:DescribeVpcAttribute", "Check VPC DNS settings"),
            ("ec2:DescribeSubnets", "List/describe subnets"),
            ("ec2:DescribeRouteTables", "List/describe route tables"),
            ("ec2:DescribeInternetGateways", "List/describe internet gateways"),
            ("ec2:DescribeNatGateways", "List/describe NAT gateways"),
        ]
        
        network_ok = True
        
        if self._can_simulate:
            actions = [a[0] for a in vpc_actions]
            results = self._simulate_actions(actions)
            
            for action, description in vpc_actions:
                status_str, message = results.get(action, ("error", "Unknown"))
                
                if status_str == "allowed":
                    status = CheckStatus.OK
                elif status_str == "denied":
                    status = CheckStatus.NOT_OK
                    network_ok = False
                else:
                    status = CheckStatus.WARNING
                
                category.add_result(CheckResult(
                    name=f"  {action}",
                    status=status,
                    message=message
                ))
        else:
            try:
                ec2.describe_vpcs(MaxResults=5)
                category.add_result(CheckResult(
                    name="  ec2:DescribeVpcs",
                    status=CheckStatus.OK,
                    message="Allowed - Can list VPCs"
                ))
            except Exception as e:
                network_ok = False
                category.add_result(CheckResult(
                    name="  ec2:DescribeVpcs",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)}"
                ))
            
            try:
                vpcs = ec2.describe_vpcs(MaxResults=5)
                if vpcs.get("Vpcs"):
                    vpc_id = vpcs["Vpcs"][0]["VpcId"]
                    ec2.describe_vpc_attribute(VpcId=vpc_id, Attribute='enableDnsHostnames')
                    category.add_result(CheckResult(
                        name="  ec2:DescribeVpcAttribute",
                        status=CheckStatus.OK,
                        message="Allowed - Can check VPC DNS settings"
                    ))
            except Exception as e:
                if is_access_denied(e):
                    network_ok = False
                    category.add_result(CheckResult(
                        name="  ec2:DescribeVpcAttribute",
                        status=CheckStatus.NOT_OK,
                        message=f"DENIED: {str(e)}"
                    ))
            
            try:
                ec2.describe_subnets(MaxResults=5)
                category.add_result(CheckResult(
                    name="  ec2:DescribeSubnets",
                    status=CheckStatus.OK,
                    message="Allowed - Can list subnets"
                ))
            except Exception as e:
                network_ok = False
                category.add_result(CheckResult(
                    name="  ec2:DescribeSubnets",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)}"
                ))
        
        # =====================================================================
        # Subnet Configuration
        # =====================================================================
        category.add_result(CheckResult(
            name="── Subnet Configuration ──",
            status=CheckStatus.OK,
            message=""
        ))
        
        try:
            if self.vpc_id:
                # Validate the VPC exists in this region before scoping to it.
                try:
                    ec2.describe_vpcs(VpcIds=[self.vpc_id])
                    category.add_result(CheckResult(
                        name="  Target VPC", status=CheckStatus.OK,
                        message=f"Scoping network checks to {self.vpc_id}",
                    ))
                except Exception as e:
                    network_ok = False
                    category.add_result(CheckResult(
                        name="  Target VPC", status=CheckStatus.NOT_OK,
                        message=f"VPC {self.vpc_id} not found in region {self.region} ({str(e)[:60]})",
                        remediation="Check the --vpc-id value and that --region matches the VPC's region.",
                    ))
                    self._check_results_by_area["network"] = category.area_state
                    return category
                subnet_list = self._describe_all(
                    ec2, "describe_subnets", "Subnets",
                    Filters=[{"Name": "vpc-id", "Values": [self.vpc_id]}],
                )
            else:
                subnet_list = self._describe_all(ec2, "describe_subnets", "Subnets")
                category.add_result(CheckResult(
                    name="  Scope", status=CheckStatus.OK,
                    message="No --vpc-id given: counting subnets ACCOUNT-WIDE. Pass --vpc-id for a VPC-specific check.",
                ))

            if self.vpc_id:
                private_subnets = [s for s in subnet_list if not s.get("MapPublicIpOnLaunch", False)]
                private = len(private_subnets)
                public = len(subnet_list) - private

                if private >= 2:
                    category.add_result(CheckResult(
                        name="  Private Subnets",
                        status=CheckStatus.OK,
                        message=f"{private} available (Databricks needs 2+ in different AZs)"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="  Private Subnets",
                        status=CheckStatus.WARNING,
                        message=f"Only {private} found - need 2+ for Databricks"
                    ))

                category.add_result(CheckResult(
                    name="  Public Subnets",
                    status=CheckStatus.OK,
                    message=f"{public} available"
                ))

                azs = set(s["AvailabilityZone"] for s in private_subnets)
                if len(azs) >= 2:
                    category.add_result(CheckResult(
                        name="  AZ Distribution",
                        status=CheckStatus.OK,
                        message=f"Private subnets in {len(azs)} AZs: {', '.join(sorted(azs)[:3])}"
                    ))
                elif len(azs) == 1:
                    category.add_result(CheckResult(
                        name="  AZ Distribution",
                        status=CheckStatus.WARNING,
                        message=f"Private subnets only in 1 AZ - recommend 2+ for HA"
                    ))

                too_small = []
                tiny = []
                for s in private_subnets:
                    cidr = s.get("CidrBlock", "")
                    free = s.get("AvailableIpAddressCount")
                    try:
                        prefix = int(cidr.split("/")[1])
                    except (IndexError, ValueError):
                        continue
                    if prefix > 26:
                        too_small.append(f"{s.get('SubnetId')} ({cidr}, {free} free IPs)")
                    elif prefix < 17:
                        tiny.append(f"{s.get('SubnetId')} ({cidr})")
                if private_subnets:
                    if too_small:
                        category.add_result(CheckResult(
                            name="  Subnet Size", status=CheckStatus.WARNING,
                            message=f"{len(too_small)} private subnet(s) smaller than /26 (Databricks needs /17–/26): "
                                    + "; ".join(too_small[:3]),
                            remediation="Use private subnets sized /17–/26 (≈ /24 recommended) so clusters have enough node IPs.",
                            doc_link="https://docs.databricks.com/aws/en/admin/workspace/create-workspace#requirements",
                        ))
                    elif tiny:
                        category.add_result(CheckResult(
                            name="  Subnet Size", status=CheckStatus.WARNING,
                            message=f"{len(tiny)} private subnet(s) larger than /17 (Databricks needs /17–/26): "
                                    + "; ".join(tiny[:3]),
                            remediation="Use private subnets sized /17–/26 (≈ /24 recommended).",
                            doc_link="https://docs.databricks.com/aws/en/admin/workspace/create-workspace#requirements",
                        ))
                    else:
                        sizes = sorted({s.get("CidrBlock", "").split("/")[-1] for s in private_subnets})
                        min_free = min((s.get("AvailableIpAddressCount", 0) for s in private_subnets), default=0)
                        category.add_result(CheckResult(
                            name="  Subnet Size", status=CheckStatus.OK,
                            message=f"Private subnets within /17–/26 (/{', /'.join(sizes)}); min free IPs in a subnet: {min_free}",
                        ))

                try:
                    nats = self._describe_all(ec2, "describe_nat_gateways", "NatGateways",
                                              Filter=[{"Name": "state", "Values": ["available"]},
                                                      {"Name": "vpc-id", "Values": [self.vpc_id]}])
                    if nats:
                        category.add_result(CheckResult(
                            name="  Outbound egress (if no PrivateLink)", status=CheckStatus.OK,
                            message=f"{len(nats)} NAT gateway(s) in {self.vpc_id}",
                        ))
                    else:
                        category.add_result(CheckResult(
                            name="  Outbound egress (if no PrivateLink)", status=CheckStatus.WARNING,
                            message=f"No NAT gateway found in {self.vpc_id}. Without PrivateLink the data plane needs an egress path (NAT + 0.0.0.0/0 route, or firewall/proxy).",
                            remediation="Add a NAT gateway + default route to the private subnets, or use PrivateLink / a firewall egress.",
                        ))
                except Exception as e:
                    category.add_result(CheckResult(
                        name="  Outbound egress (if no PrivateLink)", status=CheckStatus.WARNING,
                        message=f"Could not verify egress: {str(e)[:80]}",
                    ))

        except Exception as e:
            network_ok = False
            category.add_result(CheckResult(
                name="  ec2:DescribeSubnets",
                status=CheckStatus.NOT_OK,
                message=f"DENIED: {str(e)}"
            ))
        
        # =====================================================================
        # Step 2.3: Security Group Configuration - REAL TEST or VERIFY-ONLY
        # =====================================================================
        if self.verify_only:
            category.add_result(CheckResult(
                name="── Security Group & Rules (Read-Only) ──",
                status=CheckStatus.OK,
                message=""
            ))
            
            # Read-only SG checks
            try:
                sgs = ec2.describe_security_groups(MaxResults=5)
                sg_count = len(sgs.get("SecurityGroups", []))
                category.add_result(CheckResult(
                    name="  ec2:DescribeSecurityGroups",
                    status=CheckStatus.OK,
                    message=f"VERIFIED - Found {sg_count} security group(s)"
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  ec2:DescribeSecurityGroups",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)[:80]}"
                ))
            
            # DryRun test for CreateSecurityGroup
            status, msg, assumed = self._test_dryrun(
                "ec2:CreateSecurityGroup",
                lambda: ec2.create_security_group(
                    GroupName="databricks-test",
                    Description="test",
                    VpcId="vpc-test",
                    DryRun=True
                ),
            )
            category.add_result(CheckResult(name="  ec2:CreateSecurityGroup (DryRun)", status=status, message=msg, assumed=assumed))
            
            if self._can_simulate:
                sg_actions = ["ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
                             "ec2:RevokeSecurityGroupIngress", "ec2:DeleteSecurityGroup"]
                results = self._simulate_actions(sg_actions)
                for action in sg_actions:
                    status_str, message = results.get(action, ("error", "Unknown"))
                    if status_str == "allowed":
                        status = CheckStatus.OK
                    elif status_str == "denied":
                        status = CheckStatus.NOT_OK  # explicit deny is a hard blocker (review C2)
                    else:
                        status = CheckStatus.WARNING
                    category.add_result(CheckResult(
                        name=f"  {action}",
                        status=status,
                        message=f"Simulated: {message}"
                    ))
        else:
            category.add_result(CheckResult(
                name="── Security Group & Rules (REAL TEST) ──",
                status=CheckStatus.OK,
                message=""
            ))
            
            # Use real resource creation to test SG permissions
            sg_results = self._test_security_group_permissions(vpc_id=self.vpc_id)
            for result in sg_results:
                category.add_result(result)
        
        self._check_results_by_area["network"] = category.area_state
        
        return category
    
    def check_privatelink(self) -> CheckCategory:
        """Check permissions for VPC Endpoints / PrivateLink connectivity."""
        category = CheckCategory(name="VPC ENDPOINTS (PrivateLink)")
        
        ec2 = self._get_client("ec2")

        endpoint_actions = [
            ("ec2:CreateVpcEndpoint", "Create VPC endpoint"),
            ("ec2:DeleteVpcEndpoints", "Delete VPC endpoint"),
            ("ec2:ModifyVpcEndpoint", "Modify VPC endpoint"),
            ("ec2:DescribeVpcEndpoints", "List/describe VPC endpoints"),
            ("ec2:DescribeVpcEndpointServices", "List available endpoint services"),
        ]
        
        if self._can_simulate:
            actions = [a[0] for a in endpoint_actions]
            results = self._simulate_actions(actions)
            
            for action, description in endpoint_actions:
                status_str, message = results.get(action, ("error", "Unknown"))
                
                if status_str == "allowed":
                    status = CheckStatus.OK
                elif status_str == "denied":
                    status = CheckStatus.NOT_OK
                else:
                    status = CheckStatus.WARNING
                
                category.add_result(CheckResult(
                    name=f"  {action}",
                    status=status,
                    message=message
                ))
        else:
            try:
                ec2.describe_vpc_endpoints(MaxResults=5)
                category.add_result(CheckResult(
                    name="  ec2:DescribeVpcEndpoints",
                    status=CheckStatus.OK,
                    message="Allowed"
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  ec2:DescribeVpcEndpoints",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)}"
                ))
            
            status, msg, assumed = self._test_dryrun(
                "ec2:CreateVpcEndpoint",
                lambda: ec2.create_vpc_endpoint(
                    VpcId="vpc-test",
                    ServiceName=f"com.amazonaws.{self.region}.s3",
                    VpcEndpointType='Gateway',
                    DryRun=True
                ),
            )
            category.add_result(CheckResult(name="  ec2:CreateVpcEndpoint (S3 Gateway)", status=status, message=msg, assumed=assumed))

            # Interface endpoints the SRA creates (STS, Kinesis Streams). These
            # need CreateVpcEndpoint with the Interface type (+ ENI + SG attach).
            for svc_label, svc_name in [
                ("STS", f"com.amazonaws.{self.region}.sts"),
                ("Kinesis Streams", f"com.amazonaws.{self.region}.kinesis-streams"),
            ]:
                status, msg, assumed = self._test_dryrun(
                    f"ec2:CreateVpcEndpoint ({svc_label})",
                    lambda s=svc_name: ec2.create_vpc_endpoint(
                        VpcId="vpc-test",
                        ServiceName=s,
                        VpcEndpointType="Interface",
                        DryRun=True,
                    ),
                )
                category.add_result(CheckResult(
                    name=f"  ec2:CreateVpcEndpoint ({svc_label})", status=status, message=msg, assumed=assumed
                ))

        try:
            describe_kwargs = {}
            if self.vpc_id:
                describe_kwargs["Filters"] = [{"Name": "vpc-id", "Values": [self.vpc_id]}]
            endpoint_list = self._describe_all(ec2, "describe_vpc_endpoints", "VpcEndpoints", **describe_kwargs)

            gateway = sum(1 for e in endpoint_list if e["VpcEndpointType"] == "Gateway")
            interface = sum(1 for e in endpoint_list if e["VpcEndpointType"] == "Interface")

            category.add_result(CheckResult(
                name="  Existing VPC Endpoints",
                status=CheckStatus.OK,
                message=f"{gateway} Gateway, {interface} Interface endpoints"
                        + (f" in {self.vpc_id}" if self.vpc_id else " (account-wide)"),
            ))

            if self.vpc_id:
                for ep_name, ep_filter, ep_type, ep_desc in [
                    ("S3 Gateway Endpoint",       "s3",      "Gateway",   "recommended for cost savings"),
                    ("STS Interface Endpoint",    "sts",     "Interface", "required for PrivateLink deployments"),
                    ("Kinesis Interface Endpoint","kinesis", "Interface", "required for PrivateLink deployments"),
                ]:
                    found = [
                        e for e in endpoint_list
                        if ep_filter in e.get("ServiceName", "").lower()
                        and e["VpcEndpointType"] == ep_type
                    ]
                    if found:
                        category.add_result(CheckResult(
                            name=f"  {ep_name}",
                            status=CheckStatus.OK,
                            message=f"Found: {found[0]['VpcEndpointId']}",
                        ))
                    else:
                        category.add_result(CheckResult(
                            name=f"  {ep_name}",
                            status=CheckStatus.WARNING,
                            message=f"Not found in {self.vpc_id} — {ep_desc}",
                        ))

        except Exception as e:
            category.add_result(CheckResult(
                name="  VPC Endpoints",
                status=CheckStatus.WARNING,
                message=f"Cannot list: {str(e)[:40]}"
            ))
        
        self._check_results_by_area["privatelink"] = category.area_state
        
        return category
    
    # =========================================================================
    # STEP 3: CROSS-ACCOUNT ROLE
    # =========================================================================
    
    def check_cross_account_role(self) -> CheckCategory:
        """
        Check permissions for Cross-Account IAM Role.
        Tests EACH required permission for Customer-managed VPC.
        """
        category = CheckCategory(name="CROSS-ACCOUNT ROLE (Customer-managed VPC)")
        
        ec2 = self._get_client("ec2")
        iam = self._get_client("iam")
        cross_account_ok = True
        
        required_actions = get_cross_account_actions()
        
        category.add_result(CheckResult(
            name="Policy Type",
            status=CheckStatus.OK,
            message=f"Customer-managed VPC - {len(required_actions)} actions required"
        ))
        
        category.add_result(CheckResult(
            name="── Create Cross-Account Role ──",
            status=CheckStatus.OK,
            message=""
        ))
        
        role_actions = [
            ("iam:CreateRole", "Create cross-account role"),
            ("iam:DeleteRole", "Delete role (Terraform destroy)"),
            ("iam:GetRole", "Read role configuration"),
            ("iam:TagRole", "Tag the role"),
            ("iam:UpdateAssumeRolePolicy", "Update trust policy"),
            ("iam:PutRolePolicy", "Add inline policy"),
            ("iam:AttachRolePolicy", "Attach managed policy"),
        ]
        
        if self._can_simulate:
            actions = [a[0] for a in role_actions]
            results = self._simulate_actions(actions)
            
            for action, description in role_actions:
                status_str, message = results.get(action, ("error", "Unknown"))
                
                if status_str == "allowed":
                    status = CheckStatus.OK
                elif status_str == "denied":
                    status = CheckStatus.NOT_OK
                else:
                    status = CheckStatus.WARNING
                
                category.add_result(CheckResult(
                    name=f"  {action}",
                    status=status,
                    message=message
                ))
        else:
            # Basic tests
            try:
                iam.list_roles(MaxItems=1)
                category.add_result(CheckResult(
                    name="  iam:ListRoles",
                    status=CheckStatus.OK,
                    message="Allowed"
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  iam:ListRoles",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)}"
                ))
        
        category.add_result(CheckResult(
            name="── Cross-Account Policy Permissions ──",
            status=CheckStatus.OK,
            message=""
        ))
        
        # Key EC2 actions for cluster management
        ec2_critical_actions = [
            ("ec2:RunInstances", "Launch cluster instances"),
            ("ec2:TerminateInstances", "Terminate cluster instances"),
            ("ec2:CreateVolume", "Create EBS volumes for clusters"),
            ("ec2:DeleteVolume", "Delete EBS volumes"),
            ("ec2:AttachVolume", "Attach EBS to instances"),
            ("ec2:DetachVolume", "Detach EBS from instances"),
            ("ec2:CreateSecurityGroup", "Create cluster security groups"),
            ("ec2:DeleteSecurityGroup", "Delete security groups"),
            ("ec2:CreateTags", "Tag AWS resources"),
            ("ec2:DeleteTags", "Remove tags"),
        ]
        
        if self._can_simulate:
            # Simulate ALL cross-account actions
            results = self._simulate_actions(required_actions)
            
            # Group by service and count
            services = {}
            for action in required_actions:
                service = action.split(":")[0]
                if service not in services:
                    services[service] = {"allowed": [], "denied": [], "error": []}
                
                status_str, msg = results.get(action, ("error", "Unknown"))
                services[service][status_str if status_str in ["allowed", "denied"] else "error"].append((action, msg))
            
            # Report by service
            for service in sorted(services.keys()):
                counts = services[service]
                allowed = len(counts["allowed"])
                denied = len(counts["denied"])
                errors = len(counts["error"])
                total = allowed + denied + errors
                
                if denied == 0 and errors == 0:
                    category.add_result(CheckResult(
                        name=f"  {service.upper()} ({total} actions)",
                        status=CheckStatus.OK,
                        message="All allowed"
                    ))
                else:
                    # List denied actions
                    for action, msg in counts["denied"][:5]:
                        short_action = action.split(":")[1]
                        category.add_result(CheckResult(
                            name=f"    {action}",
                            status=CheckStatus.NOT_OK,
                            message=msg
                        ))
                    if denied > 5:
                        category.add_result(CheckResult(
                            name=f"    ... and {denied - 5} more denied",
                            status=CheckStatus.NOT_OK,
                            message=""
                        ))
        else:
            # DescribeInstances (no DryRun, just test)
            try:
                ec2.describe_instances(MaxResults=5)
                category.add_result(CheckResult(
                    name="  ec2:DescribeInstances",
                    status=CheckStatus.OK,
                    message="Allowed"
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  ec2:DescribeInstances",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)}"
                ))
            
            # DescribeVolumes
            try:
                ec2.describe_volumes(MaxResults=5)
                category.add_result(CheckResult(
                    name="  ec2:DescribeVolumes",
                    status=CheckStatus.OK,
                    message="Allowed"
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  ec2:DescribeVolumes",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)}"
                ))
            
            # DescribeImages
            try:
                ec2.describe_images(Owners=['self'], MaxResults=5)
                category.add_result(CheckResult(
                    name="  ec2:DescribeImages",
                    status=CheckStatus.OK,
                    message="Allowed"
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  ec2:DescribeImages",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)}"
                ))
        
        category.add_result(CheckResult(
            name="── Spot Instance Permissions ──",
            status=CheckStatus.OK,
            message=""
        ))
        
        spot_actions = [
            ("iam:CreateServiceLinkedRole", "Create SLR for EC2 Spot"),
            ("ec2:RequestSpotInstances", "Request spot instances"),
            ("ec2:CancelSpotInstanceRequests", "Cancel spot requests"),
        ]
        
        if self._can_simulate:
            actions = [a[0] for a in spot_actions]
            results = self._simulate_actions(actions)
            
            for action, description in spot_actions:
                status_str, message = results.get(action, ("error", "Unknown"))
                
                if status_str == "allowed":
                    status = CheckStatus.OK
                elif status_str == "denied":
                    status = CheckStatus.WARNING  # Spot is optional
                else:
                    status = CheckStatus.WARNING
                
                category.add_result(CheckResult(
                    name=f"  {action}",
                    status=status,
                    message=f"{message} (optional for Spot instances)"
                ))
        else:
            # Check if Spot SLR exists
            try:
                iam.get_role(RoleName="AWSServiceRoleForEC2Spot")
                category.add_result(CheckResult(
                    name="  AWSServiceRoleForEC2Spot",
                    status=CheckStatus.OK,
                    message="Service-linked role exists"
                ))
            except Exception as e:
                if "NoSuchEntity" in str(e):
                    category.add_result(CheckResult(
                        name="  AWSServiceRoleForEC2Spot",
                        status=CheckStatus.WARNING,
                        message="Not found - will be created on first Spot request"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="  AWSServiceRoleForEC2Spot",
                        status=CheckStatus.WARNING,
                        message=f"Cannot check: {str(e)[:40]}"
                    ))
            
            # Test RequestSpotInstances
            # Spot is an OPTIONAL capability. Ignore the ``assumed`` flag here so an
            # unverifiable spot probe never drags cross_account to NOT_TESTED.
            status, msg, _ = self._test_dryrun(
                "ec2:RequestSpotInstances",
                lambda: ec2.request_spot_instances(
                    InstanceCount=1,
                    LaunchSpecification={
                        'ImageId': 'ami-test',
                        'InstanceType': 't3.micro',
                    },
                    DryRun=True
                ),
            )
            category.add_result(CheckResult(
                name="  ec2:RequestSpotInstances",
                status=status if status == CheckStatus.OK else CheckStatus.WARNING,
                message=f"{msg} (optional)"
            ))
        
        self._check_results_by_area["cross_account"] = category.area_state
        
        return category
    
    # =========================================================================
    # UNITY CATALOG
    # =========================================================================
    
    def check_unity_catalog(self) -> CheckCategory:
        """Check permissions for Unity Catalog storage."""
        category = CheckCategory(name="UNITY CATALOG")
        
        s3 = self._get_client("s3")
        iam = self._get_client("iam")
        unity_ok = True
        
        category.add_result(CheckResult(
            name="── Storage Credential IAM ──",
            status=CheckStatus.OK,
            message=""
        ))
        
        uc_storage_actions = [
            ("s3:GetObject", "Read objects from UC bucket"),
            ("s3:PutObject", "Write objects to UC bucket"),
            ("s3:DeleteObject", "Delete objects from UC bucket"),
            ("s3:ListBucket", "List bucket contents"),
            ("s3:GetBucketLocation", "Get bucket region"),
        ]
        
        if self._can_simulate:
            actions = [a[0] for a in uc_storage_actions]
            results = self._simulate_actions(actions)
            
            for action, description in uc_storage_actions:
                status_str, message = results.get(action, ("error", "Unknown"))
                
                if status_str == "allowed":
                    status = CheckStatus.OK
                elif status_str == "denied":
                    status = CheckStatus.NOT_OK
                else:
                    status = CheckStatus.WARNING
                
                category.add_result(CheckResult(
                    name=f"  {action}",
                    status=status,
                    message=message
                ))
        elif self._temp_bucket_name:
            category.add_result(CheckResult(
                name="  📦 Using temp bucket for UC tests",
                status=CheckStatus.OK,
                message=self._temp_bucket_name
            ))
            uc_results = self._test_unity_catalog_s3_permissions()
            for r in uc_results:
                category.add_result(r)
        else:
            try:
                s3.list_buckets()
                category.add_result(CheckResult(
                    name="  s3:ListBuckets",
                    status=CheckStatus.OK,
                    message="Allowed"
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  s3:ListBuckets",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)}"
                ))
            
            for action, desc in uc_storage_actions[1:]:
                if "s3:" in action:
                    category.add_result(CheckResult(
                        name=f"  {action}",
                        status=CheckStatus.WARNING,
                        message="Cannot test without target bucket"
                    ))
        
        category.add_result(CheckResult(
            name="── File Events (Optional) ──",
            status=CheckStatus.OK,
            message=""
        ))
        
        if self._can_simulate:
            results = self._simulate_actions(UNITY_CATALOG_FILE_EVENTS_ACTIONS)
            
            denied = [a for a, (s, m) in results.items() if s == "denied"]
            allowed = len(UNITY_CATALOG_FILE_EVENTS_ACTIONS) - len(denied)
            
            if not denied:
                category.add_result(CheckResult(
                    name="  SNS/SQS/S3 Notifications",
                    status=CheckStatus.OK,
                    message=f"All {len(UNITY_CATALOG_FILE_EVENTS_ACTIONS)} actions allowed"
                ))
            else:
                for action in denied[:3]:
                    category.add_result(CheckResult(
                        name=f"  {action}",
                        status=CheckStatus.WARNING,
                        message="Denied (file events may not work)"
                    ))
                if len(denied) > 3:
                    category.add_result(CheckResult(
                        name=f"  ... and {len(denied) - 3} more",
                        status=CheckStatus.WARNING,
                        message=""
                    ))
        else:
            import uuid as _uuid
            test_id = str(_uuid.uuid4())[:8]
            sns = self._get_client("sns")
            sqs = self._get_client("sqs")
            topic_name = f"{TEST_RESOURCE_PREFIX}-sns-{test_id}"
            queue_name = f"{TEST_RESOURCE_PREFIX}-sqs-{test_id}"
            topic_arn = None
            queue_url = None
            try:
                topic_arn = sns.create_topic(Name=topic_name)["TopicArn"]
                category.add_result(CheckResult(
                    name="  sns:CreateTopic",
                    status=CheckStatus.OK,
                    message=f"✓ CREATED: {topic_name}",
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  sns:CreateTopic",
                    status=CheckStatus.NOT_OK if is_access_denied(str(e)) else CheckStatus.WARNING,
                    message=f"{'DENIED' if is_access_denied(str(e)) else 'Failed'}: {str(e)[:80]}",
                ))
            try:
                queue_url = sqs.create_queue(QueueName=queue_name)["QueueUrl"]
                category.add_result(CheckResult(
                    name="  sqs:CreateQueue",
                    status=CheckStatus.OK,
                    message=f"✓ CREATED: {queue_name}",
                ))
            except Exception as e:
                category.add_result(CheckResult(
                    name="  sqs:CreateQueue",
                    status=CheckStatus.NOT_OK if is_access_denied(str(e)) else CheckStatus.WARNING,
                    message=f"{'DENIED' if is_access_denied(str(e)) else 'Failed'}: {str(e)[:80]}",
                ))
            if topic_arn:
                try:
                    sns.delete_topic(TopicArn=topic_arn)
                except Exception:
                    pass
            if queue_url:
                try:
                    sqs.delete_queue(QueueUrl=queue_url)
                except Exception:
                    pass
        
        self._check_results_by_area["unity_catalog"] = category.area_state
        
        return category
    
    # =========================================================================
    # QUOTAS & LIMITS
    # =========================================================================
    
    def check_quotas(self) -> CheckCategory:
        """Check AWS service quotas using the Service Quotas API."""
        category = CheckCategory(name="QUOTAS & LIMITS")
        
        try:
            ec2 = self._get_client("ec2")
            sq = self._get_client("service-quotas")
            
            # Get REAL quota limits from Service Quotas API
            quota_codes = {
                "vpc": ("vpc", "L-F678F1CE", "VPCs per Region"),
                "eip": ("ec2", "L-0263D0A3", "Elastic IPs"),
                "igw": ("vpc", "L-A4707A72", "Internet Gateways per Region"),
                "natgw": ("vpc", "L-FE5A380F", "NAT Gateways per AZ"),
                "sg": ("vpc", "L-E79EC296", "Security Groups per VPC"),
                "vcpu": ("ec2", "L-1216C47A", "On-Demand Standard vCPUs"),
            }
            
            defaults = {"vpc": 5, "eip": 5, "igw": 5, "natgw": 5, "sg": 2500, "vcpu": 256}
            limits = {}
            assumed = {}  # key -> True if the real limit couldn't be read
            denied_any = False
            for key, (service, code, name) in quota_codes.items():
                try:
                    response = sq.get_service_quota(ServiceCode=service, QuotaCode=code)
                    limits[key] = int(response.get("Quota", {}).get("Value", 0))
                    assumed[key] = False
                except Exception as e:
                    limits[key] = defaults.get(key, 5)
                    assumed[key] = True
                    denied_any = denied_any or is_access_denied(e)

            if any(assumed.values()):
                category.add_result(CheckResult(
                    name="  ⚠️  Quota limits not readable",
                    status=CheckStatus.WARNING, assumed=True,
                    message=("Some/all quota limits could not be read"
                             + (" (servicequotas:GetServiceQuota denied)" if denied_any else "")
                             + " - values marked ASSUMED are AWS defaults, NOT your real limits"),
                    remediation="Grant servicequotas:GetServiceQuota to read your real limits.",
                ))

            def usage_result(name, count, key):
                limit = limits[key]
                if assumed[key]:
                    return CheckResult(
                        name=name, status=CheckStatus.WARNING, assumed=True,
                        message=f"{count} in use / ASSUMED DEFAULT {limit} (real limit unknown - cannot confirm headroom)",
                        remediation="Grant servicequotas:GetServiceQuota to verify the real limit.",
                    )
                pct = (count / limit * 100) if limit > 0 else 0
                if pct >= 100:
                    return CheckResult(name=name, status=CheckStatus.NOT_OK,
                                       message=f"{count}/{limit} - AT LIMIT! Request an increase before deployment")
                if pct >= 80:
                    return CheckResult(name=name, status=CheckStatus.WARNING,
                                       message=f"{count}/{limit} ({pct:.0f}%) - approaching limit")
                return CheckResult(name=name, status=CheckStatus.OK, message=f"{count}/{limit} ({pct:.0f}%)")

            # Paginate the counts so a large account isn't undercounted, which
            # would produce a wrong quota-usage verdict (review M6). (Elastic IPs
            # are returned in a single describe_addresses call — no paginator.)
            category.add_result(usage_result("  VPCs", len(self._describe_all(ec2, "describe_vpcs", "Vpcs")), "vpc"))
            category.add_result(usage_result("  Elastic IPs", len(ec2.describe_addresses().get("Addresses", [])), "eip"))
            nats = self._describe_all(ec2, "describe_nat_gateways", "NatGateways",
                                      Filters=[{"Name": "state", "Values": ["available"]}])
            category.add_result(usage_result("  NAT Gateways", len(nats), "natgw"))

            for nm, key, unit in [("  EC2 On-Demand vCPUs", "vcpu", "vCPUs"),
                                  ("  Security Groups per VPC", "sg", "")]:
                if assumed[key]:
                    category.add_result(CheckResult(
                        name=nm, status=CheckStatus.WARNING, assumed=True,
                        message=f"ASSUMED DEFAULT {limits[key]} {unit} (real limit unknown)",
                        remediation="Grant servicequotas:GetServiceQuota to verify the real limit.",
                    ))
                else:
                    category.add_result(CheckResult(
                        name=nm, status=CheckStatus.OK,
                        message=f"Limit: {limits[key]} {unit} (current usage not measured)",
                    ))
                
        except Exception as e:
            category.add_result(CheckResult(
                name="Quota Check",
                status=CheckStatus.WARNING,
                message=f"Could not get quotas: {str(e)}"
            ))
        
        return category
    
    # =========================================================================
    # POLICY SUGGESTION GENERATOR
    # =========================================================================
    
    # A valid IAM action is "service:Action" — lowercase service (may contain
    # digits/hyphens, e.g. service-quotas), CamelCase action, optional wildcard.
    _IAM_ACTION_RE = re.compile(r'[a-z][a-z0-9-]*:[A-Za-z0-9*]+')

    @classmethod
    def _extract_iam_action(cls, name: Optional[str]) -> Optional[str]:
        """Pull the canonical 'service:Action' token out of a display name.

        Result names carry decoration the raw name does not: a 🗑️ prefix,
        suffixes like ' (STS)' / ' (DryRun)', etc. Using result.name verbatim in
        an IAM policy Action produced a MalformedPolicyDocument that AWS rejects
        — exactly when the run has blockers and the customer is told to paste it
        (review H4). Extract and return only the valid action token, or None.
        """
        match = cls._IAM_ACTION_RE.search(name or "")
        return match.group(0) if match else None

    def generate_suggested_policy(self, report: CheckReport) -> Dict[str, Any]:
        """
        Generate a suggested IAM policy based on failed permission checks.
        Returns a dict that can be serialized to JSON.
        """
        denied_actions = set()

        # Collect all denied actions from the report, normalizing each to a valid
        # IAM action token so the generated document always parses (review H4).
        for category in report.categories:
            for result in category.results:
                if result.status == CheckStatus.NOT_OK:
                    action = self._extract_iam_action(result.name)
                    if action:
                        denied_actions.add(action)

        if not denied_actions:
            return None
        
        # Group actions by service
        services = {}
        for action in denied_actions:
            if ":" in action:
                service = action.split(":")[0]
                if service not in services:
                    services[service] = []
                services[service].append(action)
        
        # Build policy document
        statements = []
        
        # S3 permissions. Resource is "*" (not "arn:aws:s3:::databricks-*"): the
        # denied checks are for the pre-check's own temp bucket (dbxprecheck-*)
        # and the customer's chosen root/UC bucket names, so a databricks-* scope
        # would not actually clear the failing check (review M8). Narrow to your
        # specific bucket ARNs before using this in production.
        if "s3" in services:
            statements.append({
                "Sid": "DatabricksS3Access",
                "Effect": "Allow",
                "Action": sorted(services["s3"]),
                "Resource": "*"
            })
        
        # IAM permissions
        if "iam" in services:
            statements.append({
                "Sid": "DatabricksIAMAccess",
                "Effect": "Allow",
                "Action": sorted(services["iam"]),
                "Resource": "*"
            })
        
        # EC2 permissions
        if "ec2" in services:
            statements.append({
                "Sid": "DatabricksEC2Access",
                "Effect": "Allow",
                "Action": sorted(services["ec2"]),
                "Resource": "*"
            })
        
        # Other services
        other_services = [s for s in services if s not in ["s3", "iam", "ec2"]]
        for service in other_services:
            statements.append({
                "Sid": f"Databricks{service.upper()}Access",
                "Effect": "Allow",
                "Action": sorted(services[service]),
                "Resource": "*"
            })
        
        policy = {
            "Version": "2012-10-17",
            "Statement": statements
        }
        
        return policy
    
    def get_denied_permissions_summary(self, report: CheckReport) -> List[str]:
        """Get a list of all denied permissions from the report."""
        denied = []
        for category in report.categories:
            for result in category.results:
                if result.status == CheckStatus.NOT_OK:
                    action_name = result.name.strip()
                    if ":" in action_name and not action_name.startswith("──"):
                        denied.append(f"{action_name}: {result.message}")
        return denied
    
    # =========================================================================
    # MAIN CHECK RUNNER
    # =========================================================================
    
    def _compute_deployment_compatibility(self) -> CheckCategory:
        """Compute which deployment types are supported.

        Per-area state (PASS/FAIL/REVIEW/NOT_TESTED). A mode is:
          - NOT SUPPORTED  if any required area FAILED (a blocker);
          - NOT VERIFIED   if (no fail but) a required area couldn't be confirmed
                           (IAM simulation unavailable / --verify-only / no target);
          - REVIEW         if (no fail, all confirmed) a required area has an
                           actionable advisory — no blocker, worth a look;
          - SUPPORTED      if every required area is clean.
        The message names the ACTUAL reason and areas, never a generic catch-all.
        """
        category = CheckCategory(name="DEPLOYMENT COMPATIBILITY")
        st = self._check_results_by_area  # area -> "PASS"|"FAIL"|"REVIEW"|"NOT_TESTED"

        modes = [
            ("Standard", ["storage", "network", "cross_account"], "Basic workspace (VPC, S3, IAM)"),
            ("PrivateLink", ["storage", "network", "cross_account", "privatelink"], "With VPC Endpoints for private connectivity"),
            ("Unity Catalog", ["storage", "network", "cross_account", "unity_catalog"], "With Unity Catalog storage credentials"),
            ("Full", ["storage", "network", "cross_account", "privatelink", "unity_catalog"], "PrivateLink + Unity Catalog"),
        ]
        label = {"storage": "storage", "network": "network", "cross_account": "cross-account role",
                 "privatelink": "VPC endpoints", "unity_catalog": "Unity Catalog"}

        for mode_name, areas, description in modes:
            states = {a: st.get(a, "NOT_TESTED") for a in areas}
            failed = [label[a] for a, s in states.items() if s == "FAIL"]
            not_tested = [label[a] for a, s in states.items() if s == "NOT_TESTED"]
            review = [label[a] for a, s in states.items() if s == "REVIEW"]
            if failed:
                category.add_result(CheckResult(
                    name=f"  {mode_name}", status=CheckStatus.NOT_OK,
                    message=f"NOT SUPPORTED - missing: {', '.join(failed)}",
                    remediation=f"Grant the permissions flagged above for: {', '.join(failed)}.",
                ))
            elif not_tested:
                category.add_result(CheckResult(
                    name=f"  {mode_name}", status=CheckStatus.WARNING,
                    message=f"NOT VERIFIED - could not confirm: {', '.join(not_tested)} (IAM simulation unavailable, --verify-only, or no target resource)",
                    remediation="Re-run without --verify-only, grant iam:SimulatePrincipalPolicy, or pass the relevant target to confirm.",
                ))
            elif review:
                category.add_result(CheckResult(
                    name=f"  {mode_name}", status=CheckStatus.WARNING,
                    message=f"REVIEW - permissions verified; advisories to review in: {', '.join(review)} (no blockers). See the items flagged above.",
                    remediation=f"Review the flagged {', '.join(review)} item(s) above before deploying; none is a hard blocker.",
                ))
            else:
                category.add_result(CheckResult(
                    name=f"  {mode_name}", status=CheckStatus.OK,
                    message=f"SUPPORTED - {description}",
                ))
        return category
    
    def check_kms(self) -> CheckCategory:
        """Check permissions to create Customer-Managed Keys (CMK).

        The Databricks Security Reference Architecture (SRA) ALWAYS creates KMS
        keys (workspace storage + managed services, plus a per-workspace Unity
        Catalog key). KMS CreateKey has no DryRun, and a real KMS key cannot be
        deleted immediately (7-day minimum), so we verify via IAM policy
        simulation rather than by creating one. If simulation is unavailable we
        say so honestly instead of silently passing.
        """
        category = CheckCategory(name="STEP 5: CMK / KMS (Customer-Managed Keys)")

        # Core actions an SRA CMK deploy needs (cmk.tf: CreateKey/Alias/PutKeyPolicy
        # /CreateGrant + destroy path). CreateKey/CreateAlias are not DryRun-able.
        kms_actions = [
            "kms:CreateKey", "kms:CreateAlias", "kms:PutKeyPolicy",
            "kms:CreateGrant", "kms:DescribeKey", "kms:GetKeyPolicy",
            "kms:TagResource", "kms:ScheduleKeyDeletion", "kms:DeleteAlias",
        ]

        category.add_result(CheckResult(
            name="── CMK readiness ──",
            status=CheckStatus.OK,
            message="Required when using customer-managed keys (always-on in the Databricks SRA)",
        ))

        if not self._can_simulate:
            category.add_result(CheckResult(
                name="  KMS permissions",
                status=CheckStatus.WARNING,
                message=(
                    "Could not verify (IAM simulation unavailable, and KMS CreateKey "
                    "has no DryRun). If deploying with CMK, ensure these are granted: "
                    + ", ".join(kms_actions)
                ),
                remediation=(
                    "Grant the listed kms:* actions to the deploying principal, or "
                    "skip CMK if your deployment does not use customer-managed keys."
                ),
            ))
            return category

        results = self._simulate_actions(kms_actions)
        denied = [a for a, (s, _m) in results.items() if s == "denied"]
        for action in kms_actions:
            status_msg = results.get(action, ("skip", "not evaluated"))
            s, m = status_msg
            if s == "allowed":
                category.add_result(CheckResult(name=f"  {action}", status=CheckStatus.OK, message="Allowed"))
            elif s == "denied":
                category.add_result(CheckResult(
                    name=f"  {action}", status=CheckStatus.NOT_OK, message=f"DENIED: {m}",
                    remediation="Add this kms action to the deploying principal's policy.",
                ))
            else:
                category.add_result(CheckResult(name=f"  {action}", status=CheckStatus.WARNING, message=m))

        if not denied:
            category.add_result(CheckResult(
                name="  CMK summary", status=CheckStatus.OK,
                message=f"All {len(kms_actions)} KMS actions allowed",
            ))
        return category

    def check_account_api_scope_note(self) -> CheckCategory:
        """Explicitly record what this pre-check does NOT validate, so a green
        run is never mistaken for 'terraform apply will succeed'."""
        category = CheckCategory(name="NOT VALIDATED BY THIS PRE-CHECK (read this)")
        category.add_result(CheckResult(
            name="Databricks account-console registration",
            status=CheckStatus.SKIPPED,
            message=(
                "databricks_mws_* (credentials, storage, networks, workspaces, "
                "vpc_endpoint, customer_managed_keys, private_access_settings, NCC) "
                "need a Databricks account-admin token - not covered here"
            ),
            remediation="Confirm account-admin access + per-region NCC quota in the Databricks account console.",
        ))
        category.add_result(CheckResult(
            name="IAM/bucket policy CONTENT",
            status=CheckStatus.SKIPPED,
            message=(
                "We prove you CAN create the role/bucket policy, not that the trust "
                "principal (414351767826) + ExternalId = your Databricks account ID are correct"
            ),
        ))
        return category


    @staticmethod
    def _egress_covers_port(rules: list, port: int) -> bool:
        """True if any rule allows TCP `port` (or all-traffic)."""
        for r in rules:
            proto = r.get("IpProtocol")
            if proto == "-1":
                return True
            if proto == "tcp":
                fp, tp = r.get("FromPort"), r.get("ToPort")
                if fp is not None and tp is not None and fp <= port <= tp:
                    return True
        return False

    @staticmethod
    def _has_self_all_traffic(rules: list, sg_id: str) -> bool:
        """True if a rule allows broad intra-SG traffic (self-referencing)."""
        for r in rules:
            if sg_id not in [g.get("GroupId") for g in r.get("UserIdGroupPairs", [])]:
                continue
            proto = r.get("IpProtocol")
            if proto == "-1":
                return True
            if proto in ("tcp", "udp") and r.get("FromPort") == 0 and r.get("ToPort") == 65535:
                return True
        return False

    def check_security_group_rules(self) -> CheckCategory:
        """Validate the rules of an EXISTING security group (--sg-id).

        Databricks workspace SGs need intra-SG (self) all-traffic for internode
        communication, plus egress to the control plane (443/3306/6666). A
        PrivateLink/SRA SG instead scopes those ports to the VPC CIDR and omits
        self-all — so missing self-all is a WARNING (mode-dependent), missing
        egress ports is a stronger signal.
        """
        category = CheckCategory(name="SECURITY GROUP RULES (provided SG)")
        ec2 = self._get_client("ec2")
        try:
            sg = ec2.describe_security_groups(GroupIds=[self.sg_id])["SecurityGroups"][0]
        except Exception as e:
            category.add_result(CheckResult(
                name=f"  {self.sg_id}",
                status=CheckStatus.NOT_OK if is_access_denied(e) else CheckStatus.WARNING,
                message=f"Could not read SG: {str(e)[:80]}",
            ))
            return category

        ingress = sg.get("IpPermissions", [])
        egress = sg.get("IpPermissionsEgress", [])
        category.add_result(CheckResult(
            name=f"  {self.sg_id}", status=CheckStatus.OK,
            message=f"{sg.get('GroupName', '')} in {sg.get('VpcId', '')}",
        ))

        # Cross-check the SG lives in the target VPC, if one was given.
        if self.vpc_id and sg.get("VpcId") and sg["VpcId"] != self.vpc_id:
            category.add_result(CheckResult(
                name="  SG / VPC mismatch",
                status=CheckStatus.NOT_OK,
                message=f"SG {self.sg_id} is in {sg['VpcId']} but --vpc-id is {self.vpc_id}",
                remediation="Pass a security group that belongs to the target VPC.",
            ))

        # Intra-SG self all-traffic (internode communication)
        in_self = self._has_self_all_traffic(ingress, self.sg_id)
        eg_self = self._has_self_all_traffic(egress, self.sg_id)
        category.add_result(CheckResult(
            name="  Intra-SG ingress (self, all traffic)",
            status=CheckStatus.OK if in_self else CheckStatus.WARNING,
            message="Present" if in_self else "Missing - classic workspaces need all TCP+UDP from self (PrivateLink SGs may scope to CIDR instead)",
            remediation=None if in_self else "Add an inbound rule: all TCP + all UDP, source = this same security group.",
        ))
        category.add_result(CheckResult(
            name="  Intra-SG egress (self, all traffic)",
            status=CheckStatus.OK if eg_self else CheckStatus.WARNING,
            message="Present" if eg_self else "Missing - classic workspaces need all TCP+UDP to self",
            remediation=None if eg_self else "Add an outbound rule: all TCP + all UDP, destination = this same security group.",
        ))

        # Egress to the Databricks control plane
        for port, label in [(443, "HTTPS"), (3306, "Legacy metastore"), (6666, "Secure Cluster Connectivity")]:
            ok = self._egress_covers_port(egress, port)
            category.add_result(CheckResult(
                name=f"  Egress tcp/{port} ({label})",
                status=CheckStatus.OK if ok else CheckStatus.WARNING,
                message="Allowed" if ok else f"No egress rule covers tcp/{port}",
                remediation=None if ok else f"Add outbound TCP {port} (to 0.0.0.0/0, the workspace VPC CIDR, or self).",
            ))
        return category

    def run_all_checks(self) -> CheckReport:
        """Run all AWS checks for Databricks deployment.
        
        Runs every check category unconditionally and produces a deployment
        compatibility matrix at the end.
        """
        self._report = CheckReport(
            cloud=self.cloud_name,
            region=self.region or "default"
        )
        
        cred_category = self.check_credentials()
        self._report.add_category(cred_category)
        
        self._report.region = self.region or "us-east-1"
        
        credentials_ok = all(
            r.status in (CheckStatus.OK, CheckStatus.WARNING) 
            for r in cred_category.results
        )
        
        if credentials_ok:
          # try/finally guarantees temp resources are cleaned up even if a check
          # raises mid-run (otherwise an exception leaks the bucket/role/SG).
          try:
            storage_cat = self.check_storage_configuration()
            self._check_results_by_area["storage"] = storage_cat.area_state
            self._report.add_category(storage_cat)

            self._report.add_category(self.check_network_configuration())
            if self.sg_id:
                self._report.add_category(self.check_security_group_rules())
            self._report.add_category(self.check_cross_account_role())
            self._report.add_category(self.check_privatelink())
            self._report.add_category(self.check_unity_catalog())

            # Delete temp bucket after Unity Catalog used it
            delete_results = self._delete_temp_bucket()
            if delete_results:
                for r in delete_results:
                    storage_cat.add_result(r)

            # CMK/KMS — always-on in the SRA; previously unchecked, so a deploy
            # that needs CMK could pass here and then abort at the first KMS key.
            self._report.add_category(self.check_kms())

            self._report.add_category(self.check_quotas())

            self._report.add_category(self._compute_deployment_compatibility())

            # Be explicit about what a cloud-credential pre-check cannot prove.
            self._report.add_category(self.check_account_api_scope_note())
          finally:
            if self.skip_cleanup:
                # Resources were intentionally left in place (--skip-cleanup).
                cleanup_cat = CheckCategory(name="CLEANUP")
                cleanup_cat.add_result(CheckResult(
                    name="  ⏭️  Cleanup skipped (--skip-cleanup)",
                    status=CheckStatus.WARNING,
                    message=(
                        "Temporary test resources were intentionally LEFT in place. "
                        "Remove them manually or run --cleanup-orphans."
                    ),
                    remediation=(
                        f"Run: --cleanup-orphans --cloud aws --region {self.region}"
                    ),
                ))
                self._report.add_category(cleanup_cat)
            else:
                cleanup_failures = self._cleanup_test_resources()
                if cleanup_failures:
                    cleanup_cat = CheckCategory(name="CLEANUP")
                    for res_name, err in cleanup_failures:
                        cleanup_cat.add_result(CheckResult(
                            name=f"  ⚠️  Leaked resource: {res_name}",
                            status=CheckStatus.NOT_OK,
                            message=f"Automatic deletion FAILED — delete it manually. ({err[:80]})",
                            remediation=(
                                f"Delete '{res_name}' manually, or run: "
                                f"--cleanup-orphans --cloud aws --region {self.region}"
                            ),
                        ))
                    self._report.add_category(cleanup_cat)
        else:
            for name in ["STORAGE CONFIGURATION", "NETWORK CONFIGURATION",
                        "CROSS-ACCOUNT ROLE", "VPC ENDPOINTS (PrivateLink)",
                        "UNITY CATALOG", "QUOTAS & LIMITS"]:
                cat = CheckCategory(name=name)
                cat.add_result(CheckResult(
                    name="All checks",
                    status=CheckStatus.SKIPPED,
                    message="Skipped - credential failure"
                ))
                self._report.add_category(cat)
        
        return self._report
