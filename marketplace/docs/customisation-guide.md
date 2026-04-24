# Customisation Guide: Secure DTMF Capture for Amazon Connect

> **Product:** Secure DTMF Capture for Amazon Connect  
> **Version:** 1.0  
> **Audience:** Developers and solution architects adapting the solution to specific requirements

---

## 1. Collection Purpose System

The `collectionPurpose` contact attribute is the single control point that drives the entire behaviour of the solution. It determines:

- **What validation logic runs** in the validate Lambda (Luhn, format check, digit count)
- **How the masked value is formatted** for display (`****4567`, `***-**-1234`, `20-47-89`)
- **What IVR prompt is played** to the customer in the contact flow
- **Whether BIN lookup is performed**
- **Whether ownership check is invoked**
- **What the agent panel displays** (title, icon, instructions)

This means that the same four Lambda functions and the same contact flow sub-flow can handle all eight built-in purposes — and any custom purposes you add — without code duplication. The only change needed is setting the correct `collectionPurpose` before invoking the sub-flow.

### How Purpose Propagates

```
Agent clicks "Collect Card Number"
        ↓
Connect flow sets contact attribute: collectionPurpose = "full_card_number"
        ↓
Start-session Lambda writes purpose to DynamoDB session record
        ↓
Status proxy returns purpose to launcher iframe
        ↓
Launcher opens panel with purpose context
        ↓
Validate Lambda reads purpose → applies correct validation chain
        ↓
Panel renders purpose-appropriate title and status text
```

---

## 2. Adding a New Collection Purpose

To add a custom purpose (e.g. `passport_number` for 9-digit UK passport numbers):

### Step 1: Define the Purpose String

Choose a lowercase snake_case string. Example: `passport_number`.

### Step 2: Update the Validate Lambda

Open `scripts/lambdas/aria_dtmf_validate.py`. Find the validation routing section (look for `if purpose == "full_card_number":`) and add your new branch:

```python
elif purpose == "passport_number":
    # UK passport number: 9 alphanumeric but DTMF is digits-only
    # Accept 9 digits as a proxy; ownership check if configured
    if digit_count != 9:
        validation_status = "invalid_format"
        validation_message = f"Passport number must be 9 digits, got {digit_count}"
        is_valid = False
    else:
        is_valid = True
        validation_status = "valid"
        validation_message = "Passport number format accepted"
        masked_value = f"*****{last_four}"
```

Also add the masked value formatter — find the section that sets `dtmf_masked_value` and add your format:

```python
elif purpose == "passport_number":
    masked_value = f"*****{last_four}"
```

### Step 3: Update the Contact Flow

In the DTMF Secure Collection sub-flow, the "Play prompt" block before capture uses a dynamic prompt driven by `collectionPurpose`. Add a branch for your new purpose:

1. Open the sub-flow in the Connect console.
2. Find the **Check contact attributes** block that routes by `collectionPurpose`.
3. Add a new branch: `collectionPurpose = "passport_number"`.
4. Connect the branch to a **Play prompt** block with your IVR prompt text: *"Please enter your 9-digit passport number on your keypad."*
5. Connect the prompt block back to the "Store customer input" block.
6. Save and publish the flow.

### Step 4: Update the Agent Panel

Open `client/dtmf-status-panel/index.html`. Find the `PURPOSE_LABELS` constant near the top:

```javascript
const PURPOSE_LABELS = {
  full_card_number: { title: "Card Number Capture", icon: "💳" },
  card_last_four:   { title: "Card Last Four Digits", icon: "💳" },
  ssn:              { title: "Social Security Number", icon: "🔒" },
  account_number:   { title: "Account Number", icon: "🏦" },
  sort_code:        { title: "Sort Code", icon: "🏦" },
  cvv:              { title: "CVV Capture", icon: "🔐" },
  pin:              { title: "PIN Capture", icon: "🔢" },
  generic:          { title: "Secure Input", icon: "🔒" }
};
```

Add your new purpose:

```javascript
passport_number: { title: "Passport Number", icon: "🛂" },
```

### Step 5: Upload Updated Panel

```bash
aws s3 cp client/dtmf-status-panel/index.html \
  s3://<bucket-name>/dtmf-panel/index.html \
  --region eu-west-2
```

Invalidate the CloudFront cache:

```bash
aws cloudfront create-invalidation \
  --distribution-id <distribution-id> \
  --paths "/dtmf-panel/*"
```

### Step 6: Deploy Updated Lambda

```bash
bash scripts/deploy_dtmf_lambda.sh deploy
```

The deploy script publishes a new version and updates the `prod` alias automatically.

---

## 3. Customising IVR Prompts

The IVR prompts are defined directly in Amazon Connect contact flow blocks — they are not stored in Lambda or S3.

### Locating the Prompt Blocks

In the DTMF Secure Collection sub-flow, prompts are in **Play prompt** blocks. Each purpose routes to its own prompt block before the "Store customer input" block.

| Purpose | Default IVR Text |
|---|---|
| `full_card_number` | "Please enter your 16-digit card number on your keypad, followed by the hash key." |
| `card_last_four` | "Please enter the last 4 digits of your card on your keypad." |
| `ssn` | "Please enter your 9-digit Social Security Number on your keypad." |
| `account_number` | "Please enter your 8-digit account number on your keypad." |
| `sort_code` | "Please enter your 6-digit sort code on your keypad." |
| `cvv` | "Please enter the 3 or 4 digit security code from the back of your card." |
| `pin` | "Please enter your PIN on your keypad." |
| `generic` | "Please enter the digits on your keypad, followed by the hash key." |

### Editing a Prompt

1. Open the sub-flow in Connect console.
2. Click the **Play prompt** block for the purpose you want to change.
3. Edit the text in the **Text-to-speech** field, or switch to **Audio** and upload an MP3 file.
4. Click **Save**.
5. **Publish** the flow.

### Multi-Language Support

To support multiple languages:

1. Add a **Check contact attributes** block at the start of the sub-flow that checks a `language` contact attribute (e.g. `"en-GB"`, `"es"`, `"fr"`).
2. Route to language-specific **Play prompt** blocks.
3. Configure each prompt with the appropriate TTS voice:
   - English: `Joanna (Neural)` or `Amy (Neural)`
   - Spanish: `Lupe (Neural)`
   - French: `Léa (Neural)`

Connect supports over 60 voices across 29 languages via Amazon Polly.

---

## 4. Customising the Status Panel

The agent status panel is a single self-contained HTML file at `client/dtmf-status-panel/index.html`.

### Rebranding

At the top of the file, find the CSS custom properties section:

```css
:root {
  --primary-colour: #232F3E;      /* AWS dark navy — change to your brand colour */
  --success-colour: #00A86B;      /* Green for validated state */
  --error-colour:   #D13212;      /* Red for failed state */
  --warning-colour: #FF9900;      /* Amber for in-progress state */
  --idle-colour:    #879596;      /* Grey for idle state */
  --font-family:    'Amazon Ember', Arial, sans-serif;
  --border-radius:  8px;
  --panel-width:    380px;
  --panel-height:   240px;
}
```

Change `--primary-colour` to your organisation's brand colour. Optionally, change `--font-family` to your corporate font (ensure the font is loaded via a `@font-face` or CDN link in the `<head>`).

### Updating Status Messages

Find the `STATUS_MESSAGES` constant in the `<script>` section:

```javascript
const STATUS_MESSAGES = {
  idle:                     { text: "Waiting for customer input", subtitle: "" },
  awaiting_trigger:         { text: "Prompting customer...", subtitle: "Customer is entering digits" },
  decrypting:               { text: "Processing...", subtitle: "Decrypting secure input" },
  validating:               { text: "Validating...", subtitle: "Checking with your records" },
  complete:                 { text: "✅ Validated", subtitle: "" },
  failed:                   { text: "❌ Validation Failed", subtitle: "" },
  validation_service_error: { text: "⚠️ Service Error", subtitle: "Please verify manually" }
};
```

Change the `text` and `subtitle` values to match your organisation's language and tone.

### Panel Dimensions and Position

The panel is a popup window opened by the launcher. To change its dimensions, find the `window.open` call in `dtmf-launcher/index.html`:

```javascript
const panel = window.open(
  panelUrl + '?contactId=' + contactId,
  'dtmfPanel',
  'width=380,height=240,resizable=no,scrollbars=no,toolbar=no,menubar=no,location=no'
);
```

Adjust `width` and `height` values as needed.

### Adding a Company Logo

In the panel HTML `<header>` section:

```html
<header>
  <img src="https://cdn.example.com/logo.png" alt="Your Company" class="logo" />
  <h1 id="purposeTitle">Secure Input</h1>
</header>
```

Add CSS to position the logo:

```css
.logo { height: 28px; margin-right: 12px; vertical-align: middle; }
```

Ensure the logo URL is accessible from the panel's origin (CloudFront domain). If hosting the logo in S3, add it to the same bucket and reference it via CloudFront.

---

## 5. Integrating with Your Customer Data System

The validate Lambda calls your `CustomerDataLambda` to verify that the captured value belongs to the authenticated customer. You provide this Lambda; the validate Lambda invokes it via Lambda-to-Lambda invocation.

### Implementing the Contract

Your Lambda must accept the [Customer Data Lambda event schema](configuration-reference.md#7-customer-data-lambda-contract) and return a compliant response. The only technical requirement is that your Lambda is in the same AWS account (or you grant cross-account invocation permissions).

### Example: SQL Database (RDS/Aurora)

```python
import boto3
import json
import pymysql
import os

# RDS connection (use IAM auth for production)
connection = None

def get_connection():
    global connection
    if connection is None or not connection.open:
        connection = pymysql.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD'],
            database=os.environ['DB_NAME'],
            connect_timeout=3
        )
    return connection

def lambda_handler(event, context):
    customer_id = event['customerId']
    purpose = event['collectionPurpose']
    captured = event['capturedValue']
    
    conn = get_connection()
    with conn.cursor() as cursor:
        if purpose in ('full_card_number', 'card_last_four'):
            last_four = captured.get('lastFour', '')
            bin_prefix = captured.get('bin', '')
            cursor.execute(
                "SELECT card_nickname, customer_name FROM customer_cards "
                "WHERE customer_id = %s AND card_last_four = %s AND bin_prefix = %s",
                (customer_id, last_four, bin_prefix)
            )
            row = cursor.fetchone()
            if row:
                return {
                    'valid': True,
                    'customerName': row[1],
                    'cardNickname': row[0],
                    'error': ''
                }
            return {
                'valid': False, 'customerName': '', 'cardNickname': '',
                'error': f'Card ending {last_four} not on file'
            }
    
    # Default for unsupported purposes
    return {'valid': True, 'customerName': '', 'cardNickname': '', 'error': ''}
```

### Example: REST API

```python
import urllib.request
import urllib.error
import json
import os

def lambda_handler(event, context):
    customer_id = event['customerId']
    purpose = event['collectionPurpose']
    captured = event['capturedValue']
    
    payload = json.dumps({
        'customerId': customer_id,
        'purpose': purpose,
        'captured': captured
    }).encode()
    
    req = urllib.request.Request(
        url=f"{os.environ['API_BASE_URL']}/verify",
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': os.environ['API_KEY']
        },
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return {
                'valid': data.get('verified', False),
                'customerName': data.get('name', ''),
                'cardNickname': data.get('nickname', ''),
                'error': '' if data.get('verified') else data.get('reason', 'Not verified')
            }
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"API returned {e.code}") from e
```

### Timeout Considerations

The validate Lambda invokes your `CustomerDataLambda` synchronously. The validate Lambda has a 15-second timeout. Allow at least 5 seconds for your Lambda to respond:

- Set your Lambda timeout to 5 seconds.
- Set database connection timeouts to 3 seconds.
- If your data source is slow, consider adding a caching layer (ElastiCache/DAX).

If your Lambda times out or throws an exception, the validate Lambda sets `dtmf_status = "validation_service_error"` and the call continues — it does not block the customer.

---

## 6. Multi-Purpose Flows

You can build a single contact flow that handles multiple capture types dynamically, driven by an IVR menu or a prior routing decision.

### Pattern: IVR Menu Selection

```
Inbound call → Main Flow
  ↓
Customer selects: "1 for card number, 2 for sort code, 3 for account number"
  ↓
Set contact attribute: collectionPurpose = "full_card_number" (or "sort_code", etc.)
  ↓
Transfer to flow: ARIA-DTMF-SecureCollection (sub-flow)
  ↓
(sub-flow handles all purposes automatically)
  ↓
Return to main flow with result
```

In the Connect flow editor:
1. Add a **Get customer input** block with digits 1, 2, 3 as options.
2. Add a **Set contact attributes** block for each branch:
   - Branch 1: set `collectionPurpose = "full_card_number"`
   - Branch 2: set `collectionPurpose = "sort_code"`
   - Branch 3: set `collectionPurpose = "account_number"`
3. Connect all branches to the same **Transfer to flow** block pointing at the DTMF sub-flow.

### Pattern: Agent-Driven Purpose

Agents can select the purpose from a dropdown in the CCP before clicking the trigger button. This requires a custom CCP widget that sets a contact attribute via the Connect Streams API:

```javascript
// In your custom CCP widget
const purposeDropdown = document.getElementById('purposeSelect');
const triggerButton = document.getElementById('collectButton');

triggerButton.addEventListener('click', () => {
  const purpose = purposeDropdown.value;
  
  connect.agent(agent => {
    agent.getContacts().forEach(contact => {
      // Set the purpose attribute before triggering the flow
      contact.updateContactAttributes({ collectionPurpose: purpose }, {
        success: () => {
          // Now trigger the DTMF collection via a quick connect or task
          console.log('Purpose set:', purpose);
        },
        failure: err => console.error('Failed to set purpose:', err)
      });
    });
  });
});
```

---

## 7. Adding BIN Records for Card Validation

The `aria-card-bins` DynamoDB table maps 6-digit BIN prefixes to card type information. Populate this table to enable card type identification and BIN-level validation.

### BIN Table Schema

```
bin_prefix (String, PK) | card_type | card_subtype | issuer | country | card_scheme
```

### Sources of BIN Data

| Source | Notes |
|---|---|
| Card network BIN files (Visa, Mastercard) | Available to card processors and acquirers under agreement |
| Commercial BIN databases | e.g. BINbase, Mastercard BIN Lookup API, binlist.net |
| Your card processor | Typically provides a BIN file covering their issued cards |
| Manual entry | Acceptable for small, known card portfolios |

### Bulk Loading

Use a Python script to batch-write records from a CSV:

```python
import boto3
import csv

dynamodb = boto3.resource('dynamodb', region_name='eu-west-2')
table = dynamodb.Table('aria-card-bins')

with open('bins.csv', newline='') as csvfile:
    reader = csv.DictReader(csvfile)
    with table.batch_writer() as batch:
        for row in reader:
            batch.put_item(Item={
                'bin_prefix':   row['bin'],
                'card_type':    row['card_type'].upper(),
                'card_subtype': row['card_subtype'].upper(),
                'issuer':       row['issuer'],
                'country':      row['country'],
                'card_scheme':  row.get('scheme', '')
            })
```

Expected CSV format:
```csv
bin,card_type,card_subtype,issuer,country,scheme
414900,VISA,DEBIT,Barclays UK,GB,VISA DEBIT
522000,MASTERCARD,CREDIT,HSBC UK,GB,MASTERCARD CREDIT
```

### Refresh Cadence

BIN data changes as banks issue new card ranges. Recommended:
- **Monthly refresh** for commercial deployments
- **Weekly refresh** if you process high card volumes and need high match rates
- A `bin_prefix` not found in the table is treated as an unknown BIN — validation continues but `card_type` is set to `"UNKNOWN"`

---

## 8. Security Hardening Options

The default deployment provides a secure baseline. The following options harden the deployment further for high-security environments.

### CORS Restriction to Specific Domain

By default, the API Gateway CORS policy allows the CloudFront domain. To restrict to your agent portal's domain instead:

1. Update the `ALLOWED_ORIGIN` environment variable on `aria-dtmf-status-proxy`:
   ```bash
   aws lambda update-function-configuration \
     --function-name aria-dtmf-status-proxy \
     --environment "Variables={ALLOWED_ORIGIN=https://agent-portal.example.com,...}"
   ```
2. Update the API Gateway CORS configuration to allow your portal domain.

### Lambda in VPC

See [Architecture — Network Topology — VPC Deployment Guidance](architecture.md#network-topology).

In summary:
1. Create a private subnet in your VPC.
2. Create a NAT Gateway in a public subnet for Lambda egress.
3. Create VPC Interface Endpoints for `secretsmanager`, `kms`, `dynamodb`, `execute-api`.
4. Update Lambda VPC configuration via CloudFormation parameters `VpcId`, `SubnetIds`, `SecurityGroupIds`.

### WAF on CloudFront

Add AWS WAF to the CloudFront distribution to protect the panel HTML assets:

```bash
aws wafv2 create-web-acl \
  --name dtmf-panel-waf \
  --scope CLOUDFRONT \
  --region us-east-1 \
  --default-action Allow={} \
  --rules '[
    {
      "Name": "AWSManagedRulesCommonRuleSet",
      "Priority": 1,
      "Statement": {
        "ManagedRuleGroupStatement": {
          "VendorName": "AWS",
          "Name": "AWSManagedRulesCommonRuleSet"
        }
      },
      "OverrideAction": {"None": {}},
      "VisibilityConfig": {
        "SampledRequestsEnabled": true,
        "CloudWatchMetricsEnabled": true,
        "MetricName": "CommonRuleSet"
      }
    }
  ]' \
  --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName=dtmf-panel-waf
```

Associate the ACL with the CloudFront distribution via the console.

### Private API Gateway

If your agents access the CCP from within a corporate VPN or AWS Direct Connect, you can convert the API Gateway from a regional/public endpoint to a **private API Gateway** with a VPC endpoint:

1. Create a VPC Interface Endpoint for `execute-api` in your agent-accessible VPC.
2. Change the API Gateway endpoint type to **Private** in the CloudFormation template.
3. Attach a resource policy that restricts access to the VPC endpoint.
4. Update the CloudFront origin to point to the VPC endpoint (requires additional CloudFront configuration).

This ensures the `/dtmf-status` and `/dtmf-active` endpoints are only accessible from within your corporate network — the agent panel cannot be accessed from the public internet.

### Secrets Manager Access Boundary

Add a resource-based policy to the private key secret to explicitly deny access from all principals except the decrypt Lambda role:

```bash
aws secretsmanager put-resource-policy \
  --secret-id arn:aws:secretsmanager:...:secret:aria/dtmf-private-key-... \
  --resource-policy '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "AWS": "arn:aws:iam::123456789012:role/aria-dtmf-decrypt-role"
        },
        "Action": "secretsmanager:GetSecretValue",
        "Resource": "*"
      },
      {
        "Effect": "Deny",
        "Principal": "*",
        "Action": "secretsmanager:GetSecretValue",
        "Resource": "*",
        "Condition": {
          "StringNotEquals": {
            "aws:PrincipalArn": "arn:aws:iam::123456789012:role/aria-dtmf-decrypt-role"
          }
        }
      }
    ]
  }'
```

This provides defence-in-depth: even if the Lambda's IAM role was misconfigured, no other principal could read the secret.
