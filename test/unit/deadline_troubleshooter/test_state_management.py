#!/usr/bin/env python3
"""
Test script to verify state management implementation.
"""

from strands import Agent, tool, ToolContext

# Mock tools to test state tracking
@tool(context=True)
def discover_resources(resource_type: str, tool_context: ToolContext) -> str:
    """Simulate discovering resources and tracking them in state."""
    
    # Simulate discovered resources
    mock_resources = {
        "sessions": ["session-abc123", "session-def456"],
        "tasks": ["task-xyz789-1", "task-uvw012-2"]
    }
    
    resources = mock_resources.get(resource_type, [])
    
    # Track in agent state
    state_key = f"discovered_{resource_type}"
    tool_context.agent.state.set(state_key, resources)
    
    return f"Discovered {len(resources)} {resource_type}: {', '.join(resources)}"


@tool(context=True)
def use_resource(resource_type: str, resource_id: str, tool_context: ToolContext) -> str:
    """Simulate using a resource and validating it against tracked state."""
    
    # Check if resource was discovered
    state_key = f"discovered_{resource_type}"
    discovered = tool_context.agent.state.get(state_key) or []
    
    if resource_id not in discovered:
        return (
            f"❌ ERROR: {resource_type} ID '{resource_id}' not found in discovered {resource_type}.\n"
            f"Available: {', '.join(discovered)}\n"
            f"You must call discover_resources first!"
        )
    
    return f"✓ Successfully used {resource_type} '{resource_id}'"


def test_state_management():
    """Test the state management pattern."""
    
    print("=" * 60)
    print("Testing Strands Agent State Management")
    print("=" * 60)
    
    # Create agent with initial state
    agent = Agent(
        system_prompt="You are a test agent that discovers and uses resources.",
        tools=[discover_resources, use_resource],
        state={
            "discovered_sessions": [],
            "discovered_tasks": []
        }
    )
    
    print("\n1. Testing resource discovery...")
    result1 = agent("Discover sessions")
    print(f"Result: {result1}")
    
    print("\n2. Testing valid resource usage...")
    result2 = agent("Use session session-abc123")
    print(f"Result: {result2}")
    
    print("\n3. Testing invalid resource usage (should fail)...")
    result3 = agent("Use session session-invalid999")
    print(f"Result: {result3}")
    
    print("\n4. Checking agent state...")
    print(f"Discovered sessions: {agent.state.get('discovered_sessions')}")
    print(f"Discovered tasks: {agent.state.get('discovered_tasks')}")
    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    test_state_management()
