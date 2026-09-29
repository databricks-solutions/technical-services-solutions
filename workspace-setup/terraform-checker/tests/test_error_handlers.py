"""Tests for error handling utilities."""

import pytest

from utils.error_handlers import (
    parse_aws_error,
    parse_azure_error,
    parse_gcp_error,
    handle_cloud_error,
)
from checkers.base import CheckStatus


class TestParseAwsError:
    """Tests for AWS error parsing."""
    
    def test_invalid_access_key(self):
        """Test parsing invalid access key error."""
        error = Exception("InvalidClientTokenId: The security token included in the request is invalid")
        error_type, message = parse_aws_error(error)
        
        assert error_type == "auth"
        assert "Invalid AWS Access Key" in message
    
    def test_invalid_secret_key(self):
        """Test parsing invalid secret key error."""
        error = Exception("SignatureDoesNotMatch: The request signature we calculated does not match")
        error_type, message = parse_aws_error(error)
        
        assert error_type == "auth"
        assert "Invalid AWS Secret Access Key" in message
    
    def test_expired_token(self):
        """Test parsing expired token error."""
        error = Exception("ExpiredToken: The security token included in the request is expired")
        error_type, message = parse_aws_error(error)
        
        assert error_type == "auth"
        assert "expired" in message
    
    def test_access_denied(self):
        """Test parsing access denied error."""
        error = Exception("AccessDenied: User: arn:aws:iam::123:user/test is not authorized")
        error_type, message = parse_aws_error(error)
        
        assert error_type == "permission"
        assert "Access denied" in message
    
    def test_dry_run_success(self):
        """Test parsing DryRun success response."""
        error = Exception("DryRunOperation: Request would have succeeded")
        error_type, message = parse_aws_error(error)
        
        assert error_type == "success"
    
    def test_quota_exceeded(self):
        """Test parsing quota exceeded error."""
        error = Exception("LimitExceededException: You have exceeded your VPC limit")
        error_type, message = parse_aws_error(error)
        
        assert error_type == "quota"


class TestParseAzureError:
    """Tests for Azure error parsing."""
    
    def test_aad_auth_failure(self):
        """Test parsing Azure AD authentication failure."""
        error = Exception("AADSTS700016: Application not found in the directory")
        error_type, message = parse_azure_error(error)
        
        assert error_type == "auth"
        assert "Azure AD" in message
    
    def test_missing_credentials(self):
        """Test parsing missing credentials error."""
        error = Exception("DefaultAzureCredential failed to retrieve a token")
        error_type, message = parse_azure_error(error)
        
        assert error_type == "auth"
        assert "No Azure credentials" in message
    
    def test_authorization_failed(self):
        """Test parsing authorization failed error."""
        error = Exception("AuthorizationFailed: The client does not have authorization")
        error_type, message = parse_azure_error(error)
        
        assert error_type == "permission"
    
    def test_quota_exceeded(self):
        """Test parsing quota exceeded error."""
        error = Exception("MaxStorageAccountsCountPerSubscriptionExceeded")
        error_type, message = parse_azure_error(error)
        
        assert error_type == "quota"


class TestParseGcpError:
    """Tests for GCP error parsing."""
    
    def test_missing_credentials(self):
        """Test parsing missing credentials error."""
        error = Exception("Could not automatically determine credentials")
        error_type, message = parse_gcp_error(error)
        
        assert error_type == "auth"
    
    def test_expired_token(self):
        """Test parsing expired token error."""
        error = Exception("Token has been expired or revoked")
        error_type, message = parse_gcp_error(error)
        
        assert error_type == "auth"
    
    def test_permission_denied(self):
        """Test parsing permission denied error."""
        error = Exception("Permission 'compute.networks.create' denied on resource")
        error_type, message = parse_gcp_error(error)
        
        assert error_type == "permission"


class TestHandleCloudError:
    """Tests for handle_cloud_error function."""
    
    def test_aws_auth_error(self):
        """Test handling AWS auth error."""
        error = Exception("InvalidClientTokenId: Invalid token")
        result = handle_cloud_error('aws', error, 'iam:CreateRole')
        
        assert result.status == CheckStatus.NOT_OK
        assert "AUTH ERROR" in result.message
    
    def test_azure_permission_error(self):
        """Test handling Azure permission error."""
        error = Exception("AuthorizationFailed: No permission")
        result = handle_cloud_error('azure', error, 'Microsoft.Network/virtualNetworks/write')
        
        assert result.status == CheckStatus.NOT_OK
        assert "DENIED" in result.message
    
    def test_quota_error(self):
        """Test handling quota error."""
        error = Exception("LimitExceededException: Quota exceeded")
        result = handle_cloud_error('aws', error, 's3:CreateBucket')
        
        assert result.status == CheckStatus.WARNING
        assert "QUOTA" in result.message
    
    def test_unknown_error(self):
        """Test handling unknown error."""
        error = Exception("Some random error occurred")
        result = handle_cloud_error('aws', error, 'some:Action')
        
        assert result.status == CheckStatus.WARNING
        assert "Error" in result.message

