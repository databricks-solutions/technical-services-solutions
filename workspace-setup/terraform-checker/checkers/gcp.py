"""GCP checker for Databricks Terraform Pre-Check.

STATUS: BETA / PARTIAL COVERAGE.

This checker is READ-ONLY: it never creates, mutates, or deletes any GCP
resource. It establishes whether the calling identity *could* deploy a
Databricks workspace by:

  * calling ``resourcemanager.projects.testIamPermissions`` for the full
    authoritative SRA permission set (batched <=100 perms/call), and
  * probing the Service Usage API for the required googleapis.

Because everything is read-only, the checker proves *authorization* but cannot
prove that a real ``terraform apply`` will succeed end to end (org policies,
VPC-SC perimeters, billing, API quotas, and the Databricks-managed backend SA's
own project bindings are out of scope). A clean run here means "no permission
blocker was found", not "deploy guaranteed". This is surfaced as a first
informational result in every report.

The authoritative permission set is taken from the Databricks SRA Terraform
module (``terraform-databricks-sra/gcp``). Several deploy-blocking permissions
are NOT in the SRA custom role itself (they are assumed to come from broader
roles on the deploying identity); those are still required at apply time and so
are checked here. See ``REQUIRED_PERMISSION_SET`` for per-area detail and which
permissions are deploy-blocking.

GCP is read-only by construction, so the ``verify_only`` flag accepted by the
constructor (for parity with the AWS/Azure checkers and main.py) is purely
informational here — every check is already non-mutating.
"""

from typing import Optional, List, Dict, Tuple

from .base import (
    BaseChecker,
    CheckCategory,
    CheckResult,
    CheckStatus,
    CheckReport,
)
from utils.denial import is_access_denied


# Docs the remediation results point at.
_PERMISSIONS_DOC = (
    "https://docs.databricks.com/gcp/en/admin/cloud-configurations/gcp/permissions"
)


class GCPChecker(BaseChecker):
    """Checker for GCP resources and permissions for Databricks deployment.

    Read-only and beta — see the module docstring.
    """

    # ==========================================================================
    # AUTHORITATIVE REQUIRED PERMISSION SET (from the Databricks GCP SRA)
    #
    # Each area lists every permission the workspace_deployment module needs and
    # marks the subset that BLOCKS a deploy if missing. Areas gated behind a
    # feature flag (kms/psc/dns) are only treated as blocking when that feature
    # is in scope; everything in the always-on areas is checked on every run.
    #
    # `scope` controls when an area is evaluated:
    #   "always"  -> always checked (project, network base, storage, iam)
    #   "psc"     -> only when private connectivity is requested
    #   "dns"     -> only when private connectivity + DNS zone creation
    #   "kms"     -> only when CMEK is requested
    # ==========================================================================
    REQUIRED_PERMISSION_SET: Dict[str, Dict] = {
        "project": {
            "scope": "always",
            "permissions": [
                "resourcemanager.projects.get",
                "resourcemanager.projects.getIamPolicy",
                "resourcemanager.projects.setIamPolicy",
                "serviceusage.services.get",
                "serviceusage.services.list",
                "serviceusage.services.enable",
                "compute.projects.get",
            ],
            "deploy_blocking": [
                "resourcemanager.projects.get",
                "resourcemanager.projects.setIamPolicy",
                "serviceusage.services.enable",
                "compute.projects.get",
            ],
        },
        "network": {
            "scope": "always",
            "permissions": [
                "compute.networks.create",
                "compute.networks.get",
                "compute.networks.delete",
                "compute.networks.updatePolicy",
                "compute.subnetworks.create",
                "compute.subnetworks.get",
                "compute.subnetworks.delete",
                "compute.subnetworks.getIamPolicy",
                "compute.subnetworks.setIamPolicy",
                # GAP: not in SRA custom role but required to attach SA/PE to subnet
                "compute.subnetworks.use",
                "compute.subnetworks.useExternalIp",
                # GAP: required by private_ip_google_access=true on subnets
                "compute.subnetworks.setPrivateIpGoogleAccess",
                "compute.firewalls.create",
                "compute.firewalls.get",
                "compute.firewalls.update",
                "compute.firewalls.delete",
                "compute.routers.create",
                "compute.routers.get",
                "compute.routers.update",
                "compute.routers.delete",
                # GAP: needed for Cloud NAT on router
                "compute.routers.use",
            ],
            "deploy_blocking": [
                "compute.networks.create",
                "compute.subnetworks.create",
                "compute.subnetworks.use",
                "compute.subnetworks.setPrivateIpGoogleAccess",
                "compute.firewalls.create",
                "compute.routers.create",
            ],
        },
        "storage": {
            "scope": "always",
            "permissions": [
                # GAP: not in SRA workspace_creator role; needed for UC buckets
                "storage.buckets.create",
                "storage.buckets.get",
                "storage.buckets.delete",
                "storage.buckets.getIamPolicy",
                "storage.buckets.setIamPolicy",
                "storage.buckets.update",
            ],
            "deploy_blocking": [
                "storage.buckets.create",
                "storage.buckets.setIamPolicy",
            ],
        },
        "iam": {
            "scope": "always",
            "permissions": [
                "iam.roles.create",
                "iam.roles.get",
                "iam.roles.update",
                "iam.roles.delete",
                "iam.serviceAccounts.create",
                "iam.serviceAccounts.get",
                "iam.serviceAccounts.getIamPolicy",
                "iam.serviceAccounts.setIamPolicy",
                "iam.serviceAccounts.getOpenIdToken",
                "iam.serviceAccounts.getAccessToken",
                # GAP: not explicitly in SRA custom role; granted via
                # roles/iam.serviceAccountUser. The #1 GCP deploy blocker.
                "iam.serviceAccounts.actAs",
                # Only when create_service_account_key=true (keys.tf)
                "iam.serviceAccountKeys.create",
            ],
            "deploy_blocking": [
                "iam.serviceAccounts.actAs",
                "iam.serviceAccounts.getAccessToken",
                "iam.serviceAccounts.create",
                "iam.roles.create",
                "resourcemanager.projects.setIamPolicy",
            ],
        },
        "kms": {
            "scope": "kms",
            "permissions": [
                "cloudkms.keyRings.create",
                "cloudkms.keyRings.get",
                "cloudkms.cryptoKeys.create",
                "cloudkms.cryptoKeys.get",
                "cloudkms.cryptoKeys.update",
                "cloudkms.cryptoKeys.getIamPolicy",
                "cloudkms.cryptoKeys.setIamPolicy",
                "cloudkms.cryptoKeyVersions.list",
                "cloudkms.cryptoKeyVersions.destroy",
            ],
            "deploy_blocking": [
                "cloudkms.keyRings.create",
                "cloudkms.cryptoKeys.create",
                "cloudkms.cryptoKeys.setIamPolicy",
            ],
        },
        "psc": {
            "scope": "psc",
            "permissions": [
                # All GAP: not in SRA role (only forwardingRules.get/list are)
                "compute.addresses.create",
                "compute.addresses.get",
                "compute.addresses.delete",
                "compute.addresses.use",
                "compute.forwardingRules.create",
                "compute.forwardingRules.get",
                "compute.forwardingRules.list",
                "compute.forwardingRules.delete",
                "compute.forwardingRules.use",
            ],
            "deploy_blocking": [
                "compute.addresses.create",
                "compute.addresses.use",
                "compute.forwardingRules.create",
            ],
        },
        "dns": {
            "scope": "dns",
            "permissions": [
                # All GAP: no dns.* perms in SRA role at all
                "dns.managedZones.create",
                "dns.managedZones.get",
                "dns.managedZones.delete",
                "dns.networks.bindPrivateDNSZone",
                "dns.resourceRecordSets.create",
                "dns.resourceRecordSets.get",
                "dns.resourceRecordSets.update",
                "dns.resourceRecordSets.delete",
                "dns.changes.create",
                "dns.changes.get",
            ],
            "deploy_blocking": [
                "dns.managedZones.create",
                "dns.resourceRecordSets.create",
                "dns.changes.create",
            ],
        },
    }

    # Human-friendly remediation hints per area.
    _AREA_REMEDIATION = {
        "project": "Grant roles/serviceusage.serviceUsageAdmin + project IAM admin.",
        "network": "Grant roles/compute.networkAdmin (or compute.admin) on the project.",
        "storage": "Grant roles/storage.admin on the project for UC bucket creation.",
        "iam": "Grant roles/iam.serviceAccountUser (actAs) + roles/iam.roleAdmin "
               "+ roles/iam.serviceAccountAdmin to the deploying identity.",
        "kms": "Grant roles/cloudkms.admin on the project (only needed for CMEK).",
        "psc": "Grant compute.addresses.* and compute.forwardingRules.* "
               "(roles/compute.networkAdmin) for Private Service Connect.",
        "dns": "Grant roles/dns.admin on the project for the private DNS zone.",
    }

    # Required APIs. `scope` mirrors the permission-area scoping above so we only
    # treat feature-gated APIs as blocking when that feature is in scope.
    REQUIRED_APIS: List[Dict[str, str]] = [
        {"api": "compute.googleapis.com", "scope": "always",
         "description": "Compute Engine (VPC, subnets, firewalls, routers, addresses, forwarding rules)"},
        {"api": "iam.googleapis.com", "scope": "always",
         "description": "IAM custom roles and service accounts"},
        {"api": "iamcredentials.googleapis.com", "scope": "always",
         "description": "SA impersonation (getAccessToken/getOpenIdToken)"},
        {"api": "cloudresourcemanager.googleapis.com", "scope": "always",
         "description": "Project get / IAM policy"},
        {"api": "serviceusage.googleapis.com", "scope": "always",
         "description": "Enable other APIs"},
        {"api": "storage.googleapis.com", "scope": "always",
         "description": "UC metastore + external GCS buckets"},
        {"api": "container.googleapis.com", "scope": "always",
         "description": "GKE — Databricks classic data plane"},
        {"api": "deploymentmanager.googleapis.com", "scope": "always",
         "description": "Databricks provisions workspace project resources via Deployment Manager"},
        {"api": "cloudkms.googleapis.com", "scope": "kms",
         "description": "CMEK keyrings/keys (only when use_cmek=true)"},
        {"api": "dns.googleapis.com", "scope": "dns",
         "description": "Private DNS zone + A-records for PSC (only when use_psc + create_dns_zone)"},
    ]

    # testIamPermissions accepts at most 100 permissions per call.
    _MAX_PERMS_PER_CALL = 100

    def __init__(
        self,
        region: str = None,
        project_id: str = None,
        credentials_file: str = None,
        verify_only: bool = False,
    ):
        super().__init__(region)
        self.project_id = project_id
        self.credentials_file = credentials_file
        # GCP is read-only by construction; verify_only is accepted for parity
        # with the AWS/Azure checkers and main.py but is purely informational.
        self.verify_only = verify_only
        self._credentials = None
        self._project_info = None
        # Feature flags. Default to checking PSC/DNS/KMS so we never silently
        # report an absent private-connectivity / CMEK path as "OK". A caller
        # who knows these aren't in scope can flip them off.
        self.check_psc = True
        self.check_dns = True
        self.check_cmek = True

    @property
    def cloud_name(self) -> str:
        return "GCP"

    # ------------------------------------------------------------------ #
    # Pure helpers (unit-tested without any live GCP calls)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _http_status(error: object) -> Optional[int]:
        """Return the integer HTTP status from a googleapiclient HttpError.

        Prefers the structured ``resp.status`` (and ``status_code``) over string
        scraping. Returns None when no numeric status is available.
        """
        resp = getattr(error, "resp", None)
        status = getattr(resp, "status", None)
        if status is not None:
            try:
                return int(status)
            except (TypeError, ValueError):
                pass
        status_code = getattr(error, "status_code", None)
        if status_code is not None:
            try:
                return int(status_code)
            except (TypeError, ValueError):
                pass
        return None

    @staticmethod
    def _error_reason(error: object) -> str:
        """Best-effort human-readable reason for an error.

        Uses HttpError._get_reason() (the parsed API error message) when
        available, otherwise the string form. Never truncated to 50 chars —
        we surface the full reason so the gap is actionable.
        """
        get_reason = getattr(error, "_get_reason", None)
        if callable(get_reason):
            try:
                reason = get_reason()
                if reason:
                    return str(reason).strip()
            except Exception:
                pass
        return str(error).strip()

    @classmethod
    def _classify_api_error(cls, error: object) -> str:
        """Classify an API error into an actionable bucket.

        Returns one of:
          "api_disabled"      -> the API/service is not enabled (enable it)
          "permission_denied" -> 403 / denial (grant a role)
          "not_found"         -> 404 (resource/project missing)
          "other"             -> anything else (transient/unknown)
        """
        reason = (cls._error_reason(error) or "").lower()
        status = cls._http_status(error)
        # accessNotConfigured / SERVICE_DISABLED == API not enabled, distinct
        # from a plain permission denial even though both surface as 403.
        if (
            "accessnotconfigured" in reason
            or "service_disabled" in reason
            or "has not been used in project" in reason
            or "it is disabled" in reason
            or "api is not enabled" in reason
        ):
            return "api_disabled"
        if status == 404 or "not_found" in reason or "notfound" in reason:
            return "not_found"
        if status == 403 or is_access_denied(error):
            return "permission_denied"
        return "other"

    @classmethod
    def _scopes_in_effect(cls, *, psc: bool, dns: bool, cmek: bool) -> set:
        """Return the set of area/API scopes that are active for this run."""
        scopes = {"always"}
        if psc:
            scopes.add("psc")
        if dns:
            scopes.add("dns")
        if cmek:
            scopes.add("kms")
        return scopes

    @classmethod
    def _build_permission_request(cls, scopes: set) -> Tuple[List[str], Dict[str, set]]:
        """Build the de-duplicated permission list to test plus a reverse index.

        Returns ``(permissions, perm_to_areas)`` where ``perm_to_areas`` maps a
        permission to the set of in-scope areas that require it. Only areas
        whose scope is active are included.
        """
        perm_to_areas: Dict[str, set] = {}
        for area, spec in cls.REQUIRED_PERMISSION_SET.items():
            if spec["scope"] not in scopes:
                continue
            for perm in spec["permissions"]:
                perm_to_areas.setdefault(perm, set()).add(area)
        return sorted(perm_to_areas.keys()), perm_to_areas

    @classmethod
    def _batched(cls, perms: List[str]) -> List[List[str]]:
        """Split a permission list into <=100-permission batches."""
        return [
            perms[i:i + cls._MAX_PERMS_PER_CALL]
            for i in range(0, len(perms), cls._MAX_PERMS_PER_CALL)
        ] or [[]]

    @classmethod
    def _evaluate_permissions(
        cls, granted: set, scopes: set
    ) -> Dict[str, Dict]:
        """Evaluate granted permissions against the in-scope required set.

        Pure function — given the set of granted permissions and the active
        scopes, return per-area findings. Each area entry has:
          {
            "missing": [perms not granted],
            "missing_blocking": [missing perms that are deploy-blocking],
            "total": int, "granted": int,
            "status": CheckStatus,   # NOT_OK if any blocking missing
          }
        ANY missing deploy-blocking permission -> NOT_OK for that area (no
        fractional WARNING).
        """
        out: Dict[str, Dict] = {}
        for area, spec in cls.REQUIRED_PERMISSION_SET.items():
            if spec["scope"] not in scopes:
                continue
            required = spec["permissions"]
            blocking = set(spec["deploy_blocking"])
            missing = [p for p in required if p not in granted]
            missing_blocking = [p for p in missing if p in blocking]
            if missing_blocking:
                status = CheckStatus.NOT_OK
            elif missing:
                status = CheckStatus.WARNING
            else:
                status = CheckStatus.OK
            out[area] = {
                "missing": missing,
                "missing_blocking": missing_blocking,
                "total": len(required),
                "granted": len(required) - len(missing),
                "status": status,
            }
        return out

    # ------------------------------------------------------------------ #
    # Credential / client plumbing
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Checks
    # ------------------------------------------------------------------ #

    def check_scope_note(self) -> CheckCategory:
        """First informational result: read-only + partial coverage caveat."""
        category = CheckCategory(name="SCOPE & COVERAGE")
        active = []
        if self.check_psc:
            active.append("PSC")
        if self.check_dns:
            active.append("DNS")
        if self.check_cmek:
            active.append("CMEK")
        feature_note = (", optional features in scope: " + ", ".join(active)) if active else ""
        category.add_result(CheckResult(
            name="GCP checker mode",
            status=CheckStatus.SKIPPED,
            message=(
                "BETA, READ-ONLY, PARTIAL COVERAGE. Verifies IAM permissions via "
                "testIamPermissions and required-API enablement only. It does NOT "
                "create resources and cannot prove a real terraform apply will "
                "succeed (org policy, VPC-SC, billing, quota, and the "
                "Databricks-managed backend SA's own project bindings are out of "
                "scope)." + feature_note
            ),
            details="A clean run means no permission blocker was found, not deploy-guaranteed.",
        ))
        return category

    def check_credentials(self) -> CheckCategory:
        """Check GCP credentials validity."""
        category = CheckCategory(name="CREDENTIALS")

        try:
            self._get_credentials()

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
                kind = self._classify_api_error(e)
                if kind == "not_found":
                    category.add_result(CheckResult(
                        name="Project Access",
                        status=CheckStatus.NOT_OK,
                        message=f"Project '{self.project_id}' not found",
                        remediation="Verify the project ID and that it exists.",
                    ))
                elif kind == "api_disabled":
                    category.add_result(CheckResult(
                        name="Project Access",
                        status=CheckStatus.NOT_OK,
                        message=f"Cloud Resource Manager API not enabled: {self._error_reason(e)}",
                        remediation="gcloud services enable cloudresourcemanager.googleapis.com",
                    ))
                elif kind == "permission_denied":
                    category.add_result(CheckResult(
                        name="Project Access",
                        status=CheckStatus.NOT_OK,
                        message=f"Permission denied to access project: {self._error_reason(e)}",
                        remediation="Grant at least roles/viewer on the project.",
                    ))
                else:
                    category.add_result(CheckResult(
                        name="Project Access",
                        status=CheckStatus.NOT_OK,
                        message=self._error_reason(e),
                    ))

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
                    message="No region specified, will use us-central1",
                    assumed=True,
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
                message = self._error_reason(e)

            category.add_result(CheckResult(
                name="GCP Credentials",
                status=CheckStatus.NOT_OK,
                message=message
            ))

        return category

    def check_apis(self) -> CheckCategory:
        """Check if required GCP APIs are enabled.

        If the enabled-services list cannot be read, fall back to probing each
        required API directly (serviceusage get) so we never skip the loop and
        silently pass. Any API we cannot confirm is reported per-API as NOT_OK
        (when we know it's disabled) or UNVERIFIED (WARNING) — never assumed OK.
        """
        category = CheckCategory(name="REQUIRED APIS")
        scopes = self._scopes_in_effect(
            psc=self.check_psc, dns=self.check_dns, cmek=self.check_cmek
        )
        required = [a for a in self.REQUIRED_APIS if a["scope"] in scopes]

        try:
            su_client = self._get_service_usage_client()
        except ImportError:
            category.add_result(CheckResult(
                name="Service Usage SDK",
                status=CheckStatus.NOT_OK,
                message="google-api-python-client not installed",
            ))
            return category
        except Exception as e:
            category.add_result(CheckResult(
                name="Service Usage Client",
                status=CheckStatus.WARNING,
                message=self._error_reason(e),
            ))
            return category

        # First try the bulk list (cheap, one call).
        enabled_services = None
        try:
            parent = f"projects/{self.project_id}"
            enabled_services = set()
            request = su_client.services().list(parent=parent, filter="state:ENABLED")
            while request is not None:
                response = request.execute()
                for s in response.get("services", []):
                    name = s.get("config", {}).get("name", "")
                    if name:
                        enabled_services.add(name)
                request = su_client.services().list_next(request, response)
        except Exception as e:
            enabled_services = None
            self.log_debug("Bulk service list failed, will probe per-API: %s",
                           self._error_reason(e))

        for entry in required:
            api = entry["api"]
            label = f"API: {api}"
            if enabled_services is not None:
                if api in enabled_services:
                    category.add_result(CheckResult(
                        name=label, status=CheckStatus.OK, message="Enabled"))
                else:
                    category.add_result(CheckResult(
                        name=label, status=CheckStatus.NOT_OK,
                        message=f"Not enabled ({entry['description']})",
                        remediation=f"gcloud services enable {api}",
                        doc_link=_PERMISSIONS_DOC,
                    ))
                continue

            # Fallback: probe the single service directly.
            try:
                svc = su_client.services().get(
                    name=f"projects/{self.project_id}/services/{api}"
                ).execute()
                state = svc.get("state", "")
                if state == "ENABLED":
                    category.add_result(CheckResult(
                        name=label, status=CheckStatus.OK, message="Enabled (probed)"))
                else:
                    category.add_result(CheckResult(
                        name=label, status=CheckStatus.NOT_OK,
                        message=f"State is {state or 'DISABLED'} ({entry['description']})",
                        remediation=f"gcloud services enable {api}",
                        doc_link=_PERMISSIONS_DOC,
                    ))
            except Exception as e:
                kind = self._classify_api_error(e)
                if kind == "api_disabled":
                    category.add_result(CheckResult(
                        name=label, status=CheckStatus.NOT_OK,
                        message=f"Not enabled: {self._error_reason(e)}",
                        remediation=f"gcloud services enable {api}",
                        doc_link=_PERMISSIONS_DOC,
                    ))
                else:
                    # Could not confirm — surface as UNVERIFIED, never pass.
                    category.add_result(CheckResult(
                        name=label, status=CheckStatus.WARNING,
                        message=f"UNVERIFIED ({entry['description']}): {self._error_reason(e)}",
                        remediation=f"Manually confirm: gcloud services list --enabled | grep {api}",
                        assumed=True,
                    ))

        return category

    def check_iam_permissions(self) -> CheckCategory:
        """Check GCP IAM permissions for Databricks deployment.

        Drives projects.testIamPermissions from the FULL authoritative SRA set
        (REQUIRED_PERMISSION_SET), batched <=100 perms/call. Any missing
        deploy-blocking permission makes that area NOT_OK.
        """
        category = CheckCategory(name="IAM PERMISSIONS (Databricks deploy set)")
        scopes = self._scopes_in_effect(
            psc=self.check_psc, dns=self.check_dns, cmek=self.check_cmek
        )
        perms, _index = self._build_permission_request(scopes)

        try:
            rm_client = self._get_resource_manager_client()
        except ImportError:
            category.add_result(CheckResult(
                name="IAM SDK",
                status=CheckStatus.NOT_OK,
                message="google-api-python-client not installed",
            ))
            return category
        except Exception as e:
            category.add_result(CheckResult(
                name="IAM Client",
                status=CheckStatus.NOT_OK,
                message=self._error_reason(e),
            ))
            return category

        granted: set = set()
        call_failed_reason = None
        try:
            for batch in self._batched(perms):
                if not batch:
                    continue
                response = rm_client.projects().testIamPermissions(
                    resource=self.project_id,
                    body={"permissions": batch},
                ).execute()
                granted.update(response.get("permissions", []))
        except Exception as e:
            call_failed_reason = self._error_reason(e)

        if call_failed_reason is not None:
            category.add_result(CheckResult(
                name="testIamPermissions",
                status=CheckStatus.WARNING,
                message=f"Could not test permissions: {call_failed_reason}",
                remediation="Grant resourcemanager.projects.getIamPolicy "
                            "(e.g. roles/viewer) so permissions can be tested.",
                assumed=True,
            ))
            return category

        results = self._evaluate_permissions(granted, scopes)
        for area in self.REQUIRED_PERMISSION_SET:
            if area not in results:
                continue
            r = results[area]
            label = f"{area.upper()} permissions ({r['granted']}/{r['total']})"
            if r["status"] == CheckStatus.NOT_OK:
                category.add_result(CheckResult(
                    name=label,
                    status=CheckStatus.NOT_OK,
                    message="Missing deploy-blocking: " + ", ".join(r["missing_blocking"]),
                    details=("Also missing (non-blocking): " + ", ".join(
                        p for p in r["missing"] if p not in set(r["missing_blocking"])
                    )) if len(r["missing"]) > len(r["missing_blocking"]) else None,
                    remediation=self._AREA_REMEDIATION.get(area),
                    doc_link=_PERMISSIONS_DOC,
                ))
            elif r["status"] == CheckStatus.WARNING:
                category.add_result(CheckResult(
                    name=label,
                    status=CheckStatus.WARNING,
                    message="Missing (non-deploy-blocking): " + ", ".join(r["missing"]),
                    remediation=self._AREA_REMEDIATION.get(area),
                    doc_link=_PERMISSIONS_DOC,
                ))
            else:
                category.add_result(CheckResult(
                    name=label,
                    status=CheckStatus.OK,
                    message="All required permissions granted",
                ))

        return category

    def check_impersonation(self) -> CheckCategory:
        """Check iam.serviceAccounts.actAs + getAccessToken — the #1 deploy blocker.

        Called out as its own category because impersonation failure is the most
        common GCP Databricks deploy blocker and is easy to miss in a per-area
        roll-up. Tested at project level via testIamPermissions.
        """
        category = CheckCategory(name="SA IMPERSONATION (actAs)")
        impersonation_perms = [
            "iam.serviceAccounts.actAs",
            "iam.serviceAccounts.getAccessToken",
            "iam.serviceAccounts.getOpenIdToken",
        ]

        try:
            rm_client = self._get_resource_manager_client()
            response = rm_client.projects().testIamPermissions(
                resource=self.project_id,
                body={"permissions": impersonation_perms},
            ).execute()
            granted = set(response.get("permissions", []))
        except Exception as e:
            category.add_result(CheckResult(
                name="Impersonation Test",
                status=CheckStatus.WARNING,
                message=f"Could not test impersonation: {self._error_reason(e)}",
                remediation="Verify roles/iam.serviceAccountUser on the "
                            "workspace_creator service account.",
                assumed=True,
            ))
            return category

        # actAs is the hard blocker.
        if "iam.serviceAccounts.actAs" in granted:
            category.add_result(CheckResult(
                name="iam.serviceAccounts.actAs",
                status=CheckStatus.OK,
                message="Granted (can impersonate service accounts)",
            ))
        else:
            category.add_result(CheckResult(
                name="iam.serviceAccounts.actAs",
                status=CheckStatus.NOT_OK,
                message="MISSING — Terraform/gcloud cannot impersonate the "
                        "workspace_creator SA; deploy fails at auth time.",
                remediation="Grant roles/iam.serviceAccountUser on the "
                            "workspace_creator SA to the deploying identity "
                            "(this is the #1 GCP deploy blocker).",
                doc_link=_PERMISSIONS_DOC,
            ))

        for perm in ("iam.serviceAccounts.getAccessToken",
                     "iam.serviceAccounts.getOpenIdToken"):
            if perm in granted:
                category.add_result(CheckResult(
                    name=perm, status=CheckStatus.OK, message="Granted"))
            else:
                category.add_result(CheckResult(
                    name=perm,
                    status=CheckStatus.NOT_OK if perm.endswith("getAccessToken") else CheckStatus.WARNING,
                    message="MISSING — required for SA token minting during deploy."
                    if perm.endswith("getAccessToken") else "Missing (needed for OIDC token flows).",
                    remediation="Grant via the SRA workspace_creator custom role "
                                "or roles/iam.serviceAccountTokenCreator.",
                    doc_link=_PERMISSIONS_DOC,
                ))

        return category

    def _testable_area_category(self, area: str, title: str) -> CheckCategory:
        """Generic per-area testIamPermissions check used by network/PSC/DNS.

        'Can list' must NOT read as 'can use/create' — we test the actual
        create/use permissions, not list permissions.
        """
        category = CheckCategory(name=title)
        spec = self.REQUIRED_PERMISSION_SET[area]
        scopes = self._scopes_in_effect(
            psc=self.check_psc, dns=self.check_dns, cmek=self.check_cmek
        )
        if spec["scope"] not in scopes:
            category.add_result(CheckResult(
                name=title,
                status=CheckStatus.SKIPPED,
                message="Feature not in scope for this run.",
            ))
            return category

        try:
            rm_client = self._get_resource_manager_client()
            perms = spec["permissions"]
            granted: set = set()
            for batch in self._batched(perms):
                if not batch:
                    continue
                response = rm_client.projects().testIamPermissions(
                    resource=self.project_id,
                    body={"permissions": batch},
                ).execute()
                granted.update(response.get("permissions", []))
        except Exception as e:
            category.add_result(CheckResult(
                name=f"{area} permission test",
                status=CheckStatus.WARNING,
                message=f"Could not test: {self._error_reason(e)}",
                remediation=self._AREA_REMEDIATION.get(area),
                assumed=True,
            ))
            return category

        result = self._evaluate_permissions(granted, scopes)[area]
        if result["status"] == CheckStatus.NOT_OK:
            category.add_result(CheckResult(
                name=f"{area} create/use permissions",
                status=CheckStatus.NOT_OK,
                message="Missing deploy-blocking: " + ", ".join(result["missing_blocking"]),
                remediation=self._AREA_REMEDIATION.get(area),
                doc_link=_PERMISSIONS_DOC,
            ))
        elif result["status"] == CheckStatus.WARNING:
            category.add_result(CheckResult(
                name=f"{area} create/use permissions",
                status=CheckStatus.WARNING,
                message="Missing (non-blocking): " + ", ".join(result["missing"]),
                remediation=self._AREA_REMEDIATION.get(area),
                doc_link=_PERMISSIONS_DOC,
            ))
        else:
            category.add_result(CheckResult(
                name=f"{area} create/use permissions",
                status=CheckStatus.OK,
                message=f"All {result['total']} permissions granted",
            ))
        return category

    def check_network(self) -> CheckCategory:
        """Check BYO-network / VPC create+use permissions (not just list)."""
        return self._testable_area_category(
            "network", "NETWORK (VPC create/use for Databricks)")

    def check_private_connectivity(self) -> CheckCategory:
        """Check PSC + DNS permissions when private connectivity is in scope.

        Stops reporting an absent PSC/endpoint configuration as unconditionally
        OK — if PSC/DNS is in scope and the create permissions are missing, it's
        a blocker.
        """
        category = CheckCategory(name="PRIVATE CONNECTIVITY (PSC/DNS)")

        if not (self.check_psc or self.check_dns):
            category.add_result(CheckResult(
                name="Private Connectivity",
                status=CheckStatus.SKIPPED,
                message="PSC/DNS not in scope for this run.",
            ))
            return category

        for area, ok_areas in (("psc", self.check_psc), ("dns", self.check_dns)):
            if not ok_areas:
                continue
            sub = self._testable_area_category(area, area.upper())
            for r in sub.results:
                category.add_result(r)
        return category

    def check_storage(self) -> CheckCategory:
        """Check GCS bucket create + IAM permissions for Unity Catalog."""
        return self._testable_area_category(
            "storage", "STORAGE (GCS for Unity Catalog)")

    def check_kms(self) -> CheckCategory:
        """Check Cloud KMS / CMEK permissions when CMEK is in scope."""
        return self._testable_area_category("kms", "CLOUD KMS (CMEK)")

    def check_project_permissions(self) -> CheckCategory:
        """Check project-level deploy permissions (serviceusage/compute project get)."""
        return self._testable_area_category(
            "project", "PROJECT (deploy-level permissions)")

    def check_quotas(self) -> CheckCategory:
        """Check GCP resource quotas for Databricks deployment.

        Compute Engine quota honesty — read-only project/region quota usage so a
        deploy isn't blocked by an at-limit network/CPU/address quota. Quota
        introspection is best-effort: any failure is surfaced as a WARNING (the
        permission/API path is already covered by the other checks), never an
        unverified pass.
        """
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
                    message=f"Could not check: {self._error_reason(e)}",
                    assumed=True,
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
                    message=f"Could not check: {self._error_reason(e)}",
                    assumed=True,
                ))

        except Exception as e:
            category.add_result(CheckResult(
                name="Quota Check",
                status=CheckStatus.WARNING,
                message=f"Could not check quotas: {self._error_reason(e)}",
                assumed=True,
            ))

        return category

    def run_all_checks(self) -> CheckReport:
        """Run all GCP checks for Databricks deployment."""
        self._report = CheckReport(
            cloud=self.cloud_name,
            region=self.region or "default"
        )

        # Informational scope/coverage note always comes first.
        self._report.add_category(self.check_scope_note())

        # Credentials check.
        cred_category = self.check_credentials()
        self._report.add_category(cred_category)

        self._report.region = self.region or "us-central1"
        self._report.project_id = self.project_id

        if self._project_info:
            self._report.account_info = (
                f"Project: {self._project_info['name']} "
                f"({self._project_info['id']})"
            )

        credentials_ok = not any(
            r.status == CheckStatus.NOT_OK for r in cred_category.results
        )

        if credentials_ok:
            self._report.add_category(self.check_apis())
            self._report.add_category(self.check_project_permissions())
            self._report.add_category(self.check_iam_permissions())
            self._report.add_category(self.check_impersonation())
            self._report.add_category(self.check_network())
            self._report.add_category(self.check_private_connectivity())
            self._report.add_category(self.check_storage())
            self._report.add_category(self.check_kms())
            self._report.add_category(self.check_quotas())
        else:
            for check_name in [
                "REQUIRED APIS", "PROJECT (deploy-level permissions)",
                "IAM PERMISSIONS (Databricks deploy set)", "SA IMPERSONATION (actAs)",
                "NETWORK (VPC create/use for Databricks)", "PRIVATE CONNECTIVITY (PSC/DNS)",
                "STORAGE (GCS for Unity Catalog)", "CLOUD KMS (CMEK)",
                "QUOTAS & LIMITS",
            ]:
                category = CheckCategory(name=check_name)
                category.add_result(CheckResult(
                    name="All checks",
                    status=CheckStatus.SKIPPED,
                    message="Skipped due to credential failure"
                ))
                self._report.add_category(category)

        return self._report
