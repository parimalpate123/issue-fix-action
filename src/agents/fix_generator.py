"""
Fix Generator Agent
Generates code fixes based on issue analysis
"""

import json
import logging
from typing import Dict, Any, List, Optional
from ..llm.bedrock import BedrockClient
from ..utils.github_client import GitHubClient
from ..prompts import FIX_GENERATION_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class FixGenerator:
    """Generates code fixes for analyzed issues"""
    
    def __init__(self, github_client: GitHubClient, bedrock_client: BedrockClient):
        """
        Initialize Fix Generator
        
        Args:
            github_client: GitHub API client
            bedrock_client: AWS Bedrock client
        """
        self.github_client = github_client
        self.bedrock_client = bedrock_client
    
    def generate_fix(
        self,
        repo_full_name: str,
        analysis: Dict[str, Any],
        branch: str = 'main'
    ) -> Dict[str, Any]:
        """
        Generate code fix based on analysis
        
        Args:
            repo_full_name: Repository name (org/repo)
            analysis: Issue analysis result
            branch: Branch to read code from
            
        Returns:
            Fix result with file changes
        """
        logger.info(f"Generating fix for {analysis.get('affected_component')}")
        
        # Get affected files content
        affected_files = analysis.get('affected_files', [])
        if not affected_files:
            logger.warning("No affected files identified in analysis")
            return {
                'success': False,
                'error': 'No affected files identified',
                'files_to_modify': [],
                'files_to_create': []
            }
        
        # Read file contents
        file_contents = {}
        for file_info in affected_files:
            file_path = file_info.get('path')
            if file_path:
                try:
                    content = self.github_client.get_file_content(repo_full_name, file_path, ref=branch)
                    file_contents[file_path] = content
                except Exception as e:
                    logger.warning(f"Failed to read file {file_path}: {e}")
        
        # Build fix generation prompt
        user_prompt = self._build_fix_prompt(analysis, file_contents)
        
        # Call Bedrock
        logger.info("Calling Bedrock for fix generation...")
        response = self.bedrock_client.invoke_model(
            system_prompt="You are an expert software engineer generating code fixes for production incidents. Follow the instructions carefully and provide fixes in the specified JSON format.",
            user_prompt=user_prompt,
            max_tokens=4000,
            temperature=0.2
        )
        
        response_text = self.bedrock_client.get_response_text(response)
        
        # Parse response
        fix_result = self._parse_fix_response(response_text)
        
        # Add metadata
        fix_result['analysis'] = analysis
        fix_result['repo'] = repo_full_name
        
        logger.info(f"Fix generation complete: {len(fix_result.get('files_to_modify', []))} files to modify")
        
        return fix_result
    
    def _build_fix_prompt(self, analysis: Dict[str, Any], file_contents: Dict[str, str]) -> str:
        """Build the fix generation prompt"""
        issue = analysis.get('issue', {})
        
        # Format file contents
        files_section = ""
        for file_path, content in file_contents.items():
            # Detect language from extension
            language = self._detect_language(file_path)
            files_section += f"\n### File: {file_path}\n```{language}\n{content}\n```\n"
        
        # Extract error patterns from issue
        error_patterns = self._extract_error_patterns(issue)
        
        # Format the prompt
        prompt = FIX_GENERATION_PROMPT_TEMPLATE.format(
            root_cause=analysis.get('root_cause', 'Unknown'),
            affected_component=analysis.get('affected_component', 'Unknown'),
            fix_type=analysis.get('fix_type', 'other'),
            error_patterns=', '.join(error_patterns) if error_patterns else 'N/A',
            service_name=self._extract_service_name(issue),
            file_path=list(file_contents.keys())[0] if file_contents else 'unknown',
            language=self._detect_language(list(file_contents.keys())[0]) if file_contents else 'javascript',
            file_content=list(file_contents.values())[0] if file_contents else '// No file content available'
        )
        
        # Add all files
        if len(file_contents) > 1:
            prompt += "\n\n### Additional Files:\n"
            for file_path, content in list(file_contents.items())[1:]:
                language = self._detect_language(file_path)
                prompt += f"\n### File: {file_path}\n```{language}\n{content}\n```\n"
        
        return prompt
    
    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension"""
        ext = file_path.split('.')[-1].lower()
        language_map = {
            'js': 'javascript',
            'jsx': 'javascript',
            'ts': 'typescript',
            'tsx': 'typescript',
            'py': 'python',
            'java': 'java',
            'go': 'go',
            'rs': 'rust',
            'rb': 'ruby',
            'php': 'php',
            'json': 'json',
            'yaml': 'yaml',
            'yml': 'yaml',
            'md': 'markdown'
        }
        return language_map.get(ext, 'text')
    
    def _extract_error_patterns(self, issue: Dict[str, Any]) -> List[str]:
        """Extract error patterns from issue body"""
        body = issue.get('body', '')
        patterns = []
        
        # Look for "Error Patterns" section
        if 'Error Patterns' in body:
            in_section = False
            for line in body.split('\n'):
                if 'Error Patterns' in line:
                    in_section = True
                    continue
                if in_section and line.strip().startswith('-'):
                    pattern = line.strip().lstrip('-').strip()
                    if pattern:
                        patterns.append(pattern)
                elif in_section and line.strip() and not line.startswith('#'):
                    break
        
        return patterns
    
    def _extract_service_name(self, issue: Dict[str, Any]) -> str:
        """Extract service name from issue"""
        body = issue.get('body', '')
        
        if 'Service:' in body:
            for line in body.split('\n'):
                if 'Service:' in line:
                    return line.split('Service:')[-1].strip()
        
        return 'unknown-service'
    
    def _parse_fix_response(self, response_text: str) -> Dict[str, Any]:
        """Parse Bedrock response into structured fix"""
        try:
            # Try to extract JSON from response
            if '```json' in response_text:
                json_start = response_text.find('```json') + 7
                json_end = response_text.find('```', json_start)
                json_str = response_text[json_start:json_end].strip()
            elif '```' in response_text:
                json_start = response_text.find('```') + 3
                json_end = response_text.find('```', json_start)
                json_str = response_text[json_start:json_end].strip()
            else:
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                json_str = response_text[json_start:json_end]
            
            fix_result = json.loads(json_str)
            fix_result['success'] = True
            return fix_result
        except Exception as e:
            logger.error(f"Failed to parse fix response: {e}")
            logger.debug(f"Response text: {response_text[:500]}")
            return {
                'success': False,
                'error': f'Failed to parse fix response: {str(e)}',
                'files_to_modify': [],
                'files_to_create': []
            }
