"""
Custom CloudWatch tools using the SDK directly with the same credentials as Deadline tools.
Simplified to only use logs:GetLogEvents to minimize IAM permission requirements.
"""
from strands import tool
import logging
import os
import json
from datetime import datetime, timedelta
from typing import Optional
from configparser import ConfigParser
import boto3

logger = logging.getLogger(__name__)

# Check if boto3 is available
BOTO3_AVAILABLE = True
try:
    import boto3
except ImportError:
    BOTO3_AVAILABLE = False


# Import get_queue_role_credentials from deadline_tools to avoid duplication
from .deadline_tools import get_queue_role_credentials


def get_cloudwatch_client(farm_id: str = None, queue_id: str = None, config: Optional[ConfigParser] = None):
    """
    Get a CloudWatch Logs client with appropriate credentials.
    
    If farm_id and queue_id are provided, assumes the queue role for read access.
    Otherwise, uses the credentials from the deadline package's credential system.
    
    Args:
        farm_id: Optional farm ID to assume queue role
        queue_id: Optional queue ID to assume queue role
        config: Optional configuration parser
    
    Returns:
        boto3 client for logs service
    """
    from ...client.api import get_boto3_session
    
    # If farm_id and queue_id provided, assume queue role
    if farm_id and queue_id:
        logger.info("Attempting to assume queue role for CloudWatch access")
        queue_creds = get_queue_role_credentials(farm_id, queue_id, config=config)
        
        if queue_creds:
            try:
                session = boto3.Session(
                    aws_access_key_id=queue_creds['access_key_id'],
                    aws_secret_access_key=queue_creds['secret_access_key'],
                    aws_session_token=queue_creds['session_token']
                )
                client = session.client('logs')
                logger.info("✅ CloudWatch client created with queue role credentials")
                return client
            except Exception as e:
                logger.error(f"Failed to create client with queue role: {e}")
                logger.info("Falling back to user credentials")
    
    # Use deadline package's credential system
    session = get_boto3_session(config=config)
    return session.client('logs')


@tool
def get_cloudwatch_log_events(
    log_group_name: str,
    log_stream_name: str,
    farm_id: str,
    queue_id: str,
    start_time: str = None,
    end_time: str = None,
    max_events: int = 1000,
    start_from_head: bool = False
) -> str:
    """
    Get SESSION/TASK log events from CloudWatch using QUEUE role credentials.
    
    ⚠️ CRITICAL: This tool is for SESSION and TASK logs ONLY (not worker logs).
    - Uses QUEUE role credentials (requires farm_id and queue_id)
    - Log group format: /aws/deadline/farm-{farmId}/queue-{queueId}
    - Log stream format: session-{sessionId}
    
    For WORKER logs, use get_worker_cloudwatch_logs instead (requires fleet_id).
    
    IMPORTANT: You must provide farm_id and queue_id to assume the queue role.
    
    RECOMMENDED: Pass start_time and end_time from the session action's startedAt and endedAt
    timestamps to filter logs to the relevant time window.
    
    Args:
        log_group_name: Queue log group (e.g., '/aws/deadline/farm-abc/queue-xyz')
        log_stream_name: Session log stream (e.g., 'session-xyz789')
        farm_id: The farm ID (required for assuming queue role)
        queue_id: The queue ID (required for assuming queue role)
        start_time: Optional start time in ISO format (e.g., '2024-01-01T00:00:00Z')
                   Use the session action's startedAt timestamp
        end_time: Optional end time in ISO format (e.g., '2024-01-01T01:00:00Z')
                 Use the session action's endedAt timestamp
        max_events: Maximum number of events to return (default: 1000, will paginate if needed)
        start_from_head: If True, start from oldest events; if False, start from newest (default: False)
        
    Returns:
        String containing log events or error message
    """
    if not BOTO3_AVAILABLE:
        return "❌ boto3 not available. Install with: pip install boto3"
    
    try:
        try:
            client = get_cloudwatch_client(farm_id=farm_id, queue_id=queue_id)
            
            # Log which credentials are being used
            try:
                # Use the same session as the CloudWatch client
                from ...client.api._session import get_boto3_session
                session = get_boto3_session()
                sts = session.client('sts')
                identity = sts.get_caller_identity()
            except Exception as id_error:
                logger.warning(f"Could not verify CloudWatch client identity: {id_error}")
                
        except Exception as client_error:
            logger.error(f"Failed to create CloudWatch client: {client_error}")
            import traceback
            logger.error(traceback.format_exc())
            return f"❌ Failed to create CloudWatch client: {str(client_error)}"
        
        params = {
            'logGroupName': log_group_name,
            'logStreamName': log_stream_name,
            'limit': min(max_events, 10000),  # CloudWatch max is 10000 per request
            'startFromHead': start_from_head
        }
        
        # Parse time parameters
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                params['startTime'] = int(start_dt.timestamp() * 1000)
                logger.info(f"Start time: {start_time} -> {params['startTime']}")
            except Exception as e:
                logger.warning(f"Failed to parse start_time: {e}")
        
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                params['endTime'] = int(end_dt.timestamp() * 1000)
                logger.info(f"End time: {end_time} -> {params['endTime']}")
            except Exception as e:
                logger.warning(f"Failed to parse end_time: {e}")
        
        logger.info(f"Calling get_log_events with params:")
        logger.info(f"  - logGroupName: {params['logGroupName']}")
        logger.info(f"  - logStreamName: {params['logStreamName']}")
        logger.info(f"  - limit: {params['limit']}")
        logger.info(f"  - startFromHead: {params['startFromHead']}")
        if 'startTime' in params:
            logger.info(f"  - startTime: {params['startTime']}")
        if 'endTime' in params:
            logger.info(f"  - endTime: {params['endTime']}")
        
        # Paginate through results to get all events
        all_events = []
        next_token = None
        page_count = 0
        max_pages = 10  # Safety limit to avoid infinite loops
        
        try:
            while page_count < max_pages:
                page_count += 1
                
                # Add pagination token if we have one
                if next_token:
                    params['nextToken'] = next_token
                
                logger.info(f"Fetching page {page_count}...")
                response = client.get_log_events(**params)
                
                events = response.get('events', [])
                all_events.extend(events)
                
                logger.info(f"Page {page_count}: Retrieved {len(events)} events (total so far: {len(all_events)})")
                
                # Check if we have more pages
                next_backward_token = response.get('nextBackwardToken')
                next_forward_token = response.get('nextForwardToken')
                
                # If we've reached the limit or no more events, stop
                if len(all_events) >= max_events:
                    logger.info(f"Reached max_events limit ({max_events}), stopping pagination")
                    break
                
                if not events:
                    logger.info("No more events in this page, stopping pagination")
                    break
                
                # Use the appropriate token based on direction
                if start_from_head:
                    # Going forward in time
                    if next_forward_token and next_forward_token != next_token:
                        next_token = next_forward_token
                    else:
                        logger.info("No more forward pages available")
                        break
                else:
                    # Going backward in time
                    if next_backward_token and next_backward_token != next_token:
                        next_token = next_backward_token
                    else:
                        logger.info("No more backward pages available")
                        break
            
            logger.info(f"✅ get_log_events completed after {page_count} page(s)")
            logger.info(f"Total events retrieved: {len(all_events)}")
        except Exception as api_error:
            error_str = str(api_error)
            logger.error("=" * 80)
            logger.error("CLOUDWATCH API ERROR")
            logger.error("=" * 80)
            logger.error(f"Error type: {type(api_error).__name__}")
            logger.error(f"Error message: {error_str}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            logger.error("=" * 80)
            
            # Check if it's a permission error with the queue role
            if 'AccessDeniedException' in error_str and 'AWSDeadlineCloudQueueRole' in error_str:
                return (
                    f"❌ The queue role does not have permission to access this CloudWatch log group.\n\n"
                    f"**Issue**: The queue role has `logs:GetLogEvents` permission, but only for farm-level logs.\n"
                    f"The policy allows: `arn:aws:logs:*:*:log-group:/aws/deadline/farm-*/*`\n"
                    f"But the logs are at: `{log_group_name}` (queue-level)\n\n"
                    f"**Solution**: Update the queue role policy to include queue-level logs:\n"
                    f"```json\n"
                    f'{{\n'
                    f'  "Effect": "Allow",\n'
                    f'  "Action": ["logs:GetLogEvents"],\n'
                    f'  "Resource": [\n'
                    f'    "arn:aws:logs:*:*:log-group:/aws/deadline/farm-*/*",\n'
                    f'    "arn:aws:logs:*:*:log-group:/aws/deadline/queue-*/*"\n'
                    f'  ]\n'
                    f'}}\n'
                    f"```\n\n"
                    f"**Workaround**: View logs directly in AWS Console:\n"
                    f"- Log Group: `{log_group_name}`\n"
                    f"- Log Stream: `{log_stream_name}`\n\n"
                    f"Original error: {error_str}"
                )
            
            return f"❌ CloudWatch API error: {error_str}"
        
        # Trim to max_events if we got more
        if len(all_events) > max_events:
            all_events = all_events[:max_events]
            logger.info(f"Trimmed to max_events: {max_events}")
        
        if not all_events:
            return f"No log events found in {log_group_name}/{log_stream_name} for the specified time range."
        
        result = f"Found {len(all_events)} log event(s) in {log_group_name}/{log_stream_name}"
        if start_time or end_time:
            result += f" (filtered by time range)"
        result += ":\n\n"
        
        for event in all_events:
            timestamp = datetime.fromtimestamp(event['timestamp'] / 1000).isoformat()
            result += f"[{timestamp}] {event['message']}\n"
        
        logger.info(f"Successfully retrieved {len(all_events)} log events")
        return result
    
    except Exception as e:
        logger.error(f"Unexpected error getting log events: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return f"❌ Unexpected error getting log events: {str(e)}"


@tool
def get_worker_cloudwatch_logs(
    log_group_name: str,
    log_stream_name: str,
    farm_id: str,
    fleet_id: str,
    start_time: str = None,
    end_time: str = None,
    max_events: int = 1000,
    start_from_head: bool = False
) -> str:
    """
    Get WORKER log events from CloudWatch using FLEET role credentials.
    
    ⚠️ CRITICAL: This tool is for WORKER logs ONLY (not session/task logs).
    - Uses FLEET role credentials (requires farm_id and fleet_id)
    - Log group format: /aws/deadline/farm-{farmId}/fleet-{fleetId}
    - Log stream format: worker-{workerId}
    
    For SESSION/TASK logs, use get_cloudwatch_log_events instead (requires queue_id).
    
    Worker logs contain detailed information about job execution on the worker,
    including environment setup, task execution, and any worker-level errors.
    
    To get worker logs:
    1. Call get_deadline_session_details to get the session information
    2. Extract logGroupName and logStreamName from the workerLog value e.g.
        "workerLog": {
            "logDriver": "awslogs",
            "options": {
                "logGroupName": "/aws/deadline/farm-abc/fleet-xyz",
                "logStreamName": "worker-abc123"
            }
        }
    3. Extract the fleetId from the session details
    4. Call this tool with farm_id and fleet_id (NOT queue_id)
    
    IMPORTANT: You must provide farm_id and fleet_id to assume the fleet role.
    DO NOT use queue_id for worker logs - that's for session/task logs only.
    
    RECOMMENDED: Pass start_time and end_time from the session's startedAt and endedAt
    timestamps to filter logs to the relevant time window.
    
    Args:
        log_group_name: Fleet log group (e.g., '/aws/deadline/farm-abc/fleet-xyz')
        log_stream_name: Worker log stream (e.g., 'worker-abc123')
        farm_id: The farm ID (required for assuming fleet role)
        fleet_id: The fleet ID (required for assuming fleet role, from session details)
        start_time: Optional start time in ISO format (e.g., '2024-01-01T00:00:00Z')
                   Use the session's startedAt timestamp
        end_time: Optional end time in ISO format (e.g., '2024-01-01T01:00:00Z')
                 Use the session's endedAt timestamp
        max_events: Maximum number of events to return (default: 1000, will paginate if needed)
        start_from_head: If True, start from oldest events; if False, start from newest (default: False)
        
    Returns:
        String containing worker log events or error message
    """
    if not BOTO3_AVAILABLE:
        return "❌ boto3 not available. Install with: pip install boto3"
    
    try:
        logger.info("=" * 80)
        logger.info("GET_WORKER_CLOUDWATCH_LOGS CALLED")
        logger.info("=" * 80)
        logger.info(f"Log Group: {log_group_name}")
        logger.info(f"Log Stream: {log_stream_name}")
        logger.info(f"Farm ID: {farm_id}")
        logger.info(f"Fleet ID: {fleet_id}")
        logger.info(f"Max Events: {max_events}")
        logger.info(f"Start From Head: {start_from_head}")
        
        # Get credentials by assuming fleet role
        try:
            from ...client.api import get_boto3_client
            deadline_client = get_boto3_client("deadline")
            
            logger.info("Assuming fleet role for worker log access...")
            response = deadline_client.assume_fleet_role_for_read(
                farmId=farm_id,
                fleetId=fleet_id
            )
            
            creds = response.get('credentials', {})
            logger.info("✅ Successfully assumed fleet role")
            logger.info(f"Access Key ID: {creds.get('accessKeyId', '')[:20]}...")
            
            # Create CloudWatch client with fleet role credentials
            region = os.getenv('AWS_REGION', 'us-west-2')
            session = boto3.Session(
                aws_access_key_id=creds.get('accessKeyId'),
                aws_secret_access_key=creds.get('secretAccessKey'),
                aws_session_token=creds.get('sessionToken'),
                region_name=region
            )
            client = session.client('logs')
            logger.info("✅ CloudWatch client created with fleet role credentials")
            
        except Exception as client_error:
            logger.error(f"Failed to create CloudWatch client with fleet role: {client_error}")
            import traceback
            logger.error(traceback.format_exc())
            return f"❌ Failed to assume fleet role or create CloudWatch client: {str(client_error)}"
        
        params = {
            'logGroupName': log_group_name,
            'logStreamName': log_stream_name,
            'limit': min(max_events, 10000),
            'startFromHead': start_from_head
        }
        
        # Parse time parameters
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                params['startTime'] = int(start_dt.timestamp() * 1000)
                logger.info(f"Start time: {start_time} -> {params['startTime']}")
            except Exception as e:
                logger.warning(f"Failed to parse start_time: {e}")
        
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                params['endTime'] = int(end_dt.timestamp() * 1000)
                logger.info(f"End time: {end_time} -> {params['endTime']}")
            except Exception as e:
                logger.warning(f"Failed to parse end_time: {e}")
        
        logger.info(f"Calling get_log_events for worker logs...")
        
        # Paginate through results
        all_events = []
        next_token = None
        page_count = 0
        max_pages = 10
        
        try:
            while page_count < max_pages:
                page_count += 1
                
                if next_token:
                    params['nextToken'] = next_token
                
                logger.info(f"Fetching page {page_count}...")
                response = client.get_log_events(**params)
                
                events = response.get('events', [])
                all_events.extend(events)
                
                logger.info(f"Page {page_count}: Retrieved {len(events)} events (total: {len(all_events)})")
                
                if len(all_events) >= max_events or not events:
                    break
                
                next_backward_token = response.get('nextBackwardToken')
                next_forward_token = response.get('nextForwardToken')
                
                if start_from_head:
                    if next_forward_token and next_forward_token != next_token:
                        next_token = next_forward_token
                    else:
                        break
                else:
                    if next_backward_token and next_backward_token != next_token:
                        next_token = next_backward_token
                    else:
                        break
            
            logger.info(f"✅ Retrieved {len(all_events)} worker log events")
        except Exception as api_error:
            error_str = str(api_error)
            logger.error(f"CloudWatch API error: {error_str}")
            import traceback
            logger.error(traceback.format_exc())
            return f"❌ CloudWatch API error: {error_str}"
        
        if len(all_events) > max_events:
            all_events = all_events[:max_events]
        
        if not all_events:
            return f"No worker log events found in {log_group_name}/{log_stream_name} for the specified time range."
        
        result = f"Found {len(all_events)} worker log event(s) in {log_group_name}/{log_stream_name}"
        if start_time or end_time:
            result += f" (filtered by time range)"
        result += ":\n\n"
        
        for event in all_events:
            timestamp = datetime.fromtimestamp(event['timestamp'] / 1000).isoformat()
            result += f"[{timestamp}] {event['message']}\n"
        
        logger.info(f"Successfully retrieved {len(all_events)} worker log events")
        return result
    
    except Exception as e:
        logger.error(f"Unexpected error getting worker log events: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return f"❌ Unexpected error getting worker log events: {str(e)}"


def get_cloudwatch_tools():
    """
    Get all custom CloudWatch tools.
    
    Includes tools for both task logs (queue role) and worker logs (fleet role).
    
    Returns:
        List of CloudWatch tools
    """
    if not BOTO3_AVAILABLE:
        print("⚠️  boto3 not available - CloudWatch tools disabled")
        return []
    
    return [
        get_cloudwatch_log_events,
        get_worker_cloudwatch_logs,
    ]
