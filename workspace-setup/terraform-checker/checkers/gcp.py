"""GCP checker for Databricks Terraform Pre-Check."""

from typing import Optional, List, Dict

from .base import (
    BaseChecker,
    CheckCategory,
    CheckResult,
    CheckStatus,
    CheckReport,
)


class GCPChecker(BaseChecker):
    """Checker for GCP resources and permissions for Databricks deployment."""
    
    # ==========================================================================
    # DATABRICKS-SPECIFIC GCP PERMISSIONS
    # Based on Databricks documentation for GCP workspace deployment
    # ==========================================================================
    
    # Required IAM permissions for Databricks deployment
    DATABRICKS_REQUIRED_PERMISSIONS = {
        "compute": [
            "compute.instances.create",
            "compute.instances.delete",
            "compute.instances.get",
            "compute.instances.list",
            "compute.instances.setMetadata",
            "compute.instances.setServiceAccount",
            "compute.instances.setTags",
            "compute.instances.start",
            "compute.instances.stop",
            "compute.disks.create",
            "compute.disks.delete",
            "compute.disks.get",
            "compute.disks.list",
            "compute.networks.create",
            "compute.networks.delete",
            "compute.networks.get",
            "compute.networks.list",
            "compute.networks.updatePolicy",
            "compute.subnetworks.create",
            "compute.subnetworks.delete",
            "compute.subnetworks.get",
            "compute.subnetworks.list",
            "compute.subnetworks.use",
            "compute.subnetworks.useExternalIp",
            "compute.firewalls.create",
            "compute.firewalls.delete",
            "compute.firewalls.get",
            "compute.firewalls.list",
            "compute.firewalls.update",
            "compute.routers.create",
            "compute.routers.delete",
            "compute.routers.get",
            "compute.routers.list",
            "compute.routers.update",
            "compute.routes.create",
            "compute.routes.delete",
            "compute.routes.get",
            "compute.routes.list",
            # Private Google Access
            "compute.subnetworks.setPrivateIpGoogleAccess",
            # NAT
            "compute.routers.update",
        ],
        "storage": [
            "storage.buckets.create",
            "storage.buckets.delete",
            "storage.buckets.get",
            "storage.buckets.list",
            "storage.buckets.update",
            "storage.objects.create",
            "storage.objects.delete",
            "storage.objects.get",
            "storage.objects.list",
            "storage.objects.update",
        ],
        "iam": [
            "iam.serviceAccounts.create",
            "iam.serviceAccounts.delete",
            "iam.serviceAccounts.get",
            "iam.serviceAccounts.list",
            "iam.serviceAccounts.actAs",
            "iam.serviceAccountKeys.create",
            "iam.serviceAccountKeys.delete",
            "iam.serviceAccountKeys.get",
            "iam.serviceAccountKeys.list",
            "iam.roles.get",
            "iam.roles.list",
        ],
        "resourcemanager": [
            "resourcemanager.projects.get",
            "resourcemanager.projects.getIamPolicy",
            "resourcemanager.projects.setIamPolicy",
        ],
        "kms": [
            "cloudkms.cryptoKeys.get",
            "cloudkms.cryptoKeys.list",
            "cloudkms.cryptoKeys.create",
            "cloudkms.cryptoKeyVersions.useToEncrypt",
            "cloudkms.cryptoKeyVersions.useToDecrypt",
            "cloudkms.keyRings.get",
            "cloudkms.keyRings.list",
            "cloudkms.keyRings.create",
        ],
        "logging": [
            "logging.logEntries.create",
            "logging.logEntries.list",
        ],
    }
    
    # Required APIs that must be enabled
    REQUIRED_APIS = [
        "compute.googleapis.com",
        "storage.googleapis.com",
        "iam.googleapis.com",
        "cloudresourcemanager.googleapis.com",
        "cloudkms.googleapis.com",
        "logging.googleapis.com",
        "container.googleapis.com",  # For GKE-based deployments
    ]
    
    def __init__(
        self, 
        region: str = None, 
        project_id: str = None,
        credentials_file: str = None,
    ):
        super().__init__(region)
        self.project_id = project_id
        self.credentials_file = credentials_file
        self._credentials = None
        self._project_info = None
    
    @property
    def cloud_name(self) -> str:
        return "GCP"
    
    def _get_credentials(self):
        """Get GCP credentials."""
        if self._credentials is None:
            try:
                import google.auth
                from google.auth import default as get_default_credentials
                from google.oauth2 import service_account
                
                if self.credentials_file:
                    self._credentials = service_account.Credentials.from_service_account_file(
                        self.credentials_file,
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                    if not self.project_id:
                        import json
                        with open(self.credentials_file, 'r') as f:
                            cred_data = json.load(f)
                            self.project_id = cred_data.get('project_id')
                else:
                    self._credentials, project = get_default_credentials(
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                    if not self.project_id:
                        self.project_id = project
                        
            except ImportError:
                raise ImportError(
                    "google-auth is required for GCP checks. "
                    "Install with: pip install google-auth"
                )
        return self._credentials
    
    def _get_compute_client(self):
        """Get Compute Engine client."""
        from googleapiclient import discovery
        return discovery.build(
            'compute', 'v1',
            credentials=self._get_credentials(),
            cache_discovery=False
        )
    
    def _get_storage_client(self):
        """Get Cloud Storage client."""
        from google.cloud import storage
        return storage.Client(
            project=self.project_id,
            credentials=self._get_credentials()
        )
    
    def _get_resource_manager_client(self):
        """Get Resource Manager client."""
        from googleapiclient import discovery
        return discovery.build(
            'cloudresourcemanager', 'v1',
            credentials=self._get_credentials(),
            cache_discovery=False
        )
    
    def _get_iam_client(self):
        """Get IAM client."""
        from googleapiclient import discovery
        return discovery.build(
            'iam', 'v1',
            credentials=self._get_credentials(),
            cache_discovery=False
        )
    
    def _get_service_usage_client(self):
        """Get Service Usage client for checking enabled APIs."""
        from googleapiclient import discovery
        return discovery.build(
            'serviceusage', 'v1',
            credentials=self._get_credentials(),
            cache_discovery=False
        )
    
    def check_credentials(self) -> CheckCategory:
        """Check GCP credentials validity."""
        category = CheckCategory(name="CREDENTIALS")
        
        try:
            credentials = self._get_credentials()
            
            # Test by getting project info
            try:
                rm_client = self._get_resource_manager_client()
                project = rm_client.projects().get(projectId=self.project_id).execute()
                
                self._project_info = {
                    "id": project.get("projectId"),
                    "name": project.get("name"),
                    "number": project.get("projectNumber"),
                    "state": project.get("lifecycleState"),
                }
                
                category.add_result(CheckResult(
                    name="GCP Credentials",
                    status=CheckStatus.OK,
                    message="Authenticated successfully"
                ))
                
                category.add_result(CheckResult(
                    name="Project",
                    status=CheckStatus.OK,
                    message=f"{project.get('name')}"
                ))
                
                category.add_result(CheckResult(
                    name="Project ID",
                    status=CheckStatus.OK,
                    message=project.get("projectId")
                ))
                
                category.add_result(CheckResult(
                    name="Project Number",
                    status=CheckStatus.OK,
                    message=project.get("projectNumber")
                ))
                
                if project.get("lifecycleState") != "ACTIVE":
                    category.add_result(CheckResult(
                        name="Project State",
                        status=CheckStatus.WARNING,
                        message=f"State is {project.get('lifecycleState')}"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="Project State",
                        status=CheckStatus.OK,
                        message="Active"
                    ))
                    
            except Exception as e:
                error_msg = str(e)
                if "403" in error_msg:
                    category.add_result(CheckResult(
                        name="Project Access",
                        status=CheckStatus.NOT_OK,
                        message="Permission denied to access project"
                    ))
                elif "404" in error_msg:
                    category.add_result(CheckResult(
                        name="Project Access",
                        status=CheckStatus.NOT_OK,
                        message=f"Project '{self.project_id}' not found"
                    ))
                else:
                    raise
            
            # Check region
            if self.region:
                category.add_result(CheckResult(
                    name="Region Configuration",
                    status=CheckStatus.OK,
                    message=self.region
                ))
            else:
                category.add_result(CheckResult(
                    name="Region Configuration",
                    status=CheckStatus.WARNING,
                    message="No region specified, will use us-central1"
                ))
                self.region = "us-central1"
                
        except ImportError as e:
            category.add_result(CheckResult(
                name="GCP SDK",
                status=CheckStatus.NOT_OK,
                message=str(e)
            ))
        except Exception as e:
            error_msg = str(e)
            if "Could not automatically determine credentials" in error_msg:
                message = "No GCP credentials found"
            elif "invalid_grant" in error_msg:
                message = "Credentials expired or revoked"
            else:
                message = error_msg[:100]
            
            category.add_result(CheckResult(
                name="GCP Credentials",
                status=CheckStatus.NOT_OK,
                message=message
            ))
        
        return category
    
    def check_apis(self) -> CheckCategory:
        """Check if required GCP APIs are enabled."""
        category = CheckCategory(name="REQUIRED APIS")
        
        try:
            su_client = self._get_service_usage_client()
            
            # Get list of enabled services
            try:
                parent = f"projects/{self.project_id}"
                response = su_client.services().list(
                    parent=parent,
                    filter="state:ENABLED"
                ).execute()
                
                enabled_services = [
                    s.get("config", {}).get("name", "")
                    for s in response.get("services", [])
                ]
                
                for api in self.REQUIRED_APIS:
                    if api in enabled_services:
                        category.add_result(CheckResult(
                            name=f"API: {api}",
                            status=CheckStatus.OK,
                            message="Enabled"
                        ))
                    else:
                        category.add_result(CheckResult(
                            name=f"API: {api}",
                            status=CheckStatus.NOT_OK,
                            message="Not enabled - run: gcloud services enable " + api
                        ))
                        
            except Exception as e:
                category.add_result(CheckResult(
                    name="API Check",
                    status=CheckStatus.WARNING,
                    message=f"Could not verify: {str(e)[:40]}"
                ))
                
        except Exception as e:
            category.add_result(CheckResult(
                name="Service Usage API",
                status=CheckStatus.WARNING,
                message=str(e)[:50]
            ))
        
        return category
    
    def check_iam_permissions(self) -> CheckCategory:
        """Check GCP IAM permissions for Databricks deployment."""
        category = CheckCategory(name="IAM PERMISSIONS (Databricks-specific)")
        
        try:
            rm_client = self._get_resource_manager_client()
            
            # Test IAM policy access
            try:
                policy = rm_client.projects().getIamPolicy(
                    resource=self.project_id,
                    body={}
                ).execute()
                
                bindings = policy.get("bindings", [])
                category.add_result(CheckResult(
                    name="IAM Policy Access",
                    status=CheckStatus.OK,
                    message=f"Found {len(bindings)} role binding(s)"
                ))
                
                # Check for common Databricks-required roles
                common_roles = [
                    "roles/editor",
                    "roles/owner",
                    "roles/compute.admin",
                    "roles/storage.admin",
                    "roles/iam.serviceAccountAdmin",
                ]
                
                found_roles = []
                for binding in bindings:
                    role = binding.get("role", "")
                    if role in common_roles:
                        found_roles.append(role)
                
                if found_roles:
                    category.add_result(CheckResult(
                        name="Admin Roles",
                        status=CheckStatus.OK,
                        message=f"Found: {', '.join(found_roles[:3])}"
                    ))
                    
            except Exception as e:
                if "403" in str(e):
                    category.add_result(CheckResult(
                        name="IAM Policy Access",
                        status=CheckStatus.WARNING,
                        message="Cannot read IAM policy (permission denied)"
                    ))
                else:
                    raise
            
            # Test permissions by trying actual API calls
            # Compute permissions
            try:
                compute = self._get_compute_client()
                compute.networks().list(project=self.project_id).execute()
                category.add_result(CheckResult(
                    name="Compute Permissions",
                    status=CheckStatus.OK,
                    message="Can list networks"
                ))
            except Exception as e:
                if "403" in str(e) or "accessNotConfigured" in str(e):
                    category.add_result(CheckResult(
                        name="Compute Permissions",
                        status=CheckStatus.NOT_OK,
                        message="Access denied or API not enabled"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="Compute Permissions",
                        status=CheckStatus.WARNING,
                        message=str(e)[:50]
                    ))
            
            # Storage permissions
            try:
                storage = self._get_storage_client()
                list(storage.list_buckets())
                category.add_result(CheckResult(
                    name="Storage Permissions",
                    status=CheckStatus.OK,
                    message="Can list buckets"
                ))
            except Exception as e:
                if "403" in str(e):
                    category.add_result(CheckResult(
                        name="Storage Permissions",
                        status=CheckStatus.NOT_OK,
                        message="Access denied"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="Storage Permissions",
                        status=CheckStatus.WARNING,
                        message=str(e)[:50]
                    ))
            
            # IAM permissions (service accounts)
            try:
                iam = self._get_iam_client()
                iam.projects().serviceAccounts().list(
                    name=f"projects/{self.project_id}"
                ).execute()
                category.add_result(CheckResult(
                    name="IAM Service Account Permissions",
                    status=CheckStatus.OK,
                    message="Can list service accounts"
                ))
            except Exception as e:
                if "403" in str(e):
                    category.add_result(CheckResult(
                        name="IAM Service Account Permissions",
                        status=CheckStatus.WARNING,
                        message="Cannot list service accounts"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="IAM Service Account Permissions",
                        status=CheckStatus.WARNING,
                        message=str(e)[:50]
                    ))
            
            # Test IAM permissions for specific actions
            try:
                # Use testIamPermissions API
                permissions_to_test = [
                    "compute.instances.create",
                    "compute.networks.create",
                    "compute.firewalls.create",
                    "storage.buckets.create",
                    "iam.serviceAccounts.create",
                ]
                
                response = rm_client.projects().testIamPermissions(
                    resource=self.project_id,
                    body={"permissions": permissions_to_test}
                ).execute()
                
                granted = response.get("permissions", [])
                missing = set(permissions_to_test) - set(granted)
                
                if not missing:
                    category.add_result(CheckResult(
                        name="Critical Permissions Test",
                        status=CheckStatus.OK,
                        message=f"All {len(permissions_to_test)} critical permissions granted"
                    ))
                elif len(missing) < len(permissions_to_test) // 2:
                    category.add_result(CheckResult(
                        name="Critical Permissions Test",
                        status=CheckStatus.WARNING,
                        message=f"{len(missing)} missing: {', '.join(list(missing)[:2])}"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="Critical Permissions Test",
                        status=CheckStatus.NOT_OK,
                        message=f"{len(missing)} permissions missing"
                    ))
                    
            except Exception as e:
                category.add_result(CheckResult(
                    name="Permission Test",
                    status=CheckStatus.WARNING,
                    message=f"Could not test: {str(e)[:40]}"
                ))
                    
        except Exception as e:
            category.add_result(CheckResult(
                name="IAM Check",
                status=CheckStatus.NOT_OK,
                message=str(e)
            ))
        
        return category
    
    def check_network(self) -> CheckCategory:
        """Check GCP network resources for Databricks."""
        category = CheckCategory(name="NETWORK (VPC for Databricks)")
        
        try:
            compute = self._get_compute_client()
            
            # Check VPC Networks
            try:
                networks = compute.networks().list(project=self.project_id).execute()
                network_list = networks.get("items", [])
                
                category.add_result(CheckResult(
                    name="VPC Network Access",
                    status=CheckStatus.OK,
                    message=f"Found {len(network_list)} network(s)"
                ))
                
                # Check network configurations
                for network in network_list[:3]:
                    name = network.get("name")
                    auto_create = network.get("autoCreateSubnetworks", False)
                    
                    if auto_create:
                        category.add_result(CheckResult(
                            name=f"Network: {name}",
                            status=CheckStatus.WARNING,
                            message="Auto-mode VPC - custom mode recommended for Databricks"
                        ))
                    else:
                        category.add_result(CheckResult(
                            name=f"Network: {name}",
                            status=CheckStatus.OK,
                            message="Custom mode VPC"
                        ))
                        
            except Exception as e:
                category.add_result(CheckResult(
                    name="VPC Network Access",
                    status=CheckStatus.NOT_OK,
                    message=str(e)[:50]
                ))
            
            # Check Subnetworks in region
            try:
                subnets = compute.subnetworks().list(
                    project=self.project_id,
                    region=self.region or "us-central1"
                ).execute()
                subnet_list = subnets.get("items", [])
                
                category.add_result(CheckResult(
                    name="Subnetwork Access",
                    status=CheckStatus.OK,
                    message=f"Found {len(subnet_list)} subnet(s) in {self.region}"
                ))
                
                # Check Private Google Access (required for Databricks)
                for subnet in subnet_list[:5]:
                    name = subnet.get("name")
                    pga = subnet.get("privateIpGoogleAccess", False)
                    
                    if pga:
                        category.add_result(CheckResult(
                            name=f"Subnet PGA: {name}",
                            status=CheckStatus.OK,
                            message="Private Google Access enabled"
                        ))
                    else:
                        category.add_result(CheckResult(
                            name=f"Subnet PGA: {name}",
                            status=CheckStatus.WARNING,
                            message="Private Google Access disabled - needed for Databricks"
                        ))
                        
            except Exception as e:
                category.add_result(CheckResult(
                    name="Subnetwork Access",
                    status=CheckStatus.NOT_OK,
                    message=str(e)[:50]
                ))
            
            # Check Firewall Rules
            try:
                firewalls = compute.firewalls().list(project=self.project_id).execute()
                firewall_list = firewalls.get("items", [])
                
                category.add_result(CheckResult(
                    name="Firewall Rules Access",
                    status=CheckStatus.OK,
                    message=f"Found {len(firewall_list)} firewall rule(s)"
                ))
                
                # Check for Databricks-related rules
                dbx_rules = [
                    f for f in firewall_list 
                    if "databricks" in f.get("name", "").lower() or
                       "dbx" in f.get("name", "").lower()
                ]
                
                if dbx_rules:
                    category.add_result(CheckResult(
                        name="Databricks Firewall Rules",
                        status=CheckStatus.OK,
                        message=f"Found {len(dbx_rules)} Databricks rule(s)"
                    ))
                    
            except Exception as e:
                category.add_result(CheckResult(
                    name="Firewall Rules Access",
                    status=CheckStatus.NOT_OK,
                    message=str(e)[:50]
                ))
            
            # Check Cloud Routers and NAT
            try:
                routers = compute.routers().list(
                    project=self.project_id,
                    region=self.region or "us-central1"
                ).execute()
                router_list = routers.get("items", [])
                
                category.add_result(CheckResult(
                    name="Cloud Router Access",
                    status=CheckStatus.OK,
                    message=f"Found {len(router_list)} router(s)"
                ))
                
                # Check for NAT configurations
                nat_count = 0
                for router in router_list:
                    nats = router.get("nats", [])
                    nat_count += len(nats)
                    
                    for nat in nats:
                        nat_name = nat.get("name")
                        category.add_result(CheckResult(
                            name=f"Cloud NAT: {nat_name}",
                            status=CheckStatus.OK,
                            message=f"On router {router.get('name')}"
                        ))
                
                if nat_count == 0:
                    category.add_result(CheckResult(
                        name="Cloud NAT",
                        status=CheckStatus.WARNING,
                        message="No Cloud NAT configured - needed for private clusters"
                    ))
                    
            except Exception as e:
                category.add_result(CheckResult(
                    name="Cloud Router Access",
                    status=CheckStatus.WARNING,
                    message=str(e)[:50]
                ))
                
        except ImportError as e:
            category.add_result(CheckResult(
                name="Compute SDK",
                status=CheckStatus.NOT_OK,
                message="google-api-python-client not installed"
            ))
        except Exception as e:
            category.add_result(CheckResult(
                name="Network Check",
                status=CheckStatus.NOT_OK,
                message=str(e)
            ))
        
        return category
    
    def check_private_connectivity(self) -> CheckCategory:
        """Check Private Google Access and Private Service Connect."""
        category = CheckCategory(name="PRIVATE CONNECTIVITY")
        
        try:
            compute = self._get_compute_client()
            
            # Check subnets for Private Google Access
            try:
                subnets = compute.subnetworks().list(
                    project=self.project_id,
                    region=self.region or "us-central1"
                ).execute()
                subnet_list = subnets.get("items", [])
                
                pga_enabled = sum(1 for s in subnet_list if s.get("privateIpGoogleAccess", False))
                
                if pga_enabled == len(subnet_list) and subnet_list:
                    category.add_result(CheckResult(
                        name="Private Google Access",
                        status=CheckStatus.OK,
                        message=f"Enabled on all {len(subnet_list)} subnet(s)"
                    ))
                elif pga_enabled > 0:
                    category.add_result(CheckResult(
                        name="Private Google Access",
                        status=CheckStatus.WARNING,
                        message=f"Enabled on {pga_enabled}/{len(subnet_list)} subnet(s)"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="Private Google Access",
                        status=CheckStatus.WARNING,
                        message="Not enabled on any subnet - needed for Databricks"
                    ))
                    
            except Exception as e:
                category.add_result(CheckResult(
                    name="Private Google Access",
                    status=CheckStatus.WARNING,
                    message=f"Could not check: {str(e)[:40]}"
                ))
            
            # Check for Private Service Connect endpoints
            try:
                # List forwarding rules to find PSC endpoints
                forwarding_rules = compute.forwardingRules().list(
                    project=self.project_id,
                    region=self.region or "us-central1"
                ).execute()
                
                psc_endpoints = [
                    fr for fr in forwarding_rules.get("items", [])
                    if fr.get("target", "").startswith("https://www.googleapis.com/compute/v1/projects/") and
                       "serviceAttachments" in fr.get("target", "")
                ]
                
                if psc_endpoints:
                    category.add_result(CheckResult(
                        name="Private Service Connect",
                        status=CheckStatus.OK,
                        message=f"Found {len(psc_endpoints)} PSC endpoint(s)"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="Private Service Connect",
                        status=CheckStatus.OK,
                        message="No PSC endpoints (optional for Databricks)"
                    ))
                    
            except Exception as e:
                category.add_result(CheckResult(
                    name="Private Service Connect",
                    status=CheckStatus.WARNING,
                    message=f"Could not check: {str(e)[:40]}"
                ))
            
            # Check Cloud NAT for private connectivity
            try:
                routers = compute.routers().list(
                    project=self.project_id,
                    region=self.region or "us-central1"
                ).execute()
                
                nat_count = 0
                for router in routers.get("items", []):
                    nat_count += len(router.get("nats", []))
                
                if nat_count > 0:
                    category.add_result(CheckResult(
                        name="Cloud NAT for Egress",
                        status=CheckStatus.OK,
                        message=f"{nat_count} NAT configuration(s) found"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="Cloud NAT for Egress",
                        status=CheckStatus.WARNING,
                        message="No Cloud NAT - needed for private cluster egress"
                    ))
                    
            except Exception as e:
                category.add_result(CheckResult(
                    name="Cloud NAT Check",
                    status=CheckStatus.WARNING,
                    message=str(e)[:40]
                ))
                
        except Exception as e:
            category.add_result(CheckResult(
                name="Private Connectivity Check",
                status=CheckStatus.WARNING,
                message=str(e)[:50]
            ))
        
        return category
    
    def check_storage(self) -> CheckCategory:
        """Check GCP Cloud Storage for Unity Catalog."""
        category = CheckCategory(name="STORAGE (GCS for Unity Catalog)")
        
        try:
            storage = self._get_storage_client()
            
            # Check bucket listing
            try:
                buckets = list(storage.list_buckets())
                
                category.add_result(CheckResult(
                    name="Cloud Storage Access",
                    status=CheckStatus.OK,
                    message=f"Found {len(buckets)} bucket(s)"
                ))
                
                # Check for Databricks-related buckets
                dbx_buckets = [
                    b for b in buckets 
                    if "databricks" in b.name.lower() or
                       "unity" in b.name.lower() or
                       "dbfs" in b.name.lower()
                ]
                
                if dbx_buckets:
                    for bucket in dbx_buckets[:3]:
                        category.add_result(CheckResult(
                            name=f"Databricks Bucket: {bucket.name}",
                            status=CheckStatus.OK,
                            message=f"Location: {bucket.location}"
                        ))
                
                # Show first few buckets
                for bucket in buckets[:3]:
                    if bucket not in dbx_buckets:
                        category.add_result(CheckResult(
                            name=f"Bucket: {bucket.name}",
                            status=CheckStatus.OK,
                            message=f"Location: {bucket.location}"
                        ))
                    
            except Exception as e:
                if "403" in str(e):
                    category.add_result(CheckResult(
                        name="Cloud Storage Access",
                        status=CheckStatus.NOT_OK,
                        message="Access denied"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="Cloud Storage Access",
                        status=CheckStatus.NOT_OK,
                        message=str(e)[:50]
                    ))
            
            # Check bucket creation capability
            try:
                import uuid
                test_name = f"databricks-precheck-{uuid.uuid4().hex[:8]}"
                
                try:
                    storage.get_bucket(test_name)
                except Exception as e:
                    if "404" in str(e):
                        category.add_result(CheckResult(
                            name="Bucket Creation Check",
                            status=CheckStatus.OK,
                            message="Can check bucket availability"
                        ))
                    elif "403" in str(e):
                        category.add_result(CheckResult(
                            name="Bucket Creation Check",
                            status=CheckStatus.WARNING,
                            message="Limited bucket access"
                        ))
                    else:
                        raise
            except Exception as e:
                category.add_result(CheckResult(
                    name="Bucket Creation Check",
                    status=CheckStatus.WARNING,
                    message=f"Could not verify: {str(e)[:40]}"
                ))
            
            # Check for uniform bucket-level access (recommended for Unity Catalog)
            try:
                buckets = list(storage.list_buckets())
                uniform_count = 0
                
                for bucket in buckets[:10]:
                    if bucket.iam_configuration.uniform_bucket_level_access_enabled:
                        uniform_count += 1
                
                if uniform_count > 0:
                    category.add_result(CheckResult(
                        name="Uniform Bucket-Level Access",
                        status=CheckStatus.OK,
                        message=f"{uniform_count} bucket(s) with uniform access"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="Uniform Bucket-Level Access",
                        status=CheckStatus.WARNING,
                        message="No buckets with uniform access - recommended for Unity Catalog"
                    ))
                    
            except Exception:
                pass
                
        except ImportError:
            category.add_result(CheckResult(
                name="Storage SDK",
                status=CheckStatus.NOT_OK,
                message="google-cloud-storage not installed"
            ))
        except Exception as e:
            category.add_result(CheckResult(
                name="Storage Check",
                status=CheckStatus.NOT_OK,
                message=str(e)
            ))
        
        return category
    
    def check_quotas(self) -> CheckCategory:
        """Check GCP resource quotas for Databricks deployment."""
        category = CheckCategory(name="QUOTAS & LIMITS")
        
        try:
            compute = self._get_compute_client()
            
            # Get project-level quotas
            try:
                project = compute.projects().get(project=self.project_id).execute()
                quotas = project.get("quotas", [])
                
                critical_quotas = [
                    "NETWORKS",
                    "SUBNETWORKS",
                    "FIREWALLS",
                    "ROUTERS",
                    "STATIC_ADDRESSES",
                    "IN_USE_ADDRESSES",
                    "CPUS_ALL_REGIONS",
                ]
                
                for quota in quotas:
                    metric = quota.get("metric")
                    if metric in critical_quotas:
                        usage = quota.get("usage", 0)
                        limit = quota.get("limit", 0)
                        percentage = (usage / limit * 100) if limit > 0 else 0
                        
                        if percentage >= 90:
                            status = CheckStatus.NOT_OK
                            message = f"{usage}/{limit} used - at limit!"
                        elif percentage >= 75:
                            status = CheckStatus.WARNING
                            message = f"{usage}/{limit} used - approaching limit"
                        else:
                            status = CheckStatus.OK
                            message = f"{usage}/{limit} used"
                        
                        category.add_result(CheckResult(
                            name=f"{metric.replace('_', ' ').title()}",
                            status=status,
                            message=message
                        ))
                        
            except Exception as e:
                category.add_result(CheckResult(
                    name="Project Quotas",
                    status=CheckStatus.WARNING,
                    message=f"Could not check: {str(e)[:40]}"
                ))
            
            # Get region-level quotas
            try:
                region_info = compute.regions().get(
                    project=self.project_id,
                    region=self.region or "us-central1"
                ).execute()
                
                quotas = region_info.get("quotas", [])
                
                region_critical = ["CPUS", "DISKS_TOTAL_GB", "INSTANCES", "SSD_TOTAL_GB"]
                
                for quota in quotas:
                    metric = quota.get("metric")
                    if metric in region_critical:
                        usage = quota.get("usage", 0)
                        limit = quota.get("limit", 0)
                        percentage = (usage / limit * 100) if limit > 0 else 0
                        
                        if percentage >= 90:
                            status = CheckStatus.NOT_OK
                        elif percentage >= 75:
                            status = CheckStatus.WARNING
                        else:
                            status = CheckStatus.OK
                        
                        category.add_result(CheckResult(
                            name=f"{metric.replace('_', ' ').title()} ({self.region})",
                            status=status,
                            message=f"{usage}/{limit} used"
                        ))
                        
            except Exception as e:
                category.add_result(CheckResult(
                    name="Region Quotas",
                    status=CheckStatus.WARNING,
                    message=f"Could not check: {str(e)[:40]}"
                ))
                
        except Exception as e:
            category.add_result(CheckResult(
                name="Quota Check",
                status=CheckStatus.WARNING,
                message=f"Could not check quotas: {str(e)[:40]}"
            ))
        
        return category
    
    def check_kms(self) -> CheckCategory:
        """Check GCP Cloud KMS access for CMEK."""
        category = CheckCategory(name="CLOUD KMS (CMEK)")
        
        try:
            from googleapiclient import discovery
            kms = discovery.build(
                'cloudkms', 'v1',
                credentials=self._get_credentials(),
                cache_discovery=False
            )
            
            try:
                parent = f"projects/{self.project_id}/locations/{self.region or 'us-central1'}"
                response = kms.projects().locations().keyRings().list(
                    parent=parent
                ).execute()
                
                keyrings = response.get("keyRings", [])
                
                category.add_result(CheckResult(
                    name="KMS Access",
                    status=CheckStatus.OK,
                    message=f"Found {len(keyrings)} key ring(s)"
                ))
                
                # Check for Databricks-related key rings
                for kr in keyrings[:3]:
                    kr_name = kr.get("name", "").split("/")[-1]
                    if "databricks" in kr_name.lower() or "dbx" in kr_name.lower():
                        category.add_result(CheckResult(
                            name=f"Key Ring: {kr_name}",
                            status=CheckStatus.OK,
                            message="Databricks key ring found"
                        ))
                
            except Exception as e:
                if "403" in str(e):
                    category.add_result(CheckResult(
                        name="KMS Access",
                        status=CheckStatus.WARNING,
                        message="Cannot list key rings (may not have access)"
                    ))
                elif "404" in str(e) or "NOT_FOUND" in str(e):
                    category.add_result(CheckResult(
                        name="KMS Access",
                        status=CheckStatus.OK,
                        message="No key rings in this region"
                    ))
                else:
                    category.add_result(CheckResult(
                        name="KMS Access",
                        status=CheckStatus.WARNING,
                        message=str(e)[:50]
                    ))
                    
        except ImportError:
            category.add_result(CheckResult(
                name="KMS SDK",
                status=CheckStatus.SKIPPED,
                message="google-cloud-kms not installed"
            ))
        except Exception as e:
            category.add_result(CheckResult(
                name="KMS Check",
                status=CheckStatus.WARNING,
                message=str(e)[:50]
            ))
        
        return category
    
    def run_all_checks(self) -> CheckReport:
        """Run all GCP checks for Databricks deployment."""
        self._report = CheckReport(
            cloud=self.cloud_name,
            region=self.region or "default"
        )
        
        # Run credentials check first
        cred_category = self.check_credentials()
        self._report.add_category(cred_category)
        
        # Update region in report
        self._report.region = self.region or "us-central1"
        
        # Set account info
        if self._project_info:
            self._report.account_info = (
                f"Project: {self._project_info['name']} "
                f"({self._project_info['id']})"
            )
        
        # Check if credentials failed
        credentials_ok = all(
            r.status in (CheckStatus.OK, CheckStatus.WARNING) 
            for r in cred_category.results
        )
        
        if credentials_ok:
            self._report.add_category(self.check_apis())
            self._report.add_category(self.check_iam_permissions())
            self._report.add_category(self.check_network())
            self._report.add_category(self.check_private_connectivity())
            self._report.add_category(self.check_storage())
            self._report.add_category(self.check_quotas())
            self._report.add_category(self.check_kms())
        else:
            for check_name in ["REQUIRED APIS", "IAM PERMISSIONS (Databricks-specific)", 
                              "NETWORK (VPC for Databricks)", "PRIVATE CONNECTIVITY",
                              "STORAGE (GCS for Unity Catalog)", "QUOTAS & LIMITS", 
                              "CLOUD KMS (CMEK)"]:
                category = CheckCategory(name=check_name)
                category.add_result(CheckResult(
                    name="All checks",
                    status=CheckStatus.SKIPPED,
                    message="Skipped due to credential failure"
                ))
                self._report.add_category(category)
        
        return self._report
