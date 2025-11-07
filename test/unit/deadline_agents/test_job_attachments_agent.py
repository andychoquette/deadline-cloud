# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Unit tests for the job attachments agent."""

import pytest
from unittest.mock import patch, MagicMock

# Skip all tests if strands-agents is not available
pytest.importorskip("strands", reason="strands-agents dependencies not available")

from deadline._agents.agents.job_attachments_agent import (
    job_attachments_agent,
    check_s3_bucket_exists,
    get_bucket_policy,
    check_bucket_permissions,
    get_bucket_encryption,
    get_bucket_versioning,
    list_bucket_objects,
    get_s3_client_with_queue_role,
)


@pytest.fixture
def mock_s3_client():
    """Mock boto3 S3 client."""
    client = MagicMock()
    return client


@pytest.fixture
def mock_agent():
    """Mock Strands Agent for testing."""
    agent = MagicMock()
    agent.return_value = "Job attachments analysis complete"
    return agent


@pytest.fixture
def mock_telemetry_client():
    """Mock telemetry client for testing."""
    client = MagicMock()
    client.is_initialized = True
    client.record_event = MagicMock()
    return client


def test_job_attachments_agent_basic(mock_agent):
    """Test basic job attachments agent invocation."""
    with patch("deadline._agents.agents.job_attachments_agent.Agent", return_value=mock_agent):
        with patch("deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"):
            result = job_attachments_agent(
                "Check bucket access for queue queue-123", farm_id="farm-456", queue_id="queue-123"
            )

            assert "Job attachments analysis complete" in result
            mock_agent.assert_called_once()


def test_job_attachments_agent_with_farm_queue_context(mock_agent):
    """Test that farm_id and queue_id are added to system prompt."""
    with patch(
        "deadline._agents.agents.job_attachments_agent.Agent", return_value=mock_agent
    ) as mock_agent_class:
        with patch("deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"):
            job_attachments_agent("Check bucket access", farm_id="farm-456", queue_id="queue-123")

            # Verify system prompt includes farm_id and queue_id
            call_kwargs = mock_agent_class.call_args[1]
            system_prompt = call_kwargs["system_prompt"]

            assert "farm-456" in system_prompt
            assert "queue-123" in system_prompt
            assert "MANDATORY PARAMETERS" in system_prompt


def test_job_attachments_agent_uses_correct_model(mock_agent):
    """Test that job attachments agent uses the correct model."""
    with patch(
        "deadline._agents.agents.job_attachments_agent.Agent", return_value=mock_agent
    ) as mock_agent_class:
        with patch(
            "deadline._agents.agents.job_attachments_agent.get_job_attachments_model"
        ) as mock_get_model:
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ):
                mock_model = MagicMock()
                mock_get_model.return_value = mock_model

                job_attachments_agent("Check bucket access")

                # Verify model was retrieved
                mock_get_model.assert_called_once()

                # Verify Agent was created with the model
                call_kwargs = mock_agent_class.call_args[1]
                assert call_kwargs["model"] == mock_model


def test_job_attachments_agent_has_callback_handler(mock_agent):
    """Test that job attachments agent has a callback handler for streaming."""
    with patch(
        "deadline._agents.agents.job_attachments_agent.Agent", return_value=mock_agent
    ) as mock_agent_class:
        with patch("deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"):
            job_attachments_agent("Check bucket access")

            # Verify Agent was created with a callback_handler
            call_kwargs = mock_agent_class.call_args[1]
            assert call_kwargs["callback_handler"] is not None
            assert callable(call_kwargs["callback_handler"])


def test_job_attachments_agent_error_handling():
    """Test job attachments agent error handling."""
    mock_agent = MagicMock()
    mock_agent.side_effect = Exception("Test error")

    with patch("deadline._agents.agents.job_attachments_agent.Agent", return_value=mock_agent):
        with patch("deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"):
            result = job_attachments_agent("Check bucket access")

            assert "Error in job attachments agent" in result
            assert "Test error" in result


def test_check_s3_bucket_exists_success(mock_s3_client):
    """Test check_s3_bucket_exists with successful response."""
    mock_s3_client.get_bucket_location.return_value = {"LocationConstraint": "us-west-2"}

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = check_s3_bucket_exists("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "Bucket exists" in result
        assert "us-west-2" in result


def test_check_s3_bucket_exists_no_credentials():
    """Test check_s3_bucket_exists without farm_id/queue_id."""
    result = check_s3_bucket_exists("test-bucket")

    assert "ERROR" in result
    assert "farm_id and queue_id are REQUIRED" in result


def test_check_s3_bucket_exists_not_found(mock_s3_client):
    """Test check_s3_bucket_exists with bucket not found."""
    mock_s3_client.exceptions.NoSuchBucket = type("NoSuchBucket", (Exception,), {})
    mock_s3_client.get_bucket_location.side_effect = mock_s3_client.exceptions.NoSuchBucket()

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = check_s3_bucket_exists("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "Bucket does not exist" in result


def test_get_bucket_policy_success(mock_s3_client):
    """Test get_bucket_policy with successful response."""
    mock_s3_client.get_bucket_policy.return_value = {
        "Policy": '{"Version": "2012-10-17", "Statement": []}'
    }

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = get_bucket_policy("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "Bucket Policy" in result
        assert "2012-10-17" in result


def test_get_bucket_policy_no_policy(mock_s3_client):
    """Test get_bucket_policy with no policy configured."""
    # Create a proper exception class for NoSuchBucket
    NoSuchBucket = type("NoSuchBucket", (Exception,), {})
    mock_s3_client.exceptions = MagicMock()
    mock_s3_client.exceptions.NoSuchBucket = NoSuchBucket

    mock_s3_client.get_bucket_policy.side_effect = Exception("NoSuchBucketPolicy")

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = get_bucket_policy("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "No bucket policy configured" in result


def test_check_bucket_permissions_success(mock_s3_client):
    """Test check_bucket_permissions with successful permissions."""
    mock_s3_client.list_objects_v2.return_value = {}
    mock_s3_client.head_object.side_effect = Exception("404")
    mock_s3_client.get_bucket_acl.return_value = {}

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = check_bucket_permissions("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "ListBucket: ALLOWED" in result
        assert "GetObject: ALLOWED" in result
        assert "GetBucketAcl: ALLOWED" in result


def test_check_bucket_permissions_denied(mock_s3_client):
    """Test check_bucket_permissions with denied permissions."""
    mock_s3_client.list_objects_v2.side_effect = Exception("403 Forbidden")

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = check_bucket_permissions("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "ListBucket: DENIED" in result


def test_get_bucket_encryption_success(mock_s3_client):
    """Test get_bucket_encryption with encryption configured."""
    mock_s3_client.get_bucket_encryption.return_value = {
        "ServerSideEncryptionConfiguration": {
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        }
    }

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = get_bucket_encryption("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "AES256" in result


def test_get_bucket_encryption_not_configured(mock_s3_client):
    """Test get_bucket_encryption with no encryption."""
    mock_s3_client.get_bucket_encryption.side_effect = Exception(
        "ServerSideEncryptionConfigurationNotFoundError"
    )

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = get_bucket_encryption("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "No encryption configured" in result


def test_get_bucket_versioning_enabled(mock_s3_client):
    """Test get_bucket_versioning with versioning enabled."""
    mock_s3_client.get_bucket_versioning.return_value = {
        "Status": "Enabled",
        "MFADelete": "Disabled",
    }

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = get_bucket_versioning("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "Enabled" in result
        assert "MFA Delete: Disabled" in result


def test_list_bucket_objects_success(mock_s3_client):
    """Test list_bucket_objects with objects present."""
    mock_s3_client.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "file1.txt", "Size": 1024, "LastModified": "2024-01-01T00:00:00Z"},
            {"Key": "file2.txt", "Size": 2048, "LastModified": "2024-01-02T00:00:00Z"},
        ]
    }

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = list_bucket_objects("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "1024 bytes" in result


def test_list_bucket_objects_empty(mock_s3_client):
    """Test list_bucket_objects with no objects."""
    mock_s3_client.list_objects_v2.return_value = {}

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_s3_client_with_queue_role",
        return_value=mock_s3_client,
    ):
        result = list_bucket_objects("test-bucket", farm_id="farm-123", queue_id="queue-456")

        assert "No objects found" in result


def test_get_s3_client_with_queue_role():
    """Test get_s3_client_with_queue_role with credentials."""
    mock_creds = {
        "access_key_id": "AKIAIOSFODNN7EXAMPLE",
        "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "session_token": "token123",
    }

    with patch(
        "deadline._agents.agents.job_attachments_agent.get_queue_role_credentials",
        return_value=mock_creds,
    ):
        with patch("deadline._agents.agents.job_attachments_agent.boto3.Session") as mock_session:
            mock_s3 = MagicMock()
            mock_session.return_value.client.return_value = mock_s3

            client = get_s3_client_with_queue_role(farm_id="farm-123", queue_id="queue-456")

            # Verify session was created with credentials
            mock_session.assert_called_once_with(
                aws_access_key_id=mock_creds["access_key_id"],
                aws_secret_access_key=mock_creds["secret_access_key"],
                aws_session_token=mock_creds["session_token"],
            )
            assert client == mock_s3


def test_get_s3_client_with_queue_role_no_credentials():
    """Test get_s3_client_with_queue_role without farm_id/queue_id."""
    with patch("deadline._agents.agents.job_attachments_agent.get_boto3_client") as mock_get_client:
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        client = get_s3_client_with_queue_role()

        # Should fall back to default credentials
        mock_get_client.assert_called_once_with("s3")
        assert client == mock_s3
