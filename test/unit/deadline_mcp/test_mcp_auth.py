# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Unit tests for MCP OAuth credential delegation."""

import base64
import json
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_jwt_token():
    """Create a sample JWT token for testing."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "sub": "user-12345-abcde",
                "iss": "https://identitycenter.amazonaws.com/ssoins-12345",
                "aud": ["mcp-client-id"],
                "exp": int(time.time()) + 3600,
            }
        ).encode()
    ).rstrip(b"=")
    signature = base64.urlsafe_b64encode(b"fake-signature").rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.{signature.decode()}"


@pytest.fixture
def expired_jwt_token():
    """Create an expired JWT token."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "sub": "user-expired",
                "iss": "https://identitycenter.amazonaws.com/ssoins-12345",
                "aud": ["mcp-client-id"],
                "exp": int(time.time()) - 3600,
            }
        ).encode()
    ).rstrip(b"=")
    signature = base64.urlsafe_b64encode(b"fake-signature").rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.{signature.decode()}"


@pytest.fixture
def mock_env(monkeypatch):
    """Set environment variables for OAuth delegation."""
    monkeypatch.setenv("IDC_ISSUER_URL", "https://identitycenter.amazonaws.com/ssoins-12345")
    monkeypatch.setenv("DELEGATION_ROLE_ARN", "arn:aws:iam::123456789012:role/DeadlineMcpUserDelegation")
    monkeypatch.setenv("EXPECTED_AUDIENCE", "mcp-client-id")


class TestOAuthCredentialDelegator:
    def test_extract_user_id_from_token(self, sample_jwt_token, mock_env):
        from deadline._mcp.auth import OAuthCredentialDelegator

        delegator = OAuthCredentialDelegator()
        user_id = delegator._extract_user_id(sample_jwt_token)
        assert user_id == "user-12345-abcde"

    def test_extract_user_id_invalid_token(self, mock_env):
        from deadline._mcp.auth import OAuthCredentialDelegator

        delegator = OAuthCredentialDelegator()
        assert delegator._extract_user_id("not-a-jwt") == "unknown"
        assert delegator._extract_user_id("") == "unknown"

    @patch("boto3.client")
    def test_exchange_token_success(self, mock_boto_client, sample_jwt_token, mock_env):
        from deadline._mcp.auth import OAuthCredentialDelegator

        mock_sts = MagicMock()
        mock_boto_client.return_value = mock_sts
        mock_sts.assume_role_with_web_identity.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
                "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                "SessionToken": "session-token-123",
                "Expiration": datetime(2025, 1, 1, tzinfo=timezone.utc),
            }
        }

        delegator = OAuthCredentialDelegator()
        creds = delegator.exchange_token(sample_jwt_token)

        assert creds.access_key_id == "AKIAIOSFODNN7EXAMPLE"
        assert creds.secret_access_key == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        assert creds.session_token == "session-token-123"
        assert creds.user_id == "user-12345-abcde"

        mock_sts.assume_role_with_web_identity.assert_called_once_with(
            RoleArn="arn:aws:iam::123456789012:role/DeadlineMcpUserDelegation",
            RoleSessionName="mcp-user-12345-abcde",
            WebIdentityToken=sample_jwt_token,
            DurationSeconds=3600,
        )

    @patch("boto3.client")
    def test_exchange_token_caches_result(self, mock_boto_client, sample_jwt_token, mock_env):
        from deadline._mcp.auth import OAuthCredentialDelegator

        mock_sts = MagicMock()
        mock_boto_client.return_value = mock_sts
        mock_sts.assume_role_with_web_identity.return_value = {
            "Credentials": {
                "AccessKeyId": "AKID",
                "SecretAccessKey": "SECRET",
                "SessionToken": "TOKEN",
                "Expiration": datetime(2025, 1, 1, tzinfo=timezone.utc),
            }
        }

        delegator = OAuthCredentialDelegator()
        creds1 = delegator.exchange_token(sample_jwt_token)
        creds2 = delegator.exchange_token(sample_jwt_token)

        # STS should only be called once — second call uses cache
        assert mock_sts.assume_role_with_web_identity.call_count == 1
        assert creds1.access_key_id == creds2.access_key_id

    @patch("boto3.client")
    def test_exchange_token_expired_raises(self, mock_boto_client, sample_jwt_token, mock_env):
        from deadline._mcp.auth import AuthenticationError, OAuthCredentialDelegator

        mock_sts = MagicMock()
        mock_boto_client.return_value = mock_sts

        # Simulate ExpiredTokenException
        error_response = {"Error": {"Code": "ExpiredTokenException", "Message": "Token expired"}}
        mock_sts.assume_role_with_web_identity.side_effect = (
            mock_sts.exceptions.ExpiredTokenException(error_response, "AssumeRoleWithWebIdentity")
        )
        mock_sts.exceptions.ExpiredTokenException = type(
            "ExpiredTokenException", (Exception,), {}
        )
        mock_sts.exceptions.MalformedPolicyDocumentException = type(
            "MalformedPolicyDocumentException", (Exception,), {}
        )
        mock_sts.exceptions.InvalidIdentityTokenException = type(
            "InvalidIdentityTokenException", (Exception,), {}
        )

        mock_sts.assume_role_with_web_identity.side_effect = (
            mock_sts.exceptions.ExpiredTokenException()
        )

        delegator = OAuthCredentialDelegator()
        with pytest.raises(AuthenticationError, match="expired"):
            delegator.exchange_token(sample_jwt_token)


class TestRequestCredentials:
    def test_thread_isolation(self, mock_env):
        from deadline._mcp.auth import (
            DelegatedCredentials,
            get_delegated_session,
            set_request_credentials,
            clear_request_credentials,
        )

        creds_a = DelegatedCredentials(
            access_key_id="KEY_A",
            secret_access_key="SECRET_A",
            session_token="TOKEN_A",
            expiration="2025-01-01T00:00:00Z",
            user_id="user-a",
        )
        creds_b = DelegatedCredentials(
            access_key_id="KEY_B",
            secret_access_key="SECRET_B",
            session_token="TOKEN_B",
            expiration="2025-01-01T00:00:00Z",
            user_id="user-b",
        )

        results = {}

        def thread_a():
            set_request_credentials(creds_a)
            time.sleep(0.05)  # Ensure threads overlap
            session = get_delegated_session()
            results["a"] = session.get_credentials().access_key if session else None
            clear_request_credentials()

        def thread_b():
            set_request_credentials(creds_b)
            time.sleep(0.05)
            session = get_delegated_session()
            results["b"] = session.get_credentials().access_key if session else None
            clear_request_credentials()

        t1 = threading.Thread(target=thread_a)
        t2 = threading.Thread(target=thread_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results["a"] == "KEY_A"
        assert results["b"] == "KEY_B"

    def test_no_credentials_returns_none(self):
        from deadline._mcp.auth import clear_request_credentials, get_delegated_session

        clear_request_credentials()
        assert get_delegated_session() is None


class TestMiddleware:
    def test_install_patches_get_boto3_session(self, mock_env):
        from deadline._mcp.middleware import (
            install_delegation_middleware,
            uninstall_delegation_middleware,
        )
        from deadline.client.api import _session

        original_fn = _session.get_boto3_session

        try:
            install_delegation_middleware()
            assert _session.get_boto3_session is not original_fn
        finally:
            uninstall_delegation_middleware()
            assert _session.get_boto3_session is original_fn

    def test_delegated_session_used_when_credentials_set(self, mock_env):
        from deadline._mcp.auth import DelegatedCredentials, set_request_credentials, clear_request_credentials
        from deadline._mcp.middleware import (
            _delegated_get_boto3_session,
        )

        creds = DelegatedCredentials(
            access_key_id="DELEGATED_KEY",
            secret_access_key="DELEGATED_SECRET",
            session_token="DELEGATED_TOKEN",
            expiration="2025-01-01T00:00:00Z",
            user_id="test-user",
        )

        set_request_credentials(creds)
        try:
            session = _delegated_get_boto3_session()
            resolved_creds = session.get_credentials().get_frozen_credentials()
            assert resolved_creds.access_key == "DELEGATED_KEY"
            assert resolved_creds.secret_key == "DELEGATED_SECRET"
            assert resolved_creds.token == "DELEGATED_TOKEN"
        finally:
            clear_request_credentials()
