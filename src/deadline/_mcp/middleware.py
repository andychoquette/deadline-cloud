# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
MCP server middleware for OAuth credential delegation.

This module patches the boto3 session creation to use per-request delegated
credentials when the server is running in 'oauth-delegation' mode. It hooks
into the existing `get_boto3_session` path so that all MCP tool functions
automatically use the authenticated user's scoped credentials without any
per-tool changes.
"""

import logging
from typing import Optional
from unittest.mock import patch
from configparser import ConfigParser

import boto3

from .auth import get_delegated_session

logger = logging.getLogger(__name__)

# Store the original function for fallback
_original_get_boto3_session = None


def _delegated_get_boto3_session(
    force_refresh: bool = False, config: Optional[ConfigParser] = None
) -> boto3.Session:
    """Replacement for get_boto3_session that uses delegated credentials when available.

    If delegated credentials are set for the current request thread, returns
    a session using those credentials. Otherwise, falls back to the original
    behavior (reading from ~/.deadline/config).
    """
    delegated = get_delegated_session()
    if delegated is not None:
        return delegated

    # Fall back to original behavior for local mode or unauthenticated paths
    if _original_get_boto3_session:
        return _original_get_boto3_session(force_refresh=force_refresh, config=config)

    # Should never reach here, but import as last resort
    from ..client.api._session import get_boto3_session

    return get_boto3_session(force_refresh=force_refresh, config=config)


def install_delegation_middleware() -> None:
    """Install the credential delegation middleware.

    Patches `deadline.client.api._session.get_boto3_session` so that all
    downstream API calls use per-request delegated credentials when available.

    This should be called once at server startup when auth_mode is 'oauth-delegation'.
    """
    global _original_get_boto3_session

    from ..client.api import _session

    _original_get_boto3_session = _session.get_boto3_session
    _session.get_boto3_session = _delegated_get_boto3_session

    # Also patch the cached client function since it uses the session object as a cache key.
    # With delegation, each request gets a different session, so we bypass the cache.
    _original_get_session_client = _session.get_session_client.__wrapped__  # unwrap lru_cache

    def _uncached_get_session_client(session: boto3.Session, service_name: str):
        from ..client.api._session import get_default_client_config

        return session.client(service_name, config=get_default_client_config())

    _session.get_session_client = _uncached_get_session_client

    logger.info("OAuth credential delegation middleware installed")


def uninstall_delegation_middleware() -> None:
    """Restore original session behavior. Primarily for testing."""
    global _original_get_boto3_session

    if _original_get_boto3_session is None:
        return

    from ..client.api import _session

    _session.get_boto3_session = _original_get_boto3_session
    _original_get_boto3_session = None

    logger.info("OAuth credential delegation middleware removed")
