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
    read_timeout=180,    # Reduced from 300s
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
    "fleet_configuration": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "job_attachments": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "kb_retriever": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "default": "anthropic.claude-3-5-sonnet-20240620-v1:0",
}

# Model Parameters - Tune these for performance
MODEL_PARAMS = {
    "orchestrator": {
        "streaming": False,  # Disabled to avoid tool_result mismatch with non-streaming sub-agents
        "top_p": 0.9,
        "max_tokens": 800,  # Concise responses
        "temperature": 0.5,  # Balanced between focused and conversational
    },
    "classifier": {
        "streaming": False,
        "top_p": 0.9,
        "max_tokens": 200,  
        "temperature": 0.3,  # Lower temp for more consistent classification
    },
    "job_troubleshooter": {
        "streaming": False,  # Sub-agents should not stream when used as tools
        "top_p": 0.9,
        "max_tokens": 2000,  # Reduced from 4000 for faster analysis
        "temperature": 0.3,  # Lower temp for more focused analysis
    },
    "iam_validator": {
        "streaming": False,
        "top_p": 1,
        "max_tokens": 2000,
        "temperature": 0.7,
    },
    "fleet_configuration": {
        "streaming": False,
        "top_p": 1,
        "max_tokens": 500,
        "temperature": 0.7,
    },
    "job_attachments": {
        "streaming": False,
        "top_p": 1,
        "max_tokens": 2000,
        "temperature": 0.7,
    },
    "kb_retriever": {
        "streaming": False,
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

def get_model(agent_name: str = "default") -> BedrockModel:
    """
    Get a configured BedrockModel for a specific agent.
    
    Args:
        agent_name: Name of the agent (orchestrator, kb_retriever, etc.)
        
    Returns:
        Configured BedrockModel instance
    """
    model_id = MODEL_IDS.get(agent_name, MODEL_IDS["default"])
    params = MODEL_PARAMS.get(agent_name, MODEL_PARAMS["default"])
    
    # Add guardrail configuration if available for this agent
    guardrail_config = GUARDRAIL_CONFIG.get(agent_name)
    if guardrail_config:
        params = {**params, **guardrail_config}
    
    return BedrockModel(
        model_id=model_id,
        boto_client_config=BOTO_CONFIG,
        **params
    )


# Pre-configured models for easy import
orchestrator_model = get_model("orchestrator")
classifier_model = get_model("classifier")
job_troubleshooter_model = get_model("job_troubleshooter")
iam_validator_model = get_model("iam_validator")
fleet_configuration_model = get_model("fleet_configuration")
job_attachments_model = get_model("job_attachments")
kb_retriever_model = get_model("kb_retriever")
default_model = get_model("default")


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
