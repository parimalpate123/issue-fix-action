# How to Get AWS Role ARN for GitHub Actions

This guide shows you how to create the IAM role and get its ARN for the GitHub Actions workflow.

## Option 1: Using Terraform (Recommended)

If you're using Terraform for infrastructure management:

### Step 1: Add the IAM Role Configuration

The Terraform configuration is already created in `infrastructure/github_actions_iam.tf`.

### Step 2: Create OIDC Provider (One-time setup)

**Important**: Before running Terraform, you need to create the OIDC provider in AWS (if it doesn't exist).

#### Check if OIDC Provider Exists

```bash
aws iam list-open-id-connect-providers
```

If you see `token.actions.githubusercontent.com` in the list, skip to Step 3.

#### Create OIDC Provider (if needed)

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

**Note**: The thumbprint may change. If you get an error, get the latest thumbprint:
```bash
openssl s_client -servername token.actions.githubusercontent.com -showcerts -connect token.actions.githubusercontent.com:443 < /dev/null 2>/dev/null | openssl x509 -fingerprint -noout -sha1 | cut -d'=' -f2 | tr -d ':'
```

### Step 3: Apply Terraform

```bash
cd infrastructure
terraform init
terraform plan  # Review changes
terraform apply
```

### Step 4: Get the Role ARN

After `terraform apply`, you'll see the output:

```
github_actions_bedrock_role_arn = "arn:aws:iam::123456789012:role/sre-poc-github-actions-bedrock-role"
```

**Copy this ARN** - this is what you'll use as the `AWS_ROLE_ARN` secret in GitHub.

---

## Option 2: Using AWS Console (Manual)

### Step 1: Create OIDC Provider (One-time setup)

1. Go to **IAM → Identity providers**
2. Click **Add provider**
3. Select **OpenID Connect**
4. Provider URL: `https://token.actions.githubusercontent.com`
5. Audience: `sts.amazonaws.com`
6. Click **Add provider**

### Step 2: Create IAM Role

1. Go to **IAM → Roles → Create role**

2. **Trust entity type**: Select **Web identity**

3. **Identity provider**: Select `token.actions.githubusercontent.com`

4. **Audience**: `sts.amazonaws.com`

5. **Conditions** (optional but recommended):
   - Click **Add condition**
   - Condition key: `StringLike`
   - Key: `token.actions.githubusercontent.com:sub`
   - Value: `repo:parimalpate123/*`
   - This restricts the role to your GitHub organization

6. Click **Next**

7. **Permissions**: 
   - Click **Create policy**
   - Switch to **JSON** tab
   - Paste this policy:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "bedrock:InvokeModel",
           "bedrock:InvokeModelWithResponseStream"
         ],
         "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-*"
       }
     ]
   }
   ```
   - Name: `GitHubActionsBedrockPolicy`
   - Click **Create policy**
   - Go back to role creation, refresh, and select the policy

8. Click **Next**

9. **Role name**: `sre-poc-github-actions-bedrock-role` (or your preferred name)

10. Click **Create role**

### Step 3: Get the Role ARN

1. Go to **IAM → Roles**
2. Find your role: `sre-poc-github-actions-bedrock-role`
3. Click on it
4. Copy the **ARN** from the top of the page

**Example ARN format**:
```
arn:aws:iam::123456789012:role/sre-poc-github-actions-bedrock-role
```

---

## Step 4: Add ARN to GitHub Secrets

For each service repository (`poc-payment-service`, `poc-rating-service`, `poc-order-service`):

1. Go to your repository on GitHub
2. **Settings → Secrets and variables → Actions**
3. Click **New repository secret**
4. Name: `AWS_ROLE_ARN`
5. Value: Paste the ARN you copied (e.g., `arn:aws:iam::123456789012:role/sre-poc-github-actions-bedrock-role`)
6. Click **Add secret**

---

## Verify Setup

### Test the Role

You can test if the role works by running a manual workflow:

1. Go to your service repository
2. **Actions → Auto-Fix from Issues → Run workflow**
3. Enter a test issue number
4. Check the logs to see if authentication succeeds

### Common Issues

**Error: "Not authorized to perform sts:AssumeRoleWithWebIdentity"**
- Check OIDC provider exists
- Verify trust policy conditions match your repository
- Ensure role name is correct

**Error: "AccessDenied: User is not authorized to perform: bedrock:InvokeModel"**
- Check IAM role policy has Bedrock permissions
- Verify resource ARN matches your region and model

**Error: "The request signature we calculated does not match"**
- This usually means OIDC provider thumbprint is wrong
- Recreate OIDC provider with correct thumbprint

---

## Quick Reference

**Role ARN Format**:
```
arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME
```

**Example**:
```
arn:aws:iam::123456789012:role/sre-poc-github-actions-bedrock-role
```

**Where to find it**:
- Terraform output: `terraform output github_actions_bedrock_role_arn`
- AWS Console: IAM → Roles → [Your Role] → ARN at top
- AWS CLI: `aws iam get-role --role-name sre-poc-github-actions-bedrock-role --query 'Role.Arn' --output text`

---

## Next Steps

After setting up the role:

1. ✅ Add `AWS_ROLE_ARN` secret to all service repositories
2. ✅ Test with a sample issue
3. ✅ Monitor workflow runs for any authentication issues

For more details, see `SETUP.md` or `QUICK_START.md`.
