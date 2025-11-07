# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Classifier Agent - Determines the most probable source of Deadline Cloud issues.
"""

from strands import Agent, tool
from deadline._agents.bin.model_config import get_classifier_model

CLASSIFIER_SYSTEM_PROMPT = """
You are a specialized classifier for AWS Deadline Cloud troubleshooting.

Your role is to analyze the issue description and classify the most probable source of the problem.

## Classification Categories

Return the top TWO most probable issue sources, in order of confidence:

a) **Job execution errors**: Task failures, rendering errors, application crashes
b) **Resource (queue or fleet) configuration/scaling settings**: No fleet associated, insufficient capacity, auto-scaling misconfigured
c) **General service questions**: User may just want guidance on fixing an issue after the issue has been identified. 
d) **Service limits**: Quota exhaustion, throttling, resource limits reached
e) **Network configuration and/or security groups issues**: VPC misconfiguration, security group rules, connectivity problems
f) **Account permissions-related (IAM or SSO)**: Missing IAM roles, incorrect policies, SSO configuration issues

## Common Deadline Cloud Issues

The most frequent issues are:
- **Resource configuration**: Farm, queue, fleet, or related resources are not configured properly.
- **Job Submission**: Queue configuration, priority settings, dependency management
- **Fleet Management**: Worker scaling, instance types, spot vs on-demand
- **General service questions**: General questions about the Deadline Cloud service, terminology, or other information available in documentation
- **IAM Permission Problems**: Service roles, user permissions, cross-account access
- **Storage Integration**: S3 bucket permissions, file transfer issues, asset management
- **Network Configuration**: VPC settings, security groups, subnet configuration
- **Cost Optimization**: Resource utilization, scaling policies, instance selection

## Agents available for recommendation:
- job_troubleshooter_agent (RECOMMENDED for job/task failures - follows systematic workflow including CloudWatch log analysis)
- farm_setup_agent (for fleet sizing, scaling, and queue association issues)
- job_attachments_agent (for S3 bucket permission and job attachments issues)

## Your Response Format

**IMPORTANT** Provide your recommendation based on your classification as a simple JSON object with the EXACT tool names:
```json
{
  "recommended_agents": ["job_troubleshooter_agent", "farm_setup_agent"]
}
```
DO NOT add any additional text to your response, only this object. 
Use the EXACT tool names listed above (e.g., "job_troubleshooter_agent", not "Job Troubleshooter"). 

## Guidelines

- Analyze error messages, symptoms, and context carefully
- Return only high confidence classifications. 
- only recommend agents that have a high probability of solving the classification
- If there are no high confidence classifications, return a request for additional information.
- Consider the most common issues first
- Be decisive but acknowledge uncertainty when appropriate
- If no job id is provided, it is likely that it is a resource configuration issue
"""


@tool
def classifier_agent(query: str) -> str:
    """
    Classifies the most probable source of Deadline Cloud issues.

    Args:
        query: Description of the issue to classify

    Returns:
        JSON object with recommended agents
    """
    import logging
    import time
    from deadline.client.api._telemetry import get_deadline_cloud_library_telemetry_client

    logger = logging.getLogger(__name__)
    logger.info("Classifier agent invoked")

    # Get telemetry client
    telemetry_client = get_deadline_cloud_library_telemetry_client()

    # Record start time for latency tracking
    start_time = time.perf_counter_ns()
    is_success = False
    error_type = None

    try:
        # Get model with the same boto_session used by other components
        from deadline.client.api import get_boto3_session

        boto_session = get_boto3_session()

        # Suppress output - classifier is an internal routing tool
        # Users don't need to see the JSON response
        classifier = Agent(
            system_prompt=CLASSIFIER_SYSTEM_PROMPT,
            model=get_classifier_model(boto_session),  # Pass boto_session to use same credentials
            callback_handler=None,  # Suppress output
            tools=[],  # Classifier doesn't need tools, just analysis
        )

        response = classifier(query)
        is_success = True

        # Extract the response text from the result
        return str(response)
    except Exception as e:
        import traceback

        error_type = type(e).__name__
        error_details = traceback.format_exc()
        return f"Error in classifier: {str(e)}\n\nDetails:\n{error_details}"
    finally:
        # Record telemetry
        end_time = time.perf_counter_ns()
        latency = end_time - start_time

        try:
            telemetry_client.record_event(
                event_type="com.amazon.rum.deadline.agents.latency",
                event_details={
                    "latency": latency,
                    "agent_name": "classifier",
                    "usage_mode": "AGENT",
                },
            )

            telemetry_client.record_event(
                event_type="com.amazon.rum.deadline.agents.usage",
                event_details={
                    "agent_name": "classifier",
                    "is_success": is_success,
                    "error_type": error_type,
                    "usage_mode": "AGENT",
                },
            )
        except Exception as telemetry_error:
            logger.debug(f"Failed to record telemetry: {telemetry_error}")
