# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Fleet Configuration Agent - Validates Deadline Cloud fleet configuration and identifies common issues.
"""

from deadline.client.api import get_boto3_client
from strands import Agent, tool
from deadline._agents.bin.model_config import get_farm_setup_model


FARM_CONFIGURATION_AGENT_SYSTEM_PROMPT = """
You are a resource configuration specialist for AWS Deadline Cloud.

Your role is to validate fleet and queue configurations and identify common issues that prevent jobs from running, in order of confidence (high, medium, low).

## CRITICAL - Finding Fleet IDs

**You will receive a farm_id and queue_id, but NOT a fleet_id.**

To find the fleet ID(s):
1. Call `list_fleet_queues(farm_id, fleet_id)` - NO! This requires fleet_id which you don't have
2. **CORRECT**: Use the Deadline API to list queue-fleet associations for the queue
3. The queue may be associated with multiple fleets
4. Check each associated fleet

**Important**: Do NOT assume the fleet_id is the same as the queue_id. Do NOT make up a fleet_id.
You MUST discover the fleet_id(s) from the queue-fleet associations.

## Key Checks

1. **Fleet-Queue Association**:
   - Fleet must be associated with at least one queue
   - Queue must be active and properly configured

2. **Fleet Size and Scaling**:
   - Minimum worker count > 0 (or auto-scaling enabled)
   - Maximum worker count sufficient for workload
   - Target capacity configured appropriately

3. **Auto-Scaling Configuration**:
   - Scaling policies properly defined
   - Metrics and thresholds set correctly
   - Cooldown periods reasonable

4. **Instance Configuration**:
   - Instance types appropriate for workload
   - AMI exists and is accessible
   - Instance profile has necessary permissions

5. **Fleet Status**:
   - Fleet is in ACTIVE state
   - No errors in fleet status
   - Workers are launching successfully

## Common Fleet Issues

- **No Queue Association**: Fleet not linked to any queue
- **Zero Capacity**: Min/max worker count set to 0
- **Misconfigured Auto-Scaling**: Scaling never triggers or scales too aggressively
- **Wrong Instance Type**: Insufficient CPU/memory for jobs

## Your Response

**CRITICAL - NO PLEASANTRIES**:
- ❌ DO NOT say "Certainly!"
- ❌ DO NOT say "I'll be happy to..."
- ❌ DO NOT say "Let me help you..."
- ✅ Just start with "Farm Setup Agent here."

**CRITICAL - Workflow**:
1. First, call `list_queue_fleets(farm_id, queue_id)` to discover fleet IDs
2. Then, for each fleet, call `get_fleet_details(farm_id, fleet_id)`
3. Then validate configuration

**CRITICAL - Tool Usage Display**:
Use ONLY concise bullet points for tool usage. Each bullet point MUST end with a newline.
- ✅ GOOD:
```
- Discovering fleets for queue... ✓
- Checking fleet details... ✓
- Validating queue associations... ✓
- Checking worker status... ✓
```
- ❌ BAD: "Now let me check the fleet configuration..."
- ❌ BAD: "Based on the fleet details, I'll validate the queue associations..."
- ❌ BAD: "Certainly! I'll check the fleet configuration..."

**CRITICAL - NO NARRATIVE BETWEEN TOOL CALLS**:
- DO NOT explain what you're about to do
- DO NOT explain what you just did
- DO NOT apologize for errors
- ONLY use bullet points with checkmarks
- Each bullet point MUST be on its own line

**CRITICAL - Response Format**:
Start each bullet point on a NEW LINE. The format should be:
```
Farm Setup Agent here.

- Discovering fleets for queue... ✓
- Checking fleet details... ✓
- Validating queue associations... ✓
- Checking worker status... ✓

## Configuration Assessment

[Assessment details]

## Recommendations

[Specific fixes needed]
```

**CRITICAL - Newline Placement**:
- Put each bullet point on its OWN line
- Add a blank line after "Farm Setup Agent here."
- Add a blank line before "## Configuration Assessment"
- Do NOT run bullets together like: `- First... ✓- Second... ✓`
- DO format like: `- First... ✓\n- Second... ✓\n- Third... ✓`

Provide:
- Very concise fleet configuration assessment
- Only return high confidence identified misconfigurations
- Specific recommendations for fixes
"""


@tool
def get_fleet_details(farm_id: str, fleet_id: str) -> str:
    """
    Get detailed information about a Deadline Cloud fleet.

    Args:
        farm_id: Farm ID containing the fleet
        fleet_id: Fleet ID to describe

    Returns:
        Detailed fleet configuration
    """
    try:
        deadline = get_boto3_client("deadline")

        response = deadline.get_fleet(farmId=farm_id, fleetId=fleet_id)

        result = f"Fleet: {fleet_id}\n"
        result += f"Display Name: {response.get('displayName', 'N/A')}\n"
        result += f"Status: {response['status']}\n"
        result += f"Farm: {farm_id}\n\n"

        # Configuration details
        config = response.get("configuration", {})

        if "customerManaged" in config:
            cm = config["customerManaged"]
            result += "Configuration Type: Customer Managed\n"
            result += f"Mode: {cm.get('mode', 'N/A')}\n"

            if "workerCapabilities" in cm:
                wc = cm["workerCapabilities"]
                result += "\nWorker Capabilities:\n"
                result += f"  vCPU: {wc.get('vCpuCount', {})}\n"
                result += f"  Memory: {wc.get('memoryMiB', {})}\n"
                result += f"  OS Family: {wc.get('osFamily', 'N/A')}\n"
                result += f"  CPU Architecture: {wc.get('cpuArchitectureType', 'N/A')}\n"

        elif "serviceManagedEc2" in config:
            sme = config["serviceManagedEc2"]
            result += "Configuration Type: Service Managed EC2\n"
            result += (
                f"Instance Market: {sme.get('instanceMarketOptions', {}).get('type', 'N/A')}\n"
            )

            if "instanceCapabilities" in sme:
                ic = sme["instanceCapabilities"]
                result += "\nInstance Capabilities:\n"
                result += f"  vCPU: {ic.get('vCpuCount', {})}\n"
                result += f"  Memory: {ic.get('memoryMiB', {})}\n"
                result += f"  OS Family: {ic.get('osFamily', 'N/A')}\n"
                result += f"  CPU Architecture: {ic.get('cpuArchitectureType', 'N/A')}\n"

                if "allowedInstanceTypes" in ic:
                    result += f"  Allowed Instance Types: {', '.join(ic['allowedInstanceTypes'])}\n"

        # Capacity status
        result += f"\nMin Worker Count: {response.get('minWorkerCount', 0)}\n"
        result += f"Max Worker Count: {response.get('maxWorkerCount', 0)}\n"
        result += f"Worker Count: {response.get('workerCount', 0)}\n"

        # Auto-scaling
        if "autoScalingStatus" in response:
            result += (
                f"\nAuto-Scaling Status: {response['autoScalingStatus'].get('status', 'N/A')}\n"
            )

        return result

    except Exception as e:
        return f"❌ Error getting fleet details: {e}"


@tool
def list_queue_fleets(farm_id: str, queue_id: str) -> str:
    """
    List fleets associated with a queue. Use this to discover fleet IDs for a given queue.

    Args:
        farm_id: Farm ID containing the queue
        queue_id: Queue ID to check

    Returns:
        List of associated fleets with their IDs
    """
    try:
        deadline = get_boto3_client("deadline")

        response = deadline.list_queue_fleet_associations(farmId=farm_id, queueId=queue_id)

        associations = response.get("queueFleetAssociations", [])

        if not associations:
            return f"⚠️  No fleets associated with queue {queue_id}\n\nThis is a common issue - the queue cannot process jobs without a fleet association."

        result = f"Fleets associated with queue {queue_id}:\n\n"

        for assoc in associations:
            result += f"- Fleet ID: {assoc['fleetId']}\n"
            result += f"  Status: {assoc['status']}\n"
            result += f"  Created: {assoc.get('createdAt', 'N/A')}\n\n"

        return result

    except Exception as e:
        return f"❌ Error listing queue fleets: {str(e)}"


@tool
def list_fleet_queues(farm_id: str, fleet_id: str) -> str:
    """
    List queues associated with a fleet.

    Args:
        farm_id: Farm ID containing the fleet
        fleet_id: Fleet ID to check

    Returns:
        List of associated queues
    """
    try:
        deadline = get_boto3_client("deadline")

        response = deadline.list_queue_fleet_associations(farmId=farm_id, fleetId=fleet_id)

        associations = response.get("queueFleetAssociations", [])

        if not associations:
            return f"⚠️  No queues associated with fleet {fleet_id}\n\nThis is a common issue - the fleet cannot process jobs without a queue association."

        result = f"Queues associated with fleet {fleet_id}:\n\n"

        for assoc in associations:
            result += f"- Queue: {assoc['queueId']}\n"
            result += f"  Status: {assoc['status']}\n"
            result += f"  Created: {assoc.get('createdAt', 'N/A')}\n\n"

        return result

    except Exception as e:
        return f"❌ Error listing fleet queues: {str(e)}"


@tool
def check_fleet_workers(farm_id: str, fleet_id: str) -> str:
    """
    Check worker status for a fleet.

    Args:
        farm_id: Farm ID containing the fleet
        fleet_id: Fleet ID to check

    Returns:
        Worker status information
    """
    try:
        deadline = get_boto3_client("deadline")

        response = deadline.list_workers(farmId=farm_id, fleetId=fleet_id)

        workers = response.get("workers", [])

        if not workers:
            return f"No workers currently running in fleet {fleet_id}\n\nCheck if:\n- Min worker count is > 0\n- Auto-scaling is configured\n- Fleet has capacity to launch instances"

        result = f"Workers in fleet {fleet_id}:\n\n"

        status_counts = {}
        for worker in workers:
            status = worker["status"]
            status_counts[status] = status_counts.get(status, 0) + 1

        result += "Worker Status Summary:\n"
        for status, count in status_counts.items():
            result += f"  {status}: {count}\n"

        result += f"\nTotal Workers: {len(workers)}\n"

        # Show details of first few workers
        result += "\nSample Workers:\n"
        for worker in workers[:3]:
            result += f"- Worker: {worker['workerId']}\n"
            result += f"  Status: {worker['status']}\n"
            result += f"  Created: {worker.get('createdAt', 'N/A')}\n\n"

        return result

    except Exception as e:
        return f"❌ Error checking fleet workers: {str(e)}"


@tool
def validate_fleet_configuration(farm_id: str, fleet_id: str) -> str:
    """
    Perform comprehensive validation of fleet configuration.

    Args:
        farm_id: Farm ID containing the fleet
        fleet_id: Fleet ID to validate

    Returns:
        Validation results with identified issues
    """
    try:
        deadline = get_boto3_client("deadline")

        # Get fleet details
        fleet = deadline.get_fleet(farmId=farm_id, fleetId=fleet_id)

        issues = []
        warnings = []

        # Check status
        if fleet["status"] != "ACTIVE":
            issues.append(f"Fleet status is {fleet['status']}, not ACTIVE")

        # Check capacity
        min_workers = fleet.get("minWorkerCount", 0)
        max_workers = fleet.get("maxWorkerCount", 0)

        if min_workers == 0 and max_workers == 0:
            issues.append("Both min and max worker counts are 0 - fleet cannot launch workers")
        elif min_workers == 0:
            warnings.append("Min worker count is 0 - fleet relies entirely on auto-scaling")

        if max_workers < min_workers:
            issues.append(f"Max workers ({max_workers}) is less than min workers ({min_workers})")

        # Check queue associations
        assocs = deadline.list_queue_fleet_associations(farmId=farm_id, fleetId=fleet_id)

        if not assocs.get("queueFleetAssociations"):
            issues.append("No queues associated with fleet - jobs cannot be assigned")

        # Build result
        result = f"Fleet Validation: {fleet_id}\n\n"

        if issues:
            result += "❌ ISSUES FOUND:\n"
            for issue in issues:
                result += f"  - {issue}\n"
            result += "\n"

        if warnings:
            result += "⚠️  WARNINGS:\n"
            for warning in warnings:
                result += f"  - {warning}\n"
            result += "\n"

        if not issues and not warnings:
            result += "✓ No configuration issues detected\n"

        return result

    except Exception as e:
        return f"❌ Error validating fleet configuration: {str(e)}"


@tool
def farm_setup_agent(query: str) -> str:
    """
    Validates fleet configuration and identifies common issues.

    Args:
        query: Description of the fleet issue to investigate

    Returns:
        Fleet configuration assessment and recommendations
    """
    import logging
    import time
    from deadline.client.api._telemetry import get_deadline_cloud_library_telemetry_client

    logger = logging.getLogger(__name__)
    logger.info("Resource configuration agent invoked")

    # Get telemetry client
    telemetry_client = get_deadline_cloud_library_telemetry_client()

    # Record start time for latency tracking
    start_time = time.perf_counter_ns()
    is_success = False
    error_type = None

    try:
        # Get model with the same boto_session used by other components
        from deadline.client.api import get_boto3_session
        from deadline._agents.orchestrator import sub_agent_streaming_callback_handler

        boto_session = get_boto3_session()

        fleet_agent = Agent(
            system_prompt=FARM_CONFIGURATION_AGENT_SYSTEM_PROMPT,
            model=get_farm_setup_model(boto_session),  # Pass boto_session to use same credentials
            tools=[
                list_queue_fleets,  # NEW: Discover fleet IDs from queue
                get_fleet_details,
                list_fleet_queues,
                check_fleet_workers,
                validate_fleet_configuration,
            ],
            callback_handler=sub_agent_streaming_callback_handler("Farm Setup Agent"),
        )

        response = fleet_agent(query)
        print()  # Newline after streaming
        is_success = True

        return str(response)
    except Exception as e:
        import traceback

        error_type = type(e).__name__
        error_details = traceback.format_exc()
        return f"❌ Error in fleet configuration agent: {str(e)}\n\nDetails:\n{error_details}"
    finally:
        # Record telemetry
        end_time = time.perf_counter_ns()
        latency = end_time - start_time

        try:
            telemetry_client.record_event(
                event_type="com.amazon.rum.deadline.agents.latency",
                event_details={
                    "latency": latency,
                    "agent_name": "farm_setup",
                    "usage_mode": "AGENT",
                },
            )

            telemetry_client.record_event(
                event_type="com.amazon.rum.deadline.agents.usage",
                event_details={
                    "agent_name": "farm_setup",
                    "is_success": is_success,
                    "error_type": error_type,
                    "usage_mode": "AGENT",
                },
            )
        except Exception as telemetry_error:
            logger.debug(f"Failed to record telemetry: {telemetry_error}")
