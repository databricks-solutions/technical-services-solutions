"""Credential loader for multiple cloud providers."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AWSCredentials:
    """AWS credentials container."""
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    session_token: Optional[str] = None
    profile: Optional[str] = None
    region: Optional[str] = None
    
    @property
    def is_configured(self) -> bool:
        """Check if credentials are configured."""
        # Either explicit keys or profile-based auth
        return bool(self.access_key_id and self.secret_access_key) or bool(self.profile)


@dataclass
class AzureCredentials:
    """Azure credentials container."""
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    subscription_id: Optional[str] = None
    use_cli: bool = False
    use_managed_identity: bool = False
    
    @property
    def is_configured(self) -> bool:
        """Check if credentials are configured."""
        return (
            bool(self.tenant_id and self.client_id and self.client_secret) or
            self.use_cli or
            self.use_managed_identity
        )


@dataclass
class GCPCredentials:
    """GCP credentials container."""
    credentials_file: Optional[str] = None
    project_id: Optional[str] = None
    use_adc: bool = False  # Application Default Credentials
    
    @property
    def is_configured(self) -> bool:
        """Check if credentials are configured."""
        return bool(self.credentials_file) or self.use_adc


class CredentialLoader:
    """Load credentials from multiple sources."""
    
    @staticmethod
    def load_aws(
        profile: Optional[str] = None,
        region: Optional[str] = None
    ) -> AWSCredentials:
        """
        Load AWS credentials from environment or config files.
        
        Priority:
        1. Environment variables (AWS_ACCESS_KEY_ID, etc.)
        2. AWS credentials file with profile
        3. Default profile
        """
        creds = AWSCredentials(
            access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            session_token=os.environ.get("AWS_SESSION_TOKEN"),
            profile=profile or os.environ.get("AWS_PROFILE"),
            region=region or os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION"))
        )
        
        # If no explicit keys, check if credentials file exists
        if not creds.access_key_id:
            aws_creds_file = Path.home() / ".aws" / "credentials"
            if aws_creds_file.exists():
                # boto3 will handle reading the file
                if not creds.profile:
                    creds.profile = "default"
        
        return creds
    
    @staticmethod
    def load_azure(
        subscription_id: Optional[str] = None
    ) -> AzureCredentials:
        """
        Load Azure credentials from environment or config.
        
        Priority:
        1. Environment variables (AZURE_CLIENT_ID, etc.)
        2. Azure CLI auth
        3. Managed Identity
        """
        creds = AzureCredentials(
            tenant_id=os.environ.get("AZURE_TENANT_ID"),
            client_id=os.environ.get("AZURE_CLIENT_ID"),
            client_secret=os.environ.get("AZURE_CLIENT_SECRET"),
            subscription_id=subscription_id or os.environ.get("AZURE_SUBSCRIPTION_ID"),
        )
        
        # Check if Azure CLI is configured
        if not creds.client_id:
            azure_dir = Path.home() / ".azure"
            if azure_dir.exists():
                creds.use_cli = True
        
        # Check for managed identity env var
        if os.environ.get("MSI_ENDPOINT") or os.environ.get("IDENTITY_ENDPOINT"):
            creds.use_managed_identity = True
        
        return creds
    
    @staticmethod
    def load_gcp(
        project_id: Optional[str] = None
    ) -> GCPCredentials:
        """
        Load GCP credentials from environment or config.
        
        Priority:
        1. GOOGLE_APPLICATION_CREDENTIALS environment variable
        2. Application Default Credentials (gcloud auth)
        """
        creds_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        
        creds = GCPCredentials(
            credentials_file=creds_file if creds_file and Path(creds_file).exists() else None,
            project_id=project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", 
                                                     os.environ.get("GCLOUD_PROJECT",
                                                                    os.environ.get("GCP_PROJECT"))),
        )
        
        # Check for ADC
        adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
        if adc_path.exists() or creds.credentials_file:
            creds.use_adc = True
        
        return creds
    
    @classmethod
    def detect_available_clouds(cls) -> dict[str, bool]:
        """Detect which cloud providers have credentials configured."""
        return {
            "aws": cls.load_aws().is_configured,
            "azure": cls.load_azure().is_configured,
            "gcp": cls.load_gcp().is_configured,
        }

