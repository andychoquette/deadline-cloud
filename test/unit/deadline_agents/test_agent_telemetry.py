# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Unit tests for agent telemetry functionality."""

import pytest
from unittest.mock import patch, MagicMock

# Skip all tests if strands-agents is not available
pytest.importorskip("strands", reason="strands-agents dependencies not available")

from deadline._agents.agents.classifier import classifier_agent
from deadline._agents.agents.job_troubleshooter import job_troubleshooter_agent
from deadline._agents.agents.farm_setup_agent import farm_setup_agent
from deadline._agents.agents.job_attachments_agent import job_attachments_agent


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
    agent.return_value = "Test response"
    return agent


@pytest.fixture
def mock_deadline_tools():
    """Mock Deadline tools."""
    return [MagicMock(__name__=f"tool_{i}") for i in range(5)]


@pytest.fixture
def mock_cloudwatch_tools():
    """Mock CloudWatch tools."""
    return [MagicMock(__name__=f"cw_tool_{i}") for i in range(2)]


def test_classifier_agent_telemetry_success(mock_telemetry_client, mock_agent):
    """Test that classifier agent records telemetry on success."""
    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.classifier.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                return_value=mock_telemetry_client,
            ):
                result = classifier_agent("Test query")

                assert "Test response" in result
                assert mock_telemetry_client.record_event.call_count == 2

                calls = mock_telemetry_client.record_event.call_args_list

                # Check latency event
                latency_call = next(
                    call
                    for call in calls
                    if call[1]["event_type"] == "com.amazon.rum.deadline.agents.latency"
                )
                latency_details = latency_call[1]["event_details"]
                assert "latency" in latency_details
                assert latency_details["agent_name"] == "classifier"
                assert latency_details["usage_mode"] == "AGENT"

                # Check usage event
                usage_call = next(
                    call
                    for call in calls
                    if call[1]["event_type"] == "com.amazon.rum.deadline.agents.usage"
                )
                usage_details = usage_call[1]["event_details"]
                assert usage_details["agent_name"] == "classifier"
                assert usage_details["is_success"] is True
                assert usage_details["error_type"] is None
                assert usage_details["usage_mode"] == "AGENT"


def test_classifier_agent_telemetry_failure(mock_telemetry_client):
    """Test that classifier agent records telemetry on failure."""
    mock_agent = MagicMock()
    mock_agent.side_effect = ValueError("Test error")

    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.classifier.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                return_value=mock_telemetry_client,
            ):
                result = classifier_agent("Test query")

                assert "Error in classifier" in result
                assert mock_telemetry_client.record_event.call_count == 2

                calls = mock_telemetry_client.record_event.call_args_list
                usage_call = next(
                    call
                    for call in calls
                    if call[1]["event_type"] == "com.amazon.rum.deadline.agents.usage"
                )
                usage_details = usage_call[1]["event_details"]
                assert usage_details["is_success"] is False
                assert usage_details["error_type"] == "ValueError"


def test_job_troubleshooter_agent_telemetry_success(
    mock_telemetry_client, mock_agent, mock_deadline_tools, mock_cloudwatch_tools
):
    """Test that job troubleshooter agent records telemetry on success."""
    with patch("deadline.client.api.get_boto3_session"):
        with patch(
            "deadline._agents.agents.job_troubleshooter.get_deadline_tools",
            return_value=mock_deadline_tools,
        ):
            with patch(
                "deadline._agents.agents.job_troubleshooter.get_cloudwatch_tools",
                return_value=mock_cloudwatch_tools,
            ):
                with patch(
                    "deadline._agents.agents.job_troubleshooter.Agent", return_value=mock_agent
                ):
                    with patch(
                        "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                        return_value=mock_telemetry_client,
                    ):
                        result = job_troubleshooter_agent("Troubleshoot job job-123")

                        assert "Test response" in result
                        assert mock_telemetry_client.record_event.call_count == 2

                        calls = mock_telemetry_client.record_event.call_args_list

                        # Check that both latency and usage events were recorded
                        event_types = [call[1]["event_type"] for call in calls]
                        assert "com.amazon.rum.deadline.agents.latency" in event_types
                        assert "com.amazon.rum.deadline.agents.usage" in event_types

                        # Check usage event details
                        usage_call = next(
                            call
                            for call in calls
                            if call[1]["event_type"] == "com.amazon.rum.deadline.agents.usage"
                        )
                        usage_details = usage_call[1]["event_details"]
                        assert usage_details["agent_name"] == "job_troubleshooter"
                        assert usage_details["is_success"] is True


def test_farm_setup_agent_telemetry_success(mock_telemetry_client, mock_agent):
    """Test that farm setup agent records telemetry on success."""
    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.farm_setup_agent.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                return_value=mock_telemetry_client,
            ):
                result = farm_setup_agent("Check fleet configuration")

                assert "Test response" in result
                assert mock_telemetry_client.record_event.call_count == 2

                calls = mock_telemetry_client.record_event.call_args_list
                usage_call = next(
                    call
                    for call in calls
                    if call[1]["event_type"] == "com.amazon.rum.deadline.agents.usage"
                )
                usage_details = usage_call[1]["event_details"]
                assert usage_details["agent_name"] == "farm_setup"
                assert usage_details["is_success"] is True


def test_job_attachments_agent_telemetry_success(mock_telemetry_client, mock_agent):
    """Test that job attachments agent records telemetry on success."""
    with patch("deadline._agents.agents.job_attachments_agent.Agent", return_value=mock_agent):
        with patch(
            "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
            return_value=mock_telemetry_client,
        ):
            result = job_attachments_agent(
                "Check bucket access", farm_id="farm-123", queue_id="queue-456"
            )

            assert "Test response" in result
            assert mock_telemetry_client.record_event.call_count == 2

            calls = mock_telemetry_client.record_event.call_args_list

            # Check that farm/queue context is recorded
            usage_call = next(
                call
                for call in calls
                if call[1]["event_type"] == "com.amazon.rum.deadline.agents.usage"
            )
            usage_details = usage_call[1]["event_details"]
            assert usage_details["agent_name"] == "job_attachments"
            assert usage_details["is_success"] is True
            assert usage_details["has_farm_queue_context"] is True


def test_job_attachments_agent_telemetry_without_context(mock_telemetry_client, mock_agent):
    """Test that job attachments agent records telemetry without farm/queue context."""
    with patch("deadline._agents.agents.job_attachments_agent.Agent", return_value=mock_agent):
        with patch(
            "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
            return_value=mock_telemetry_client,
        ):
            result = job_attachments_agent("Check bucket access")

            assert "Test response" in result

            calls = mock_telemetry_client.record_event.call_args_list
            usage_call = next(
                call
                for call in calls
                if call[1]["event_type"] == "com.amazon.rum.deadline.agents.usage"
            )
            usage_details = usage_call[1]["event_details"]
            assert usage_details["has_farm_queue_context"] is False


def test_telemetry_error_handling(mock_agent):
    """Test that telemetry errors don't affect agent execution."""
    mock_telemetry_client = MagicMock()
    mock_telemetry_client.record_event.side_effect = Exception("Telemetry error")

    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.classifier.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                return_value=mock_telemetry_client,
            ):
                # Should not raise exception despite telemetry error
                result = classifier_agent("Test query")

                assert "Test response" in result
                assert mock_telemetry_client.record_event.call_count > 0


@pytest.mark.asyncio
async def test_orchestrator_telemetry_success(mock_telemetry_client):
    """Test that orchestrator records telemetry on success."""
    from deadline._agents.orchestrator import run_diagnostics

    mock_agent = MagicMock()

    async def mock_stream():
        yield {"data": "Test response"}

    mock_agent.stream_async = MagicMock(return_value=mock_stream())

    with patch("deadline.client.api._session.get_boto3_session"):
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

                assert "Test response" in result
                assert mock_telemetry_client.record_event.call_count == 2

                calls = mock_telemetry_client.record_event.call_args_list

                # Check usage event
                usage_call = next(
                    call
                    for call in calls
                    if call[1]["event_type"] == "com.amazon.rum.deadline.agents.usage"
                )
                usage_details = usage_call[1]["event_details"]
                assert usage_details["agent_name"] == "orchestrator"
                assert usage_details["is_success"] is True
                assert usage_details["has_job_id"] is True
                assert usage_details["model_override"] is False


@pytest.mark.asyncio
async def test_orchestrator_telemetry_with_model_override(mock_telemetry_client):
    """Test that orchestrator records model override in telemetry."""
    from deadline._agents.orchestrator import run_diagnostics

    mock_agent = MagicMock()

    async def mock_stream():
        yield {"data": "Test response"}

    mock_agent.stream_async = MagicMock(return_value=mock_stream())

    with patch("deadline.client.api._session.get_boto3_session"):
        with patch("deadline._agents.orchestrator.Agent", return_value=mock_agent):
            with patch("deadline._agents.bin.model_config.set_model_override"):
                with patch(
                    "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                    return_value=mock_telemetry_client,
                ):
                    result, agent = await run_diagnostics(
                        job_id="job-123",
                        farm_id="farm-456",
                        queue_id="queue-789",
                        model_id_override="anthropic.claude-3-opus-20240229-v1:0",
                    )

                    calls = mock_telemetry_client.record_event.call_args_list
                    usage_call = next(
                        call
                        for call in calls
                        if call[1]["event_type"] == "com.amazon.rum.deadline.agents.usage"
                    )
                    usage_details = usage_call[1]["event_details"]
                    assert usage_details["model_override"] is True


def test_telemetry_event_structure():
    """Test that telemetry events have the correct structure."""
    mock_telemetry_client = MagicMock()
    mock_agent = MagicMock()
    mock_agent.return_value = "Test response"

    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.classifier.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client",
                return_value=mock_telemetry_client,
            ):
                classifier_agent("Test query")

                calls = mock_telemetry_client.record_event.call_args_list

                for call in calls:
                    assert "event_type" in call[1]
                    assert "event_details" in call[1]

                    event_type = call[1]["event_type"]
                    event_details = call[1]["event_details"]

                    assert event_type.startswith("com.amazon.rum.deadline.agents.")
                    assert event_type in [
                        "com.amazon.rum.deadline.agents.latency",
                        "com.amazon.rum.deadline.agents.usage",
                    ]

                    assert "agent_name" in event_details
                    assert "usage_mode" in event_details
                    assert event_details["usage_mode"] == "AGENT"

                    if event_type == "com.amazon.rum.deadline.agents.latency":
                        assert "latency" in event_details
                        assert isinstance(event_details["latency"], (int, float))
                    elif event_type == "com.amazon.rum.deadline.agents.usage":
                        assert "is_success" in event_details
                        assert isinstance(event_details["is_success"], bool)
                        assert "error_type" in event_details
