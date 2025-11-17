# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Rich console utilities for styled agent output.
Provides colored, markdown-formatted streaming output for each agent.
"""

from rich.console import Console
from rich.text import Text
import sys

# Agent-specific color scheme
AGENT_COLORS = {
    "orchestrator": "cyan",
    "classifier": "yellow",
    "job_troubleshooter": "green",
    "farm_setup": "blue",
    "job_attachments": "magenta",
    "default": "white",
}

# Create console instances for each agent
_consoles = {}


def get_agent_console(agent_name: str) -> Console:
    """
    Get or create a Rich console for a specific agent.

    Args:
        agent_name: Name of the agent (orchestrator, job_troubleshooter, etc.)

    Returns:
        Rich Console instance configured for the agent
    """
    if agent_name not in _consoles:
        _consoles[agent_name] = Console(
            file=sys.stdout,
            force_terminal=True,
            color_system="auto",
            highlight=False,  # Disable automatic syntax highlighting
        )
    return _consoles[agent_name]


def get_agent_color(agent_name: str) -> str:
    """
    Get the color associated with an agent.

    Args:
        agent_name: Name of the agent

    Returns:
        Color name for the agent
    """
    return AGENT_COLORS.get(agent_name, AGENT_COLORS["default"])


def print_agent_text(agent_name: str, text: str, end: str = "", flush: bool = True):
    """
    Print text with agent-specific color.

    Args:
        agent_name: Name of the agent
        text: Text to print
        end: String appended after the text (default: "")
        flush: Whether to flush the output buffer
    """
    console = get_agent_console(agent_name)
    color = get_agent_color(agent_name)

    styled_text = Text(text, style=color)
    console.print(styled_text, end=end)

    if flush:
        console.file.flush()


def stream_agent_text(agent_name: str, text: str):
    """
    Stream a text chunk with agent-specific color.

    Args:
        agent_name: Name of the agent for color coding
        text: Text chunk to stream
    """
    if text:
        print_agent_text(agent_name, text, end="", flush=True)
