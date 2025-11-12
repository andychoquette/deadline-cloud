"""
AWS Documentation tools for the AI troubleshooter.
Provides access to AWS service documentation for troubleshooting.
"""
from strands import tool
import logging
import boto3
from typing import Optional

logger = logging.getLogger(__name__)

# Check if boto3 is available
AWS_DOCS_AVAILABLE = True
try:
    import boto3
except ImportError:
    AWS_DOCS_AVAILABLE = False


@tool
def search_aws_docs(query: str, service: str = None, max_results: int = 5) -> str:
    """
    Search AWS documentation for troubleshooting information.
    
    This tool searches AWS service documentation to find relevant information
    about errors, configurations, and best practices.
    
    Args:
        query: Search query (e.g., "S3 access denied error", "VPC security group configuration")
        service: Optional AWS service to filter results (e.g., "s3", "ec2", "deadline")
        max_results: Maximum number of results to return (default: 5)
        
    Returns:
        String containing search results with documentation snippets
    """
    
    try:
        # For now, return a helpful message about AWS documentation
        # In a full implementation, this would integrate with AWS documentation API
        result = f"**AWS Documentation Search Results for: {query}**\n\n"
        
        if service:
            result += f"Service Filter: {service.upper()}\n\n"
        
        # Provide relevant documentation links based on common patterns
        if "deadline" in query.lower():
            result += "**AWS Deadline Cloud Documentation:**\n"
            result += "- Getting Started: https://docs.aws.amazon.com/deadline-cloud/latest/userguide/\n"
            result += "- Troubleshooting: https://docs.aws.amazon.com/deadline-cloud/latest/userguide/troubleshooting.html\n"
            result += "- API Reference: https://docs.aws.amazon.com/deadline-cloud/latest/APIReference/\n\n"
        
        if "s3" in query.lower() or "bucket" in query.lower():
            result += "**Amazon S3 Documentation:**\n"
            result += "- Troubleshooting: https://docs.aws.amazon.com/AmazonS3/latest/userguide/troubleshooting.html\n"
            result += "- Access Control: https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-overview.html\n\n"
        
        if "iam" in query.lower() or "permission" in query.lower():
            result += "**IAM Documentation:**\n"
            result += "- Troubleshooting: https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot.html\n"
            result += "- Policies: https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies.html\n\n"
        
        if "vpc" in query.lower() or "network" in query.lower():
            result += "**VPC Documentation:**\n"
            result += "- Troubleshooting: https://docs.aws.amazon.com/vpc/latest/userguide/vpc-troubleshooting.html\n"
            result += "- Security Groups: https://docs.aws.amazon.com/vpc/latest/userguide/VPC_SecurityGroups.html\n\n"
        
        result += "\n💡 For detailed troubleshooting, visit the AWS documentation links above.\n"
        
        return result
    
    except Exception as e:
        logger.error(f"Error searching AWS docs: {e}")
        return f"❌ Error searching AWS documentation: {str(e)}"


@tool
def get_aws_error_explanation(error_code: str, service: str = "deadline") -> str:
    """
    Get explanation and troubleshooting steps for AWS error codes.
    
    Args:
        error_code: AWS error code (e.g., "AccessDenied", "ResourceNotFoundException")
        service: AWS service name (default: "deadline")
        
    Returns:
        String containing error explanation and troubleshooting steps
    """
    
    # Common AWS error explanations
    error_explanations = {
        "AccessDenied": {
            "description": "The request was denied due to insufficient permissions.",
            "common_causes": [
                "IAM policy doesn't grant required permissions",
                "Resource-based policy blocks access",
                "Service Control Policy (SCP) restriction",
                "Session policy limitation",
            ],
            "troubleshooting": [
                "Check IAM policies attached to the user/role",
                "Verify resource-based policies (e.g., S3 bucket policy)",
                "Review CloudTrail logs for detailed error information",
                "Ensure the principal has the correct permissions for the action",
            ],
        },
        "ResourceNotFoundException": {
            "description": "The specified resource does not exist.",
            "common_causes": [
                "Resource ID is incorrect or misspelled",
                "Resource was deleted",
                "Resource is in a different region",
                "Resource is in a different account",
            ],
            "troubleshooting": [
                "Verify the resource ID is correct",
                "Check the AWS region",
                "Confirm the resource exists using list/describe operations",
                "Verify you're using the correct AWS account",
            ],
        },
        "ValidationException": {
            "description": "The request parameters failed validation.",
            "common_causes": [
                "Invalid parameter format",
                "Missing required parameters",
                "Parameter value out of allowed range",
                "Conflicting parameters",
            ],
            "troubleshooting": [
                "Review the API documentation for parameter requirements",
                "Check parameter formats and data types",
                "Verify all required parameters are provided",
                "Look for conflicting parameter combinations",
            ],
        },
        "ThrottlingException": {
            "description": "The request was throttled due to rate limiting.",
            "common_causes": [
                "Too many requests in a short time period",
                "Service quota exceeded",
                "Burst capacity exhausted",
            ],
            "troubleshooting": [
                "Implement exponential backoff and retry logic",
                "Request a service quota increase if needed",
                "Distribute requests over time",
                "Use batch operations where available",
            ],
        },
    }
    
    result = f"**AWS Error: {error_code}**\n\n"
    result += f"Service: {service.upper()}\n\n"
    
    if error_code in error_explanations:
        error_info = error_explanations[error_code]
        
        result += f"**Description:**\n{error_info['description']}\n\n"
        
        result += f"**Common Causes:**\n"
        for cause in error_info['common_causes']:
            result += f"- {cause}\n"
        result += "\n"
        
        result += f"**Troubleshooting Steps:**\n"
        for step in error_info['troubleshooting']:
            result += f"- {step}\n"
        result += "\n"
    else:
        result += f"No specific information available for error code: {error_code}\n\n"
        result += "**General Troubleshooting:**\n"
        result += "- Check AWS CloudTrail logs for detailed error information\n"
        result += "- Review the service documentation for this error code\n"
        result += "- Verify your IAM permissions and resource configurations\n\n"
    
    result += f"**Documentation:**\n"
    result += f"- AWS Error Codes: https://docs.aws.amazon.com/\n"
    result += f"- {service.capitalize()} API Reference: https://docs.aws.amazon.com/{service}/\n"
    
    return result


def get_aws_docs_tools():
    """
    Get all AWS documentation tools.
    
    Returns:
        List of AWS documentation tools
    """
    if not AWS_DOCS_AVAILABLE:
        logger.warning("boto3 not available - AWS docs tools disabled")
        return []
    
    return [
        search_aws_docs,
        get_aws_error_explanation,
    ]
