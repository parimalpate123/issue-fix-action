# Setup Guide for Issue Fix Action

This guide will help you set up the Issue Fix Action in your service repositories.

## Prerequisites

1. **GitHub Repository**: Your service repository (e.g., `poc-payment-service`)
2. **AWS Account**: With Bedrock access configured
3. **GitHub Token**: For API access (automatically provided in GitHub Actions)
4. **AWS IAM Role**: With Bedrock permissions (for OIDC authentication)

## Step 1: Create GitHub Repository

If you haven't already, create the `issue-fix-action` repository:

```bash
cd /path/to/agentic-sre
cd issue-fix-action
git init
git add .
git commit -m "Initial commit: Issue Fix Action"
git remote add origin https://github.com/parimalpate123/issue-fix-action.git
git push -u origin main
```

## Step 2: Configure Service Repository

For each service repository (e.g., `poc-payment-service`), add the workflow:

### 2.1 Create Workflow File

Create `.github/workflows/auto-fix.yml` in your service repository:

```yaml
name: Auto-Fix from Issues

on:
  issues:
    types: [opened, labeled]
  workflow_dispatch:
    inputs:
      issue_number:
        description: 'Issue number to process'
        required: true
        type: string

jobs:
  analyze-and-fix:
    runs-on: ubuntu-latest
    if: |
      contains(github.event.issue.labels.*.name, 'auto-fix') ||
      github.event.issue.user.type == 'Bot' ||
      github.event_name == 'workflow_dispatch'
    
    permissions:
      contents: write
      pull-requests: write
      issues: write
      id-token: write
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      
      - name: Install Issue Agent
        run: |
          git clone https://github.com/parimalpate123/issue-fix-action.git /tmp/issue-fix-action
          cd /tmp/issue-fix-action
          pip install -r requirements.txt
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ secrets.AWS_REGION || 'us-east-1' }}
      
      - name: Run Issue Agent
        env:
          BEDROCK_MODEL_ID: ${{ secrets.BEDROCK_MODEL_ID || 'anthropic.claude-3-5-sonnet-20240620-v1:0' }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ISSUE_NUMBER: ${{ github.event.issue.number || github.event.inputs.issue_number }}
          REPOSITORY: ${{ github.repository }}
        run: |
          python /tmp/issue-fix-action/src/agents/issue_agent.py \
            --issue-number $ISSUE_NUMBER \
            --repo $REPOSITORY \
            --output-dir ./agent-output
      
      - name: Comment on issue
        if: always()
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python /tmp/issue-fix-action/src/utils/update_issue_comment.py \
            --issue-number ${{ github.event.issue.number || github.event.inputs.issue_number }} \
            --repo ${{ github.repository }} \
            --status-dir ./agent-output
```

### 2.2 Configure Secrets

In your service repository, go to **Settings → Secrets and variables → Actions** and add:

- `AWS_ROLE_ARN`: IAM role ARN for Bedrock access (with OIDC trust)
- `AWS_REGION`: AWS region (default: `us-east-1`)
- `BEDROCK_MODEL_ID`: (Optional) Bedrock model ID (default: Claude 3.5 Sonnet)

**Note**: `GITHUB_TOKEN` is automatically provided by GitHub Actions.

## Step 3: Configure AWS IAM Role

Create an IAM role for GitHub Actions OIDC authentication:

### 3.1 Trust Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::YOUR_ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:parimalpate123/*"
        }
      }
    }
  ]
}
```

### 3.2 Permissions Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-*"
    }
  ]
}
```

## Step 4: Test the Setup

### 4.1 Create a Test Issue

In your service repository, create an issue with the `auto-fix` label:

```markdown
## Incident: test-123

### Service
payment-service

### Root Cause
Database connection timeout in payment-service Lambda function

### Recommended Fix
Adjust database connection pool and timeout settings
```

### 4.2 Trigger the Workflow

The workflow will automatically run when:
- An issue with `auto-fix` label is created
- A bot creates an issue
- You manually trigger it via `workflow_dispatch`

### 4.3 Verify Results

Check:
1. Issue comments for status updates
2. Pull Requests tab for created PRs
3. Workflow runs in Actions tab

## Step 5: Integration with PR Review Agent

After the Issue Agent creates a PR, the PR Review Agent should automatically review it.

Make sure your service repository has the PR Review Agent workflow configured (from `pr-code-review-action`).

## Troubleshooting

### Issue: "GITHUB_TOKEN not set"
- This is automatically provided by GitHub Actions
- If running locally, set: `export GITHUB_TOKEN=your_token`

### Issue: "AWS credentials not configured"
- Verify `AWS_ROLE_ARN` secret is set
- Check IAM role trust policy allows your repository
- Verify OIDC provider is configured in AWS

### Issue: "Bedrock invocation failed"
- Check IAM role has `bedrock:InvokeModel` permission
- Verify model ID is correct
- Check AWS region matches

### Issue: "No affected files identified"
- The issue may not have enough context
- Check issue body format matches expected structure
- Verify service name is correctly specified

## Next Steps

1. Test with a real incident from your SRE system
2. Monitor PR creation and review process
3. Iterate on prompts based on results
4. Add more service repositories

## Support

For issues or questions:
- Open an issue in the `issue-fix-action` repository
- Check logs in GitHub Actions workflow runs
- Review agent output in `agent-output/` directory
