# Issue Fix Action - Architecture

## Overview

The Issue Fix Action is a GitHub Action that automatically analyzes GitHub issues (created by the SRE Remediation Agent) and generates code fixes, then creates Pull Requests.

## Architecture Diagram

```
┌─────────────────────────────────────────┐
│   Remediation Agent (Lambda)            │
│   - Creates GitHub Issue                │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│   GitHub Issue (with auto-fix label)    │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│   Issue Agent (GitHub Action)           │
│   ┌───────────────────────────────────┐ │
│   │ 1. Issue Analyzer                 │ │
│   │    - Reads issue                  │ │
│   │    - Analyzes root cause          │ │
│   │    - Identifies affected files    │ │
│   └──────────────┬────────────────────┘ │
│                  ▼                       │
│   ┌───────────────────────────────────┐ │
│   │ 2. Fix Generator                  │ │
│   │    - Reads code files             │ │
│   │    - Generates fix via Bedrock    │ │
│   │    - Creates code changes        │ │
│   └──────────────┬────────────────────┘ │
│                  ▼                       │
│   ┌───────────────────────────────────┐ │
│   │ 3. PR Creator                     │ │
│   │    - Creates branch               │ │
│   │    - Applies changes              │ │
│   │    - Creates PR                  │ │
│   └──────────────┬────────────────────┘ │
└──────────────────┼───────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│   Pull Request (auto-fix branch)        │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│   PR Review Agent (pr-code-review-action)│
│   - Reviews PR                          │
│   - Approves/Merges                     │
└─────────────────────────────────────────┘
```

## Components

### 1. Issue Analyzer (`src/agents/issue_analyzer.py`)

**Purpose**: Analyzes GitHub issues to understand the problem and determine fix strategy.

**Inputs**:
- GitHub issue number
- Repository name

**Process**:
1. Fetches issue details from GitHub API
2. Extracts service name, root cause, error patterns
3. Identifies relevant files in repository
4. Calls Bedrock to analyze issue and determine fix strategy

**Outputs**:
- Root cause analysis
- Affected component identification
- Fix type (bug_fix, config_change, error_handling, etc.)
- List of affected files
- Fix strategy

**Key Methods**:
- `analyze_issue(repo, issue_number)`: Main analysis method

### 2. Fix Generator (`src/agents/fix_generator.py`)

**Purpose**: Generates code fixes based on issue analysis.

**Inputs**:
- Issue analysis result
- Repository name
- Branch name (to read code from)

**Process**:
1. Reads affected file contents from GitHub
2. Builds fix generation prompt with code context
3. Calls Bedrock to generate fix
4. Parses fix response (file changes, new files)

**Outputs**:
- Files to modify (with line-by-line changes)
- Files to create
- Fix summary
- Testing notes

**Key Methods**:
- `generate_fix(repo, analysis, branch)`: Main fix generation method

### 3. PR Creator (`src/agents/pr_creator.py`)

**Purpose**: Creates Pull Requests with generated fixes.

**Inputs**:
- Issue number
- Fix result
- Repository name

**Process**:
1. Creates new branch (`fix/issue-{number}`)
2. Applies file changes (modify existing, create new)
3. Creates Pull Request with description
4. Adds comment to original issue

**Outputs**:
- PR number and URL
- Branch name
- List of modified/created files

**Key Methods**:
- `create_pr_with_fix(repo, issue_number, fix_result)`: Main PR creation method

### 4. Bedrock Client (`src/llm/bedrock.py`)

**Purpose**: AWS Bedrock API client with retry logic.

**Features**:
- Exponential backoff for throttling
- Configurable model ID
- Error handling

**Key Methods**:
- `invoke_model(system_prompt, user_prompt, ...)`: Invoke Bedrock model
- `get_response_text(response)`: Extract text from response

### 5. GitHub Client (`src/utils/github_client.py`)

**Purpose**: GitHub API client for repository operations.

**Features**:
- Issue management
- File operations
- Branch creation
- PR creation
- Comments

**Key Methods**:
- `get_issue(repo, issue_number)`: Get issue details
- `get_file_content(repo, file_path, ref)`: Read file
- `create_branch(repo, branch_name, base)`: Create branch
- `create_or_update_file(...)`: Modify/create files
- `create_pull_request(...)`: Create PR

## Data Flow

### Issue Analysis Flow

```
GitHub Issue
    ↓
Issue Analyzer
    ├─ Fetch issue → GitHub API
    ├─ Get repo files → GitHub API
    └─ Analyze → Bedrock API
        ↓
Analysis Result (JSON)
```

### Fix Generation Flow

```
Analysis Result
    ↓
Fix Generator
    ├─ Read affected files → GitHub API
    ├─ Build prompt (with code context)
    └─ Generate fix → Bedrock API
        ↓
Fix Result (JSON with code changes)
```

### PR Creation Flow

```
Fix Result
    ↓
PR Creator
    ├─ Create branch → GitHub API
    ├─ Apply changes → GitHub API
    ├─ Create PR → GitHub API
    └─ Comment on issue → GitHub API
        ↓
Pull Request
```

## Integration Points

### With Remediation Agent

The Remediation Agent (in `agentic-sre`) creates GitHub issues with:
- Root cause description
- Service name
- Error patterns
- Recommended fix
- Incident context

### With PR Review Agent

After PR creation, the PR Review Agent (from `pr-code-review-action`) automatically:
- Reviews the PR
- Validates the fix
- Approves or requests changes

## Error Handling

### Bedrock API Errors

- **ThrottlingException**: Retry with exponential backoff (up to 5 retries)
- **InvalidRequestException**: Log error, return fallback response
- **Other errors**: Log and fail gracefully

### GitHub API Errors

- **Rate limiting**: Retry with backoff
- **Permission errors**: Log and fail
- **File not found**: Skip file, continue with others

### Parsing Errors

- **JSON parsing failures**: Return fallback structure
- **Missing fields**: Use defaults
- **Invalid data**: Log warning, continue

## Configuration

### Environment Variables

- `GITHUB_TOKEN`: GitHub API token (auto-provided in Actions)
- `BEDROCK_MODEL_ID`: Bedrock model ID (default: Claude 3.5 Sonnet)
- `AWS_REGION`: AWS region (default: us-east-1)
- `ISSUE_NUMBER`: Issue number to process
- `REPOSITORY`: Repository name (org/repo)

### Secrets (GitHub Actions)

- `AWS_ROLE_ARN`: IAM role for Bedrock access
- `AWS_REGION`: AWS region
- `BEDROCK_MODEL_ID`: (Optional) Model ID override

## Cost Estimation

### Per Issue Processing

- **Issue Analysis**: 1 Bedrock API call (~$0.01-0.03)
- **Fix Generation**: 1 Bedrock API call (~$0.01-0.03)
- **Total per issue**: ~$0.02-0.06

### Monthly Estimates

| Issues/Month | Estimated Cost |
|--------------|----------------|
| 10           | $0.20-0.60     |
| 50           | $1.00-3.00     |
| 100          | $2.00-6.00     |

## Security Considerations

1. **GitHub Token**: Auto-provided by GitHub Actions (read-only for public repos, write for private)
2. **AWS Credentials**: OIDC-based authentication (no long-lived keys)
3. **Code Access**: Only reads/writes files in the repository
4. **PR Permissions**: Requires `pull-requests: write` permission

## Future Enhancements

1. **Multi-file fixes**: Support for complex fixes across multiple files
2. **Test generation**: Automatic test creation for fixes
3. **Documentation updates**: Auto-update docs when code changes
4. **Fix validation**: Pre-commit checks before PR creation
5. **Rollback support**: Automatic rollback if fix causes issues
