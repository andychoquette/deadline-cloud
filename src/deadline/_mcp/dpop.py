# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
DPoP (Demonstrating Proof-of-Possession) implementation for AWS Sign-In Service.

Implements RFC 9449 DPoP JWT creation using an ephemeral P-256 key pair.
AWS Sign-In Service requires DPoP proof headers on token exchange requests
to bind tokens to the specific client making the request.

The DPoP JWT structure:
  Header: {"typ": "dpop+jwt", "alg": "ES256", "jwk": {P-256 public key}}
  Payload: {"htm": "POST", "htu": "<token endpoint>", "iat": <timestamp>, "jti": <uuid>}
  Signature: ES256 (ECDSA with P-256 and SHA-256)
"""

import base64
import json
import time
import uuid
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


def _b64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int_to_bytes(n: int, length: int) -> bytes:
    """Convert an integer to bytes of specified length (big-endian)."""
    return n.to_bytes(length, byteorder="big")


@dataclass
class DpopKeyPair:
    """Ephemeral EC P-256 key pair for DPoP proof generation."""

    _private_key: ec.EllipticCurvePrivateKey

    @classmethod
    def generate(cls) -> "DpopKeyPair":
        """Generate a new P-256 key pair."""
        private_key = ec.generate_private_key(ec.SECP256R1())
        return cls(_private_key=private_key)

    def create_dpop_token(self, http_method: str, http_uri: str) -> str:
        """Create a DPoP JWT proof token.

        Args:
            http_method: HTTP method (e.g., "POST")
            http_uri: Full URL of the endpoint (e.g., the token endpoint)

        Returns:
            A signed DPoP JWT string.
        """
        # Extract public key coordinates
        public_numbers = self._private_key.public_key().public_numbers()
        x_bytes = _int_to_bytes(public_numbers.x, 32)
        y_bytes = _int_to_bytes(public_numbers.y, 32)

        # Build JWK (public key only)
        jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": _b64url_encode(x_bytes),
            "y": _b64url_encode(y_bytes),
        }

        # Build JWT header
        header = {
            "typ": "dpop+jwt",
            "alg": "ES256",
            "jwk": jwk,
        }

        # Build JWT payload
        payload = {
            "htm": http_method,
            "htu": http_uri,
            "iat": int(time.time()),
            "jti": str(uuid.uuid4()),
        }

        # Encode header and payload
        header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())

        # Sign
        message = f"{header_b64}.{payload_b64}".encode()
        der_signature = self._private_key.sign(message, ec.ECDSA(hashes.SHA256()))

        # Convert DER signature to raw r||s format (64 bytes) as required by JWS
        r, s = decode_dss_signature(der_signature)
        raw_signature = _int_to_bytes(r, 32) + _int_to_bytes(s, 32)
        signature_b64 = _b64url_encode(raw_signature)

        return f"{header_b64}.{payload_b64}.{signature_b64}"

    def to_pem(self) -> str:
        """Export the private key as PEM (SEC1 format for AWS SDK compatibility)."""
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
