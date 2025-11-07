"""
Job Attachments Configuration Agent - Validates S3 bucket permissions for job attachments.
"""
import boto3
from deadline.ai_troubleshooter.aws_clients import get_client
from strands import Agent, tool
from deadline.ai_troubleshooter.model_config import job_attachments_model

JOB_ATTACHMENTS_AGENT_SYSTEM_PROMPT = """
You are a job attachments configuration specialist for AWS Deadline Cloud.

Your role is to validate S3 bucket permissions and configuration for Deadline Cloud job attachments.

## Key Checks

1. **Bucket Existence**: Verify the job attachments bucket exists
2. **Bucket Permissions**: Check bucket policy and ACLs
3. **IAM Permissions**: Verify user/role has necessary S3 permissions
4. **Bucket Configuration**:
   - Versioning enabled (recommended)
   - Encryption settings
   - Lifecycle policies
   - CORS configuration if needed

5. **Access Testing**: Attempt to list objects and check read/write access

## Required S3 Permissions

For job attachments, Deadline Cloud needs:
- s3:GetObject - Read files from bucket
- s3:PutObject - Upload files to bucket
- s3:ListBucket - List bucket contents
- s3:DeleteObject - Clean up temporary files (optional)
- s3:GetBucketLocation - Get bucket region

## Common Issues

- Bucket policy denying access
- Missing IAM permissions
- Bucket in different region than farm
- Encryption key access issues (if using KMS)
- Bucket versioning causing issues

## Your Response

Provide:
- Bucket configuration assessment
- Permission validation results
- Identified access issues
- Recommendations for fixes
"""


@tool
def check_s3_bucket_exists(bucket_name: str) -> str:
    """
    Check if an S3 bucket exists and get basic information.
    
    Args:
        bucket_name: Name of the S3 bucket
        
    Returns:
        Bucket existence and basic configuration
    """
    try:
        s3 = get_client('s3')
        
        # Check if bucket exists by getting its location
        location = s3.get_bucket_location(Bucket=bucket_name)
        
        result = f"✓ Bucket exists: {bucket_name}\n"
        result += f"Region: {location['LocationConstraint'] or 'us-east-1'}\n"
        
        return result
        
    except s3.exceptions.NoSuchBucket:
        return f"❌ Bucket does not exist: {bucket_name}"
    except Exception as e:
        return f"❌ Error checking bucket: {str(e)}"


@tool
def get_bucket_policy(bucket_name: str) -> str:
    """
    Get the bucket policy for an S3 bucket.
    
    Args:
        bucket_name: Name of the S3 bucket
        
    Returns:
        Bucket policy JSON or indication if no policy exists
    """
    try:
        s3 = get_client('s3')
        
        response = s3.get_bucket_policy(Bucket=bucket_name)
        
        result = f"Bucket Policy for {bucket_name}:\n\n"
        result += response['Policy']
        
        return result
        
    except s3.exceptions.NoSuchBucket:
        return f"❌ Bucket does not exist: {bucket_name}"
    except Exception as e:
        if 'NoSuchBucketPolicy' in str(e):
            return f"No bucket policy configured for {bucket_name}"
        return f"❌ Error getting bucket policy: {str(e)}"


@tool
def check_bucket_permissions(bucket_name: str) -> str:
    """
    Test actual access to the bucket by attempting common operations.
    
    Args:
        bucket_name: Name of the S3 bucket
        
    Returns:
        Results of permission tests
    """
    try:
        s3 = get_client('s3')
        
        result = f"Testing permissions for bucket: {bucket_name}\n\n"
        
        # Test ListBucket
        try:
            s3.list_objects_v2(Bucket=bucket_name, MaxKeys=1)
            result += "✓ ListBucket: ALLOWED\n"
        except Exception as e:
            result += f"✗ ListBucket: DENIED - {str(e)}\n"
        
        # Test GetObject (try to read a test object)
        try:
            # This will fail if object doesn't exist, but permission error is different
            s3.head_object(Bucket=bucket_name, Key='test-permission-check')
            result += "✓ GetObject: ALLOWED\n"
        except Exception as e:
            if '404' in str(e) or 'Not Found' in str(e):
                result += "✓ GetObject: ALLOWED (no test object found, but permission granted)\n"
            elif '403' in str(e) or 'Forbidden' in str(e):
                result += f"✗ GetObject: DENIED - {str(e)}\n"
            else:
                result += f"? GetObject: UNKNOWN - {str(e)}\n"
        
        # Test PutObject (we won't actually write, just check ACL)
        try:
            s3.get_bucket_acl(Bucket=bucket_name)
            result += "✓ GetBucketAcl: ALLOWED\n"
        except Exception as e:
            result += f"✗ GetBucketAcl: DENIED - {str(e)}\n"
        
        return result
        
    except Exception as e:
        return f"❌ Error testing bucket permissions: {str(e)}"


@tool
def get_bucket_encryption(bucket_name: str) -> str:
    """
    Get bucket encryption configuration.
    
    Args:
        bucket_name: Name of the S3 bucket
        
    Returns:
        Bucket encryption settings
    """
    try:
        s3 = get_client('s3')
        
        response = s3.get_bucket_encryption(Bucket=bucket_name)
        
        result = f"Encryption for {bucket_name}:\n\n"
        
        for rule in response['ServerSideEncryptionConfiguration']['Rules']:
            sse = rule['ApplyServerSideEncryptionByDefault']
            result += f"Algorithm: {sse['SSEAlgorithm']}\n"
            
            if 'KMSMasterKeyID' in sse:
                result += f"KMS Key: {sse['KMSMasterKeyID']}\n"
        
        return result
        
    except Exception as e:
        if 'ServerSideEncryptionConfigurationNotFoundError' in str(e):
            return f"No encryption configured for {bucket_name}"
        return f"❌ Error getting bucket encryption: {str(e)}"


@tool
def get_bucket_versioning(bucket_name: str) -> str:
    """
    Get bucket versioning configuration.
    
    Args:
        bucket_name: Name of the S3 bucket
        
    Returns:
        Bucket versioning status
    """
    try:
        s3 = get_client('s3')
        
        response = s3.get_bucket_versioning(Bucket=bucket_name)
        
        status = response.get('Status', 'Disabled')
        mfa_delete = response.get('MFADelete', 'Disabled')
        
        result = f"Versioning for {bucket_name}:\n"
        result += f"Status: {status}\n"
        result += f"MFA Delete: {mfa_delete}\n"
        
        return result
        
    except Exception as e:
        return f"❌ Error getting bucket versioning: {str(e)}"


@tool
def list_bucket_objects(bucket_name: str, prefix: str = "", max_keys: int = 10) -> str:
    """
    List objects in the bucket (useful for verifying access and content).
    
    Args:
        bucket_name: Name of the S3 bucket
        prefix: Optional prefix to filter objects
        max_keys: Maximum number of objects to list (default: 10)
        
    Returns:
        List of objects in the bucket
    """
    try:
        s3 = get_client('s3')
        
        response = s3.list_objects_v2(
            Bucket=bucket_name,
            Prefix=prefix,
            MaxKeys=max_keys
        )
        
        if 'Contents' not in response:
            return f"No objects found in {bucket_name} with prefix '{prefix}'"
        
        result = f"Objects in {bucket_name} (showing up to {max_keys}):\n\n"
        
        for obj in response['Contents']:
            result += f"- {obj['Key']}\n"
            result += f"  Size: {obj['Size']} bytes\n"
            result += f"  Last Modified: {obj['LastModified']}\n\n"
        
        if response.get('IsTruncated', False):
            result += f"\n(More objects available, showing first {max_keys})\n"
        
        return result
        
    except Exception as e:
        return f"❌ Error listing bucket objects: {str(e)}"

@tool
def job_attachments_agent(query: str) -> str:
    """
    Validates S3 bucket configuration and permissions for job attachments.
    
    Args:
        query: Description of the job attachments issue to investigate
        
    Returns:
        Job attachments assessment and recommendations
    """
    try:
        attachments_agent = Agent(
            system_prompt=JOB_ATTACHMENTS_AGENT_SYSTEM_PROMPT,
            model=job_attachments_model,  # Using centralized model config
            tools=[
                check_s3_bucket_exists,
                get_bucket_policy,
                check_bucket_permissions,
                get_bucket_encryption,
                get_bucket_versioning,
                list_bucket_objects,
            ],
        )

        response = attachments_agent(query)
        
        return str(response)
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return f"❌ Error in job attachments agent: {str(e)}\n\nDetails:\n{error_details}"
