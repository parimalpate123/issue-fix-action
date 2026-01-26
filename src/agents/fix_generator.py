"""
Fix Generator Agent
Generates code fixes based on issue analysis
"""

import json
import logging
import re
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
        file_contents = {}
        
        # Read file contents from analysis
        for file_info in affected_files:
            file_path = file_info.get('path')
            if file_path:
                try:
                    content = self.github_client.get_file_content(repo_full_name, file_path, ref=branch)
                    file_contents[file_path] = content
                except Exception as e:
                    logger.warning(f"Failed to read file {file_path}: {e}")
        
        # If no files found, try to find common files
        if not file_contents:
            logger.warning("No affected files found. Trying to find common files...")
            service_name = self._extract_service_name(analysis.get('issue', {}))
            common_files = [
                'src/index.js',
                'index.js',
                'package.json',
                'src/config/database.js',
                'config/database.js'
            ]
            if service_name and service_name != 'unknown-service':
                common_files.insert(0, f'src/{service_name}.js')
                common_files.insert(1, f'{service_name}.js')
            
            for file_path in common_files:
                try:
                    content = self.github_client.get_file_content(repo_full_name, file_path, ref=branch)
                    file_contents[file_path] = content
                    logger.info(f"Found file: {file_path}")
                    break
                except Exception:
                    continue
        
        # If still no files, create a placeholder
        if not file_contents:
            logger.warning("No files found in repository. Will generate fix based on issue description.")
            file_contents['src/config/database.js'] = '// No existing code found. Generate new configuration file based on the issue description.'
        
        # Build fix generation prompt
        user_prompt = self._build_fix_prompt(analysis, file_contents)
        
        # Call Bedrock
        logger.info("Calling Bedrock for fix generation...")
        response = self.bedrock_client.invoke_model(
            system_prompt=(
                "You are an expert software engineer generating targeted code fixes for production incidents. "
                "You MUST make minimal, surgical changes — only modify the specific function or block that is broken. "
                "NEVER remove or rewrite existing API routes, server setup, exports, or unrelated code. "
                "The old_code field must contain the exact code from the file being replaced. "
                "The new_code field must contain only the replacement for that specific section. "
                "Follow the instructions carefully and provide fixes in the specified JSON format."
            ),
            user_prompt=user_prompt,
            max_tokens=8000,
            temperature=0.2
        )
        
        response_text = self.bedrock_client.get_response_text(response)

        # Parse response
        fix_result = self._parse_fix_response(response_text)

        # Validate and refine the fix if needed
        if fix_result.get('success'):
            issues = self._validate_fix(fix_result, file_contents)
            if issues:
                logger.warning(f"Fix validation found {len(issues)} issues, requesting refinement...")
                fix_result = self._refine_fix(fix_result, issues, file_contents, analysis)

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
        
        # Format the prompt - escape braces in the template first
        # Replace { with {{ and } with }} except for our actual placeholders
        template = FIX_GENERATION_PROMPT_TEMPLATE
        
        # Format the prompt with actual values
        prompt = template.format(
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
    
    def _validate_fix(self, fix_result: Dict[str, Any], file_contents: Dict[str, str]) -> List[str]:
        """
        Validate the generated fix for completeness.
        Returns a list of issues found, empty if fix is valid.
        """
        issues = []

        # Collect all new_code across all changes
        all_new_code = ''
        for file_mod in fix_result.get('files_to_modify', []):
            for change in file_mod.get('changes', []):
                all_new_code += '\n' + change.get('new_code', '')

        # Collect all existing code (imports, etc.)
        all_existing_code = '\n'.join(file_contents.values())

        # Check for undefined references: new modules used but not imported
        import_keywords = ['require(', 'import ']
        new_modules = []
        for keyword in import_keywords:
            idx = 0
            while True:
                idx = all_new_code.find(keyword, idx)
                if idx == -1:
                    break
                # Extract module name
                start = all_new_code.find("'", idx)
                if start == -1:
                    start = all_new_code.find('"', idx)
                if start != -1:
                    end = all_new_code.find(all_new_code[start], start + 1)
                    if end != -1:
                        module_name = all_new_code[start + 1:end]
                        new_modules.append(module_name)
                idx += len(keyword)

        # Check if new modules are already in existing code or in another change entry
        for module in new_modules:
            if module not in all_existing_code and module not in all_new_code.replace(all_new_code, '', 1):
                # Module is new — check if there's a change entry that adds the import
                has_import_change = False
                for file_mod in fix_result.get('files_to_modify', []):
                    for change in file_mod.get('changes', []):
                        new_code = change.get('new_code', '')
                        if f"require('{module}')" in new_code or f'require("{module}")' in new_code:
                            has_import_change = True
                            break
                        if f"from '{module}'" in new_code or f'from "{module}"' in new_code:
                            has_import_change = True
                            break

                if not has_import_change:
                    issues.append(f"Module '{module}' is used but no import/require change entry adds it")

        # Check for variables used in new_code that aren't defined anywhere
        # Look for common patterns like `variableName.method()` or `variableName,`
        # This is a simple heuristic, not a full parser
        for file_mod in fix_result.get('files_to_modify', []):
            for change in file_mod.get('changes', []):
                new_code = change.get('new_code', '')
                old_code = change.get('old_code', '')
                # Find identifiers in new_code that aren't in old_code or existing code
                # Simple check: look for camelCase identifiers ending with Config/Client/Options/Settings
                identifiers = set(re.findall(r'\b([a-z][a-zA-Z0-9]+(?:Config|Client|Options|Settings))\b', new_code))
                for ident in identifiers:
                    if ident not in all_existing_code and ident not in all_new_code.replace(new_code, '', 1):
                        issues.append(f"Variable '{ident}' is used in new_code but not defined in any change entry or existing code")

        # Check if tests are included
        files_to_create = fix_result.get('files_to_create', [])
        has_tests = any(
            'test' in f.get('path', '').lower() or 'spec' in f.get('path', '').lower()
            for f in files_to_create
        )
        if not has_tests:
            issues.append("No test file included in files_to_create")

        return issues

    def _refine_fix(
        self,
        fix_result: Dict[str, Any],
        issues: List[str],
        file_contents: Dict[str, str],
        analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send the fix back to the LLM with validation issues for refinement.
        """
        issues_text = '\n'.join(f'- {issue}' for issue in issues)

        # Build the current fix as JSON for context
        fix_json = json.dumps({
            'files_to_modify': fix_result.get('files_to_modify', []),
            'files_to_create': fix_result.get('files_to_create', []),
            'summary': fix_result.get('summary', ''),
        }, indent=2)

        # Include the current file content
        file_context = ''
        for path, content in file_contents.items():
            lang = self._detect_language(path)
            file_context += f"\n### Current file: {path}\n```{lang}\n{content}\n```\n"

        refinement_prompt = f"""Your previous fix has validation issues that must be resolved.

## Validation Issues Found
{issues_text}

## Your Previous Fix
```json
{fix_json}
```

## Current File Content
{file_context}

## Instructions

Fix ALL the validation issues above. Specifically:
1. If a module is used but not imported, add a separate change entry that adds the import/require statement. The old_code must match the existing import line exactly (copy from the current file), and new_code adds the new import alongside it.
2. If a variable/config is used but not defined, add a separate change entry that defines it. Pick an appropriate location in the file (e.g., after imports) and use an existing line as old_code anchor.
3. If tests are missing, add a test file in files_to_create that covers the happy path and the error scenario from the original incident.

Return the COMPLETE corrected fix in the same JSON format (files_to_modify, files_to_create, summary, confidence, testing_notes). Include ALL change entries — both the original ones that were correct AND the new ones you're adding."""

        logger.info("Calling Bedrock for fix refinement...")
        response = self.bedrock_client.invoke_model(
            system_prompt=(
                "You are an expert software engineer refining a code fix. "
                "The previous fix was incomplete. Add the missing pieces (imports, variable definitions, tests) "
                "while keeping the original fix changes intact. "
                "Return the complete corrected fix in JSON format."
            ),
            user_prompt=refinement_prompt,
            max_tokens=8000,
            temperature=0.2
        )

        response_text = self.bedrock_client.get_response_text(response)
        refined_result = self._parse_fix_response(response_text)

        if refined_result.get('success'):
            logger.info("Fix refinement successful")
            return refined_result
        else:
            logger.warning("Fix refinement failed, using original fix")
            return fix_result

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
