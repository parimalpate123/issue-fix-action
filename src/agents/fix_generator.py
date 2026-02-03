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
from ..validators.build_runner import BuildRunner
from ..validators.test_runner import TestRunner

logger = logging.getLogger(__name__)

# Tool definitions for LLM
VALIDATION_TOOLS = [
    {
        "name": "validate_syntax",
        "description": "Validate code syntax using AST parsing. Use this to check if your generated code has any syntax errors before returning it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The code to validate"
                },
                "file_path": {
                    "type": "string",
                    "description": "File path (used to detect language, e.g., 'index.js', 'app.py')"
                }
            },
            "required": ["code", "file_path"]
        }
    },
    {
        "name": "check_dependencies",
        "description": "Check if all imports/requires exist in the package manifest. Use this to verify you haven't used any unavailable dependencies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The code to check for imports"
                },
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "typescript"],
                    "description": "Programming language"
                }
            },
            "required": ["code", "language"]
        }
    },
    {
        "name": "build_code",
        "description": "Build/compile the code to check for build errors. Use this before running tests to ensure the code compiles.",
        "input_schema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "object",
                    "description": "Map of file paths to file contents to build (including your generated fix)"
                }
            },
            "required": ["files"]
        }
    },
    {
        "name": "run_tests",
        "description": "Execute unit tests to verify your fix actually works. ALWAYS use this to prove your fix solves the problem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "object",
                    "description": "Map of file paths to file contents (including test files you generated)"
                }
            },
            "required": ["files"]
        }
    }
]


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

        # Initialize validators
        self.syntax_validator = SyntaxValidator()
        self.dependency_checker = DependencyChecker()
        self.build_runner = BuildRunner()
        self.test_runner = TestRunner()

        # Context for tool execution
        self.repo_full_name = None
        self.branch = None
        self.package_manifest_cache = {}
    
    def generate_fix(
        self,
        repo_full_name: str,
        analysis: Dict[str, Any],
        branch: str = 'main'
    ) -> Dict[str, Any]:
        """
        Generate code fix based on analysis using tool-based validation.

        Args:
            repo_full_name: Repository name (org/repo)
            analysis: Issue analysis result
            branch: Branch to read code from

        Returns:
            Fix result with file changes and validation results
        """
        logger.info(f"Generating fix for {analysis.get('affected_component')}")

        # Set context for tool execution
        self.repo_full_name = repo_full_name
        self.branch = branch

        # Get affected files content - validate and read in one pass
        affected_files = analysis.get('affected_files', [])
        file_contents = {}

        # Read file contents, skipping non-existent files
        for file_info in affected_files:
            file_path = file_info.get('path')
            if file_path:
                try:
                    content = self.github_client.get_file_content(repo_full_name, file_path, ref=branch)
                    file_contents[file_path] = content
                    logger.info(f"Successfully loaded file: {file_path}")
                except Exception as e:
                    # Check if it's a 404 (file not found) vs other error
                    error_str = str(e)
                    if '404' in error_str or 'Not Found' in error_str:
                        logger.warning(f"File path from analysis does not exist, skipping: {file_path}")
                    else:
                        logger.warning(f"Failed to read file {file_path}: {e}")

        # If no files found from analysis, try to find common files
        if not file_contents:
            logger.warning("No valid affected files found. Trying to find common files...")
            common_files = [
                'src/index.js',
                'index.js',
                'package.json',
                'src/config/database.js',
                'config/database.js'
            ]

            # Try common files in order, stop at first success
            for file_path in common_files:
                try:
                    content = self.github_client.get_file_content(repo_full_name, file_path, ref=branch)
                    file_contents[file_path] = content
                    logger.info(f"Found common file: {file_path}")
                    break
                except Exception as e:
                    # Skip 404s silently, log other errors
                    error_str = str(e)
                    if '404' not in error_str and 'Not Found' not in error_str:
                        logger.debug(f"Error reading {file_path}: {e}")
                    continue

        # If still no files, create a placeholder
        if not file_contents:
            logger.warning("No files found in repository. Will generate fix based on issue description.")
            file_contents['src/config/database.js'] = '// No existing code found. Generate new configuration file based on the issue description.'

        # Also get package manifest for dependency checking
        self._load_package_manifest(repo_full_name, branch, file_contents)

        # Build fix generation prompt
        user_prompt = self._build_fix_prompt(analysis, file_contents)

        # Enhanced system prompt for tool use
        system_prompt = """You are an expert software engineer generating code fixes for production incidents.

CRITICAL REQUIREMENTS:
1. ALWAYS generate unit tests for your fix - this is MANDATORY
2. Use validation tools to ensure your code works BEFORE returning
3. Only return the fix when ALL validation passes

PROCESS TO FOLLOW:
1. Analyze the issue and generate a fix with surgical changes
2. Generate unit tests that prove the fix works (REQUIRED - use testing framework like Jest/pytest)
3. Use validate_syntax tool to check for syntax errors in your code
4. If syntax errors found, fix them and validate again
5. Use check_dependencies tool to verify all imports exist
6. If dependencies missing, add them to package.json/requirements.txt in your fix
7. Use build_code tool to build the project
8. If build fails, analyze errors and fix them
9. Use run_tests tool to execute the tests you generated
10. If tests fail, analyze the failure and fix the code
11. Repeat validation until all checks pass
12. Only return the fix when:
    ✓ Syntax is valid
    ✓ All dependencies available
    ✓ Build succeeds
    ✓ Tests pass

IMPORTANT:
- Make minimal, surgical changes - only modify the specific function or block that is broken
- NEVER remove or rewrite existing API routes, server setup, exports, or unrelated code
- The old_code field must contain the exact code from the file being replaced
- The new_code field must contain only the replacement for that specific section
- Use tools multiple times if needed - your goal is to return a working, tested fix
- Return the fix in JSON format only after all validation passes

Use this JSON format:
{
  "files_to_modify": [
    {
      "path": "file/path",
      "changes": [
        {
          "old_code": "exact code to replace",
          "new_code": "replacement code",
          "explanation": "what this change does"
        }
      ]
    }
  ],
  "files_to_create": [
    {
      "path": "test/file.test.js",
      "content": "complete test file content",
      "explanation": "Unit tests proving the fix works"
    }
  ],
  "summary": "Brief description of the fix",
  "confidence": 95,
  "testing_notes": "All tests passing (X passed)"
}"""

        # Call Bedrock with tools
        logger.info("Calling Bedrock with validation tools...")
        response = self.bedrock_client.invoke_model_with_tools(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tools=VALIDATION_TOOLS,
            tool_executor=self._execute_tool,
            max_tokens=8000,
            temperature=0.2,
            max_tool_iterations=15  # Allow multiple tool uses
        )

        response_text = self.bedrock_client.get_response_text(response)

        # Parse response
        fix_result = self._parse_fix_response(response_text)

        # Mark as validated (LLM validated internally using tools)
        fix_result['validated_with_tools'] = True
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
    
    def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool requested by the LLM during generation

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool

        Returns:
            Tool execution result
        """
        logger.info(f"Executing tool: {tool_name}")

        try:
            if tool_name == "validate_syntax":
                result = self.syntax_validator.validate(
                    tool_input['file_path'],
                    tool_input['code']
                )
                return result

            elif tool_name == "check_dependencies":
                language = tool_input['language']
                code = tool_input['code']

                # Get package manifest
                package_content = self.package_manifest_cache.get(language)

                if not package_content:
                    return {
                        "all_available": True,
                        "missing_dependencies": [],
                        "message": "No package manifest found, skipping dependency check"
                    }

                missing = self.dependency_checker.check_dependencies(
                    code,
                    package_content,
                    language
                )

                return {
                    "all_available": len(missing) == 0,
                    "missing_dependencies": missing
                }

            elif tool_name == "build_code":
                files = tool_input['files']
                result = self.build_runner.build(files)
                return result

            elif tool_name == "run_tests":
                files = tool_input['files']
                result = self.test_runner.run_tests(files)
                return result

            else:
                return {
                    "error": f"Unknown tool: {tool_name}",
                    "success": False
                }

        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return {
                "error": str(e),
                "success": False
            }

    def _load_package_manifest(
        self,
        repo_full_name: str,
        branch: str,
        file_contents: Dict[str, str]
    ):
        """Load package manifests for dependency checking"""
        # Check if package.json already in file_contents
        if 'package.json' in file_contents:
            self.package_manifest_cache['javascript'] = file_contents['package.json']
            self.package_manifest_cache['typescript'] = file_contents['package.json']
        else:
            # Try to load package.json
            try:
                package_json = self.github_client.get_file_content(
                    repo_full_name, 'package.json', ref=branch
                )
                self.package_manifest_cache['javascript'] = package_json
                self.package_manifest_cache['typescript'] = package_json
            except Exception:
                logger.debug("No package.json found")

        # Check if requirements.txt already in file_contents
        if 'requirements.txt' in file_contents:
            self.package_manifest_cache['python'] = file_contents['requirements.txt']
        else:
            # Try to load requirements.txt
            try:
                requirements_txt = self.github_client.get_file_content(
                    repo_full_name, 'requirements.txt', ref=branch
                )
                self.package_manifest_cache['python'] = requirements_txt
            except Exception:
                logger.debug("No requirements.txt found")

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

    def _refine_with_validation_feedback(
        self,
        fix_result: Dict[str, Any],
        validation_results: Dict[str, Any],
        file_contents: Dict[str, str],
        analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Retry fix generation with structured validation feedback.
        Uses validation results to guide the LLM to fix specific issues.
        """
        checks_failed = validation_results.get('checks_failed', [])
        warnings = validation_results.get('warnings', [])

        # Build detailed feedback
        feedback = "## Validation Failures\n\n"
        feedback += "Your previous fix has the following validation errors that MUST be fixed:\n\n"

        for check in checks_failed:
            feedback += f"- {check}\n"

        if warnings:
            feedback += "\n## Warnings\n\n"
            for warning in warnings:
                feedback += f"- {warning}\n"

        # Build context
        fix_json = json.dumps({
            'files_to_modify': fix_result.get('files_to_modify', []),
            'files_to_create': fix_result.get('files_to_create', []),
            'summary': fix_result.get('summary', ''),
        }, indent=2)

        file_context = ''
        for path, content in file_contents.items():
            lang = self._detect_language(path)
            file_context += f"\n### Current file: {path}\n```{lang}\n{content}\n```\n"

        refinement_prompt = f"""{feedback}

## Your Previous Fix
```json
{fix_json}
```

## Current File Content
{file_context}

## Instructions

Fix ALL the validation errors above:

1. **Syntax Errors**: Fix any syntax errors in the code. The error messages include line numbers.

2. **Missing Dependencies**:
   - If a module is missing, add it to the appropriate change entry
   - For Python: add to requirements.txt or use a built-in alternative
   - For JavaScript: add to package.json or use a built-in alternative
   - OR add an import/require statement if the module already exists

3. **Code Quality**:
   - Remove TODO/FIXME comments - complete the implementation
   - Remove debug statements (console.log, print) unless needed for production logging

4. **Tests**:
   - If tests are missing, add a test file with proper syntax
   - Ensure test files have all required imports
   - Include test dependencies in the package manifest if needed

Return the COMPLETE corrected fix in JSON format with:
- All syntax errors fixed
- All missing dependencies resolved
- All validation issues addressed
- The same structure: files_to_modify, files_to_create, summary, confidence, testing_notes
"""

        logger.info("Calling Bedrock for fix refinement with validation feedback...")
        response = self.bedrock_client.invoke_model(
            system_prompt=(
                "You are an expert software engineer fixing validation errors in a code fix. "
                "The previous fix had syntax errors, missing dependencies, or other validation issues. "
                "Fix ALL validation errors while preserving the original fix intent. "
                "Ensure the code is syntactically correct and all dependencies are available. "
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
            logger.warning("Fix refinement failed to parse, using original fix")
            return fix_result

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
