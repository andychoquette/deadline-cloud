"""
Token Exchange Lambda

Validates an incoming OAuth access token (from IAM Identity Center) and returns
temporary AWS credentials scoped to the authenticated user.

This Lambda is called by the MCP server when it needs to obtain per-user credentials
for Deadline Cloud API calls.

Flow:
1. MCP server receives a request with an OAuth Bearer token
2. MCP server invokes this Lambda with the token
3. This Lambda validates the token with the IdC issuer
4. If valid, it calls STS AssumeRoleWithWebIdentity to get scoped credentials
5. Returns the temporary credentials to the MCP server

The MCP server then uses these credentials to call the Deadline Cloud API
as the authenticated user.
"""

import json
import logging
import os

import boto3
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DELEGATION_ROLE_ARN = os.environ["DELEGATION_ROLE_ARN"]
IDC_ISSUER_URL = os.environ["IDC_ISSUER_URL"]
EXPECTED_AUDIENCE = os.environ["EXPECTED_AUDIENCE"]


def handler(event, context):
    """Exchange an IdC access token for scoped AWS credentials."""
    try:
        token = event.get("token")
        if not token:
            return _error_response(400, "Missing token in request")

        # Validate the token and extract claims
        # In production, verify JWT signature against IdC JWKS
        claims = _validate_token(token)
        if not claims:
            return _error_response(401, "Invalid or expired token")

        user_id = claims.get("sub")
        if not user_id:
            return _error_response(401, "Token missing subject claim")

        # Assume the delegation role with the user's web identity
        sts = boto3.client("sts")
        response = sts.assume_role_with_web_identity(
            RoleArn=DELEGATION_ROLE_ARN,
            RoleSessionName=f"mcp-{user_id[:32]}",
            WebIdentityToken=token,
            DurationSeconds=3600,
        )

        credentials = response["Credentials"]

        logger.info(f"Issued credentials for user {user_id}, session: mcp-{user_id[:32]}")

        return {
            "statusCode": 200,
            "body": {
                "accessKeyId": credentials["AccessKeyId"],
                "secretAccessKey": credentials["SecretAccessKey"],
                "sessionToken": credentials["SessionToken"],
                "expiration": credentials["Expiration"].isoformat(),
                "userId": user_id,
            },
        }

    except sts.exceptions.MalformedPolicyDocumentException as e:
        logger.error(f"Role policy error: {e}")
        return _error_response(500, "Credential delegation configuration error")
    except sts.exceptions.ExpiredTokenException:
        return _error_response(401, "Token has expired")
    except Exception as e:
        logger.error(f"Token exchange failed: {e}", exc_info=True)
        return _error_response(500, "Internal error during token exchange")


def _validate_token(token: str) -> dict:
    """
    Validate the OAuth token against the Identity Center issuer.

    In production, this should:
    1. Fetch the JWKS from {IDC_ISSUER_URL}/.well-known/jwks.json
    2. Verify the JWT signature
    3. Check expiration, audience, and issuer claims

    For now, we rely on STS AssumeRoleWithWebIdentity to validate the token
    (it verifies the token against the OIDC provider's trust policy).
    """
    # Minimal decode to extract claims for logging/session naming
    # STS does the actual cryptographic validation
    import base64

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        # Decode payload (part 1)
        payload = parts[1]
        # Add padding if needed
        payload += "=" * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)

        # Basic claim checks
        if claims.get("iss") != IDC_ISSUER_URL:
            logger.warning(f"Token issuer mismatch: {claims.get('iss')}")
            return None

        if EXPECTED_AUDIENCE not in claims.get("aud", []):
            logger.warning(f"Token audience mismatch: {claims.get('aud')}")
            return None

        return claims

    except Exception as e:
        logger.warning(f"Token decode failed: {e}")
        return None


def _error_response(status_code: int, message: str) -> dict:
    return {
        "statusCode": status_code,
        "body": {"error": message},
    }
