# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
All the `deadline agents` commands.
"""

import sys
import click

from .._common import _apply_cli_options_to_config, _handle_error
from .._main import deadline as main


@main.group(name="agents")
@_handle_error
def cli_agents():
    """
    Commands to invoke specialized Deadline agents
    """


@cli_agents.command(name="diagnose")
@click.option("--profile", help="The AWS profile to use.")
@click.option("--farm-id", help="The farm ID.")
@click.option("--queue-id", help="The queue ID.")
@click.option("--job-id", help="The job ID to troubleshoot (optional for general troubleshooting).")
@click.option(
    "--job-template-bucket-arn", help="S3 bucket ARN to export job templates for diagnosis."
)
@click.option(
    "--model-id",
    help="Override the default model ID for all agents (e.g., anthropic.claude-3-5-sonnet-20240620-v1:0).",
)
@click.option(
    "--interactive/--no-interactive",
    default=True,
    help="Enable interactive mode for follow-up questions.",
)
@_handle_error
def agents_diagnose(
    profile, farm_id, queue_id, job_id, job_template_bucket_arn, model_id, interactive, **args
):
    """
    Diagnose issues with a Deadline Cloud job using AI troubleshooting.

    By default, runs in interactive mode allowing you to ask follow-up questions.
    Use --no-interactive for single-shot troubleshooting.

    If --job-id is not provided, starts in general troubleshooting mode where you can
    ask questions about Deadline Cloud or provide a job ID interactively.

    Use --model-id to override the default model for all agents. This is useful for
    testing different models or using newer model versions.

    Use --job-template-bucket-arn to provide an S3 bucket where the agent can store
    the current job template for diagnosis. To use this correctly, your role must have 
    read and write object permissions for the specified bucket.
    """
    try:
        from ...._agents import run_diagnostics
    except ImportError as e:
        click.echo(
            "Error: Agent dependencies not installed.\n"
            "Please install them with: pip install 'deadline[agents]'\n"
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
        **args,
    )

    # Extract values from config
    from ...config import config_file

    farm_id_value = config_file.get_setting("defaults.farm_id", config=config)
    queue_id_value = config_file.get_setting("defaults.queue_id", config=config)

    # Validate that if non-interactive mode is used, job_id must be provided
    if not interactive and not job_id:
        click.echo("Error: --job-id is required when using --no-interactive mode.", err=True)
        sys.exit(1)

    # Pass values and config to troubleshooter
    try:
        import asyncio

        # Run the async function
        result, orchestrator = asyncio.run(
            run_diagnostics(
                job_id=job_id,
                farm_id=farm_id_value,
                queue_id=queue_id_value,
                job_template_bucket_arn=job_template_bucket_arn,
                model_id_override=model_id,
                config=config,
            )
        )

        # Interactive mode
        if interactive:
            click.echo(
                "\n💬 Interactive mode enabled. Continue discussing this diagnosis with the agent or type 'exit' to quit."
            )

            while True:
                try:
                    # Get user input
                    user_input = click.prompt("You", type=str, prompt_suffix="> ")

                    # Check for exit commands
                    if user_input.lower() in ["exit", "quit", "q"]:
                        click.echo("Goodbye!")
                        break

                    # Send to orchestrator with streaming
                    click.echo("\n🤖 Agent: ")

                    # Stream the response in real-time using async
                    import asyncio

                    async def stream_interactive():
                        """Async function to handle interactive streaming."""
                        stream = orchestrator.stream_async(user_input)
                        async for event in stream:
                            # Events are dictionaries with a "data" key containing text chunks
                            if isinstance(event, dict) and "data" in event:
                                text_chunk = event["data"]
                                if text_chunk:
                                    click.echo(text_chunk, nl=False)

                    asyncio.run(stream_interactive())

                    click.echo()  # Empty line for spacing

                except (KeyboardInterrupt, EOFError):
                    click.echo("\nGoodbye!")
                    break
                except Exception as e:
                    click.echo(f"\nError: {e}", err=True)

    except Exception as e:
        click.echo(f"Error running diagnostics: {e}", err=True)
        sys.exit(1)
