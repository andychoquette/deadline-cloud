# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
OAuth credential delegation for the remote MCP server.

When running in 'oauth-delegation' mode, the MCP server validates incoming
OAuth Bearer tokens and exchanges them for scoped AWS credentials via
STS AssumeRoleWithWebIdentity. Each MCP tool call then uses credentials
that represent the authenticated user, preserving per-user IAM authorization
at the Deadline Cloud API layer.
"""

import logging
import os
import threading
import time
from configparser import ConfigParser
from dataclasses import dataclass
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

# Thread-local storage for per-request credentials
_request_credentials: threading.local = threading.local()


@dataclass
class DelegatedCredentials:
    """Temporary AWS credentials obtained via OAuth token exchange."""

    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: str
    user_id: str


def get_delegated_session() -> Optional[boto3.Session]:
    """Get a boto3 session using the current request's delegated credentials.

    Returns None if no delegated credentials are set for the current thread
    (i.e., running in local mode or no auth token was provided).
    """
    creds = getattr(_request_credentials, "current", None)
    if creds is None:
        return None

    return boto3.Session(
        aws_access_key_id=creds.access_key_id,
        aws_secret_access_key=creds.secret_access_key,
        aws_session_token=creds.session_token,
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-west-2"),
    )


def set_request_credentials(creds: Optional[DelegatedCredentials]) -> None:
    """Set delegated credentials for the current request thread."""
    _request_credentials.current = creds


def clear_request_credentials() -> None:
    """Clear credentials after a request completes."""
    _request_credentials.current = None


class OAuthCredentialDelegator:
    """Handles OAuth token validation and credential delegation.

    Validates incoming Bearer tokens against the configured IdC issuer
    and exchanges them for scoped AWS credentials via STS.
    """

    def __init__(
        self,
        issuer_url: Optional[str] = None,
        delegation_role_arn: Optional[str] = None,
        expected_audience: Optional[str] = None,
    ):
        self.issuer_url = issuer_url or os.environ.get("IDC_ISSUER_URL", "")
        self.delegation_role_arn = delegation_role_arn or os.environ.get(
            "DELEGATION_ROLE_ARN", ""
        )
        self.expected_audience = expected_audience or os.environ.get(
            "EXPECTED_AUDIENCE", ""
        )
        self._sts_client = boto3.client("sts")
        self._credential_cache: dict[str, tuple[DelegatedCredentials, float]] = {}
        self._cache_lock = threading.Lock()

    def exchange_token(self, bearer_token: str) -> DelegatedCredentials:
        """Exchange an OAuth Bearer token for scoped AWS credentials.

        Args:
            bearer_token: The OAuth access token from the Authorization header.

        Returns:
            DelegatedCredentials with temporary AWS creds scoped to the user.

        Raises:
            AuthenticationError: If the token is invalid or expired.
            CredentialDelegationError: If STS AssumeRoleWithWebIdentity fails.
        """
        # Check cache first (tokens are valid for ~1hr, avoid redundant STS calls)
        cached = self._get_cached(bearer_token)
        if cached:
            return cached

        # Extract user identity from token (for session naming)
        user_id = self._extract_user_id(bearer_token)

        try:
            response = self._sts_client.assume_role_with_web_identity(
                RoleArn=self.delegation_role_arn,
                RoleSessionName=f"mcp-{user_id[:32]}",
                WebIdentityToken=bearer_token,
                DurationSeconds=3600,
            )
        except self._sts_client.exceptions.ExpiredTokenException:
            raise AuthenticationError("OAuth token has expired. Please re-authenticate.")
        except self._sts_client.exceptions.MalformedPolicyDocumentException as e:
            raise CredentialDelegationError(
                f"Delegation role policy error: {e}"
            )
        except self._sts_client.exceptions.InvalidIdentityTokenException as e:
            raise AuthenticationError(f"Invalid OAuth token: {e}")
        except Exception as e:
            raise CredentialDelegationError(
                f"Failed to assume delegation role: {e}"
            )

        credentials = response["Credentials"]
        delegated = DelegatedCredentials(
            access_key_id=credentials["AccessKeyId"],
            secret_access_key=credentials["SecretAccessKey"],
            session_token=credentials["SessionToken"],
            expiration=credentials["Expiration"].isoformat(),
            user_id=user_id,
        )

        # Cache for 50 minutes (credentials last 60 min, leave buffer)
        self._put_cached(bearer_token, delegated, ttl=3000)

        logger.info(f"Issued delegated credentials for user {user_id}")
        return delegated

    def _extract_user_id(self, token: str) -> str:
        """Extract the subject (user ID) from the JWT token payload.

        This does a base64 decode of the payload only — cryptographic
        validation is performed by STS when it verifies the token against
        the OIDC provider's trust policy.
        """
        import base64
        import json

        try:
            parts = token.split(".")
            if len(parts) != 3:
                return "unknown"

            payload = parts[1]
            # Add base64 padding
            payload += "=" * (4 - len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload)
            claims = json.loads(decoded)
            return claims.get("sub", "unknown")
        except Exception:
            return "unknown"

    def _get_cached(self, token: str) -> Optional[DelegatedCredentials]:
        """Retrieve cached credentials if still valid."""
        with self._cache_lock:
            if token in self._credential_cache:
                creds, expires_at = self._credential_cache[token]
                if time.time() < expires_at:
                    return creds
                del self._credential_cache[token]
        return None

    def _put_cached(
        self, token: str, creds: DelegatedCredentials, ttl: float
    ) -> None:
        """Cache credentials with a TTL."""
        with self._cache_lock:
            self._credential_cache[token] = (creds, time.time() + ttl)

            # Evict expired entries periodically
            if len(self._credential_cache) > 100:
                now = time.time()
                expired = [
                    k
                    for k, (_, exp) in self._credential_cache.items()
                    if now >= exp
                ]
                for k in expired:
                    del self._credential_cache[k]


class AuthenticationError(Exception):
    """Raised when OAuth token validation fails."""

    pass


class CredentialDelegationError(Exception):
    """Raised when STS AssumeRoleWithWebIdentity fails."""

    pass
