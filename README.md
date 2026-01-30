# Issue Fix Action

A GitHub Action that automatically analyzes GitHub issues (created by the SRE Remediation Agent) and generates code fixes, then creates Pull Requests.

## Overview

This action is part of the Agentic SRE auto-remediation system. When the Remediation Agent identifies that an incident requires a code fix, it creates a GitHub issue. The Issue Agent then:

1. **Analyzes** the issue to understand the root cause and required fix
2. **Generates** the code fix using AWS Bedrock (Claude)
3. **Creates** a Pull Request with the fix
4. **Triggers** the PR Review Agent to review the PR

## Architecture

```
GitHub Issue (created by Remediation Agent)
    ↓
Issue Agent (this action)
    ├─ Analyzes issue context
    ├─ Generates code fix
    └─ Creates PR
        ↓
PR Review Agent (pr-code-review-action)
    └─ Reviews and approves PR
```

## Usage

### Basic Setup

Add this workflow to your service repository (e.g., `poc-payment-service`):

```yaml
# .github/workflows/auto-fix.yml
name: Auto-Fix from Issues

on:
  issues:
    types: [opened, labeled]

jobs:
  analyze-and-fix:
    runs-on: ubuntu-latest
    # Only run if issue has 'auto-fix' label or was created by bot
    if: |
      contains(github.event.issue.labels.*.name, 'auto-fix') ||
      github.event.issue.user.type == 'Bot'
    
    permissions:
      contents: write
      pull-requests: write
      issues: write
      id-token: write  # For AWS Bedrock access
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for better code analysis
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          pip install -r .github/agents/requirements.txt
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ secrets.AWS_REGION || 'us-east-1' }}
      
      - name: Run Issue Agent
        env:
          BEDROCK_MODEL_ID: ${{ secrets.BEDROCK_MODEL_ID || 'anthropic.claude-3-5-sonnet-20240620-v1:0' }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
          REPOSITORY: ${{ github.repository }}
        run: |
          python .github/agents/issue_agent.py \
            --issue-number $ISSUE_NUMBER \
            --repo $REPOSITORY \
            --output-dir ./agent-output
      
      - name: Create PR if fix generated
        if: success() && hashFiles('agent-output/*.patch') != ''
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python .github/agents/create_pr.py \
            --issue-number $ISSUE_NUMBER \
            --repo $REPOSITORY \
            --fix-dir ./agent-output
```

### Required Secrets

- `AWS_ROLE_ARN`: IAM role ARN for Bedrock access (with OIDC)
- `AWS_REGION`: AWS region (default: us-east-1)
- `BEDROCK_MODEL_ID`: Bedrock model ID (default: Claude 3.5 Sonnet)
- `GITHUB_TOKEN`: Auto-provided by GitHub Actions

## How It Works

### 1. Issue Analysis

The agent reads the GitHub issue and extracts:
- Root cause description
- Error patterns
- Affected service/component
- Recommended fix
- Relevant log entries
- Incident context

### 2. Code Analysis

The agent analyzes the repository:
- Identifies affected files
- Understands code structure
- Locates where the fix should be applied

### 3. Fix Generation

Using AWS Bedrock (Claude), the agent:
- Generates the code fix (single LLM call)
- Creates tests if needed
- Updates documentation
- Ensures code follows best practices

### 4. Validation (New!)

After fix generation, validation checks run automatically:
- **Syntax validation** - AST parsing for Python, JavaScript, TypeScript
- **Dependency checking** - Ensures all imports exist in package.json/requirements.txt
- **Test coverage** - Checks if test files are included
- **Code quality** - Detects TODO/FIXME, console.log, etc.

**Zero API Cost**: All validation uses local tools (no additional LLM calls)

### 5. PR Creation

The agent:
- Creates a new branch
- Applies the fix
- Commits changes
- Creates a PR with:
  - Detailed description
  - **Validation results** (new!)
  - Link to original issue
- Posts validation results as issue comment for PR Review Agent

### Validation Results Sharing

Validation results are shared in two places:
1. **PR Body** - Full validation report in the PR description
2. **Issue Comment** - Dedicated comment for PR Review Agent to see

Example validation comment:
```markdown
## 🔍 Validation Results for PR #123

**Summary:** 3 passed, 1 failed, 1 warnings

### ✅ Checks Passed
- ✓ Syntax valid: src/config/database.js
- ✓ All dependencies available
- ✓ Test file included

### ❌ Checks Failed
- ✗ Syntax error in src/index.js: Line 5

### ⚠️ Warnings
- ⚠ Code contains TODO comments
```

## Example Issue Format

Issues created by the Remediation Agent should follow this format:

```markdown
## Incident: chat-1769230875-d496d010

### Service
payment-service

### Root Cause
Database connection timeout in payment-service Lambda function due to misconfigured connection settings

### Error Patterns
- Database connection timeout
- ERROR: Database connection timeout

### Recommended Fix
Adjust database connection pool and timeout settings in the payment-service Lambda function

### Relevant Logs
[Log entries here]

### Context
- Incident Time: 2026-01-24T05:01:10
- Confidence: 75%
- Category: TIMEOUT
```

## Cost Estimation

Each issue analysis uses **exactly 1 API call** to AWS Bedrock:
- 1 call for issue analysis and fix generation
- Validation runs locally (zero API cost)

| Monthly Issues | Estimated Cost |
| -------------- | -------------- |
| 10 issues      | $0.20-0.60     |
| 50 issues      | $1.00-3.00     |
| 100 issues     | $2.00-6.00     |

**Per Issue Cost**: ~$0.02-0.06 (varies by issue complexity)
**Validation Cost**: $0 (tool-based, no LLM calls)

### Cost Improvements
- **Single LLM call** (no refinement loop) = up to 50% cost reduction
- **Zero validation cost** (AST parsing instead of LLM) = additional savings
- **Faster execution** (<1s validation vs 5-10s LLM refinement)

## Development

### Local Testing

```bash
# Set environment variables
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1
export GITHUB_TOKEN=...
export ISSUE_NUMBER=1
export REPOSITORY=parimalpate123/poc-payment-service

# Run issue agent
python src/agents/issue_agent.py \
  --issue-number $ISSUE_NUMBER \
  --repo $REPOSITORY \
  --output-dir ./output
```

### Project Structure

```
issue-fix-action/
├── .github/
│   └── workflows/
│       └── issue-agent.yml          # Main workflow
├── src/
│   ├── agents/
│   │   ├── issue_analyzer.py        # Analyzes GitHub issues
│   │   ├── fix_generator.py         # Generates code fixes (single LLM call)
│   │   └── pr_creator.py            # Creates PRs with validation results
│   ├── validators/                   # NEW: Validation infrastructure
│   │   ├── syntax_validator.py      # AST-based syntax validation
│   │   └── dependency_checker.py    # Import/dependency validation
│   ├── llm/
│   │   └── bedrock.py               # AWS Bedrock client
│   ├── prompts/
│   │   ├── issue_analysis.md        # Issue analysis prompt
│   │   └── fix_generation.md        # Code generation prompt
│   └── utils/
│       ├── github_client.py          # GitHub API client
│       └── code_analyzer.py          # Code analysis utilities
├── examples/
│   └── workflow-usage.yml            # Example workflow
├── test_validators.py                # NEW: Validator tests
├── VALIDATION_IMPLEMENTATION.md      # NEW: Implementation details
├── IMPLEMENTATION_SUMMARY.md         # NEW: Change summary
├── README.md
└── requirements.txt
```

## Integration with PR Review Agent

After the Issue Agent creates a PR, the PR Review Agent (from `pr-code-review-action`) automatically reviews it:

1. Issue Agent creates PR → Triggers PR Review Agent
2. PR Review Agent reviews the fix
3. If approved, PR can be merged (manually or automatically)

## License

MIT

## Contributing

1. Fork the repo
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open Pull Request

---

Built with ❤️ using Claude Sonnet via AWS Bedrock
