"""
Job Attachments Configuration Agent - Validates S3 bucket permissions for job attachments.
"""
import boto3
from deadline.ai_troubleshooter.aws_clients import get_client
from deadline.ai_troubleshooter.tools.deadline_tools import get_queue_role_credentials, get_queue_details
from strands import Agent, tool
from deadline.ai_troubleshooter.model_config import job_attachments_model
import logging

logger = logging.getLogger(__name__)

JOB_ATTACHMENTS_AGENT_SYSTEM_PROMPT = """
You are a job attachments configuration specialist for AWS Deadline Cloud.

Your role is to validate S3 bucket permissions and configuration for Deadline Cloud job attachments.

**CRITICAL - QUEUE ROLE CREDENTIALS**:
When you receive farm_id and queue_id in the context, you MUST pass them to EVERY S3 tool call.

Example tool calls:
- check_s3_bucket_exists(bucket_name="my-bucket", farm_id="farm-abc", queue_id="queue-xyz")
- list_bucket_objects(bucket_name="my-bucket", farm_id="farm-abc", queue_id="queue-xyz")
- check_bucket_permissions(bucket_name="my-bucket", farm_id="farm-abc", queue_id="queue-xyz")

DO NOT call S3 tools without farm_id and queue_id if they were provided in the context.
This ensures you're testing with the queue role credentials, not expired user credentials.

## Workflow

**STEP 1: Get Job Attachments Bucket Information**
- ALWAYS start by calling `get_queue_details(farm_id, queue_id)` to retrieve the queue configuration
- Extract the S3 bucket name from `jobAttachmentSettings.s3BucketName`
- Extract the root prefix from `jobAttachmentSettings.rootPrefix`
- This tells you exactly which bucket to check

**STEP 2: Validate Bucket Access**
- Use the bucket name from Step 1 to check S3 permissions
- Always pass farm_id and queue_id to S3 tools to use queue role credentials

## Key Checks

1. **Queue Configuration**: Get job attachments settings from queue details (REQUIRED FIRST STEP)
2. **Bucket Existence**: Verify the job attachments bucket exists
3. **Bucket Permissions**: Check bucket policy and ACLs
4. **IAM Permissions**: Verify queue role has necessary S3 permissions
5. **Bucket Configuration**:
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


def get_s3_client_with_queue_role(farm_id: str = None, queue_id: str = None):
    """
    Get an S3 client, optionally using queue role credentials.
    
    Args:
        farm_id: Optional farm ID to assume queue role
        queue_id: Optional queue ID to assume queue role
        
    Returns:
        boto3 S3 client
    """
    if farm_id and queue_id:
        logger.info("="*80)
        logger.info(f"🔑 USING QUEUE ROLE CREDENTIALS")
        logger.info(f"   Farm ID: {farm_id}")
        logger.info(f"   Queue ID: {queue_id}")
        logger.info("="*80)
        
        creds = get_queue_role_credentials(farm_id, queue_id)
        
        if creds:
            logger.info("✅ Successfully obtained queue role credentials for S3 access")
            session = boto3.Session(
                aws_access_key_id=creds['access_key_id'],
                aws_secret_access_key=creds['secret_access_key'],
                aws_session_token=creds['session_token']
            )
            return session.client('s3')
        else:
            logger.error("❌ Failed to get queue role credentials, falling back to default credentials")
    else:
        logger.warning("⚠️  No farm_id/queue_id provided - using default credentials (may be expired!)")
    
    # Fall back to default credentials
    return get_client('s3')


@tool
def check_s3_bucket_exists(bucket_name: str, farm_id: str = None, queue_id: str = None) -> str:
    """
    Check if an S3 bucket exists and get basic information.
    
    **CRITICAL**: You MUST provide farm_id and queue_id to use queue role credentials.
    Without these, the tool will use expired user credentials and fail.
    
    Args:
        bucket_name: Name of the S3 bucket
        farm_id: Farm ID to use queue role credentials (REQUIRED for proper access)
        queue_id: Queue ID to use queue role credentials (REQUIRED for proper access)
        
    Returns:
        Bucket existence and basic configuration
    """
    if not farm_id or not queue_id:
        return (
            "❌ ERROR: farm_id and queue_id are REQUIRED for this tool.\n"
            "You must provide both parameters to use queue role credentials.\n"
            "Example: check_s3_bucket_exists(bucket_name='my-bucket', farm_id='farm-abc', queue_id='queue-xyz')"
        )
    
    try:
        s3 = get_s3_client_with_queue_role(farm_id, queue_id)
        
        # Check if bucket exists by getting its location
        location = s3.get_bucket_location(Bucket=bucket_name)
        
        result = f"✓ Bucket exists: {bucket_name}\n"
        result += f"Region: {location['LocationConstraint'] or 'us-east-1'}\n"
        
        return result
        
    except s3.exceptions.NoSuchBucket:
        return f"❌ Bucket does not exist: {bucket_name}"
    except Exception as e:
        error_str = str(e)
        result = f"❌ Error checking bucket: {error_str}\n\n"
        
        # Provide specific guidance for common errors
        if 'AccessDenied' in error_str or '403' in error_str:
            result += "**Permission Error**: The queue role does not have permission to access this bucket.\n\n"
            result += "**Required Permission**: s3:GetBucketLocation\n\n"
            result += "**Solution**: Update the queue role IAM policy to include:\n"
            result += "```json\n"
            result += "{\n"
            result += '  "Effect": "Allow",\n'
            result += '  "Action": ["s3:GetBucketLocation"],\n'
            result += f'  "Resource": "arn:aws:s3:::{bucket_name}"\n'
            result += "}\n"
            result += "```\n"
        elif 'ExpiredToken' in error_str:
            result += "**Credential Error**: The queue role credentials have expired.\n"
            result += "This should not happen - please report this issue.\n"
        
        return result


@tool
def get_bucket_policy(bucket_name: str, farm_id: str = None, queue_id: str = None) -> str:
    """
    Get the bucket policy for an S3 bucket.
    
    **CRITICAL**: You MUST provide farm_id and queue_id to use queue role credentials.
    Without these, the tool will use expired user credentials and fail.
    
    Args:
        bucket_name: Name of the S3 bucket
        farm_id: Farm ID to use queue role credentials (REQUIRED for proper access)
        queue_id: Queue ID to use queue role credentials (REQUIRED for proper access)
        
    Returns:
        Bucket policy JSON or indication if no policy exists
    """
    if not farm_id or not queue_id:
        return (
            "❌ ERROR: farm_id and queue_id are REQUIRED for this tool.\n"
            "You must provide both parameters to use queue role credentials.\n"
            "Example: get_bucket_policy(bucket_name='my-bucket', farm_id='farm-abc', queue_id='queue-xyz')"
        )
    
    try:
        s3 = get_s3_client_with_queue_role(farm_id, queue_id)
        
        response = s3.get_bucket_policy(Bucket=bucket_name)
        
        result = f"Bucket Policy for {bucket_name}:\n\n"
        result += response['Policy']
        
        return result
        
    except s3.exceptions.NoSuchBucket:
        return f"❌ Bucket does not exist: {bucket_name}"
    except Exception as e:
        error_str = str(e)
        
        if 'NoSuchBucketPolicy' in error_str:
            return f"No bucket policy configured for {bucket_name}"
        
        result = f"❌ Error getting bucket policy: {error_str}\n\n"
        
        if 'AccessDenied' in error_str or '403' in error_str:
            result += "**Permission Error**: The queue role does not have permission to read the bucket policy.\n\n"
            result += "**Required Permission**: s3:GetBucketPolicy\n\n"
            result += "**Solution**: Update the queue role IAM policy to include:\n"
            result += "```json\n"
            result += "{\n"
            result += '  "Effect": "Allow",\n'
            result += '  "Action": ["s3:GetBucketPolicy"],\n'
            result += f'  "Resource": "arn:aws:s3:::{bucket_name}"\n'
            result += "}\n"
            result += "```\n"
        
        return result


@tool
def check_bucket_permissions(bucket_name: str, farm_id: str = None, queue_id: str = None) -> str:
    """
    Test actual access to the bucket by attempting common operations.
    
    **CRITICAL**: You MUST provide farm_id and queue_id to use queue role credentials.
    Without these, the tool will use expired user credentials and fail.
    
    Args:
        bucket_name: Name of the S3 bucket
        farm_id: Farm ID to use queue role credentials (REQUIRED for proper access)
        queue_id: Queue ID to use queue role credentials (REQUIRED for proper access)
        
    Returns:
        Results of permission tests
    """
    if not farm_id or not queue_id:
        return (
            "❌ ERROR: farm_id and queue_id are REQUIRED for this tool.\n"
            "You must provide both parameters to use queue role credentials.\n"
            "Example: check_bucket_permissions(bucket_name='my-bucket', farm_id='farm-abc', queue_id='queue-xyz')"
        )
    
    try:
        s3 = get_s3_client_with_queue_role(farm_id, queue_id)
        
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
        error_str = str(e)
        result = f"❌ Error testing bucket permissions: {error_str}\n\n"
        
        if 'AccessDenied' in error_str or '403' in error_str:
            result += "**Permission Error**: The queue role does not have permission to test bucket access.\n\n"
            result += "**Required Permissions**: s3:ListBucket, s3:GetObject, s3:GetBucketAcl\n\n"
            result += "**Solution**: Update the queue role IAM policy to include:\n"
            result += "```json\n"
            result += "{\n"
            result += '  "Effect": "Allow",\n'
            result += '  "Action": [\n'
            result += '    "s3:ListBucket",\n'
            result += '    "s3:GetObject",\n'
            result += '    "s3:GetBucketAcl"\n'
            result += '  ],\n'
            result += f'  "Resource": [\n'
            result += f'    "arn:aws:s3:::{bucket_name}",\n'
            result += f'    "arn:aws:s3:::{bucket_name}/*"\n'
            result += '  ]\n'
            result += "}\n"
            result += "```\n"
        
        return result


@tool
def get_bucket_encryption(bucket_name: str, farm_id: str = None, queue_id: str = None) -> str:
    """
    Get bucket encryption configuration.
    
    **CRITICAL**: You MUST provide farm_id and queue_id to use queue role credentials.
    Without these, the tool will use expired user credentials and fail.
    
    Args:
        bucket_name: Name of the S3 bucket
        farm_id: Farm ID to use queue role credentials (REQUIRED for proper access)
        queue_id: Queue ID to use queue role credentials (REQUIRED for proper access)
        
    Returns:
        Bucket encryption settings
    """
    if not farm_id or not queue_id:
        return (
            "❌ ERROR: farm_id and queue_id are REQUIRED for this tool.\n"
            "You must provide both parameters to use queue role credentials.\n"
            "Example: get_bucket_encryption(bucket_name='my-bucket', farm_id='farm-abc', queue_id='queue-xyz')"
        )
    
    try:
        s3 = get_s3_client_with_queue_role(farm_id, queue_id)
        
        response = s3.get_bucket_encryption(Bucket=bucket_name)
        
        result = f"Encryption for {bucket_name}:\n\n"
        
        for rule in response['ServerSideEncryptionConfiguration']['Rules']:
            sse = rule['ApplyServerSideEncryptionByDefault']
            result += f"Algorithm: {sse['SSEAlgorithm']}\n"
            
            if 'KMSMasterKeyID' in sse:
                result += f"KMS Key: {sse['KMSMasterKeyID']}\n"
        
        return result
        
    except Exception as e:
        error_str = str(e)
        
        if 'ServerSideEncryptionConfigurationNotFoundError' in error_str:
            return f"No encryption configured for {bucket_name}"
        
        result = f"❌ Error getting bucket encryption: {error_str}\n\n"
        
        if 'AccessDenied' in error_str or '403' in error_str:
            result += "**Permission Error**: The queue role does not have permission to read bucket encryption settings.\n\n"
            result += "**Required Permission**: s3:GetEncryptionConfiguration\n\n"
            result += "**Solution**: Update the queue role IAM policy to include:\n"
            result += "```json\n"
            result += "{\n"
            result += '  "Effect": "Allow",\n'
            result += '  "Action": ["s3:GetEncryptionConfiguration"],\n'
            result += f'  "Resource": "arn:aws:s3:::{bucket_name}"\n'
            result += "}\n"
            result += "```\n"
        
        return result


@tool
def get_bucket_versioning(bucket_name: str, farm_id: str = None, queue_id: str = None) -> str:
    """
    Get bucket versioning configuration.
    
    **CRITICAL**: You MUST provide farm_id and queue_id to use queue role credentials.
    Without these, the tool will use expired user credentials and fail.
    
    Args:
        bucket_name: Name of the S3 bucket
        farm_id: Farm ID to use queue role credentials (REQUIRED for proper access)
        queue_id: Queue ID to use queue role credentials (REQUIRED for proper access)
        
    Returns:
        Bucket versioning status
    """
    if not farm_id or not queue_id:
        return (
            "❌ ERROR: farm_id and queue_id are REQUIRED for this tool.\n"
            "You must provide both parameters to use queue role credentials.\n"
            "Example: get_bucket_versioning(bucket_name='my-bucket', farm_id='farm-abc', queue_id='queue-xyz')"
        )
    
    try:
        s3 = get_s3_client_with_queue_role(farm_id, queue_id)
        
        response = s3.get_bucket_versioning(Bucket=bucket_name)
        
        status = response.get('Status', 'Disabled')
        mfa_delete = response.get('MFADelete', 'Disabled')
        
        result = f"Versioning for {bucket_name}:\n"
        result += f"Status: {status}\n"
        result += f"MFA Delete: {mfa_delete}\n"
        
        return result
        
    except Exception as e:
        error_str = str(e)
        result = f"❌ Error getting bucket versioning: {error_str}\n\n"
        
        if 'AccessDenied' in error_str or '403' in error_str:
            result += "**Permission Error**: The queue role does not have permission to read bucket versioning settings.\n\n"
            result += "**Required Permission**: s3:GetBucketVersioning\n\n"
            result += "**Solution**: Update the queue role IAM policy to include:\n"
            result += "```json\n"
            result += "{\n"
            result += '  "Effect": "Allow",\n'
            result += '  "Action": ["s3:GetBucketVersioning"],\n'
            result += f'  "Resource": "arn:aws:s3:::{bucket_name}"\n'
            result += "}\n"
            result += "```\n"
        
        return result


@tool
def list_bucket_objects(bucket_name: str, prefix: str = "", max_keys: int = 10, farm_id: str = None, queue_id: str = None) -> str:
    """
    List objects in the bucket (useful for verifying access and content).
    
    **CRITICAL**: You MUST provide farm_id and queue_id to use queue role credentials.
    Without these, the tool will use expired user credentials and fail.
    
    Args:
        bucket_name: Name of the S3 bucket
        prefix: Optional prefix to filter objects
        max_keys: Maximum number of objects to list (default: 10)
        farm_id: Farm ID to use queue role credentials (REQUIRED for proper access)
        queue_id: Queue ID to use queue role credentials (REQUIRED for proper access)
        
    Returns:
        List of objects in the bucket
    """
    if not farm_id or not queue_id:
        return (
            "❌ ERROR: farm_id and queue_id are REQUIRED for this tool.\n"
            "You must provide both parameters to use queue role credentials.\n"
            "Example: list_bucket_objects(bucket_name='my-bucket', farm_id='farm-abc', queue_id='queue-xyz')"
        )
    
    try:
        s3 = get_s3_client_with_queue_role(farm_id, queue_id)
        
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
        error_str = str(e)
        result = f"❌ Error listing bucket objects: {error_str}\n\n"
        
        if 'AccessDenied' in error_str or '403' in error_str:
            result += "**Permission Error**: The queue role does not have permission to list objects in this bucket.\n\n"
            result += "**Required Permission**: s3:ListBucket\n\n"
            result += "**Solution**: Update the queue role IAM policy to include:\n"
            result += "```json\n"
            result += "{\n"
            result += '  "Effect": "Allow",\n'
            result += '  "Action": ["s3:ListBucket"],\n'
            result += f'  "Resource": "arn:aws:s3:::{bucket_name}"\n'
            result += "}\n"
            result += "```\n"
            result += "\n**Note**: For job attachments, the queue role needs ListBucket permission on the job attachments bucket.\n"
        elif 'NoSuchBucket' in error_str:
            result += f"**Bucket Not Found**: The bucket '{bucket_name}' does not exist or is in a different region.\n"
        
        return result

@tool
def job_attachments_agent(query: str, farm_id: str = None, queue_id: str = None) -> str:
    """
    Validates S3 bucket configuration and permissions for job attachments.
    
    IMPORTANT: Provide farm_id and queue_id to test S3 access with queue role credentials.
    This ensures you're testing with the same permissions the queue uses.
    
    Args:
        query: Description of the job attachments issue to investigate
        farm_id: Optional farm ID to use queue role credentials for S3 access
        queue_id: Optional queue ID to use queue role credentials for S3 access
        
    Returns:
        Job attachments assessment and recommendations
    """
    try:
        # Update system prompt to include farm_id and queue_id context
        system_prompt = JOB_ATTACHMENTS_AGENT_SYSTEM_PROMPT
        if farm_id and queue_id:
            system_prompt += f"\n\n" + "="*80 + "\n"
            system_prompt += f"**CURRENT CONTEXT**\n"
            system_prompt += f"="*80 + "\n"
            system_prompt += f"Farm ID: {farm_id}\n"
            system_prompt += f"Queue ID: {queue_id}\n\n"
            system_prompt += f"**MANDATORY PARAMETERS FOR ALL S3 TOOL CALLS**:\n"
            system_prompt += f"- farm_id='{farm_id}'\n"
            system_prompt += f"- queue_id='{queue_id}'\n\n"
            system_prompt += f"**EXAMPLE CORRECT TOOL CALL**:\n"
            system_prompt += f"list_bucket_objects(bucket_name='my-bucket', farm_id='{farm_id}', queue_id='{queue_id}')\n\n"
            system_prompt += f"**WRONG - DO NOT DO THIS**:\n"
            system_prompt += f"list_bucket_objects(bucket_name='my-bucket')  # Missing farm_id and queue_id!\n"
            system_prompt += "="*80 + "\n"
        
        attachments_agent = Agent(
            system_prompt=system_prompt,
            model=job_attachments_model,  # Using centralized model config
            tools=[
                get_queue_details,  # Get job attachments bucket info from queue
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
