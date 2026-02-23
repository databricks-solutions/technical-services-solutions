"""AWS checker for Databricks Terraform Pre-Check.

Runs all permission checks and reports which deployment types are supported
based on the detected permissions. No deployment mode selection required.
"""

import uuid
import time
import json
import logging
from typing import Optional, List, Dict, Any, Callable, Tuple

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
    ):
        super().__init__(region)
        self.profile = profile
        self.verify_only = verify_only
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
        """Clean up any temporary resources created during testing."""
        for cleanup_func, resource_name in reversed(self._cleanup_tasks):
            try:
                cleanup_func()
            except Exception:
                pass  # Best effort cleanup
        self._cleanup_tasks = []
    
    # =========================================================================
    # REAL RESOURCE TESTING (Create & Delete)
    # This is how we verify permissions without iam:SimulatePrincipalPolicy
    # =========================================================================
    
    def _test_s3_bucket_permissions(self) -> List[CheckResult]:
        """
        Test S3 permissions by creating a real bucket and testing operations.
        Returns list of CheckResults for each operation tested.
        """
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
            results.append(CheckResult(
                name="  s3:CreateBucket",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {bucket_name}"
            ))
            
            # Schedule cleanup
            self._cleanup_tasks.append((
                lambda: s3.delete_bucket(Bucket=bucket_name),
                bucket_name
            ))
            
        except Exception as e:
            error = str(e)
            if "AccessDenied" in error or "is not authorized" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            except:
                pass
                
        except Exception as e:
            error = str(e)
            if "AccessDenied" in error or "is not authorized" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
        
        # Clean up any leftover objects before deleting the bucket
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
            if "AccessDenied" in error or "is not authorized" in error:
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
        
        # Trust policy for Databricks
        trust_policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{self._account_id}:root"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"sts:ExternalId": "precheck-test"}}
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
            results.append(CheckResult(
                name="  iam:CreateRole",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {role_name}"
            ))
            
        except Exception as e:
            error = str(e)
            if "AccessDenied" in error or "is not authorized" in error:
                results.append(CheckResult(
                    name="  iam:CreateRole",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            elif "EntityAlreadyExists" in error:
                role_created = True
                results.append(CheckResult(
                    name="  iam:CreateRole",
                    status=CheckStatus.OK,
                    message="VERIFIED - Role exists (permission OK)"
                ))
            else:
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
            if "AccessDenied" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            except:
                pass
                
        except Exception as e:
            error = str(e)
            if "AccessDenied" in error or "is not authorized" in error:
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
            except:
                pass
            
            # Delete inline policies
            try:
                inline = iam.list_role_policies(RoleName=role_name)
                for policy_name in inline.get('PolicyNames', []):
                    iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
            except:
                pass
            
            iam.delete_role(RoleName=role_name)
            results.append(CheckResult(
                name="  🗑️  iam:DeleteRole",
                status=CheckStatus.OK,
                message=f"✓ DELETED: {role_name}"
            ))
        except Exception as e:
            error = str(e)
            if "AccessDenied" in error or "is not authorized" in error:
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
            results.append(CheckResult(
                name="  iam:CreatePolicy",
                status=CheckStatus.OK,
                message=f"✓ CREATED: {policy_arn}"
            ))
            
        except Exception as e:
            error = str(e)
            if "AccessDenied" in error or "is not authorized" in error:
                results.append(CheckResult(
                    name="  iam:CreatePolicy",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            elif "EntityAlreadyExists" in error:
                # Get existing policy ARN
                policy_arn = f"arn:aws:iam::{self._account_id}:policy/{policy_name}"
                results.append(CheckResult(
                    name="  iam:CreatePolicy",
                    status=CheckStatus.OK,
                    message="VERIFIED - Policy exists (permission OK)"
                ))
            else:
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
            if "AccessDenied" in error:
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
            if "AccessDenied" in error or "is not authorized" in error:
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
            except:
                pass
            
            iam.delete_policy(PolicyArn=policy_arn)
            results.append(CheckResult(
                name="  🗑️  iam:DeletePolicy",
                status=CheckStatus.OK,
                message=f"✓ DELETED: {policy_arn}"
            ))
        except Exception as e:
            error = str(e)
            if "AccessDenied" in error or "is not authorized" in error:
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
        results = []
        ec2 = self._get_client("ec2")
        sg_name = self._get_test_resource_name("sg")
        sg_id = None
        
        # Get a VPC to use for testing
        if not vpc_id:
            try:
                vpcs = ec2.describe_vpcs(Filters=[{'Name': 'is-default', 'Values': ['true']}])
                if vpcs.get('Vpcs'):
                    vpc_id = vpcs['Vpcs'][0]['VpcId']
                else:
                    # Get any VPC
                    vpcs = ec2.describe_vpcs(MaxResults=1)
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
            results.append(CheckResult(
                name="  ec2:CreateSecurityGroup",
                status=CheckStatus.OK,
                message=f"VERIFIED - Created test SG: {sg_id}"
            ))
            
        except Exception as e:
            error = str(e)
            if "UnauthorizedOperation" in error or "AccessDenied" in error or "is not authorized" in error:
                results.append(CheckResult(
                    name="  ec2:CreateSecurityGroup",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
            elif "InvalidGroup.Duplicate" in error:
                # SG already exists - find it
                try:
                    sgs = ec2.describe_security_groups(
                        Filters=[{'Name': 'group-name', 'Values': [sg_name]}]
                    )
                    if sgs.get('SecurityGroups'):
                        sg_id = sgs['SecurityGroups'][0]['GroupId']
                        results.append(CheckResult(
                            name="  ec2:CreateSecurityGroup",
                            status=CheckStatus.OK,
                            message="VERIFIED - SG exists (permission OK)"
                        ))
                except:
                    pass
            else:
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
            if "UnauthorizedOperation" in error or "AccessDenied" in error or "is not authorized" in error:
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
            if "UnauthorizedOperation" in error or "AccessDenied" in error or "is not authorized" in error:
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
            if "UnauthorizedOperation" in error or "AccessDenied" in error or "is not authorized" in error:
                results.append(CheckResult(
                    name="  ec2:RevokeSecurityGroupIngress",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {error}"
                ))
        
        # CLEANUP: Delete the test security group
        try:
            ec2.delete_security_group(GroupId=sg_id)
            results.append(CheckResult(
                name="  🗑️  ec2:DeleteSecurityGroup",
                status=CheckStatus.OK,
                message=f"✓ DELETED: {sg_id} ({sg_name})"
            ))
        except Exception as e:
            error = str(e)
            if "UnauthorizedOperation" in error or "AccessDenied" in error or "is not authorized" in error:
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
                    response = iam.simulate_principal_policy(
                        PolicySourceArn=self._user_arn,
                        ActionNames=batch,
                        ResourceArns=[resource] if resource else ["*"]
                    )
                    
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
                    error_msg = str(e)
                    for action in batch:
                        results[action] = ("error", error_msg)
                        
        except Exception as e:
            error_msg = str(e)
            for action in actions:
                results[action] = ("error", error_msg)
        
        return results
    
    def _test_dryrun(
        self, 
        action_name: str, 
        test_func: Callable,
        success_patterns: List[str] = None,
        permission_patterns: List[str] = None,
    ) -> Tuple[CheckStatus, str]:
        """
        Test an action using DryRun.
        Returns (status, detailed_message)
        """
        success_patterns = success_patterns or ["DryRunOperation"]
        permission_patterns = permission_patterns or ["UnauthorizedOperation", "AccessDenied", "is not authorized"]
        
        try:
            test_func()
            # If no exception, unexpected success
            return (CheckStatus.OK, "Allowed (unexpected actual success)")
        except Exception as e:
            error_str = str(e)
            error_code = getattr(e, 'response', {}).get('Error', {}).get('Code', '')
            
            # Check for DryRun success (means permission is granted)
            for pattern in success_patterns:
                if pattern in error_str or pattern == error_code:
                    return (CheckStatus.OK, "Allowed (DryRun verified)")
            
            # Check for permission denied
            for pattern in permission_patterns:
                if pattern in error_str:
                    # Extract the specific denial message
                    if "is not authorized to perform" in error_str:
                        # Parse the specific action and resource
                        parts = error_str.split("is not authorized to perform:")
                        if len(parts) > 1:
                            denied_action = parts[1].split(" on ")[0].strip()
                            return (CheckStatus.NOT_OK, f"DENIED: {denied_action}")
                    return (CheckStatus.NOT_OK, f"DENIED: {error_str[:100]}")
            
            # Check for resource-not-found errors (means permission exists but resource doesn't)
            not_found_patterns = [
                "InvalidVpcID", "InvalidSubnet", "InvalidGroup",
                "InvalidAMIID", "NoSuchEntity", "InvalidParameterValue",
                "InvalidVpcId", "MalformedAMIID", "InvalidGroupId",
                "InvalidInstanceID", "InvalidID", "InvalidVolume",
                "InvalidAddress", "InvalidRoute", "InvalidEndpoint",
                "Malformed",
            ]
            for pattern in not_found_patterns:
                if pattern in error_str or pattern == error_code:
                    return (CheckStatus.OK, "Allowed (resource doesn't exist)")
            
            # Unknown error - return full message for debugging
            return (CheckStatus.WARNING, f"Check failed: {error_str}")
    
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
                    status=CheckStatus.WARNING,
                    message="Cannot simulate - using DryRun API calls"
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
                    status = CheckStatus.OK if status_str == "allowed" else CheckStatus.WARNING
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
                    status = CheckStatus.OK if status_str == "allowed" else CheckStatus.WARNING
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
                vpcs = ec2.describe_vpcs(MaxResults=1)
                if vpcs.get("Vpcs"):
                    vpc_id = vpcs["Vpcs"][0]["VpcId"]
                    ec2.describe_vpc_attribute(VpcId=vpc_id, Attribute='enableDnsHostnames')
                    category.add_result(CheckResult(
                        name="  ec2:DescribeVpcAttribute",
                        status=CheckStatus.OK,
                        message="Allowed - Can check VPC DNS settings"
                    ))
            except Exception as e:
                if "AccessDenied" in str(e):
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
            subnets = ec2.describe_subnets()
            subnet_list = subnets.get("Subnets", [])
            
            private = sum(1 for s in subnet_list if not s.get("MapPublicIpOnLaunch", False))
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
            
            azs = set(s["AvailabilityZone"] for s in subnet_list if not s.get("MapPublicIpOnLaunch", False))
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
            status, msg = self._test_dryrun(
                "ec2:CreateSecurityGroup",
                lambda: ec2.create_security_group(
                    GroupName="databricks-test",
                    Description="test",
                    VpcId="vpc-test",
                    DryRun=True
                ),
            )
            category.add_result(CheckResult(name="  ec2:CreateSecurityGroup (DryRun)", status=status, message=msg))
            
            if self._can_simulate:
                sg_actions = ["ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
                             "ec2:RevokeSecurityGroupIngress", "ec2:DeleteSecurityGroup"]
                results = self._simulate_actions(sg_actions)
                for action in sg_actions:
                    status_str, message = results.get(action, ("error", "Unknown"))
                    status = CheckStatus.OK if status_str == "allowed" else CheckStatus.WARNING
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
            sg_results = self._test_security_group_permissions()
            for result in sg_results:
                category.add_result(result)
        
        self._check_results_by_area["network"] = network_ok
        
        return category
    
    def check_privatelink(self) -> CheckCategory:
        """Check permissions for VPC Endpoints / PrivateLink connectivity."""
        category = CheckCategory(name="VPC ENDPOINTS (PrivateLink)")
        
        ec2 = self._get_client("ec2")
        privatelink_ok = True
        
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
                    privatelink_ok = False
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
                privatelink_ok = False
                category.add_result(CheckResult(
                    name="  ec2:DescribeVpcEndpoints",
                    status=CheckStatus.NOT_OK,
                    message=f"DENIED: {str(e)}"
                ))
            
            status, msg = self._test_dryrun(
                "ec2:CreateVpcEndpoint",
                lambda: ec2.create_vpc_endpoint(
                    VpcId="vpc-test",
                    ServiceName=f"com.amazonaws.{self.region}.s3",
                    VpcEndpointType='Gateway',
                    DryRun=True
                ),
            )
            if status == CheckStatus.NOT_OK:
                privatelink_ok = False
            category.add_result(CheckResult(name="  ec2:CreateVpcEndpoint", status=status, message=msg))
        
        try:
            endpoints = ec2.describe_vpc_endpoints()
            endpoint_list = endpoints.get("VpcEndpoints", [])
            
            gateway = sum(1 for e in endpoint_list if e["VpcEndpointType"] == "Gateway")
            interface = sum(1 for e in endpoint_list if e["VpcEndpointType"] == "Interface")
            
            category.add_result(CheckResult(
                name="  Existing VPC Endpoints",
                status=CheckStatus.OK,
                message=f"{gateway} Gateway, {interface} Interface endpoints"
            ))
            
            s3_gw = [e for e in endpoint_list if "s3" in e.get("ServiceName", "").lower() and e["VpcEndpointType"] == "Gateway"]
            if s3_gw:
                category.add_result(CheckResult(
                    name="  S3 Gateway Endpoint",
                    status=CheckStatus.OK,
                    message=f"Found: {s3_gw[0]['VpcEndpointId']}"
                ))
            else:
                category.add_result(CheckResult(
                    name="  S3 Gateway Endpoint",
                    status=CheckStatus.WARNING,
                    message="Not found - recommended for cost savings"
                ))
            
            sts_ep = [e for e in endpoint_list if "sts" in e.get("ServiceName", "").lower()]
            if sts_ep:
                category.add_result(CheckResult(
                    name="  STS Interface Endpoint",
                    status=CheckStatus.OK,
                    message=f"Found: {sts_ep[0]['VpcEndpointId']}"
                ))
            else:
                category.add_result(CheckResult(
                    name="  STS Interface Endpoint",
                    status=CheckStatus.WARNING,
                    message="Not found - required for PrivateLink deployments"
                ))
                
        except Exception as e:
            category.add_result(CheckResult(
                name="  VPC Endpoints",
                status=CheckStatus.WARNING,
                message=f"Cannot list: {str(e)[:40]}"
            ))
        
        self._check_results_by_area["privatelink"] = privatelink_ok
        
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
            # DryRun tests for critical EC2 actions
            
            # RunInstances
            status, msg = self._test_dryrun(
                "ec2:RunInstances",
                lambda: ec2.run_instances(
                    ImageId="ami-12345678",
                    MinCount=1,
                    MaxCount=1,
                    InstanceType="t3.micro",
                    DryRun=True
                ),
            )
            category.add_result(CheckResult(name="  ec2:RunInstances", status=status, message=msg))
            
            # TerminateInstances
            status, msg = self._test_dryrun(
                "ec2:TerminateInstances",
                lambda: ec2.terminate_instances(InstanceIds=["i-test12345"], DryRun=True),
            )
            category.add_result(CheckResult(name="  ec2:TerminateInstances", status=status, message=msg))
            
            # CreateVolume
            status, msg = self._test_dryrun(
                "ec2:CreateVolume",
                lambda: ec2.create_volume(
                    AvailabilityZone=f"{self.region}a",
                    Size=10,
                    VolumeType='gp3',
                    DryRun=True
                ),
            )
            category.add_result(CheckResult(name="  ec2:CreateVolume", status=status, message=msg))
            
            # DeleteVolume
            status, msg = self._test_dryrun(
                "ec2:DeleteVolume",
                lambda: ec2.delete_volume(VolumeId="vol-test12345", DryRun=True),
            )
            category.add_result(CheckResult(name="  ec2:DeleteVolume", status=status, message=msg))
            
            # CreateSecurityGroup
            status, msg = self._test_dryrun(
                "ec2:CreateSecurityGroup",
                lambda: ec2.create_security_group(
                    GroupName="databricks-test",
                    Description="test",
                    VpcId="vpc-test",
                    DryRun=True
                ),
            )
            category.add_result(CheckResult(name="  ec2:CreateSecurityGroup", status=status, message=msg))
            
            # CreateTags
            status, msg = self._test_dryrun(
                "ec2:CreateTags",
                lambda: ec2.create_tags(
                    Resources=["i-test12345"],
                    Tags=[{"Key": "test", "Value": "test"}],
                    DryRun=True
                ),
            )
            category.add_result(CheckResult(name="  ec2:CreateTags", status=status, message=msg))
            
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
            status, msg = self._test_dryrun(
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
        
        self._check_results_by_area["cross_account"] = (category.not_ok_count == 0)
        
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
            ("sts:AssumeRole", "Assume storage credential role"),
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
            category.add_result(CheckResult(
                name="  sts:AssumeRole",
                status=CheckStatus.WARNING,
                message="Requires target role ARN - tested via cross-account checks"
            ))
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
            category.add_result(CheckResult(
                name="  File Events",
                status=CheckStatus.WARNING,
                message="Cannot test SNS/SQS permissions without simulation"
            ))
        
        self._check_results_by_area["unity_catalog"] = (category.not_ok_count == 0)
        
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
            
            limits = {}
            for key, (service, code, name) in quota_codes.items():
                try:
                    response = sq.get_service_quota(ServiceCode=service, QuotaCode=code)
                    limits[key] = int(response.get("Quota", {}).get("Value", 0))
                except Exception:
                    defaults = {"vpc": 5, "eip": 5, "igw": 5, "natgw": 5, "sg": 2500, "vcpu": 256}
                    limits[key] = defaults.get(key, 5)
            
            # VPCs
            vpcs = ec2.describe_vpcs()
            vpc_count = len(vpcs.get("Vpcs", []))
            vpc_limit = limits.get("vpc", 5)
            pct = (vpc_count / vpc_limit * 100) if vpc_limit > 0 else 0
            
            if pct >= 100:
                status = CheckStatus.NOT_OK
                msg = f"{vpc_count}/{vpc_limit} - AT LIMIT! Request increase before deployment"
            elif pct >= 80:
                status = CheckStatus.WARNING
                msg = f"{vpc_count}/{vpc_limit} ({pct:.0f}%) - approaching limit"
            else:
                status = CheckStatus.OK
                msg = f"{vpc_count}/{vpc_limit} ({pct:.0f}%)"
            
            category.add_result(CheckResult(name="  VPCs", status=status, message=msg))
            
            # Elastic IPs
            eips = ec2.describe_addresses()
            eip_count = len(eips.get("Addresses", []))
            eip_limit = limits.get("eip", 5)
            pct = (eip_count / eip_limit * 100) if eip_limit > 0 else 0
            
            if pct >= 100:
                status = CheckStatus.NOT_OK
                msg = f"{eip_count}/{eip_limit} - AT LIMIT!"
            elif pct >= 80:
                status = CheckStatus.WARNING
                msg = f"{eip_count}/{eip_limit} ({pct:.0f}%) - approaching limit"
            else:
                status = CheckStatus.OK
                msg = f"{eip_count}/{eip_limit} ({pct:.0f}%)"
            
            category.add_result(CheckResult(name="  Elastic IPs", status=status, message=msg))
            
            # NAT Gateways
            nats = ec2.describe_nat_gateways(Filters=[{"Name": "state", "Values": ["available"]}])
            nat_count = len(nats.get("NatGateways", []))
            nat_limit = limits.get("natgw", 5)
            pct = (nat_count / nat_limit * 100) if nat_limit > 0 else 0
            
            if pct >= 100:
                status = CheckStatus.NOT_OK
            elif pct >= 80:
                status = CheckStatus.WARNING
            else:
                status = CheckStatus.OK
            
            category.add_result(CheckResult(name="  NAT Gateways", status=status, message=f"{nat_count}/{nat_limit} ({pct:.0f}%)"))
            
            # vCPU quota
            vcpu_limit = limits.get("vcpu", 256)
            category.add_result(CheckResult(
                name="  EC2 On-Demand vCPUs",
                status=CheckStatus.OK,
                message=f"Limit: {vcpu_limit} vCPUs"
            ))
            
            # Security Groups
            sg_limit = limits.get("sg", 2500)
            category.add_result(CheckResult(
                name="  Security Groups per VPC",
                status=CheckStatus.OK,
                message=f"Limit: {sg_limit}"
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
    
    def generate_suggested_policy(self, report: CheckReport) -> Dict[str, Any]:
        """
        Generate a suggested IAM policy based on failed permission checks.
        Returns a dict that can be serialized to JSON.
        """
        denied_actions = set()
        
        # Collect all denied actions from the report
        for category in report.categories:
            for result in category.results:
                if result.status == CheckStatus.NOT_OK:
                    # Extract action name from result name (e.g., "  s3:CreateBucket" -> "s3:CreateBucket")
                    action_name = result.name.strip()
                    if ":" in action_name and not action_name.startswith("──"):
                        denied_actions.add(action_name)
        
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
        
        # S3 permissions
        if "s3" in services:
            statements.append({
                "Sid": "DatabricksS3Access",
                "Effect": "Allow",
                "Action": sorted(services["s3"]),
                "Resource": [
                    "arn:aws:s3:::databricks-*",
                    "arn:aws:s3:::databricks-*/*"
                ]
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
        """Compute which deployment types are supported based on check results."""
        category = CheckCategory(name="DEPLOYMENT COMPATIBILITY")
        
        storage_ok = self._check_results_by_area.get("storage", True)
        network_ok = self._check_results_by_area.get("network", True)
        cross_account_ok = self._check_results_by_area.get("cross_account", True)
        privatelink_ok = self._check_results_by_area.get("privatelink", True)
        unity_ok = self._check_results_by_area.get("unity_catalog", True)
        
        base_ok = storage_ok and network_ok and cross_account_ok
        
        modes = [
            ("Standard", base_ok,
             "Basic workspace (VPC, S3, IAM)"),
            ("PrivateLink", base_ok and privatelink_ok,
             "With VPC Endpoints for private connectivity"),
            ("Unity Catalog", base_ok and unity_ok,
             "With Unity Catalog storage credentials"),
            ("Full", base_ok and privatelink_ok and unity_ok,
             "All features (PrivateLink + Unity Catalog + CMK)"),
        ]
        
        for mode_name, supported, description in modes:
            if supported:
                category.add_result(CheckResult(
                    name=f"  {mode_name}",
                    status=CheckStatus.OK,
                    message=f"SUPPORTED - {description}"
                ))
            else:
                missing = []
                if not storage_ok:
                    missing.append("storage")
                if not network_ok:
                    missing.append("network")
                if not cross_account_ok:
                    missing.append("cross-account role")
                if mode_name in ("PrivateLink", "Full") and not privatelink_ok:
                    missing.append("VPC endpoints")
                if mode_name in ("Unity Catalog", "Full") and not unity_ok:
                    missing.append("Unity Catalog")
                
                category.add_result(CheckResult(
                    name=f"  {mode_name}",
                    status=CheckStatus.WARNING,
                    message=f"MISSING PERMISSIONS - Fix: {', '.join(missing)}"
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
            storage_cat = self.check_storage_configuration()
            self._check_results_by_area["storage"] = (storage_cat.not_ok_count == 0)
            self._report.add_category(storage_cat)
            
            self._report.add_category(self.check_network_configuration())
            self._report.add_category(self.check_cross_account_role())
            self._report.add_category(self.check_privatelink())
            self._report.add_category(self.check_unity_catalog())
            
            # Delete temp bucket after Unity Catalog used it
            delete_results = self._delete_temp_bucket()
            if delete_results:
                for r in delete_results:
                    storage_cat.add_result(r)
            
            self._report.add_category(self.check_quotas())
            
            self._report.add_category(self._compute_deployment_compatibility())
            
            self._cleanup_test_resources()
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
