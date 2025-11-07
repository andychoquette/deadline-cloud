# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Custom Deadline Cloud tools using the SDK directly.
Alternative to MCP server until mcp-server command is available.
"""

from strands import tool, ToolContext
import logging
from typing import Optional
from configparser import ConfigParser
import os

# Import deadline package's credential management

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def validate_deadline_id(id_value: str, id_type: str) -> tuple[bool, str]:
    """
    Validate Deadline Cloud resource ID format.

    Args:
        id_value: The ID value to validate
        id_type: Type of ID (session, task, step, job, etc.)

    Returns:
        Tuple of (is_valid, error_message)
    """
    import re

    patterns = {
        "session": r"^session-[0-9a-f]{32}$",
        "task": r"^task-[0-9a-f]{32}$",
        "step": r"^step-[0-9a-f]{32}$",
        "job": r"^job-[0-9a-f]{32}$",
    }

    if id_type not in patterns:
        return True, ""  # Unknown type, skip validation

    pattern = patterns[id_type]
    if not re.match(pattern, id_value):
        example_ids = {
            "session": "session-c45e67929df54960a558170de8cb02a8",
            "task": "task-a1b2c3d4e5f6789012345678901234ab",
            "step": "step-a1b2c3d4e5f6789012345678901234ab",
            "job": "job-a1b2c3d4e5f6789012345678901234ab",
        }

        # Check if user is trying to use wrong resource type
        wrong_type_detected = None
        for other_type, other_pattern in patterns.items():
            if other_type != id_type and re.match(other_pattern, id_value):
                wrong_type_detected = other_type
                break

        error_msg = f"Invalid {id_type} ID format: {id_value}\n"

        if wrong_type_detected:
            error_msg += f"\n⚠️  CRITICAL ERROR: You provided a {wrong_type_detected.upper()} ID, but this function requires a {id_type.upper()} ID!\n"
            error_msg += (
                f"   - {wrong_type_detected.capitalize()} IDs start with '{wrong_type_detected}-'\n"
            )
            error_msg += f"   - {id_type.capitalize()} IDs start with '{id_type}-'\n"
            error_msg += (
                "   - DO NOT try to convert between resource types by replacing the prefix!\n\n"
            )

            if id_type == "session" and wrong_type_detected == "task":
                error_msg += "To get the session ID for a task:\n"
                error_msg += "1. Call list_deadline_sessions for the job, OR\n"
                error_msg += "2. Call list_deadline_session_actions with the task_id parameter\n"
                error_msg += "3. Extract the sessionId from the session action details\n\n"
        else:
            error_msg += (
                f"{id_type.capitalize()} ID must match pattern '{id_type}-[32 hex characters]'.\n"
            )
            error_msg += f"Example: {example_ids.get(id_type, 'N/A')}\n"

        error_msg += f"Please use list_deadline_{id_type}s to get valid {id_type} IDs."

        return False, error_msg

    return True, ""


def format_tool_error(error: Exception, context: str = "") -> str:
    """
    Format tool errors in a way that prevents infinite retries.

    Args:
        error: The exception that occurred
        context: Additional context about what operation failed

    Returns:
        Formatted error message that instructs the agent not to retry
    """
    error_msg = str(error)

    # Check for specific error types that should not be retried
    if "AccessDeniedException" in error_msg or "not authorized" in error_msg:
        return (
            f"❌ PERMISSION ERROR - DO NOT RETRY: {error_msg}\n\n"
            f"Context: {context}\n\n"
            "**This is likely a permissions or authentication issue.**\n\n"
            "Please inform the user about this error and ask them to:\n"
            "1. Verify their AWS credentials are correct\n"
            "2. Check that they have the necessary IAM permissions\n"
            "3. Ensure the principal ID (if used) is a valid Deadline identity\n\n"
            "DO NOT retry this operation without user intervention."
        )
    elif "ResourceNotFoundException" in error_msg or "not found" in error_msg.lower():
        return (
            f"❌ RESOURCE NOT FOUND - DO NOT RETRY: {error_msg}\n\n"
            f"Context: {context}\n\n"
            "**The requested resource does not exist.**\n\n"
            "Please inform the user and ask them to:\n"
            "1. Verify the resource ID is correct\n"
            "2. Check that the resource exists in the specified region\n"
            "3. Confirm they have access to view this resource\n\n"
            "DO NOT retry with the same parameters."
        )
    elif "ValidationException" in error_msg or "Invalid" in error_msg:
        return (
            f"❌ VALIDATION ERROR - DO NOT RETRY: {error_msg}\n\n"
            f"Context: {context}\n\n"
            "**The request parameters are invalid.**\n\n"
            "Please inform the user about this validation error.\n"
            "DO NOT retry with the same parameters."
        )
    else:
        # Generic error - still should not retry without changes
        return (
            f"❌ ERROR - DO NOT RETRY: {error_msg}\n\n"
            f"Context: {context}\n\n"
            "Please inform the user about this error and ask for guidance on how to proceed.\n"
            "DO NOT retry the same operation without changes."
        )


def get_deadline_client(config: Optional[ConfigParser] = None):
    """
    Get a Deadline Cloud client using the deadline package's credential system.

    This automatically handles:
    - AWS profiles from ~/.deadline/config
    - Deadline Cloud Monitor credentials
    - Default AWS credential chain
    - IAM roles

    Args:
        config: Optional configuration parser for custom settings

    Returns:
        boto3 client for deadline service
    """
    from ...client.api import get_boto3_client

    return get_boto3_client("deadline", config=config)


@tool
def list_deadline_queues(farm_id: str) -> str:
    """
    List all queues in a specific Deadline Cloud farm.

    Args:
        farm_id: The ID of the farm to list queues from

    Returns:
        String containing queue information or error message
    """

    try:
        client = get_deadline_client()

        # Build parameters
        params = {"farmId": farm_id, "maxResults": 50}

        # Add principal ID if available (must be Deadline identity ID)
        principal_id = os.getenv("DEADLINE_PRINCIPAL_ID")
        if principal_id:
            params["principalId"] = principal_id

        response = client.list_queues(**params)

        queues = response.get("queues", [])
        if not queues:
            return f"No queues found in farm {farm_id}."

        result = f"Found {len(queues)} queue(s) in farm {farm_id}:\n\n"
        for queue in queues:
            result += f"- **{queue['displayName']}** (ID: {queue['queueId']})\n"
            result += f"  Status: {queue.get('status', 'N/A')}\n"
            result += f"  Default Budget: {queue.get('defaultBudgetAction', 'N/A')}\n\n"

        return result

    except Exception as e:
        logger.error(f"Error listing queues: {e}")
        return format_tool_error(e, context=f"listing queues in farm {farm_id}")


@tool
def get_queue_details(farm_id: str, queue_id: str) -> str:
    """
    Get detailed information about a specific Deadline Cloud queue.

    This includes job attachments configuration, which specifies the S3 bucket
    and root prefix where job files are stored.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue

    Returns:
        String containing detailed queue information including job attachments settings
    """

    try:
        client = get_deadline_client()
        response = client.get_queue(farmId=farm_id, queueId=queue_id)

        result = f"**Queue Details for {queue_id}**\n\n"
        result += f"Display Name: {response.get('displayName', 'N/A')}\n"
        result += f"Status: {response.get('status', 'N/A')}\n"
        result += f"Default Budget Action: {response.get('defaultBudgetAction', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Created By: {response.get('createdBy', 'N/A')}\n"

        # Job Attachments Settings - CRITICAL for job attachments troubleshooting
        if response.get("jobAttachmentSettings"):
            result += "\n**Job Attachments Settings:**\n"
            settings = response["jobAttachmentSettings"]

            bucket_name = settings.get("s3BucketName", "N/A")
            root_prefix = settings.get("rootPrefix", "")

            result += f"S3 Bucket: {bucket_name}\n"
            result += f"Root Prefix: {root_prefix}\n"

            if bucket_name != "N/A":
                result += f"\n💡 Job attachments are stored at: s3://{bucket_name}/{root_prefix}\n"
                result += "💡 Use this bucket name when checking S3 permissions.\n"
        else:
            result += "\n⚠️  No job attachments settings configured for this queue.\n"

        # Role ARN
        if response.get("roleArn"):
            result += f"\nQueue Role ARN: {response['roleArn']}\n"

        # Description
        if response.get("description"):
            result += f"\nDescription: {response['description']}\n"

        return result

    except Exception as e:
        logger.error(f"Error getting queue details: {e}")
        return format_tool_error(e, context=f"getting details for queue {queue_id}")


@tool
def list_queue_environments(farm_id: str, queue_id: str, max_results: int = 20) -> str:
    """
    List all environments configured for a specific Deadline Cloud queue.

    Queue environments define the software and configuration that workers use
    during job setup (envEnter) and teardown (envExit). Issues with environments
    can cause setup/teardown failures.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        max_results: Maximum number of environments to return (default: 20)

    Returns:
        String containing queue environment information or error message
    """

    try:
        client = get_deadline_client()

        response = client.list_queue_environments(
            farmId=farm_id, queueId=queue_id, maxResults=min(max_results, 100)
        )

        environments = response.get("environments", [])
        if not environments:
            return f"No environments found for queue {queue_id}."

        result = f"Found {len(environments)} environment(s) for queue {queue_id}:\n\n"
        for env in environments:
            result += f"- **Environment {env['queueEnvironmentId']}**\n"
            result += f"  Name: {env.get('name', 'N/A')}\n"
            result += f"  Priority: {env.get('priority', 'N/A')}\n"

            if env.get("templateType"):
                result += f"  Template Type: {env['templateType']}\n"

            result += "\n"

        result += (
            "\n💡 Use get_queue_environment to see detailed configuration for each environment.\n"
        )

        return result

    except Exception as e:
        logger.error(f"Error listing queue environments: {e}")
        return format_tool_error(e, context=f"listing environments for queue {queue_id}")


@tool
def get_queue_environment(farm_id: str, queue_id: str, queue_environment_id: str) -> str:
    """
    Get detailed configuration for a specific queue environment.

    This is critical for diagnosing setup/teardown issues. The environment defines:
    - Software packages and versions to install
    - Environment variables to set
    - Scripts to run during setup (envEnter) and teardown (envExit)

    Common issues found in environments:
    - Missing or incorrect software dependencies
    - Invalid environment variable configurations
    - Script errors in setup/teardown commands
    - Incorrect file paths or permissions

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        queue_environment_id: The ID of the queue environment

    Returns:
        String containing detailed environment configuration or error message
    """

    try:
        client = get_deadline_client()

        response = client.get_queue_environment(
            farmId=farm_id, queueId=queue_id, queueEnvironmentId=queue_environment_id
        )

        result = f"**Queue Environment Details: {queue_environment_id}**\n\n"
        result += f"Name: {response.get('name', 'N/A')}\n"
        result += f"Priority: {response.get('priority', 'N/A')}\n"
        result += f"Template Type: {response.get('templateType', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Created By: {response.get('createdBy', 'N/A')}\n"
        result += f"Updated: {response.get('updatedAt', 'N/A')}\n"

        if response.get("updatedBy"):
            result += f"Updated By: {response['updatedBy']}\n"

        # Template content - this is the key configuration
        if response.get("template"):
            result += "\n**Environment Template:**\n"
            template = response["template"]

            # Show template in a readable format
            import json

            try:
                # Try to parse as JSON for better formatting
                if isinstance(template, str):
                    template_obj = json.loads(template)
                    result += f"```json\n{json.dumps(template_obj, indent=2)}\n```\n"
                else:
                    result += f"```json\n{json.dumps(template, indent=2)}\n```\n"
            except Exception:
                # If not JSON, show as-is
                result += f"```\n{template}\n```\n"

        result += "\n**Troubleshooting Tips:**\n"
        result += "- Check for missing software dependencies in the template\n"
        result += "- Verify environment variables are correctly formatted\n"
        result += "- Look for script errors in setup/teardown commands\n"
        result += "- Ensure file paths and permissions are correct\n"
        result += "- Compare with working environments if available\n"

        return result

    except Exception as e:
        logger.error(f"Error getting queue environment: {e}")
        return format_tool_error(
            e, context=f"getting environment {queue_environment_id} for queue {queue_id}"
        )


@tool
def get_fleet_details(farm_id: str, fleet_id: str) -> str:
    """
    Get detailed information about a specific Deadline Cloud fleet.

    Use list_queue_fleet_associations to get the fleet_id for a queue first.

    Args:
        farm_id: The ID of the farm
        fleet_id: The ID of the fleet

    Returns:
        String containing detailed fleet information or error message
    """

    try:
        client = get_deadline_client()
        response = client.get_fleet(farmId=farm_id, fleetId=fleet_id)

        result = f"**Fleet Details for {fleet_id}**\n\n"
        result += f"Display Name: {response.get('displayName', 'N/A')}\n"
        result += f"Status: {response.get('status', 'N/A')}\n"
        result += f"Farm ID: {response.get('farmId', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Created By: {response.get('createdBy', 'N/A')}\n"
        result += f"Updated: {response.get('updatedAt', 'N/A')}\n"

        # Worker configuration
        result += "\n**Worker Configuration:**\n"
        result += f"Min Workers: {response.get('minWorkerCount', 0)}\n"
        result += f"Max Workers: {response.get('maxWorkerCount', 0)}\n"
        result += f"Current Worker Count: {response.get('workerCount', 0)}\n"

        # Auto scaling
        if response.get("autoScalingStatus"):
            auto_scaling = response["autoScalingStatus"]
            result += "\n**Auto Scaling:**\n"
            result += f"Status: {auto_scaling.get('status', 'N/A')}\n"
            if auto_scaling.get("statusMessage"):
                result += f"Message: {auto_scaling['statusMessage']}\n"

        # Configuration
        if response.get("configuration"):
            config = response["configuration"]
            result += "\n**Configuration:**\n"

            if "customerManaged" in config:
                result += "Type: Customer Managed\n"
                cm = config["customerManaged"]
                result += f"Mode: {cm.get('mode', 'N/A')}\n"
                if cm.get("workerCapabilities"):
                    result += f"Worker Capabilities: {cm['workerCapabilities']}\n"
            elif "serviceManagedEc2" in config:
                result += "Type: Service Managed EC2\n"
                sm = config["serviceManagedEc2"]
                instance_caps = sm.get("instanceCapabilities", {})
                if isinstance(instance_caps, dict):
                    result += f"Instance Type: {instance_caps.get('instanceType', 'N/A')}\n"
                else:
                    result += f"Instance Capabilities: {instance_caps}\n"

        # Role ARN
        if response.get("roleArn"):
            result += f"\nFleet Role ARN: {response['roleArn']}\n"

        # Description
        if response.get("description"):
            result += f"\nDescription: {response['description']}\n"

        return result

    except Exception as e:
        logger.error(f"Error getting fleet details: {e}")
        return format_tool_error(e, context=f"getting details for fleet {fleet_id}")


@tool
def list_queue_fleet_associations(
    farm_id: str, queue_id: str = None, fleet_id: str = None, max_results: int = 20
) -> str:
    """
    List queue-fleet associations. Can filter by queue ID or fleet ID.

    Args:
        farm_id: The ID of the farm
        queue_id: Optional queue ID to filter associations for a specific queue
        fleet_id: Optional fleet ID to filter associations for a specific fleet
        max_results: Maximum number of associations to return (default: 20)

    Returns:
        String containing queue-fleet association information or error message
    """

    try:
        client = get_deadline_client()

        params = {"farmId": farm_id, "maxResults": min(max_results, 100)}

        if queue_id:
            params["queueId"] = queue_id
        if fleet_id:
            params["fleetId"] = fleet_id

        response = client.list_queue_fleet_associations(**params)

        associations = response.get("queueFleetAssociations", [])
        if not associations:
            filter_msg = ""
            if queue_id:
                filter_msg = f" for queue {queue_id}"
            elif fleet_id:
                filter_msg = f" for fleet {fleet_id}"
            return f"No queue-fleet associations found in farm {farm_id}{filter_msg}."

        result = f"Found {len(associations)} queue-fleet association(s):\n\n"
        for assoc in associations:
            result += f"- **Queue {assoc['queueId']}** ↔ **Fleet {assoc['fleetId']}**\n"
            result += f"  Status: {assoc.get('status', 'N/A')}\n"
            result += f"  Created: {assoc.get('createdAt', 'N/A')}\n"
            result += f"  Created By: {assoc.get('createdBy', 'N/A')}\n"
            result += f"  Updated: {assoc.get('updatedAt', 'N/A')}\n"

            if assoc.get("updatedBy"):
                result += f"  Updated By: {assoc['updatedBy']}\n"

            result += "\n"

        return result

    except Exception as e:
        logger.error(f"Error listing queue-fleet associations: {e}")
        return format_tool_error(e, context=f"listing queue-fleet associations in farm {farm_id}")


@tool
def get_queue_fleet_association_details(farm_id: str, queue_id: str, fleet_id: str) -> str:
    """
    Get detailed information about a specific queue-fleet association.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        fleet_id: The ID of the fleet

    Returns:
        String containing detailed queue-fleet association information or error message
    """

    try:
        client = get_deadline_client()
        response = client.get_queue_fleet_association(
            farmId=farm_id, queueId=queue_id, fleetId=fleet_id
        )

        result = "**Queue-Fleet Association Details**\n\n"
        result += f"Queue ID: {response.get('queueId', 'N/A')}\n"
        result += f"Fleet ID: {response.get('fleetId', 'N/A')}\n"
        result += f"Status: {response.get('status', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Created By: {response.get('createdBy', 'N/A')}\n"
        result += f"Updated: {response.get('updatedAt', 'N/A')}\n"

        if response.get("updatedBy"):
            result += f"Updated By: {response['updatedBy']}\n"

        return result

    except Exception as e:
        logger.error(f"Error getting queue-fleet association details: {e}")
        return format_tool_error(
            e,
            context=f"getting queue-fleet association details for queue {queue_id} and fleet {fleet_id}",
        )


@tool
def list_deadline_jobs(farm_id: str, queue_id: str, max_results: int = 20) -> str:
    """
    Search for jobs in a specific Deadline Cloud queue using the SearchJobs API.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        max_results: Maximum number of jobs to return (default: 20)

    Returns:
        String containing job information or error message
    """

    try:
        client = get_deadline_client()

        # Build search parameters
        search_params = {
            "farmId": farm_id,
            "queueIds": [queue_id],
            "itemOffset": 0,
            "pageSize": min(max_results, 100),
        }

        response = client.search_jobs(**search_params)

        jobs = response.get("jobs", [])
        total_results = response.get("totalResults", 0)

        if not jobs:
            return f"No jobs found in queue {queue_id}."

        result = f"Found {len(jobs)} of {total_results} job(s) in queue {queue_id}:\n\n"

        for job in jobs:
            result += f"- **{job.get('name', 'N/A')}** (ID: {job['jobId']})\n"
            result += f"  Status: {job.get('lifecycleStatus', 'N/A')}\n"
            result += f"  Priority: {job.get('priority', 'N/A')}\n"
            result += f"  Created: {job.get('createdAt', 'N/A')}\n"
            result += f"  Created By: {job.get('createdBy', 'N/A')}\n"
            if job.get("lifecycleStatusMessage"):
                result += f"  Message: {job['lifecycleStatusMessage']}\n"
            if job.get("startedAt"):
                result += f"  Started: {job['startedAt']}\n"
            if job.get("endedAt"):
                result += f"  Ended: {job['endedAt']}\n"
            result += "\n"

        return result

    except Exception as e:
        logger.error(f"Error searching jobs: {e}")
        return format_tool_error(e, context=f"searching jobs in queue {queue_id}")


@tool
def get_deadline_job_details(farm_id: str, queue_id: str, job_id: str) -> str:
    """
    Get detailed information about a specific Deadline Cloud job.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job

    Returns:
        String containing detailed job information or error message
    """

    try:
        client = get_deadline_client()
        response = client.get_job(farmId=farm_id, queueId=queue_id, jobId=job_id)

        result = f"**Job Details for {job_id}**\n\n"
        result += f"Name: {response.get('name', 'N/A')}\n"
        result += f"Lifecycle Status: {response.get('lifecycleStatus', 'N/A')}\n"
        result += f"Priority: {response.get('priority', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Started: {response.get('startedAt', 'N/A')}\n"
        result += f"Ended: {response.get('endedAt', 'N/A')}\n"

        # CRITICAL: Include task execution status
        if response.get("taskRunStatus"):
            result += f"\n**Task Execution Status: {response['taskRunStatus']}**\n"

        if response.get("taskRunStatusCounts"):
            result += "\n**Task Status Counts:**\n"
            counts = response["taskRunStatusCounts"]
            for status, count in counts.items():
                result += f"- {status}: {count}\n"

            # Highlight if there are failed tasks
            if counts.get("FAILED", 0) > 0:
                result += f"\n⚠️  **WARNING: {counts['FAILED']} task(s) FAILED**\n"

        if response.get("lifecycleStatusMessage"):
            result += f"\n**Lifecycle Status Message:**\n{response['lifecycleStatusMessage']}\n"

        if response.get("parameters"):
            result += "\n**Parameters:**\n"
            for key, value in response["parameters"].items():
                result += f"- {key}: {value}\n"

        # Add note about lifecycle vs task status
        result += "\n💡 **Note**: Lifecycle Status indicates job creation status. "
        result += "Task Execution Status indicates whether tasks succeeded or failed.\n"

        return result

    except Exception as e:
        logger.error(f"Error getting job details: {e}")
        return format_tool_error(e, context=f"getting details for job {job_id}")


@tool(context=True)
def list_deadline_steps(
    farm_id: str, queue_id: str, job_id: str, max_results: int = 20, tool_context=None
) -> str:
    """
    Search for steps in a specific Deadline Cloud job using the SearchSteps API.

    This tool automatically tracks discovered step IDs in agent state for use by other tools.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        max_results: Maximum number of steps to return (default: 20)

    Returns:
        String containing step information or error message
    """
    from strands import ToolContext

    try:
        client = get_deadline_client()

        # Build search parameters
        search_params = {
            "farmId": farm_id,
            "queueIds": [queue_id],
            "jobId": job_id,
            "itemOffset": 0,
            "pageSize": min(max_results, 100),
        }

        response = client.search_steps(**search_params)

        steps = response.get("steps", [])
        total_results = response.get("totalResults", 0)

        if not steps:
            return f"No steps found for job {job_id}."

        # Track discovered step IDs in agent state
        if tool_context and isinstance(tool_context, ToolContext):
            discovered_steps = tool_context.agent.state.get("discovered_steps") or []
            for step in steps:
                step_id = step["stepId"]
                if step_id not in discovered_steps:
                    discovered_steps.append(step_id)
            tool_context.agent.state.set("discovered_steps", discovered_steps)
            logger.info(f"Tracked {len(steps)} step IDs in agent state")

        result = f"Found {len(steps)} of {total_results} step(s) for job {job_id}:\n\n"

        for step in steps:
            result += f"- **{step.get('name', 'N/A')}** (ID: {step['stepId']})\n"
            result += f"  Status: {step.get('lifecycleStatus', 'N/A')}\n"
            result += f"  Task Run Status: {step.get('taskRunStatus', 'N/A')}\n"
            result += f"  Created: {step.get('createdAt', 'N/A')}\n"

            # Task counts
            task_counts = step.get("taskRunStatusCounts", {})
            if task_counts:
                result += "  Tasks: "
                counts = []
                for status, count in task_counts.items():
                    counts.append(f"{status}={count}")
                result += ", ".join(counts) + "\n"

            if step.get("startedAt"):
                result += f"  Started: {step['startedAt']}\n"
            if step.get("endedAt"):
                result += f"  Ended: {step['endedAt']}\n"
            if step.get("lifecycleStatusMessage"):
                result += f"  Message: {step['lifecycleStatusMessage']}\n"
            result += "\n"

        return result

    except Exception as e:
        logger.error(f"Error searching steps: {e}")
        return format_tool_error(e, context=f"searching steps in job {job_id}")


@tool
def get_deadline_step_details(farm_id: str, queue_id: str, job_id: str, step_id: str) -> str:
    """
    Get detailed information about a specific Deadline Cloud step.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        step_id: The ID of the step

    Returns:
        String containing detailed step information or error message
    """

    try:
        client = get_deadline_client()
        response = client.get_step(farmId=farm_id, queueId=queue_id, jobId=job_id, stepId=step_id)

        result = f"**Step Details for {step_id}**\n\n"
        result += f"Name: {response.get('name', 'N/A')}\n"
        result += f"Status: {response.get('lifecycleStatus', 'N/A')}\n"
        result += f"Task Run Status: {response.get('taskRunStatus', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Started: {response.get('startedAt', 'N/A')}\n"
        result += f"Ended: {response.get('endedAt', 'N/A')}\n"

        # Task counts
        task_counts = response.get("taskRunStatusCounts", {})
        if task_counts:
            result += "\n**Task Status Counts:**\n"
            for status, count in task_counts.items():
                result += f"- {status}: {count}\n"

        # Dependency counts
        dep_counts = response.get("dependencyCounts", {})
        if dep_counts:
            result += "\n**Dependency Counts:**\n"
            for key, count in dep_counts.items():
                result += f"- {key}: {count}\n"

        if response.get("lifecycleStatusMessage"):
            result += f"\n**Status Message:**\n{response['lifecycleStatusMessage']}\n"

        return result

    except Exception as e:
        logger.error(f"Error getting step details: {e}")
        return format_tool_error(e, context=f"getting details for step {step_id}")


@tool(context=True)
def list_deadline_tasks(
    farm_id: str,
    queue_id: str,
    job_id: str,
    step_id: str,
    status_filter: str = None,
    max_results: int = 20,
    tool_context=None,
) -> str:
    """
    Search for tasks in a specific Deadline Cloud step using the SearchTasks API.

    This tool automatically tracks discovered task IDs in agent state for use by other tools.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        step_id: The ID of the step
        status_filter: Optional filter by task run status. Valid values:
            - PENDING: Task is waiting to run
            - READY: Task is ready to run
            - ASSIGNED: Task has been assigned to a worker
            - STARTING: Task is starting
            - SCHEDULED: Task is scheduled
            - INTERRUPTING: Task is being interrupted
            - RUNNING: Task is currently running
            - SUSPENDED: Task is suspended
            - CANCELED: Task was canceled
            - FAILED: Task failed (use this to find failed tasks)
            - SUCCEEDED: Task completed successfully
            - NOT_COMPATIBLE: Task is not compatible with available workers
        max_results: Maximum number of tasks to return (default: 20)

    Returns:
        String containing task information or error message
    """
    from strands import ToolContext

    # Validate status_filter if provided
    valid_statuses = [
        "PENDING",
        "READY",
        "ASSIGNED",
        "STARTING",
        "SCHEDULED",
        "INTERRUPTING",
        "RUNNING",
        "SUSPENDED",
        "CANCELED",
        "FAILED",
        "SUCCEEDED",
        "NOT_COMPATIBLE",
    ]

    if status_filter and status_filter not in valid_statuses:
        return format_tool_error(
            Exception(
                f"Invalid status_filter: {status_filter}\n\n"
                f"Valid task run statuses:\n" + "\n".join(f"- {s}" for s in valid_statuses)
            ),
            context="listing tasks with invalid status filter",
        )

    try:
        client = get_deadline_client()

        # Build search parameters
        search_params = {
            "farmId": farm_id,
            "queueIds": [queue_id],
            "jobId": job_id,
            "itemOffset": 0,
            "pageSize": min(max_results, 100),
        }

        # Add status filter if provided
        # AWS Deadline Cloud filterExpressions uses typed filters (stringFilter, dateTimeFilter, etc.)
        if status_filter:
            search_params["filterExpressions"] = {
                "filters": [
                    {
                        "stringFilter": {
                            "name": "RUN_STATUS",
                            "operator": "EQUAL",
                            "value": status_filter,
                        }
                    }
                ],
                "operator": "OR",
            }

        response = client.search_tasks(**search_params)

        tasks = response.get("tasks", [])
        total_results = response.get("totalResults", 0)

        # Build descriptive message
        filter_desc = f" with status {status_filter}" if status_filter else ""

        if not tasks:
            return f"No tasks found for step {step_id}{filter_desc}."

        # Track discovered task IDs in agent state
        if tool_context and isinstance(tool_context, ToolContext):
            discovered_tasks = tool_context.agent.state.get("discovered_tasks") or []
            for task in tasks:
                task_id = task["taskId"]
                if task_id not in discovered_tasks:
                    discovered_tasks.append(task_id)
            tool_context.agent.state.set("discovered_tasks", discovered_tasks)
            logger.info(f"Tracked {len(tasks)} task IDs in agent state")

        result = (
            f"Found {len(tasks)} of {total_results} task(s) for step {step_id}{filter_desc}:\n\n"
        )

        for task in tasks:
            result += f"- **Task {task['taskId']}**\n"
            result += f"  Status: {task.get('runStatus', 'N/A')}\n"
            result += f"  Created: {task.get('createdAt', 'N/A')}\n"
            result += f"  Started: {task.get('startedAt', 'N/A')}\n"
            result += f"  Ended: {task.get('endedAt', 'N/A')}\n"

            if task.get("failureRetryCount"):
                result += f"  Retry Count: {task['failureRetryCount']}\n"

            if task.get("latestSessionActionId"):
                result += f"  Latest Session Action: {task['latestSessionActionId']}\n"

            result += "\n"

        return result

    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        return format_tool_error(e, context=f"listing tasks in step {step_id}")


@tool(context=True)
def get_deadline_task_details(
    farm_id: str, queue_id: str, job_id: str, step_id: str, task_id: str, tool_context=None
) -> str:
    """
    Get detailed information about a specific Deadline Cloud task.

    CRITICAL: This function requires both a STEP ID and a TASK ID.
    - Step IDs start with 'step-' (e.g., step-a1b2c3d4e5f6789012345678901234ab)
    - Task IDs start with 'task-' (e.g., task-5c1014dc9d7a4602874695e53210c21d-1)

    To get the correct IDs:
    1. Call list_deadline_steps to get step IDs
    2. Call list_deadline_tasks with the step_id to get task IDs

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        step_id: The ID of the step (format: step-[32 hex chars])
        task_id: The ID of the task (format: task-[32 hex chars]-[number])

    Returns:
        String containing detailed task information or error message
    """
    from strands import ToolContext

    # Validate step_id format
    is_valid, error_msg = validate_deadline_id(step_id, "step")
    if not is_valid:
        return format_tool_error(Exception(error_msg), context="getting task details")

    # Validate task_id format
    is_valid, error_msg = validate_deadline_id(task_id, "task")
    if not is_valid:
        return format_tool_error(Exception(error_msg), context="getting task details")

    # Check if step_id was discovered by list_deadline_steps
    if tool_context and isinstance(tool_context, ToolContext):
        discovered_steps = tool_context.agent.state.get("discovered_steps") or []
        if discovered_steps and step_id not in discovered_steps:
            return format_tool_error(
                Exception(
                    f"Step ID {step_id} was not found in discovered steps.\n\n"
                    f"**Available step IDs:**\n"
                    + "\n".join(f"- {sid}" for sid in discovered_steps)
                    + "\n\n"
                    "**You must use one of the step IDs from list_deadline_steps.**\n"
                    "If you need to find steps, call list_deadline_steps first."
                ),
                context="getting task details - step not in discovered list",
            )

        # Check if task_id was discovered by list_deadline_tasks
        discovered_tasks = tool_context.agent.state.get("discovered_tasks") or []
        if discovered_tasks and task_id not in discovered_tasks:
            return format_tool_error(
                Exception(
                    f"Task ID {task_id} was not found in discovered tasks.\n\n"
                    f"**Available task IDs:**\n"
                    + "\n".join(f"- {tid}" for tid in discovered_tasks[:10])
                    + (
                        f"\n... and {len(discovered_tasks) - 10} more"
                        if len(discovered_tasks) > 10
                        else ""
                    )
                    + "\n\n"
                    "**You must use one of the task IDs from list_deadline_tasks.**\n"
                    "If you need to find tasks, call list_deadline_tasks first."
                ),
                context="getting task details - task not in discovered list",
            )

    try:
        client = get_deadline_client()
        response = client.get_task(
            farmId=farm_id, queueId=queue_id, jobId=job_id, stepId=step_id, taskId=task_id
        )

        result = f"**Task Details for {task_id}**\n\n"
        result += f"Status: {response.get('runStatus', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Started: {response.get('startedAt', 'N/A')}\n"
        result += f"Ended: {response.get('endedAt', 'N/A')}\n"

        if response.get("failureRetryCount"):
            result += f"Failure Retry Count: {response['failureRetryCount']}\n"

        if response.get("latestSessionActionId"):
            result += f"Latest Session Action ID: {response['latestSessionActionId']}\n"

        if response.get("parameters"):
            result += "\n**Parameters:**\n"
            for key, value in response["parameters"].items():
                result += f"- {key}: {value}\n"

        return result

    except Exception as e:
        logger.error(f"Error getting task details: {e}")
        return format_tool_error(e, context=f"getting details for task {task_id}")


@tool(context=True)
def list_deadline_sessions(
    farm_id: str, queue_id: str, job_id: str, max_results: int = 20, tool_context=None
) -> str:
    """
    List sessions for a specific Deadline Cloud job.

    This tool automatically tracks discovered session IDs in agent state for use by other tools.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        max_results: Maximum number of sessions to return (default: 20)

    Returns:
        String containing session information or error message
    """
    from strands import ToolContext

    try:
        client = get_deadline_client()
        response = client.list_sessions(
            farmId=farm_id, queueId=queue_id, jobId=job_id, maxResults=min(max_results, 100)
        )

        sessions = response.get("sessions", [])
        if not sessions:
            return f"No sessions found for job {job_id}."

        # Track discovered session IDs in agent state
        if tool_context and isinstance(tool_context, ToolContext):
            discovered_sessions = tool_context.agent.state.get("discovered_sessions") or []
            for session in sessions:
                session_id = session["sessionId"]
                if session_id not in discovered_sessions:
                    discovered_sessions.append(session_id)
            tool_context.agent.state.set("discovered_sessions", discovered_sessions)
            logger.info(f"Tracked {len(sessions)} session IDs in agent state")

        result = f"Found {len(sessions)} session(s) for job {job_id}:\n\n"
        for session in sessions:
            result += f"- **Session {session['sessionId']}**\n"
            result += f"  Status: {session.get('lifecycleStatus', 'N/A')}\n"
            result += f"  Fleet ID: {session.get('fleetId', 'N/A')}\n"
            result += f"  Worker ID: {session.get('workerId', 'N/A')}\n"
            result += f"  Started: {session.get('startedAt', 'N/A')}\n"
            result += f"  Ended: {session.get('endedAt', 'N/A')}\n"

            if session.get("targetLifecycleStatus"):
                result += f"  Target Status: {session['targetLifecycleStatus']}\n"

            result += "\n"

        return result

    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        return format_tool_error(e, context=f"listing sessions for job {job_id}")


@tool
def get_deadline_session_details(farm_id: str, queue_id: str, job_id: str, session_id: str) -> str:
    """
    Get detailed information about a specific Deadline Cloud session.

    This includes worker information and log configuration that can be used to:
    - Get worker logs using the logGroupName and logStreamName
    - Get worker metadata using the workerId

    CRITICAL: This function requires a SESSION ID, not a TASK ID!
    - Session IDs start with 'session-' (e.g., session-c45e67929df54960a558170de8cb02a8)
    - Task IDs start with 'task-' (e.g., task-5c1014dc9d7a4602874695e53210c21d)
    - DO NOT try to convert a task ID to a session ID by replacing the prefix!

    To get the correct session ID:
    1. Call list_deadline_sessions for the job, OR
    2. Get the sessionId from session action details, OR
    3. Use list_deadline_session_actions with task_id parameter to find the session for a task

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        session_id: The ID of the session (must match format: session-[0-9a-f]{32})

    Returns:
        String containing detailed session information or error message
    """

    # Check for common hallucinated session ID pattern
    if session_id == "session-00000000000000000000000000000000" or session_id.endswith("0" * 32):
        return format_tool_error(
            Exception(
                "Invalid session ID detected: This appears to be a placeholder or hallucinated session ID.\n\n"
                "**CRITICAL ERROR**: You MUST get real session IDs from the API.\n\n"
                "To get valid session IDs:\n"
                "1. Call list_deadline_sessions(farm_id, queue_id, job_id) first\n"
                "2. Extract the sessionId values from the response\n"
                "3. Use those real session IDs in this function\n\n"
                "**DO NOT make up or guess session IDs**. They must come from the API."
            ),
            context="getting session details - invalid session ID",
        )

    # Validate session_id format
    is_valid, error_msg = validate_deadline_id(session_id, "session")
    if not is_valid:
        return format_tool_error(Exception(error_msg), context="getting session details")

    try:
        client = get_deadline_client()
        response = client.get_session(
            farmId=farm_id, queueId=queue_id, jobId=job_id, sessionId=session_id
        )

        result = f"**Session Details for {session_id}**\n\n"
        result += f"Status: {response.get('lifecycleStatus', 'N/A')}\n"
        result += f"Fleet ID: {response.get('fleetId', 'N/A')}\n"
        result += f"Worker ID: {response.get('workerId', 'N/A')}\n"
        result += f"Started: {response.get('startedAt', 'N/A')}\n"
        result += f"Ended: {response.get('endedAt', 'N/A')}\n"
        result += f"Target Status: {response.get('targetLifecycleStatus', 'N/A')}\n"

        if response.get("hostProperties"):
            result += "\n**Host Properties:**\n"
            host = response["hostProperties"]
            ip_addresses = host.get("ipAddresses", {})
            if isinstance(ip_addresses, dict):
                ipv4_list = ip_addresses.get("ipV4Addresses", ["N/A"])
                result += f"- IP Address: {ipv4_list[0] if ipv4_list else 'N/A'}\n"
            else:
                result += f"- IP Addresses: {ip_addresses}\n"
            result += f"- Host Name: {host.get('hostName', 'N/A')}\n"
            result += f"- EC2 Instance ARN: {host.get('ec2InstanceArn', 'N/A')}\n"

        if response.get("log"):
            result += "\n**Log Configuration:**\n"
            log = response["log"]
            result += f"- Log Driver: {log.get('logDriver', 'N/A')}\n"
            if log.get("options"):
                result += f"- Options: {log['options']}\n"

            # Extract worker log information if available
            if log.get("logDriver") == "awslogs":
                options = log.get("options", {})
                log_group = options.get("awslogs-group", "N/A")
                log_stream = options.get("awslogs-stream", "N/A")

                result += "\n**Worker Log Location:**\n"
                result += f"- Log Group: {log_group}\n"
                result += f"- Log Stream: {log_stream}\n"
                result += "\n💡 Use get_worker_cloudwatch_logs to fetch worker logs for detailed troubleshooting.\n"

        # Add note about getting worker metadata
        if response.get("workerId") and response.get("fleetId"):
            result += (
                "\n💡 Use get_deadline_worker_details to get worker metadata and configuration.\n"
            )

        return result

    except Exception as e:
        logger.error(f"Error getting session details: {e}")
        return format_tool_error(e, context=f"getting details for session {session_id}")


@tool(context=True)
def list_deadline_session_actions(
    farm_id: str,
    queue_id: str,
    job_id: str,
    session_id: str,
    task_id: str = None,
    max_results: int = 20,
    tool_context=None,
) -> str:
    """
    List session actions for a specific Deadline Cloud session.

    IMPORTANT: session_id is REQUIRED. The AWS Deadline API requires a session ID to list session actions.
    You can optionally filter by task_id to see only actions related to a specific task.

    To get a session ID:
    1. Call list_deadline_sessions for the job, OR
    2. Call get_deadline_task_details and look for latestSessionActionId, then use get_deadline_session_action_details to get the sessionId

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        session_id: REQUIRED - The session ID (format: session-[32 hex chars])
        task_id: Optional task ID to filter session actions for a specific task
        max_results: Maximum number of session actions to return (default: 20)

    Returns:
        String containing session action information or error message
    """

    # Check for common hallucinated session ID pattern
    if session_id == "session-00000000000000000000000000000000" or session_id.endswith("0" * 32):
        return format_tool_error(
            Exception(
                "Invalid session ID detected: This appears to be a placeholder or hallucinated session ID.\n\n"
                "**CRITICAL ERROR**: You MUST get real session IDs from the API.\n\n"
                "To get valid session IDs:\n"
                "1. Call list_deadline_sessions(farm_id, queue_id, job_id) first\n"
                "2. Extract the sessionId values from the response\n"
                "3. Use those real session IDs in this function\n\n"
                "**DO NOT make up or guess session IDs**. They must come from the API."
            ),
            context="listing session actions - invalid session ID",
        )

    # Validate session_id format (required)
    is_valid, error_msg = validate_deadline_id(session_id, "session")
    if not is_valid:
        return format_tool_error(Exception(error_msg), context="listing session actions")

    # Check if session_id was discovered by list_deadline_sessions
    if tool_context and isinstance(tool_context, ToolContext):
        discovered_sessions = tool_context.agent.state.get("discovered_sessions") or []
        if discovered_sessions and session_id not in discovered_sessions:
            return format_tool_error(
                Exception(
                    f"Session ID {session_id} was not found in discovered sessions.\n\n"
                    f"**Available session IDs:**\n"
                    + "\n".join(f"- {sid}" for sid in discovered_sessions)
                    + "\n\n"
                    "**You must use one of the session IDs from list_deadline_sessions.**\n"
                    "If you need to find sessions, call list_deadline_sessions first."
                ),
                context="listing session actions - session not in discovered list",
            )

    # Validate task_id format if provided
    if task_id:
        is_valid, error_msg = validate_deadline_id(task_id, "task")
        if not is_valid:
            return format_tool_error(Exception(error_msg), context="listing session actions")

    try:
        client = get_deadline_client()

        # session_id is required by the AWS API
        params = {
            "farmId": farm_id,
            "queueId": queue_id,
            "jobId": job_id,
            "sessionId": session_id,
            "maxResults": min(max_results, 100),
        }

        filter_desc = f"session {session_id}"

        # Add optional task_id filter if provided
        if task_id:
            params["taskId"] = task_id
            filter_desc += f" and task {task_id}"

        logger.info(f"Calling list_session_actions with params: {params}")
        response = client.list_session_actions(**params)

        actions = response.get("sessionActions", [])
        if not actions:
            return f"No session actions found for {filter_desc}."

        result = f"Found {len(actions)} session action(s) for {filter_desc}:\n\n"
        for action in actions:
            result += f"- **Session Action {action['sessionActionId']}**\n"
            result += f"  Status: {action.get('status', 'N/A')}\n"
            result += f"  Started: {action.get('startedAt', 'N/A')}\n"
            result += f"  Ended: {action.get('endedAt', 'N/A')}\n"

            if action.get("definition"):
                definition = action["definition"]
                if "envEnter" in definition:
                    result += "  Type: Environment Enter\n"
                    result += (
                        f"  Environment ID: {definition['envEnter'].get('environmentId', 'N/A')}\n"
                    )
                elif "envExit" in definition:
                    result += "  Type: Environment Exit\n"
                    result += (
                        f"  Environment ID: {definition['envExit'].get('environmentId', 'N/A')}\n"
                    )
                elif "taskRun" in definition:
                    result += "  Type: Task Run\n"
                    task_run = definition["taskRun"]
                    result += f"  Task ID: {task_run.get('taskId', 'N/A')}\n"
                    result += f"  Step ID: {task_run.get('stepId', 'N/A')}\n"
                elif "syncInputJobAttachments" in definition:
                    result += "  Type: Sync Input Job Attachments\n"

            if action.get("progressPercent"):
                result += f"  Progress: {action['progressPercent']}%\n"

            result += "\n"

        return result

    except Exception as e:
        logger.error(f"Error listing session actions: {e}")
        return format_tool_error(e, context=f"listing session actions for session {session_id}")


@tool
def get_deadline_worker_details(farm_id: str, fleet_id: str, worker_id: str) -> str:
    """
    Get detailed information about a specific Deadline Cloud worker.

    This provides worker metadata including:
    - Worker status and lifecycle
    - Host properties (IP, hostname, EC2 instance)
    - Worker capabilities and configuration

    Args:
        farm_id: The ID of the farm
        fleet_id: The ID of the fleet (from session details)
        worker_id: The ID of the worker (from session details)

    Returns:
        String containing detailed worker information or error message
    """

    try:
        client = get_deadline_client()
        response = client.get_worker(farmId=farm_id, fleetId=fleet_id, workerId=worker_id)

        result = f"**Worker Details for {worker_id}**\n\n"
        result += f"Status: {response.get('status', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Created By: {response.get('createdBy', 'N/A')}\n"
        result += f"Updated: {response.get('updatedAt', 'N/A')}\n"

        if response.get("hostProperties"):
            result += "\n**Host Properties:**\n"
            host = response["hostProperties"]

            if host.get("ipAddresses"):
                ip_addrs = host["ipAddresses"]
                if ip_addrs.get("ipV4Addresses"):
                    result += f"- IPv4 Addresses: {', '.join(ip_addrs['ipV4Addresses'])}\n"
                if ip_addrs.get("ipV6Addresses"):
                    result += f"- IPv6 Addresses: {', '.join(ip_addrs['ipV6Addresses'])}\n"

            result += f"- Host Name: {host.get('hostName', 'N/A')}\n"
            result += f"- EC2 Instance ARN: {host.get('ec2InstanceArn', 'N/A')}\n"
            result += f"- EC2 Instance Type: {host.get('ec2InstanceType', 'N/A')}\n"

        if response.get("log"):
            result += "\n**Log Configuration:**\n"
            log = response["log"]
            result += f"- Log Driver: {log.get('logDriver', 'N/A')}\n"
            if log.get("options"):
                options = log["options"]
                result += f"- Log Group: {options.get('awslogs-group', 'N/A')}\n"
                result += f"- Log Stream Prefix: {options.get('awslogs-stream-prefix', 'N/A')}\n"

        return result

    except Exception as e:
        error_msg = str(e)

        # Handle 404 - worker no longer exists (this is expected and OK)
        if (
            "ResourceNotFoundException" in error_msg
            or "404" in error_msg
            or "not found" in error_msg.lower()
        ):
            logger.info(f"Worker {worker_id} not found (likely terminated) - this is expected")
            return (
                f"ℹ️ Worker {worker_id} is no longer available (likely terminated).\n\n"
                f"This is normal behavior - workers are often terminated after completing their tasks.\n"
                f"You can still analyze the job using session logs and CloudWatch logs.\n\n"
                f"**Continue with your analysis using the available information.**"
            )

        # For other errors, use standard error handling
        logger.error(f"Error getting worker details: {e}")
        return format_tool_error(e, context=f"getting details for worker {worker_id}")


@tool
def get_deadline_session_action_details(
    farm_id: str, queue_id: str, job_id: str, session_action_id: str
) -> str:
    """
    Get detailed information about a specific Deadline Cloud session action.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        session_action_id: The ID of the session action

    Returns:
        String containing detailed session action information or error message
    """

    try:
        client = get_deadline_client()
        response = client.get_session_action(
            farmId=farm_id, queueId=queue_id, jobId=job_id, sessionActionId=session_action_id
        )

        result = f"**Session Action Details for {session_action_id}**\n\n"
        result += f"Session ID: {response.get('sessionId', 'N/A')}\n"
        result += f"Status: {response.get('status', 'N/A')}\n"
        result += f"Started: {response.get('startedAt', 'N/A')}\n"
        result += f"Ended: {response.get('endedAt', 'N/A')}\n"
        result += f"Progress: {response.get('progressPercent', 0)}%\n"

        if response.get("definition"):
            result += "\n**Definition:**\n"
            definition = response["definition"]

            if "envEnter" in definition:
                result += "Type: Environment Enter\n"
                env = definition["envEnter"]
                result += f"Environment ID: {env.get('environmentId', 'N/A')}\n"
            elif "envExit" in definition:
                result += "Type: Environment Exit\n"
                env = definition["envExit"]
                result += f"Environment ID: {env.get('environmentId', 'N/A')}\n"
            elif "taskRun" in definition:
                result += "Type: Task Run\n"
                task_run = definition["taskRun"]
                result += f"Task ID: {task_run.get('taskId', 'N/A')}\n"
                result += f"Step ID: {task_run.get('stepId', 'N/A')}\n"
                if task_run.get("parameters"):
                    result += f"Parameters: {task_run['parameters']}\n"
            elif "syncInputJobAttachments" in definition:
                result += "Type: Sync Input Job Attachments\n"
                sync = definition["syncInputJobAttachments"]
                result += f"Step ID: {sync.get('stepId', 'N/A')}\n"

        if response.get("progressMessage"):
            result += f"\n**Progress Message:**\n{response['progressMessage']}\n"

        return result

    except Exception as e:
        logger.error(f"Error getting session action details: {e}")
        return format_tool_error(
            e, context=f"getting details for session action {session_action_id}"
        )


def get_queue_role_credentials(farm_id: str, queue_id: str, config: Optional[ConfigParser] = None):
    """
    Get temporary credentials by assuming the queue role for read access.

    This is a helper function that can be used by other tools/agents that need
    to access AWS resources with queue role permissions (e.g., S3 job attachments bucket).

    Args:
        farm_id: The farm ID
        queue_id: The queue ID
        config: Optional configuration parser

    Returns:
        Dictionary with AWS credentials or None if failed
    """
    try:
        from deadline.client.api import get_boto3_client

        # Get Deadline client using the package's credential system
        deadline_client = get_boto3_client("deadline", config=config)

        logger.info(f"Assuming queue role for farm {farm_id}, queue {queue_id}")

        response = deadline_client.assume_queue_role_for_read(farmId=farm_id, queueId=queue_id)

        creds = response.get("credentials", {})
        logger.info("✅ Successfully assumed queue role")

        return {
            "access_key_id": creds.get("accessKeyId"),
            "secret_access_key": creds.get("secretAccessKey"),
            "session_token": creds.get("sessionToken"),
            "expiration": creds.get("expiration"),
        }

    except Exception as e:
        logger.error(f"Failed to assume queue role: {e}")
        return None


@tool
def get_queue_credentials(farm_id: str, queue_id: str) -> str:
    """
    Get temporary AWS credentials by assuming the queue role for read access.

    These credentials can be used to access AWS resources that the queue role has
    permissions for, such as:
    - S3 job attachments bucket
    - CloudWatch logs for the queue
    - Other queue-scoped AWS resources

    The credentials are temporary and will expire after a period of time.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue

    Returns:
        String containing credential information or error message
    """
    try:
        creds = get_queue_role_credentials(farm_id, queue_id)

        if not creds:
            return "❌ Failed to assume queue role. Check permissions and resource IDs."

        result = "**Queue Role Credentials**\n\n"
        result += f"Access Key ID: {creds['access_key_id'][:20]}...\n"
        result += f"Expiration: {creds['expiration']}\n\n"
        result += "✓ Credentials obtained successfully\n\n"
        result += "These credentials can be used to:\n"
        result += "- Access the job attachments S3 bucket\n"
        result += "- Read CloudWatch logs for this queue\n"
        result += "- Access other queue-scoped AWS resources\n\n"
        result += "💡 Use these credentials when accessing S3 or other AWS services on behalf of the queue.\n"

        return result

    except Exception as e:
        logger.error(f"Error getting queue credentials: {e}")
        return format_tool_error(e, context=f"getting queue credentials for queue {queue_id}")


@tool
def copy_job_template(
    farm_id: str,
    queue_id: str,
    job_id: str,
    s3_bucket: str,
    s3_key_prefix: str = "deadline-job-templates/",
    validate_template: bool = True,
) -> str:
    """
    Copy a job template to an S3 bucket for review and diagnosis.

    This tool exports the job template JSON to S3, allowing you to:
    - Review the complete job configuration
    - Diagnose rendering errors by examining template structure
    - Identify misconfigurations in job parameters
    - Validate the template using openjd-cli (if available)

    The template will be written to: s3://{bucket}/{prefix}{job_id}.json

    After reviewing, you can delete the object using standard S3 tools if permissions allow.

    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        s3_bucket: The S3 bucket name to write the template to
        s3_key_prefix: Optional S3 key prefix (default: "deadline-job-templates/")
        validate_template: Whether to validate the template using openjd-cli (default: True)

    Returns:
        String containing the S3 location, validation results, and summary of the template, or error message
    """
    import json
    import tempfile
    import subprocess
    import shutil
    from pathlib import Path

    try:
        # Get the job details first to retrieve the template
        deadline_client = get_deadline_client()
        job_response = deadline_client.get_job(farmId=farm_id, queueId=queue_id, jobId=job_id)

        # Extract the job template
        # The template is typically in the job parameters or attachments
        template_data = {
            "jobId": job_id,
            "name": job_response.get("name"),
            "lifecycleStatus": job_response.get("lifecycleStatus"),
            "priority": job_response.get("priority"),
            "parameters": job_response.get("parameters", {}),
            "attachments": job_response.get("attachments", {}),
            "description": job_response.get("description"),
            "createdAt": str(job_response.get("createdAt")),
            "createdBy": job_response.get("createdBy"),
        }

        # Convert to JSON
        template_json = json.dumps(template_data, indent=2, default=str)

        # Write to S3 using the same session as deadline client
        from deadline.client.api import get_boto3_session

        session = get_boto3_session()
        s3_client = session.client("s3")
        s3_key = f"{s3_key_prefix}{job_id}.json"

        s3_client.put_object(
            Bucket=s3_bucket,
            Key=s3_key,
            Body=template_json.encode("utf-8"),
            ContentType="application/json",
        )

        s3_location = f"s3://{s3_bucket}/{s3_key}"

        result = "**Job Template Exported Successfully**\n\n"
        result += f"Location: {s3_location}\n"
        result += f"Job Name: {template_data.get('name', 'N/A')}\n"
        result += f"Status: {template_data.get('lifecycleStatus', 'N/A')}\n"
        result += f"Priority: {template_data.get('priority', 'N/A')}\n\n"

        # Validate template using openjd-cli if requested
        validation_result = None
        if validate_template:
            # Check if openjd is available
            openjd_available = shutil.which("openjd") is not None

            if openjd_available:
                # Create a temporary directory for validation
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    template_file = temp_path / "template.json"

                    # Write template to temporary file
                    template_file.write_text(template_json)

                    try:
                        # Run openjd check command
                        validation_process = subprocess.run(
                            ["openjd", "check", str(template_file)],
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )

                        validation_result = {
                            "success": validation_process.returncode == 0,
                            "stdout": validation_process.stdout,
                            "stderr": validation_process.stderr,
                            "returncode": validation_process.returncode,
                        }

                    except subprocess.TimeoutExpired:
                        validation_result = {
                            "success": False,
                            "error": "Validation timed out after 30 seconds",
                        }
                    except Exception as e:
                        validation_result = {
                            "success": False,
                            "error": f"Validation error: {str(e)}",
                        }
            else:
                validation_result = {
                    "success": False,
                    "error": "openjd-cli not found. Install from: https://github.com/OpenJobDescription/openjd-cli",
                }

        # Add validation results to output
        if validation_result:
            result += "\n**Validation Results:**\n"
            if validation_result.get("success"):
                result += "✅ Template is VALID\n"
                if validation_result.get("stdout"):
                    result += f"```\n{validation_result['stdout']}\n```\n"
            else:
                if validation_result.get("error"):
                    result += f"⚠️  {validation_result['error']}\n"
                else:
                    result += "❌ Template VALIDATION FAILED\n"
                    if validation_result.get("stderr"):
                        result += f"```\n{validation_result['stderr']}\n```\n"

        # Provide summary of parameters
        params = template_data.get("parameters", {})
        if params:
            result += f"\n**Parameters ({len(params)} total):**\n"
            for key in list(params.keys())[:5]:  # Show first 5
                result += f"- {key}\n"
            if len(params) > 5:
                result += f"- ... and {len(params) - 5} more\n"

        result += f"\n💡 Review the template at {s3_location}\n"
        result += f"💡 To validate separately, use: validate_job_template(s3_bucket='{s3_bucket}', s3_key='{s3_key}')\n"
        result += f"💡 To delete after review: aws s3 rm {s3_location}\n"

        return result

    except Exception as e:
        logger.error(f"Error copying job template: {e}")
        return format_tool_error(e, context=f"copying job template for job {job_id} to S3")


@tool
def validate_job_template(s3_bucket: str, s3_key: str) -> str:
    """
    Validate a job template from S3 using openjd-cli.

    This tool:
    1. Downloads the template from S3
    2. Validates it using 'openjd check' command
    3. Reports any validation errors or confirms the template is valid

    Requires openjd-cli to be installed: pip install openjd-cli
    See: https://github.com/OpenJobDescription/openjd-cli

    Args:
        s3_bucket: The S3 bucket containing the template
        s3_key: The S3 key (path) to the template file

    Returns:
        String containing validation results or error message
    """
    import tempfile
    import subprocess
    import shutil
    from pathlib import Path

    try:
        # Check if openjd is available
        openjd_available = shutil.which("openjd") is not None

        if not openjd_available:
            return (
                "❌ openjd-cli is not installed or not in PATH.\n\n"
                "To install openjd-cli:\n"
                "```bash\n"
                "pip install openjd-cli\n"
                "```\n\n"
                "See: https://github.com/OpenJobDescription/openjd-cli\n"
            )

        # Download template from S3
        from deadline.client.api import get_boto3_session

        session = get_boto3_session()
        s3_client = session.client("s3")

        # Create temporary directory for validation
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            template_file = temp_path / "template.yaml"

            # Download from S3
            s3_client.download_file(s3_bucket, s3_key, str(template_file))

            result = "**Job Template Validation**\n\n"
            result += f"Template: s3://{s3_bucket}/{s3_key}\n\n"

            # Run openjd check
            try:
                validation_output = subprocess.run(
                    ["openjd", "check", str(template_file)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if validation_output.returncode == 0:
                    result += "✅ **Template is VALID**\n\n"
                    if validation_output.stdout:
                        result += f"Output:\n```\n{validation_output.stdout}\n```\n"
                else:
                    result += "❌ **Template VALIDATION FAILED**\n\n"
                    if validation_output.stderr:
                        result += f"Errors:\n```\n{validation_output.stderr}\n```\n"
                    if validation_output.stdout:
                        result += f"\nOutput:\n```\n{validation_output.stdout}\n```\n"

                    result += "\n**Common Issues:**\n"
                    result += "- Missing required fields in the template\n"
                    result += "- Invalid parameter types or values\n"
                    result += "- Malformed YAML/JSON structure\n"
                    result += "- Unsupported Open Job Description schema version\n"

            except subprocess.TimeoutExpired:
                result += "⚠️  Validation timed out after 30 seconds.\n"
            except Exception as validation_error:
                result += f"⚠️  Error running openjd check: {validation_error}\n"

            return result

    except Exception as e:
        logger.error(f"Error validating job template: {e}")
        return format_tool_error(e, context=f"validating template s3://{s3_bucket}/{s3_key}")


def get_deadline_tools():
    """
    Get all custom Deadline Cloud tools.

    Returns:
        List of Deadline Cloud tools
    """

    return [
        # Farm and Queue tools
        list_deadline_queues,
        get_queue_details,
        list_queue_environments,
        get_queue_environment,
        get_fleet_details,
        # Queue-Fleet Association tools
        list_queue_fleet_associations,
        get_queue_fleet_association_details,
        # Job tools
        list_deadline_jobs,
        get_deadline_job_details,
        copy_job_template,
        validate_job_template,
        # Step tools
        list_deadline_steps,
        get_deadline_step_details,
        # Task tools
        list_deadline_tasks,
        get_deadline_task_details,
        # Session tools
        list_deadline_sessions,
        get_deadline_session_details,
        # Session Action tools
        list_deadline_session_actions,
        get_deadline_session_action_details,
        # Worker tools
        get_deadline_worker_details,
        # Credentials tools
        get_queue_credentials,
    ]
