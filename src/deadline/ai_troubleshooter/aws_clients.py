"""
AWS client management for AI troubleshooter.
"""
from deadline.client.api import get_boto3_client


def get_client(service_name: str, use_deadline_credentials: bool = False):
    """
    Get a boto3 client for the specified service.
    
    Args:
        service_name: Name of the AWS service (e.g., 'deadline', 's3', 'cloudwatch')
        use_deadline_credentials: Whether to use Deadline Cloud credentials (default: False)
        
    Returns:
        boto3 client for the specified service
    """
    return get_boto3_client(service_name)
