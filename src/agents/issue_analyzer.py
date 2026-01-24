"""
Issue Analyzer Agent
Analyzes GitHub issues to understand the problem and determine fix strategy
"""

import json
import logging
import os
from typing import Dict, Any, Optional, List
from ..llm.bedrock import BedrockClient
from ..utils.github_client import GitHubClient
from ..prompts import ISSUE_ANALYSIS_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class IssueAnalyzer:
    """Analyzes GitHub issues to extract fix requirements"""
    
    def __init__(self, github_client: GitHubClient, bedrock_client: BedrockClient):
        """
        Initialize Issue Analyzer
        
        Args:
            github_client: GitHub API client
            bedrock_client: AWS Bedrock client
        """
        self.github_client = github_client
        self.bedrock_client = bedrock_client
    
    def analyze_issue(self, repo_full_name: str, issue_number: int) -> Dict[str, Any]:
        """
        Analyze a GitHub issue to understand the problem
        
        Args:
            repo_full_name: Repository name (org/repo)
            issue_number: Issue number
            
        Returns:
            Analysis result with root cause, affected files, fix strategy
        """
        logger.info(f"Analyzing issue #{issue_number} in {repo_full_name}")
        
        # Get issue details
        issue = self.github_client.get_issue(repo_full_name, issue_number)
        
        # Get repository structure to understand codebase
        repo_files = self._get_relevant_files(repo_full_name, issue)
        
        # Build analysis prompt
        user_prompt = self._build_analysis_prompt(issue, repo_files)
        
        # Call Bedrock
        logger.info("Calling Bedrock for issue analysis...")
        response = self.bedrock_client.invoke_model(
            system_prompt=ISSUE_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=2000,
            temperature=0.2
        )
        
        response_text = self.bedrock_client.get_response_text(response)
        
        # Parse response
        analysis = self._parse_analysis_response(response_text)
        
        # Add issue metadata
        analysis['issue'] = issue
        analysis['repo'] = repo_full_name
        
        logger.info(f"Issue analysis complete: {analysis.get('fix_type')} fix for {analysis.get('affected_component')}")
        
        return analysis
    
    def _get_relevant_files(self, repo_full_name: str, issue: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Get relevant files from repository based on issue context
        
        Args:
            repo_full_name: Repository name
            issue: Issue data
            
        Returns:
            List of relevant files
        """
        # Extract service name from issue
        service_name = self._extract_service_name(issue)
        
        # Get repository structure
        try:
            all_files = self.github_client.get_repo_files(repo_full_name)
            
            # Filter relevant files based on service name and issue content
            relevant_files = []
            for file in all_files:
                if file['type'] == 'file':
                    # Look for service-specific files
                    if service_name and service_name.lower() in file['path'].lower():
                        relevant_files.append(file)
                    # Look for common configuration files
                    elif any(pattern in file['path'].lower() for pattern in ['config', 'database', 'connection', 'pool']):
                        relevant_files.append(file)
            
            return relevant_files[:20]  # Limit to 20 files
        except Exception as e:
            logger.warning(f"Failed to get repository files: {e}")
            return []
    
    def _extract_service_name(self, issue: Dict[str, Any]) -> Optional[str]:
        """Extract service name from issue body"""
        body = issue.get('body', '')
        
        # Look for "Service: service-name" pattern
        if 'Service:' in body:
            for line in body.split('\n'):
                if 'Service:' in line:
                    service = line.split('Service:')[-1].strip()
                    return service
        
        return None
    
    def _build_analysis_prompt(self, issue: Dict[str, Any], repo_files: List[Dict[str, Any]]) -> str:
        """Build the analysis prompt"""
        files_info = "\n".join([f"- {f['path']} ({f['type']})" for f in repo_files[:10]])
        
        return f"""Analyze this GitHub issue and determine what needs to be fixed:

## Issue #{issue['number']}: {issue['title']}

### Issue Body:
{issue['body']}

### Repository Files (sample):
{files_info if files_info else "No files listed"}

### Labels:
{', '.join(issue.get('labels', []))}

Provide your analysis in the JSON format specified in the system prompt.
"""
    
    def _parse_analysis_response(self, response_text: str) -> Dict[str, Any]:
        """Parse Bedrock response into structured analysis"""
        try:
            # Try to extract JSON from response
            # Look for JSON code block
            if '```json' in response_text:
                json_start = response_text.find('```json') + 7
                json_end = response_text.find('```', json_start)
                json_str = response_text[json_start:json_end].strip()
            elif '```' in response_text:
                json_start = response_text.find('```') + 3
                json_end = response_text.find('```', json_start)
                json_str = response_text[json_start:json_end].strip()
            else:
                # Try to find JSON object
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                json_str = response_text[json_start:json_end]
            
            analysis = json.loads(json_str)
            return analysis
        except Exception as e:
            logger.error(f"Failed to parse analysis response: {e}")
            logger.debug(f"Response text: {response_text[:500]}")
            # Return fallback analysis
            return {
                'root_cause': 'Unable to parse analysis',
                'affected_component': 'unknown',
                'fix_type': 'other',
                'affected_files': [],
                'fix_strategy': 'Manual review required',
                'confidence': 0,
                'requires_code_analysis': True
            }
