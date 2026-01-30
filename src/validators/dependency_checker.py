"""
Dependency Checker
Validates that all imports/requires are available
"""

import re
import json
import logging
from typing import List, Set

logger = logging.getLogger(__name__)


class DependencyChecker:
    """Checks if all imports/requires are available"""

    # Built-in modules that don't need to be in package files
    PYTHON_BUILTINS = {
        'os', 'sys', 're', 'json', 'time', 'datetime', 'collections',
        'itertools', 'functools', 'math', 'random', 'string', 'io',
        'logging', 'unittest', 'argparse', 'subprocess', 'pathlib',
        'typing', 'enum', 'dataclasses', 'abc', 'asyncio', 'threading',
        'multiprocessing', 'socket', 'http', 'urllib', 'email', 'base64',
        'hashlib', 'hmac', 'csv', 'tempfile', 'shutil', 'glob', 'fnmatch'
    }

    JAVASCRIPT_BUILTINS = {
        'fs', 'path', 'http', 'https', 'util', 'crypto', 'os', 'events',
        'stream', 'buffer', 'url', 'querystring', 'assert', 'child_process',
        'cluster', 'dgram', 'dns', 'net', 'readline', 'repl', 'tls', 'tty',
        'v8', 'vm', 'worker_threads', 'zlib', 'process', 'console'
    }

    def check_dependencies(
        self,
        file_content: str,
        package_file_content: str,
        language: str
    ) -> List[str]:
        """
        Check if all imports exist in package manifest

        Args:
            file_content: Content of the code file
            package_file_content: Content of package.json or requirements.txt
            language: Programming language (python, javascript, typescript)

        Returns:
            List of missing dependencies
        """
        try:
            imports = self._extract_imports(file_content, language)
            available = self._parse_package_file(package_file_content, language)

            missing = []
            for module in imports:
                if not self._is_available(module, available, language):
                    missing.append(module)

            return missing
        except Exception as e:
            logger.warning(f"Dependency check failed: {e}")
            return []

    def _extract_imports(self, content: str, language: str) -> Set[str]:
        """Extract imported modules from code"""
        imports = set()

        if language == 'python':
            # Match: import X, from X import Y, from X.Y import Z
            patterns = [
                r'^\s*import\s+([a-zA-Z0-9_\.]+)',
                r'^\s*from\s+([a-zA-Z0-9_\.]+)\s+import',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, content, re.MULTILINE)
                for match in matches:
                    # Get root module (before first dot)
                    root_module = match.split('.')[0]
                    imports.add(root_module)

        elif language in ['javascript', 'typescript']:
            # Match: require('X'), import X from 'Y', import { X } from 'Y'
            patterns = [
                r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
                r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]",
                r"import\s+['\"]([^'\"]+)['\"]",
            ]
            for pattern in patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    # Skip relative imports (./foo, ../bar)
                    if match.startswith('.'):
                        continue
                    # Get root module (before first /)
                    root_module = match.split('/')[0]
                    # Handle scoped packages (@org/package)
                    if root_module.startswith('@') and '/' in match:
                        root_module = '/'.join(match.split('/')[:2])
                    imports.add(root_module)

        return imports

    def _parse_package_file(self, content: str, language: str) -> Set[str]:
        """Parse package manifest file"""
        available = set()

        try:
            if language == 'python':
                # Parse requirements.txt
                for line in content.split('\n'):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # Remove version specifiers
                    module = re.split(r'[=<>!]', line)[0].strip()
                    available.add(module)

            elif language in ['javascript', 'typescript']:
                # Parse package.json
                try:
                    pkg = json.loads(content)
                    deps = pkg.get('dependencies', {})
                    dev_deps = pkg.get('devDependencies', {})
                    available = set(deps.keys()) | set(dev_deps.keys())
                except json.JSONDecodeError:
                    logger.warning("Failed to parse package.json")

        except Exception as e:
            logger.warning(f"Failed to parse package file: {e}")

        return available

    def _is_available(self, module: str, available: Set[str], language: str) -> bool:
        """Check if module is available (either builtin or in package manifest)"""
        # Check if it's a builtin module
        if language == 'python' and module in self.PYTHON_BUILTINS:
            return True
        elif language in ['javascript', 'typescript'] and module in self.JAVASCRIPT_BUILTINS:
            return True

        # Check if it's in the package manifest
        return module in available
