# Complete Workflow: Generate, Build, Test, Fix

## The Right Approach

The issue-fix-agent should:

1. **Generate fix + unit tests** (always include tests)
2. **Build the code** (npm build, python compile, etc.)
3. **Run the tests** (npm test, pytest, etc.)
4. **If build/test fails → Fix and try again**
5. **Only return when tests pass**

All in **ONE LLM call** using tools!

## Workflow

```
LLM: Generate Fix
  ↓
LLM: Generate Unit Tests (proves fix works)
  ↓
LLM: <calls build_code tool>
  ↓
Build Success? ──No──→ LLM: Fix build errors → Retry build
  ↓ Yes
LLM: <calls run_tests tool>
  ↓
Tests Pass? ──No──→ LLM: Fix failing tests → Retry tests
  ↓ Yes
LLM: Return validated, tested fix ✅
```

**All in ONE API call!** LLM has tools available during generation.

## Tools for Complete Validation

### 1. Syntax Validation
```python
{
    "name": "validate_syntax",
    "description": "Check code syntax using AST parsing",
    "input_schema": {
        "code": "string",
        "language": "python|javascript|typescript"
    }
}
```

### 2. Build Code
```python
{
    "name": "build_code",
    "description": "Build/compile the code to check for build errors",
    "input_schema": {
        "files": {
            "type": "object",
            "description": "Map of file paths to contents"
        },
        "language": "python|javascript|typescript"
    }
}
```

### 3. Run Tests
```python
{
    "name": "run_tests",
    "description": "Execute unit tests and return results. Use this to verify your fix works.",
    "input_schema": {
        "test_file": "string",
        "test_command": "string"  # e.g., "npm test", "pytest"
    }
}
```

### 4. Check Dependencies
```python
{
    "name": "check_dependencies",
    "description": "Verify all imports exist in package manifest"
}
```

## Implementation

### Tool Definitions

```python
# src/agents/fix_generator.py

VALIDATION_TOOLS = [
    {
        "name": "validate_syntax",
        "description": "Validate code syntax using AST parsing",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "language": {"type": "string", "enum": ["python", "javascript", "typescript"]}
            },
            "required": ["code", "language"]
        }
    },
    {
        "name": "build_code",
        "description": "Build/compile the code in a sandbox. Returns build output and any errors. Use this before running tests.",
        "input_schema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "object",
                    "description": "Map of file paths to file contents to build"
                },
                "build_command": {
                    "type": "string",
                    "description": "Build command (e.g., 'npm run build', 'python -m py_compile')"
                }
            },
            "required": ["files", "build_command"]
        }
    },
    {
        "name": "run_tests",
        "description": "Execute unit tests in a sandbox and return test results. Use this to verify your fix actually works.",
        "input_schema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "object",
                    "description": "Map of file paths to file contents (including test files)"
                },
                "test_command": {
                    "type": "string",
                    "description": "Test command (e.g., 'npm test', 'pytest test_file.py')"
                }
            },
            "required": ["files", "test_command"]
        }
    },
    {
        "name": "check_dependencies",
        "description": "Check if all imports/requires are available",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "package_file": {"type": "string"},
                "language": {"type": "string"}
            },
            "required": ["code", "package_file", "language"]
        }
    }
]
```

### Tool Executor

```python
# src/agents/fix_generator.py

def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool requested by the LLM"""

    if tool_name == "validate_syntax":
        from ..validators.syntax_validator import SyntaxValidator
        validator = SyntaxValidator()
        return validator.validate(
            f"temp.{tool_input['language']}",
            tool_input['code']
        )

    elif tool_name == "build_code":
        from ..validators.build_runner import BuildRunner
        builder = BuildRunner()
        return builder.build(
            tool_input['files'],
            tool_input['build_command']
        )

    elif tool_name == "run_tests":
        from ..validators.test_runner import TestRunner
        runner = TestRunner()
        return runner.run_tests(
            tool_input['files'],
            tool_input['test_command']
        )

    elif tool_name == "check_dependencies":
        from ..validators.dependency_checker import DependencyChecker
        checker = DependencyChecker()
        missing = checker.check_dependencies(
            tool_input['code'],
            tool_input['package_file'],
            tool_input['language']
        )
        return {
            "missing_dependencies": missing,
            "all_available": len(missing) == 0
        }
```

### Build Runner (New Validator)

```python
# src/validators/build_runner.py

import subprocess
import tempfile
import os
from typing import Dict, Any

class BuildRunner:
    """Runs build in a sandbox"""

    def build(self, files: Dict[str, str], build_command: str) -> Dict[str, Any]:
        """
        Build code in a temporary directory sandbox

        Args:
            files: Map of file paths to contents
            build_command: Build command to execute

        Returns:
            Build result with success status and output
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write files to temp directory
            for file_path, content in files.items():
                full_path = os.path.join(tmpdir, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w') as f:
                    f.write(content)

            # Run build command
            try:
                result = subprocess.run(
                    build_command,
                    shell=True,
                    cwd=tmpdir,
                    capture_output=True,
                    timeout=60,
                    text=True
                )

                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode
                }
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "error": "Build timeout (60s)",
                    "stderr": "Build command timed out after 60 seconds"
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "stderr": str(e)
                }
```

### Test Runner (New Validator)

```python
# src/validators/test_runner.py

import subprocess
import tempfile
import os
from typing import Dict, Any

class TestRunner:
    """Runs tests in a sandbox"""

    def run_tests(self, files: Dict[str, str], test_command: str) -> Dict[str, Any]:
        """
        Run tests in a temporary directory sandbox

        Args:
            files: Map of file paths to contents (including test files)
            test_command: Test command to execute

        Returns:
            Test result with pass/fail status and output
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write files to temp directory
            for file_path, content in files.items():
                full_path = os.path.join(tmpdir, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w') as f:
                    f.write(content)

            # Install dependencies first (if package.json or requirements.txt exists)
            self._install_dependencies(tmpdir, files)

            # Run tests
            try:
                result = subprocess.run(
                    test_command,
                    shell=True,
                    cwd=tmpdir,
                    capture_output=True,
                    timeout=120,  # 2 minutes for tests
                    text=True
                )

                # Parse test output
                passed = result.returncode == 0

                return {
                    "passed": passed,
                    "failed": not passed,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                    "summary": self._parse_test_summary(result.stdout)
                }
            except subprocess.TimeoutExpired:
                return {
                    "passed": False,
                    "failed": True,
                    "error": "Tests timeout (120s)",
                    "stderr": "Test execution timed out after 120 seconds"
                }
            except Exception as e:
                return {
                    "passed": False,
                    "failed": True,
                    "error": str(e),
                    "stderr": str(e)
                }

    def _install_dependencies(self, tmpdir: str, files: Dict[str, str]):
        """Install dependencies before running tests"""
        if 'package.json' in files:
            # Node.js project
            subprocess.run(['npm', 'install'], cwd=tmpdir, timeout=120)
        elif 'requirements.txt' in files:
            # Python project
            subprocess.run(['pip', 'install', '-r', 'requirements.txt'], cwd=tmpdir, timeout=120)

    def _parse_test_summary(self, output: str) -> str:
        """Parse test output to extract summary"""
        # Look for common test framework output patterns
        if 'PASS' in output or 'FAIL' in output:
            # Jest/npm test output
            for line in output.split('\n'):
                if 'Tests:' in line or 'Test Suites:' in line:
                    return line.strip()
        elif 'passed' in output or 'failed' in output:
            # pytest output
            for line in output.split('\n'):
                if 'passed' in line or 'failed' in line:
                    return line.strip()

        return "See full output for details"
```

### Updated System Prompt

```python
system_prompt = """You are an expert software engineer generating code fixes for production incidents.

CRITICAL REQUIREMENTS:
1. ALWAYS generate unit tests for your fix
2. Use validation tools to ensure your code works
3. Only return the fix when ALL validation passes

PROCESS:
1. Analyze the issue and generate a fix
2. Generate unit tests that prove the fix works (REQUIRED)
3. Use validate_syntax to check for syntax errors
4. Use check_dependencies to verify imports
5. Use build_code to build the project
6. Use run_tests to execute the tests
7. If build or tests fail:
   - Analyze the error
   - Fix the code
   - Re-run build and tests
8. Only return the fix when:
   ✓ Syntax is valid
   ✓ All dependencies available
   ✓ Build succeeds
   ✓ Tests pass

Use tools multiple times if needed. Your goal is to return a working, tested fix."""
```

## Example: LLM Using Tools

```
User: Fix database timeout in payment service

LLM: I'll create a fix for the connection pool timeout...

     [generates fix code]
     [generates unit test]

     Let me validate this:
     <calls validate_syntax on fix code>

Tool: ✓ Syntax valid

LLM: <calls validate_syntax on test code>

Tool: ✓ Syntax valid

LLM: Now let me build the code:
     <calls build_code with all files>

Tool: ✗ Build failed: Cannot find module 'pg-pool'

LLM: I need to add pg-pool to package.json:
     [updates package.json in fix]

     <calls build_code with updated files>

Tool: ✓ Build successful

LLM: Great! Now let me run the tests to ensure the fix works:
     <calls run_tests with test command "npm test">

Tool: ✗ Tests failed:
      FAIL test/payment.test.js
        ● should handle null payment data
          Expected: timeout prevented
          Received: timeout still occurs

LLM: The test is failing because I need to add timeout handling:
     [updates code to add proper timeout]

     <calls build_code>

Tool: ✓ Build successful

LLM: <calls run_tests>

Tool: ✓ Tests passed:
      PASS test/payment.test.js
        ✓ should handle null payment data (45ms)
        ✓ should timeout gracefully (102ms)
      Tests: 2 passed, 2 total

LLM: Perfect! All validation passed. Here's the complete fix:
     {
       "files_to_modify": [
         {
           "path": "src/payment.js",
           "changes": [...]
         },
         {
           "path": "package.json",
           "changes": [...]
         }
       ],
       "files_to_create": [
         {
           "path": "test/payment.test.js",
           "content": "...",
           "explanation": "Unit tests proving the fix works"
         }
       ],
       "summary": "Fixed database timeout with proper connection pool settings",
       "testing_notes": "All tests passing (2 passed)",
       "confidence": 95
     }
```

## Validation Results Posted to PR

```markdown
## ✅ Validation Results for PR #123

**Summary:** All checks passed ✅

### Build Status
✓ Build successful

### Test Results
✓ All tests passed (2 passed, 0 failed)
- ✓ should handle null payment data (45ms)
- ✓ should timeout gracefully (102ms)

### Additional Checks
✓ Syntax valid: src/payment.js
✓ Syntax valid: test/payment.test.js
✓ All dependencies available

---
*✅ Fix validated with passing tests - ready for review*
```

## Benefits

| Validation Level | Confidence | What It Proves |
|-----------------|-----------|----------------|
| Syntax check | 60% | Code is parseable |
| Dependency check | 70% | Imports exist |
| Build success | 85% | Code compiles |
| **Tests pass** | **95%** | **Fix actually works!** |

## Cost Analysis

**Single LLM call with tools:**
- Generate fix: ~2000 tokens
- Generate tests: ~500 tokens
- Tool calls (build, test): ~1000 tokens
- Total: ~3500 tokens

**Cost per issue:** $0.05-0.10

**Value:** Fix is proven to work with passing tests!

## Summary

✅ Always generate unit tests
✅ Build the code in sandbox
✅ Run the tests
✅ If build/test fails, LLM fixes automatically
✅ Only return when tests pass
✅ All in ONE LLM call using tools

**This gives you a working, tested fix every time!**
