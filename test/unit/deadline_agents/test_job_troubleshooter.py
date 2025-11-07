# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Unit tests for the job troubleshooter agent."""

import pytest
from unittest.mock import patch, MagicMock

# Skip all tests if strands-agents is not available
pytest.importorskip("strands", reason="strands-agents dependencies not available")

from deadline._agents.agents.job_troubleshooter import job_troubleshooter_agent


@pytest.fixture
def mock_boto3_session():
    """Mock boto3 session for testing."""
    session = MagicMock()
    return session


@pytest.fixture
def mock_agent():
    """Mock Strands Agent for testing."""
    agent = MagicMock()
    agent.return_value = "Job analysis complete"
    return agent


@pytest.fixture
def mock_telemetry_client():
    """Mock telemetry client for testing."""
    client = MagicMock()
    client.is_initialized = True
    client.record_event = MagicMock()
    return client


@pytest.fixture
def mock_deadline_tools():
    """Mock Deadline tools."""
    tools = [
        MagicMock(__name__="get_deadline_job_details"),
        MagicMock(__name__="list_deadline_steps"),
        MagicMock(__name__="list_deadline_tasks"),
        MagicMock(__name__="get_deadline_task_details"),
        MagicMock(__name__="list_deadline_sessions"),
        MagicMock(__name__="list_deadline_session_actions"),
        MagicMock(__name__="get_deadline_session_action_details"),
        MagicMock(__name__="get_deadline_session_details"),
        MagicMock(__name__="get_deadline_worker_details"),
    ]
    return tools


@pytest.fixture
def mock_cloudwatch_tools():
    """Mock CloudWatch tools."""
    tools = [
        MagicMock(__name__="get_cloudwatch_log_events"),
        MagicMock(__name__="get_worker_cloudwatch_logs"),
    ]
    return tools


def test_job_troubleshooter_agent_basic(mock_agent, mock_deadline_tools, mock_cloudwatch_tools):
    """Test basic job troubleshooter agent invocation."""
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
                        "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
                    ):
                        result = job_troubleshooter_agent("Troubleshoot job job-123")

                        assert "Job analysis complete" in result
                        mock_agent.assert_called_once()


def test_job_troubleshooter_agent_filters_tools(
    mock_agent, mock_deadline_tools, mock_cloudwatch_tools
):
    """Test that job troubleshooter agent filters to only needed tools."""
    # Add some extra tools that should be filtered out
    all_tools = mock_deadline_tools + [
        MagicMock(__name__="list_deadline_farms"),
        MagicMock(__name__="get_deadline_queue_details"),
    ]

    with patch("deadline.client.api.get_boto3_session"):
        with patch(
            "deadline._agents.agents.job_troubleshooter.get_deadline_tools", return_value=all_tools
        ):
            with patch(
                "deadline._agents.agents.job_troubleshooter.get_cloudwatch_tools",
                return_value=mock_cloudwatch_tools,
            ):
                with patch(
                    "deadline._agents.agents.job_troubleshooter.Agent", return_value=mock_agent
                ) as mock_agent_class:
                    with patch(
                        "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
                    ):
                        job_troubleshooter_agent("Troubleshoot job job-123")

                        # Verify only job troubleshooting tools were passed
                        call_kwargs = mock_agent_class.call_args[1]
                        tools = call_kwargs["tools"]

                        # Should have 9 Deadline tools + CloudWatch tools
                        deadline_tool_names = [t.__name__ for t in tools if hasattr(t, "__name__")]
                        assert "get_deadline_job_details" in deadline_tool_names
                        assert "list_deadline_sessions" in deadline_tool_names
                        assert "list_deadline_farms" not in deadline_tool_names


def test_job_troubleshooter_agent_uses_correct_model(
    mock_agent, mock_deadline_tools, mock_cloudwatch_tools
):
    """Test that job troubleshooter agent uses the correct model."""
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
                ) as mock_agent_class:
                    with patch(
                        "deadline._agents.agents.job_troubleshooter.get_job_troubleshooter_model"
                    ) as mock_get_model:
                        with patch(
                            "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
                        ):
                            mock_model = MagicMock()
                            mock_get_model.return_value = mock_model

                            job_troubleshooter_agent("Troubleshoot job job-123")

                            # Verify model was retrieved with boto_session
                            mock_get_model.assert_called_once()

                            # Verify Agent was created with the model
                            call_kwargs = mock_agent_class.call_args[1]
                            assert call_kwargs["model"] == mock_model


def test_job_troubleshooter_agent_has_callback_handler(
    mock_agent, mock_deadline_tools, mock_cloudwatch_tools
):
    """Test that job troubleshooter agent has a callback handler for streaming."""
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
                ) as mock_agent_class:
                    with patch(
                        "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
                    ):
                        job_troubleshooter_agent("Troubleshoot job job-123")

                        # Verify Agent was created with a callback_handler
                        call_kwargs = mock_agent_class.call_args[1]
                        assert call_kwargs["callback_handler"] is not None
                        assert callable(call_kwargs["callback_handler"])


def test_job_troubleshooter_agent_error_handling(mock_deadline_tools, mock_cloudwatch_tools):
    """Test job troubleshooter agent error handling."""
    mock_agent = MagicMock()
    mock_agent.side_effect = Exception("Test error")

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
                        "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
                    ):
                        result = job_troubleshooter_agent("Troubleshoot job job-123")

                        assert "An error occurred while troubleshooting the job" in result
                        assert "Test error" in result


def test_job_troubleshooter_agent_includes_cloudwatch_tools(
    mock_agent, mock_deadline_tools, mock_cloudwatch_tools
):
    """Test that job troubleshooter agent includes CloudWatch tools."""
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
                ) as mock_agent_class:
                    with patch(
                        "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
                    ):
                        job_troubleshooter_agent("Troubleshoot job job-123")

                        # Verify CloudWatch tools were included
                        call_kwargs = mock_agent_class.call_args[1]
                        tools = call_kwargs["tools"]

                        # CloudWatch tools should be in the list
                        assert any(t in tools for t in mock_cloudwatch_tools)


def test_job_troubleshooter_agent_system_prompt(
    mock_agent, mock_deadline_tools, mock_cloudwatch_tools
):
    """Test that job troubleshooter agent uses the correct system prompt."""
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
                ) as mock_agent_class:
                    with patch(
                        "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
                    ):
                        job_troubleshooter_agent("Troubleshoot job job-123")

                        # Verify system prompt contains key instructions
                        call_kwargs = mock_agent_class.call_args[1]
                        system_prompt = call_kwargs["system_prompt"]

                        assert "Job Troubleshooter" in system_prompt
                        assert "get_deadline_job_details" in system_prompt
                        assert "CloudWatch" in system_prompt
