# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Unit tests for the farm setup agent."""

import pytest
from unittest.mock import patch, MagicMock

# Skip all tests if strands-agents is not available
pytest.importorskip("strands", reason="strands-agents dependencies not available")

from deadline._agents.agents.farm_setup_agent import (
    farm_setup_agent,
    get_fleet_details,
    list_queue_fleets,
    list_fleet_queues,
    check_fleet_workers,
    validate_fleet_configuration,
)


@pytest.fixture
def mock_boto3_client():
    """Mock boto3 Deadline client."""
    client = MagicMock()
    return client


@pytest.fixture
def mock_agent():
    """Mock Strands Agent for testing."""
    agent = MagicMock()
    agent.return_value = "Fleet configuration analysis complete"
    return agent


@pytest.fixture
def mock_telemetry_client():
    """Mock telemetry client for testing."""
    client = MagicMock()
    client.is_initialized = True
    client.record_event = MagicMock()
    return client


def test_farm_setup_agent_basic(mock_agent):
    """Test basic farm setup agent invocation."""
    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.farm_setup_agent.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ):
                result = farm_setup_agent("Check fleet configuration for queue queue-123")

                assert "Fleet configuration analysis complete" in result
                mock_agent.assert_called_once()


def test_farm_setup_agent_uses_correct_model(mock_agent):
    """Test that farm setup agent uses the correct model."""
    with patch("deadline.client.api.get_boto3_session"):
        with patch(
            "deadline._agents.agents.farm_setup_agent.Agent", return_value=mock_agent
        ) as mock_agent_class:
            with patch(
                "deadline._agents.agents.farm_setup_agent.get_farm_setup_model"
            ) as mock_get_model:
                with patch(
                    "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
                ):
                    mock_model = MagicMock()
                    mock_get_model.return_value = mock_model

                    farm_setup_agent("Check fleet configuration")

                    # Verify model was retrieved with boto_session
                    mock_get_model.assert_called_once()

                    # Verify Agent was created with the model
                    call_kwargs = mock_agent_class.call_args[1]
                    assert call_kwargs["model"] == mock_model


def test_farm_setup_agent_has_callback_handler(mock_agent):
    """Test that farm setup agent has a callback handler for streaming."""
    with patch("deadline.client.api.get_boto3_session"):
        with patch(
            "deadline._agents.agents.farm_setup_agent.Agent", return_value=mock_agent
        ) as mock_agent_class:
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ):
                farm_setup_agent("Check fleet configuration")

                # Verify Agent was created with a callback_handler
                call_kwargs = mock_agent_class.call_args[1]
                assert call_kwargs["callback_handler"] is not None
                assert callable(call_kwargs["callback_handler"])


def test_farm_setup_agent_error_handling():
    """Test farm setup agent error handling."""
    mock_agent = MagicMock()
    mock_agent.side_effect = Exception("Test error")

    with patch("deadline.client.api.get_boto3_session"):
        with patch("deadline._agents.agents.farm_setup_agent.Agent", return_value=mock_agent):
            with patch(
                "deadline.client.api._telemetry.get_deadline_cloud_library_telemetry_client"
            ):
                result = farm_setup_agent("Check fleet configuration")

                assert "Error in fleet configuration agent" in result
                assert "Test error" in result


def test_get_fleet_details_success(mock_boto3_client):
    """Test get_fleet_details with successful response."""
    mock_boto3_client.get_fleet.return_value = {
        "displayName": "Test Fleet",
        "status": "ACTIVE",
        "minWorkerCount": 1,
        "maxWorkerCount": 10,
        "workerCount": 5,
        "configuration": {
            "serviceManagedEc2": {
                "instanceMarketOptions": {"type": "on-demand"},
                "instanceCapabilities": {
                    "vCpuCount": {"min": 2, "max": 8},
                    "memoryMiB": {"min": 4096, "max": 16384},
                    "osFamily": "LINUX",
                    "cpuArchitectureType": "x86_64",
                },
            }
        },
    }

    with patch(
        "deadline._agents.agents.farm_setup_agent.get_boto3_client", return_value=mock_boto3_client
    ):
        result = get_fleet_details("farm-123", "fleet-456")

        assert "Test Fleet" in result
        assert "ACTIVE" in result
        assert "Min Worker Count: 1" in result
        assert "Max Worker Count: 10" in result


def test_get_fleet_details_error(mock_boto3_client):
    """Test get_fleet_details with error."""
    mock_boto3_client.get_fleet.side_effect = Exception("Fleet not found")

    with patch(
        "deadline._agents.agents.farm_setup_agent.get_boto3_client", return_value=mock_boto3_client
    ):
        result = get_fleet_details("farm-123", "fleet-456")

        assert "Error getting fleet details" in result


def test_list_queue_fleets_success(mock_boto3_client):
    """Test list_queue_fleets with successful response."""
    mock_boto3_client.list_queue_fleet_associations.return_value = {
        "queueFleetAssociations": [
            {"fleetId": "fleet-123", "status": "ACTIVE", "createdAt": "2024-01-01T00:00:00Z"},
            {"fleetId": "fleet-456", "status": "ACTIVE", "createdAt": "2024-01-02T00:00:00Z"},
        ]
    }

    with patch(
        "deadline._agents.agents.farm_setup_agent.get_boto3_client", return_value=mock_boto3_client
    ):
        result = list_queue_fleets("farm-123", "queue-789")

        assert "fleet-123" in result
        assert "fleet-456" in result
        assert "ACTIVE" in result


def test_list_queue_fleets_no_associations(mock_boto3_client):
    """Test list_queue_fleets with no fleet associations."""
    mock_boto3_client.list_queue_fleet_associations.return_value = {"queueFleetAssociations": []}

    with patch(
        "deadline._agents.agents.farm_setup_agent.get_boto3_client", return_value=mock_boto3_client
    ):
        result = list_queue_fleets("farm-123", "queue-789")

        assert "No fleets associated" in result
        assert "common issue" in result


def test_list_fleet_queues_success(mock_boto3_client):
    """Test list_fleet_queues with successful response."""
    mock_boto3_client.list_queue_fleet_associations.return_value = {
        "queueFleetAssociations": [
            {"queueId": "queue-123", "status": "ACTIVE", "createdAt": "2024-01-01T00:00:00Z"}
        ]
    }

    with patch(
        "deadline._agents.agents.farm_setup_agent.get_boto3_client", return_value=mock_boto3_client
    ):
        result = list_fleet_queues("farm-123", "fleet-456")

        assert "queue-123" in result
        assert "ACTIVE" in result


def test_check_fleet_workers_success(mock_boto3_client):
    """Test check_fleet_workers with workers present."""
    mock_boto3_client.list_workers.return_value = {
        "workers": [
            {"workerId": "worker-1", "status": "STARTED", "createdAt": "2024-01-01T00:00:00Z"},
            {"workerId": "worker-2", "status": "STARTED", "createdAt": "2024-01-01T00:00:00Z"},
        ]
    }

    with patch(
        "deadline._agents.agents.farm_setup_agent.get_boto3_client", return_value=mock_boto3_client
    ):
        result = check_fleet_workers("farm-123", "fleet-456")

        assert "worker-1" in result
        assert "worker-2" in result
        assert "STARTED" in result
        assert "Total Workers: 2" in result


def test_check_fleet_workers_no_workers(mock_boto3_client):
    """Test check_fleet_workers with no workers."""
    mock_boto3_client.list_workers.return_value = {"workers": []}

    with patch(
        "deadline._agents.agents.farm_setup_agent.get_boto3_client", return_value=mock_boto3_client
    ):
        result = check_fleet_workers("farm-123", "fleet-456")

        assert "No workers currently running" in result
        assert "Min worker count" in result


def test_validate_fleet_configuration_success(mock_boto3_client):
    """Test validate_fleet_configuration with valid configuration."""
    mock_boto3_client.get_fleet.return_value = {
        "status": "ACTIVE",
        "minWorkerCount": 1,
        "maxWorkerCount": 10,
    }
    mock_boto3_client.list_queue_fleet_associations.return_value = {
        "queueFleetAssociations": [{"queueId": "queue-123"}]
    }

    with patch(
        "deadline._agents.agents.farm_setup_agent.get_boto3_client", return_value=mock_boto3_client
    ):
        result = validate_fleet_configuration("farm-123", "fleet-456")

        assert "No configuration issues detected" in result


def test_validate_fleet_configuration_issues(mock_boto3_client):
    """Test validate_fleet_configuration with configuration issues."""
    mock_boto3_client.get_fleet.return_value = {
        "status": "INACTIVE",
        "minWorkerCount": 0,
        "maxWorkerCount": 0,
    }
    mock_boto3_client.list_queue_fleet_associations.return_value = {"queueFleetAssociations": []}

    with patch(
        "deadline._agents.agents.farm_setup_agent.get_boto3_client", return_value=mock_boto3_client
    ):
        result = validate_fleet_configuration("farm-123", "fleet-456")

        assert "ISSUES FOUND" in result
        assert "not ACTIVE" in result
        assert "worker counts are 0" in result
        assert "No queues associated" in result
