# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Centralized model configuration for all agents.
Modify settings here to optimize performance across the entire system.
"""

from botocore.config import Config
from strands.models import BedrockModel

# AWS Configuration
AWS_REGION = "us-west-2"
BOTO_CONFIG = Config(
    connect_timeout=30,  # Reduced from 60s
    read_timeout=180,  # Reduced from 300s
    max_pool_connections=10,  # Limit connection pool size
)

# Guardrail Configuration
GUARDRAIL_CONFIG = {
    "orchestrator__not_used": {
        "guardrail_id": "b7cwreku3t0r",  # Changed from guardrail_identifier to guardrail_id
        "guardrail_version": "DRAFT",  # Use "DRAFT" or specific version number
    },
}

# Model IDs - Update these to use different models
MODEL_IDS = {
    "orchestrator": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "classifier": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "job_troubleshooter": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "iam_validator": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "farm_setup": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "job_attachments": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "kb_retriever": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "default": "anthropic.claude-3-5-sonnet-20240620-v1:0",
}

# Global model override - set via set_model_override()
_MODEL_ID_OVERRIDE = None

# Model Parameters - Tune these for performance
MODEL_PARAMS = {
    "orchestrator": {
        "streaming": True,
        "top_p": 0.9,
        "max_tokens": 2000,  # Concise responses
        "temperature": 0.5,  # Balanced between focused and conversational
    },
    "classifier": {
        "streaming": True,
        "top_p": 0.9,
        "max_tokens": 200,
        "temperature": 0.3,  # Lower temp for more consistent classification
    },
    "job_troubleshooter": {
        "streaming": True,
        "top_p": 0.9,
        "max_tokens": 5000,
        "temperature": 0.3,  # Lower temp for more focused analysis
    },
    "farm_setup": {
        "streaming": True,
        "top_p": 1,
        "max_tokens": 500,
        "temperature": 0.7,
    },
    "job_attachments": {
        "streaming": True,
        "top_p": 1,
        "max_tokens": 2000,
        "temperature": 0.7,
    },
    "default": {
        "streaming": True,
        "top_p": 1,
        "max_tokens": 2000,
        "temperature": 1,
    },
}


def set_model_override(model_id: str):
    """
    Set a global model ID override for all agents.

    Args:
        model_id: The model ID to use for all agents (e.g., "anthropic.claude-3-5-sonnet-20240620-v1:0")
    """
    global _MODEL_ID_OVERRIDE
    _MODEL_ID_OVERRIDE = model_id


def clear_model_override():
    """Clear the global model ID override."""
    global _MODEL_ID_OVERRIDE
    _MODEL_ID_OVERRIDE = None


def get_model(agent_name: str = "default", boto_session=None) -> BedrockModel:
    """
    Get a configured BedrockModel for a specific agent.

    Args:
        agent_name: Name of the agent (orchestrator, kb_retriever, etc.)
        boto_session: Optional boto3 session to use for the model

    Returns:
        Configured BedrockModel instance
    """
    # Use override if set, otherwise use configured model
    if _MODEL_ID_OVERRIDE:
        model_id = _MODEL_ID_OVERRIDE
    else:
        model_id = MODEL_IDS.get(agent_name, MODEL_IDS["default"])

    params = MODEL_PARAMS.get(agent_name, MODEL_PARAMS["default"])

    # Add guardrail configuration if available for this agent
    guardrail_config = GUARDRAIL_CONFIG.get(agent_name)
    if guardrail_config:
        params = {**params, **guardrail_config}

    model_kwargs = {"model_id": model_id, "boto_client_config": BOTO_CONFIG, **params}

    # Add boto_session if provided
    if boto_session:
        model_kwargs["boto_session"] = boto_session

    return BedrockModel(**model_kwargs)


# Helper functions to get models (respects overrides)
# Use these instead of direct model imports when you need override support
def get_orchestrator_model(boto_session=None):
    return get_model("orchestrator", boto_session=boto_session)


def get_classifier_model(boto_session=None):
    return get_model("classifier", boto_session=boto_session)


def get_job_troubleshooter_model(boto_session=None):
    return get_model("job_troubleshooter", boto_session=boto_session)


def get_iam_validator_model(boto_session=None):
    return get_model("iam_validator", boto_session=boto_session)


def get_farm_setup_model(boto_session=None):
    return get_model("farm_setup", boto_session=boto_session)


def get_job_attachments_model(boto_session=None):
    return get_model("job_attachments", boto_session=boto_session)


def get_kb_retriever_model(boto_session=None):
    return get_model("kb_retriever", boto_session=boto_session)


def get_default_model(boto_session=None):
    return get_model("default", boto_session=boto_session)


# Configuration Tips:
#
# Model Selection:
# - Claude 3.5 Sonnet: Best balance of speed and capability
# - Claude 3 Opus: Highest capability, slower and more expensive
# - Claude 3 Haiku: Fastest and cheapest, good for simple tasks
#
# Temperature:
# - 0.0-0.3: More focused and deterministic (good for retrieval, analysis)
# - 0.7-1.0: More creative and varied (good for conversation, troubleshooting)
#
# Max Tokens:
# - 1000-2000: Quick responses, simple queries
# - 2000-4000: Detailed analysis, complex troubleshooting
# - 4000+: Very detailed responses, may be slower
#
# Streaming:
# - True: Better UX, see responses as they're generated
# - False: Simpler to handle, wait for complete response
#
# Top P:
# - 0.9-1.0: More diverse responses
# - 0.5-0.8: More focused responses
