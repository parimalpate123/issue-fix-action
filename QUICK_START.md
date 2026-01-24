# Quick Start Guide - Service Repository Setup

This guide will help you quickly set up the Issue Agent workflow in your service repositories.

## Step 1: Add Workflow to Service Repository

For each service repository (`poc-payment-service`, `poc-rating-service`, `poc-order-service`):

1. **Create the workflow directory** (if it doesn't exist):
   ```bash
   mkdir -p .github/workflows
   ```

2. **Copy the workflow file**:
   - Copy `SERVICE_WORKFLOW.yml` from this repository
   - Save it as `.github/workflows/auto-fix.yml` in your service repository

3. **Commit and push**:
   ```bash
   git add .github/workflows/auto-fix.yml
   git commit -m "Add Issue Agent workflow for auto-fix"
   git push
   ```

## Step 2: Configure Secrets

In each service repository, go to **Settings → Secrets and variables → Actions** and add:

### Required Secrets:

1. **`AWS_ROLE_ARN`**
   - IAM role ARN for Bedrock access
   - Format: `arn:aws:iam::ACCOUNT_ID:role/GITHUB_ACTIONS_BEDROCK_ROLE`
   - See IAM setup below

2. **`AWS_REGION`** (Optional)
   - AWS region (default: `us-east-1`)
   - Only set if different from default

3. **`BEDROCK_MODEL_ID`** (Optional)
   - Bedrock model ID (default: `anthropic.claude-3-5-sonnet-20240620-v1:0`)
   - Only set if using a different model

**Note**: `GITHUB_TOKEN` is automatically provided by GitHub Actions.

## Step 3: Set Up AWS IAM Role

### Option A: Using AWS Console

1. **Create OIDC Provider** (if not exists):
   - Go to IAM → Identity providers
   - Add provider: `token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`

2. **Create IAM Role**:
   - Go to IAM → Roles → Create role
   - Trust entity: Web identity
   - Identity provider: `token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`
   - Condition: `StringLike` → `token.actions.githubusercontent.com:sub` → `repo:parimalpate123/*`

3. **Attach Policy**:
   - Add inline policy or attach `AmazonBedrockFullAccess` (or create custom policy with only `bedrock:InvokeModel`)

### Option B: Using Terraform

See the Terraform configuration below.

## Step 4: Test the Workflow

1. **Create a test issue** in your service repository:
   ```markdown
   ## Incident: test-123

   ### Service
   payment-service

   ### Root Cause
   Database connection timeout in payment-service Lambda function

   ### Recommended Fix
   Adjust database connection pool and timeout settings
   ```

2. **Add the `auto-fix` label** to the issue

3. **Check the Actions tab** - the workflow should automatically run

4. **Verify**:
   - Issue should have a status comment
   - A PR should be created (if fix was generated)
   - Check workflow logs for any errors

## Troubleshooting

### Workflow doesn't trigger
- Verify issue has `auto-fix` label
- Check workflow file is in `.github/workflows/auto-fix.yml`
- Verify workflow syntax is correct

### AWS authentication fails
- Check `AWS_ROLE_ARN` secret is set correctly
- Verify IAM role trust policy allows your repository
- Check OIDC provider is configured

### Bedrock invocation fails
- Verify IAM role has `bedrock:InvokeModel` permission
- Check model ID is correct
- Verify AWS region matches

### No fix generated
- Check issue body format (should have Service, Root Cause, etc.)
- Review workflow logs in Actions tab
- Check `agent-output/` artifacts for details

## Terraform IAM Setup (Optional)

If you want to manage IAM via Terraform, add this to your infrastructure:

```hcl
# OIDC Provider for GitHub Actions
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

# IAM Role for GitHub Actions
resource "aws_iam_role" "github_actions_bedrock" {
  name = "github-actions-bedrock-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = data.aws_iam_openid_connect_provider.github.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:parimalpate123/*"
          }
        }
      }
    ]
  })
}

# Policy for Bedrock access
resource "aws_iam_role_policy" "github_actions_bedrock" {
  name = "bedrock-invoke-policy"
  role = aws_iam_role.github_actions_bedrock.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-*"
      }
    ]
  })
}

# Output the role ARN
output "github_actions_bedrock_role_arn" {
  value = aws_iam_role.github_actions_bedrock.arn
  description = "ARN of the IAM role for GitHub Actions Bedrock access"
}
```

After applying, use the output ARN as the `AWS_ROLE_ARN` secret.

## Next Steps

1. ✅ Add workflow to all service repositories
2. ✅ Configure secrets in each repository
3. ✅ Set up AWS IAM role
4. ✅ Test with a sample issue
5. ✅ Monitor first real incident from Remediation Agent

## Support

- Check workflow logs in GitHub Actions
- Review `agent-output/` artifacts
- See `SETUP.md` for detailed setup instructions
- See `ARCHITECTURE.md` for technical details
