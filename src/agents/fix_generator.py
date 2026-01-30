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
from ..validators.syntax_validator import SyntaxValidator
from ..validators.dependency_checker import DependencyChecker

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

        # Run validation checks (but don't refine - single LLM call approach)
        validation_results = {'checks_passed': [], 'checks_failed': [], 'warnings': []}
        if fix_result.get('success'):
            validation_results = self._run_validation_checks(fix_result, file_contents, repo_full_name, branch)
            logger.info(f"Validation: {len(validation_results['checks_passed'])} passed, {len(validation_results['checks_failed'])} failed")

        # Add metadata and validation results
        fix_result['analysis'] = analysis
        fix_result['repo'] = repo_full_name
        fix_result['validation_results'] = validation_results

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
    
    def _run_validation_checks(
        self,
        fix_result: Dict[str, Any],
        file_contents: Dict[str, str],
        repo_full_name: str,
        branch: str
    ) -> Dict[str, Any]:
        """
        Run validation checks on the generated fix.
        Returns structured validation results without retrying.

        Returns:
            Dict with 'checks_passed', 'checks_failed', and 'warnings'
        """
        checks_passed = []
        checks_failed = []
        warnings = []

        syntax_validator = SyntaxValidator()
        dependency_checker = DependencyChecker()

        # Simulate applying changes to get final file contents
        simulated_files = self._simulate_file_changes(fix_result, file_contents, repo_full_name, branch)

        # Check 1: Syntax validation
        for file_path, content in simulated_files.items():
            result = syntax_validator.validate(file_path, content)

            if result.get('skipped'):
                warnings.append(f"Syntax check skipped for {file_path}: {result.get('reason', 'unknown reason')}")
            elif result.get('valid'):
                checks_passed.append(f"✓ Syntax valid: {file_path}")
            else:
                checks_failed.append(f"✗ Syntax error in {file_path}: {result.get('error', 'Unknown error')}")

        # Check 2: Dependency validation
        for file_path, content in simulated_files.items():
            language = syntax_validator._detect_language(file_path)

            if language == 'unknown':
                continue

            # Get package manifest
            package_content = None
            try:
                if language == 'python':
                    try:
                        package_content = self.github_client.get_file_content(
                            repo_full_name, 'requirements.txt', ref=branch
                        )
                    except:
                        logger.debug("No requirements.txt found")
                elif language in ['javascript', 'typescript']:
                    try:
                        package_content = self.github_client.get_file_content(
                            repo_full_name, 'package.json', ref=branch
                        )
                    except:
                        logger.debug("No package.json found")

                if package_content:
                    missing = dependency_checker.check_dependencies(
                        content, package_content, language
                    )
                    if missing:
                        checks_failed.append(f"✗ Missing dependencies in {file_path}: {', '.join(missing)}")
                    else:
                        checks_passed.append(f"✓ All dependencies available: {file_path}")
                else:
                    warnings.append(f"Package manifest not found, skipping dependency check for {file_path}")

            except Exception as e:
                logger.warning(f"Dependency check failed for {file_path}: {e}")
                warnings.append(f"Dependency check failed for {file_path}: {str(e)}")

        # Check 3: Test coverage check
        files_to_create = fix_result.get('files_to_create', [])
        has_tests = any(
            'test' in f.get('path', '').lower() or 'spec' in f.get('path', '').lower()
            for f in files_to_create
        )
        if has_tests:
            checks_passed.append("✓ Test file included")
        else:
            warnings.append("⚠ No test file included in files_to_create")

        # Check 4: Heuristic checks for common issues
        all_new_code = ''
        for file_mod in fix_result.get('files_to_modify', []):
            for change in file_mod.get('changes', []):
                all_new_code += '\n' + change.get('new_code', '')

        # Check for TODO/FIXME comments that might indicate incomplete work
        if 'TODO' in all_new_code or 'FIXME' in all_new_code:
            warnings.append("⚠ Code contains TODO/FIXME comments")

        # Check for console.log/print statements (potential debug code)
        if 'console.log' in all_new_code or re.search(r'\bprint\s*\(', all_new_code):
            warnings.append("⚠ Code contains console.log/print statements")

        return {
            'checks_passed': checks_passed,
            'checks_failed': checks_failed,
            'warnings': warnings,
            'summary': f"{len(checks_passed)} passed, {len(checks_failed)} failed, {len(warnings)} warnings"
        }

    def _simulate_file_changes(
        self,
        fix_result: Dict[str, Any],
        file_contents: Dict[str, str],
        repo_full_name: str,
        branch: str
    ) -> Dict[str, str]:
        """
        Simulate applying changes to get final file contents for validation.

        Returns:
            Dict mapping file paths to their final content after applying changes
        """
        simulated = {}

        # Handle modified files
        for file_change in fix_result.get('files_to_modify', []):
            file_path = file_change.get('path')
            if not file_path:
                continue

            # Get current content
            if file_path in file_contents:
                current = file_contents[file_path]
            else:
                try:
                    current = self.github_client.get_file_content(
                        repo_full_name, file_path, ref=branch
                    )
                except Exception as e:
                    logger.warning(f"Could not get content for {file_path}: {e}")
                    continue

            # Apply changes
            modified = self._apply_changes_for_simulation(current, file_change.get('changes', []))
            if modified:
                simulated[file_path] = modified

        # Handle new files
        for file_create in fix_result.get('files_to_create', []):
            file_path = file_create.get('path')
            content = file_create.get('content', '')
            if file_path and content:
                simulated[file_path] = content

        return simulated

    def _apply_changes_for_simulation(self, current_content: str, changes: List[Dict[str, Any]]) -> str:
        """
        Apply changes to simulate final file content.
        Similar to PR creator's logic but for validation purposes.
        """
        if not current_content or not changes:
            return current_content or ''

        modified_content = current_content

        for change in changes:
            old_code = change.get('old_code', '')
            new_code = change.get('new_code', '')

            if not new_code:
                continue

            if old_code and old_code.strip() in modified_content:
                # Surgical replacement
                modified_content = modified_content.replace(old_code.strip(), new_code.strip(), 1)
            elif not old_code:
                # No old_code - check if new_code looks like full file
                new_lines = new_code.strip().split('\n')
                has_imports = any(
                    l.strip().startswith(('import ', 'const ', 'require(', 'from '))
                    for l in new_lines[:5]
                )
                has_structure = len(new_lines) > 10

                if has_imports and has_structure:
                    # Looks like full file replacement
                    modified_content = new_code

        return modified_content

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
