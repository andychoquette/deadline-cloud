# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
All the `deadline troubleshoot` commands.
"""

import sys
import click

from .._common import _apply_cli_options_to_config, _handle_error
from .._main import deadline as main


@main.group(name="troubleshoot")
@_handle_error
def cli_troubleshoot():
    """
    Commands to troubleshoot Deadline Cloud jobs using AI.
    """


@cli_troubleshoot.command(name="diagnose")
@click.option("--profile", help="The AWS profile to use.")
@click.option("--farm-id", help="The farm ID.")
@click.option("--queue-id", help="The queue ID.")
@click.option("--job-id", required=True, help="The job ID to troubleshoot.")
@click.option("--interactive/--no-interactive", default=True, help="Enable interactive mode for follow-up questions.")
@_handle_error
def troubleshoot_diagnose(profile, farm_id, queue_id, job_id, interactive, **args):
    """
    Diagnose issues with a Deadline Cloud job using AI troubleshooting.
    
    By default, runs in interactive mode allowing you to ask follow-up questions.
    Use --no-interactive for single-shot troubleshooting.
    """
    try:
        from ....ai_troubleshooter import run_diagnostics
    except ImportError as e:
        click.echo(
            "Error: Troubleshooter dependencies not installed.\n"
            "Please install them with: pip install 'deadline[troubleshooter]'\n"
            f"Details: {e}",
            err=True,
        )
        sys.exit(1)
    
    # Get config with CLI options applied
    config = _apply_cli_options_to_config(
        required_options={"farm_id", "queue_id"},
        profile=profile,
        farm_id=farm_id,
        queue_id=queue_id,
        **args
    )
    
    # Extract values from config
    from ...config import config_file
    farm_id_value = config_file.get_setting("defaults.farm_id", config=config)
    queue_id_value = config_file.get_setting("defaults.queue_id", config=config)
    
    # Pass values and config to troubleshooter
    try:
        result, orchestrator = run_diagnostics(
            job_id=job_id,
            farm_id=farm_id_value,
            queue_id=queue_id_value,
            config=config
        )
        
        # Display initial result
        click.echo("\n" + "=" * 80)
        click.echo("TROUBLESHOOTING RESULTS")
        click.echo("=" * 80)
        click.echo(result)
        click.echo("=" * 80)
        
        # Interactive mode
        if interactive:
            click.echo("\n💬 Interactive mode enabled. Ask follow-up questions or type 'exit' to quit.")
            click.echo("   Examples: 'What caused this error?', 'How can I prevent this?', 'Show me the logs'\n")
            
            while True:
                try:
                    # Get user input
                    user_input = click.prompt("You", type=str, prompt_suffix="> ")
                    
                    # Check for exit commands
                    if user_input.lower() in ['exit', 'quit', 'q']:
                        click.echo("Goodbye!")
                        break
                    
                    # Send to orchestrator
                    click.echo("\n🤖 Agent: ")
                    response = orchestrator(user_input)
                    
                    # Extract and display response
                    response_text = ""
                    if hasattr(response, 'message'):
                        message = response.message
                        if isinstance(message, dict) and 'content' in message:
                            content = message['content']
                            if isinstance(content, list):
                                text_parts = []
                                for block in content:
                                    if isinstance(block, dict) and 'text' in block:
                                        text_parts.append(block['text'])
                                response_text = '\n'.join(text_parts)
                            elif isinstance(content, str):
                                response_text = content
                        elif isinstance(message, str):
                            response_text = message
                    
                    if not response_text:
                        response_text = str(response)
                    
                    click.echo(response_text)
                    click.echo()  # Empty line for spacing
                    
                except (KeyboardInterrupt, EOFError):
                    click.echo("\nGoodbye!")
                    break
                except Exception as e:
                    click.echo(f"\nError: {e}", err=True)
                    
    except Exception as e:
        click.echo(f"Error running diagnostics: {e}", err=True)
        sys.exit(1)
