# Amazon Connect Security Profiles for AI Agents — Complete Step-by-Step Guide

> **Who this is for:** Amazon Connect administrators who need to create security profiles that control who can create, edit, and use Connect AI Agents, AI Prompts, AI Guardrails, Flow Modules (as tools), and related components — applying the principle of least privilege so each team member can only access what they need.
>
> **Official references:**
> - [Security profile permissions list](https://docs.aws.amazon.com/connect/latest/adminguide/security-profile-list.html)
> - [Create a security profile](https://docs.aws.amazon.com/connect/latest/adminguide/create-security-profile.html)
> - [Default security profiles](https://docs.aws.amazon.com/connect/latest/adminguide/default-security-profiles.html)
> - [Security profile best practices](https://docs.aws.amazon.com/connect/latest/adminguide/security-profile-best-practices.html)
> - [Tag-based access control](https://docs.aws.amazon.com/connect/latest/adminguide/tag-based-access-control.html)
> - [Inherited permissions](https://docs.aws.amazon.com/connect/latest/adminguide/inherited-permissions.html)

---

## What is a Security Profile?

A **Security Profile** in Amazon Connect is a collection of permissions that you assign to users. It controls what a user can see and do in the Amazon Connect admin website — including whether they can create AI Agents, edit AI Prompts, manage flow modules, or access contact records.

Think of security profiles like IAM roles — you create profiles for roles (job functions), not for individuals, then assign users to one or more profiles.

**Default security profiles provided by Amazon Connect:**

| Profile | Purpose |
|---|---|
| `Admin` | Full access to almost all Amazon Connect features |
| `Agent` | Access to the Contact Control Panel (CCP) to handle contacts |
| `CallCenterManager` | User management, metrics, routing — no AI agent management |
| `QualityAnalyst` | Read-only access to metrics and recordings |

> **Important:** None of the default profiles are tailored for AI Agent development. You must create custom profiles for AI developers and guardrail managers.

---

## Key AI Agent Permissions

The following permission groups are relevant when working with ARIA and Connect AI features:

### AI Agents
| UI label | API name | What it allows |
|---|---|---|
| AI agents — View | `QConnectAIAgents.View` | Read the AI Agent configuration |
| AI agents — Create | `QConnectAIAgents.Create` | Create a new AI Agent |
| AI agents — Edit | `QConnectAIAgents.Edit` | Edit an existing AI Agent, add/remove tools |
| AI agents — Delete | `QConnectAIAgents.Delete` | Delete an AI Agent permanently |

### AI Prompts
| UI label | API name | What it allows |
|---|---|---|
| AI prompts — View | `QConnectAIPrompts.View` | Read the system prompt YAML |
| AI prompts — Create | `QConnectAIPrompts.Create` | Author a new AI prompt |
| AI prompts — Edit | `QConnectAIPrompts.Edit` | Modify the system prompt |
| AI prompts — Delete | `QConnectAIPrompts.Delete` | Delete a prompt permanently |

### AI Guardrails
| UI label | API name | What it allows |
|---|---|---|
| AI guardrails — View | `QConnectGuardrails.View` | Read guardrail rules |
| AI guardrails — Create | `QConnectGuardrails.Create` | Create blocking/filtering rules |
| AI guardrails — Edit | `QConnectGuardrails.Edit` | Modify guardrail rules |
| AI guardrails — Delete | `QConnectGuardrails.Delete` | Delete a guardrail |

### Flow Modules (as tools)
| UI label | API name | What it allows |
|---|---|---|
| Flow modules — View | `ContactFlowModules.View` | Read module flow diagrams |
| Flow modules — Create | `ContactFlowModules.Create` | Create new module tools |
| Flow modules — Edit | `ContactFlowModules.Edit` | Modify module logic |
| Flow modules — Publish | `ContactFlowModules.Publish` | Publish modules for use in AI Agents |
| Flow modules — Remove | `ContactFlowModules.Delete` | Delete modules permanently |

### Contact Flows
| UI label | API name | What it allows |
|---|---|---|
| Flows — View | `ContactFlows.View` | Read flow diagrams |
| Flows — Create | `ContactFlows.Create` | Create inbound and other flows |
| Flows — Edit | `ContactFlows.Edit` | Modify flow logic |
| Flows — Publish | `ContactFlows.Publish` | Make flows active |
| Flows — Remove | `ContactFlows.Delete` | Delete flows permanently |

### Queues and Routing (needed by flow module developers to reference queues)
| UI label | API name | What it allows |
|---|---|---|
| Queues — View | `Queues.View` | Browse available queues in flow designer |
| Routing profiles — View | `RoutingPolicies.View` | View routing profiles |
| Hours of operation — View | `HoursOfOperation.View` | Browse hours in flow designer |

---

## Part 1 — Plan Your Security Profile Strategy

Before creating profiles, map your team roles to the minimum permissions they require:

```
Team Role              Profiles Needed                          Key Permissions
─────────────────────────────────────────────────────────────────────────────────
AI Agent Designer      ARIA-AIAgent-Designer                    QConnectAIAgents (all)
                                                                 QConnectAIPrompts (all)
                                                                 QConnectGuardrails (all)
                                                                 ContactFlowModules.View
                                                                 ContactFlows.View

Flow Module Developer  ARIA-FlowModule-Developer                ContactFlowModules (all)
                                                                 ContactFlows.View
                                                                 Queues.View
                                                                 HoursOfOperation.View
                                                                 InvokeLambdaFunction.Access

Contact Flow Admin     ARIA-ContactFlow-Admin                   ContactFlows (all)
                                                                 ContactFlowModules (all)
                                                                 Queues.View
                                                                 PhoneNumbers.View
                                                                 HoursOfOperation.View

Compliance Reviewer    ARIA-Compliance-Reviewer (read-only)     QConnectAIAgents.View
                                                                 QConnectAIPrompts.View
                                                                 QConnectGuardrails.View
                                                                 ContactFlowModules.View
                                                                 ContactFlows.View

Agent (CCP access)     Agent (default)                          BasicAgentAccess
                                                                 TransferDestinations.View
```

> **Principle of least privilege:** Grant only the permissions needed for the job. Never assign the `Admin` profile to developers — create dedicated developer profiles with only what is needed.

---

## Part 2 — Create the AI Agent Designer Profile

This profile is for developers who design and maintain the ARIA AI Agent, AI Prompts, and AI Guardrails.

### Step 2.1 — Navigate to Security Profiles

1. Log in to the Amazon Connect admin website as an administrator.
2. In the left navigation menu, choose **Users** → **Security profiles**.
3. You will see the list of existing security profiles.
4. Click **Add security profile**.

### Step 2.2 — Fill in Profile Details

1. **Security profile name:** `ARIA-AIAgent-Designer`
2. **Description:** `Permits AI Agent, AI Prompt, and AI Guardrail creation and management for the ARIA banking agent project. Does not allow contact flow publishing or user management.`
3. Leave **Tags** empty for now (or add `Project:ARIA`, `Team:AIDesign`).

### Step 2.3 — Grant AI Agent Permissions

Scroll to the **AI Agents** permission group.

Under **Amazon Q in Connect**, check the following:

| Permission | Check? |
|---|---|
| AI agents — View | ✅ Yes |
| AI agents — Create | ✅ Yes |
| AI agents — Edit | ✅ Yes |
| AI agents — Delete | ⛔ No (only admins should delete) |

Under **AI Prompts**, check:

| Permission | Check? |
|---|---|
| AI prompts — View | ✅ Yes |
| AI prompts — Create | ✅ Yes |
| AI prompts — Edit | ✅ Yes |
| AI prompts — Delete | ⛔ No |

Under **AI Guardrails**, check:

| Permission | Check? |
|---|---|
| AI guardrails — View | ✅ Yes |
| AI guardrails — Create | ✅ Yes |
| AI guardrails — Edit | ✅ Yes |
| AI guardrails — Delete | ⛔ No |

### Step 2.4 — Grant Read-Only Flow Access

Scroll to the **Flows** permission group. Check:

| Permission | Check? |
|---|---|
| Flows — View | ✅ Yes |
| Flow modules — View | ✅ Yes |
| Flows — Create | ⛔ No |
| Flows — Edit | ⛔ No |
| Flows — Publish | ⛔ No |

> AI Agent designers need View-only on flows and modules to see which flow module tools are available when building the AI Agent. They should not be able to publish flows.

### Step 2.5 — Grant Queue and Hours View

Scroll to the **Routing** permission group:

| Permission | Check? |
|---|---|
| Queues — View | ✅ Yes |
| Hours of operation — View | ✅ Yes |
| Routing profiles — View | ✅ Yes |

### Step 2.6 — Do Not Grant These Permissions

Ensure the following are **NOT** checked for this profile:

- Users — Create / Edit / Delete / Edit permission
- Security profiles — Create / Edit / Delete
- Flows — Create / Edit / Publish / Remove
- Phone numbers — Claim / Edit / Release
- Access metrics / Real-time metrics (unless needed for testing)
- Contact search (unless needed for testing)

### Step 2.7 — Save the Profile

1. Click **Save** at the bottom of the page.
2. The profile `ARIA-AIAgent-Designer` is now available to assign to users.

---

## Part 3 — Create the Flow Module Developer Profile

This profile is for developers who build and maintain Flow Module Tools that ARIA can call.

### Step 3.1 — Create New Profile

1. Choose **Users** → **Security profiles** → **Add security profile**.
2. **Security profile name:** `ARIA-FlowModule-Developer`
3. **Description:** `Permits creation, editing, and publishing of Flow Modules as Tools for the ARIA AI Agent. Cannot manage the AI Agent itself or publish contact flows.`

### Step 3.2 — Grant Flow Module Permissions

Under **Flows** → **Flow modules**:

| Permission | Check? |
|---|---|
| Flow modules — View | ✅ Yes |
| Flow modules — Create | ✅ Yes |
| Flow modules — Edit | ✅ Yes |
| Flow modules — Publish | ✅ Yes |
| Flow modules — Remove | ⛔ No (only admins should delete) |

Under **Flows** → **Flows**:

| Permission | Check? |
|---|---|
| Flows — View | ✅ Yes (needed to reference flows in modules) |
| Flows — Create | ⛔ No |
| Flows — Edit | ⛔ No |
| Flows — Publish | ⛔ No |

### Step 3.3 — Grant Reference Resource View Permissions

Flow module developers need to be able to reference queues, hours of operation, and prompts from within their module designer.

Under **Routing**:

| Permission | Check? |
|---|---|
| Queues — View | ✅ Yes |
| Routing profiles — View | ✅ Yes |
| Hours of operation — View | ✅ Yes |
| Quick connects — View | ✅ Yes |

Under **Channels and flows** → **Prompts**:

| Permission | Check? |
|---|---|
| Prompts — View | ✅ Yes |

> **Note on inherited permissions:** When you grant `Queues — View`, users also inherit the ability to see all phone numbers and hours of operation in dropdown lists when they reference queues in the flow designer. This is expected and intentional behaviour. They **do not** inherit Edit access to these resources.

### Step 3.4 — Grant AI Agents View Permission

Flow module developers should be able to see the AI Agent to verify that their module tools have been wired up, but not edit it.

Under **Amazon Q in Connect** → **AI agents**:

| Permission | Check? |
|---|---|
| AI agents — View | ✅ Yes |
| AI agents — Edit | ⛔ No |
| AI agents — Create | ⛔ No |

### Step 3.5 — Save the Profile

Click **Save**.

---

## Part 4 — Create the Contact Flow Admin Profile

This profile is for contact centre admins who manage the full contact flow ecosystem, including inbound flows that reference ARIA.

### Step 4.1 — Create New Profile

1. **Security profile name:** `ARIA-ContactFlow-Admin`
2. **Description:** `Full management access to contact flows and flow modules. Can publish flows and modules. Cannot manage users or security profiles.`

### Step 4.2 — Grant Full Flow Permissions

Under **Flows**:

| Permission | Check? |
|---|---|
| Flows — View | ✅ Yes |
| Flows — Create | ✅ Yes |
| Flows — Edit | ✅ Yes |
| Flows — Publish | ✅ Yes |
| Flows — Remove | ✅ Yes |

Under **Flow modules**:

| Permission | Check? |
|---|---|
| Flow modules — View | ✅ Yes |
| Flow modules — Create | ✅ Yes |
| Flow modules — Edit | ✅ Yes |
| Flow modules — Publish | ✅ Yes |
| Flow modules — Remove | ✅ Yes |

### Step 4.3 — Grant Resource Management

| Permission group | Permissions to grant |
|---|---|
| Queues | View, Create, Edit, Enable/Disable |
| Routing profiles | View, Create, Edit |
| Hours of operation | View, Create, Edit |
| Quick connects | View, Create, Edit, Delete |
| Phone numbers | View, Edit |
| Prompts | View, Create, Edit, Delete |

### Step 4.4 — Grant AI Agent View (Read-Only)

| Permission | Check? |
|---|---|
| AI agents — View | ✅ Yes |
| AI prompts — View | ✅ Yes |
| AI guardrails — View | ✅ Yes |
| AI agents — Edit | ⛔ No (flow admin doesn't edit AI components) |

### Step 4.5 — Optional: Metrics

If flow admins need to validate their changes through metrics:

| Permission | Check? |
|---|---|
| Access metrics | ✅ Yes |
| Real-time metrics | ✅ Yes |
| Historical metrics | ✅ Yes |

### Step 4.6 — Save the Profile

Click **Save**.

---

## Part 5 — Create the Compliance Reviewer Profile (Read-Only)

This profile is for compliance, audit, or security officers who need to review AI Agent configurations, guardrails, and prompts without being able to modify them.

### Step 5.1 — Create New Profile

1. **Security profile name:** `ARIA-Compliance-Reviewer`
2. **Description:** `Read-only access to AI Agent configurations, guardrails, prompts, and contact flows for compliance review and audit purposes. No create, edit, or delete permissions.`

### Step 5.2 — Grant View-Only Permissions

Under **Amazon Q in Connect**:

| Permission | Check? |
|---|---|
| AI agents — View | ✅ Yes |
| AI prompts — View | ✅ Yes |
| AI guardrails — View | ✅ Yes |
| All Edit/Create/Delete | ⛔ No |

Under **Flows**:

| Permission | Check? |
|---|---|
| Flows — View | ✅ Yes |
| Flow modules — View | ✅ Yes |
| All Create/Edit/Publish/Remove | ⛔ No |

Under **Routing**:

| Permission | Check? |
|---|---|
| Queues — View | ✅ Yes |
| Routing profiles — View | ✅ Yes |
| Hours of operation — View | ✅ Yes |

Under **Analytics** (optional, for audit trails):

| Permission | Check? |
|---|---|
| Contact search — View | ✅ Yes |
| Contact Lens — conversational analytics — View | ✅ Yes |
| Contact Lens — post-contact summary — View | ✅ Yes |

### Step 5.3 — Save the Profile

Click **Save**.

---

## Part 6 — Assign Security Profiles to Users

### Step 6.1 — Navigate to Users

1. Choose **Users** → **User management**.
2. Find the user you want to assign a profile to.
3. Click their name to open their settings.

### Step 6.2 — Edit Security Profiles

1. In the user's settings, click **Edit**.
2. Scroll to the **Security profile** section.
3. Remove any over-permissive profiles (e.g., `Admin`, `CallCenterManager`).
4. Click **Add security profile** and select the appropriate profile.

| Team member role | Assign profile(s) |
|---|---|
| AI Prompt engineer | `ARIA-AIAgent-Designer` |
| Module tool developer | `ARIA-FlowModule-Developer` |
| Contact centre flow admin | `ARIA-ContactFlow-Admin` |
| Compliance / audit reviewer | `ARIA-Compliance-Reviewer` |
| Customer service agent | `Agent` (default) |
| Contact centre manager | `CallCenterManager` (default) + `ARIA-Compliance-Reviewer` |
| Full platform admin | `Admin` (limit to 2–3 named individuals) |

> **Rule:** A user can be assigned up to **3 security profiles that contain access control tags**. Users can have additional profiles without access control tags. The least restrictive combination of granted permissions applies across all their profiles.

### Step 6.3 — Save User Changes

Click **Save** on the user's settings page.

---

## Part 7 — Tag-Based Access Control for AI Agents

Tag-based access control allows you to restrict which specific AI Agents a user can edit, even within the same permission group. This is particularly useful in multi-team environments where you have several AI Agents (e.g., ARIA for banking, another agent for mortgages, a third for fraud).

### Step 7.1 — Tag Your AI Agent Resources

First, add resource tags to your AI Agent, AI Prompt, and AI Guardrail in the Connect console or via CLI.

**Tag the ARIA AI Agent:**

1. Navigate to **AI agent designer** → **AI agents** → `ARIA-Banking-Agent`.
2. Click **Manage tags**.
3. Add:
   - `Project` = `ARIA`
   - `Domain` = `Banking`
   - `Environment` = `Production`
4. Click **Save**.

**Tag the ARIA AI Prompt:**

1. Navigate to **AI agent designer** → **AI prompts** → `ARIA-Banking-Orchestration-Prompt`.
2. Add same tags: `Project=ARIA`, `Domain=Banking`.

**Tag the ARIA AI Guardrail:**

1. Navigate to **AI agent designer** → **AI guardrails** → `ARIA-Banking-Guardrail`.
2. Add same tags: `Project=ARIA`, `Domain=Banking`.

**Via CLI:**

```bash
# Tag the AI Agent
aws connect tag-resource \
  --resource-arn "arn:aws:connect:eu-west-2:395402194296:instance/<INSTANCE_ID>/ai-agent/<AGENT_ID>" \
  --tags '{"Project":"ARIA","Domain":"Banking","Environment":"Production"}' \
  --region eu-west-2

# Tag the AI Prompt
aws connect tag-resource \
  --resource-arn "arn:aws:connect:eu-west-2:395402194296:instance/<INSTANCE_ID>/ai-prompt/<PROMPT_ID>" \
  --tags '{"Project":"ARIA","Domain":"Banking"}' \
  --region eu-west-2
```

### Step 7.2 — Configure Access Control Tags on the Security Profile

Now, restrict the `ARIA-AIAgent-Designer` profile so it can only manage AI Agents tagged with `Project=ARIA`:

1. Navigate to **Users** → **Security profiles** → `ARIA-AIAgent-Designer`.
2. Click **Edit**.
3. Scroll to the **Access control tags** section at the bottom of the permissions page.
4. Click **Add access control tag**.
5. Select resource type: **AI agents**.
6. Enter:
   - **Tag key:** `Project`
   - **Tag value:** `ARIA`
7. Click **Add**.
8. Click **Save**.

**Result:** Users with the `ARIA-AIAgent-Designer` profile can now only see and edit AI Agents tagged `Project=ARIA`. Any AI Agents tagged `Project=Mortgage` or without the tag are invisible to them.

### Step 7.3 — Access Control Tag Limits

| Rule | Limit |
|---|---|
| Access control tags per security profile | Maximum **4** |
| Security profiles with access control tags per user | Maximum **3** |
| Multiple access control tags on one profile | **AND** logic — more restrictive |
| Multiple profiles with different access control tags | **OR** logic — less restrictive |

**Example — AND logic (more restrictive):**

If profile `ARIA-AIAgent-Designer` has:
- Tag 1: `Project=ARIA`
- Tag 2: `Environment=Production`

The user can only see AI Agents tagged with **both** `Project=ARIA` **AND** `Environment=Production`.

**Example — OR logic across profiles (less restrictive):**

If a user has two profiles:
- Profile 1 with tag `Environment=Production`
- Profile 2 with tag `Environment=Staging`

The user can see resources tagged with **either** `Production` **or** `Staging`.

### Step 7.4 — Disable Access to Resources Not Covered by Tags

According to AWS best practices, when you enable tag-based access control, you should disable access to pages that would show an unrestricted list of resources, overriding your tag restrictions. Explicitly **remove** these permissions from profiles that have access control tags:

| Module/Page | Permission to remove |
|---|---|
| Contact search | `ContactSearch.View` |
| Dashboards/metrics | `AccessMetrics` |
| Flows page | `ContactFlows.View` |
| Flow modules page | `ContactFlowModules.View` |
| Historical changes/Audit portal | `AccessMetrics` |
| Hours of operation | `HoursOfOperation.View` |
| Routing rules | `Rules.View` |

> **Rationale:** These pages sometimes list all resources without applying tag-based filters. A user with `QConnectAIAgents.View` + tag restriction `Project=ARIA` might still see all AI Agents if they navigate to a page that lists everything unfiltered. Removing access to those unrestricted pages prevents accidental exposure.

---

## Part 8 — Create and Manage Security Profiles via AWS CLI

For infrastructure-as-code and repeatable deployments, create security profiles via the AWS CLI.

### Step 8.1 — Create the AI Agent Designer Profile via CLI

```bash
aws connect create-security-profile \
  --instance-id "<YOUR_CONNECT_INSTANCE_ID>" \
  --security-profile-name "ARIA-AIAgent-Designer" \
  --description "AI Agent, Prompt, and Guardrail design permissions for ARIA project. Read-only on flows." \
  --permissions \
    "QConnectAIAgents.View" \
    "QConnectAIAgents.Create" \
    "QConnectAIAgents.Edit" \
    "QConnectAIPrompts.View" \
    "QConnectAIPrompts.Create" \
    "QConnectAIPrompts.Edit" \
    "QConnectGuardrails.View" \
    "QConnectGuardrails.Create" \
    "QConnectGuardrails.Edit" \
    "ContactFlowModules.View" \
    "ContactFlows.View" \
    "Queues.View" \
    "HoursOfOperation.View" \
    "RoutingPolicies.View" \
  --tags "Project=ARIA,ManagedBy=IAC" \
  --region eu-west-2
```

### Step 8.2 — Create the Flow Module Developer Profile via CLI

```bash
aws connect create-security-profile \
  --instance-id "<YOUR_CONNECT_INSTANCE_ID>" \
  --security-profile-name "ARIA-FlowModule-Developer" \
  --description "Flow Module tool creation and publishing for ARIA. View-only on AI Agent." \
  --permissions \
    "ContactFlowModules.View" \
    "ContactFlowModules.Create" \
    "ContactFlowModules.Edit" \
    "ContactFlowModules.Publish" \
    "ContactFlows.View" \
    "QConnectAIAgents.View" \
    "QConnectAIPrompts.View" \
    "Queues.View" \
    "HoursOfOperation.View" \
    "RoutingPolicies.View" \
    "TransferDestinations.View" \
    "Prompts.View" \
  --tags "Project=ARIA,ManagedBy=IAC" \
  --region eu-west-2
```

### Step 8.3 — Create the Compliance Reviewer Profile via CLI

```bash
aws connect create-security-profile \
  --instance-id "<YOUR_CONNECT_INSTANCE_ID>" \
  --security-profile-name "ARIA-Compliance-Reviewer" \
  --description "Read-only access to ARIA AI Agent configurations, guardrails, prompts, flows for audit." \
  --permissions \
    "QConnectAIAgents.View" \
    "QConnectAIPrompts.View" \
    "QConnectGuardrails.View" \
    "ContactFlowModules.View" \
    "ContactFlows.View" \
    "Queues.View" \
    "HoursOfOperation.View" \
    "RoutingPolicies.View" \
    "ContactSearch.View" \
    "GraphTrends.View" \
    "ContactLensPostContactSummary.View" \
  --tags "Project=ARIA,ManagedBy=IAC" \
  --region eu-west-2
```

### Step 8.4 — List All Security Profiles

```bash
aws connect list-security-profiles \
  --instance-id "<YOUR_CONNECT_INSTANCE_ID>" \
  --region eu-west-2 \
  --query "SecurityProfileSummaryList[*].{Name:Name,Id:Id}" \
  --output table
```

### Step 8.5 — Assign Security Profile to a User

```bash
# Get user ID by username
USER_ID=$(aws connect list-users \
  --instance-id "<YOUR_CONNECT_INSTANCE_ID>" \
  --region eu-west-2 \
  --query "UserSummaryList[?Username=='jsmith'].Id" \
  --output text)

# Get profile ID by name
PROFILE_ID=$(aws connect list-security-profiles \
  --instance-id "<YOUR_CONNECT_INSTANCE_ID>" \
  --region eu-west-2 \
  --query "SecurityProfileSummaryList[?Name=='ARIA-AIAgent-Designer'].Id" \
  --output text)

# Update user's security profiles
aws connect update-user-security-profiles \
  --instance-id "<YOUR_CONNECT_INSTANCE_ID>" \
  --user-id "$USER_ID" \
  --security-profile-ids "$PROFILE_ID" \
  --region eu-west-2
```

---

## Part 9 — Audit and Monitoring

### Step 9.1 — Enable AWS CloudTrail for Connect

AWS recommends using CloudTrail to track who makes changes to users and security profiles.

1. Open the **AWS CloudTrail** console.
2. Click **Create trail**.
3. **Trail name:** `aria-connect-audit-trail`
4. **Apply trail to all regions:** Yes
5. **Data events:** Add Amazon Connect as a data source.
6. **Management events:** Write events (covers CreateSecurityProfile, UpdateUserSecurityProfiles, DeleteSecurityProfile).
7. **S3 bucket:** Create `aria-connect-audit-logs-<account-id>`.
8. Click **Create trail**.

**Key API calls to monitor:**

| API call | What it means |
|---|---|
| `UpdateUserIdentityInfo` | User identity data changed — could be a credential takeover attempt |
| `UpdateUserSecurityProfiles` | A user was assigned different security profiles |
| `CreateSecurityProfile` | New security profile created |
| `DeleteSecurityProfile` | Security profile deleted |
| `UpdateSecurityProfile` | Permissions changed on an existing profile |
| `CreateAIAgent` | New AI Agent created |
| `UpdateAIAgent` | AI Agent configuration changed |
| `CreateAIPrompt` | New prompt created |
| `UpdateAIPrompt` | Prompt (ARIA's instructions) modified |

### Step 9.2 — Set Up CloudWatch Alarms for Critical Changes

Create CloudWatch alarms for high-risk events:

```bash
# Create alarm for ARIA AI Prompt changes (catches rogue prompt injections)
aws cloudwatch put-metric-alarm \
  --alarm-name "ARIA-AIPrompt-Modified" \
  --alarm-description "Alert when ARIA AI Prompt is created or updated" \
  --metric-name "CallCount" \
  --namespace "CloudTrailMetrics" \
  --statistic "Sum" \
  --period 300 \
  --threshold 1 \
  --comparison-operator "GreaterThanOrEqualToThreshold" \
  --evaluation-periods 1 \
  --alarm-actions "arn:aws:sns:eu-west-2:395402194296:aria-security-alerts" \
  --region eu-west-2
```

Create a CloudWatch Logs metric filter for the prompt change event:

```json
{
  "filterName": "ARIAPromptModified",
  "filterPattern": "{ ($.eventName = CreateAIPrompt) || ($.eventName = UpdateAIPrompt) }",
  "metricName": "CallCount",
  "metricNamespace": "CloudTrailMetrics",
  "metricValue": "1"
}
```

---

## Part 10 — Security Best Practices Summary

### 10.1 — Principle of Least Privilege

✅ **Do:** Grant only the permissions needed for the user's job function.  
✅ **Do:** Use the dedicated profiles created in this guide rather than the `Admin` default.  
✅ **Do:** Audit permission assignments quarterly.  
❌ **Don't:** Assign `Admin` to developers, analysts, or module builders.  
❌ **Don't:** Assign `Users — Edit or Create` to AI developers — they don't need user management.

### 10.2 — Protect User Management Permissions

The `Users — Edit` and `Users — Create` permissions are the highest-risk permissions in Connect:

- Someone with `Users — Edit` can reset any user's password, including the administrator.
- Someone with `Users — Edit permission` can grant themselves (or anyone) the `Admin` security profile.

**Best practice:** Assign `Users — Create` and `Users — Edit permission` to **no more than 2–3 named administrators**. All other profiles should explicitly exclude these.

### 10.3 — Protect AI Prompt Modifications

ARIA's system prompt (`ARIA-Banking-Orchestration-Prompt`) contains the instructions that determine ARIA's behaviour with customers. Treat this like application source code:

- Only `ARIA-AIAgent-Designer` profile holders should have `QConnectAIPrompts.Edit`.
- Use tag-based access control on the prompt resource so only those tagged with `Project=ARIA` can edit it.
- Monitor all `UpdateAIPrompt` API calls via CloudTrail (see Part 9).
- Consider requiring 2-person authorisation for prompt changes in production (one person edits, a second reviews before publishing the new version).

### 10.4 — Separate Development and Production Environments

If you have a development Connect instance and a production Connect instance:

1. Create the same security profiles in both instances.
2. AI designers have `Edit` on the **dev** instance but only `View` on the **prod** instance.
3. Promotion to production goes through a code review / change management process.
4. Add `Environment=Development` or `Environment=Production` tags to AI resources and use access control tags to enforce the separation.

### 10.5 — Tag All AI Resources

Immediately after creating any AI Agent, AI Prompt, AI Guardrail, or Flow Module, add resource tags:

| Tag key | Tag value | Purpose |
|---|---|---|
| `Project` | `ARIA` | Scopes access to ARIA-related resources |
| `Domain` | `Banking` | Subdivides by business domain |
| `Environment` | `Production` or `Development` | Separates prod/dev resources |
| `Owner` | `team-aria@yourbank.com` | Identifies responsible team |
| `CostCentre` | `CC-12345` | Cost allocation |

### 10.6 — Inherited Permissions Awareness

When you grant a permission, be aware of inherited permissions that come with it (from the AWS docs):

| You grant | User also inherits (view-only) |
|---|---|
| `Queues.View` or `.Edit` | All phone numbers, all hours of operation (in dropdown lists) |
| `Quick connects.View` | All queues, all flows, all users |
| `Quick connects.Edit` | All queues, all flows |
| `Phone numbers.View` or `.Edit` | All flows |
| `Users.View` or `.Edit` | All security profiles, routing profiles, agent hierarchies, agent proficiencies |

> **Implication for AI designers:** When you grant `Queues.View` so they can reference queues in the AI Prompt YAML, they also inherit visibility of all phone numbers and hours of operation. This is expected. They do **not** inherit Edit access to those resources.

### 10.7 — Review and Update Profiles Regularly

Amazon Connect regularly adds new features and new permissions. Permissions for features released **after** you created your profiles are **not automatically added** to your existing profiles.

**Schedule a quarterly review:**
1. Navigate to **Users** → **Security profiles**.
2. Compare existing profile permissions against the latest [security profile permissions list](https://docs.aws.amazon.com/connect/latest/adminguide/security-profile-list.html).
3. Determine whether newly added permissions (especially in AI agents, Q in Connect) are relevant to your roles.
4. Update profiles as needed.

---

## Appendix A — Quick Reference Permission Matrix

| Permission | AI Agent Designer | Flow Module Developer | Contact Flow Admin | Compliance Reviewer | Agent (CCP) |
|---|---|---|---|---|---|
| `QConnectAIAgents.View` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `QConnectAIAgents.Create` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `QConnectAIAgents.Edit` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `QConnectAIAgents.Delete` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `QConnectAIPrompts.View` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `QConnectAIPrompts.Create` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `QConnectAIPrompts.Edit` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `QConnectGuardrails.View` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `QConnectGuardrails.Create` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `QConnectGuardrails.Edit` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `ContactFlowModules.View` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `ContactFlowModules.Create` | ❌ | ✅ | ✅ | ❌ | ❌ |
| `ContactFlowModules.Edit` | ❌ | ✅ | ✅ | ❌ | ❌ |
| `ContactFlowModules.Publish` | ❌ | ✅ | ✅ | ❌ | ❌ |
| `ContactFlowModules.Delete` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `ContactFlows.View` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `ContactFlows.Create` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `ContactFlows.Edit` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `ContactFlows.Publish` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `ContactFlows.Delete` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `Queues.View` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `HoursOfOperation.View` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `RoutingPolicies.View` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `Users.Edit` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `SecurityProfiles.Edit` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `BasicAgentAccess` | ❌ | ❌ | ❌ | ❌ | ✅ |
| `ContactSearch.View` | ❌ | ❌ | ✅ | ✅ | ❌ |
| `AccessMetrics` | ❌ | ❌ | ✅ | ❌ | ❌ |

> ❌ for `Delete` permissions follows the recommendation that only administrators should be able to permanently delete AI resources, flow modules, and flows.

---

## Appendix B — Troubleshooting Common Permission Errors

### Error: "You don't have permission to access AI agents"

The user needs `QConnectAIAgents.View` in their security profile.

1. Navigate to **Users** → **User management** → click the user.
2. Check **Security profiles** — confirm `ARIA-AIAgent-Designer` (or equivalent) is assigned.
3. If missing, add the profile and ask the user to log out and log back in.

### Error: "You can't publish this flow module"

The user needs `ContactFlowModules.Publish`.

1. Check the user's security profile has `ContactFlowModules.Publish` checked.
2. Confirm the profile was saved **after** checking the Publish box — unsaved changes don't take effect.

### Error: AI Agent tool picker shows no flow modules

1. The module must be **published** (not just saved as draft) and enabled as a tool in the Settings tab.
2. The user adding the tool to the AI Agent needs `QConnectAIAgents.Edit`.
3. The user creating the module needs `ContactFlowModules.Publish`.
4. Wait 1–2 minutes after publishing for the module to propagate.

### Error: "Access denied" when viewing AI Prompt but profile has View permission

Tag-based access control may be blocking it.

1. Check whether the AI Prompt resource has tags.
2. Check the user's security profile for access control tags in the **Access control tags** section.
3. If the security profile requires `Project=ARIA` but the prompt is tagged `Project=Mortgages`, the user cannot see it by design.
4. Either add `Project=ARIA` to the prompt resource, or add a second security profile to the user that has the `Project=Mortgages` access control tag.
