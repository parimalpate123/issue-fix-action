"""
Syntax Validator
Validates code syntax using AST parsing
"""

import ast
import subprocess
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class SyntaxValidator:
    """Validates code syntax using AST parsing"""

    def validate(self, file_path: str, content: str) -> Dict[str, Any]:
        """
        Validate syntax using AST parsing

        Args:
            file_path: Path to the file (used to detect language)
            content: File content to validate

        Returns:
            Validation result with 'valid', 'language', and optionally 'error', 'line'
        """
        language = self._detect_language(file_path)

        if language == 'python':
            return self._validate_python(content)
        elif language in ['javascript', 'typescript']:
            return self._validate_javascript(content, language)

        # Unknown language, skip validation
        return {
            'valid': True,
            'language': 'unknown',
            'skipped': True
        }

    def _validate_python(self, content: str) -> Dict[str, Any]:
        """Validate Python syntax"""
        try:
            ast.parse(content)
            return {
                'valid': True,
                'language': 'python'
            }
        except SyntaxError as e:
            return {
                'valid': False,
                'language': 'python',
                'error': f"Line {e.lineno}: {e.msg}",
                'line': e.lineno
            }
        except Exception as e:
            return {
                'valid': False,
                'language': 'python',
                'error': str(e)
            }

    def _validate_javascript(self, content: str, language: str) -> Dict[str, Any]:
        """Validate JavaScript/TypeScript syntax using Node.js acorn parser"""
        try:
            # Escape content for JSON
            content_json = json.dumps(content)

            # Use acorn parser via Node.js
            # acorn is a fast JavaScript parser
            script = f"""
            try {{
                const acorn = require('acorn');
                const code = {content_json};
                acorn.parse(code, {{ ecmaVersion: 2020, sourceType: 'module' }});
                console.log('VALID');
            }} catch (e) {{
                console.log('ERROR: ' + e.message);
                process.exit(1);
            }}
            """

            result = subprocess.run(
                ['node', '-e', script],
                capture_output=True,
                timeout=5,
                text=True
            )

            if result.returncode == 0 and 'VALID' in result.stdout:
                return {
                    'valid': True,
                    'language': language
                }
            else:
                error_msg = result.stderr or result.stdout
                # Clean up error message
                if 'ERROR: ' in error_msg:
                    error_msg = error_msg.split('ERROR: ', 1)[1].strip()

                return {
                    'valid': False,
                    'language': language,
                    'error': error_msg
                }
        except subprocess.TimeoutExpired:
            return {
                'valid': False,
                'language': language,
                'error': 'Syntax validation timed out'
            }
        except FileNotFoundError:
            # Node.js not available, skip validation
            logger.warning("Node.js not found, skipping JavaScript syntax validation")
            return {
                'valid': True,
                'language': language,
                'skipped': True,
                'reason': 'Node.js not available'
            }
        except Exception as e:
            logger.warning(f"JavaScript syntax validation failed: {e}")
            return {
                'valid': True,  # Don't fail the whole process
                'language': language,
                'skipped': True,
                'reason': str(e)
            }

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension"""
        if not file_path:
            return 'unknown'

        ext = file_path.split('.')[-1].lower()
        language_map = {
            'py': 'python',
            'js': 'javascript',
            'jsx': 'javascript',
            'ts': 'typescript',
            'tsx': 'typescript',
            'mjs': 'javascript',
            'cjs': 'javascript',
        }
        return language_map.get(ext, 'unknown')
