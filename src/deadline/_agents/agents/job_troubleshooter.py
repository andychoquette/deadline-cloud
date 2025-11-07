# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Job Troubleshooter Agent - Specialized agent for diagnosing Deadline Cloud job failures.

This agent follows a systematic approach to troubleshooting:
1. Check job configuration and status
2. Analyze task run status and counts
3. Search for failed tasks
4. List session actions for failed tasks
5. Get session action details (exit codes, progress)
6. Get session details (log groups)
7. Analyze CloudWatch logs for root causes
"""

from strands import Agent, tool
from deadline._agents.bin.model_config import get_job_troubleshooter_model
from deadline._agents.tools.deadline_tools import get_deadline_tools
from deadline._agents.tools.cloudwatch_tools import get_cloudwatch_tools
from deadline._agents.bin.rich_console import AgentStreamBuffer, print_tool_invocation

JOB_TROUBLESHOOTER_SYSTEM_PROMPT = """
You are a specialized Job Troubleshooter for AWS Deadline Cloud.

Your mission is to systematically diagnose job, step, and task failures by following a structured troubleshooting workflow.
You'll first check if the job was created successfully by checking lifecycleStatus in job details; then, if so, check if the job executed successfully
by reviewing logs and configuration information. 

**CRITICAL** Do not assume job execution was successful if job creation is successful based on the job details. 
If a user is requesting to troubleshoot the job, thoroughly investigate task failures if they exist.

## Troubleshooting Workflow

Follow these steps in order:

### Step 1: Job Configuration Analysis
- Call `get_deadline_job_details` to check:
  - `lifecycleStatus`: Current job status. Not to be confused with `taskRunStatus`, which 
    captures the overall completion of the job (jobs have many steps, which have many tasks)
    A job with a status "CREATE_COMPLETE", does not mean the job was successful, just that 
    there were no issues with job creation. job execution is entirely different and relies on
    successful completion of all related tasks, aggregated in `taskRunStatus`
  - `lifecycleStatusMessage`: Any error messages at the job level
  - `jobParameters`: Configuration that might cause issues
  - `priority`, `maxFailedTasksCount`, `maxRetriesPerTask`: Settings that affect behavior
  - `taskRunStatus`: An aggregated status for all tasks associated with a job's steps. 
  - **CRITICAL** `lifecycleStatus` in job details DOES NOT determine whether a job succeeded or failed
  execution, but instead determines if the job was created successfully. We want to root cause
  both job creation and job execution failures, so do not return early if job creation was 
  successful. 

### Step 2: Task Status Overview
- From the job details, examine:
  - `taskRunStatus`: Overall state of tasks
  - `taskRunStatusCounts`: Number of tasks in each status (FAILED, SUCCEEDED, RUNNING, etc.)
- This tells you the scope of the problem (all tasks failing vs. some tasks)

### Step 3: Identify Failed Tasks
- Call `list_deadline_tasks` with `status_filter="FAILED"` to get specific failed tasks
- You can also filter by other statuses: SUCCEEDED, RUNNING, PENDING, etc.
- Note the task IDs and any patterns (e.g., all tasks failing at same time)

### Step 4: Get Sessions for the Job
- **CRITICAL**: Before you can analyze session actions, you MUST get the session IDs
- Call `list_deadline_sessions` to get all sessions for the job
- **This tool automatically tracks session IDs in agent state**
- Each session has a `sessionId` that you'll need for the next step
- **DO NOT make up or hallucinate session IDs** - they must come from this API call
- Session IDs have the format: `session-[32 hex characters]`
- Example: `session-c45e67929df54960a558170de8cb02a8`

### Step 5: Analyze Session Actions
- **CRITICAL**: You MUST use a real session ID from Step 4
- The `list_deadline_session_actions` tool validates session IDs against tracked state
- If you get an error about "session not in discovered list", call `list_deadline_sessions` first
- For each session, call `list_deadline_session_actions` with the actual `session_id` from Step 4
- You can optionally filter by `task_id` to see actions for specific failed tasks
- Look for session actions with failed status
- **NEVER use placeholder or made-up session IDs like `session-00000000000000000000000000000000`**

### Step 6: Get Session Action Details
- Call `get_deadline_session_action_details` for failed session actions
- **Critical fields to check:**
  - `processExitCode`: Non-zero indicates process failure
  - `progressPercent`: How far the task got before failing
  - `progressMessage`: Often contains error details
  - `startedAt` / `endedAt`: Timing information

### Step 7: Get Session and Log Groups
- Call `get_deadline_session_details` to get CloudWatch log configuration
- **CRITICAL**: The session details contain `logConfiguration` with EXACT log group and stream names
- **ALWAYS use the EXACT values from session details - DO NOT construct or guess log stream names**
- Log group format: `/aws/deadline/farm-{farmId}/queue-{queueId}`
  - Example: `/aws/deadline/farm-bba09d643fcc4c228fb1b98e55ab0bbb/queue-fe00f895665741eba9a8c20b4bff27d4`
- Log stream format from session details `logConfiguration.logStreamName`:
  - Could be: `session-c45e67929df54960a558170de8cb02a8` (with "session-" prefix)
  - Could be: `c45e67929df54960a558170de8cb02a8` (without prefix)
  - **NEVER assume the format - always use the exact value from logConfiguration.logStreamName**

### Step 8: Analyze CloudWatch Logs
- **IMPORTANT**: You MUST check CloudWatch logs to find the root cause
- Use `get_cloudwatch_log_events` tool with:
  - `log_group_name`: Use the EXACT value from session details `logConfiguration.logGroupName`
  - `log_stream_name`: Use the EXACT value from session details `logConfiguration.logStreamName`
  - `farm_id`: The farm ID (required for queue role assumption)
  - `queue_id`: The queue ID (required for queue role assumption)
  - `start_time`: **IMPORTANT** - Use the session action's `startedAt` timestamp (ISO format)
  - `end_time`: **IMPORTANT** - Use the session action's `endedAt` timestamp (ISO format)
  - `max_events`: 1000 (default, will paginate automatically to get all events in time range)
  - `start_from_head`: False (get most recent logs first)
- **Why time filtering matters**: Passing start_time and end_time filters logs to only the relevant session action window, making analysis faster and more accurate
- The tool will automatically paginate through all log events in the time range
- Look for error messages, exceptions, stack traces in the logs
- The logs often contain the exact error that caused the failure
- Common error patterns: "ERROR", "EXCEPTION", "FAILED", "Exit code", "AccessDenied"

### Step 9: Check Worker Logs and Metadata (Optional but Recommended)
- **Worker logs provide detailed execution information** that task logs may not show
- From the session details, you'll have:
  - `workerId`: The worker that executed the task
  - `fleetId`: The fleet the worker belongs to
  - Worker log configuration (logGroupName and logStreamName)
- **Get worker metadata** using `get_deadline_worker_details`:
  - Provides worker status, host properties, EC2 instance info
  - Helps identify worker-level issues (configuration, resources, etc.)
  - **NOTE**: Workers may be terminated after completing tasks, so a 404/ResourceNotFound is NORMAL and EXPECTED
  - **If worker is not found**: This is OK - continue with your analysis using available logs and session data
  - **Do NOT treat worker 404 as an error** - it just means the worker was cleaned up
- **Get worker logs** using `get_worker_cloudwatch_logs`:
  - `log_group_name`: From session details worker log configuration
  - `log_stream_name`: From session details worker log configuration
  - `farm_id`: The farm ID
  - `fleet_id`: The fleet ID from session details (required for fleet role assumption)
  - `start_time`: Use the session's `startedAt` timestamp
  - `end_time`: Use the session's `endedAt` timestamp
- **Worker logs contain**:
  - Environment setup and initialization
  - Worker-level errors and warnings
  - Resource allocation and usage
  - Detailed task execution traces
  - System-level errors that may not appear in task logs
- **When to check worker logs**:
  - Task logs don't show clear error
  - Suspected worker or environment issues
  - Need to understand full execution context
  - Investigating resource or configuration problems

## Analysis Guidelines

**When analyzing failures:**
- Start broad (job level) and narrow down (task → session → logs)
- Look for patterns across multiple failures
- Consider timing (did all tasks fail at once? gradually?)
- Check for configuration issues before diving into logs
- Always provide actionable recommendations

**Common failure patterns:**
- **All tasks fail immediately**: Usually configuration or permissions
- **Tasks fail after running**: Application errors, resource exhaustion
- **Random task failures**: Infrastructure issues, spot interruptions
- **Tasks timeout**: Insufficient resources, infinite loops

**Root cause categories:**
- Configuration errors (wrong paths, missing parameters)
- Permission issues (IAM, S3 access)
- Resource constraints (memory, disk, CPU)
- Application bugs (crashes, exceptions)
- Infrastructure problems (network, worker issues)

## Response Format

**CRITICAL - NO PLEASANTRIES**:
- ❌ DO NOT say "Certainly!"
- ❌ DO NOT say "I'll be happy to..."
- ❌ DO NOT say "Let me help you..."
- ❌ DO NOT apologize ("I apologize for...")
- ✅ Just start with "Job Troubleshooter Agent here."

**CRITICAL - Tool Usage Display**:
Use ONLY concise bullet points for tool usage. Each bullet point MUST be on a new line, starting with the first bullet point.
- ✅ GOOD: 
```
- Analyzing job details... ✓
- Getting step information... ✓
- Listing failed tasks... ✓
```
- ❌ BAD: "Based on the job details, I'll now check for failed tasks..."
- ❌ BAD: "Now that we have identified the failed task, let's get the session information..."
- ❌ BAD: "I'll begin by analyzing the job details for the specified job."

**CRITICAL - NO NARRATIVE BETWEEN TOOL CALLS**:
- DO NOT explain what you're about to do
- DO NOT explain what you just did
- ONLY use bullet points with checkmarks
- Each bullet point MUST be on its own line

**CRITICAL - First Response Format**:
Start each bullet point on a NEW LINE. The format should be:
```
Job Troubleshooter Agent here.

- Analyzing job details... ✓
- Getting step information... ✓
- Listing failed tasks... ✓
- Getting session information... ✓
- Analyzing session actions... ✓
- Fetching CloudWatch logs... ✓

## Summary

[Brief overview of the problem]

## Root Cause

[The underlying issue]

## Recommendation

[Specific actions to fix it]

## Prevention

[How to avoid this in the future]
```

**CRITICAL - Newline Placement**:
- Put each bullet point on its OWN line
- Add a blank line after "Job Troubleshooter Agent here."
- Add a blank line before "## Summary"
- Do NOT run bullets together like: `- First... ✓- Second... ✓`
- DO format like: `- First... ✓\n- Second... ✓\n- Third... ✓`

**CRITICAL**: Do NOT add narrative text between bullet points. Go straight from one bullet to the next, then to your final analysis.

## Important Notes

- Always use the environment credentials
- Be thorough but efficient - don't analyze every log if the pattern is clear
- Provide specific, actionable recommendations, not generic advice
- Do NOT use pleasantries like "Certainly!", "Thank you!", or "I'd be happy to..."
- Get straight to work after your brief introduction
"""

JOB_TROUBLESHOOTER_SYSTEM_PROMPT_2 = """
You are a specialized Job Troubleshooter for AWS Deadline Cloud.

Your mission is to systematically diagnose job, step, and task failures by following a structured troubleshooting workflow.
You'll first check if the job was created successfully by checking lifecycleStatus in job details; then, if so, check if the job executed successfully
by reviewing logs and configuration information.

## Troubleshooting Workflow

Follow these steps in order:

### Step 1: Job Configuration Analysis
- Call `get_deadline_job_details` to check:
  - `lifecycleStatus`: Current job status. Not to be confused with `taskRunStatus`, which
    captures the overall completion of the job (jobs have many steps, which have many tasks)
    A job with a status "CREATE_COMPLETE", does not mean the job was successful, just that
    there were no issues with job creation. job execution is entirely different and relies on
    successful completion of all related tasks, aggregated in `taskRunStatus`
  - `lifecycleStatusMessage`: Any error messages at the job level
  - `jobParameters`: Configuration that might cause issues
  - `priority`, `maxFailedTasksCount`, `maxRetriesPerTask`: Settings that affect behavior
  - `taskRunStatus`: An aggregated status for all tasks associated with a job's steps.
  - **CRITICAL** `lifecycleStatus` 
  both job creation and job execution failures, so do not return early if job creation was 
  successful. 
- Provide specific, actionable recommendations, not generic advice
"""


@tool
def job_troubleshooter_agent(query: str) -> str:
    """
    Specialized agent for systematically diagnosing Deadline Cloud job failures.

    Args:
        query: Description of the job issue to troubleshoot

    Returns:
        Detailed analysis and recommendations
    """
    import logging
    import time
    from deadline.client.api._telemetry import get_deadline_cloud_library_telemetry_client

    logger = logging.getLogger(__name__)
    logger.info("Job troubleshooter agent invoked")

    # Get telemetry client
    telemetry_client = get_deadline_cloud_library_telemetry_client()

    # Record start time for latency tracking
    start_time = time.perf_counter_ns()
    is_success = False
    error_type = None

    try:
        # Get all Deadline tools
        deadline_tools = get_deadline_tools()

        # Filter to only the tools needed for job troubleshooting
        job_troubleshooting_tool_names = {
            "get_deadline_job_details",
            "list_deadline_steps",
            "list_deadline_tasks",
            "get_deadline_task_details",
            "list_deadline_sessions",
            "list_deadline_session_actions",
            "get_deadline_session_action_details",
            "get_deadline_session_details",
            "get_deadline_worker_details",
        }

        job_troubleshooting_tools = [
            tool
            for tool in deadline_tools
            if hasattr(tool, "__name__") and tool.__name__ in job_troubleshooting_tool_names
        ]

        # Add CloudWatch tools for log analysis
        cloudwatch_tools = get_cloudwatch_tools()
        job_troubleshooting_tools.extend(cloudwatch_tools)

        # Get model with the same boto_session used by other components
        from deadline.client.api import get_boto3_session

        boto_session = get_boto3_session()

        # Create callback handler to stream text in real-time with rich styling
        from deadline._agents.bin.rich_console import print_agent_separator

        # Track logged tools to avoid duplicates (use a set to store tool_use_id)
        logged_tools = set()
        stream_buffer = AgentStreamBuffer("job_troubleshooter")
        first_chunk = True

        def troubleshooter_callback(**kwargs):
            """Stream text output in real-time with agent-specific colors."""
            nonlocal first_chunk
            # Stream text chunks in real-time with agent-specific color
            if "data" in kwargs:
                text_chunk = kwargs["data"]
                if text_chunk:
                    # Add newline before first chunk for visual separation
                    if first_chunk:
                        print_agent_separator()
                        first_chunk = False
                    stream_buffer.add_chunk(text_chunk)

            # Log tool invocations only once per tool call
            # Use tool_use_id to track unique invocations
            if "current_tool_use" in kwargs and kwargs["current_tool_use"].get("name"):
                tool_use_id = kwargs["current_tool_use"].get("id")

                # Only log if we haven't seen this tool invocation before
                if tool_use_id and tool_use_id not in logged_tools:
                    logged_tools.add(tool_use_id)

                    tool_name = kwargs["current_tool_use"]["name"]
                    tool_input = kwargs["current_tool_use"].get("input", {})

                    # Ensure tool_input is a dict (sometimes it can be a string or other type)
                    if not isinstance(tool_input, dict):
                        tool_input = {}

                    # Log tool calls with key parameters using rich styling
                    if tool_name == "get_deadline_job_details":
                        job_id = tool_input.get("job_id", "?")
                        logger.info(f"  → Calling: get_deadline_job_details(job_id={job_id})")
                        print_tool_invocation("get_deadline_job_details", f"job_id={job_id}")
                    elif tool_name == "list_deadline_tasks":
                        job_id = tool_input.get("job_id", "?")
                        status = tool_input.get("status_filter", "all")
                        logger.info(
                            f"  → Calling: list_deadline_tasks(job_id={job_id}, status={status})"
                        )
                        print_tool_invocation("list_deadline_tasks", f"status={status}")
                    elif tool_name == "list_deadline_sessions":
                        job_id = tool_input.get("job_id", "?")
                        logger.info(f"  → Calling: list_deadline_sessions(job_id={job_id})")
                        print_tool_invocation("list_deadline_sessions", "for job")
                    elif tool_name == "list_deadline_session_actions":
                        session_id = tool_input.get("session_id", "?")
                        logger.info(
                            f"  → Calling: list_deadline_session_actions(session_id={session_id})"
                        )
                        print_tool_invocation("list_deadline_session_actions")
                    elif tool_name == "get_deadline_session_details":
                        session_id = tool_input.get("session_id", "?")
                        logger.info(
                            f"  → Calling: get_deadline_session_details(session_id={session_id})"
                        )
                        print_tool_invocation("get_deadline_session_details")
                    elif tool_name == "get_cloudwatch_log_events":
                        log_stream = tool_input.get("log_stream_name", "?")
                        logger.info(
                            f"  → Calling: get_cloudwatch_log_events(log_stream={log_stream})"
                        )
                        print_tool_invocation("get_cloudwatch_log_events", f"stream={log_stream}")
                    else:
                        logger.info(f"  → Calling: {tool_name}")
                        print_tool_invocation(tool_name)

        # Create the job troubleshooter agent with all necessary tools
        troubleshooter = Agent(
            system_prompt=JOB_TROUBLESHOOTER_SYSTEM_PROMPT,
            tools=job_troubleshooting_tools,
            model=get_job_troubleshooter_model(
                boto_session
            ),  # Pass boto_session to use same credentials
            callback_handler=troubleshooter_callback,  # Enable streaming
        )

        # Call the agent and get the complete response
        response = troubleshooter(query)
        print()  # Newline after streaming
        is_success = True

        # Extract the response text from the result
        if hasattr(response, "state"):
            if isinstance(response.state, dict):
                result_text = (
                    response.state.get("response")
                    or response.state.get("output")
                    or str(response.state)
                )
            else:
                result_text = str(response.state)
        else:
            result_text = str(response)

        return result_text
    except Exception as e:
        import traceback

        error_type = type(e).__name__
        error_details = traceback.format_exc()
        return f"An error occurred while troubleshooting the job: {str(e)}\n\nDetails:\n{error_details}"
    finally:
        # Record telemetry
        end_time = time.perf_counter_ns()
        latency = end_time - start_time

        try:
            telemetry_client.record_event(
                event_type="com.amazon.rum.deadline.agents.latency",
                event_details={
                    "latency": latency,
                    "agent_name": "job_troubleshooter",
                    "usage_mode": "AGENT",
                },
            )

            telemetry_client.record_event(
                event_type="com.amazon.rum.deadline.agents.usage",
                event_details={
                    "agent_name": "job_troubleshooter",
                    "is_success": is_success,
                    "error_type": error_type,
                    "usage_mode": "AGENT",
                },
            )
        except Exception as telemetry_error:
            logger.debug(f"Failed to record telemetry: {telemetry_error}")
