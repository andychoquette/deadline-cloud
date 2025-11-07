"""
Custom Deadline Cloud tools using the SDK directly.
Alternative to MCP server until mcp-server command is available.
"""
from strands import tool
import logging
from typing import Optional
from configparser import ConfigParser
import boto3
import os

# Import deadline package's credential management
from deadline.client.api import get_boto3_client

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Check if boto3 is available
DEADLINE_AVAILABLE = True
try:
    import boto3
except ImportError:
    DEADLINE_AVAILABLE = False


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
        'session': r'^session-[0-9a-f]{32}$',
        'task': r'^task-[0-9a-f]{32}$',
        'step': r'^step-[0-9a-f]{32}$',
        'job': r'^job-[0-9a-f]{32}$',
    }
    
    if id_type not in patterns:
        return True, ""  # Unknown type, skip validation
    
    pattern = patterns[id_type]
    if not re.match(pattern, id_value):
        example_ids = {
            'session': 'session-c45e67929df54960a558170de8cb02a8',
            'task': 'task-a1b2c3d4e5f6789012345678901234ab',
            'step': 'step-a1b2c3d4e5f6789012345678901234ab',
            'job': 'job-a1b2c3d4e5f6789012345678901234ab',
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
            error_msg += f"   - {wrong_type_detected.capitalize()} IDs start with '{wrong_type_detected}-'\n"
            error_msg += f"   - {id_type.capitalize()} IDs start with '{id_type}-'\n"
            error_msg += f"   - DO NOT try to convert between resource types by replacing the prefix!\n\n"
            
            if id_type == 'session' and wrong_type_detected == 'task':
                error_msg += "To get the session ID for a task:\n"
                error_msg += "1. Call list_deadline_sessions for the job, OR\n"
                error_msg += "2. Call list_deadline_session_actions with the task_id parameter\n"
                error_msg += "3. Extract the sessionId from the session action details\n\n"
        else:
            error_msg += f"{id_type.capitalize()} ID must match pattern '{id_type}-[32 hex characters]'.\n"
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
        params = {'farmId': farm_id, 'maxResults': 50}
        
        # Add principal ID if available (must be Deadline identity ID)
        principal_id = os.getenv('DEADLINE_PRINCIPAL_ID')
        if principal_id:
            params['principalId'] = principal_id
        
        response = client.list_queues(**params)
        
        queues = response.get('queues', [])
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
def list_deadline_fleets(farm_id: str, max_results: int = 20) -> str:
    """
    List all fleets in a specific Deadline Cloud farm.
    
    Args:
        farm_id: The ID of the farm to list fleets from
        max_results: Maximum number of fleets to return (default: 20)
        
    Returns:
        String containing fleet information or error message
    """
    
    try:
        client = get_deadline_client()
        
        # Build parameters
        params = {'farmId': farm_id, 'maxResults': min(max_results, 100)}
        
        # Add principal ID if available (must be Deadline identity ID)
        principal_id = os.getenv('DEADLINE_PRINCIPAL_ID')
        if principal_id:
            params['principalId'] = principal_id
        
        response = client.list_fleets(**params)
        
        fleets = response.get('fleets', [])
        if not fleets:
            return f"No fleets found in farm {farm_id}."
        
        result = f"Found {len(fleets)} fleet(s) in farm {farm_id}:\n\n"
        for fleet in fleets:
            result += f"- **{fleet['displayName']}** (ID: {fleet['fleetId']})\n"
            result += f"  Status: {fleet.get('status', 'N/A')}\n"
            result += f"  Min Workers: {fleet.get('minWorkerCount', 0)}\n"
            result += f"  Max Workers: {fleet.get('maxWorkerCount', 0)}\n"
            result += f"  Worker Count: {fleet.get('workerCount', 0)}\n"
            result += f"  Auto Scaling: {fleet.get('autoScalingStatus', {}).get('status', 'N/A')}\n\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error listing fleets: {e}")
        return format_tool_error(e, context=f"listing fleets in farm {farm_id}")


@tool
def list_queue_fleet_associations(farm_id: str, queue_id: str = None, fleet_id: str = None, max_results: int = 20) -> str:
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
        
        params = {
            'farmId': farm_id,
            'maxResults': min(max_results, 100)
        }
        
        if queue_id:
            params['queueId'] = queue_id
        if fleet_id:
            params['fleetId'] = fleet_id
        
        response = client.list_queue_fleet_associations(**params)
        
        associations = response.get('queueFleetAssociations', [])
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
            
            if assoc.get('updatedBy'):
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
            farmId=farm_id,
            queueId=queue_id,
            fleetId=fleet_id
        )
        
        result = f"**Queue-Fleet Association Details**\n\n"
        result += f"Queue ID: {response.get('queueId', 'N/A')}\n"
        result += f"Fleet ID: {response.get('fleetId', 'N/A')}\n"
        result += f"Status: {response.get('status', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Created By: {response.get('createdBy', 'N/A')}\n"
        result += f"Updated: {response.get('updatedAt', 'N/A')}\n"
        
        if response.get('updatedBy'):
            result += f"Updated By: {response['updatedBy']}\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error getting queue-fleet association details: {e}")
        return format_tool_error(e, context=f"getting queue-fleet association details for queue {queue_id} and fleet {fleet_id}")


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
            'farmId': farm_id,
            'queueIds': [queue_id],
            'itemOffset': 0,
            'pageSize': min(max_results, 100)
        }
        
        response = client.search_jobs(**search_params)
        
        jobs = response.get('jobs', [])
        total_results = response.get('totalResults', 0)
        
        if not jobs:
            return f"No jobs found in queue {queue_id}."
        
        result = f"Found {len(jobs)} of {total_results} job(s) in queue {queue_id}:\n\n"
        
        for job in jobs:
            job_data = job.get('jobParameters', {})
            result += f"- **{job.get('name', 'N/A')}** (ID: {job['jobId']})\n"
            result += f"  Status: {job.get('lifecycleStatus', 'N/A')}\n"
            result += f"  Priority: {job.get('priority', 'N/A')}\n"
            result += f"  Created: {job.get('createdAt', 'N/A')}\n"
            result += f"  Created By: {job.get('createdBy', 'N/A')}\n"
            if job.get('lifecycleStatusMessage'):
                result += f"  Message: {job['lifecycleStatusMessage']}\n"
            if job.get('startedAt'):
                result += f"  Started: {job['startedAt']}\n"
            if job.get('endedAt'):
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
        result += f"Status: {response.get('lifecycleStatus', 'N/A')}\n"
        result += f"Priority: {response.get('priority', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Started: {response.get('startedAt', 'N/A')}\n"
        result += f"Ended: {response.get('endedAt', 'N/A')}\n"
        
        if response.get('lifecycleStatusMessage'):
            result += f"\n**Status Message:**\n{response['lifecycleStatusMessage']}\n"
        
        if response.get('parameters'):
            result += f"\n**Parameters:**\n"
            for key, value in response['parameters'].items():
                result += f"- {key}: {value}\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error getting job details: {e}")
        return format_tool_error(e, context=f"getting details for job {job_id}")


@tool
def list_deadline_steps(farm_id: str, queue_id: str, job_id: str, max_results: int = 20) -> str:
    """
    Search for steps in a specific Deadline Cloud job using the SearchSteps API.
    
    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        max_results: Maximum number of steps to return (default: 20)
        
    Returns:
        String containing step information or error message
    """
    
    try:
        client = get_deadline_client()
        
        # Build search parameters
        search_params = {
            'farmId': farm_id,
            'queueIds': [queue_id],
            'jobId': job_id,
            'itemOffset': 0,
            'pageSize': min(max_results, 100)
        }
        
        response = client.search_steps(**search_params)
        
        steps = response.get('steps', [])
        total_results = response.get('totalResults', 0)
        
        if not steps:
            return f"No steps found for job {job_id}."
        
        result = f"Found {len(steps)} of {total_results} step(s) for job {job_id}:\n\n"
        
        for step in steps:
            result += f"- **{step.get('name', 'N/A')}** (ID: {step['stepId']})\n"
            result += f"  Status: {step.get('lifecycleStatus', 'N/A')}\n"
            result += f"  Task Run Status: {step.get('taskRunStatus', 'N/A')}\n"
            result += f"  Created: {step.get('createdAt', 'N/A')}\n"
            
            # Task counts
            task_counts = step.get('taskRunStatusCounts', {})
            if task_counts:
                result += f"  Tasks: "
                counts = []
                for status, count in task_counts.items():
                    counts.append(f"{status}={count}")
                result += ", ".join(counts) + "\n"
            
            if step.get('startedAt'):
                result += f"  Started: {step['startedAt']}\n"
            if step.get('endedAt'):
                result += f"  Ended: {step['endedAt']}\n"
            if step.get('lifecycleStatusMessage'):
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
        response = client.get_step(
            farmId=farm_id,
            queueId=queue_id,
            jobId=job_id,
            stepId=step_id
        )
        
        result = f"**Step Details for {step_id}**\n\n"
        result += f"Name: {response.get('name', 'N/A')}\n"
        result += f"Status: {response.get('lifecycleStatus', 'N/A')}\n"
        result += f"Task Run Status: {response.get('taskRunStatus', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Started: {response.get('startedAt', 'N/A')}\n"
        result += f"Ended: {response.get('endedAt', 'N/A')}\n"
        
        # Task counts
        task_counts = response.get('taskRunStatusCounts', {})
        if task_counts:
            result += f"\n**Task Status Counts:**\n"
            for status, count in task_counts.items():
                result += f"- {status}: {count}\n"
        
        # Dependency counts
        dep_counts = response.get('dependencyCounts', {})
        if dep_counts:
            result += f"\n**Dependency Counts:**\n"
            for key, count in dep_counts.items():
                result += f"- {key}: {count}\n"
        
        if response.get('lifecycleStatusMessage'):
            result += f"\n**Status Message:**\n{response['lifecycleStatusMessage']}\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error getting step details: {e}")
        return format_tool_error(e, context=f"getting details for step {step_id}")


@tool
def list_deadline_tasks(farm_id: str, queue_id: str, job_id: str, step_id: str, max_results: int = 20) -> str:
    """
    Search for tasks in a specific Deadline Cloud step using the SearchTasks API.
    
    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        step_id: The ID of the step
        max_results: Maximum number of tasks to return (default: 20)
        
    Returns:
        String containing task information or error message
    """
    
    try:
        client = get_deadline_client()
        
        # Build search parameters
        search_params = {
            'farmId': farm_id,
            'queueIds': [queue_id],
            'jobId': job_id,
            'itemOffset': 0,
            'pageSize': min(max_results, 100)
        }
        
        response = client.search_tasks(**search_params)
        
        tasks = response.get('tasks', [])
        total_results = response.get('totalResults', 0)
        
        if not tasks:
            return f"No tasks found for step {step_id}."
        
        result = f"Found {len(tasks)} of {total_results} task(s) for step {step_id}:\n\n"
        
        for task in tasks:
            result += f"- **Task {task['taskId']}**\n"
            result += f"  Status: {task.get('runStatus', 'N/A')}\n"
            result += f"  Created: {task.get('createdAt', 'N/A')}\n"
            result += f"  Started: {task.get('startedAt', 'N/A')}\n"
            result += f"  Ended: {task.get('endedAt', 'N/A')}\n"
            
            if task.get('failureRetryCount'):
                result += f"  Retry Count: {task['failureRetryCount']}\n"
            
            if task.get('latestSessionActionId'):
                result += f"  Latest Session Action: {task['latestSessionActionId']}\n"
            
            result += "\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        return format_tool_error(e, context=f"listing tasks in step {step_id}")


@tool
def get_deadline_task_details(farm_id: str, queue_id: str, job_id: str, step_id: str, task_id: str) -> str:
    """
    Get detailed information about a specific Deadline Cloud task.
    
    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        step_id: The ID of the step
        task_id: The ID of the task
        
    Returns:
        String containing detailed task information or error message
    """
    
    try:
        client = get_deadline_client()
        response = client.get_task(
            farmId=farm_id,
            queueId=queue_id,
            jobId=job_id,
            stepId=step_id,
            taskId=task_id
        )
        
        result = f"**Task Details for {task_id}**\n\n"
        result += f"Status: {response.get('runStatus', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Started: {response.get('startedAt', 'N/A')}\n"
        result += f"Ended: {response.get('endedAt', 'N/A')}\n"
        
        if response.get('failureRetryCount'):
            result += f"Failure Retry Count: {response['failureRetryCount']}\n"
        
        if response.get('latestSessionActionId'):
            result += f"Latest Session Action ID: {response['latestSessionActionId']}\n"
        
        if response.get('parameters'):
            result += f"\n**Parameters:**\n"
            for key, value in response['parameters'].items():
                result += f"- {key}: {value}\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error getting task details: {e}")
        return format_tool_error(e, context=f"getting details for task {task_id}")


@tool
def list_deadline_sessions(farm_id: str, queue_id: str, job_id: str, max_results: int = 20) -> str:
    """
    List sessions for a specific Deadline Cloud job.
    
    Args:
        farm_id: The ID of the farm
        queue_id: The ID of the queue
        job_id: The ID of the job
        max_results: Maximum number of sessions to return (default: 20)
        
    Returns:
        String containing session information or error message
    """
    
    try:
        client = get_deadline_client()
        response = client.list_sessions(
            farmId=farm_id,
            queueId=queue_id,
            jobId=job_id,
            maxResults=min(max_results, 100)
        )
        
        sessions = response.get('sessions', [])
        if not sessions:
            return f"No sessions found for job {job_id}."
        
        result = f"Found {len(sessions)} session(s) for job {job_id}:\n\n"
        for session in sessions:
            result += f"- **Session {session['sessionId']}**\n"
            result += f"  Status: {session.get('lifecycleStatus', 'N/A')}\n"
            result += f"  Fleet ID: {session.get('fleetId', 'N/A')}\n"
            result += f"  Worker ID: {session.get('workerId', 'N/A')}\n"
            result += f"  Started: {session.get('startedAt', 'N/A')}\n"
            result += f"  Ended: {session.get('endedAt', 'N/A')}\n"
            
            if session.get('targetLifecycleStatus'):
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
    
    # Validate session_id format
    is_valid, error_msg = validate_deadline_id(session_id, 'session')
    if not is_valid:
        return format_tool_error(
            Exception(error_msg),
            context="getting session details"
        )
    
    try:
        client = get_deadline_client()
        response = client.get_session(
            farmId=farm_id,
            queueId=queue_id,
            jobId=job_id,
            sessionId=session_id
        )
        
        result = f"**Session Details for {session_id}**\n\n"
        result += f"Status: {response.get('lifecycleStatus', 'N/A')}\n"
        result += f"Fleet ID: {response.get('fleetId', 'N/A')}\n"
        result += f"Worker ID: {response.get('workerId', 'N/A')}\n"
        result += f"Started: {response.get('startedAt', 'N/A')}\n"
        result += f"Ended: {response.get('endedAt', 'N/A')}\n"
        result += f"Target Status: {response.get('targetLifecycleStatus', 'N/A')}\n"
        
        if response.get('hostProperties'):
            result += f"\n**Host Properties:**\n"
            host = response['hostProperties']
            result += f"- IP Address: {host.get('ipAddresses', {}).get('ipV4Addresses', ['N/A'])[0]}\n"
            result += f"- Host Name: {host.get('hostName', 'N/A')}\n"
            result += f"- EC2 Instance ARN: {host.get('ec2InstanceArn', 'N/A')}\n"
        
        if response.get('log'):
            result += f"\n**Log Configuration:**\n"
            log = response['log']
            result += f"- Log Driver: {log.get('logDriver', 'N/A')}\n"
            if log.get('options'):
                result += f"- Options: {log['options']}\n"
            
            # Extract worker log information if available
            if log.get('logDriver') == 'awslogs':
                options = log.get('options', {})
                log_group = options.get('awslogs-group', 'N/A')
                log_stream = options.get('awslogs-stream', 'N/A')
                
                result += f"\n**Worker Log Location:**\n"
                result += f"- Log Group: {log_group}\n"
                result += f"- Log Stream: {log_stream}\n"
                result += f"\n💡 Use get_worker_cloudwatch_logs to fetch worker logs for detailed troubleshooting.\n"
        
        # Add note about getting worker metadata
        if response.get('workerId') and response.get('fleetId'):
            result += f"\n💡 Use get_deadline_worker_details to get worker metadata and configuration.\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error getting session details: {e}")
        return format_tool_error(e, context=f"getting details for session {session_id}")


@tool
def list_deadline_session_actions(farm_id: str, queue_id: str, job_id: str, session_id: str, task_id: str = None, max_results: int = 20) -> str:
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
    
    # Validate session_id format (required)
    is_valid, error_msg = validate_deadline_id(session_id, 'session')
    if not is_valid:
        return format_tool_error(
            Exception(error_msg),
            context="listing session actions"
        )
    
    # Validate task_id format if provided
    if task_id:
        is_valid, error_msg = validate_deadline_id(task_id, 'task')
        if not is_valid:
            return format_tool_error(
                Exception(error_msg),
                context="listing session actions"
            )
    
    try:
        client = get_deadline_client()
        
        # session_id is required by the AWS API
        params = {
            'farmId': farm_id,
            'queueId': queue_id,
            'jobId': job_id,
            'sessionId': session_id,
            'maxResults': min(max_results, 100)
        }
        
        filter_desc = f"session {session_id}"
        
        # Add optional task_id filter if provided
        if task_id:
            params['taskId'] = task_id
            filter_desc += f" and task {task_id}"
        
        logger.info(f"Calling list_session_actions with params: {params}")
        response = client.list_session_actions(**params)
        
        actions = response.get('sessionActions', [])
        if not actions:
            return f"No session actions found for {filter_desc}."
        
        result = f"Found {len(actions)} session action(s) for {filter_desc}:\n\n"
        for action in actions:
            result += f"- **Session Action {action['sessionActionId']}**\n"
            result += f"  Status: {action.get('status', 'N/A')}\n"
            result += f"  Started: {action.get('startedAt', 'N/A')}\n"
            result += f"  Ended: {action.get('endedAt', 'N/A')}\n"
            
            if action.get('definition'):
                definition = action['definition']
                if 'envEnter' in definition:
                    result += f"  Type: Environment Enter\n"
                    result += f"  Environment ID: {definition['envEnter'].get('environmentId', 'N/A')}\n"
                elif 'envExit' in definition:
                    result += f"  Type: Environment Exit\n"
                    result += f"  Environment ID: {definition['envExit'].get('environmentId', 'N/A')}\n"
                elif 'taskRun' in definition:
                    result += f"  Type: Task Run\n"
                    task_run = definition['taskRun']
                    result += f"  Task ID: {task_run.get('taskId', 'N/A')}\n"
                    result += f"  Step ID: {task_run.get('stepId', 'N/A')}\n"
                elif 'syncInputJobAttachments' in definition:
                    result += f"  Type: Sync Input Job Attachments\n"
            
            if action.get('progressPercent'):
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
        response = client.get_worker(
            farmId=farm_id,
            fleetId=fleet_id,
            workerId=worker_id
        )
        
        result = f"**Worker Details for {worker_id}**\n\n"
        result += f"Status: {response.get('status', 'N/A')}\n"
        result += f"Created: {response.get('createdAt', 'N/A')}\n"
        result += f"Created By: {response.get('createdBy', 'N/A')}\n"
        result += f"Updated: {response.get('updatedAt', 'N/A')}\n"
        
        if response.get('hostProperties'):
            result += f"\n**Host Properties:**\n"
            host = response['hostProperties']
            
            if host.get('ipAddresses'):
                ip_addrs = host['ipAddresses']
                if ip_addrs.get('ipV4Addresses'):
                    result += f"- IPv4 Addresses: {', '.join(ip_addrs['ipV4Addresses'])}\n"
                if ip_addrs.get('ipV6Addresses'):
                    result += f"- IPv6 Addresses: {', '.join(ip_addrs['ipV6Addresses'])}\n"
            
            result += f"- Host Name: {host.get('hostName', 'N/A')}\n"
            result += f"- EC2 Instance ARN: {host.get('ec2InstanceArn', 'N/A')}\n"
            result += f"- EC2 Instance Type: {host.get('ec2InstanceType', 'N/A')}\n"
        
        if response.get('log'):
            result += f"\n**Log Configuration:**\n"
            log = response['log']
            result += f"- Log Driver: {log.get('logDriver', 'N/A')}\n"
            if log.get('options'):
                options = log['options']
                result += f"- Log Group: {options.get('awslogs-group', 'N/A')}\n"
                result += f"- Log Stream Prefix: {options.get('awslogs-stream-prefix', 'N/A')}\n"
        
        return result
    
    except Exception as e:
        error_msg = str(e)
        
        # Handle 404 - worker no longer exists (this is expected and OK)
        if "ResourceNotFoundException" in error_msg or "404" in error_msg or "not found" in error_msg.lower():
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
def get_deadline_session_action_details(farm_id: str, queue_id: str, job_id: str, session_action_id: str) -> str:
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
            farmId=farm_id,
            queueId=queue_id,
            jobId=job_id,
            sessionActionId=session_action_id
        )
        
        result = f"**Session Action Details for {session_action_id}**\n\n"
        result += f"Session ID: {response.get('sessionId', 'N/A')}\n"
        result += f"Status: {response.get('status', 'N/A')}\n"
        result += f"Started: {response.get('startedAt', 'N/A')}\n"
        result += f"Ended: {response.get('endedAt', 'N/A')}\n"
        result += f"Progress: {response.get('progressPercent', 0)}%\n"
        
        if response.get('definition'):
            result += f"\n**Definition:**\n"
            definition = response['definition']
            
            if 'envEnter' in definition:
                result += f"Type: Environment Enter\n"
                env = definition['envEnter']
                result += f"Environment ID: {env.get('environmentId', 'N/A')}\n"
            elif 'envExit' in definition:
                result += f"Type: Environment Exit\n"
                env = definition['envExit']
                result += f"Environment ID: {env.get('environmentId', 'N/A')}\n"
            elif 'taskRun' in definition:
                result += f"Type: Task Run\n"
                task_run = definition['taskRun']
                result += f"Task ID: {task_run.get('taskId', 'N/A')}\n"
                result += f"Step ID: {task_run.get('stepId', 'N/A')}\n"
                if task_run.get('parameters'):
                    result += f"Parameters: {task_run['parameters']}\n"
            elif 'syncInputJobAttachments' in definition:
                result += f"Type: Sync Input Job Attachments\n"
                sync = definition['syncInputJobAttachments']
                result += f"Step ID: {sync.get('stepId', 'N/A')}\n"
        
        if response.get('progressMessage'):
            result += f"\n**Progress Message:**\n{response['progressMessage']}\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error getting session action details: {e}")
        return format_tool_error(e, context=f"getting details for session action {session_action_id}")


def get_deadline_tools():
    """
    Get all custom Deadline Cloud tools.
    
    Returns:
        List of Deadline Cloud tools
    """
    if not DEADLINE_AVAILABLE:
        print("⚠️  boto3 not available - Deadline Cloud tools disabled")
        return []
    
    return [
        # Farm and Queue tools
        list_deadline_farms,
        list_deadline_queues,
        list_deadline_fleets,
        
        # Queue-Fleet Association tools
        list_queue_fleet_associations,
        get_queue_fleet_association_details,
        
        # Job tools
        list_deadline_jobs,
        get_deadline_job_details,
        
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
    ]
