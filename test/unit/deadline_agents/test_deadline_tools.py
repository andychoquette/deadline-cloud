# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Unit tests for Deadline tools."""

import pytest
from unittest.mock import patch, MagicMock
import os

# Skip all tests if strands-agents is not available
pytest.importorskip("strands", reason="strands-agents dependencies not available")

from deadline._agents.tools.deadline_tools import (
    validate_deadline_id,
    format_tool_error,
    get_deadline_client,
    list_deadline_queues,
    get_queue_details,
    list_deadline_jobs,
    get_deadline_job_details,
    list_deadline_steps,
    get_deadline_step_details,
    list_deadline_tasks,
    get_deadline_task_details,
    list_deadline_sessions,
    get_deadline_session_details,
    list_deadline_session_actions,
    get_deadline_worker_details,
    get_queue_role_credentials,
    get_deadline_tools,
)


@pytest.fixture
def mock_deadline_client():
    """Mock Deadline client for testing."""
    with patch("deadline.client.api.get_boto3_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


class TestValidateDeadlineId:
    """Tests for validate_deadline_id function."""

    def test_valid_session_id(self):
        """Test validation of valid session ID."""
        is_valid, error = validate_deadline_id(
            "session-c45e67929df54960a558170de8cb02a8", "session"
        )
        assert is_valid is True
        assert error == ""

    def test_valid_task_id(self):
        """Test validation of valid task ID."""
        is_valid, error = validate_deadline_id("task-a1b2c3d4e5f6789012345678901234ab", "task")
        assert is_valid is True
        assert error == ""

    def test_valid_step_id(self):
        """Test validation of valid step ID."""
        is_valid, error = validate_deadline_id("step-a1b2c3d4e5f6789012345678901234ab", "step")
        assert is_valid is True
        assert error == ""

    def test_valid_job_id(self):
        """Test validation of valid job ID."""
        is_valid, error = validate_deadline_id("job-a1b2c3d4e5f6789012345678901234ab", "job")
        assert is_valid is True
        assert error == ""

    def test_invalid_session_id_format(self):
        """Test validation of invalid session ID format."""
        is_valid, error = validate_deadline_id("invalid-session-id", "session")
        assert is_valid is False
        assert "Invalid session ID format" in error

    def test_wrong_resource_type(self):
        """Test validation when wrong resource type is provided."""
        is_valid, error = validate_deadline_id("task-a1b2c3d4e5f6789012345678901234ab", "session")
        assert is_valid is False
        assert "CRITICAL ERROR" in error
        assert "You provided a TASK ID" in error

    def test_unknown_id_type(self):
        """Test validation with unknown ID type."""
        is_valid, error = validate_deadline_id("unknown-123", "unknown")
        assert is_valid is True
        assert error == ""


class TestFormatToolError:
    """Tests for format_tool_error function."""

    def test_access_denied_error(self):
        """Test formatting of AccessDeniedException."""
        error = Exception("AccessDeniedException: User not authorized")
        result = format_tool_error(error, context="testing access")

        assert "PERMISSION ERROR" in result
        assert "DO NOT RETRY" in result
        assert "testing access" in result

    def test_resource_not_found_error(self):
        """Test formatting of ResourceNotFoundException."""
        error = Exception("ResourceNotFoundException: Resource not found")
        result = format_tool_error(error, context="testing resource")

        assert "RESOURCE NOT FOUND" in result
        assert "DO NOT RETRY" in result

    def test_validation_error(self):
        """Test formatting of ValidationException."""
        error = Exception("ValidationException: Invalid parameter")
        result = format_tool_error(error, context="testing validation")

        assert "VALIDATION ERROR" in result
        assert "DO NOT RETRY" in result

    def test_generic_error(self):
        """Test formatting of generic error."""
        error = Exception("Some generic error")
        result = format_tool_error(error, context="testing generic")

        assert "ERROR - DO NOT RETRY" in result
        assert "testing generic" in result


class TestGetDeadlineClient:
    """Tests for get_deadline_client function."""

    def test_get_client_success(self):
        """Test getting Deadline client successfully."""
        with patch("deadline.client.api.get_boto3_client") as mock:
            mock_client = MagicMock()
            mock.return_value = mock_client

            result = get_deadline_client()

            assert result == mock_client
            mock.assert_called_once_with("deadline", config=None)


class TestListDeadlineQueues:
    """Tests for list_deadline_queues function."""

    def test_list_queues_success(self, mock_deadline_client):
        """Test listing queues successfully."""
        mock_deadline_client.list_queues.return_value = {
            "queues": [
                {
                    "queueId": "queue-123",
                    "displayName": "Test Queue",
                    "status": "ACTIVE",
                    "defaultBudgetAction": "STOP",
                }
            ]
        }

        result = list_deadline_queues(farm_id="farm-123")

        assert "Found 1 queue(s)" in result
        assert "Test Queue" in result
        assert "queue-123" in result

    def test_list_queues_empty(self, mock_deadline_client):
        """Test listing queues when none exist."""
        mock_deadline_client.list_queues.return_value = {"queues": []}

        result = list_deadline_queues(farm_id="farm-123")

        assert "No queues found" in result

    def test_list_queues_with_principal_id(self, mock_deadline_client):
        """Test listing queues with principal ID from environment."""
        mock_deadline_client.list_queues.return_value = {"queues": []}

        with patch.dict(os.environ, {"DEADLINE_PRINCIPAL_ID": "principal-123"}):
            list_deadline_queues(farm_id="farm-123")

            mock_deadline_client.list_queues.assert_called_once()
            call_args = mock_deadline_client.list_queues.call_args[1]
            assert call_args["principalId"] == "principal-123"

    def test_list_queues_error(self, mock_deadline_client):
        """Test error handling when listing queues."""
        mock_deadline_client.list_queues.side_effect = Exception("API Error")

        result = list_deadline_queues(farm_id="farm-123")

        assert "ERROR" in result


class TestGetQueueDetails:
    """Tests for get_queue_details function."""

    def test_get_queue_details_success(self, mock_deadline_client):
        """Test getting queue details successfully."""
        mock_deadline_client.get_queue.return_value = {
            "displayName": "Test Queue",
            "status": "ACTIVE",
            "defaultBudgetAction": "STOP",
            "createdAt": "2024-01-01T00:00:00Z",
            "createdBy": "user-123",
            "jobAttachmentSettings": {
                "s3BucketName": "test-bucket",
                "rootPrefix": "deadline/",
            },
            "roleArn": "arn:aws:iam::123456789012:role/DeadlineQueue",
        }

        result = get_queue_details(farm_id="farm-123", queue_id="queue-456")

        assert "Test Queue" in result
        assert "ACTIVE" in result
        assert "test-bucket" in result
        assert "deadline/" in result

    def test_get_queue_details_no_job_attachments(self, mock_deadline_client):
        """Test getting queue details without job attachments settings."""
        mock_deadline_client.get_queue.return_value = {
            "displayName": "Test Queue",
            "status": "ACTIVE",
        }

        result = get_queue_details(farm_id="farm-123", queue_id="queue-456")

        assert "No job attachments settings" in result


class TestListDeadlineJobs:
    """Tests for list_deadline_jobs function."""

    def test_list_jobs_success(self, mock_deadline_client):
        """Test listing jobs successfully."""
        mock_deadline_client.search_jobs.return_value = {
            "jobs": [
                {
                    "jobId": "job-123",
                    "name": "Test Job",
                    "lifecycleStatus": "SUCCEEDED",
                    "priority": 50,
                    "createdAt": "2024-01-01T00:00:00Z",
                    "createdBy": "user-123",
                }
            ],
            "totalResults": 1,
        }

        result = list_deadline_jobs(farm_id="farm-123", queue_id="queue-456")

        assert "Found 1 of 1 job(s)" in result
        assert "Test Job" in result
        assert "job-123" in result

    def test_list_jobs_empty(self, mock_deadline_client):
        """Test listing jobs when none exist."""
        mock_deadline_client.search_jobs.return_value = {"jobs": [], "totalResults": 0}

        result = list_deadline_jobs(farm_id="farm-123", queue_id="queue-456")

        assert "No jobs found" in result


class TestGetDeadlineJobDetails:
    """Tests for get_deadline_job_details function."""

    def test_get_job_details_success(self, mock_deadline_client):
        """Test getting job details successfully."""
        mock_deadline_client.get_job.return_value = {
            "name": "Test Job",
            "lifecycleStatus": "SUCCEEDED",
            "taskRunStatus": "SUCCEEDED",
            "priority": 50,
            "createdAt": "2024-01-01T00:00:00Z",
            "startedAt": "2024-01-01T00:01:00Z",
            "endedAt": "2024-01-01T00:10:00Z",
            "taskRunStatusCounts": {"SUCCEEDED": 10, "FAILED": 0},
        }

        result = get_deadline_job_details(
            farm_id="farm-123", queue_id="queue-456", job_id="job-789"
        )

        assert "Test Job" in result
        assert "SUCCEEDED" in result
        assert "Task Status Counts" in result

    def test_get_job_details_with_failures(self, mock_deadline_client):
        """Test getting job details with failed tasks."""
        mock_deadline_client.get_job.return_value = {
            "name": "Failed Job",
            "lifecycleStatus": "FAILED",
            "taskRunStatus": "FAILED",
            "taskRunStatusCounts": {"SUCCEEDED": 5, "FAILED": 3},
        }

        result = get_deadline_job_details(
            farm_id="farm-123", queue_id="queue-456", job_id="job-789"
        )

        assert "WARNING" in result
        assert "3 task(s) FAILED" in result


class TestListDeadlineSteps:
    """Tests for list_deadline_steps function."""

    def test_list_steps_success(self, mock_deadline_client):
        """Test listing steps successfully."""
        mock_deadline_client.search_steps.return_value = {
            "steps": [
                {
                    "stepId": "step-123",
                    "name": "Render",
                    "lifecycleStatus": "COMPLETE",
                    "taskRunStatus": "SUCCEEDED",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "taskRunStatusCounts": {"SUCCEEDED": 10},
                }
            ],
            "totalResults": 1,
        }

        result = list_deadline_steps(farm_id="farm-123", queue_id="queue-456", job_id="job-789")

        assert "Found 1 of 1 step(s)" in result
        assert "Render" in result
        assert "step-123" in result

    def test_list_steps_tracks_state(self, mock_deadline_client):
        """Test that list_steps tracks discovered step IDs in agent state."""
        mock_deadline_client.search_steps.return_value = {
            "steps": [{"stepId": "step-123", "name": "Render"}],
            "totalResults": 1,
        }

        # Create a proper ToolContext mock that will pass isinstance check
        from strands import ToolContext

        # Create a real-ish mock that passes isinstance
        mock_agent = MagicMock()
        mock_agent.state.get.return_value = []

        mock_tool_context = MagicMock(spec=ToolContext)
        mock_tool_context.agent = mock_agent

        # Make isinstance work by setting the class
        type(mock_tool_context).__name__ = "ToolContext"

        list_deadline_steps(
            farm_id="farm-123",
            queue_id="queue-456",
            job_id="job-789",
            tool_context=mock_tool_context,
        )

        # Verify state was set with discovered steps
        mock_agent.state.set.assert_called_once()
        call_args = mock_agent.state.set.call_args[0]
        assert call_args[0] == "discovered_steps"
        assert "step-123" in call_args[1]


class TestGetDeadlineStepDetails:
    """Tests for get_deadline_step_details function."""

    def test_get_step_details_success(self, mock_deadline_client):
        """Test getting step details successfully."""
        mock_deadline_client.get_step.return_value = {
            "name": "Render",
            "lifecycleStatus": "COMPLETE",
            "taskRunStatus": "SUCCEEDED",
            "createdAt": "2024-01-01T00:00:00Z",
            "startedAt": "2024-01-01T00:01:00Z",
            "endedAt": "2024-01-01T00:10:00Z",
            "taskRunStatusCounts": {"SUCCEEDED": 10},
        }

        result = get_deadline_step_details(
            farm_id="farm-123", queue_id="queue-456", job_id="job-789", step_id="step-abc"
        )

        assert "Render" in result
        assert "COMPLETE" in result


class TestListDeadlineTasks:
    """Tests for list_deadline_tasks function."""

    def test_list_tasks_success(self, mock_deadline_client):
        """Test listing tasks successfully."""
        mock_deadline_client.search_tasks.return_value = {
            "tasks": [
                {
                    "taskId": "task-123",
                    "runStatus": "SUCCEEDED",
                    "createdAt": "2024-01-01T00:00:00Z",
                }
            ],
            "totalResults": 1,
        }

        result = list_deadline_tasks(
            farm_id="farm-123", queue_id="queue-456", job_id="job-789", step_id="step-abc"
        )

        assert "Found 1 of 1 task(s)" in result
        assert "task-123" in result

    def test_list_tasks_with_status_filter(self, mock_deadline_client):
        """Test listing tasks with status filter."""
        mock_deadline_client.search_tasks.return_value = {
            "tasks": [{"taskId": "task-123", "runStatus": "FAILED"}],
            "totalResults": 1,
        }

        result = list_deadline_tasks(
            farm_id="farm-123",
            queue_id="queue-456",
            job_id="job-789",
            step_id="step-abc",
            status_filter="FAILED",
        )

        assert "with status FAILED" in result

    def test_list_tasks_invalid_status_filter(self, mock_deadline_client):
        """Test listing tasks with invalid status filter."""
        result = list_deadline_tasks(
            farm_id="farm-123",
            queue_id="queue-456",
            job_id="job-789",
            step_id="step-abc",
            status_filter="INVALID_STATUS",
        )

        assert "Invalid status_filter" in result


class TestGetDeadlineTaskDetails:
    """Tests for get_deadline_task_details function."""

    def test_get_task_details_success(self, mock_deadline_client):
        """Test getting task details successfully."""
        mock_deadline_client.get_task.return_value = {
            "runStatus": "SUCCEEDED",
            "createdAt": "2024-01-01T00:00:00Z",
            "startedAt": "2024-01-01T00:01:00Z",
            "endedAt": "2024-01-01T00:10:00Z",
            "latestSessionActionId": "action-123",
        }

        result = get_deadline_task_details(
            farm_id="farm-123",
            queue_id="queue-456",
            job_id="job-789",
            step_id="step-a1b2c3d4e5f6789012345678901234ab",
            task_id="task-a1b2c3d4e5f6789012345678901234ab",
        )

        assert "SUCCEEDED" in result
        assert "action-123" in result

    def test_get_task_details_invalid_step_id(self, mock_deadline_client):
        """Test getting task details with invalid step ID."""
        result = get_deadline_task_details(
            farm_id="farm-123",
            queue_id="queue-456",
            job_id="job-789",
            step_id="invalid-step",
            task_id="task-a1b2c3d4e5f6789012345678901234ab",
        )

        assert "Invalid step ID format" in result


class TestListDeadlineSessions:
    """Tests for list_deadline_sessions function."""

    def test_list_sessions_success(self, mock_deadline_client):
        """Test listing sessions successfully."""
        mock_deadline_client.list_sessions.return_value = {
            "sessions": [
                {
                    "sessionId": "session-123",
                    "lifecycleStatus": "ENDED",
                    "fleetId": "fleet-456",
                    "workerId": "worker-789",
                    "startedAt": "2024-01-01T00:00:00Z",
                    "endedAt": "2024-01-01T00:10:00Z",
                }
            ]
        }

        result = list_deadline_sessions(farm_id="farm-123", queue_id="queue-456", job_id="job-789")

        assert "Found 1 session(s)" in result
        assert "session-123" in result


class TestGetDeadlineSessionDetails:
    """Tests for get_deadline_session_details function."""

    def test_get_session_details_success(self, mock_deadline_client):
        """Test getting session details successfully."""
        mock_deadline_client.get_session.return_value = {
            "lifecycleStatus": "ENDED",
            "fleetId": "fleet-456",
            "workerId": "worker-789",
            "startedAt": "2024-01-01T00:00:00Z",
            "endedAt": "2024-01-01T00:10:00Z",
            "targetLifecycleStatus": "ENDED",
            "log": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "/aws/deadline/farm-123/fleet-456",
                    "awslogs-stream": "worker-789",
                },
            },
        }

        result = get_deadline_session_details(
            farm_id="farm-123",
            queue_id="queue-456",
            job_id="job-789",
            session_id="session-c45e67929df54960a558170de8cb02a8",
        )

        assert "ENDED" in result
        assert "fleet-456" in result
        assert "Worker Log Location" in result

    def test_get_session_details_hallucinated_id(self, mock_deadline_client):
        """Test getting session details with hallucinated session ID."""
        result = get_deadline_session_details(
            farm_id="farm-123",
            queue_id="queue-456",
            job_id="job-789",
            session_id="session-00000000000000000000000000000000",
        )

        assert "Invalid session ID detected" in result
        assert "placeholder or hallucinated" in result


class TestListDeadlineSessionActions:
    """Tests for list_deadline_session_actions function."""

    def test_list_session_actions_success(self, mock_deadline_client):
        """Test listing session actions successfully."""
        mock_deadline_client.list_session_actions.return_value = {
            "sessionActions": [
                {
                    "sessionActionId": "action-123",
                    "status": "SUCCEEDED",
                    "startedAt": "2024-01-01T00:00:00Z",
                    "endedAt": "2024-01-01T00:01:00Z",
                    "definition": {"taskRun": {"taskId": "task-456", "stepId": "step-789"}},
                }
            ]
        }

        result = list_deadline_session_actions(
            farm_id="farm-123",
            queue_id="queue-456",
            job_id="job-789",
            session_id="session-c45e67929df54960a558170de8cb02a8",
        )

        assert "Found 1 session action(s)" in result
        assert "action-123" in result


class TestGetDeadlineWorkerDetails:
    """Tests for get_deadline_worker_details function."""

    def test_get_worker_details_success(self, mock_deadline_client):
        """Test getting worker details successfully."""
        mock_deadline_client.get_worker.return_value = {
            "status": "RUNNING",
            "createdAt": "2024-01-01T00:00:00Z",
            "createdBy": "system",
            "updatedAt": "2024-01-01T00:10:00Z",
            "hostProperties": {
                "ipAddresses": {"ipV4Addresses": ["10.0.0.1"]},
                "hostName": "worker-host",
                "ec2InstanceArn": "arn:aws:ec2:us-west-2:123456789012:instance/i-1234567890abcdef0",
            },
        }

        result = get_deadline_worker_details(
            farm_id="farm-123", fleet_id="fleet-456", worker_id="worker-789"
        )

        assert "RUNNING" in result
        assert "10.0.0.1" in result

    def test_get_worker_details_not_found(self, mock_deadline_client):
        """Test getting worker details when worker no longer exists."""
        mock_deadline_client.get_worker.side_effect = Exception(
            "ResourceNotFoundException: Worker not found"
        )

        result = get_deadline_worker_details(
            farm_id="farm-123", fleet_id="fleet-456", worker_id="worker-789"
        )

        assert "no longer available" in result
        assert "likely terminated" in result


class TestGetQueueRoleCredentials:
    """Tests for get_queue_role_credentials function."""

    def test_get_queue_role_credentials_success(self):
        """Test getting queue role credentials successfully."""
        with patch("deadline.client.api.get_boto3_client") as mock:
            mock_client = MagicMock()
            mock.return_value = mock_client

            mock_client.assume_queue_role_for_read.return_value = {
                "credentials": {
                    "accessKeyId": "test_key",
                    "secretAccessKey": "test_secret",
                    "sessionToken": "test_token",
                }
            }

            result = get_queue_role_credentials(farm_id="farm-123", queue_id="queue-456")

            assert result is not None
            assert result["access_key_id"] == "test_key"
            assert result["secret_access_key"] == "test_secret"
            assert result["session_token"] == "test_token"

    def test_get_queue_role_credentials_failure(self):
        """Test getting queue role credentials when it fails."""
        with patch("deadline.client.api.get_boto3_client") as mock:
            mock_client = MagicMock()
            mock.return_value = mock_client

            mock_client.assume_queue_role_for_read.side_effect = Exception("Failed to assume role")

            result = get_queue_role_credentials(farm_id="farm-123", queue_id="queue-456")

            assert result is None


class TestGetDeadlineTools:
    """Tests for get_deadline_tools function."""

    def test_get_tools_returns_list(self):
        """Test that get_deadline_tools returns a list of tools."""
        tools = get_deadline_tools()

        assert isinstance(tools, list)
        assert len(tools) > 0
        assert list_deadline_queues in tools
        assert get_queue_details in tools
        assert list_deadline_jobs in tools
