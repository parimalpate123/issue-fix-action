"""
AWS Bedrock Client for Issue Agent
Reuses patterns from pr-code-review-action
"""

import json
import logging
import time
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class BedrockClient:
    """Client for AWS Bedrock API with retry logic"""
    
    def __init__(self, region: str = 'us-east-1', model_id: str = 'anthropic.claude-3-5-sonnet-20240620-v1:0'):
        """
        Initialize Bedrock client
        
        Args:
            region: AWS region
            model_id: Bedrock model ID
        """
        self.region = region
        self.model_id = model_id
        self.bedrock_runtime = boto3.client('bedrock-runtime', region_name=region)
        logger.info(f"Bedrock client initialized: {model_id} in {region}")
    
    def invoke_model(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.3,
        max_retries: int = 5,
        initial_delay: float = 2.0,
        max_delay: float = 60.0
    ) -> Dict[str, Any]:
        """
        Invoke Bedrock model with retry logic
        
        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            max_tokens: Maximum tokens to generate
            temperature: Temperature for generation
            max_retries: Maximum retry attempts
            initial_delay: Initial delay before retry
            max_delay: Maximum delay between retries
            
        Returns:
            Response from Bedrock API
        """
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        }
        
        delay = initial_delay
        
        for attempt in range(max_retries):
            try:
                response = self.bedrock_runtime.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps(request_body)
                )
                
                response_body = json.loads(response['body'].read())
                return response_body
                
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                
                # Only retry on throttling errors
                if error_code == 'ThrottlingException' and attempt < max_retries - 1:
                    logger.warning(
                        f"Bedrock throttling (attempt {attempt + 1}/{max_retries}): "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    delay = min(delay * 2.0, max_delay)
                    continue
                else:
                    logger.error(f"Bedrock invocation failed: {error_code} - {str(e)}")
                    raise
                    
            except Exception as e:
                logger.error(f"Bedrock invocation failed with unexpected error: {str(e)}")
                raise
        
        # Should never reach here
        raise ClientError(
            {'Error': {'Code': 'MaxRetriesExceeded', 'Message': 'Max retries exceeded'}},
            'InvokeModel'
        )
    
    def get_response_text(self, response: Dict[str, Any]) -> str:
        """
        Extract text from Bedrock response
        
        Args:
            response: Bedrock API response
            
        Returns:
            Response text
        """
        if 'content' in response and len(response['content']) > 0:
            return response['content'][0].get('text', '')
        return ''
