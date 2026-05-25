# Nationwide Chat Widget Operational Runbook

| Field | Value |
|---|---|
| **Document ID** | RNB-NCW-001 |
| **Companion Playbook** | PLY-NCW-001 |
| **Version** | 1.0 |
| **Owner** | Platform Engineering |
| **Date** | 2026-05-25 |
| **Status** | Active |

> Execute steps in order.
> Repository root used throughout: `/Users/alokkulkarni/Documents/Development/awsagentcore`

---

## 1. Pre-deployment checklist

### 1.1 Confirm toolchain and AWS identity

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
node --version
npm --version
aws --version
aws sts get-caller-identity
```

**✓ Verify**

```bash
command -v node && command -v npm && command -v aws
```

**Expected result:** all commands resolve; AWS identity returns the expected account.

### 1.2 Confirm repository state and target version

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
git status
git rev-parse --abbrev-ref HEAD
git describe --tags --always
```

**✓ Verify**

```bash
git status --short
```

**Expected result:** working tree is in the expected state for the release branch or tag.

### 1.3 Confirm Nationwide widget source configuration

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
grep -n "snippetId\|customDisplayNames\|contactAttributes\|conversationalbot.my.connect.aws" nationwide_chat_widget/index.html
grep -n "BOT\|SYSTEM\|ARIA\|Nationwide" nationwide_chat_widget/src/components/ConnectChatWidget.jsx
```

**✓ Verify**

```bash
grep -n "port" nationwide_chat_widget/vite.config.js
```

**Expected result:** `vite.config.js` shows port `4001`; `index.html` shows the hosted widget bootstrap.

### 1.4 Confirm Amazon Connect prerequisites outside the repo

Validate the following in the Amazon Connect console before deployment:

- The hosted widget snippet in `nationwide_chat_widget/index.html` is the intended one.
- Approved origins include `http://localhost:4001` for local testing.
- The production CloudFront origin will be added or updated after deployment.
- Any ARIA routing/contact-flow dependency behind the hosted widget is ready.

**Source note:** the repo does **not** store a Connect instance URL, contact flow ARN, or API Gateway endpoint as separate variables.

---

## 2. Local development

### 2.1 Install and start the Vite dev server

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/nationwide_chat_widget
npm install
npm run dev
```

Open: `http://localhost:4001`

### 2.2 Configuration location

The Nationwide widget does **not** use a `.env` file today. Update configuration in:

- `nationwide_chat_widget/index.html` for hosted widget snippet, styles, contact attributes, and display names
- `nationwide_chat_widget/src/components/ConnectChatWidget.jsx` for MutationObserver relabeling
- `nationwide_chat_widget/src/App.jsx` / CSS / `public/nationwide-logo.png` for branding and layout

**✓ Verify**

```bash
curl -I http://localhost:4001
```

**Expected result:** local dev server returns `200 OK` once Vite is running.

---

## 3. Build

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/nationwide_chat_widget
npm run build
```

**✓ Verify**

```bash
find dist -maxdepth 2 -type f | sort
```

**Expected result:** `dist/index.html`, `dist/assets/*`, `dist/favicon.svg`, and `dist/nationwide-logo.png` are present.

---

## 4. Deploy to AWS

### 4.1 Standard deployment command

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
bash scripts/deploy_nationwide_chat_widget.sh
```

Optional variants supported by the script:

```bash
bash scripts/deploy_nationwide_chat_widget.sh --env staging
bash scripts/deploy_nationwide_chat_widget.sh --env prod --region eu-west-2
bash scripts/deploy_nationwide_chat_widget.sh --bucket-name <your-unique-bucket-name>
bash scripts/deploy_nationwide_chat_widget.sh --no-build
bash scripts/deploy_nationwide_chat_widget.sh --dry-run
```

**Expected duration:** allow **5-15 minutes** for new CloudFront distribution deployment. Cache invalidation is typically reported as live within about **30 seconds**, but edge propagation may take longer.

### 4.2 What the script does

In order, `scripts/deploy_nationwide_chat_widget.sh`:

1. Detects the AWS account with `aws sts get-caller-identity --query Account --output text`.
2. Runs `npm install --silent` and `npm run build` unless `--no-build` is set.
3. Creates or reuses a private S3 bucket.
4. Enables S3 block public access, AES-256 encryption, and suspends versioning.
5. Removes any S3 CORS configuration.
6. Creates or reuses a CloudFront Origin Access Control.
7. Applies a bucket policy allowing CloudFront read access.
8. Creates or reuses a CloudFront response headers policy.
9. Creates or reuses the CloudFront distribution with SPA fallback and split cache behaviour.
10. Tightens the bucket policy to the exact distribution ARN.
11. Uploads `dist/assets/`, `dist/index.html`, and the remaining files with different cache headers.
12. Creates a CloudFront invalidation for `/*`.
13. Prints the bucket, distribution ID, widget URL, and approved-origin reminder.

### 4.3 Exact AWS CLI commands used by the script (variable-driven)

```bash
# Account detection
aws sts get-caller-identity --query Account --output text

# Bucket setup
# For regions other than us-east-1; the script omits --create-bucket-configuration in us-east-1.
aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" --create-bucket-configuration "LocationConstraint=${AWS_REGION}"
aws s3api put-public-access-block --bucket "$BUCKET_NAME" --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
aws s3api put-bucket-encryption --bucket "$BUCKET_NAME" --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-versioning --bucket "$BUCKET_NAME" --versioning-configuration "Status=Suspended"
aws s3api delete-bucket-cors --bucket "$BUCKET_NAME"

# CloudFront access
aws cloudfront create-origin-access-control --origin-access-control-config "{\"Name\":\"${OAC_NAME}\",\"Description\":\"OAC for ${CF_COMMENT}\",\"SigningProtocol\":\"sigv4\",\"SigningBehavior\":\"always\",\"OriginAccessControlOriginType\":\"s3\"}"
aws s3api put-bucket-policy --bucket "$BUCKET_NAME" --policy "<initial-cloudfront-read-policy>"
aws cloudfront list-response-headers-policies --type custom --query "ResponseHeadersPolicyList.Items[?ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name=='${HEADERS_POLICY_NAME}'].ResponseHeadersPolicy.Id" --output text
aws cloudfront create-response-headers-policy --response-headers-policy-config file://<headers-policy-config.json>
aws cloudfront create-distribution --distribution-config file://<distribution-config.json>
aws s3api put-bucket-policy --bucket "$BUCKET_NAME" --policy "<distribution-specific-cloudfront-read-policy>"

# Upload
aws s3 sync "${DIST_DIR}/assets/" "s3://${BUCKET_NAME}/assets/" --region "$AWS_REGION" --cache-control "public, max-age=31536000, immutable" --delete --exact-timestamps
aws s3 cp "${DIST_DIR}/index.html" "s3://${BUCKET_NAME}/index.html" --region "$AWS_REGION" --content-type "text/html; charset=utf-8" --cache-control "no-cache, no-store, must-revalidate"
aws s3 sync "${DIST_DIR}/" "s3://${BUCKET_NAME}/" --region "$AWS_REGION" --cache-control "public, max-age=86400" --exclude "assets/*" --exclude "index.html" --delete --exact-timestamps

# Invalidate
aws cloudfront create-invalidation --distribution-id "$CF_DISTRIBUTION_ID" --paths "/*" --query "Invalidation.Id" --output text
```

### 4.4 Deployment outputs to capture

Record these values from the script output:

- `S3 Bucket`
- `OAC`
- `Distribution ID`
- `Widget URL`
- `State file` (`nationwide_chat_widget/.deploy-state-<env>.env`)

---

## 5. ✓ Verify after deploy

```bash
curl -I https://<cloudfront-domain>
```

Open the returned CloudFront URL in Chrome and verify:

- Nationwide page renders correctly
- `nationwide-logo.png` loads in the header
- Chat launcher is visible
- Opening chat loads the Amazon Connect panel
- Chat can start successfully

**Optional CloudFront status check**

```bash
aws cloudfront get-distribution --id <distribution-id> --query 'Distribution.Status' --output text
```

**Expected result:** `Deployed`.

---

## 6. Cache invalidation

The deploy script already runs an invalidation, but the manual command is:

```bash
aws cloudfront create-invalidation --distribution-id <distribution-id> --paths "/*"
```

Use this after urgent content or configuration updates if you need to force edge refresh.

---

## 7. Update widget configuration

### 7.1 Update source files

Edit the actual source of truth:

- `nationwide_chat_widget/index.html`
- `nationwide_chat_widget/src/components/ConnectChatWidget.jsx`
- `nationwide_chat_widget/src/App.jsx`, `src/App.css`, and `public/nationwide-logo.png` as needed

Examples of settings currently held in `index.html`:

- hosted widget script URL
- `snippetId`
- `customDisplayNames`
- `contactAttributes`
- widget button colour styling

### 7.2 Rebuild and redeploy

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/nationwide_chat_widget
npm run build

cd /Users/alokkulkarni/Documents/Development/awsagentcore
bash scripts/deploy_nationwide_chat_widget.sh
aws cloudfront create-invalidation --distribution-id <distribution-id> --paths "/*"
```

**Important:** there is no `.env` or `src/config.js` file driving widget connection details today.

---

## 8. Rollback

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
git checkout <previous-tag-or-commit>

cd nationwide_chat_widget
npm run build

cd ..
bash scripts/deploy_nationwide_chat_widget.sh
aws cloudfront create-invalidation --distribution-id <distribution-id> --paths "/*"
```

**✓ Verify**

```bash
curl -I https://<cloudfront-domain>
```

**Expected result:** CloudFront serves the prior known-good build and the chat widget opens successfully.

---

## 9. Smoke test

1. Open the deployed Nationwide widget URL in Chrome.
2. Open **DevTools -> Network**.
3. Click the chat launcher.
4. Confirm requests to the Amazon Connect hosted widget load successfully from `conversationalbot.my.connect.aws`.
5. Filter Network for `StartChatContact`, `connectparticipant`, or `websocket` traffic.
6. If the hosted widget surfaces a `StartChatContact` request, confirm it returns `200`.
7. Confirm the chat session opens and a persistent chat transport (for example WebSocket or equivalent long-lived Connect chat connection) is established.
8. Confirm transcript labels show `ARIA` and `Nationwide`.
9. Confirm the Nationwide-branded header, product navigation, and hero content render correctly.
10. Confirm no browser console errors appear during chat start.

**Helpful checks**

- No `403` for JS/CSS/image/static assets
- No approved-origin failure from Amazon Connect
- No CSP/security-policy errors on the hosting page
- No blank widget panel after clicking the launcher
- No failed Connect participant/session requests during chat startup

---

## 10. Teardown

### 10.1 Remove S3 objects and bucket

```bash
export BUCKET_NAME="<nationwide-connect-widget-bucket>"
export AWS_REGION="eu-west-2"

aws s3 rm "s3://${BUCKET_NAME}" --recursive
aws s3api delete-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION"
```

### 10.2 Disable then delete the CloudFront distribution

```bash
export DIST_ID="<distribution-id>"
aws cloudfront get-distribution-config --id "$DIST_ID" --output json > cloudfront-disable-config.json
```

Edit `cloudfront-disable-config.json` so the embedded `DistributionConfig.Enabled` value is `false`, then run:

```bash
ETAG=$(aws cloudfront get-distribution-config --id "$DIST_ID" --query 'ETag' --output text)
aws cloudfront update-distribution --id "$DIST_ID" --if-match "$ETAG" --distribution-config file://cloudfront-disable-config.json
aws cloudfront get-distribution --id "$DIST_ID" --query 'Distribution.Status' --output text
```

When the distribution status returns `Deployed`, fetch the current ETag and delete it:

```bash
ETAG=$(aws cloudfront get-distribution-config --id "$DIST_ID" --query 'ETag' --output text)
aws cloudfront delete-distribution --id "$DIST_ID" --if-match "$ETAG"
rm -f cloudfront-disable-config.json
```

---

## 11. Troubleshooting

### Page blank / missing assets

- Check CloudFront and S3 asset requests for `403` or `404`.
- Confirm the bucket policy still grants the CloudFront distribution read access.
- Verify `nationwide-logo.png` is present in `dist/` and delivered by CloudFront.

### Chat will not connect

- Confirm the hosted widget snippet in `nationwide_chat_widget/index.html` is correct.
- Confirm the Amazon Connect approved origins list includes the current page origin.
- Validate the upstream Amazon Connect widget configuration in the console.

### CORS or browser security errors

- Check browser console for blocked `script-src`, `frame-src`, or `connect-src` activity.
- The deploy script does not set CSP headers; if the site embedding this widget adds its own CSP, it must allow the Connect domain.

### Widget loads but there is no ARIA response

- Confirm the hosted snippet still routes into the intended Connect-side experience.
- Validate any Connect flow, bot, or Lambda integration outside this repository.

### `403` from CloudFront

- Re-check OAC configuration and the distribution-specific bucket policy.
- Confirm the bucket is private and the distribution ID in the policy matches the active distribution.

### Chat launcher missing entirely

- Confirm the external script from `conversationalbot.my.connect.aws` loads.
- Confirm no ad-blocker or browser extension is suppressing the hosted widget.

---

## Source References

- `nationwide_chat_widget/package.json`
- `nationwide_chat_widget/vite.config.js`
- `nationwide_chat_widget/index.html`
- `nationwide_chat_widget/src/App.jsx`
- `nationwide_chat_widget/src/components/ConnectChatWidget.jsx`
- `nationwide_chat_widget/public/favicon.svg`
- `nationwide_chat_widget/public/nationwide-logo.png`
- `scripts/deploy_nationwide_chat_widget.sh`
