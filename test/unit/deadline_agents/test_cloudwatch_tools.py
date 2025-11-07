# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Unit tests for CloudWatch tools."""

import pytest
from unittest.mock import patch, MagicMock

# Skip all tests if strands-agents is not available
pytest.importorskip("strands", reason="strands-agents dependencies not available")

from deadline._agents.tools.cloudwatch_tools import (
    get_cloudwatch_client,
    get_cloudwatch_log_events,
    get_worker_cloudwatch_logs,
    get_cloudwatch_tools,
)


@pytest.fixture
def mock_boto3_session():
    """Mock boto3 session for testing."""
    session = MagicMock()
    client = MagicMock()
    session.client.return_value = client
    return session, client


@pytest.fixture
def mock_deadline_session():
    """Mock deadline session for testing."""
    with patch("deadline.client.api.get_boto3_session") as mock:
        session = MagicMock()
        client = MagicMock()
        session.client.return_value = client
        mock.return_value = session
        yield mock, session, client


class TestGetCloudWatchClient:
    """Tests for get_cloudwatch_client function."""

    def test_get_client_without_queue_role(self, mock_deadline_session):
        """Test getting CloudWatch client without assuming queue role."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        result = get_cloudwatch_client()

        assert result == mock_client
        mock_session.client.assert_called_once_with("logs")

    def test_get_client_with_queue_role_success(self, mock_deadline_session):
        """Test getting CloudWatch client with queue role credentials."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch(
            "deadline._agents.tools.cloudwatch_tools.get_queue_role_credentials"
        ) as mock_get_creds:
            mock_get_creds.return_value = {
                "access_key_id": "test_key",
                "secret_access_key": "test_secret",
                "session_token": "test_token",
            }

            with patch(
                "deadline._agents.tools.cloudwatch_tools.boto3.Session"
            ) as mock_boto_session:
                mock_boto_client = MagicMock()
                mock_boto_session.return_value.client.return_value = mock_boto_client

                result = get_cloudwatch_client(farm_id="farm-123", queue_id="queue-456")

                assert result == mock_boto_client
                mock_get_creds.assert_called_once_with("farm-123", "queue-456", config=None)

    def test_get_client_with_queue_role_failure_fallback(self, mock_deadline_session):
        """Test fallback to user credentials when queue role fails."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch(
            "deadline._agents.tools.cloudwatch_tools.get_queue_role_credentials"
        ) as mock_get_creds:
            mock_get_creds.return_value = None

            result = get_cloudwatch_client(farm_id="farm-123", queue_id="queue-456")

            assert result == mock_client
            mock_session.client.assert_called_once_with("logs")


class TestGetCloudWatchLogEvents:
    """Tests for get_cloudwatch_log_events function."""

    def test_get_log_events_success(self, mock_deadline_session):
        """Test successfully retrieving log events."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch(
            "deadline._agents.tools.cloudwatch_tools.get_cloudwatch_client"
        ) as mock_get_cw_client:
            mock_cw_client = MagicMock()
            mock_get_cw_client.return_value = mock_cw_client

            mock_cw_client.get_log_events.return_value = {
                "events": [
                    {"timestamp": 1609459200000, "message": "Test log 1"},
                    {"timestamp": 1609459201000, "message": "Test log 2"},
                ],
                "nextBackwardToken": None,
                "nextForwardToken": None,
            }

            result = get_cloudwatch_log_events(
                log_group_name="/aws/deadline/farm-123/queue-456",
                log_stream_name="session-789",
                farm_id="farm-123",
                queue_id="queue-456",
            )

            assert "Found 2 log event(s)" in result
            assert "Test log 1" in result
            assert "Test log 2" in result

    def test_get_log_events_with_time_filter(self, mock_deadline_session):
        """Test retrieving log events with time filters."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch(
            "deadline._agents.tools.cloudwatch_tools.get_cloudwatch_client"
        ) as mock_get_cw_client:
            mock_cw_client = MagicMock()
            mock_get_cw_client.return_value = mock_cw_client

            mock_cw_client.get_log_events.return_value = {
                "events": [{"timestamp": 1609459200000, "message": "Filtered log"}],
                "nextBackwardToken": None,
                "nextForwardToken": None,
            }

            result = get_cloudwatch_log_events(
                log_group_name="/aws/deadline/farm-123/queue-456",
                log_stream_name="session-789",
                farm_id="farm-123",
                queue_id="queue-456",
                start_time="2024-01-01T00:00:00Z",
                end_time="2024-01-01T01:00:00Z",
            )

            assert "Found 1 log event(s)" in result
            assert "filtered by time range" in result

    def test_get_log_events_pagination(self, mock_deadline_session):
        """Test pagination through multiple pages of log events."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch(
            "deadline._agents.tools.cloudwatch_tools.get_cloudwatch_client"
        ) as mock_get_cw_client:
            mock_cw_client = MagicMock()
            mock_get_cw_client.return_value = mock_cw_client

            # Simulate pagination with two pages - need different tokens to trigger pagination
            mock_cw_client.get_log_events.side_effect = [
                {
                    "events": [{"timestamp": 1609459200000, "message": "Page 1"}],
                    "nextBackwardToken": "token2",
                    "nextForwardToken": "token2",
                },
                {
                    "events": [{"timestamp": 1609459201000, "message": "Page 2"}],
                    "nextBackwardToken": "token2",
                    "nextForwardToken": "token2",
                },
            ]

            result = get_cloudwatch_log_events(
                log_group_name="/aws/deadline/farm-123/queue-456",
                log_stream_name="session-789",
                farm_id="farm-123",
                queue_id="queue-456",
            )

            assert "Found 2 log event(s)" in result
            assert "Page 1" in result
            assert "Page 2" in result

    def test_get_log_events_no_events(self, mock_deadline_session):
        """Test when no log events are found."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch(
            "deadline._agents.tools.cloudwatch_tools.get_cloudwatch_client"
        ) as mock_get_cw_client:
            mock_cw_client = MagicMock()
            mock_get_cw_client.return_value = mock_cw_client

            mock_cw_client.get_log_events.return_value = {
                "events": [],
                "nextBackwardToken": None,
                "nextForwardToken": None,
            }

            result = get_cloudwatch_log_events(
                log_group_name="/aws/deadline/farm-123/queue-456",
                log_stream_name="session-789",
                farm_id="farm-123",
                queue_id="queue-456",
            )

            assert "No log events found" in result

    def test_get_log_events_resource_not_found_stream(self, mock_deadline_session):
        """Test handling of ResourceNotFoundException for log stream."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch(
            "deadline._agents.tools.cloudwatch_tools.get_cloudwatch_client"
        ) as mock_get_cw_client:
            mock_cw_client = MagicMock()
            mock_get_cw_client.return_value = mock_cw_client

            mock_cw_client.get_log_events.side_effect = Exception(
                "ResourceNotFoundException: log stream does not exist"
            )

            result = get_cloudwatch_log_events(
                log_group_name="/aws/deadline/farm-123/queue-456",
                log_stream_name="session-789",
                farm_id="farm-123",
                queue_id="queue-456",
            )

            assert "Log stream not found" in result
            assert "session-789" in result

    def test_get_log_events_resource_not_found_group(self, mock_deadline_session):
        """Test handling of ResourceNotFoundException for log group."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch(
            "deadline._agents.tools.cloudwatch_tools.get_cloudwatch_client"
        ) as mock_get_cw_client:
            mock_cw_client = MagicMock()
            mock_get_cw_client.return_value = mock_cw_client

            mock_cw_client.get_log_events.side_effect = Exception(
                "ResourceNotFoundException: log group does not exist"
            )

            result = get_cloudwatch_log_events(
                log_group_name="/aws/deadline/farm-123/queue-456",
                log_stream_name="session-789",
                farm_id="farm-123",
                queue_id="queue-456",
            )

            assert "Log group not found" in result
            assert "CloudWatch logging may not be configured" in result

    def test_get_log_events_access_denied(self, mock_deadline_session):
        """Test handling of AccessDeniedException."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch(
            "deadline._agents.tools.cloudwatch_tools.get_cloudwatch_client"
        ) as mock_get_cw_client:
            mock_cw_client = MagicMock()
            mock_get_cw_client.return_value = mock_cw_client

            mock_cw_client.get_log_events.side_effect = Exception(
                "AccessDeniedException: Access denied"
            )

            result = get_cloudwatch_log_events(
                log_group_name="/aws/deadline/farm-123/queue-456",
                log_stream_name="session-789",
                farm_id="farm-123",
                queue_id="queue-456",
            )

            assert "Access denied" in result
            assert "logs:GetLogEvents" in result


class TestGetWorkerCloudWatchLogs:
    """Tests for get_worker_cloudwatch_logs function."""

    def test_get_worker_logs_success(self, mock_deadline_session):
        """Test successfully retrieving worker log events."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch("deadline.client.api.get_boto3_client") as mock_get_client:
            mock_deadline_client = MagicMock()
            mock_get_client.return_value = mock_deadline_client

            mock_deadline_client.assume_fleet_role_for_read.return_value = {
                "credentials": {
                    "accessKeyId": "test_key",
                    "secretAccessKey": "test_secret",
                    "sessionToken": "test_token",
                }
            }

            with patch(
                "deadline._agents.tools.cloudwatch_tools.boto3.Session"
            ) as mock_boto_session:
                mock_logs_client = MagicMock()
                mock_boto_session.return_value.client.return_value = mock_logs_client

                mock_logs_client.get_log_events.return_value = {
                    "events": [{"timestamp": 1609459200000, "message": "Worker log"}],
                    "nextBackwardToken": None,
                    "nextForwardToken": None,
                }

                result = get_worker_cloudwatch_logs(
                    log_group_name="/aws/deadline/farm-123/fleet-456",
                    log_stream_name="worker-789",
                    farm_id="farm-123",
                    fleet_id="fleet-456",
                )

                assert "Found 1 worker log event(s)" in result
                assert "Worker log" in result

    def test_get_worker_logs_assume_role_failure(self, mock_deadline_session):
        """Test handling of assume fleet role failure."""
        mock_get_session, mock_session, mock_client = mock_deadline_session

        with patch("deadline.client.api.get_boto3_client") as mock_get_client:
            mock_deadline_client = MagicMock()
            mock_get_client.return_value = mock_deadline_client

            mock_deadline_client.assume_fleet_role_for_read.side_effect = Exception(
                "Failed to assume role"
            )

            result = get_worker_cloudwatch_logs(
                log_group_name="/aws/deadline/farm-123/fleet-456",
                log_stream_name="worker-789",
                farm_id="farm-123",
                fleet_id="fleet-456",
            )

            assert "Failed to assume fleet role" in result


class TestGetCloudWatchTools:
    """Tests for get_cloudwatch_tools function."""

    def test_get_tools_returns_list(self):
        """Test that get_cloudwatch_tools returns a list of tools."""
        tools = get_cloudwatch_tools()

        assert isinstance(tools, list)
        assert len(tools) == 2
        assert get_cloudwatch_log_events in tools
        assert get_worker_cloudwatch_logs in tools

    @patch("deadline._agents.tools.cloudwatch_tools.BOTO3_AVAILABLE", False)
    def test_get_tools_boto3_unavailable(self):
        """Test that get_cloudwatch_tools returns empty list when boto3 unavailable."""
        tools = get_cloudwatch_tools()

        assert isinstance(tools, list)
        assert len(tools) == 0
