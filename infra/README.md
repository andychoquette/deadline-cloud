# Deadline Cloud MCP Server Infrastructure

CDK infrastructure for hosting the Deadline Cloud MCP server as a remote service.

## Architecture

```
Internet → API Gateway (HTTP API) → VPC Link → ALB → ECS Fargate (MCP Server)
                                                              ↓
                                                   STS AssumeRoleWithWebIdentity
                                                              ↓
                                                   Deadline Cloud Public API
```

**Auth flow:** User authenticates via IAM Identity Center OAuth. The MCP server
validates their token and assumes a delegation role with their identity, then
calls the Deadline Cloud API with per-user scoped credentials.

## Prerequisites

- AWS account with CDK bootstrapped
- IAM Identity Center OIDC application registered (one-time setup)
- GitHub Actions OIDC provider configured for deployments

## Local Development

```bash
cd infra
npm install
npx cdk synth --context stage=dev
npx cdk deploy --context stage=dev
```

## Client Configuration

After deployment, users configure their MCP client with:

```json
{
  "mcpServers": {
    "deadline-cloud": {
      "url": "https://<api-gateway-id>.execute-api.<region>.amazonaws.com/mcp"
    }
  }
}
```

## Stacks

| Stack | Resources |
|-------|-----------|
| `DeadlineMcpServer-{stage}` | VPC, ECS Cluster, Fargate Service, ALB, API Gateway, IAM Roles, ECR Repository |

## IAM Roles

| Role | Purpose |
|------|---------|
| `McpTaskRole` | ECS task role — can only STS:AssumeRoleWithWebIdentity to get per-user creds |
| `DeadlineMcpUserDelegation` | Assumed per-request with user's IdC token. Has Deadline Cloud API permissions. |
| GitHub OIDC Role | Used by GitHub Actions to deploy infrastructure and push container images |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MCP_TRANSPORT` | `streamable-http` for remote hosting |
| `MCP_AUTH_MODE` | `oauth-delegation` for per-user credential delegation |
| `MCP_PORT` | Port the server listens on (default: 8000) |
| `IDC_ISSUER_URL` | IAM Identity Center OIDC issuer URL |
| `DELEGATION_ROLE_ARN` | ARN of the DeadlineMcpUserDelegation role |

## One-Time Setup

### 1. Register OIDC Application in IAM Identity Center

Create a custom OIDC application in your Identity Center instance:
- **Application name:** Deadline Cloud MCP Server
- **Redirect URI:** `http://localhost` (MCP clients handle the redirect locally)
- **Scopes:** `openid`, `profile`
- **Token endpoint auth method:** `client_secret_basic`

Record the Client ID — it's needed for the OIDC provider trust policy.

### 2. Create GitHub OIDC Provider

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list <github-thumbprint>
```

### 3. Create GitHub Deploy Role

Create a role trusted by the GitHub OIDC provider, scoped to this repository:
- Trust policy condition: `token.actions.githubusercontent.com:sub` = `repo:aws-deadline/deadline-cloud:ref:refs/heads/mainline`
- Permissions: ECR push, ECS deploy, CDK deploy (CloudFormation, IAM, etc.)

Store the role ARN as `MCP_DEPLOY_ROLE_ARN` in GitHub repository secrets.
