# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Token verifier for the MCP OAuth flow.

Validates access tokens issued by our OAuth provider and injects the
corresponding AWS credentials into the request context so that tool
invocations use the authenticated user's permissions.
"""

import logging
from typing import Any, Optional

from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)


class AwsCredentialTokenVerifier:
    """Verifies MCP access tokens and sets up per-request AWS credentials.

    When the MCP client sends a Bearer token, this verifier:
    1. Looks up the token in our OAuth provider's store
    2. Extracts the associated AWS credentials
    3. Sets them in thread-local storage for the request
    """

    def __init__(self, oauth_provider):
        self._provider = oauth_provider

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        """Verify an access token and return its associated info.

        Called by FastMCP's auth middleware on every authenticated request.
        """
        stored = await self._provider.load_access_token(token)
        if stored is None:
            logger.debug("Token verification failed: token not found or expired")
            return None

        # Inject AWS credentials into thread-local storage for this request
        from .auth import DelegatedCredentials, set_request_credentials

        set_request_credentials(
            DelegatedCredentials(
                access_key_id=stored.aws_access_key_id,
                secret_access_key=stored.aws_secret_access_key,
                session_token=stored.aws_session_token,
                expiration=str(stored.expires_at),
                user_id=stored.user_id,
            )
        )

        return AccessToken(
            token=token,
            client_id=stored.client_id,
            scopes=stored.scopes,
        )
