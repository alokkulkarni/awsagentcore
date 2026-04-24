# Configuration Reference: Secure DTMF Capture for Amazon Connect

> **Product:** Secure DTMF Capture for Amazon Connect  
> **Version:** 1.0

---

## 1. CloudFormation Parameters

The following parameters are accepted by `marketplace/cloudformation/dtmf-secure-capture.yaml`.

| Parameter | Type | Default | Description | Example |
|---|---|---|---|---|
| `ConnectInstanceId` | String | *(required)* | Amazon Connect instance UUID | `f969d4b4-f716-4974-a325-bb7899f2f293` |
| `ConnectInstanceArn` | String | *(required)* | Full ARN of the Connect instance | `arn:aws:connect:eu-west-2:123456789012:instance/f969d4b4-...` |
| `ConnectKeyId` | String | *(required)* | Key ID from Connect Security Keys (Step 2 of deployment) | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| `PrivateKeySecretArn` | String | *(required)* | Secrets Manager ARN of the RSA private key PEM | `arn:aws:secretsmanager:eu-west-2:...:secret:aria/dtmf-private-key-AbCdEf` |
| `KmsKeyArn` | String | *(required)* | ARN of the KMS CMK that encrypts the secret and DynamoDB | `arn:aws:kms:eu-west-2:...:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `CustomerDataLambdaArn` | String | `""` (empty) | ARN of the buyer-provided ownership-check Lambda | `arn:aws:lambda:eu-west-2:123456789012:function:my-customer-data-fn` |
| `SessionTTLHours` | Number | `2` | DynamoDB session auto-expiry in hours | `2` |
| `EnableBinCheck` | String | `"true"` | Whether validate Lambda checks the `aria-card-bins` table | `"true"` or `"false"` |
| `SessionsTableName` | String | `"dtmf_active_sessions"` | DynamoDB table name for active sessions | `"dtmf_active_sessions"` |
| `BinsTableName` | String | `"aria-card-bins"` | DynamoDB table name for BIN lookup | `"aria-card-bins"` |
| `Environment` | String | `"prod"` | Environment tag applied to all resources | `"prod"`, `"staging"`, `"dev"` |
| `StackName` | String | `"dtmf-secure-capture"` | CloudFormation stack name | `"dtmf-secure-capture-prod"` |
| `SkipOwnershipIfUnauth` | String | `"true"` | Skip ownership check if customer is unauthenticated | `"true"` or `"false"` |
| `LambdaLogLevel` | String | `"INFO"` | Python logging level for all Lambdas | `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"` |

---

## 2. Amazon Connect Contact Attributes

Contact attributes are the primary mechanism for passing state between Lambda functions and the agent panel. All attributes are set on the active contact by Lambda and read by the status proxy.

### Full Attribute Reference

| Attribute | Set By | Read By | Possible Values | Notes |
|---|---|---|---|---|
| `collectionPurpose` | Agent / Connect flow (before invoking start-session) | `aria-dtmf-validate` | See [Collection Purpose Reference](#4-collection-purpose-reference) | Must be set before the flow invokes start-session Lambda |
| `customerId` | Contact flow (from previous auth step) | `aria-dtmf-validate` | Any string identifier | Required for ownership check; optional if `SkipOwnershipIfUnauth=true` |
| `authStatus` | Contact flow (from previous auth step) | `aria-dtmf-validate` | `"authenticated"` \| `"unauthenticated"` | If `"unauthenticated"` and `SkipOwnershipIfUnauth=true`, ownership check is skipped |
| `dtmf_status` | `aria-dtmf-start-session`, `aria-dtmf-validate` | `aria-dtmf-status-proxy`, agent panel | See status lifecycle below | Primary attribute polled by agent panel |
| `dtmf_masked_value` | `aria-dtmf-validate` | `aria-dtmf-status-proxy`, agent panel | e.g. `"****4567"`, `"***-**-1234"` | Safe to display; never contains full digits |
| `dtmf_card_bin` | `aria-dtmf-decrypt` | `aria-dtmf-validate` | e.g. `"414900"` | First 6 digits of card; not PCI-sensitive |
| `dtmf_last_four` | `aria-dtmf-decrypt` | `aria-dtmf-validate`, agent panel | e.g. `"4567"` | Last 4 digits only |
| `dtmf_digit_count` | `aria-dtmf-decrypt` | `aria-dtmf-validate` | e.g. `"16"` | Always a string (Connect attributes are strings) |
| `dtmf_failure_reason` | `aria-dtmf-validate` | `aria-dtmf-status-proxy`, agent panel | e.g. `"Luhn check failed"`, `"Card not on file"` | Only set when `dtmf_status = "failed"` |
| `dtmf_card_type` | `aria-dtmf-validate` | Agent panel | `"VISA"`, `"MASTERCARD"`, `"AMEX"`, `"MAESTRO"`, `"UNKNOWN"` | Set after BIN lookup; empty for non-card purposes |
| `dtmf_card_nickname` | `aria-dtmf-validate` | Agent panel | e.g. `"Everyday Debit"` | From customer Lambda if available; may be empty |

### `dtmf_status` Lifecycle

```
[not set] → awaiting_trigger → decrypting → validating → complete
                                                        ↘ failed
                                                        ↘ validation_service_error
```

| Status Value | Set By | Meaning |
|---|---|---|
| `awaiting_trigger` | `aria-dtmf-start-session` | Session started; waiting for customer to enter digits |
| `decrypting` | `aria-dtmf-decrypt` (at start of invocation) | Connect has captured digits; decryption in progress |
| `validating` | `aria-dtmf-validate` (at start of invocation) | Decryption succeeded; validation checks running |
| `complete` | `aria-dtmf-validate` (on success) | All checks passed; `dtmf_masked_value` is set |
| `failed` | `aria-dtmf-validate` (on validation failure) | A validation check failed; `dtmf_failure_reason` explains why |
| `validation_service_error` | `aria-dtmf-validate` (on infrastructure error) | Service error (DynamoDB, customer Lambda); call can continue via alternative verification |

---

## 3. Lambda Environment Variables

### `aria-dtmf-decrypt`

| Variable | Required | Description | Example |
|---|---|---|---|
| `PRIVATE_KEY_SECRET_ARN` | Yes | Secrets Manager ARN of the RSA private key | `arn:aws:secretsmanager:eu-west-2:...:secret:aria/dtmf-private-key-...` |
| `CONNECT_KEY_ID` | Yes | Default Connect Security Key ID (used if not passed in event parameters) | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| `AWS_REGION` | Auto | Set by Lambda runtime | `eu-west-2` |
| `LOG_LEVEL` | No | Python logging level | `INFO` |

### `aria-dtmf-validate`

| Variable | Required | Description | Example |
|---|---|---|---|
| `CONNECT_INSTANCE_ARN` | Yes | Full ARN of the Connect instance (for `UpdateContactAttributes`) | `arn:aws:connect:eu-west-2:...:instance/f969d4b4-...` |
| `BINS_TABLE_NAME` | Yes | DynamoDB BIN lookup table name | `aria-card-bins` |
| `ENABLE_BIN_CHECK` | No | `"true"` to enable BIN lookup; `"false"` to skip | `"true"` |
| `CUSTOMER_DATA_LAMBDA_ARN` | No | ARN of buyer ownership-check Lambda; empty to skip ownership check | `arn:aws:lambda:eu-west-2:...:function:my-fn` |
| `SKIP_OWNERSHIP_IF_UNAUTH` | No | Skip ownership check for unauthenticated contacts | `"true"` |
| `AWS_REGION` | Auto | Set by Lambda runtime | `eu-west-2` |
| `LOG_LEVEL` | No | Python logging level | `INFO` |

### `aria-dtmf-start-session`

| Variable | Required | Description | Example |
|---|---|---|---|
| `SESSIONS_TABLE_NAME` | Yes | DynamoDB sessions table name | `dtmf_active_sessions` |
| `CONNECT_INSTANCE_ARN` | Yes | Full ARN of the Connect instance | `arn:aws:connect:eu-west-2:...:instance/f969d4b4-...` |
| `SESSION_TTL_HOURS` | No | Session TTL in hours | `2` |
| `AWS_REGION` | Auto | Set by Lambda runtime | `eu-west-2` |
| `LOG_LEVEL` | No | Python logging level | `INFO` |

### `aria-dtmf-status-proxy`

| Variable | Required | Description | Example |
|---|---|---|---|
| `SESSIONS_TABLE_NAME` | Yes | DynamoDB sessions table name | `dtmf_active_sessions` |
| `CONNECT_INSTANCE_ARN` | Yes | Full ARN of the Connect instance | `arn:aws:connect:eu-west-2:...:instance/f969d4b4-...` |
| `ALLOWED_ORIGIN` | Yes | CORS allowed origin (CloudFront domain) | `https://d1bkzzc74letv0.cloudfront.net` |
| `AWS_REGION` | Auto | Set by Lambda runtime | `eu-west-2` |
| `LOG_LEVEL` | No | Python logging level | `INFO` |

---

## 4. Collection Purpose Reference

The `collectionPurpose` attribute controls which validation path the validate Lambda executes.

| Purpose | Validation Performed | Required Input | Masked Value Format | BIN Table Required | Ownership Check |
|---|---|---|---|---|---|
| `full_card_number` | Luhn algorithm + digit count (13–19) + BIN check + optional ownership | 13–19 digits | `****{lastFour}` e.g. `****4567` | Optional (recommended) | Optional |
| `card_last_four` | Digit count exactly 4 + optional ownership | 4 digits | `****{digits}` e.g. `****4567` | No | Optional |
| `ssn` | Digit count exactly 9 + structural format check | 9 digits | `***-**-{lastFour}` e.g. `***-**-1234` | No | No |
| `account_number` | Digit count 6–8 (UK bank account format) | 6–8 digits | `****{lastTwo}` e.g. `****78` | No | No |
| `sort_code` | Digit count exactly 6 | 6 digits | `{d1}{d2}-{d3}{d4}-{d5}{d6}` e.g. `20-47-89` | No | No |
| `cvv` | Digit count 3–4 | 3 or 4 digits | `***` or `****` | No | No |
| `pin` | Digit count 4–6 | 4–6 digits | `****` | No | No |
| `generic` | Digit count matches expected count (if provided) | Any digits | `****` (redacted) | No | No |

### Adding a New Purpose

See [Customisation Guide — Adding a New Collection Purpose](customisation-guide.md#2-adding-a-new-collection-purpose).

---

## 5. DynamoDB Schemas

### `dtmf_active_sessions`

Stores the single active capture session. At most one record exists at a time (key: `ACTIVE`).

| Attribute | Type | Key Type | Description | Example |
|---|---|---|---|---|
| `session_id` | String | Partition key | Always `"ACTIVE"` for the live session | `"ACTIVE"` |
| `contact_id` | String | — | Amazon Connect Contact ID | `"abc12345-def6-7890-ghij-klmnopqrstuv"` |
| `collection_purpose` | String | — | The purpose string | `"full_card_number"` |
| `status` | String | — | Current status | `"awaiting_trigger"` |
| `customer_id` | String | — | Customer identifier (if known) | `"CUST-001"` |
| `created_at` | String | — | ISO 8601 creation timestamp | `"2025-01-15T14:30:00Z"` |
| `ttl` | Number | — | Unix epoch timestamp for DynamoDB TTL | `1736953800` |

**Note:** A Global Secondary Index (GSI) on `contact_id` is created by the CloudFormation template for the status proxy to look up sessions by Contact ID efficiently.

### `aria-card-bins`

Stores BIN prefix to card type mappings. Read-only by Lambdas; written by operators during setup.

| Attribute | Type | Key Type | Description | Example |
|---|---|---|---|---|
| `bin_prefix` | String | Partition key | 6-digit BIN prefix | `"414900"` |
| `card_type` | String | — | Card network | `"VISA"` |
| `card_subtype` | String | — | Debit/Credit/Prepaid | `"DEBIT"` |
| `issuer` | String | — | Issuing bank name | `"Barclays UK"` |
| `country` | String | — | ISO 3166-1 alpha-2 country | `"GB"` |
| `card_scheme` | String | — | Additional scheme info | `"VISA DEBIT"` |

---

## 6. API Endpoints

Both endpoints are served by the `aria-dtmf-status-proxy` Lambda via API Gateway HTTP API.

### GET `/dtmf-status`

Returns the current DTMF capture status for a specific contact.

**Query Parameters:**

| Parameter | Required | Description |
|---|---|---|
| `contactId` | Yes | The Amazon Connect Contact ID |

**Request:**
```http
GET /dtmf-status?contactId=abc12345-def6-7890-ghij-klmnopqrstuv HTTP/1.1
Host: bz8frqf9f9.execute-api.eu-west-2.amazonaws.com
Origin: https://d1bkzzc74letv0.cloudfront.net
```

**Success Response (200):**
```json
{
  "status": "complete",
  "maskedValue": "****4567",
  "failureReason": "",
  "cardType": "VISA",
  "cardNickname": "Everyday Debit",
  "collectionPurpose": "full_card_number",
  "contactId": "abc12345-def6-7890-ghij-klmnopqrstuv"
}
```

**No-capture Response (200 — no active session for this contact):**
```json
{
  "status": "idle",
  "maskedValue": "",
  "failureReason": "",
  "cardType": "",
  "cardNickname": "",
  "collectionPurpose": "",
  "contactId": "abc12345-def6-7890-ghij-klmnopqrstuv"
}
```

**Error Response (400):**
```json
{
  "error": "contactId query parameter is required"
}
```

**Possible `status` values in response:** `idle`, `awaiting_trigger`, `decrypting`, `validating`, `complete`, `failed`, `validation_service_error`

---

### GET `/dtmf-active`

Returns the currently active DTMF capture session (if any). Used by the launcher iframe to detect when to open the panel.

**Request:**
```http
GET /dtmf-active HTTP/1.1
Host: bz8frqf9f9.execute-api.eu-west-2.amazonaws.com
Origin: https://d1bkzzc74letv0.cloudfront.net
```

**Active Session Response (200):**
```json
{
  "active": true,
  "contactId": "abc12345-def6-7890-ghij-klmnopqrstuv",
  "collectionPurpose": "full_card_number",
  "status": "awaiting_trigger",
  "createdAt": "2025-01-15T14:30:00Z"
}
```

**No Active Session Response (200):**
```json
{
  "active": false,
  "contactId": null,
  "collectionPurpose": null,
  "status": "idle",
  "createdAt": null
}
```

**CORS Headers (on all responses):**
```
Access-Control-Allow-Origin: https://<CloudFrontDomain>
Access-Control-Allow-Methods: GET
Access-Control-Allow-Headers: Content-Type
```

---

## 7. Customer Data Lambda Contract

If you provide a `CustomerDataLambdaArn`, the validate Lambda will invoke it to check card/data ownership. Your Lambda must accept the following event schema and return the specified response schema.

### Event Schema

Your Lambda receives a JSON event from the validate Lambda:

```json
{
  "customerId": "CUST-001",
  "collectionPurpose": "full_card_number",
  "capturedValue": {
    "lastFour": "4567",
    "bin": "414900"
  }
}
```

The `capturedValue` object varies by `collectionPurpose`:

| `collectionPurpose` | `capturedValue` fields |
|---|---|
| `full_card_number` | `{ "lastFour": "4567", "bin": "414900" }` |
| `card_last_four` | `{ "lastFour": "4567" }` |
| `ssn` | `{ "lastFour": "1234" }` (last 4 of SSN) |
| `account_number` | `{ "lastTwo": "78" }` (last 2 digits) |
| `sort_code` | `{ "digits": "204789" }` (full sort code — not sensitive) |
| `cvv` | *(not passed — ownership check does not apply)* |
| `pin` | *(not passed — ownership check does not apply)* |
| `generic` | `{ "digitCount": 6 }` (count only) |

### Required Response Schema

Your Lambda **must** return a JSON object with exactly these fields:

```json
{
  "valid": true,
  "customerName": "John Smith",
  "cardNickname": "Everyday Debit",
  "error": ""
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `valid` | Boolean | Yes | `true` if the captured data matches the customer's record |
| `customerName` | String | Yes | Customer display name (may be empty string) |
| `cardNickname` | String | No | Friendly name for the card (e.g. "Everyday Debit"); may be empty string |
| `error` | String | Yes | Error message if `valid` is `false`; empty string otherwise |

### Response Handling

| Your Response | Validate Lambda Action |
|---|---|
| `{ "valid": true, ... }` | Sets `dtmf_status = "complete"`, includes `cardNickname` in contact attributes |
| `{ "valid": false, "error": "Card not on file" }` | Sets `dtmf_status = "failed"`, `dtmf_failure_reason = "Card not on file"` |
| Lambda throws exception or times out | Sets `dtmf_status = "validation_service_error"` (fail-open; call continues) |

### Example Implementation Stubs

**DynamoDB-backed ownership check:**
```python
import boto3
import json

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('customer-cards')

def lambda_handler(event, context):
    customer_id = event['customerId']
    last_four = event['capturedValue'].get('lastFour', '')
    
    response = table.get_item(Key={'customerId': customer_id, 'cardLastFour': last_four})
    item = response.get('Item')
    
    if item:
        return {
            'valid': True,
            'customerName': item.get('customerName', ''),
            'cardNickname': item.get('nickname', ''),
            'error': ''
        }
    return {
        'valid': False,
        'customerName': '',
        'cardNickname': '',
        'error': f'Card ending {last_four} not found for customer {customer_id}'
    }
```

**REST API-backed ownership check:**
```python
import json
import urllib.request

def lambda_handler(event, context):
    customer_id = event['customerId']
    last_four = event['capturedValue'].get('lastFour', '')
    
    url = f"https://api.internal.example.com/customers/{customer_id}/cards/{last_four}/verify"
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer <token>'})
    
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return {
                'valid': data['verified'],
                'customerName': data.get('name', ''),
                'cardNickname': data.get('nickname', ''),
                'error': '' if data['verified'] else 'Card not verified'
            }
    except Exception as e:
        raise  # Let validate Lambda handle as service error
```
