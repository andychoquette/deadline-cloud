# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Unit tests for the orchestrator agent."""

import pytest
from unittest.mock import patch, MagicMock
from configparser import ConfigParser

# Skip all tests if strands-agents is not available
pytest.importorskip("strands", reason="strands-agents dependencies not available")

from deadline._agents.orchestrator import run_diagnostics


@pytest.fixture
def mock_boto3_session():
    """Mock boto3 session for testing."""
    session = MagicMock()
    session.client.return_value = MagicMock()
    return session


@pytest.fixture
def mock_telemetry_client():
    """Mock telemetry client for testing."""
    client = MagicMock()
    client.is_initialized = True
    client.record_event = MagicMock()
    return client


@pytest.fixture
def mock_agent():
    """Mock Strands Agent for testing."""
    agent = MagicMock()

    # Mock async stream - return the generator function, not the result
    async def mock_stream():
        yield {"data": "Test response chunk 1"}
        yield {"data": " chunk 2"}

    agent.stream_async = MagicMock(side_effect=lambda *args, **kwargs: mock_stream())
    return agent


@pytest.mark.asyncio
async def test_run_diagnostics_with_job_id(mock_boto3_session, mock_telemetry_client, mock_agent):
    """Test run_diagnostics with a specific job ID."""
    with patch("deadline.client.api._session.get_boto3_session", return_value=mock_boto3_session):
        with patch("deadline._agents.orchestrator.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                return_value=mock_telemetry_client,
            ):
                result, agent = await run_diagnostics(
                    job_id="job-123",
                    farm_id="farm-456",
                    queue_id="queue-789",
                )

                assert "Test response chunk 1 chunk 2" in result
                assert mock_agent.stream_async.called

                # Verify invocation state was passed
                call_args = mock_agent.stream_async.call_args
                assert call_args[1]["invocation_state"]["job_id"] == "job-123"
                assert call_args[1]["invocation_state"]["farm_id"] == "farm-456"
                assert call_args[1]["invocation_state"]["queue_id"] == "queue-789"


@pytest.mark.asyncio
async def test_run_diagnostics_without_job_id(
    mock_boto3_session, mock_telemetry_client, mock_agent
):
    """Test run_diagnostics without a job ID (general troubleshooting)."""
    with patch("deadline.client.api._session.get_boto3_session", return_value=mock_boto3_session):
        with patch("deadline._agents.orchestrator.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                return_value=mock_telemetry_client,
            ):
                result, agent = await run_diagnostics(
                    job_id=None,
                    farm_id="farm-456",
                    queue_id="queue-789",
                )

                assert "Test response chunk 1 chunk 2" in result

                # Verify invocation state
                call_args = mock_agent.stream_async.call_args
                assert call_args[1]["invocation_state"]["job_id"] is None
                assert call_args[1]["invocation_state"]["farm_id"] == "farm-456"


@pytest.mark.asyncio
async def test_run_diagnostics_with_model_override(
    mock_boto3_session, mock_telemetry_client, mock_agent
):
    """Test run_diagnostics with model override."""
    with patch("deadline.client.api._session.get_boto3_session", return_value=mock_boto3_session):
        with patch("deadline._agents.orchestrator.Agent", return_value=mock_agent):
            with patch("deadline._agents.bin.model_config.set_model_override") as mock_set_override:
                with patch(
                    "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                    return_value=mock_telemetry_client,
                ):
                    await run_diagnostics(
                        job_id="job-123",
                        farm_id="farm-456",
                        queue_id="queue-789",
                        model_id_override="anthropic.claude-3-opus-20240229-v1:0",
                    )

                    mock_set_override.assert_called_once_with(
                        "anthropic.claude-3-opus-20240229-v1:0"
                    )


@pytest.mark.asyncio
async def test_run_diagnostics_with_config(mock_boto3_session, mock_telemetry_client, mock_agent):
    """Test run_diagnostics with custom config."""
    config = ConfigParser()
    config.add_section("defaults")
    config.set("defaults", "aws_profile", "test-profile")

    with patch(
        "deadline.client.api._session.get_boto3_session", return_value=mock_boto3_session
    ) as mock_get_session:
        with patch("deadline._agents.orchestrator.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                return_value=mock_telemetry_client,
            ):
                await run_diagnostics(
                    job_id="job-123",
                    farm_id="farm-456",
                    queue_id="queue-789",
                    config=config,
                )

                # Verify config was passed to get_boto3_session
                mock_get_session.assert_called_once_with(config=config)


@pytest.mark.asyncio
async def test_run_diagnostics_error_handling(mock_boto3_session, mock_telemetry_client):
    """Test run_diagnostics error handling."""
    mock_agent = MagicMock()

    async def mock_stream_error():
        raise Exception("Test error")
        yield  # Make it a generator

    mock_agent.stream_async = MagicMock(side_effect=lambda *args, **kwargs: mock_stream_error())

    with patch("deadline.client.api._session.get_boto3_session", return_value=mock_boto3_session):
        with patch("deadline._agents.orchestrator.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                return_value=mock_telemetry_client,
            ):
                with pytest.raises(Exception, match="Test error"):
                    await run_diagnostics(
                        job_id="job-123",
                        farm_id="farm-456",
                        queue_id="queue-789",
                    )


@pytest.mark.asyncio
async def test_run_diagnostics_initial_state(mock_boto3_session, mock_telemetry_client, mock_agent):
    """Test that run_diagnostics initializes agent state correctly."""
    with patch("deadline.client.api._session.get_boto3_session", return_value=mock_boto3_session):
        with patch(
            "deadline._agents.orchestrator.Agent", return_value=mock_agent
        ) as mock_agent_class:
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                return_value=mock_telemetry_client,
            ):
                await run_diagnostics(
                    job_id="job-123",
                    farm_id="farm-456",
                    queue_id="queue-789",
                )

                # Verify initial state was set
                call_kwargs = mock_agent_class.call_args[1]
                assert "state" in call_kwargs
                state = call_kwargs["state"]
                assert "discovered_sessions" in state
                assert "discovered_tasks" in state
                assert "session_to_task_map" in state
