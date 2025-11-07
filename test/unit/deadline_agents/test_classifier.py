# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Unit tests for the classifier agent."""

import pytest
import json
from unittest.mock import patch, MagicMock

# Skip all tests if strands-agents is not available
pytest.importorskip("strands", reason="strands-agents dependencies not available")

from deadline._agents.agents.classifier import classifier_agent


@pytest.fixture
def mock_boto3_session():
    """Mock boto3 session for testing."""
    session = MagicMock()
    return session


@pytest.fixture
def mock_agent():
    """Mock Strands Agent for testing."""
    agent = MagicMock()
    return agent


@pytest.fixture
def mock_telemetry_client():
    """Mock telemetry client for testing."""
    client = MagicMock()
    client.is_initialized = True
    client.record_event = MagicMock()
    return client


def test_classifier_agent_job_failure():
    """Test classifier agent with job failure scenario."""
    mock_agent = MagicMock()
    mock_response = json.dumps({"recommended_agents": ["job_troubleshooter_agent"]})
    mock_agent.return_value = mock_response

    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.classifier.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ) as mock_get_telemetry:
                mock_telemetry = MagicMock()
                mock_get_telemetry.return_value = mock_telemetry

                result = classifier_agent("Job job-123 failed with task errors")

                assert "job_troubleshooter_agent" in result
                mock_agent.assert_called_once()


def test_classifier_agent_fleet_issue():
    """Test classifier agent with fleet configuration issue."""
    mock_agent = MagicMock()
    mock_response = json.dumps({"recommended_agents": ["farm_setup_agent"]})
    mock_agent.return_value = mock_response

    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.classifier.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ):
                result = classifier_agent("No workers are launching in the fleet")

                assert "farm_setup_agent" in result


def test_classifier_agent_s3_issue():
    """Test classifier agent with S3/job attachments issue."""
    mock_agent = MagicMock()
    mock_response = json.dumps({"recommended_agents": ["job_attachments_agent"]})
    mock_agent.return_value = mock_response

    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.classifier.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ):
                result = classifier_agent("Cannot access S3 bucket for job attachments")

                assert "job_attachments_agent" in result


def test_classifier_agent_multiple_recommendations():
    """Test classifier agent returning multiple agent recommendations."""
    mock_agent = MagicMock()
    mock_response = json.dumps(
        {"recommended_agents": ["job_troubleshooter_agent", "farm_setup_agent"]}
    )
    mock_agent.return_value = mock_response

    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.classifier.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ):
                result = classifier_agent("Job failed and fleet has no capacity")

                assert "job_troubleshooter_agent" in result
                assert "farm_setup_agent" in result


def test_classifier_agent_error_handling():
    """Test classifier agent error handling."""
    mock_agent = MagicMock()
    mock_agent.side_effect = Exception("Test error")

    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.classifier.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ):
                result = classifier_agent("Test query")

                assert "Error in classifier" in result
                assert "Test error" in result


def test_classifier_agent_uses_correct_model():
    """Test that classifier agent uses the correct model configuration."""
    mock_agent = MagicMock()
    mock_agent.return_value = json.dumps({"recommended_agents": ["job_troubleshooter_agent"]})

    with patch("deadline.client.api.get_boto3_session"):
        with patch(
            "deadline._agents.agents.classifier.Agent", return_value=mock_agent
        ) as mock_agent_class:
            with patch("deadline._agents.agents.classifier.get_classifier_model") as mock_get_model:
                with patch(
                    "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
                ):
                    mock_model = MagicMock()
                    mock_get_model.return_value = mock_model

                    classifier_agent("Test query")

                    # Verify get_classifier_model was called with boto_session
                    mock_get_model.assert_called_once()

                    # Verify Agent was created with the model
                    call_kwargs = mock_agent_class.call_args[1]
                    assert call_kwargs["model"] == mock_model


def test_classifier_agent_no_tools():
    """Test that classifier agent is created without tools."""
    mock_agent = MagicMock()
    mock_agent.return_value = json.dumps({"recommended_agents": []})

    with patch("deadline.client.api.get_boto3_session"):
        with patch(
            "deadline._agents.agents.classifier.Agent", return_value=mock_agent
        ) as mock_agent_class:
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ):
                classifier_agent("Test query")

                # Verify Agent was created with empty tools list
                call_kwargs = mock_agent_class.call_args[1]
                assert call_kwargs["tools"] == []


def test_classifier_agent_suppresses_output():
    """Test that classifier agent suppresses callback output."""
    mock_agent = MagicMock()
    mock_agent.return_value = json.dumps({"recommended_agents": ["job_troubleshooter_agent"]})

    with patch("deadline.client.api.get_boto3_session"):
        with patch(
            "deadline._agents.agents.classifier.Agent", return_value=mock_agent
        ) as mock_agent_class:
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ):
                classifier_agent("Test query")

                # Verify Agent was created with None callback_handler
                call_kwargs = mock_agent_class.call_args[1]
                assert call_kwargs["callback_handler"] is None
