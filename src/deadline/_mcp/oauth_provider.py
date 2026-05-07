# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
OAuth Authorization Server Provider for the remote MCP server.

Implements the MCP protocol's OAuth flow by proxying authentication to the
AWS Sign-In Service (same flow as `aws login` CLI and CTDX). The MCP server
acts as an intermediary OAuth server:

1. Claude Code (MCP client) discovers OAuth metadata from the server
2. Server redirects the user to AWS Sign-In Service for authentication
3. User authenticates in browser (Console login)
4. AWS Sign-In Service redirects back to the MCP server's callback
5. Server exchanges the auth code for AWS credentials
6. Server issues its own access token to the MCP client
7. On subsequent requests, the server uses the stored AWS credentials

This gives each user their own AWS session with their own IAM permissions.
"""

import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

from mcp.server.auth.provider import (
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)

# AWS Sign-In Service endpoints (same as `aws login` CLI)
AWS_SIGNIN_REGION = os.environ.get("AWS_REGION", "us-west-2")
AWS_AUTHORIZE_URL = f"https://{AWS_SIGNIN_REGION}.signin.aws.amazon.com/authorize"
AWS_TOKEN_URL = f"https://{AWS_SIGNIN_REGION}.signin.aws.amazon.com/token"

# MCP server's own client ID for the AWS Sign-In Service
# This is a public client (no secret), similar to AWS CLI
AWS_SIGNIN_CLIENT_ID = "arn:aws:signin:::console/canvas"
AWS_SIGNIN_SCOPES = ["sts:*"]


@dataclass
class StoredAuthCode:
    """Authorization code with associated PKCE and redirect info."""

    code: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    aws_credentials: Optional[dict] = None
    created_at: float = field(default_factory=time.time)
    scopes: list[str] = field(default_factory=list)


@dataclass
class StoredAccessToken:
    """Access token mapped to AWS credentials."""

    token: str
    client_id: str
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_session_token: str
    expires_at: float
    user_id: str
    scopes: list[str] = field(default_factory=list)


@dataclass
class StoredRefreshToken:
    """Refresh token for obtaining new AWS credentials."""

    token: str
    client_id: str
    aws_refresh_token: str
    user_id: str
    scopes: list[str] = field(default_factory=list)


class AwsSignInOAuthProvider(OAuthAuthorizationServerProvider):
    """OAuth provider that delegates authentication to AWS Sign-In Service.

    This implements the MCP OAuth protocol by acting as an intermediary:
    - The MCP client authenticates with this server
    - This server proxies the auth to AWS Sign-In Service
    - User credentials are stored server-side and used for API calls
    """

    def __init__(self):
        # In-memory stores (use Redis/DDB for production)
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, StoredAuthCode] = {}
        self._access_tokens: dict[str, StoredAccessToken] = {}
        self._refresh_tokens: dict[str, StoredRefreshToken] = {}
        # Map AWS Sign-In state → our auth code context
        self._pending_auth: dict[str, dict] = {}

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Dynamic client registration — MCP clients register on first connection."""
        self._clients[client_info.client_id] = client_info
        logger.info(f"Registered MCP client: {client_info.client_id}")

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Redirect the user to AWS Sign-In Service for authentication.

        This is the core of the CTDX-style flow: we construct an AWS Sign-In
        authorization URL and redirect the user there. When they complete login,
        AWS redirects back to our callback endpoint.
        """
        import urllib.parse

        # Generate a state token to correlate the AWS callback with this auth request
        aws_state = secrets.token_urlsafe(32)

        # Store the pending auth context so we can complete it on callback
        self._pending_auth[aws_state] = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "code_challenge_method": params.code_challenge_method or "S256",
            "scopes": params.scopes or [],
            "mcp_state": params.state,
        }

        # Build the AWS Sign-In authorization URL
        # This matches the CTDX/AWS CLI `aws login` flow
        aws_auth_params = {
            "response_type": "code",
            "client_id": AWS_SIGNIN_CLIENT_ID,
            "redirect_uri": self._get_our_callback_url(),
            "state": aws_state,
            "scopes": " ".join(AWS_SIGNIN_SCOPES),
        }

        authorize_url = f"{AWS_AUTHORIZE_URL}?{urllib.parse.urlencode(aws_auth_params)}"
        logger.info(f"Redirecting user to AWS Sign-In: {authorize_url}")
        return authorize_url

    async def handle_aws_callback(self, code: str, state: str) -> str:
        """Handle the callback from AWS Sign-In Service.

        Called when the user completes authentication on AWS. We exchange the
        AWS auth code for credentials, then generate our own auth code to
        return to the MCP client.

        Returns the redirect URL for the MCP client with our auth code.
        """
        pending = self._pending_auth.pop(state, None)
        if not pending:
            raise ValueError("Invalid or expired state parameter")

        # Exchange the AWS code for credentials
        aws_credentials = await self._exchange_aws_code(code)

        # Generate our own authorization code for the MCP client
        our_code = secrets.token_urlsafe(32)
        self._auth_codes[our_code] = StoredAuthCode(
            code=our_code,
            client_id=pending["client_id"],
            redirect_uri=pending["redirect_uri"],
            code_challenge=pending["code_challenge"],
            code_challenge_method=pending["code_challenge_method"],
            aws_credentials=aws_credentials,
            scopes=pending["scopes"],
        )

        # Redirect back to the MCP client with our auth code
        import urllib.parse

        redirect_params = {
            "code": our_code,
            "state": pending["mcp_state"],
        }
        redirect_url = f"{pending['redirect_uri']}?{urllib.parse.urlencode(redirect_params)}"
        return redirect_url

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[StoredAuthCode]:
        stored = self._auth_codes.get(authorization_code)
        if stored and stored.client_id == client.client_id:
            # Expire after 10 minutes
            if time.time() - stored.created_at > 600:
                del self._auth_codes[authorization_code]
                return None
            return stored
        return None

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: StoredAuthCode
    ) -> OAuthToken:
        """Exchange our auth code for an access token backed by AWS credentials."""
        # Remove the code (single use)
        self._auth_codes.pop(authorization_code.code, None)

        aws_creds = authorization_code.aws_credentials
        if not aws_creds:
            raise ValueError("No AWS credentials associated with auth code")

        # Generate access token
        access_token = secrets.token_urlsafe(48)
        expires_in = aws_creds.get("expires_in", 3600)

        self._access_tokens[access_token] = StoredAccessToken(
            token=access_token,
            client_id=client.client_id,
            aws_access_key_id=aws_creds["access_key_id"],
            aws_secret_access_key=aws_creds["secret_access_key"],
            aws_session_token=aws_creds["session_token"],
            expires_at=time.time() + expires_in,
            user_id=aws_creds.get("user_id", "unknown"),
            scopes=authorization_code.scopes,
        )

        # Generate refresh token if AWS provided one
        refresh_token = None
        if aws_creds.get("refresh_token"):
            refresh_token = secrets.token_urlsafe(48)
            self._refresh_tokens[refresh_token] = StoredRefreshToken(
                token=refresh_token,
                client_id=client.client_id,
                aws_refresh_token=aws_creds["refresh_token"],
                user_id=aws_creds.get("user_id", "unknown"),
                scopes=authorization_code.scopes,
            )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    async def load_access_token(self, token: str) -> Optional[StoredAccessToken]:
        stored = self._access_tokens.get(token)
        if stored and time.time() < stored.expires_at:
            # Inject AWS credentials into thread-local for this request
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
            return stored
        if stored:
            del self._access_tokens[token]
        return None

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[StoredRefreshToken]:
        stored = self._refresh_tokens.get(refresh_token)
        if stored and stored.client_id == client.client_id:
            return stored
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: StoredRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Use the AWS refresh token to get new credentials."""
        # Call AWS Sign-In token endpoint with refresh_token grant
        new_creds = await self._refresh_aws_credentials(refresh_token.aws_refresh_token)

        # Revoke old access tokens for this user
        old_tokens = [
            k for k, v in self._access_tokens.items() if v.user_id == refresh_token.user_id
        ]
        for k in old_tokens:
            del self._access_tokens[k]

        # Issue new access token
        access_token = secrets.token_urlsafe(48)
        expires_in = new_creds.get("expires_in", 900)

        self._access_tokens[access_token] = StoredAccessToken(
            token=access_token,
            client_id=client.client_id,
            aws_access_key_id=new_creds["access_key_id"],
            aws_secret_access_key=new_creds["secret_access_key"],
            aws_session_token=new_creds["session_token"],
            expires_at=time.time() + expires_in,
            user_id=refresh_token.user_id,
            scopes=scopes or refresh_token.scopes,
        )

        # Rotate refresh token
        new_refresh = secrets.token_urlsafe(48)
        del self._refresh_tokens[refresh_token.token]
        self._refresh_tokens[new_refresh] = StoredRefreshToken(
            token=new_refresh,
            client_id=client.client_id,
            aws_refresh_token=new_creds.get("refresh_token", refresh_token.aws_refresh_token),
            user_id=refresh_token.user_id,
            scopes=scopes or refresh_token.scopes,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=new_refresh,
            scope=" ".join(scopes) if scopes else None,
        )

    async def revoke_token(self, token) -> None:
        """Revoke an access or refresh token."""
        if isinstance(token, StoredAccessToken):
            self._access_tokens.pop(token.token, None)
        elif isinstance(token, StoredRefreshToken):
            self._refresh_tokens.pop(token.token, None)

    # --- AWS Sign-In Service integration ---

    async def _exchange_aws_code(self, code: str) -> dict:
        """Exchange an AWS Sign-In authorization code for credentials.

        This matches the CTDX token_exchange.rs logic:
        - POST to AWS Sign-In token endpoint
        - Include DPoP proof (for production; simplified here for dev)
        - Returns access_key_id, secret_access_key, session_token, refresh_token
        """
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                AWS_TOKEN_URL,
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": AWS_SIGNIN_CLIENT_ID,
                    "redirect_uri": self._get_our_callback_url(),
                },
                headers={"Content-Type": "application/json"},
            )

            if response.status_code != 200:
                logger.error(f"AWS token exchange failed: {response.status_code} {response.text}")
                raise ValueError(f"AWS token exchange failed: {response.status_code}")

            data = response.json()
            return {
                "access_key_id": data.get("accessKeyId"),
                "secret_access_key": data.get("secretAccessKey"),
                "session_token": data.get("sessionToken"),
                "refresh_token": data.get("refreshToken"),
                "expires_in": data.get("expiresIn", 900),
                "user_id": data.get("loginSessionArn", "unknown"),
            }

    async def _refresh_aws_credentials(self, refresh_token: str) -> dict:
        """Use an AWS refresh token to get new credentials."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                AWS_TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": AWS_SIGNIN_CLIENT_ID,
                },
                headers={"Content-Type": "application/json"},
            )

            if response.status_code != 200:
                logger.error(f"AWS token refresh failed: {response.status_code}")
                raise ValueError(f"AWS token refresh failed: {response.status_code}")

            data = response.json()
            return {
                "access_key_id": data.get("accessKeyId"),
                "secret_access_key": data.get("secretAccessKey"),
                "session_token": data.get("sessionToken"),
                "refresh_token": data.get("refreshToken"),
                "expires_in": data.get("expiresIn", 900),
            }

    def _get_our_callback_url(self) -> str:
        """Get the URL where AWS Sign-In will redirect after user authenticates."""
        server_url = os.environ.get(
            "MCP_SERVER_URL", "https://5grpve61a5.execute-api.us-west-2.amazonaws.com"
        )
        return f"{server_url}/oauth/callback"
