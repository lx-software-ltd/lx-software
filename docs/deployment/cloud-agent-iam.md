# Cloud-agent IAM read access (debugging)

The Cursor cloud agents (and any other read-only investigators) authenticate
to AWS as the IAM user **`cursor-cloud-agent`** in account `588024549699`.

By default this identity has **no AWS-managed nor inline policies attached**,
so it can do nothing other than `sts:GetCallerIdentity`. We grant it just
enough read-only permissions to investigate production issues from
CloudWatch / S3 / DynamoDB without ever being able to mutate state.

This document shows exactly which actions are needed and how to attach them.

## Why this exists

When the admin **Finance > House > Import statement (PDF)** flow fails, the
useful evidence is split across:

- **CloudWatch Logs** — `lxsoftware-HttpApiAccessLogs*` (HTTP API access log)
  and `lxsoftware-AdminApiFnLogGroup*` (Lambda stdout). Already readable.
- **S3 server access logs** — written to the
  `lxsoftware-admin-assets-logs-<account>-<region>` bucket under the
  `assets-data-bucket/` prefix. Records every PUT/POST against the assets
  bucket, including the status code returned by S3 to the browser. **Not
  readable today** without this policy.
- **Assets bucket CORS configuration** — needed to confirm whether a
  browser POST was rejected by CORS preflight. **Not readable today**.
- **Audit log table** — `lxsoftware-admin-audit-log` DynamoDB table. Records
  every admin action with user sub + request id, useful to correlate a
  client-reported failure with the matching CloudWatch log row. **Not
  readable today**.

## Inline policy: `lxsoftware-cloud-agent-read`

Create this as an inline policy on the `cursor-cloud-agent` IAM user.
It grants:

- `s3:ListBucket` + `s3:GetObject` on the **access-logs bucket only**
  (so we can read S3 access logs but never the source statements).
- `s3:GetBucketCORS` + `s3:GetBucketPolicy` + `s3:GetBucketLocation` on
  the **assets bucket** (read-only metadata; no `s3:GetObject`).
- `dynamodb:Query` on the audit log table (no scan, no write).
- `dynamodb:GetItem` + `dynamodb:Query` on the records table so we can
  diff the persisted finance state against what the UI reports.
- `ses:GetEmailIdentity` on the board-mail and outreach sending
  identities so a Health `AWS_SES_DKIM_PENDING_TO_FAILED` can be
  diagnosed. Optional write actions below are only for
  `scripts/sync-ses-sending-dns.py --retry`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAssetsAccessLogs",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:GetObject"
      ],
      "Resource": [
        "arn:aws:s3:::lxsoftware-admin-assets-logs-588024549699-ap-southeast-1",
        "arn:aws:s3:::lxsoftware-admin-assets-logs-588024549699-ap-southeast-1/*"
      ]
    },
    {
      "Sid": "ReadAssetsBucketMetadata",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketCORS",
        "s3:GetBucketPolicy",
        "s3:GetBucketLocation",
        "s3:GetBucketVersioning",
        "s3:GetBucketLogging",
        "s3:GetEncryptionConfiguration"
      ],
      "Resource": [
        "arn:aws:s3:::lxsoftware-admin-assets-588024549699-ap-southeast-1"
      ]
    },
    {
      "Sid": "ReadAdminTables",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:DescribeTable"
      ],
      "Resource": [
        "arn:aws:dynamodb:ap-southeast-1:588024549699:table/lxsoftware-admin-audit-log",
        "arn:aws:dynamodb:ap-southeast-1:588024549699:table/lxsoftware-admin-records"
      ]
    },
    {
      "Sid": "ReadBoardSesIdentities",
      "Effect": "Allow",
      "Action": [
        "ses:GetEmailIdentity"
      ],
      "Resource": [
        "arn:aws:ses:ap-southeast-1:588024549699:identity/siutindei.com",
        "arn:aws:ses:ap-southeast-1:588024549699:identity/partners.siutindei.com"
      ]
    },
    {
      "Sid": "RetryBoardSesDkim",
      "Effect": "Allow",
      "Action": [
        "ses:PutEmailIdentityDkimAttributes",
        "ses:PutEmailIdentityMailFromAttributes"
      ],
      "Resource": [
        "arn:aws:ses:ap-southeast-1:588024549699:identity/siutindei.com",
        "arn:aws:ses:ap-southeast-1:588024549699:identity/partners.siutindei.com"
      ]
    }
  ]
}
```

Notes / deliberate omissions:

- **No `s3:GetObject` on the assets bucket itself.** Bank-statement PDFs
  must never be readable by debugging identities.
- **No `dynamodb:Scan`.** The audit table is partitioned by `USER#<sub>`;
  point queries are sufficient and cheaper.
- **No KMS actions.** The buckets and tables use AWS-managed encryption
  (`aws/s3`, `aws/dynamodb`) — no extra grant required.
- **No CloudWatch Logs actions.** `cursor-cloud-agent` already has
  `logs:StartQuery`, `logs:GetQueryResults`, etc. via a separate policy
  attached when the user was created. If that ever stops working, add
  the `CloudWatchLogsReadOnlyAccess` AWS-managed policy.

## How to attach it

### Option A — AWS Console

1. Sign in to the AWS console for account `588024549699`.
2. Navigate to **IAM > Users > cursor-cloud-agent**.
3. Open the **Permissions** tab and click **Add permissions > Create
   inline policy**.
4. Switch to the **JSON** editor, paste the policy above verbatim, and
   click **Next**.
5. Name the policy **`lxsoftware-cloud-agent-read`** and click
   **Create policy**.

### Option B — AWS CLI (one-shot)

Save the policy above to `cloud-agent-read.json` then run:

```bash
aws iam put-user-policy \
  --user-name cursor-cloud-agent \
  --policy-name lxsoftware-cloud-agent-read \
  --policy-document file://cloud-agent-read.json
```

You will need an IAM user with `iam:PutUserPolicy` permission to do this
(typically the bootstrap admin or your own console user).

### Verifying the grant

After attaching, the agent (or any tool using the same credentials) should
succeed at:

```bash
# S3 access logs are now listable / readable:
aws s3api list-objects-v2 \
  --region ap-southeast-1 \
  --bucket lxsoftware-admin-assets-logs-588024549699-ap-southeast-1 \
  --prefix assets-data-bucket/ --max-keys 5

# CORS configuration on the assets bucket:
aws s3api get-bucket-cors \
  --region ap-southeast-1 \
  --bucket lxsoftware-admin-assets-588024549699-ap-southeast-1

# Current SES Easy DKIM tokens (needed after AWS_SES_DKIM_PENDING_TO_FAILED):
python3 - <<'PY'
import boto3, json
print(json.dumps(
    boto3.client("sesv2", region_name="ap-southeast-1").get_email_identity(
        EmailIdentity="partners.siutindei.com"
    ).get("DkimAttributes"),
    indent=2,
))
PY

# Audit-log query for a specific Cognito sub:
aws dynamodb query \
  --region ap-southeast-1 \
  --table-name lxsoftware-admin-audit-log \
  --key-condition-expression 'pk = :pk' \
  --expression-attribute-values '{":pk":{"S":"USER#<cognito-sub>"}}' \
  --max-items 10
```

All three should return data instead of `AccessDenied`.

## Removing access

Whenever the cloud-agent identity is no longer needed:

```bash
aws iam delete-user-policy \
  --user-name cursor-cloud-agent \
  --policy-name lxsoftware-cloud-agent-read
```

(or delete the inline policy from the IAM console).

## Reading S3 server access logs

Once the policy is attached, S3 access logs landing under
`s3://lxsoftware-admin-assets-logs-…/assets-data-bucket/` follow the
[S3 access log format](https://docs.aws.amazon.com/AmazonS3/latest/userguide/LogFormat.html)
and can be queried directly with `aws s3 cp`/`aws s3 ls` or, for any
sustained investigation, exposed as an Athena table over the prefix.

The fields most useful for the PDF-import diagnosis are:

- `Operation` — `REST.POST.OBJECT` for browser uploads.
- `Key` — the `uploads/<sub>/<uuid>/<filename>` key, matches the response
  from `/assets/upload-url`.
- `HTTP status` — 204 means the upload succeeded; anything else is the
  exact reason the chain stopped.
- `Error Code` — `AccessDenied` (likely casing-mismatch on the policy),
  `EntityTooLarge` (over `ASSET_MAX_BYTES`), `MalformedPOSTRequest`
  (bad form), etc.
- `User-Agent` — pin the failure to a specific browser if needed.
- `Bytes Sent` — confirms the file size that actually crossed the wire.
