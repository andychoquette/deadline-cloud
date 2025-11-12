"""
Fleet Configuration Agent - Validates Deadline Cloud fleet configuration and identifies common issues.
"""
import boto3
from deadline.ai_troubleshooter.aws_clients import get_client
from strands import Agent, tool
from deadline.ai_troubleshooter.model_config import resource_configuration_model

RESOURCE_CONFIGURATION_AGENT_SYSTEM_PROMPT = """
You are a resource configuration specialist for AWS Deadline Cloud.

Your role is to validate fleet and queue configurations and identify common issues that prevent jobs from running, in order of confidence (high, medium, low).

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

Provide:
- Very concise fleet configuration assessment
- Only return high confidence identified misconfigurations
- Specific recommendations for fixes for the high-confidence misconfigurations
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
        deadline = get_client('deadline', use_deadline_credentials=True)
        
        response = deadline.get_fleet(
            farmId=farm_id,
            fleetId=fleet_id
        )
        
        result = f"Fleet: {fleet_id}\n"
        result += f"Display Name: {response.get('displayName', 'N/A')}\n"
        result += f"Status: {response['status']}\n"
        result += f"Farm: {farm_id}\n\n"
        
        # Configuration details
        config = response.get('configuration', {})
        
        if 'customerManaged' in config:
            cm = config['customerManaged']
            result += "Configuration Type: Customer Managed\n"
            result += f"Mode: {cm.get('mode', 'N/A')}\n"
            
            if 'workerCapabilities' in cm:
                wc = cm['workerCapabilities']
                result += f"\nWorker Capabilities:\n"
                result += f"  vCPU: {wc.get('vCpuCount', {})}\n"
                result += f"  Memory: {wc.get('memoryMiB', {})}\n"
                result += f"  OS Family: {wc.get('osFamily', 'N/A')}\n"
                result += f"  CPU Architecture: {wc.get('cpuArchitectureType', 'N/A')}\n"
        
        elif 'serviceManagedEc2' in config:
            sme = config['serviceManagedEc2']
            result += "Configuration Type: Service Managed EC2\n"
            result += f"Instance Market: {sme.get('instanceMarketOptions', {}).get('type', 'N/A')}\n"
            
            if 'instanceCapabilities' in sme:
                ic = sme['instanceCapabilities']
                result += f"\nInstance Capabilities:\n"
                result += f"  vCPU: {ic.get('vCpuCount', {})}\n"
                result += f"  Memory: {ic.get('memoryMiB', {})}\n"
                result += f"  OS Family: {ic.get('osFamily', 'N/A')}\n"
                result += f"  CPU Architecture: {ic.get('cpuArchitectureType', 'N/A')}\n"
                
                if 'allowedInstanceTypes' in ic:
                    result += f"  Allowed Instance Types: {', '.join(ic['allowedInstanceTypes'])}\n"
        
        # Capacity status
        result += f"\nMin Worker Count: {response.get('minWorkerCount', 0)}\n"
        result += f"Max Worker Count: {response.get('maxWorkerCount', 0)}\n"
        result += f"Worker Count: {response.get('workerCount', 0)}\n"
        
        # Auto-scaling
        if 'autoScalingStatus' in response:
            result += f"\nAuto-Scaling Status: {response['autoScalingStatus'].get('status', 'N/A')}\n"
        
        return result
        
    except Exception as e:
        return f"❌ Error getting fleet details: {e}"


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
        deadline = get_client('deadline', use_deadline_credentials=True)
        
        response = deadline.list_queue_fleet_associations(
            farmId=farm_id,
            fleetId=fleet_id
        )
        
        associations = response.get('queueFleetAssociations', [])
        
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
        deadline = get_client('deadline', use_deadline_credentials=True)
        
        response = deadline.list_workers(
            farmId=farm_id,
            fleetId=fleet_id
        )
        
        workers = response.get('workers', [])
        
        if not workers:
            return f"No workers currently running in fleet {fleet_id}\n\nCheck if:\n- Min worker count is > 0\n- Auto-scaling is configured\n- Fleet has capacity to launch instances"
        
        result = f"Workers in fleet {fleet_id}:\n\n"
        
        status_counts = {}
        for worker in workers:
            status = worker['status']
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
        deadline = get_client('deadline', use_deadline_credentials=True)
        
        # Get fleet details
        fleet = deadline.get_fleet(farmId=farm_id, fleetId=fleet_id)
        
        issues = []
        warnings = []
        
        # Check status
        if fleet['status'] != 'ACTIVE':
            issues.append(f"Fleet status is {fleet['status']}, not ACTIVE")
        
        # Check capacity
        min_workers = fleet.get('minWorkerCount', 0)
        max_workers = fleet.get('maxWorkerCount', 0)
        
        if min_workers == 0 and max_workers == 0:
            issues.append("Both min and max worker counts are 0 - fleet cannot launch workers")
        elif min_workers == 0:
            warnings.append("Min worker count is 0 - fleet relies entirely on auto-scaling")
        
        if max_workers < min_workers:
            issues.append(f"Max workers ({max_workers}) is less than min workers ({min_workers})")
        
        # Check queue associations
        assocs = deadline.list_queue_fleet_associations(
            farmId=farm_id,
            fleetId=fleet_id
        )
        
        if not assocs.get('queueFleetAssociations'):
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
def resource_configuration_agent(query: str) -> str:
    """
    Validates fleet configuration and identifies common issues.
    
    Args:
        query: Description of the fleet issue to investigate
        
    Returns:
        Fleet configuration assessment and recommendations
    """
    try:
        fleet_agent = Agent(
            system_prompt=RESOURCE_CONFIGURATION_AGENT_SYSTEM_PROMPT,
            model=resource_configuration_model,  # Using centralized model config
            tools=[
                get_fleet_details,
                list_fleet_queues,
                check_fleet_workers,
                validate_fleet_configuration,
            ],
        )

        response = fleet_agent(query)
        
        return str(response)
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return f"❌ Error in fleet configuration agent: {str(e)}\n\nDetails:\n{error_details}"


