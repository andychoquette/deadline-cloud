# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Rich console utilities for styled agent output.
Provides colored, markdown-formatted streaming output for each agent.
"""

from rich.console import Console
from rich.markdown import Markdown
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


def print_agent_markdown(agent_name: str, markdown_text: str):
    """
    Print markdown-formatted text with agent-specific color.

    Args:
        agent_name: Name of the agent
        markdown_text: Markdown text to render
    """
    console = get_agent_console(agent_name)
    color = get_agent_color(agent_name)

    # Create markdown object
    md = Markdown(markdown_text, code_theme="monokai")

    # Print with agent color
    console.print(md, style=color)


def print_tool_invocation(tool_name: str, details: str = ""):
    """
    Print a tool invocation message in a subtle style.

    Args:
        tool_name: Name of the tool being invoked
        details: Optional details about the invocation
    """
    console = Console(file=sys.stderr, force_terminal=True)
    message = f"  → {tool_name}"
    if details:
        message += f": {details}"
    console.print(message, style="dim cyan")


class AgentStreamBuffer:
    """
    Buffer for accumulating streamed text with real-time colored output.
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.buffer = []
        self.color = get_agent_color(agent_name)
        self.console = get_agent_console(agent_name)

    def add_chunk(self, text: str):
        """Add a text chunk and print it immediately with agent color."""
        if text:
            self.buffer.append(text)
            # Print chunk immediately with color for real-time streaming
            print_agent_text(self.agent_name, text, end="", flush=True)

    def get_full_text(self) -> str:
        """Get the complete buffered text."""
        return "".join(self.buffer)

    def clear(self):
        """Clear the buffer."""
        self.buffer.clear()


def print_agent_separator():
    """Print a visual separator between agent outputs."""
    print()  # Just a newline for separation
