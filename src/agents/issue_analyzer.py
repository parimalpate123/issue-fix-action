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
        Get relevant files from repository based on issue context.
        Returns comprehensive file list to help LLM generate accurate paths.
        
        Args:
            repo_full_name: Repository name
            issue: Issue data
            
        Returns:
            List of all files in the repository (up to 50 files)
        """
        all_files = []
        
        try:
            # Get root level files
            root_files = self.github_client.get_repo_files(repo_full_name)
            all_files.extend([f for f in root_files if f['type'] == 'file'])
            
            # Get files from common directories (silently skip if they don't exist)
            common_dirs = ['src', 'lib', 'app', 'config', 'tests', 'test']
            for dir_name in common_dirs:
                try:
                    dir_files = self.github_client.get_repo_files(repo_full_name, path=dir_name)
                    all_files.extend([f for f in dir_files if f['type'] == 'file'])
                except Exception as e:
                    # Directory doesn't exist (404) - this is expected and not an error
                    # Only log if it's not a 404
                    error_str = str(e)
                    if '404' not in error_str and 'Not Found' not in error_str:
                        logger.debug(f"Error checking directory {dir_name}: {e}")
                    # Silently continue for 404s
                    continue
            
            # Limit to 50 files to avoid token limits
            return all_files[:50]
            
        except Exception as e:
            logger.warning(f"Failed to get repository files: {e}")
            # Return empty list if we can't get files
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
        """Build the analysis prompt with actual repository file structure"""
        # Build comprehensive file list
        if repo_files:
            files_info = "\n".join([f"- {f['path']}" for f in repo_files])
            files_section = f"""### Actual Repository Files (use ONLY these paths):
{files_info}

**IMPORTANT:** Only use file paths that exist in the list above. Do not invent or guess file paths."""
        else:
            files_section = "### Repository Files: Unable to retrieve file structure. Use common file patterns (e.g., src/index.js, package.json)."
        
        return f"""Analyze this GitHub issue and determine what needs to be fixed:

## Issue #{issue['number']}: {issue['title']}

### Issue Body:
{issue['body']}

{files_section}

### Labels:
{', '.join(issue.get('labels', []))}

**CRITICAL:** When specifying affected_files in your JSON response, ONLY use file paths that are listed in the "Actual Repository Files" section above. Do not create paths based on service names or assumptions. If you cannot find the exact file, set requires_code_analysis: true and provide your best guess with a note.

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
