"""
Test Runner
Runs unit tests in a sandbox
"""

import subprocess
import tempfile
import os
import json
import re
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class TestRunner:
    """Runs tests in a temporary directory sandbox"""

    def run_tests(self, files: Dict[str, str], test_command: str = None) -> Dict[str, Any]:
        """
        Run tests in a temporary directory sandbox

        Args:
            files: Map of file paths to contents (including test files)
            test_command: Optional test command. Auto-detected if not provided.

        Returns:
            Test result with pass/fail status and output
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                # Write files to temp directory
                for file_path, content in files.items():
                    full_path = os.path.join(tmpdir, file_path)
                    os.makedirs(os.path.dirname(full_path) or tmpdir, exist_ok=True)
                    with open(full_path, 'w') as f:
                        f.write(content)

                # Auto-detect test command if not provided
                if not test_command:
                    test_command = self._detect_test_command(files)

                if not test_command:
                    return {
                        "passed": True,
                        "skipped": True,
                        "message": "No tests found or test framework not configured"
                    }

                # Install dependencies first
                install_result = self._install_dependencies(tmpdir, files)
                if not install_result['success']:
                    return {
                        "passed": False,
                        "failed": True,
                        "stage": "dependency_install",
                        "stdout": install_result.get('stdout', ''),
                        "stderr": install_result.get('stderr', ''),
                        "error": "Failed to install dependencies"
                    }

                # Run tests
                logger.info(f"Running test command: {test_command}")
                result = subprocess.run(
                    test_command,
                    shell=True,
                    cwd=tmpdir,
                    capture_output=True,
                    timeout=180,  # 3 minutes for tests
                    text=True
                )

                passed = result.returncode == 0
                summary = self._parse_test_summary(result.stdout + result.stderr)

                return {
                    "passed": passed,
                    "failed": not passed,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                    "summary": summary,
                    "command": test_command
                }

            except subprocess.TimeoutExpired:
                return {
                    "passed": False,
                    "failed": True,
                    "error": "Tests timeout after 180 seconds",
                    "stderr": "Test execution timed out"
                }
            except Exception as e:
                logger.error(f"Test execution failed: {e}")
                return {
                    "passed": False,
                    "failed": True,
                    "error": str(e),
                    "stderr": str(e)
                }

    def _detect_test_command(self, files: Dict[str, str]) -> str:
        """Auto-detect appropriate test command based on project files"""

        # Node.js/JavaScript projects
        if 'package.json' in files:
            try:
                pkg = json.loads(files['package.json'])
                scripts = pkg.get('scripts', {})

                # Check for test script
                if 'test' in scripts:
                    return 'npm test'
            except json.JSONDecodeError:
                pass

            # Check for specific test files
            test_files = [f for f in files.keys() if self._is_test_file(f)]
            if test_files:
                # Jest
                if any('jest' in files.get('package.json', '').lower()):
                    return f'npx jest {test_files[0]}'
                # Mocha
                elif any('mocha' in files.get('package.json', '').lower()):
                    return f'npx mocha {test_files[0]}'
                # Generic
                else:
                    return 'npm test'

        # Python projects
        if any(f.endswith('.py') for f in files.keys()):
            test_files = [f for f in files.keys() if self._is_test_file(f)]
            if test_files:
                # pytest
                return f'pytest {test_files[0]} -v'

        # No tests found
        return None

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file"""
        test_patterns = [
            r'.*\.test\.(js|ts|jsx|tsx)$',
            r'.*\.spec\.(js|ts|jsx|tsx)$',
            r'test_.*\.py$',
            r'.*_test\.py$',
        ]
        return any(re.match(pattern, file_path) for pattern in test_patterns)

    def _install_dependencies(self, tmpdir: str, files: Dict[str, str]) -> Dict[str, Any]:
        """Install dependencies before running tests"""
        try:
            if 'package.json' in files:
                # Node.js project
                logger.info("Installing npm dependencies...")
                result = subprocess.run(
                    ['npm', 'install', '--legacy-peer-deps'],
                    cwd=tmpdir,
                    capture_output=True,
                    timeout=180,
                    text=True
                )
                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }

            elif 'requirements.txt' in files:
                # Python project
                logger.info("Installing pip dependencies...")
                result = subprocess.run(
                    ['pip', 'install', '-r', 'requirements.txt', '--quiet'],
                    cwd=tmpdir,
                    capture_output=True,
                    timeout=180,
                    text=True
                )
                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }

            return {"success": True}

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Dependency installation timeout"
            }
        except FileNotFoundError:
            logger.warning("Package manager not found, skipping dependency install")
            return {"success": True, "skipped": True}
        except Exception as e:
            logger.error(f"Dependency installation failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _parse_test_summary(self, output: str) -> str:
        """Parse test output to extract summary"""
        # Jest output
        jest_pattern = r'Tests:\s+(\d+)\s+passed,\s+(\d+)\s+total'
        match = re.search(jest_pattern, output)
        if match:
            return f"{match.group(1)} passed, {match.group(2)} total"

        # Jest failure pattern
        jest_fail_pattern = r'Tests:\s+(\d+)\s+failed,\s+(\d+)\s+passed,\s+(\d+)\s+total'
        match = re.search(jest_fail_pattern, output)
        if match:
            return f"{match.group(2)} passed, {match.group(1)} failed, {match.group(3)} total"

        # Pytest output
        pytest_pattern = r'(\d+)\s+passed'
        match = re.search(pytest_pattern, output)
        if match:
            return f"{match.group(1)} passed"

        # Pytest failure pattern
        pytest_fail_pattern = r'(\d+)\s+failed,\s+(\d+)\s+passed'
        match = re.search(pytest_fail_pattern, output)
        if match:
            return f"{match.group(2)} passed, {match.group(1)} failed"

        # Mocha output
        mocha_pattern = r'(\d+)\s+passing'
        match = re.search(mocha_pattern, output)
        if match:
            return f"{match.group(1)} passing"

        # Generic pattern
        if 'PASS' in output:
            return "Tests passed"
        elif 'FAIL' in output:
            return "Tests failed"

        return "See output for details"
