# Deployment setup (AWS + GitHub Actions)

One-time prerequisites shared by every deploy workflow. Do these before
[`public-website.md`](./public-website.md) or [`admin-website.md`](./admin-website.md).

## 1. GitHub OIDC provider

**IAM → Identity providers → Add provider**

- Provider type: **OpenID Connect**
- Provider URL: `https://token.actions.githubusercontent.com`
- Audience: `sts.amazonaws.com`

## 2. `GitHubActionsRole`

The workflows assume an IAM role named `GitHubActionsRole`.

### Create it (if missing)

1. **IAM → Roles → Create role** (tag `Organization: LX Software`,
   `Project: Public Website`).
2. Trusted entity **Web identity**, provider
   `token.actions.githubusercontent.com`, audience `sts.amazonaws.com`.
3. Permissions: `AdministratorAccess` to start; tighten to the list below.
4. Name: `GitHubActionsRole`.

### Trust policy

Apply [`../architecture/github-actions-trust-policy.json`](../architecture/github-actions-trust-policy.json):

```bash
aws iam update-assume-role-policy \
  --role-name GitHubActionsRole \
  --policy-document file://docs/architecture/github-actions-trust-policy.json
```

It trusts every repository in the `lx-software-ltd` organization through
two `sub` formats:

- `repo:lx-software-ltd/*` — name-only format, issued to repositories
  created before July 15, 2026 and not renamed or transferred since.
- `repo:lx-software-ltd@321652495/*` — immutable-ID format
  (`repo:OWNER@OWNER-ID/REPO@REPO-ID:...`) for repositories created,
  renamed or transferred after that date. `321652495` is the organization
  id.

Both end in `*` so branch, environment and pull-request subjects match.
Check which format a repository issues with
`gh api repos/lx-software-ltd/<REPO>/actions/oidc/customization/sub`.

### Permissions

CDK deploys through the roles created by `cdk bootstrap`, so the role must
be able to assume them and read the bootstrap version parameter
(`ACCOUNT_ID` = your account; `hnb659fds` = your qualifier if you changed
it):

```json
{
  "Effect": "Allow",
  "Action": "sts:AssumeRole",
  "Resource": [
    "arn:aws:iam::ACCOUNT_ID:role/cdk-hnb659fds-deploy-role-*",
    "arn:aws:iam::ACCOUNT_ID:role/cdk-hnb659fds-lookup-role-*",
    "arn:aws:iam::ACCOUNT_ID:role/cdk-hnb659fds-file-publishing-role-*",
    "arn:aws:iam::ACCOUNT_ID:role/cdk-hnb659fds-image-publishing-role-*"
  ]
}
```

```json
{
  "Effect": "Allow",
  "Action": "ssm:GetParameter",
  "Resource": "arn:aws:ssm:*:ACCOUNT_ID:parameter/cdk-bootstrap/*"
}
```

For the three stacks (`lxsoftware-public-www`, `lxsoftware`,
`lxsoftware-admin-web`) the role also needs:

- **CloudFormation** on the stack ARNs
  `arn:aws:cloudformation:REGION:ACCOUNT_ID:stack/<stack>/*`.
- **S3** `GetObject` / `PutObject` / `DeleteObject` / `ListBucket` on the
  two website buckets (`lxsoftware-public-www` origin and
  `lxsoftware-admin-web-*`) for the deploy scripts.
- **CloudFront** `CreateInvalidation` on both distributions.
- For the **Manage Public API Keys** workflow: DynamoDB read/write on
  `lxsoftware-admin-records` (`PutItem` for mint, plus the read and update
  calls behind `list` / `revoke` / `set-write`) and `kms:Decrypt` on the
  shared CMK. An `AccessDenied` in that workflow names the missing action.

If CDK Bootstrap was run from a different repository, confirm the bootstrap
roles' trust policy allows `GitHubActionsRole` to assume them.

## 3. CDK Bootstrap

Once per account/region. The stacks deploy to `AWS_REGION`; CloudFront
certificates for the admin site need `us-east-1` as well.

Via GitHub Actions: **Actions → CDK Bootstrap → Run workflow**.

Locally:

```bash
cd backend/infrastructure
npm ci
npx cdk bootstrap aws://ACCOUNT_ID/REGION
npx cdk bootstrap aws://ACCOUNT_ID/us-east-1   # admin ACM certificate
```

## 4. GitHub environment (`production`)

Variables:

| Variable | Purpose |
|----------|---------|
| `AWS_ACCOUNT_ID`, `AWS_REGION` | Target account and region (must match where CDK Bootstrap ran). |
| `CDK_BOOTSTRAP_QUALIFIER` | Only if you did not use the default `hnb659fds`. |
| `CDK_PARAM_FILE` | e.g. `backend/infrastructure/params/production.json` (`backend/infrastructure/params/README.md` lists the keys). |
| `PUBLIC_WEBSITE_STACK_NAME` | Defaults to `lxsoftware-public-www`. |
| `ADMIN_API_BASE_URL` | Admin HTTP API origin; also inlined into the public site as `VITE_PUBLIC_API_URL`. |
| `ADMIN_ACM_CERT_ARN`, `ADMIN_GOOGLE_CLIENT_ID`, `ADMIN_FEDERATED_EMAIL_ALLOWLIST`, `ADMIN_BOOTSTRAP_EMAIL`, `ADMIN_COGNITO_*` | Admin stack and SPA settings; see [`admin-website.md`](./admin-website.md). |

Secrets:

| Secret | Purpose |
|--------|---------|
| `ADMIN_GOOGLE_CLIENT_SECRET` | Google OAuth client secret (CDK `noEcho`). |
| `ADMIN_BOOTSTRAP_TEMP_PASSWORD` | Bootstrap admin password (14+ chars, mixed classes). |
| `PUBLIC_API_KEY_GPG_PASSPHRASE` | Encrypts minted keys in the public workflow logs. |
| `OPENROUTER_MANAGEMENT_API_KEY` | For **Mint OpenRouter App Keys**. |

## Troubleshooting

**`SSM parameter /cdk-bootstrap/hnb659fds/version not found`** — bootstrap
has not run in that region, or the role lacks `ssm:GetParameter` (see §2).

**`current credentials could not be used to assume … deploy-role`** — the
role lacks the `sts:AssumeRole` statement in §2, or the bootstrap roles do
not trust it.
