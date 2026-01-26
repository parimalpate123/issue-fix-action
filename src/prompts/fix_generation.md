# Fix Generation Prompt

You are an expert software engineer generating a code fix for a production incident.

## Context

A production incident has been identified and analyzed. You need to generate the specific code changes to fix the issue.

## Incident Details

**Root Cause**: {root_cause}

**Affected Component**: {affected_component}

**Fix Type**: {fix_type}

**Error Patterns**: {error_patterns}

**Service**: {service_name}

## Current Code

The affected file(s) are shown below. Analyze the code and generate the fix.

### File: {file_path}
```{language}
{file_content}
```

## Your Task

Generate the fix by:

1. **Identifying the Problem**: What specific function or code block is causing the issue?
2. **Designing the Fix**: What minimal changes are needed to resolve the issue?
3. **Implementing the Fix**: Provide the targeted code changes using old_code/new_code pairs
4. **Adding Tests** (if applicable): Create tests to verify the fix

## CRITICAL Rules — DO NOT VIOLATE

- **NEVER remove or rewrite the entire file.** Only modify the specific functions or code blocks that are broken.
- **NEVER remove existing API routes, HTTP endpoints, server setup, or module exports.** These are the application's public interface.
- **NEVER remove existing `require()` or `import` statements** unless they are directly causing the bug.
- **NEVER remove the server startup code** (e.g., `app.listen()`, `module.exports`).
- **The `old_code` field MUST contain the exact code being replaced** — copied verbatim from the current file. The system uses `old_code` to locate where to apply the change.
- **The `new_code` field MUST contain ONLY the replacement for `old_code`** — not the entire file.
- If you need to add new imports, create a separate change entry for the import lines.

## Fix Requirements

- **Minimal scope**: Only change the specific function or block that is broken. Leave everything else untouched.
- **Safety**: The fix must not break existing functionality, routes, or exports.
- **Best Practices**: Follow language-specific best practices.
- **Error Handling**: Add proper error handling if missing.
- **Backward Compatibility**: The application must continue to serve all existing endpoints after the fix.

## Output Format

Provide the fix in JSON format:

```json
{{
  "files_to_modify": [
    {{
      "path": "src/database.js",
      "changes": [
        {{
          "type": "modify",
          "line_start": 45,
          "line_end": 50,
          "old_code": "const pool = new Pool({{\\n  max: 10,\\n  timeout: 5000\\n}});",
          "new_code": "const pool = new Pool({{\\n  max: 20,\\n  timeout: 10000,\\n  idleTimeoutMillis: 30000\\n}});",
          "explanation": "Increased connection pool size and timeout to handle higher load"
        }}
      ]
    }}
  ],
  "files_to_create": [
    {{
      "path": "tests/database.test.js",
      "content": "// Test content here",
      "explanation": "Added tests for connection pool configuration"
    }}
  ],
  "summary": "Brief summary of the fix",
  "confidence": 90,
  "testing_notes": "How to test this fix"
}}
```

## Important Guidelines

- **Be Precise**: Only change the specific function or block that is broken. If the issue is in `processPayment()`, only change that function — do not touch routes, server setup, or other functions.
- **Preserve Application Structure**: The file's overall structure (imports, routes, exports, server startup) MUST remain intact. You are patching, not rewriting.
- **old_code must be exact**: Copy the old_code verbatim from the current file shown above. The system uses string matching to find and replace it.
- **new_code replaces old_code only**: The new_code replaces ONLY the old_code section. Everything outside old_code stays unchanged.
- **One change per concern**: If you need to add an import AND modify a function, use two separate change entries.
- **Follow Patterns**: Match existing code patterns, style, and conventions in the file.

## Example Fix Types

### Configuration Change (Database Connection Pool)
- Increase pool size
- Adjust timeout values
- Add retry logic
- Configure connection parameters

### Bug Fix
- Fix logic errors
- Correct data handling
- Fix race conditions
- Fix null/undefined handling

### Error Handling
- Add try-catch blocks
- Improve error messages
- Add error recovery
- Implement retry logic
